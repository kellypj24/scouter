"""Unit tests for src/agent/providers/anthropic.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from src.agent.providers.anthropic import AnthropicProvider
from src.agent.providers.base import LLMError, LLMValidationError


class _Schema(BaseModel):
    result: str
    score: float = 0.0


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return AnthropicProvider(api_key="test-key")


def _make_text_response(text: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


def _make_tool_response(data: dict, schema_name: str = "_Schema") -> MagicMock:
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = data
    text_block = MagicMock()
    text_block.type = "text"
    response = MagicMock()
    response.content = [text_block, tool_block]
    return response


class TestInit:
    def test_reads_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        p = AnthropicProvider()
        assert p.api_key == "env-key"

    def test_reads_model_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-7")
        p = AnthropicProvider()
        assert p.model == "claude-opus-4-7"

    def test_explicit_values_override_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        p = AnthropicProvider(api_key="explicit-key", model="custom-model")
        assert p.api_key == "explicit-key"
        assert p.model == "custom-model"


class TestClient:
    def test_returns_async_anthropic(self, provider):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.AsyncAnthropic.return_value = mock_client
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = provider._client()
            assert result is mock_client

    def test_raises_llm_error_on_import_failure(self, provider):
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            pytest.raises(LLMError, match="anthropic package not installed"),
        ):
            provider._client()


class TestComplete:
    async def test_returns_text(self, provider):
        mock_response = _make_text_response("The answer is 42.")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_client", return_value=mock_client):
            result = await provider.complete([{"role": "user", "content": "What is 6x7?"}])
        assert result == "The answer is 42."

    async def test_strips_system_from_messages(self, provider):
        mock_response = _make_text_response("ok")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_client", return_value=mock_client):
            await provider.complete(
                [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Q"},
                ]
            )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful."
        assert not any(m.get("role") == "system" for m in call_kwargs["messages"])

    async def test_raises_llm_error_on_api_failure(self, provider):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("connection reset"))

        with (
            patch.object(provider, "_client", return_value=mock_client),
            pytest.raises(LLMError, match="Anthropic API error"),
        ):
            await provider.complete([{"role": "user", "content": "Q"}])


class TestCompleteStructured:
    async def test_returns_validated_model(self, provider):
        mock_response = _make_tool_response({"result": "hello", "score": 0.9})
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_client", return_value=mock_client):
            result = await provider.complete_structured(
                [{"role": "user", "content": "Q"}],
                _Schema,
            )
        assert isinstance(result, _Schema)
        assert result.result == "hello"

    async def test_raises_validation_error_when_no_tool_block(self, provider):
        # Response with no tool_use blocks
        text_block = MagicMock()
        text_block.type = "text"
        mock_response = MagicMock()
        mock_response.content = [text_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(provider, "_client", return_value=mock_client),
            pytest.raises(LLMValidationError, match="No tool_use block"),
        ):
            await provider.complete_structured(
                [{"role": "user", "content": "Q"}],
                _Schema,
            )

    async def test_raises_llm_error_on_api_failure(self, provider):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("rate limit"))

        with (
            patch.object(provider, "_client", return_value=mock_client),
            pytest.raises(LLMError, match="structured completion error"),
        ):
            await provider.complete_structured(
                [{"role": "user", "content": "Q"}],
                _Schema,
            )

    async def test_uses_tool_use_for_schema(self, provider):
        mock_response = _make_tool_response({"result": "ok", "score": 1.0})
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_client", return_value=mock_client):
            await provider.complete_structured([{"role": "user", "content": "Q"}], _Schema)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tool_choice"]["type"] == "tool"
        assert call_kwargs["tool_choice"]["name"] == "_Schema"
