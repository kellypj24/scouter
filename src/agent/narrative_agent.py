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
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from src.agent.prompts.narrative import SYSTEM, USER
from src.agent.providers.base import LLMError, LLMProvider
from src.data.news import NewsItem
from src.models.response import ChartSpec, NarrativeBlock, QueryResult
from src.observability.logger import get_obs_logger

_NewsFetcher = Callable[[list[str]], Awaitable[list[NewsItem]]]

logger = logging.getLogger(__name__)

_VALID_CHART_TYPES = frozenset({"line", "bar", "scatter", "area", "histogram"})
_MAX_SAMPLE_ROWS = 5
_MAX_SAMPLE_COLS = 8

# Known date and categorical column names for chart inference.
_DATE_COLS = frozenset({"date", "price_date", "trade_date", "period_date", "as_of_date"})
_CAT_COLS = frozenset(
    {"ticker", "company_name", "sector", "industry", "gics_sector", "gics_sub_industry"}
)

# Preferred y-axis columns in priority order for auto-inference.
_PREFERRED_Y = (
    "close",
    "ytd_return",
    "sharpe_20d",
    "volatility_20d",
    "drawdown_from_52w_high",
    "avg_ytd_return_ew",
    "daily_return",
    "ma_50d",
    "avg_volatility_20d",
    "avg_sharpe_20d",
    "avg_drawdown_from_52w_high",
    "latest_close",
)


