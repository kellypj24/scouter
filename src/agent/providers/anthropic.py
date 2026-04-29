"""Anthropic (Claude) provider — production LLM.

Requires: uv add anthropic
Env vars: ANTHROPIC_API_KEY, ANTHROPIC_MODEL (default: claude-sonnet-4-6)
"""

import os
from typing import Any

from pydantic import BaseModel

from src.agent.providers.base import LLMError, LLMValidationError

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider:
    """Anthropic Claude provider using the Messages API.

    Uses tool_use for structured output — more reliable than JSON prompting.

    Args:
        api_key: Anthropic API key. Reads ANTHROPIC_API_KEY env var.
        model: Claude model ID. Reads ANTHROPIC_MODEL env var.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.timeout = timeout

    def _client(self) -> Any:
        """Lazy-import Anthropic client to avoid hard dependency when not in use."""
        try:
            import anthropic

            return anthropic.AsyncAnthropic(api_key=self.api_key)
        except ImportError as exc:
            raise LLMError("anthropic package not installed. Run: uv add anthropic") from exc

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Generate a text completion via Claude Messages API.

        Args:
            messages: List of {role, content} dicts.
            **kwargs: Overrides — model, max_tokens, temperature.

        Returns:
            Generated text string.
        """
        client = self._client()
        system = None
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)

        try:
            response = await client.messages.create(
                model=kwargs.pop("model", self.model),
                max_tokens=kwargs.pop("max_tokens", 1024),
                system=system or "You are a helpful financial data analyst.",
                messages=filtered,
                **kwargs,
            )
            return str(response.content[0].text)
        except Exception as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Generate structured output via Claude tool_use.

        Defines the Pydantic schema as a tool and forces its use,
        which is more reliable than JSON prompting for complex schemas.

        Args:
            messages: List of {role, content} dicts.
            schema: Pydantic model to parse response into.
            **kwargs: Overrides — model, max_tokens.

        Returns:
            Validated Pydantic model instance.
        """
        client = self._client()
        system = None
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)

        tool = {
            "name": schema.__name__,
            "description": schema.__doc__ or f"Output conforming to {schema.__name__}",
            "input_schema": schema.model_json_schema(),
        }

        try:
            response = await client.messages.create(
                model=kwargs.pop("model", self.model),
                max_tokens=kwargs.pop("max_tokens", 1024),
                system=system or "You are a helpful financial data analyst.",
                messages=filtered,
                tools=[tool],
                tool_choice={"type": "tool", "name": schema.__name__},
                **kwargs,
            )
            tool_block = next(b for b in response.content if b.type == "tool_use")
            return schema.model_validate(tool_block.input)
        except StopIteration as exc:
            raise LLMValidationError("No tool_use block in Claude response") from exc
        except Exception as exc:
            raise LLMError(f"Anthropic structured completion error: {exc}") from exc
