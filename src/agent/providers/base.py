"""LLM provider abstraction.

The agent harness ONLY imports LLMProvider — never a concrete provider.
Swap providers via SCOUTER_LLM_PROVIDER env var, zero harness code changes.

Supported providers (set SCOUTER_LLM_PROVIDER):
  ollama     — local Ollama (PoC default)
  anthropic  — Claude API
  bedrock    — AWS Bedrock
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class LLMProvider(Protocol):
    """Contract all LLM providers must satisfy.

    The agent harness depends only on this protocol — never on a concrete
    implementation. This makes provider swaps transparent to all agent code.
    """

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Generate a text completion.

        Args:
            messages: List of {role, content} dicts (OpenAI-style message format).
            **kwargs: Provider-specific overrides (temperature, max_tokens, etc.)

        Returns:
            Generated text string.

        Raises:
            LLMTimeoutError: If the provider does not respond within timeout.
            LLMConnectionError: If the provider cannot be reached.
            LLMError: For any other provider error.
        """
        ...

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Generate a structured completion validated against a Pydantic schema.

        Each provider implements this differently:
          - Ollama: JSON mode + prompt injection
          - Anthropic: tool_use with schema as tool definition
          - Bedrock: varies by underlying model

        Args:
            messages: List of {role, content} dicts.
            schema: Pydantic model class to validate the response against.
            **kwargs: Provider-specific overrides.

        Returns:
            Validated instance of schema.

        Raises:
            LLMValidationError: If response cannot be parsed into schema.
            LLMTimeoutError: If the provider does not respond within timeout.
            LLMConnectionError: If the provider cannot be reached.
        """
        ...


class LLMError(Exception):
    """Base exception for all LLM provider errors."""


class LLMConnectionError(LLMError):
    """Provider unreachable."""


class LLMTimeoutError(LLMError):
    """Provider did not respond within timeout."""


class LLMValidationError(LLMError):
    """Response could not be parsed into the expected schema."""


def get_provider() -> LLMProvider:
    """Instantiate the configured LLM provider.

    Reads SCOUTER_LLM_PROVIDER from environment (default: 'ollama').
    Import is deferred so unused providers don't require their dependencies.

    Returns:
        Configured LLMProvider instance.

    Raises:
        ValueError: If SCOUTER_LLM_PROVIDER names an unknown provider.
    """
    import os

    provider = os.getenv("SCOUTER_LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from src.agent.providers.ollama import OllamaProvider

        return OllamaProvider()
    elif provider == "anthropic":
        from src.agent.providers.anthropic import AnthropicProvider

        return AnthropicProvider()
    elif provider == "bedrock":
        from src.agent.providers.bedrock import BedrockProvider

        return BedrockProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            "Set SCOUTER_LLM_PROVIDER to one of: ollama, anthropic, bedrock"
        )
