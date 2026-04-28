# Scouter - Development Guidelines

## Project Overview
Financial data narrative agent. Users ask questions in natural language; Scouter generates SQL,
executes it against DuckDB, and returns an annotated visual + prose narrative — showing all its work.

**Tagline**: "It's over 9000." — reads the power level of your data.

**Developer Context**: Intermediate Python, advanced SQL/dbt, building toward production-grade agentic harness.

**Stack**: Python 3.13, DuckDB, dbt-duckdb, Dagster, Ollama (Code Llama), Plotly, Streamlit (PoC), uv, Docker

## Current Status

| Phase | Name | Status |
|-------|------|--------|
| 1 | Data Layer + Query Agent | Planned |
| 2 | Narrative Agent + Visualization | Planned |
| 3 | Orchestrator (multi-query) | Planned |
| 4 | UI Polish | Planned |
| 5 | Production Harness | Planned |

**Active work**: `assignments/active/`
**Completed reference**: `assignments/completed/`

## Architecture

Two distinct runtimes — keep them separate:

```
┌─────────────────────────────────────┐
│  Dagster Pipeline (pipeline/)       │
│  Ingest → dbt transform → DuckDB   │
│  Runs on schedule / sensor trigger  │
└──────────────┬──────────────────────┘
               │ writes
               ▼
          DuckDB (data/)
               │ reads
               ▼
┌─────────────────────────────────────┐
│  Agent Harness (src/)               │
│  User question → SQL → narrative   │
│  Runs on request (Streamlit)        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Streamlit App (app/)               │
│  Chat UI + artifact renderer        │
└─────────────────────────────────────┘
```

## Constitution (Non-Negotiable Principles)

### Architecture
1. **The Harness is the Product** — Streamlit is scaffolding. All logic lives in `src/`. UI is swappable.
2. **Show Your Work** — Every response is a `NarrativeBlock`: SQL artifact + data result + chart + prose. No black boxes.
3. **Dependency Injection Only** — Pass dependencies via constructors. No global state, no singletons (except OllamaClient).
4. **Type Safety Required** — Type hints on ALL signatures and class attributes. No `Any` without justification.
5. **Strict Layer Separation** — `src/agent/` has no UI code. `app/` has no agent logic. `pipeline/` has no LLM calls. `src/data/` has no LLM calls.

### Agent
6. **Always Async** — All Ollama calls MUST be async (`async/await`). Never block on LLM.
7. **Always Have Fallbacks** — Every agent action needs a rule-based fallback. System must work if Ollama is down.
8. **Token Budget: 4096 Hard Limit** — Validate before sending. Count tokens, truncate if needed, cache responses.
9. **Structured Responses Only** — All LLM output validated via Pydantic before use. Never trust raw strings.
10. **Artifact Chain** — Each response is a list of `NarrativeBlock` objects. Never a raw string response.

### Data
11. **DuckDB is the Source of Truth** — All queries run against DuckDB. No in-memory pandas pipelines.
12. **Query Safety** — Generated SQL must be validated before execution. SELECT only — no DDL/DML from agent.
13. **Schema Awareness** — Agent always receives current schema. Inject schema into every SQL-generation prompt.
14. **Dagster owns ingestion** — Raw data loading and dbt transformations run through Dagster assets only.

### Code Quality
15. **>= 80% Test Coverage** — Unit tests alongside implementation. No exceptions.
16. **Specific Error Handling** — Never bare `except:`. Catch specific exceptions.
17. **Google-style Docstrings** — Required on all public methods and classes.

## Project Structure

```
src/
  agent/
    orchestrator.py     # Decomposes questions, manages multi-block narrative flow
    query_agent.py      # SQL generation + DuckDB execution
    narrative_agent.py  # Prose generation + visualization decisions
    ollama.py           # Async Ollama client (retry, fallback, timeout)
    prompts/
      sql.py            # SQL generation prompt templates
      narrative.py      # Narrative/interpretation prompt templates
  data/
    db.py               # DuckDB connection management
    schema.py           # Schema introspection + prompt injection helpers
    loader.py           # CSV/Parquet → DuckDB ingestion (used by Dagster asset)
  viz/
    charts.py           # Plotly chart builders keyed to ChartType enum
  models/
    response.py         # Pydantic: NarrativeBlock, QueryResult, ChartSpec
    agent.py            # Pydantic: AgentRequest, AgentResponse
  utils/
    tokens.py           # Token counting + truncation
    cache.py            # Response cache
pipeline/               # Dagster — data pipeline only, no LLM calls
  assets/
    ingestion.py        # Raw data → DuckDB asset
    transformations.py  # @dbt_assets
  checks/
    freshness.py        # Asset freshness checks
  resources/
    connections.py      # DuckDB resource, dbt resource
  schedules/
    daily.py            # Daily refresh schedule
  sensors/              # Future: file arrival sensors
  __init__.py           # Dagster Definitions entry point
app/
  main.py               # Streamlit app shell
  components/           # Chat UI, artifact renderer (NarrativeBlock → HTML/Plotly)
dbt/
  models/
    staging/            # Raw event transformations
    intermediate/       # Business logic
    analytics/          # Agent-ready aggregations
  macros/
  tests/
data/                   # Raw CSV/Parquet (gitignored if large)
tests/
  unit/
  integration/
assignments/
  active/
  completed/
  templates/
```

## Tooling
- **Package manager**: `uv` (`uv add`, `uv sync`, `uv run`)
- **Task runner**: `just` (`just test`, `just lint`, `just run`, `just pipeline`)
- **Containers**: Docker Compose (app + Ollama + Dagster)
- **Testing**: pytest >= 80% coverage
- **Linting**: ruff check + ruff format + mypy

## Key Patterns
- **NarrativeBlock** — atomic response unit: `{question, sql, result_df, chart, prose, follow_ups}`
- **Async/await** for all LLM calls
- **Pydantic** for all LLM response validation
- **Schema injection** — always prepend DuckDB schema to SQL-generation prompts
- **Dagster Definitions** pattern — `all_assets`, `all_checks`, `all_schedules` lists wired in `pipeline/__init__.py`
- **EnvVar()** for all secrets in Dagster resources

## Anti-Patterns (Never Do)
- LLM asserts a number without a backing SQL query
- Synchronous Ollama calls anywhere
- Raw LLM string used without Pydantic validation
- Agent logic inside `app/` (Streamlit code)
- LLM calls inside `pipeline/` (Dagster code)
- `SELECT *` in generated queries
- Hardcoded table/column names in agent code (use schema introspection)
- Bare `except:` clauses

## Graceful Degradation
1. Full narrative: LLM SQL + LLM prose + Plotly chart
2. LLM timeout/error → retry once with truncated context
3. Second failure → rule-based SQL template + plain text summary
4. Never surface a raw error to the user

## Deviation Protocol
Any deviation from constitution requires: Justification → `decisions.md` → Human approval → Tech debt issue → Remediation plan.
