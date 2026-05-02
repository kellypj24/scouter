# src/ — Agent Harness

The harness is the product. All business logic lives here. `app/`, `api/`, and `pipeline/` are thin wrappers around this package.

## Layer map

```
src/
  agent/          Question → SQL → narrative pipeline (LLM-driven)
  data/           DuckDB connection, schema introspection, data loading
  models/         Pydantic types shared across layers
  viz/            Plotly chart builders
  observability/  SQLite telemetry write path
  utils/          Token counting, response cache
```

## Key invariants

- `src/agent/` has no UI code
- `src/data/` has no LLM calls
- `src/observability/` never blocks — all writes are fire-and-forget
- All LLM calls are async
- All LLM output is validated through Pydantic before use

## Entry points

- `src/agent/orchestrator.py` — `Orchestrator.run()` / `Orchestrator.stream()` are the public API
- `src/agent/providers/base.py` — `get_provider()` factory for the configured LLM backend
- `src/data/db.py` — `get_read_connection()` for DuckDB access
