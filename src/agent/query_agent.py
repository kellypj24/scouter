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
import time
from datetime import date
from typing import Any

import duckdb
import pandas as pd
import sqlglot
import sqlglot.errors
from pydantic import BaseModel
from sqlglot import exp

import hashlib as _hashlib

from src.agent.prompts.sql import SYSTEM, USER
from src.agent.providers.base import LLMError, LLMProvider
from src.data.context import get_few_shot_examples
from src.data.schema import SchemaContext, build_column_lookup, get_schema_prompt, load_schema_context
from src.models.response import QueryResult
from src.observability.logger import get_obs_logger

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

# Fundamental (income-statement / balance-sheet) metrics not present in the schema.
# Questions that match these should be rejected before calling the LLM.
_FUNDAMENTAL_PATTERN = re.compile(
    r"\b("
    r"earnings per share|eps"
    r"|p/?e ratio|price[- ]to[- ]earnings"
    r"|revenue|net income"
    r"|operating (?:income|margin|profit)"
    r"|ebitda|gross (?:profit|margin)"
    r"|net margin|book value"
    r"|free cash flow|cash flow from operations"
    r"|return on equity|return on assets|\broa\b|\broe\b"
    r"|dividend (?:yield|per share)"
    r")\b",
    re.IGNORECASE,
)
_DERIVABLE_SUFFIX = re.compile(r".*_\d+d$")  # e.g. vol_20d, ret_30d, ma_50d
_MART_RE = re.compile(r"\b(mart_\w+)\b", re.IGNORECASE)


def _extract_mart(sql: str) -> str | None:
    """Return the first mart_* table name found in a SQL string."""
    m = _MART_RE.search(sql)
    return m.group(1).lower() if m else None


def _sql_hash(sql: str) -> str:
    """Return a 12-char MD5 of normalised SQL for deduplication in pattern tracking."""
    normalized = re.sub(r"\s+", " ", sql.strip().lower())
    return _hashlib.md5(normalized.encode()).hexdigest()[:12]


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


