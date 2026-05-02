"""Unit tests for src/agent/orchestrator.py."""

from unittest.mock import AsyncMock, MagicMock

import duckdb
import pandas as pd
import pytest

from src.agent.orchestrator import DecompositionResponse, Orchestrator, _error_block
from src.agent.providers.base import LLMError
from src.agent.query_agent import _FALLBACK_SQL
from src.models.agent import AgentRequest
from src.models.response import ChartSpec, NarrativeBlock, QueryResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_query_result(sql: str = "SELECT 1") -> QueryResult:
    return QueryResult(sql=sql, row_count=3, columns=["ticker", "ytd_return"])


def _make_block(question: str = "Q", sql: str = "SELECT 1") -> NarrativeBlock:
    return NarrativeBlock(
        question=question,
        query_result=_make_query_result(sql),
        data=pd.DataFrame({"ticker": ["AAPL"], "ytd_return": [0.15]}),
        chart_spec=ChartSpec(chart_type="bar", x_col="ticker", y_col="ytd_return", title="T"),
        prose="AAPL returned 15% YTD.",
        follow_ups=["What drove this?"],
    )


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.complete_structured = AsyncMock(
        return_value=DecompositionResponse(sub_questions=["Q1", "Q2"])
    )
    return provider


@pytest.fixture
def mock_query_agent():
    agent = MagicMock()
    agent.run = AsyncMock(
        return_value=(
            _make_query_result(),
            pd.DataFrame({"ticker": ["AAPL"], "ytd_return": [0.15]}),
        )
    )
    return agent


@pytest.fixture
def mock_narrative_agent():
    agent = MagicMock()
    agent.run = AsyncMock(return_value=_make_block())
    return agent


@pytest.fixture
def orchestrator(mock_provider, mock_query_agent, mock_narrative_agent):
    return Orchestrator(
        provider=mock_provider,
        query_agent=mock_query_agent,
        narrative_agent=mock_narrative_agent,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRun:
    async def test_returns_one_block_per_sub_question(self, orchestrator, mock_narrative_agent):
        request = AgentRequest(question="How are tech stocks doing?")
        response = await orchestrator.run(request)
        assert len(response.blocks) == 2
        assert mock_narrative_agent.run.call_count == 2

    async def test_block_questions_match_sub_questions(self, orchestrator, mock_narrative_agent):
        mock_narrative_agent.run = AsyncMock(side_effect=lambda q, qr, df: _make_block(question=q))
        request = AgentRequest(question="Compare sectors")
        response = await orchestrator.run(request)
        questions = [b.question for b in response.blocks]
        assert questions == ["Q1", "Q2"]

    async def test_fallback_used_false_when_no_fallback_sql(self, orchestrator):
        request = AgentRequest(question="Q")
        response = await orchestrator.run(request)
        assert response.fallback_used is False

    async def test_fallback_used_true_when_query_used_fallback_sql(
        self, orchestrator, mock_narrative_agent
    ):
        mock_narrative_agent.run = AsyncMock(return_value=_make_block(sql=_FALLBACK_SQL))
        request = AgentRequest(question="Q")
        response = await orchestrator.run(request)
        assert response.fallback_used is True

    async def test_max_blocks_respected(
        self, mock_provider, mock_query_agent, mock_narrative_agent
    ):
        mock_provider.complete_structured = AsyncMock(
            return_value=DecompositionResponse(sub_questions=["Q1", "Q2", "Q3", "Q4"])
        )
        orchestrator = Orchestrator(mock_provider, mock_query_agent, mock_narrative_agent)
        request = AgentRequest(question="Big complex question", max_blocks=2)
        response = await orchestrator.run(request)
        assert len(response.blocks) <= 2

    async def test_duckdb_error_produces_error_block(self, orchestrator, mock_query_agent):
        mock_query_agent.run = AsyncMock(side_effect=duckdb.Error("table not found"))
        request = AgentRequest(question="Q")
        response = await orchestrator.run(request)
        assert len(response.blocks) == 2
        assert all("could not be answered" in b.prose for b in response.blocks)

    async def test_partial_failure_returns_remaining_blocks(
        self, orchestrator, mock_query_agent, mock_narrative_agent
    ):
        # The orchestrator filters out zero-row blocks when multiple blocks exist,
        # so only the successful block (row_count > 0) is returned.
        mock_query_agent.run = AsyncMock(
            side_effect=[
                duckdb.Error("first fails"),
                (_make_query_result(), pd.DataFrame({"ticker": ["AAPL"], "ytd_return": [0.1]})),
            ]
        )
        request = AgentRequest(question="Q")
        response = await orchestrator.run(request)
        assert len(response.blocks) == 1
        assert response.blocks[0].prose == "AAPL returned 15% YTD."


class TestDecompose:
    async def test_returns_sub_questions(self, orchestrator):
        sub_qs = await orchestrator._decompose("Compare sectors", max_blocks=3)
        assert sub_qs == ["Q1", "Q2"]

    async def test_falls_back_to_original_on_llm_error(self, orchestrator, mock_provider):
        mock_provider.complete_structured = AsyncMock(side_effect=LLMError("timeout"))
        sub_qs = await orchestrator._decompose("What is AAPL doing?", max_blocks=3)
        assert sub_qs == ["What is AAPL doing?"]

    async def test_trims_to_max_blocks(self, orchestrator, mock_provider):
        mock_provider.complete_structured = AsyncMock(
            return_value=DecompositionResponse(sub_questions=["Q1", "Q2", "Q3", "Q4", "Q5"])
        )
        sub_qs = await orchestrator._decompose("Big question", max_blocks=2)
        assert len(sub_qs) == 2

    async def test_single_question_returned_as_is(self, orchestrator, mock_provider):
        mock_provider.complete_structured = AsyncMock(
            return_value=DecompositionResponse(sub_questions=["What is AAPL's YTD return?"])
        )
        sub_qs = await orchestrator._decompose("What is AAPL's YTD return?", max_blocks=3)
        assert sub_qs == ["What is AAPL's YTD return?"]


class TestErrorBlock:
    def test_has_helpful_prose(self):
        block = _error_block("What is sector rotation?", "table not found")
        assert "could not be answered" in block.prose

    def test_has_follow_ups(self):
        block = _error_block("Q", "error")
        assert len(block.follow_ups) > 0

    def test_empty_query_result(self):
        block = _error_block("Q", "error")
        assert block.query_result.row_count == 0
        assert block.chart_spec is None
