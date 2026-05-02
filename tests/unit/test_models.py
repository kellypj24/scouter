"""Unit tests for src/models/response.py and src/models/agent.py."""

import pandas as pd

from src.models.agent import AgentRequest, AgentResponse
from src.models.response import ChartSpec, NarrativeBlock, QueryResult


class TestQueryResult:
    def test_basic(self):
        qr = QueryResult(sql="SELECT 1", row_count=5, columns=["a", "b"])
        assert qr.sql == "SELECT 1"
        assert qr.row_count == 5
        assert qr.columns == ["a", "b"]

    def test_empty_columns(self):
        qr = QueryResult(sql="SELECT 1", row_count=0, columns=[])
        assert qr.columns == []


class TestChartSpec:
    def test_defaults(self):
        cs = ChartSpec(chart_type="line", x_col="date", y_col="price", title="Price")
        assert cs.color_col is None
        assert cs.annotations == []

    def test_list_y_col(self):
        cs = ChartSpec(
            chart_type="bar",
            x_col="sector",
            y_col=["return", "vol"],
            title="Sector",
        )
        assert cs.y_col == ["return", "vol"]

    def test_with_all_options(self):
        cs = ChartSpec(
            chart_type="scatter",
            x_col="x",
            y_col="y",
            title="T",
            color_col="group",
            annotations=[{"x": 1, "y": 2, "text": "hi"}],
        )
        assert cs.color_col == "group"
        assert len(cs.annotations) == 1


class TestNarrativeBlock:
    def _make_qr(self) -> QueryResult:
        return QueryResult(sql="SELECT 1", row_count=1, columns=["x"])

    def test_minimal(self):
        nb = NarrativeBlock(
            question="What?",
            query_result=self._make_qr(),
            data=pd.DataFrame({"x": [1]}),
            prose="It is one.",
        )
        assert nb.chart_spec is None
        assert nb.follow_ups == []

    def test_with_chart_and_follow_ups(self):
        cs = ChartSpec(chart_type="line", x_col="x", y_col="x", title="T")
        nb = NarrativeBlock(
            question="How?",
            query_result=self._make_qr(),
            data=pd.DataFrame({"x": [1]}),
            chart_spec=cs,
            prose="It trends.",
            follow_ups=["Next?", "Also?"],
        )
        assert nb.chart_spec is not None
        assert nb.follow_ups == ["Next?", "Also?"]


class TestAgentRequest:
    def test_defaults(self):
        req = AgentRequest(question="What is AAPL?")
        assert req.conversation_id is None
        assert req.max_blocks == 2

    def test_explicit_values(self):
        req = AgentRequest(question="Q", conversation_id="session-1", max_blocks=5)
        assert req.conversation_id == "session-1"
        assert req.max_blocks == 5


class TestAgentResponse:
    def test_empty_no_fallback(self):
        resp = AgentResponse(blocks=[])
        assert resp.fallback_used is False
        assert resp.blocks == []

    def test_fallback_flag(self):
        resp = AgentResponse(blocks=[], fallback_used=True)
        assert resp.fallback_used is True
