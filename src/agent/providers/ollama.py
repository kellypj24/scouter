"""Ollama provider — local LLM for PoC.

Routes by task:
  SQL generation  → OLLAMA_SQL_MODEL   (default: codellama)
  Narrative prose → OLLAMA_MODEL       (default: llama3.2)

This lets us squeeze maximum quality out of local inference by using
the right model for each task without changing any harness code.
"""

import json
import os
from typing import Any

import aiohttp
from pydantic import BaseModel

from src.agent.providers.base import (
    LLMConnectionError,
    LLMError,
    LLMTimeoutError,
    LLMValidationError,
)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
DEFAULT_SQL_MODEL = "codellama"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3


class OllamaProvider:
    """Ollama LLM provider for local inference.

    Uses aiohttp for async requests with connection pooling.
    Retries with exponential backoff on connection/timeout errors.

    Args:
        host: Ollama server URL. Reads OLLAMA_HOST env var.
        model: Default model for narrative tasks. Reads OLLAMA_MODEL env var.
        sql_model: Model for SQL generation. Reads OLLAMA_SQL_MODEL env var.
        timeout: Request timeout in seconds. Reads OLLAMA_TIMEOUT env var.
    """

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        sql_model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.host = host or os.getenv("OLLAMA_HOST", DEFAULT_HOST)
        self.model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
        self.sql_model = sql_model or os.getenv("OLLAMA_SQL_MODEL", DEFAULT_SQL_MODEL)
        timeout_env = os.getenv("OLLAMA_TIMEOUT", str(DEFAULT_TIMEOUT))
        self.timeout = timeout if timeout is not None else int(timeout_env)
        self._connector: aiohttp.TCPConnector | None = None
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return shared aiohttp session, creating it if needed."""
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(limit=10)
            self._session = aiohttp.ClientSession(connector=self._connector)
        return self._session

    async def close(self) -> None:
        """Clean up aiohttp session. Call on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Generate a text completion via Ollama /api/chat.

        Args:
            messages: List of {role, content} dicts.
            **kwargs: Overrides — model, temperature, num_predict.

        Returns:
            Generated text string.
        """
        model = kwargs.pop("model", self.model)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.pop("temperature", 0.1),
                "num_predict": kwargs.pop("num_predict", 1024),
                **kwargs,
            },
        }
        response = await self._post("/api/chat", payload)
        return str(response["message"]["content"])

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Generate a structured completion using Ollama JSON mode.

        Injects the schema as a JSON instruction into the system prompt,
        then validates the response against the Pydantic model.

        Args:
            messages: List of {role, content} dicts.
            schema: Pydantic model class to parse response into.
            **kwargs: Overrides — model, temperature, num_predict.

        Returns:
            Validated Pydantic model instance.

        Raises:
            LLMValidationError: If response JSON cannot be parsed into schema.
        """
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        schema_instruction = (
            f"\n\nRespond with ONLY valid JSON matching this schema:\n{schema_json}"
        )

        # Inject schema into the last system message, or prepend one
        augmented = list(messages)
        if augmented and augmented[0]["role"] == "system":
            augmented[0] = {
                "role": "system",
                "content": augmented[0]["content"] + schema_instruction,
            }
        else:
            augmented.insert(0, {"role": "system", "content": schema_instruction})

        model = kwargs.pop("model", self.model)
        payload = {
            "model": model,
            "messages": augmented,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": kwargs.pop("temperature", 0.0),
                "num_predict": kwargs.pop("num_predict", 1024),
                **kwargs,
            },
        }
        response = await self._post("/api/chat", payload)
        raw = response["message"]["content"]

        try:
            return schema.model_validate_json(raw)
        except Exception as exc:
            raise LLMValidationError(
                f"Response could not be parsed into {schema.__name__}: {exc}\nRaw: {raw}"
            ) from exc

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to Ollama with retry and error handling.

        Args:
            path: API path (e.g. /api/chat).
            payload: JSON payload.

        Returns:
            Parsed JSON response dict.
        """
        import asyncio

        session = await self._get_session()
        url = f"{self.host}{path}"
        last_exc: Exception = LLMError("Unknown error")

        for attempt in range(MAX_RETRIES):
            try:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise LLMError(f"Ollama returned {resp.status}: {body}")
                    return await resp.json()  # type: ignore[no-any-return]
            except aiohttp.ClientConnectorError as exc:
                last_exc = LLMConnectionError(f"Cannot reach Ollama at {self.host}: {exc}")
            except TimeoutError as exc:
                last_exc = LLMTimeoutError(f"Ollama timed out after {self.timeout}s: {exc}")
            except LLMError:
                raise
            except Exception as exc:
                last_exc = LLMError(f"Unexpected Ollama error: {exc}")

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2**attempt)

        raise last_exc
