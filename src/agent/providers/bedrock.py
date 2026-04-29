"""AWS Bedrock provider — enterprise/cloud LLM.

Requires: uv add boto3
Env vars: AWS_REGION, BEDROCK_MODEL (default: anthropic.claude-sonnet-4-6-v1)
          Standard AWS credential chain (AWS_ACCESS_KEY_ID / role / profile)
"""

import os
from typing import Any

from pydantic import BaseModel

from src.agent.providers.base import LLMError, LLMValidationError

DEFAULT_MODEL = "anthropic.claude-sonnet-4-6-v1"
DEFAULT_REGION = "us-east-1"


class BedrockProvider:
    """AWS Bedrock provider using boto3 converse API.

    The converse API provides a unified interface across Bedrock models,
    reducing the per-model differences in request/response format.

    Args:
        region: AWS region. Reads AWS_REGION env var.
        model_id: Bedrock model ID. Reads BEDROCK_MODEL env var.
    """

    def __init__(
        self,
        region: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self.region = region or os.getenv("AWS_REGION", DEFAULT_REGION)
        self.model_id = model_id or os.getenv("BEDROCK_MODEL", DEFAULT_MODEL)

    def _client(self) -> Any:
        """Lazy-import boto3 client to avoid hard dependency when not in use."""
        try:
            import boto3

            return boto3.client("bedrock-runtime", region_name=self.region)
        except ImportError as exc:
            raise LLMError("boto3 not installed. Run: uv add boto3") from exc

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Generate a text completion via Bedrock converse API.

        Note: boto3 is synchronous — runs in a thread executor to stay async.

        Args:
            messages: List of {role, content} dicts.
            **kwargs: Overrides — model_id, max_tokens, temperature.

        Returns:
            Generated text string.
        """
        import asyncio

        client = self._client()
        system_parts = [{"text": m["content"]} for m in messages if m["role"] == "system"]
        converse_messages = [
            {"role": m["role"], "content": [{"text": m["content"]}]}
            for m in messages
            if m["role"] != "system"
        ]

        def _call() -> str:
            response = client.converse(
                modelId=kwargs.pop("model_id", self.model_id),
                messages=converse_messages,
                system=system_parts or [{"text": "You are a helpful financial data analyst."}],
                inferenceConfig={
                    "maxTokens": kwargs.pop("max_tokens", 1024),
                    "temperature": kwargs.pop("temperature", 0.1),
                },
            )
            return str(response["output"]["message"]["content"][0]["text"])

        try:
            return await asyncio.get_event_loop().run_in_executor(None, _call)
        except Exception as exc:
            raise LLMError(f"Bedrock error: {exc}") from exc

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Generate structured output via Bedrock tool_use (converse API).

        Args:
            messages: List of {role, content} dicts.
            schema: Pydantic model to parse response into.
            **kwargs: Overrides.

        Returns:
            Validated Pydantic model instance.
        """
        import asyncio

        client = self._client()
        system_parts = [{"text": m["content"]} for m in messages if m["role"] == "system"]
        converse_messages = [
            {"role": m["role"], "content": [{"text": m["content"]}]}
            for m in messages
            if m["role"] != "system"
        ]

        tool_config = {
            "tools": [
                {
                    "toolSpec": {
                        "name": schema.__name__,
                        "description": schema.__doc__ or f"Output conforming to {schema.__name__}",
                        "inputSchema": {"json": schema.model_json_schema()},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": schema.__name__}},
        }

        def _call() -> BaseModel:
            response = client.converse(
                modelId=kwargs.pop("model_id", self.model_id),
                messages=converse_messages,
                system=system_parts or [{"text": "You are a helpful financial data analyst."}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": kwargs.pop("max_tokens", 1024)},
            )
            content = response["output"]["message"]["content"]
            tool_inputs = [b["toolUse"]["input"] for b in content if "toolUse" in b]
            if not tool_inputs:
                raise LLMValidationError("No toolUse block in Bedrock response")
            return schema.model_validate(tool_inputs[0])

        try:
            return await asyncio.get_event_loop().run_in_executor(None, _call)
        except LLMValidationError:
            raise
        except Exception as exc:
            raise LLMError(f"Bedrock structured completion error: {exc}") from exc
