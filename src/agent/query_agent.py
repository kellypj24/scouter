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
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel

from src.agent.prompts.sql import SYSTEM, USER
from src.agent.providers.base import LLMError, LLMProvider
from src.data.schema import SchemaContext, load_schema_context
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
        for attempt, prompt_domains in enumerate([domains, None]):
            if attempt == 1:
                # Widen schema on retry — maybe classification was too narrow.
                schema_prompt = self._schema.to_prompt(domains=prompt_domains)
            try:
                sql = await self._generate_sql(question, schema_prompt)
                break
            except (LLMError, ValueError) as exc:
                logger.warning("SQL generation attempt %d failed: %s", attempt + 1, exc)

        if sql is None:
            logger.warning("Both LLM attempts failed — using rule-based fallback")
            sql = _FALLBACK_SQL

        return self._execute(sql)

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

    async def _generate_sql(self, question: str, schema_prompt: str) -> str:
        """Call the LLM and return a validated SQL string.

        Args:
            question: Natural language question.
            schema_prompt: Schema context string for injection.

        Returns:
            Validated SQL string.

        Raises:
            LLMError: If the provider call fails.
            ValueError: If the returned SQL fails validation.
        """
        messages = [
            {"role": "system", "content": SYSTEM.format(schema=schema_prompt)},
            {"role": "user", "content": USER.format(question=question)},
        ]
        response: Any = await self._provider.complete_structured(
            messages,
            SQLResponse,
            model=getattr(self._provider, "sql_model", None),  # Ollama routes to codellama
        )
        sql_response = (
            response if isinstance(response, SQLResponse) else SQLResponse.model_validate(response)
        )
        return self._validate_sql(sql_response.sql)

    def _validate_sql(self, sql: str) -> str:
        """Sanitize and validate SQL before execution.

        Args:
            sql: Raw SQL string from the LLM.

        Returns:
            Cleaned SQL string.

        Raises:
            ValueError: If the SQL contains blocked statements.
        """
        sql = sql.strip().rstrip(";")
        if _BLOCKED.search(sql):
            raise ValueError(f"Generated SQL contains blocked statement: {sql[:120]}")
        if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
            raise ValueError(f"Generated SQL is not a SELECT: {sql[:120]}")
        return sql

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
