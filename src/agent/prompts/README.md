# src/agent/prompts/ — Prompt Templates

String templates injected by each agent stage. No logic here — just formatted strings.

## Files

| File | Used by | Purpose |
|------|---------|---------|
| `sql.py` | `QueryAgent` | SQL generation: schema injection, domain context, output format |
| `narrative.py` | `NarrativeAgent` | Prose + chart spec generation from SQL results |
| `orchestrator.py` | `Orchestrator._decompose()` | Question decomposition into sub-questions |

## Conventions

- Schema is injected at call time via `str.format()` — templates use `{schema}` placeholder
- Keep domain context narrow: only inject the relevant mart schema, not the full DB
- SQL prompts include explicit `SELECT only` and no-DDL instructions
- Output format specs must match the Pydantic schema the caller validates against
