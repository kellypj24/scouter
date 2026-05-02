# src/models/ — Pydantic Types

Shared type definitions used across the harness layers. No business logic here.

## Files

| File | Types |
|------|-------|
| `response.py` | `NarrativeBlock`, `QueryResult`, `ChartSpec` — the atomic response unit |
| `agent.py` | `AgentRequest`, `AgentResponse` — API boundary types |

## NarrativeBlock

The fundamental unit of a Scouter response. Every answer, regardless of complexity, is a list of these:

```python
NarrativeBlock(
    question: str,          # the sub-question this block answers
    query_result: QueryResult,  # sql + row_count + columns
    data: pd.DataFrame,     # raw query results
    chart_spec: ChartSpec | None,  # chart type + axis assignments
    prose: str,             # LLM-generated narrative
    follow_ups: list[str],  # suggested next questions
)
```

The chain is always: SQL artifact → data result → chart → prose. Never a raw string response.
