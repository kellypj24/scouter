# src/agent/providers/ — Claude Context

## Protocol contract

Every provider must implement `LLMProvider` as defined in `base.py`. Both methods must be `async`. The protocol is `@runtime_checkable` so isinstance checks work at runtime.

## complete_structured() rules

- Must validate response against the Pydantic schema before returning
- Raise `LLMValidationError` (not a bare exception) if parsing fails
- Anthropic and Bedrock use `tool_use` to force structured output — do not switch to JSON mode
- Ollama uses JSON mode + prompt injection (tool_use support is unreliable for the local models)

## Error hierarchy

Always raise from this hierarchy — never raw exceptions:
- `LLMConnectionError` — provider unreachable
- `LLMTimeoutError` — no response within timeout
- `LLMValidationError` — can't parse response into schema
- `LLMError` — base class for anything else

## Adding a provider — don't forget

- Deferred import inside `get_provider()` to avoid requiring unused deps
- Integration test covering both `complete()` and `complete_structured()`
- Update `providers/README.md` with the new entry
