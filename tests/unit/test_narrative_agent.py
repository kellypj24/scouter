"""Unit tests for src/agent/narrative_agent.py."""

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.agent.narrative_agent import (
    NarrativeAgent,
    NarrativeResponse,
    _data_sample,
    _empty_result_block,
    _fallback_block,
)
from src.agent.providers.base import LLMError
from src.models.response import QueryResult


@pytest.fixture
def query_result():
    return QueryResult(
        sql="SELECT ticker, sector, ytd_return FROM main_equity.mart_equity_screener LIMIT 5",
        row_count=5,
        columns=["ticker", "sector", "ytd_return"],
    )


@pytest.fixture
def data():
    return pd.DataFrame(
        {
            "ticker": ["NVDA", "META", "AAPL", "MSFT", "AMZN"],
            "sector": ["Tech", "Tech", "Tech", "Tech", "Consumer"],
            "ytd_return": [0.42, 0.31, 0.18, 0.15, 0.12],
        }
    )


@pytest.fixture
def mock_provider():
    return MagicMock()


@pytest.fixture
def agent(mock_provider):
    return NarrativeAgent(provider=mock_provider)


def _make_response(**kwargs) -> NarrativeResponse:
    defaults = dict(
        chartable=True,
        chart_type="bar",
        x_col="ticker",
        y_col="ytd_return",
        title="YTD Return by Ticker",
        color_col=None,
        prose="NVDA leads with a 42% YTD return, well ahead of peers.",
        follow_ups=["What drove NVDA's outperformance?", "How does this compare to last year?"],
    )
    defaults.update(kwargs)
    return NarrativeResponse(**defaults)


class TestRun:
    async def test_happy_path_returns_narrative_block(
        self, agent, mock_provider, query_result, data
    ):
        mock_provider.complete_structured = AsyncMock(return_value=_make_response())
        block = await agent.run("Top performing stocks?", query_result, data)
        assert block.prose == "NVDA leads with a 42% YTD return, well ahead of peers."
        assert block.chart_spec is not None
        assert block.chart_spec.chart_type == "bar"

    async def test_chart_spec_populated_correctly(self, agent, mock_provider, query_result, data):
        mock_provider.complete_structured = AsyncMock(
            return_value=_make_response(x_col="ticker", y_col="ytd_return", title="Returns")
        )
        block = await agent.run("Q", query_result, data)
        assert block.chart_spec.x_col == "ticker"
        assert block.chart_spec.y_col == "ytd_return"
        assert block.chart_spec.title == "Returns"

    async def test_not_chartable_omits_chart_spec(self, agent, mock_provider):
        # A single-row result (< 3 rows) is genuinely not chartable regardless of LLM signal.
        single_row_result = QueryResult(sql="SELECT 1", row_count=1, columns=["ytd_return"])
        single_row_data = pd.DataFrame({"ytd_return": [0.15]})
        mock_provider.complete_structured = AsyncMock(
            return_value=_make_response(chartable=False, prose="Single aggregate value returned.")
        )
        block = await agent.run("Q", single_row_result, single_row_data)
        assert block.chart_spec is None
        assert block.prose == "Single aggregate value returned."

    async def test_invalid_x_col_infers_valid_x_col(self, agent, mock_provider, query_result, data):
        # Invalid x_col is silently replaced by inference; chart is still produced.
        mock_provider.complete_structured = AsyncMock(
            return_value=_make_response(x_col="nonexistent_col")
        )
        block = await agent.run("Q", query_result, data)
        assert block.chart_spec is not None
        assert block.chart_spec.x_col in query_result.columns
        assert block.prose  # prose preserved

    async def test_invalid_y_col_infers_valid_y_col(self, agent, mock_provider, query_result, data):
        # Invalid y_col is replaced by inference; chart is still produced.
        mock_provider.complete_structured = AsyncMock(return_value=_make_response(y_col="bad_col"))
        block = await agent.run("Q", query_result, data)
        assert block.chart_spec is not None
        assert block.chart_spec.y_col in query_result.columns

    async def test_invalid_color_col_infers_color_col(
        self, agent, mock_provider, query_result, data
    ):
        # Invalid color_col is ignored; inference auto-picks "sector" for a bar chart.
        mock_provider.complete_structured = AsyncMock(
            return_value=_make_response(color_col="not_a_column")
        )
        block = await agent.run("Q", query_result, data)
        assert block.chart_spec is not None
        assert block.chart_spec.color_col == "sector"

    async def test_valid_color_col_propagated(self, agent, mock_provider, query_result, data):
        mock_provider.complete_structured = AsyncMock(
            return_value=_make_response(color_col="sector")
        )
        block = await agent.run("Q", query_result, data)
        assert block.chart_spec is not None
        assert block.chart_spec.color_col == "sector"

    async def test_no_chart_type_infers_from_data_structure(
        self, agent, mock_provider, query_result, data
    ):
        # When LLM omits chart_type, inference picks "bar" from categorical columns.
        mock_provider.complete_structured = AsyncMock(return_value=_make_response(chart_type=None))
        block = await agent.run("Q", query_result, data)
        assert block.chart_spec is not None
        assert block.chart_spec.chart_type in {"bar", "line", "scatter", "area", "histogram"}

    async def test_llm_error_uses_fallback(self, agent, mock_provider, query_result, data):
        # LLM failure produces a rule-based fallback with a chart inferred from the data.
        mock_provider.complete_structured = AsyncMock(side_effect=LLMError("timeout"))
        block = await agent.run("Top stocks?", query_result, data)
        assert block.chart_spec is not None
        assert "5 rows" in block.prose or "5 row" in block.prose

    async def test_empty_dataframe_returns_empty_block(self, agent, query_result):
        empty_df = pd.DataFrame(columns=["ticker", "sector", "ytd_return"])
        block = await agent.run("Q", query_result, empty_df)
        assert block.chart_spec is None
        assert "no results" in block.prose.lower()

    async def test_follow_ups_propagated(self, agent, mock_provider, query_result, data):
        mock_provider.complete_structured = AsyncMock(
            return_value=_make_response(follow_ups=["What drove NVDA?", "Compare to last year?"])
        )
        block = await agent.run("Q", query_result, data)
        assert len(block.follow_ups) == 2


