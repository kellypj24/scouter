"""Query agent: natural language → validated SQL → DuckDB execution.

Responsibilities:
  1. Classify question domain to scope the schema injected into the prompt.
  2. Generate SQL via LLM (complete_structured → SQLResponse).
  3. Validate the SQL (SELECT-only, no DDL).
  4. Execute against DuckDB and return QueryResult + DataFrame.
  5. Fall back to a rule-based query if the LLM fails twice.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import duckdb
import pandas as pd
import sqlglot
import sqlglot.errors
from pydantic import BaseModel
from sqlglot import exp

from src.agent.prompts.sql import SYSTEM, USER
from src.agent.providers.base import LLMError, LLMProvider
from src.data.schema import SchemaContext, build_column_lookup, load_schema_context
from src.models.response import QueryResult

logger = logging.getLogger(__name__)

# DDL/DML keywords that must never appear in generated SQL.
_BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)

# Domain keyword map for lightweight question classification.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "sector": ["sector", "industry", "rotation", "gics"],
    "risk": ["risk", "drawdown", "volatility", "sharpe", "var", "beta"],
    "equity": [
        "stock",
        "ticker",
        "company",
        "return",
        "performance",
        "price",
        "high",
        "low",
        "momentum",
        "screener",
    ],
}

# Patterns that indicate a column is a derived/computed metric rather than a
# stored column — moving averages, exponential averages, RSI, rolling windows, etc.
_DERIVABLE_PREFIXES = ("ma_", "sma_", "ema_", "rsi_", "macd_", "bb_", "atr_", "obv_")
_DERIVABLE_SUFFIX = re.compile(r".*_\d+d$")  # e.g. vol_20d, ret_30d, ma_50d


def _is_derivable_metric(col_name: str) -> bool:
    """Return True if col_name looks like a computable derived metric."""
    lower = col_name.lower()
    return lower.startswith(_DERIVABLE_PREFIXES) or bool(_DERIVABLE_SUFFIX.match(lower))


# Fallback query when LLM fails — returns a useful default result.
_FALLBACK_SQL = (
    "SELECT ticker, company_name, sector, ytd_return, volatility_20d, sharpe_20d "
    "FROM main_equity.mart_equity_screener "
    "ORDER BY ytd_return DESC "
    "LIMIT 20"
)


class SQLResponse(BaseModel):
    """Structured LLM output for SQL generation."""

    sql: str
    explanation: str


class QueryAgent:
    """Generates and executes SQL from natural language questions.

    Args:
        provider: LLM provider (injected — never instantiated internally).
        conn: Active DuckDB connection (injected).
        schema_context: Pre-loaded schema context. Loaded from dbt artifacts if None.
    """

    def __init__(
        self,
        provider: LLMProvider,
        conn: duckdb.DuckDBPyConnection,
        schema_context: SchemaContext | None = None,
    ) -> None:
        self._provider = provider
        self._conn = conn
        self._schema = schema_context or load_schema_context(conn)
        self._column_lookup = build_column_lookup(self._schema)

    async def run(self, question: str) -> tuple[QueryResult, pd.DataFrame]:
        """Translate a question into SQL, execute it, and return results.

        Retries once with a truncated schema on LLM failure, then falls back
        to a rule-based query so the caller always gets a usable result.

        Args:
            question: Natural language question from the user.

        Returns:
            Tuple of (QueryResult metadata, DataFrame of results).
        """
        domains = self._classify_domains(question)
        schema_prompt = self._schema.to_prompt(domains=domains)

        sql: str | None = None
        last_error: str | None = None
        all_failures_schema = True  # flipped to False if any failure is an LLM error

        for attempt, prompt_domains in enumerate([domains, None]):
            if attempt == 1:
                # Widen schema on retry — maybe classification was too narrow.
                schema_prompt = self._schema.to_prompt(domains=prompt_domains)
            try:
                sql = await self._generate_sql(question, schema_prompt, error_context=last_error)
                break
            except LLMError as exc:
                last_error = str(exc)
                all_failures_schema = False
                logger.warning("SQL generation attempt %d failed (LLM error): %s", attempt + 1, exc)
            except ValueError as exc:
                last_error = str(exc)
                logger.warning("SQL generation attempt %d failed: %s", attempt + 1, exc)

        if sql is None:
            if all_failures_schema and last_error:
                # Check whether the failing column exists anywhere in the schema.
                # If it doesn't, the metric is genuinely absent → surface an informative
                # error rather than misleading screener data.
                # If it does, the LLM chose the wrong table — screener fallback is fine.
                col_match = re.search(r"Column '(\w+)' does not exist", last_error)
                if col_match and not self._column_known_anywhere(col_match.group(1)):
                    metric = col_match.group(1)
                    if not _is_derivable_metric(metric):
                        logger.info(
                            "METRIC_MISSING question=%r metric=%r — "
                            "consider adding to schema or upgrading model",
                            question,
                            metric,
                        )
                        raise ValueError(last_error)
                    # Derivable metric (e.g. moving average) — fall through to screener fallback.
            logger.warning("Both LLM attempts failed — using rule-based fallback")
            sql = _FALLBACK_SQL

        return self._execute(sql)

    def _column_known_anywhere(self, col_name: str) -> bool:
        """Return True if col_name exists in at least one table in the known schema."""
        return any(col_name.lower() in cols for cols in self._column_lookup.values())

    def _missing_column_error(self, col_name: str, db: str, tbl_name: str) -> str:
        """Build an error string for a missing column, including a hint if the column
        exists in another table so the LLM can correct its table selection on retry."""
        tables_with_col = [
            f"{d}.{t}"
            for (d, t), cols in self._column_lookup.items()
            if col_name in cols
        ]
        hint = f" It is available in: {', '.join(tables_with_col)}." if tables_with_col else ""
        available = ", ".join(sorted(self._column_lookup.get((db, tbl_name), set())))
        return (
            f"Column '{col_name}' does not exist in {db}.{tbl_name}.{hint} "
            f"Available columns in {tbl_name}: {available}."
        )

    def _classify_domains(self, question: str) -> list[str] | None:
        """Return relevant domain names based on question keywords.

        Returns None (= all domains) if no keywords match, so the LLM
        sees the full schema rather than an empty one.
        """
        q = question.lower()
        matched = [
            domain
            for domain, keywords in _DOMAIN_KEYWORDS.items()
            if any(kw in q for kw in keywords)
        ]
        # Always include core — dims and facts underpin every mart.
        if matched:
            matched = list(dict.fromkeys(["core"] + matched))
        return matched or None

    async def _generate_sql(
        self,
        question: str,
        schema_prompt: str,
        error_context: str | None = None,
    ) -> str:
        """Call the LLM and return a validated SQL string.

        On retry (error_context is set), appends the previous error as a
        correction turn so the LLM can fix the specific issue.

        Args:
            question: Natural language question.
            schema_prompt: Schema context string for injection.
            error_context: Error message from the previous attempt, if any.

        Returns:
            DuckDB-compatible, schema-validated SQL string.

        Raises:
            LLMError: If the provider call fails.
            ValueError: If validation or schema checks fail.
        """
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": SYSTEM.format(
                    schema=schema_prompt,
                    current_date=date.today().isoformat(),
                ),
            },
            {"role": "user", "content": USER.format(question=question)},
        ]
        if error_context:
            # If the error is about a derived metric, add an explicit window-function hint.
            derived_hint = ""
            col_match = re.search(r"Column '(\w+)' does not exist", error_context)
            if col_match and _is_derivable_metric(col_match.group(1)):
                derived_hint = (
                    f"\n\nHINT: '{col_match.group(1)}' is a derived metric, not a stored column. "
                    "Compute it with a SQL window function. Example for a 50-day moving average:\n"
                    "  AVG(close) OVER (\n"
                    "    PARTITION BY ticker ORDER BY date\n"
                    "    ROWS BETWEEN 49 PRECEDING AND CURRENT ROW\n"
                    "  ) AS ma_50d"
                )
            messages.append({"role": "assistant", "content": '{"sql": "...", "explanation": ""}'})
            messages.append({
                "role": "user",
                "content": (
                    f"That query failed:\n\n{error_context}{derived_hint}\n\n"
                    "Fix the SQL and respond with JSON only:\n"
                    '{"sql": "<corrected SQL>", "explanation": "<one sentence>"}'
                ),
            })
        response: Any = await self._provider.complete_structured(
            messages,
            SQLResponse,
            model=getattr(self._provider, "sql_model", None),  # Ollama routes to codellama
        )
        sql_response = (
            response if isinstance(response, SQLResponse) else SQLResponse.model_validate(response)
        )
        sql = self._validate_sql(sql_response.sql)
        errors = self._validate_schema(sql)
        if errors:
            raise ValueError("\n".join(errors))
        return sql

    def _validate_sql(self, sql: str) -> str:
        """Sanitize, transpile, and validate SQL before execution.

        Transpiles via sqlglot (MySQL/generic → DuckDB) to fix LLM-generated
        dialect mismatches (e.g. DATE_SUB, INTERVAL N MONTH). Then checks for
        blocked DDL/DML statements.

        Args:
            sql: Raw SQL string from the LLM.

        Returns:
            DuckDB-compatible SQL string.

        Raises:
            ValueError: If the SQL contains blocked statements or fails to parse.
        """
        sql = sql.strip().rstrip(";")
        if _BLOCKED.search(sql):
            raise ValueError(f"Generated SQL contains blocked statement: {sql[:120]}")
        if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
            raise ValueError(f"Generated SQL is not a SELECT: {sql[:120]}")

        try:
            transpiled = sqlglot.transpile(sql, read="mysql", write="duckdb", pretty=False)
            if transpiled:
                sql = transpiled[0]
                logger.debug("sqlglot transpiled SQL: %s", sql[:200])
        except sqlglot.errors.SqlglotError as exc:
            logger.warning("sqlglot could not transpile SQL (using as-is): %s", exc)

        return sql

    def _validate_schema(self, sql: str) -> list[str]:
        """Check SQL table and column references against the known schema.

        Parses the SQL AST via sqlglot and verifies that:
        - Fully-qualified tables (schema.table) exist in the schema.
        - Columns qualified with a resolvable table alias exist in that table.
        - Unqualified columns in simple single-table queries (no CTEs) exist in
          that table.

        Conservative: skips checks it cannot resolve without false positives
        (multi-table unqualified columns, CTE aliases). Unparseable SQL returns
        an empty list so execution can attempt it and fail naturally.

        Args:
            sql: Transpiled, DDL-validated SQL string.

        Returns:
            List of human-readable error strings; empty means validation passed.
        """
        try:
            statement = sqlglot.parse_one(sql, dialect="duckdb")
        except sqlglot.errors.SqlglotError:
            return []

        # CTE names are valid table references not in our schema — exclude them.
        cte_names: set[str] = {
            cte.alias.lower() for cte in statement.find_all(exp.CTE) if cte.alias
        }
        has_ctes = bool(cte_names)

        # Build alias → (duckdb_schema, table_name) for every FROM/JOIN table.
        alias_to_table: dict[str, tuple[str, str]] = {}
        for tbl in statement.find_all(exp.Table):
            if tbl.name.lower() in cte_names:
                continue
            db = (tbl.db or "").lower()
            name = tbl.name.lower()
            alias = (tbl.alias or tbl.name).lower()
            alias_to_table[alias] = (db, name)
            if tbl.alias:
                alias_to_table[name] = (db, name)

        errors: list[str] = []

        # Check fully-qualified tables exist.
        seen: set[tuple[str, str]] = set()
        for db, name in alias_to_table.values():
            key = (db, name)
            if db and key not in seen and key not in self._column_lookup:
                errors.append(f"Table '{db}.{name}' not found in schema.")
            seen.add(key)

        # Check column references.
        for col in statement.find_all(exp.Column):
            col_name = col.name.lower()
            qualifier = (col.table or "").lower()

            if qualifier and qualifier in alias_to_table:
                db, tbl_name = alias_to_table[qualifier]
                key = (db, tbl_name)
                if key in self._column_lookup and col_name not in self._column_lookup[key]:
                    errors.append(self._missing_column_error(col_name, db, tbl_name))
            elif not qualifier and not has_ctes and len(alias_to_table) == 1:
                (db, tbl_name) = next(iter(alias_to_table.values()))
                key = (db, tbl_name)
                if key in self._column_lookup and col_name not in self._column_lookup[key]:
                    errors.append(self._missing_column_error(col_name, db, tbl_name))

        return errors

    def _execute(self, sql: str) -> tuple[QueryResult, pd.DataFrame]:
        """Execute SQL against DuckDB and return structured results.

        Args:
            sql: Validated SQL string.

        Returns:
            Tuple of (QueryResult, DataFrame).

        Raises:
            duckdb.Error: If the query fails at the database level.
        """
        relation = self._conn.execute(sql)
        df = relation.df()
        result = QueryResult(
            sql=sql,
            row_count=len(df),
            columns=list(df.columns),
        )
        logger.info("Query returned %d rows, %d columns", result.row_count, len(result.columns))
        return result, df
