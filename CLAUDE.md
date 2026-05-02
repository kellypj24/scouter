# Scouter - Development Guidelines

## Project Overview
Financial data narrative agent. Users ask questions in natural language; Scouter generates SQL,
executes it against DuckDB, and returns an annotated visual + prose narrative — showing all its work.

**Tagline**: "It's over 9000." — reads the power level of your data.

**Developer Context**: Intermediate Python, advanced SQL/dbt, building toward production-grade agentic harness.

**Stack**: Python 3.13, DuckDB, dbt-duckdb, Dagster, Ollama/Claude/Bedrock (pluggable), Plotly, Streamlit (PoC), Go 1.26 (eval runner), uv, Docker

## Current Status

| Phase | Name | Status |
|-------|------|--------|
| 1 | Data Layer + Query Agent | Complete |
| 2 | Narrative Agent + Visualization | Complete |
| 3 | Orchestrator (multi-query) | Complete |
| 4 | UI Polish | Complete |
| 5 | Production Harness | In Progress |

### What's done
- **Phase 1**: `src/data/` (DuckDB connection, schema introspection, loader), `src/agent/query_agent.py` (LLM SQL gen, 2-attempt retry, domain classification, validation), full dbt mart structure (`core/`, `equity/`, `sector/`, `risk/`), Dagster ingestion + dbt assets
- **Phase 2**: `src/agent/narrative_agent.py` (LLM prose + chart inference), `src/viz/charts.py` (Plotly builders), `src/models/response.py` (NarrativeBlock), 15/15 eval fixtures passing
- **Phase 3**: `src/agent/orchestrator.py` (`run()` + `stream()`), multi-block decomposition, graceful degradation at every layer
- **Phase 4**: `api/` (FastAPI SSE service), `gateway/` (Go HTTP proxy), `app/main.py` rewritten as httpx SSE client — clean client/server boundary, no direct `src/` imports from UI

### What's next (Phase 5)
- Docker Compose for full stack (FastAPI + gateway + Streamlit + Ollama)
- Structured logging / observability (request IDs already flow through gateway)
- Answer quality: prompt hardening for multi-stock time-series queries, broader eval fixture coverage

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
│  Exposed via FastAPI SSE (api/)     │
└──────────────┬──────────────────────┘
               │ HTTP SSE
               ▼
┌─────────────────────────────────────┐
│  Go Gateway (gateway/)              │
│  Proxy + request ID + timing        │
└──────────────┬──────────────────────┘
               │ HTTP SSE
               ▼
┌─────────────────────────────────────┐
│  Streamlit App (app/)               │
│  httpx SSE client + artifact render │
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
6. **Provider Abstraction is Sacred** — Agent code ONLY imports `LLMProvider` from `providers/base.py`. Never import `OllamaProvider`, `AnthropicProvider`, or `BedrockProvider` directly in agent code. Swap providers via `SCOUTER_LLM_PROVIDER` env var.
7. **Always Async** — All LLM provider calls MUST be async (`async/await`). Never block on LLM.
8. **Always Have Fallbacks** — Every agent action needs a rule-based fallback. System must work if the LLM provider is unavailable.
9. **Token Budget: 4096 Hard Limit** — Validate before sending. Count tokens, truncate if needed, cache responses.
10. **Structured Responses Only** — All LLM output validated via Pydantic before use. Never trust raw strings.
11. **Artifact Chain** — Each response is a list of `NarrativeBlock` objects. Never a raw string response.

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
    providers/
      base.py           # LLMProvider protocol + get_provider() factory + error types
      ollama.py         # Ollama (local PoC) — routes SQL→codellama, prose→llama3.2
      anthropic.py      # Claude API — tool_use for structured output
      bedrock.py        # AWS Bedrock — converse API, tool_use for structured output
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
  eval/
    fixtures.yaml       # Eval fixture definitions (question + expected properties)
eval/                   # Go eval runner — replaces eval_score.py
  main.go               # CLI flags, semaphore-based goroutine dispatch
  runner.go             # Subprocess invocation + JSON parsing
  scorer.go             # Score RunResult against fixture expectations
  scorer_test.go        # Unit tests for scorer and fixture loader
  fixtures.go           # Load fixtures.yaml
  report.go             # tabwriter summary table + failure details
  go.mod / go.sum
scripts/
  eval_runner.py        # Single-question headless runner (JSON output — called by Go runner)
```

## Tooling
- **Package manager**: `uv` (`uv add`, `uv sync`, `uv run`)
- **Task runner**: `just` (`just test`, `just lint`, `just run`, `just pipeline`)
- **Containers**: Docker Compose (app + Ollama + Dagster)
- **Testing**: pytest >= 80% coverage
- **Linting**: ruff check + ruff format + mypy

### Eval commands
| Command | What it does |
|---------|-------------|
| `just ask "question"` | Run one question through the full pipeline, rich terminal output |
| `just eval-go` | Run all fixtures concurrently (Go runner) — primary eval command |
| `just eval-go-filter screener` | Run fixtures whose ID contains a substring |
| `just eval-go-build` | Compile Go runner to `eval/scouter-eval` binary |
| `uv run python scripts/eval_score.py` | Python sequential scorer (reference / fallback) |

The Go runner (`eval/`) calls `scripts/eval_runner.py --json` as a subprocess per fixture.
`eval_runner.py` is required. `eval_score.py` has been deleted — use `just eval-go` instead.

## Key Patterns
- **NarrativeBlock** — atomic response unit: `{question, sql, result_df, chart, prose, follow_ups}`
- **Async/await** for all LLM calls
- **Pydantic** for all LLM response validation
- **Schema injection** — always prepend DuckDB schema to SQL-generation prompts
- **Dagster Definitions** pattern — `all_assets`, `all_checks`, `all_schedules` lists wired in `pipeline/__init__.py`
- **EnvVar()** for all secrets in Dagster resources

## Data Architecture (Kimball Dimensional Model)

```
raw (DuckDB main schema)        yfinance ingestion via Dagster
  └── staging (views)           stg_prices, stg_companies, stg_market_snapshots
       └── intermediate (tables) int_daily_returns, int_volatility, int_sector_aggregates
            └── marts/
                 core/          dim_company, dim_date, fct_daily_prices, fct_fundamentals
                 equity/        mart_equity_performance, mart_equity_screener
                 sector/        mart_sector_rotation, mart_sector_fundamentals
                 risk/          mart_risk_profile, mart_drawdown
```

**LLM schema injection strategy**: The orchestrator classifies the user's question into a domain
(equity / sector / risk) and injects only that domain's mart schema into the prompt. The LLM
generates simple queries against pre-joined marts — not raw multi-table joins.

**Adding a new domain**: Create `dbt/models/marts/<domain>/`, add schema config to `dbt_project.yml`,
register with the schema injection classifier in `src/agent/orchestrator.py`.

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