class TestDataSample:
    def test_limits_rows(self):
        df = pd.DataFrame({"a": range(20), "b": range(20)})
        sample = _data_sample(df)
        # 5 data rows + 1 header = 6 lines
        assert len(sample.strip().splitlines()) == 6

    def test_limits_columns(self):
        df = pd.DataFrame({str(i): [1, 2] for i in range(15)})
        sample = _data_sample(df)
        # Only first 8 columns should appear
        header = sample.strip().splitlines()[0]
        assert "8" not in header  # column "8" through "14" truncated

    def test_small_df_unchanged(self):
        df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
        sample = _data_sample(df)
        assert "1" in sample and "2" in sample


class TestEmptyResultBlock:
    def test_has_helpful_prose(self):
        qr = QueryResult(sql="SELECT 1", row_count=0, columns=[])
        block = _empty_result_block("Q", qr, pd.DataFrame())
        assert "no results" in block.prose.lower()

    def test_has_follow_ups(self):
        qr = QueryResult(sql="SELECT 1", row_count=0, columns=[])
        block = _empty_result_block("Q", qr, pd.DataFrame())
        assert len(block.follow_ups) > 0


class TestFallbackBlock:
    def test_includes_row_count(self, query_result, data):
        block = _fallback_block("Top stocks?", query_result, data)
        assert "5" in block.prose

    def test_includes_numeric_summary(self, query_result, data):
        block = _fallback_block("Top stocks?", query_result, data)
        assert "ytd_return" in block.prose

    def test_includes_top_entries(self, query_result, data):
        block = _fallback_block("Top stocks?", query_result, data)
        assert "NVDA" in block.prose

    def test_singular_row_word(self, query_result):
        single_row_qr = QueryResult(sql="SELECT 1", row_count=1, columns=["x"])
        single_df = pd.DataFrame({"x": [42.0]})
        block = _fallback_block("Q", single_row_qr, single_df)
        assert "1 row" in block.prose
        assert "1 rows" not in block.prose

    def test_no_crash_on_all_text_columns(self):
        qr = QueryResult(sql="SELECT 1", row_count=2, columns=["name"])
        df = pd.DataFrame({"name": ["Alice", "Bob"]})
        block = _fallback_block("Q", qr, df)
        assert block.prose