class NarrativeResponse(BaseModel):
    """Structured LLM output for narrative and chart generation."""

    chartable: bool
    chart_type: Literal["line", "bar", "scatter", "area", "histogram"] | None = None
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
        news_fetcher: Async callable that returns news headlines for a list of
            tickers. Pass None to disable news (e.g. in tests). The composition
            root (api/deps.py) wires in the real implementation.
    """

    def __init__(
        self,
        provider: LLMProvider,
        news_fetcher: _NewsFetcher | None = None,
    ) -> None:
        self._provider = provider
        self._news_fetcher = news_fetcher

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

        news_context = await self._build_news_context(data)

        obs = get_obs_logger()
        t_narr = time.perf_counter()
        try:
            response = await self._generate_narrative(question, query_result, data, news_context)
            block = self._assemble_block(question, query_result, data, response)
            narr_ms = int((time.perf_counter() - t_narr) * 1000)
            chart_source = (
                "llm"
                if block.chart_spec and response.chartable
                else "inferred"
                if block.chart_spec
                else "none"
            )
            await obs.log_span("narrative", narr_ms, success=True, chart_source=chart_source)
            return block
        except (LLMError, Exception) as exc:
            narr_ms = int((time.perf_counter() - t_narr) * 1000)
            await obs.log_span("narrative", narr_ms, success=False, error=str(exc))
            logger.warning("Narrative generation failed — using fallback: %s", exc)
            return _fallback_block(question, query_result, data)

    async def _build_news_context(self, data: pd.DataFrame) -> str:
        """Fetch and format news for tickers present in the result.

        Returns an empty string if news is disabled, no tickers are present,
        or the fetch fails for any reason.

        Args:
            data: Query result DataFrame.

        Returns:
            Formatted news context string, or "" if not applicable.
        """
        if self._news_fetcher is None:
            return ""
        tickers = _tickers_for_news(data)
        if not tickers:
            return ""
        obs = get_obs_logger()
        t_news = time.perf_counter()
        try:
            items = await self._news_fetcher(tickers)
            news_ms = int((time.perf_counter() - t_news) * 1000)
            await obs.log_span("news", news_ms, success=True, news_items=len(items))
            return _format_news_context(items)
        except Exception as exc:
            news_ms = int((time.perf_counter() - t_news) * 1000)
            await obs.log_span("news", news_ms, success=False, error=str(exc))
            logger.debug("News context skipped: %s", exc)
            return ""

    async def _generate_narrative(
        self,
        question: str,
        query_result: QueryResult,
        data: pd.DataFrame,
        news_context: str = "",
    ) -> NarrativeResponse:
        """Call the LLM and return a validated NarrativeResponse.

        Args:
            question: Natural language question.
            query_result: SQL metadata.
            data: Query result DataFrame.
            news_context: Formatted news headlines, or "" if unavailable.

        Returns:
            Validated NarrativeResponse.

        Raises:
            LLMError: If the provider call fails.
        """
        news_section = f"\n{news_context}\n" if news_context else ""
        news_hint = (
            " Since recent news is provided, include at least one follow-up that "
            "connects a news event to the quantitative data (e.g. 'Show price "
            "history since the earnings announcement')."
            if news_context
            else ""
        )
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
                    news_context=news_section,
                    news_followup_hint=news_hint,
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

        LLM column suggestions are validated against the actual DataFrame; any
        invalid or missing values are filled in by _infer_chart_spec so that
        a chart is produced whenever the data is chartable.

        Args:
            question: Original question.
            query_result: SQL metadata.
            data: Query result DataFrame.
            response: Validated LLM output.

        Returns:
            Assembled NarrativeBlock.
        """
        col_set = set(query_result.columns)
        numeric_cols = data.select_dtypes(include="number").columns.tolist()
        data_chartable = len(data) >= 3 and bool(numeric_cols)

        chart_spec: ChartSpec | None = None
        if response.chartable or data_chartable:
            preferred_x = response.x_col if response.x_col and response.x_col in col_set else None
            preferred_y = response.y_col if response.y_col and response.y_col in col_set else None
            preferred_color = (
                response.color_col if response.color_col and response.color_col in col_set else None
            )
            chart_spec = _infer_chart_spec(
                columns=query_result.columns,
                data=data,
                preferred_type=response.chart_type,
                preferred_x=preferred_x,
                preferred_y=preferred_y,
                preferred_color=preferred_color,
                title=response.title,
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

_MAX_NEWS_TICKERS = 5


def _tickers_for_news(data: pd.DataFrame) -> list[str]:
    """Return the tickers to fetch news for, or [] if news is not applicable.

    For screeners with many tickers, only the first few are used (they are
    already sorted by the primary metric, so these are the most prominent).
    """
    if "ticker" not in data.columns:
        return []
    unique: list[str] = data["ticker"].dropna().unique().tolist()
    return unique[:_MAX_NEWS_TICKERS]


def _format_news_context(items: list[NewsItem]) -> str:
    """Format a list of NewsItems into a compact prompt block."""
    if not items:
        return ""
    by_ticker: dict[str, list[NewsItem]] = {}
    for item in items:
        by_ticker.setdefault(item.ticker, []).append(item)

    lines = ["Recent news (last 7 days):"]
    for ticker, ticker_items in by_ticker.items():
        lines.append(f"\n{ticker}:")
        for item in ticker_items:
            date_str = item.published_at.strftime("%b %d")
            pub = f" [{item.publisher}, {date_str}]" if item.publisher else f" [{date_str}]"
            lines.append(f"  • {item.title}{pub}")
            if item.summary and item.summary.strip() != item.title.strip():
                lines.append(f"    {item.summary[:150]}")
    return "\n".join(lines)


def _infer_chart_spec(
    columns: list[str],
    data: pd.DataFrame,
    preferred_type: str | None,
    preferred_x: str | None,
    preferred_y: str | None,
    preferred_color: str | None,
    title: str,
) -> ChartSpec | None:
    """Build a ChartSpec, using LLM suggestions where valid and inferring the rest.

    When the LLM returns None or an invalid column name, this function derives
    sensible defaults from the DataFrame's structure (date columns → line chart;
    categorical columns → bar chart; multiple tickers → color by ticker).

    Args:
        columns: Column names from the query result.
        data: Query result DataFrame.
        preferred_type: LLM-suggested chart type (validated to be in _VALID_CHART_TYPES upstream).
        preferred_x: LLM-suggested x column (already confirmed to exist in data).
        preferred_y: LLM-suggested y column (already confirmed to exist in data).
        preferred_color: LLM-suggested color column (already confirmed to exist in data).
        title: Chart title from LLM.

    Returns:
        ChartSpec, or None if the data cannot be charted.
    """
    if len(data) < 3:
        return None

    col_set = set(columns)
    numeric_cols = data.select_dtypes(include="number").columns.tolist()
    numeric_set = set(numeric_cols)
    if not numeric_cols:
        return None

    date_cols = [c for c in columns if c.lower() in _DATE_COLS]
    cat_cols = [c for c in columns if c.lower() in _CAT_COLS]

    # Determine chart type: trust LLM if valid, infer from data shape otherwise.
    chart_type = preferred_type if preferred_type in _VALID_CHART_TYPES else None
    if chart_type is None:
        chart_type = "line" if date_cols else ("bar" if cat_cols else None)
    if chart_type is None:
        return None

    # Determine x_col.
    x_col = preferred_x
    if x_col is None:
        if chart_type == "line":
            x_col = date_cols[0] if date_cols else None
        else:
            # Prefer named categorical columns; fall back to first non-numeric column.
            x_col = (
                cat_cols[0]
                if cat_cols
                else next((c for c in columns if c not in numeric_set), None)
                or (columns[0] if columns else None)
            )

    # Determine y_col.
    y_col = preferred_y
    if y_col is None:
        for candidate in _PREFERRED_Y:
            if candidate in numeric_cols:
                y_col = candidate
                break
        if y_col is None:
            non_x = [c for c in numeric_cols if c != x_col]
            y_col = non_x[0] if non_x else (numeric_cols[0] if numeric_cols else None)

    if not x_col or not y_col:
        return None

    # Determine color_col.
    color_col = preferred_color
    if color_col is None and chart_type == "line" and "ticker" in col_set:
        try:
            if data["ticker"].nunique() > 1:
                color_col = "ticker"
        except Exception:
            pass
    elif color_col is None and chart_type == "bar":
        if "sector" in col_set and x_col != "sector":
            color_col = "sector"
        elif "industry" in col_set and x_col != "industry":
            color_col = "industry"

    return ChartSpec(
        chart_type=chart_type,
        x_col=x_col,
        y_col=y_col,
        title=title,
        color_col=color_col,
    )


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

    chart_spec = _infer_chart_spec(
        columns=query_result.columns,
        data=data,
        preferred_type=None,
        preferred_x=None,
        preferred_y=None,
        preferred_color=None,
        title="",
    )

    return NarrativeBlock(
        question=question,
        query_result=query_result,
        data=data,
        chart_spec=chart_spec,
        prose=" ".join(lines),
        follow_ups=[],
    )
