"""Narrative agent: query result → prose interpretation + chart specification.

Responsibilities:
  1. Summarise the DataFrame into a compact prompt-safe sample.
  2. Ask the LLM to choose a chart type and write interpretive prose.
  3. Validate all column references against the actual DataFrame.
  4. Assemble a complete NarrativeBlock (prose + optional ChartSpec).
  5. Fall back to a data-driven rule-based summary if the LLM fails.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from src.agent.prompts.narrative import SYSTEM, USER
from src.agent.providers.base import LLMError, LLMProvider
from src.models.response import ChartSpec, NarrativeBlock, QueryResult

logger = logging.getLogger(__name__)

_VALID_CHART_TYPES = frozenset({"line", "bar", "scatter", "area", "histogram"})
_MAX_SAMPLE_ROWS = 5
_MAX_SAMPLE_COLS = 8


class NarrativeResponse(BaseModel):
    """Structured LLM output for narrative and chart generation."""

    chartable: bool
    chart_type: str | None = None
    x_col: str | None = None
    y_col: str | None = None
    title: str = ""
    color_col: str | None = None
    prose: str
    follow_ups: list[str] = Field(default_factory=list)


class NarrativeAgent:
    """Interprets query results into prose and optional chart specifications.

    Args:
        provider: LLM provider (injected — never instantiated internally).
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def run(
        self,
        question: str,
        query_result: QueryResult,
        data: pd.DataFrame,
    ) -> NarrativeBlock:
        """Interpret a query result as human-readable prose and an optional chart.

        Args:
            question: The original natural language question.
            query_result: SQL metadata from DuckDB execution.
            data: Query result as a DataFrame.

        Returns:
            NarrativeBlock with prose, optional ChartSpec, and follow-up questions.
        """
        if data.empty:
            return _empty_result_block(question, query_result, data)

        try:
            response = await self._generate_narrative(question, query_result, data)
            return self._assemble_block(question, query_result, data, response)
        except (LLMError, Exception) as exc:
            logger.warning("Narrative generation failed — using fallback: %s", exc)
            return _fallback_block(question, query_result, data)

    async def _generate_narrative(
        self,
        question: str,
        query_result: QueryResult,
        data: pd.DataFrame,
    ) -> NarrativeResponse:
        """Call the LLM and return a validated NarrativeResponse.

        Args:
            question: Natural language question.
            query_result: SQL metadata.
            data: Query result DataFrame.

        Returns:
            Validated NarrativeResponse.

        Raises:
            LLMError: If the provider call fails.
        """
        messages = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": USER.format(
                    question=question,
                    sql=query_result.sql,
                    columns=", ".join(query_result.columns),
                    row_count=query_result.row_count,
                    sample=_data_sample(data),
                ),
            },
        ]
        raw: Any = await self._provider.complete_structured(messages, NarrativeResponse)
        if isinstance(raw, NarrativeResponse):
            return raw
        return NarrativeResponse.model_validate(raw)

    def _assemble_block(
        self,
        question: str,
        query_result: QueryResult,
        data: pd.DataFrame,
        response: NarrativeResponse,
    ) -> NarrativeBlock:
        """Build a NarrativeBlock from the LLM response.

        Column references are validated against the actual DataFrame — invalid
        columns drop the chart but preserve the prose.

        Args:
            question: Original question.
            query_result: SQL metadata.
            data: Query result DataFrame.
            response: Validated LLM output.

        Returns:
            Assembled NarrativeBlock.
        """
        chart_spec: ChartSpec | None = None

        if response.chartable and response.chart_type in _VALID_CHART_TYPES:
            col_set = set(query_result.columns)
            if response.x_col and response.y_col and response.x_col in col_set and response.y_col in col_set:
                color_col = (
                    response.color_col
                    if response.color_col and response.color_col in col_set
                    else None
                )
                chart_spec = ChartSpec(
                    chart_type=response.chart_type,
                    x_col=response.x_col,
                    y_col=response.y_col,
                    title=response.title,
                    color_col=color_col,
                )
            else:
                logger.warning(
                    "LLM returned columns not in result (x=%r y=%r) — dropping chart",
                    response.x_col,
                    response.y_col,
                )

        return NarrativeBlock(
            question=question,
            query_result=query_result,
            data=data,
            chart_spec=chart_spec,
            prose=response.prose,
            follow_ups=response.follow_ups,
        )


# ---------------------------------------------------------------------------
# Helpers (module-level so they're independently testable)
# ---------------------------------------------------------------------------


def _data_sample(df: pd.DataFrame) -> str:
    """Return a compact tabular string of the first few rows for prompt injection."""
    sample = df.head(_MAX_SAMPLE_ROWS)
    if len(sample.columns) > _MAX_SAMPLE_COLS:
        sample = sample.iloc[:, :_MAX_SAMPLE_COLS]
    return str(sample.to_string(index=False))


def _empty_result_block(
    question: str,
    query_result: QueryResult,
    data: pd.DataFrame,
) -> NarrativeBlock:
    """NarrativeBlock for queries that returned zero rows."""
    return NarrativeBlock(
        question=question,
        query_result=query_result,
        data=data,
        chart_spec=None,
        prose=(
            "The query returned no results. "
            "This may indicate no data matches the specified criteria, "
            "or the relevant data has not yet been ingested."
        ),
        follow_ups=[
            "Can you broaden the search criteria?",
            "Is there data available for a different time period?",
        ],
    )


def _fallback_block(
    question: str,
    query_result: QueryResult,
    data: pd.DataFrame,
) -> NarrativeBlock:
    """Rule-based NarrativeBlock used when the LLM is unavailable or fails.

    Produces a data-driven summary rather than a generic placeholder —
    numeric ranges, averages, and the top entries give the user actionable
    information even without LLM interpretation.
    """
    lines: list[str] = []

    row_word = "row" if query_result.row_count == 1 else "rows"
    lines.append(f'Returned {query_result.row_count} {row_word} for: "{question}".')

    numeric_cols = data.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        summaries = []
        for col in numeric_cols[:3]:
            col_data = data[col].dropna()
            if len(col_data):
                summaries.append(
                    f"{col} ranging {col_data.min():.2f}–{col_data.max():.2f} "
                    f"(avg {col_data.mean():.2f})"
                )
        if summaries:
            lines.append("Key metrics: " + "; ".join(summaries) + ".")

    text_cols = data.select_dtypes(include=["object", "string"]).columns.tolist()
    if text_cols:
        top = data[text_cols[0]].dropna().head(3).tolist()
        if top:
            lines.append(f"Top entries: {', '.join(str(v) for v in top)}.")

    return NarrativeBlock(
        question=question,
        query_result=query_result,
        data=data,
        chart_spec=None,
        prose=" ".join(lines),
        follow_ups=[],
    )
