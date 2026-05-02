# src/agent/providers/ — LLM Provider Abstraction

All providers implement the `LLMProvider` protocol defined in `base.py`. Agent code never imports a concrete provider — it imports the protocol and uses `get_provider()` to get the configured instance.

## Providers

| File | Provider | Notes |
|------|----------|-------|
| `base.py` | Protocol + factory | `get_provider()` reads `SCOUTER_LLM_PROVIDER` env var |
| `ollama.py` | Ollama (local) | Default. Routes SQL→codellama, prose→llama3.2. Good for offline dev. |
| `anthropic.py` | Claude API | Uses `tool_use` for structured output |
| `bedrock.py` | AWS Bedrock | Uses Converse API + `tool_use` |

## Switching providers

```bash
SCOUTER_LLM_PROVIDER=anthropic just run   # Claude
SCOUTER_LLM_PROVIDER=bedrock just run     # Bedrock
# default (no env var) → Ollama
```

## Adding a new provider

1. Create `providers/<name>.py` implementing the `LLMProvider` protocol
2. Implement both `complete()` and `complete_structured()` as `async` methods
3. Add the `elif provider == "<name>":` branch in `base.py::get_provider()`
4. Add integration tests in `tests/integration/`

The `complete_structured()` method must validate the response against the provided Pydantic schema before returning — raise `LLMValidationError` if it can't.
