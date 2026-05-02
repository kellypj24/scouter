"""Unit tests for api/main.py endpoints and api/deps.py."""

import json
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from api.deps import get_orchestrator
from api.main import app
from src.models.response import ChartSpec, NarrativeBlock, QueryResult


def _make_block(question: str = "Test question") -> NarrativeBlock:
    return NarrativeBlock(
        question=question,
        query_result=QueryResult(sql="SELECT 1", row_count=1, columns=["ticker"]),
        data=pd.DataFrame({"ticker": ["AAPL"], "ytd_return": [0.15]}),
        chart_spec=ChartSpec(chart_type="bar", x_col="ticker", y_col="ytd_return", title="Test"),
        prose="AAPL returned 15%.",
        follow_ups=["What about MSFT?"],
    )


def _mock_orchestrator(blocks: list[NarrativeBlock]) -> MagicMock:
    orch = MagicMock()

    async def fake_stream(request: object) -> AsyncGenerator[NarrativeBlock]:
        for block in blocks:
            yield block

    orch.stream = fake_stream
    return orch


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


class TestHealth:
    async def test_returns_200(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200

    async def test_returns_ok_status(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        assert response.json() == {"status": "ok"}


class TestAsk:
    async def test_returns_200_with_sse_content_type(self):
        app.dependency_overrides[get_orchestrator] = lambda: _mock_orchestrator([_make_block()])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ask", json={"question": "Test"})

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    async def test_emits_one_block_event_per_block(self):
        app.dependency_overrides[get_orchestrator] = lambda: _mock_orchestrator(
            [_make_block("Q1"), _make_block("Q2")]
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ask", json={"question": "Test"})

        event_lines = [line for line in response.text.splitlines() if line.startswith("event:")]
        assert event_lines.count("event: block") == 2

    async def test_done_event_terminates_stream(self):
        app.dependency_overrides[get_orchestrator] = lambda: _mock_orchestrator([_make_block()])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ask", json={"question": "Test"})

        event_lines = [line for line in response.text.splitlines() if line.startswith("event:")]
        assert "event: done" in event_lines
        assert event_lines[-1] == "event: done"

    async def test_block_data_line_is_valid_json(self):
        app.dependency_overrides[get_orchestrator] = lambda: _mock_orchestrator(
            [_make_block("Which stocks?")]
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ask", json={"question": "Test"})

        # The data line after "event: block" must be parseable JSON with the right question.
        lines = response.text.splitlines()
        block_idx = lines.index("event: block")
        payload = json.loads(lines[block_idx + 1].removeprefix("data: "))
        assert payload["question"] == "Which stocks?"

    async def test_empty_stream_emits_only_done_event(self):
        app.dependency_overrides[get_orchestrator] = lambda: _mock_orchestrator([])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ask", json={"question": "Test"})

        event_lines = [line for line in response.text.splitlines() if line.startswith("event:")]
        assert event_lines == ["event: done"]

    async def test_done_event_data_is_empty_object(self):
        app.dependency_overrides[get_orchestrator] = lambda: _mock_orchestrator([])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/ask", json={"question": "Test"})

        lines = response.text.splitlines()
        done_idx = lines.index("event: done")
        assert json.loads(lines[done_idx + 1].removeprefix("data: ")) == {}


class TestGetOrchestrator:
    def test_returns_orchestrator_instance(self):
        from src.agent.orchestrator import Orchestrator

        with (
            patch("api.deps.get_provider", return_value=MagicMock()),
            patch("api.deps.get_read_connection", return_value=MagicMock()),
        ):
            result = get_orchestrator()

        assert isinstance(result, Orchestrator)

    def test_provider_is_wired_into_orchestrator(self):
        sentinel = MagicMock()

        with (
            patch("api.deps.get_provider", return_value=sentinel),
            patch("api.deps.get_read_connection", return_value=MagicMock()),
        ):
            result = get_orchestrator()

        assert result._provider is sentinel
