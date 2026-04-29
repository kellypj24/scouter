"""Unit tests for src/agent/providers/base.py."""

from unittest.mock import MagicMock, patch

import pytest

from src.agent.providers.base import (
    LLMConnectionError,
    LLMError,
    LLMProvider,
    LLMTimeoutError,
    LLMValidationError,
    get_provider,
)


class TestExceptionHierarchy:
    def test_connection_error_is_llm_error(self):
        assert issubclass(LLMConnectionError, LLMError)

    def test_timeout_error_is_llm_error(self):
        assert issubclass(LLMTimeoutError, LLMError)

    def test_validation_error_is_llm_error(self):
        assert issubclass(LLMValidationError, LLMError)

    def test_catch_subclass_as_base(self):
        with pytest.raises(LLMError):
            raise LLMConnectionError("no connection")

    def test_exception_chaining(self):
        with pytest.raises(LLMTimeoutError) as exc_info:
            try:
                raise ValueError("root cause")
            except ValueError as exc:
                raise LLMTimeoutError("timed out") from exc
        assert exc_info.value.__cause__ is not None

    def test_validation_error_message(self):
        exc = LLMValidationError("bad JSON")
        assert "bad JSON" in str(exc)


class TestGetProvider:
    def test_defaults_to_ollama(self, monkeypatch):
        monkeypatch.delenv("SCOUTER_LLM_PROVIDER", raising=False)
        mock_instance = MagicMock()
        with patch(
            "src.agent.providers.ollama.OllamaProvider", return_value=mock_instance
        ) as mock_cls:
            result = get_provider()
            mock_cls.assert_called_once()
            assert result is mock_instance

    def test_anthropic(self, monkeypatch):
        monkeypatch.setenv("SCOUTER_LLM_PROVIDER", "anthropic")
        mock_instance = MagicMock()
        with patch(
            "src.agent.providers.anthropic.AnthropicProvider", return_value=mock_instance
        ) as mock_cls:
            result = get_provider()
            mock_cls.assert_called_once()
            assert result is mock_instance

    def test_bedrock(self, monkeypatch):
        monkeypatch.setenv("SCOUTER_LLM_PROVIDER", "bedrock")
        mock_instance = MagicMock()
        with patch(
            "src.agent.providers.bedrock.BedrockProvider", return_value=mock_instance
        ) as mock_cls:
            get_provider()
            mock_cls.assert_called_once()

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("SCOUTER_LLM_PROVIDER", "ANTHROPIC")
        mock_instance = MagicMock()
        with patch("src.agent.providers.anthropic.AnthropicProvider", return_value=mock_instance):
            get_provider()  # should not raise

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("SCOUTER_LLM_PROVIDER", "notareal_provider")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider()


class TestLLMProviderProtocol:
    def test_satisfies_protocol(self):
        class GoodProvider:
            async def complete(self, messages, **kwargs):
                return ""

            async def complete_structured(self, messages, schema, **kwargs):
                return schema()

        assert isinstance(GoodProvider(), LLMProvider)

    def test_missing_methods_fails_protocol(self):
        class BadProvider:
            pass

        assert not isinstance(BadProvider(), LLMProvider)

    def test_partial_methods_fails_protocol(self):
        class PartialProvider:
            async def complete(self, messages, **kwargs):
                return ""

        assert not isinstance(PartialProvider(), LLMProvider)
