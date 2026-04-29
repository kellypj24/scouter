"""Unit tests for src/agent/providers/bedrock.py."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.agent.providers.base import LLMError, LLMValidationError
from src.agent.providers.bedrock import BedrockProvider


class _Schema(BaseModel):
    answer: str
    score: float = 0.0


@pytest.fixture
def provider():
    return BedrockProvider(region="us-east-1")


def _make_converse_response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}}


def _make_tool_use_response(data: dict, tool_name: str = "_Schema") -> dict:
    return {"output": {"message": {"content": [{"toolUse": {"name": tool_name, "input": data}}]}}}


class TestInit:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("BEDROCK_MODEL", raising=False)
        p = BedrockProvider()
        assert p.region == "us-east-1"
        assert "claude" in p.model_id

    def test_explicit_values(self):
        p = BedrockProvider(region="eu-west-1", model_id="amazon.titan-v1")
        assert p.region == "eu-west-1"
        assert p.model_id == "amazon.titan-v1"

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
        p = BedrockProvider()
        assert p.region == "ap-southeast-1"


class TestClient:
    def test_returns_boto3_client(self, provider):
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = provider._client()
            assert result is mock_client
            mock_boto3.client.assert_called_once_with(
                "bedrock-runtime", region_name=provider.region
            )

    def test_raises_llm_error_on_import_failure(self, provider):
        with (
            patch.dict("sys.modules", {"boto3": None}),
            pytest.raises(LLMError, match="boto3 not installed"),
        ):
            provider._client()


class TestComplete:
    async def test_returns_text(self, provider):
        mock_client = MagicMock()
        mock_client.converse.return_value = _make_converse_response("The answer is 42.")

        with patch.object(provider, "_client", return_value=mock_client):
            result = await provider.complete([{"role": "user", "content": "What is 6x7?"}])
        assert result == "The answer is 42."

    async def test_passes_system_message(self, provider):
        mock_client = MagicMock()
        mock_client.converse.return_value = _make_converse_response("ok")

        with patch.object(provider, "_client", return_value=mock_client):
            await provider.complete(
                [
                    {"role": "system", "content": "You are a financial analyst."},
                    {"role": "user", "content": "Q"},
                ]
            )

        call_kwargs = mock_client.converse.call_args.kwargs
        assert call_kwargs["system"] == [{"text": "You are a financial analyst."}]

    async def test_raises_llm_error_on_api_failure(self, provider):
        mock_client = MagicMock()
        mock_client.converse.side_effect = Exception("throttling")

        with (
            patch.object(provider, "_client", return_value=mock_client),
            pytest.raises(LLMError, match="Bedrock error"),
        ):
            await provider.complete([{"role": "user", "content": "Q"}])

    async def test_uses_default_system_when_none_provided(self, provider):
        mock_client = MagicMock()
        mock_client.converse.return_value = _make_converse_response("ok")

        with patch.object(provider, "_client", return_value=mock_client):
            await provider.complete([{"role": "user", "content": "Q"}])

        call_kwargs = mock_client.converse.call_args.kwargs
        assert "financial data analyst" in call_kwargs["system"][0]["text"]


class TestCompleteStructured:
    async def test_returns_validated_model(self, provider):
        mock_client = MagicMock()
        mock_client.converse.return_value = _make_tool_use_response(
            {"answer": "hello", "score": 0.9}
        )

        with patch.object(provider, "_client", return_value=mock_client):
            result = await provider.complete_structured(
                [{"role": "user", "content": "Q"}],
                _Schema,
            )
        assert isinstance(result, _Schema)
        assert result.answer == "hello"

    async def test_raises_validation_error_when_no_tool_use(self, provider):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "plain text, no tool"}]}}
        }

        with (
            patch.object(provider, "_client", return_value=mock_client),
            pytest.raises(LLMValidationError, match="No toolUse block"),
        ):
            await provider.complete_structured(
                [{"role": "user", "content": "Q"}],
                _Schema,
            )

    async def test_raises_llm_error_on_api_failure(self, provider):
        mock_client = MagicMock()
        mock_client.converse.side_effect = Exception("service unavailable")

        with (
            patch.object(provider, "_client", return_value=mock_client),
            pytest.raises(LLMError, match="structured completion error"),
        ):
            await provider.complete_structured(
                [{"role": "user", "content": "Q"}],
                _Schema,
            )

    async def test_wires_tool_config_correctly(self, provider):
        mock_client = MagicMock()
        mock_client.converse.return_value = _make_tool_use_response({"answer": "ok", "score": 1.0})

        with patch.object(provider, "_client", return_value=mock_client):
            await provider.complete_structured([{"role": "user", "content": "Q"}], _Schema)

        call_kwargs = mock_client.converse.call_args.kwargs
        tool_config = call_kwargs["toolConfig"]
        assert tool_config["tools"][0]["toolSpec"]["name"] == "_Schema"
        assert tool_config["toolChoice"]["tool"]["name"] == "_Schema"
