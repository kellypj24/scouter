# src/agent/ — Agent Pipeline

Drives the end-to-end question → SQL → narrative flow.

## Files

| File | Responsibility |
|------|---------------|
| `orchestrator.py` | Decomposes questions, runs sub-questions through query + narrative, returns `AgentResponse` |
| `query_agent.py` | LLM SQL generation, DuckDB execution, domain classification, 2-attempt retry |
| `narrative_agent.py` | LLM prose generation, chart type inference, `NarrativeBlock` assembly |
| `providers/` | LLM provider abstraction — see `providers/README.md` |
| `prompts/` | Prompt templates for each agent stage |

## Request lifecycle

```
AgentRequest
  → Orchestrator._decompose()       LLM breaks question into sub-questions
  → [per sub-question]
      QueryAgent.run()              LLM generates SQL → DuckDB executes
      NarrativeAgent.run()          LLM generates prose + chart spec
      → NarrativeBlock              sql + data + chart + prose + follow_ups
  → AgentResponse([NarrativeBlock])
```

## Graceful degradation

1. Full path: LLM SQL + LLM prose + Plotly chart
2. LLM timeout → retry once with truncated context
3. Second failure → rule-based SQL template + plain text summary
4. DuckDB error → `_error_block()` (never a raw exception to caller)
5. Unanswerable metric → `_unanswerable_block()` with suggestions

## Streaming

`Orchestrator.stream()` yields `NarrativeBlock` objects as they complete — designed for SSE transport via `api/main.py`. Blocks are not filtered in stream mode; that's the client's responsibility.