def _clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Rename SQL-expression column names (e.g. avg("close")) to clean snake_case.

    DuckDB and sqlglot sometimes produce column names that look like raw SQL
    expressions when the LLM omits an alias. These break narrative agent chart
    selection because the column name doesn't match any schema field.
    """
    _expr_re = re.compile(r'^(\w+)\s*\(["\'`]?(\w+)["\'`]?\)$')

    def _clean(name: str) -> str:
        m = _expr_re.match(name.strip())
        if m:
            return f"{m.group(1)}_{m.group(2)}"
        return name

    cleaned = {col: _clean(col) for col in df.columns}
    if any(k != v for k, v in cleaned.items()):
        df = df.rename(columns=cleaned)
    return df


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

        Raises:
            ValueError: If the question asks for a fundamental metric not in the schema.
        """
        if _FUNDAMENTAL_PATTERN.search(question):
            raise ValueError(
                "This metric is not available in the dataset — no query was generated. "
                "The schema covers prices, returns, volatility, Sharpe ratio, drawdown, "
                "and sector aggregates. Income-statement metrics (EPS, revenue, margins, "
                "P/E, earnings) are not ingested."
            )

        domains = self.classify_domains(question)
        schema_prompt = get_schema_prompt(self._conn, domains=domains)

        sql: str | None = None
        last_error: str | None = None
        all_failures_schema = True  # flipped to False if any failure is an LLM error

        obs = get_obs_logger()
        for attempt, prompt_domains in enumerate([domains, None]):
            if attempt == 1:
                # Widen schema on retry — maybe classification was too narrow.
                schema_prompt = get_schema_prompt(self._conn, domains=prompt_domains)
            t_gen = time.perf_counter()
            try:
                sql = await self._generate_sql(question, schema_prompt, error_context=last_error)
                gen_ms = int((time.perf_counter() - t_gen) * 1000)
                await obs.log_span(
                    "sql_gen",
                    gen_ms,
                    success=True,
                    attempt=attempt + 1,
                    domain=",".join(domains) if domains else "all",
                    sql_length=len(sql),
                )
                break
            except LLMError as exc:
                gen_ms = int((time.perf_counter() - t_gen) * 1000)
                last_error = str(exc)
                all_failures_schema = False
                await obs.log_span(
                    "sql_gen",
                    gen_ms,
                    success=False,
                    attempt=attempt + 1,
                    error=last_error,
                    domain=",".join(domains) if domains else "all",
                )
                logger.warning("SQL generation attempt %d failed (LLM error): %s", attempt + 1, exc)
            except ValueError as exc:
                gen_ms = int((time.perf_counter() - t_gen) * 1000)
                last_error = str(exc)
                await obs.log_span(
                    "sql_gen",
                    gen_ms,
                    success=False,
                    attempt=attempt + 1,
                    error=last_error,
                    domain=",".join(domains) if domains else "all",
                )
                logger.warning("SQL generation attempt %d failed: %s", attempt + 1, exc)
                # Don't retry for definitively unanswerable errors — a retry would only
                # generate a wrong-domain substitution query.
                if attempt == 0 and (
                    re.search(r"Table '[\w.]+' not found in schema", last_error)
                    or "not available in the dataset" in last_error
                ):
                    break

        if sql is None:
            if all_failures_schema and last_error:
                # Table invented by LLM that doesn't exist → metric genuinely absent.
                if re.search(r"Table '[\w.]+' not found in schema", last_error):
                    raise ValueError(last_error)

                # LLM signalled the metric is unavailable (returned empty sql).
                if "not available in the dataset" in last_error:
                    raise ValueError(last_error)

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

        t_exec = time.perf_counter()
        result, df = self._execute(sql)
        exec_ms = int((time.perf_counter() - t_exec) * 1000)
        await obs.log_span("sql_exec", exec_ms, success=True, row_count=result.row_count)

        # Log a candidate pattern when a genuine LLM-generated query succeeds.
        # Worker-bee signal only — never self-promoting. Claude reviews mart_query_patterns
        # and promotes to learned_patterns.yaml after eval validation.
        if sql != _FALLBACK_SQL and result.row_count > 0:
            await obs.log_span(
                "query_pattern",
                0,
                success=True,
                domain=",".join(domains) if domains else "all",
                mart=_extract_mart(sql),
                sql_hash=_sql_hash(sql),
                row_count=result.row_count,
            )

        return result, df

    def _column_known_anywhere(self, col_name: str) -> bool:
        """Return True if col_name matches or is a clear prefix of any known column.

        Prefix matching handles common abbreviations: 'sharpe' → 'sharpe_20d',
        'volatility' → 'volatility_20d', so these aren't treated as truly absent.
        """
        lower = col_name.lower()
        return any(
            lower == c or c.startswith(lower + "_")
            for cols in self._column_lookup.values()
            for c in cols
        )

    def _missing_column_error(self, col_name: str, db: str, tbl_name: str) -> str:
        """Build an error string for a missing column, including a hint if the column
        exists in another table so the LLM can correct its table selection on retry."""
        available = ", ".join(sorted(self._column_lookup.get((db, tbl_name), set())))

        # Screener is a snapshot — date filters are never needed and always wrong.
        if col_name == "date" and "screener" in tbl_name:
            return (
                f"Column 'date' does not exist in {db}.{tbl_name}. "
                f"mart_equity_screener is a current snapshot — there is NO date column, NO "
                f"INTERVAL, and NO WHERE clause needed. Remove ALL WHERE conditions and "
                f"use ORDER BY to rank results. "
                f"Correct query: SELECT ticker, company_name, sector, ytd_return "
                f"FROM main_equity.mart_equity_screener ORDER BY ytd_return DESC LIMIT 10. "
                f"Available columns: {available}."
            )

        tables_with_col = [
            f"{d}.{t}" for (d, t), cols in self._column_lookup.items() if col_name in cols
        ]
        hint = f" It is available in: {', '.join(tables_with_col)}." if tables_with_col else ""

        # Suggest the correct full column name if a prefix match exists in the same table.
        tbl_cols = self._column_lookup.get((db, tbl_name), set())
        prefix_candidates = sorted(c for c in tbl_cols if c.startswith(col_name + "_"))
        if prefix_candidates:
            suggestion = (
                f" Replace '{col_name}' with '{prefix_candidates[0]}'. "
                f"Keep {db}.{tbl_name} as the table — it has this column."
            )
        else:
            suggestion = ""

        return (
            f"Column '{col_name}' does not exist in {db}.{tbl_name}.{hint}{suggestion} "
            f"Available columns in {tbl_name}: {available}."
        )

    def classify_domains(self, question: str) -> list[str] | None:
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
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"That query failed:\n\n{error_context}{derived_hint}\n\n"
                        "Fix the SQL and respond with JSON only:\n"
                        '{"sql": "<corrected SQL>", "explanation": "<one sentence>"}'
                    ),
                }
            )
        response: Any = await self._provider.complete_structured(
            messages,
            SQLResponse,
            model=getattr(self._provider, "sql_model", None),  # Ollama routes to codellama
        )
        sql_response = (
            response if isinstance(response, SQLResponse) else SQLResponse.model_validate(response)
        )
        if not sql_response.sql.strip():
            raise ValueError(
                "This metric is not available in the dataset — no query was generated."
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
        if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
            raise ValueError(f"Generated SQL is not a SELECT: {sql[:120]}")

        try:
            transpiled = sqlglot.transpile(sql, read="mysql", write="duckdb", pretty=False)
            if transpiled:
                sql = transpiled[0]
                logger.debug("sqlglot transpiled SQL: %s", sql[:200])
        except sqlglot.errors.SqlglotError as exc:
            logger.warning("sqlglot could not transpile SQL (using as-is): %s", exc)

        # Detect GROUP BY aggregate on performance without OVER — likely malformed moving average.
        # AVG(close) GROUP BY date loses the date column from results, breaking chart generation.
        if (
            re.search(r"\bGROUP\s+BY\b", sql, re.IGNORECASE)
            and re.search(r"\bAVG\s*\(", sql, re.IGNORECASE)
            and not re.search(r"\bOVER\s*\(", sql, re.IGNORECASE)
            and re.search(r"\bmart_equity_performance\b", sql, re.IGNORECASE)
        ):
            raise ValueError(
                "AVG() with GROUP BY on mart_equity_performance is a malformed moving average. "
                "Use a window function: AVG(close) OVER (PARTITION BY ticker ORDER BY date "
                "ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS ma_50d. "
                "Include ticker, date, and close in SELECT."
            )

        # Detect LIMIT on the outer mart_equity_performance query — it truncates the time series.
        # LIMIT is valid only inside CTEs (subqueries) for ranking/filtering tickers.
        if re.search(r"\bmart_equity_performance\b", sql, re.IGNORECASE) and re.search(
            r"\bLIMIT\s+\d+\s*$", sql.strip(), re.IGNORECASE
        ):
            raise ValueError(
                "Do not add LIMIT to the outer mart_equity_performance query — it truncates "
                "the time series. Remove LIMIT from the outer SELECT entirely. "
                "Only use LIMIT inside a CTE subquery to select which tickers to include. "
                "All table names MUST be fully qualified (schema.table). "
                "Example:\n"
                "  WITH top AS (\n"
                "    SELECT ticker FROM main_equity.mart_equity_screener\n"
                "    ORDER BY ytd_return DESC LIMIT 5\n"
                "  )\n"
                "  SELECT p.ticker, p.date, p.close, p.daily_return\n"
                "  FROM main_equity.mart_equity_performance p\n"
                "  JOIN top ON p.ticker = top.ticker\n"
                "  WHERE p.date >= CURRENT_DATE - INTERVAL '3 months'\n"
                "  ORDER BY p.date ASC, p.ticker"
            )

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

        # Screener-specific: catch unqualified `date` references even in multi-table queries
        # (e.g. WHERE date = (SELECT MAX(date) FROM dim_date) bypasses the single-table check).
        screener_in_query = any(
            "mart_equity_screener" in name for _, name in alias_to_table.values()
        )
        if screener_in_query:
            for col in statement.find_all(exp.Column):
                if col.name.lower() == "date" and not col.table:
                    errors.append(
                        self._missing_column_error("date", "main_equity", "mart_equity_screener")
                    )
                    break

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
        df = _clean_column_names(df)
        result = QueryResult(
            sql=sql,
            row_count=len(df),
            columns=list(df.columns),
        )
        logger.info("Query returned %d rows, %d columns", result.row_count, len(result.columns))
        return result, df
