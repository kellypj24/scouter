# src/utils/ — Stateless Helpers

Utility functions with no side effects and no dependencies on the rest of the harness.

## Files

| File | Contents |
|------|---------|
| `tokens.py` | Token counting and context truncation — used before every LLM call |
| `cache.py` | Response cache — keyed by question + schema hash |

## Token budget

Hard limit: **4096 tokens** per LLM request. `tokens.py` provides `count_tokens()` and `truncate_to_budget()`. The query agent uses these before sending the schema-injected prompt. Schema injection is the main variable — only the relevant domain mart schema is injected to stay within budget.

## Cache

`cache.py` caches LLM responses keyed to a hash of (question, schema). Useful for dev iteration and for eval runs where the same questions repeat. Cache is in-memory and not persisted across process restarts.
