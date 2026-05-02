# src/agent/ — Claude Context

## Provider abstraction is sacred

Agent code imports **only** `LLMProvider` from `providers/base.py`. Never import `OllamaProvider`, `AnthropicProvider`, or `BedrockProvider` directly. Provider is selected at runtime via `SCOUTER_LLM_PROVIDER` env var.

```python
# correct
from src.agent.providers.base import LLMProvider, get_provider

# NEVER in agent code
from src.agent.providers.anthropic import AnthropicProvider
```

## Structured output always

All LLM calls must use `complete_structured()` with a Pydantic schema. Never use `complete()` and parse the string yourself.

## Token budget

Hard limit of 4096 tokens per request. Use `src/utils/tokens.py` to count and truncate before sending. Schema injection is the main variable cost — only inject the relevant domain's marts, not the full schema.

## Fallback required

Every agent action needs a rule-based fallback path. The harness must work if the LLM provider is unavailable.

## Observability

- Call `obs.start_request()` / `obs.finish_request()` in `Orchestrator.run()` and `stream()`
- Call `obs.log_span()` in `QueryAgent` and `NarrativeAgent` for per-stage timing
- All obs calls are fire-and-forget — wrap in `asyncio.create_task()`, never await directly in the hot path
