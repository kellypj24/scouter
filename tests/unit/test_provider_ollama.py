"""Unit tests for src/agent/providers/ollama.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from src.agent.providers.base import (
    LLMConnectionError,
    LLMError,
    LLMValidationError,
)
from src.agent.providers.ollama import OllamaProvider


class _Schema(BaseModel):
    answer: str
    confidence: float = 1.0


@pytest.fixture
def provider():
    return OllamaProvider(host="http://localhost:11434", model="llama3.2", sql_model="codellama")


def _mock_session(response_data: dict) -> MagicMock:
    """Build a mock aiohttp session that returns response_data on POST."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.closed = False
    return mock_session


class TestInit:
    def test_defaults_from_env(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_SQL_MODEL", raising=False)
        p = OllamaProvider()
        assert p.host == "http://localhost:11434"
        assert p.model == "qwen2.5:3b"
        assert p.sql_model == "qwen2.5-coder:3b"

    def test_explicit_values(self):
        p = OllamaProvider(host="http://custom:11434", model="mistral", sql_model="phi3")
        assert p.host == "http://custom:11434"
        assert p.model == "mistral"
        assert p.sql_model == "phi3"

    def test_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "gemma")
        p = OllamaProvider()
        assert p.model == "gemma"


class TestGetSession:
    async def test_creates_session(self, provider):
        with patch("aiohttp.TCPConnector"), patch("aiohttp.ClientSession") as mock_sess:
            mock_sess.return_value.closed = False
            await provider._get_session()
            mock_sess.assert_called_once()

    async def test_reuses_open_session(self, provider):
        mock_session = MagicMock()
        mock_session.closed = False
        provider._session = mock_session
        result = await provider._get_session()
        assert result is mock_session


class TestClose:
    async def test_closes_open_session(self, provider):
        mock_session = AsyncMock()
        mock_session.closed = False
        provider._session = mock_session
        await provider.close()
        mock_session.close.assert_called_once()

    async def test_no_op_when_no_session(self, provider):
        await provider.close()  # should not raise


class TestComplete:
    async def test_returns_text(self, provider):
        mock_session = _mock_session({"message": {"content": "Paris"}})
        provider._session = mock_session
        result = await provider.complete([{"role": "user", "content": "Capital of France?"}])
        assert result == "Paris"

    async def test_uses_model_kwarg(self, provider):
        mock_session = _mock_session({"message": {"content": "ok"}})
        provider._session = mock_session
        await provider.complete([{"role": "user", "content": "Q"}], model="custom-model")
        call_args = mock_session.post.call_args
        payload = call_args.kwargs.get("json") or call_args.args[1]
        assert payload["model"] == "custom-model"


class TestCompleteStructured:
    async def test_returns_validated_model(self, provider):
        import json

        raw = json.dumps({"answer": "42", "confidence": 0.9})
        mock_session = _mock_session({"message": {"content": raw}})
        provider._session = mock_session
        result = await provider.complete_structured(
            [{"role": "user", "content": "What is the answer?"}],
            _Schema,
        )
        assert isinstance(result, _Schema)
        assert result.answer == "42"

    async def test_injects_schema_into_system_message(self, provider):
        import json

        raw = json.dumps({"answer": "yes", "confidence": 1.0})
        mock_session = _mock_session({"message": {"content": raw}})
        provider._session = mock_session
        await provider.complete_structured(
            [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "Q"}],
            _Schema,
        )
        call_args = mock_session.post.call_args
        payload = call_args.kwargs.get("json") or call_args.args[1]
        system_msg = payload["messages"][0]
        assert "_Schema" in system_msg["content"]

    async def test_raises_validation_error_on_bad_json(self, provider):
        mock_session = _mock_session({"message": {"content": "not valid json {{{"}})
        provider._session = mock_session
        with pytest.raises(LLMValidationError):
            await provider.complete_structured([{"role": "user", "content": "Q"}], _Schema)

    async def test_prepends_system_message_when_absent(self, provider):
        import json

        raw = json.dumps({"answer": "yes", "confidence": 1.0})
        mock_session = _mock_session({"message": {"content": raw}})
        provider._session = mock_session
        await provider.complete_structured(
            [{"role": "user", "content": "Q"}],
            _Schema,
        )
        call_args = mock_session.post.call_args
        payload = call_args.kwargs.get("json") or call_args.args[1]
        assert payload["messages"][0]["role"] == "system"


class TestPost:
    async def test_raises_llm_error_on_non_200(self, provider):
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        provider._session = mock_session

        with pytest.raises(LLMError, match="500"):
            await provider._post("/api/chat", {})

    async def test_raises_connection_error(self, provider):
        import aiohttp

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.post = MagicMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError("refused"))
        )
        provider._session = mock_session

        with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(LLMConnectionError):
            await provider._post("/api/chat", {})
