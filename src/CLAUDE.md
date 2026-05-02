# src/ — Claude Context

## Layer rules (non-negotiable)

| Layer | Allowed | Never |
|-------|---------|-------|
| `agent/` | LLM calls, DuckDB reads via QueryAgent | UI code, direct DB writes |
| `data/` | DuckDB reads, schema introspection | LLM calls |
| `observability/` | SQLite writes (async, fire-and-forget) | Blocking I/O, raising exceptions |
| `viz/` | Plotly chart construction | Data fetching, LLM calls |
| `models/` | Pydantic types | Business logic |
| `utils/` | Stateless helpers | State, I/O |

## Cross-cutting rules

- **Dependency injection only** — pass providers/connections via constructors, no global state
- **Type hints required** on all signatures and class attributes
- **Async for all LLM calls** — never block on LLM
- **Pydantic validation** — never use raw LLM strings; always validate before use
- **Specific exceptions** — never bare `except:`
- **Google-style docstrings** on all public methods and classes
