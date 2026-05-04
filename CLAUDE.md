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
- **Phase 5 (partial)**: Answer quality hardening (28 eval fixtures, follow-up constraints, live news context via yfinance); Observability layer (`src/observability/` — SQLite WAL write store, request ID propagation, all 5 pipeline stages logged: `decompose`, `sql_gen`, `sql_exec`, `narrative`, `news`; domain propagated at request + span level); Dagster ELT pipeline (SQLite + Dagster run history → DuckDB `raw_observability` schema → 5 dbt analytical marts); event-based sensors replacing all cron schedules; `dbt_test_runner` asset writes test results directly to DuckDB after each ingest; eval runner tags fixture runs with `eval_{fixture_id}` prefix so prod and eval telemetry are queryable side-by-side; Docker Compose phase 1 (`Dockerfile` + `Dockerfile.gateway` + `docker-compose.yml`) containerises FastAPI + Go gateway + Streamlit; `host.docker.internal` bridges to local Ollama until phase 2; contextual knowledge base (dbt docs sensor, few-shot injection via `learned_patterns.yaml`); Docker Compose phase 2 (Ollama + Dagster webserver/daemon services); schema-level SQL guards (Guards 1-3 in `query_agent._validate_schema`) cutting first-attempt failures for sector snapshot misuse, pctile hallucination, and avg_drawdown on risk mart — 27/28 eval fixtures passing, 290 unit tests, 82% coverage
- **Phase 5 (eval harness round 2, branch `feature/eval-harness-round2`)**: Expanded eval suite to 45 fixtures (was 28); narrative agent improvements (multi-sector color inference, scatter keyword detection, x/y inference fixes); SQL prompt scatter/correlation guidance; Guard 5 (unqualified unknown table names); 11 learned patterns with domain priority ordering; `mart_eval_runs` observability feedback loop — **37/45 passing**, 8 remaining failures are local model ceiling (see model notes below)

### What's next (Phase 5 remaining)
- **Model ceiling**: 8 fixtures blocked by `qwen2.5-coder:3b` limits — see **Local model capability ceiling** section below for details and workarounds
- **Chart x_col/y_col scorer validation**: Go scorer validates chart presence but not column sensibility — `assignments/active/eval_harness_round2.md` Task 3
- **Domain-specific fallback SQL**: replace single generic fallback with per-domain templates so model failures produce useful data, not empty results
- News → tool-calling: upgrade when using Anthropic provider (qwen2.5 tool support is unreliable)

**Active work**: `assignments/active/`
**Completed reference**: `assignments/completed/`

## Architecture

Three distinct runtimes — keep them separate:

```
┌─────────────────────────────────────┐
│  Dagster Pipeline (pipeline/)       │
│  Sensors (event-based, no crons)   │
│  data_freshness_sensor → ingest    │
│  dbt_build_after_ingest → dbt run  │
│  dbt_test_after_ingest → dbt tests │
│  obs_log_sensor → obs sync         │
└──────────────┬──────────────────────┘
               │ writes financial data
               ▼
          DuckDB (data/scouter.duckdb)
               │ reads (read-only conn)
               ▼
┌─────────────────────────────────────┐
│  Agent Harness (src/)               │
│  User question → SQL → narrative   │
│  Exposed via FastAPI SSE (api/)     │
│  Writes telemetry spans →          │
└──────────┬───────────┬──────────────┘
           │ HTTP SSE  │ writes (async, WAL)
           ▼           ▼
┌──────────────┐  SQLite (logs/scouter_logs.db)
│  Go Gateway  │       │ Dagster ELT (obs_log_sensor)
│  request ID  │       ▼
└──────┬───────┘  DuckDB raw_observability schema
       │ HTTP SSE      │ dbt transforms
       ▼               ▼
┌─────────────────────────────────────┐
│  Streamlit App (app/)               │
│  httpx SSE client + artifact render │
└─────────────────────────────────────┘
       mart_fallback_analysis         ← answer quality targets (filter: eval_%  vs prod)
       mart_stage_latency             ← bottleneck identification
       mart_request_metrics           ← per-request audit (prod + eval fixture runs)
       mart_pipeline_health           ← Dagster run history
       mart_dbt_test_health           ← data quality: failing tests per model
       mart_eval_runs                 ← per-fixture pass/fail + observability context (just eval-load-results)
```

## Local model capability ceiling

`qwen2.5-coder:3b` (default SQL model via Ollama) has hard limits that determine which
eval fixtures pass or fail. Claude Sonnet/Opus via the Anthropic provider is expected
to clear all 8 remaining failures. This section documents the failure modes and the
compensating controls already in place.

### Failure taxonomy

| Fixture(s) | Root cause | Prompt tokens | Compensating control |
|---|---|---|---|
| `sector_daily_leaders` | Hallucinates table name (`StockReturns`) on every attempt; retry uses wider schema with no examples and picks a random real table | ~4000 | Guard 5 catches hallucinated tables; error message names valid tables. Pattern injected on attempt 1. |
| `sector_fundamentals_snapshot` | Blends valid column names (`avg_market_cap` + `total_market_cap` → `avg_total_market_cap`); both attempts fail schema validation | ~3700 | Learned pattern shows exact column names; Guard validates on attempt 2 |
| `drawdown_longest_streak` | Can't produce QUALIFY + `mart_drawdown` aggregation; returns empty SQL | ~4000 | Learned pattern with CTE + QUALIFY template |
| `moving_avg_crossover_screen` | Dual-window + QUALIFY + WHERE CTE is complex; passes ~40% of runs but falls back on the rest | ~4000 | Learned pattern with complete CTE template |
| `moving_avg_multi_stock`, `multistock_three_tech_giants`, `multistock_sector_champions` | Orchestrator decomposes multi-stock questions into 1-ticker-per-block; each block has 1 ticker so `color_col` never fires | — | Learned CTE pattern; orchestrator prompt not yet updated |

### Why these workarounds help Claude more than qwen2.5

- **Guard 5 (table-existence)** — catches `FROM StockReturns` at validation, produces a
  specific error naming valid tables. qwen2.5 ignores the hint; Claude uses it to generate
  correct SQL on retry.
- **Learned patterns** — qwen2.5 sees examples but doesn't reliably follow them at ~4000
  tokens. Claude at its context size uses few-shot examples nearly perfectly.
- **Guards 1–5 error messages** — qwen2.5 retries produce similar wrong SQL. Claude reads
  the error, understands it, and self-corrects — each guard doubles as a precise correction prompt.
- **Tiered example injection (1 example for 3+ domain combos)** — protects qwen2.5's 4k
  context from bloat. With Claude's 200k context this cap doesn't apply; all 11 patterns
  could be injected simultaneously with no budget concern.

### Upgrading the provider

Set `SCOUTER_LLM_PROVIDER=anthropic` and ensure `ANTHROPIC_API_KEY` is set. The Anthropic
provider uses `tool_use` for structured SQL + narrative output, which is more reliable than
JSON-in-text for both models. Expected outcome: 45/45 eval fixtures passing.

### Domain-specific fallback SQL (not yet built)

The current fallback (`_FALLBACK_SQL` in `query_agent.py`) is a single generic screener
query. When both LLM attempts fail, the user always gets a top-YTD screener result
regardless of what they asked. Replacing this with per-domain fallback templates would:
- Give a correct (if generic) sector or risk answer when the LLM fails
- Surface observability signal that distinguishes "LLM failed but fallback answered" from
  "LLM failed and produced a wrong-domain result"
- Apply equally for qwen2.5 AND Claude (both can fail under load or context limits)

---

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
    db.py               # DuckDB connection management (get_connection, get_read_connection, fresh_read_connection)
    schema.py           # Schema introspection + prompt injection helpers (TTL cache, few-shot injection)
    context.py          # Learned patterns loader — reads learned_patterns.yaml, get_few_shot_examples()
    loader.py           # CSV/Parquet → DuckDB ingestion (used by Dagster asset)
  viz/
    charts.py           # Plotly chart builders keyed to ChartType enum
  models/
    response.py         # Pydantic: NarrativeBlock, QueryResult, ChartSpec
    agent.py            # Pydantic: AgentRequest, AgentResponse
  utils/
    tokens.py           # Token counting + truncation
    cache.py            # Response cache
src/
  observability/
    context.py          # request_id ContextVar — set by middleware, flows to all coroutines
    logger.py           # ObservabilityLogger — SQLite WAL writer, asyncio.to_thread, fire-and-forget
pipeline/               # Dagster — data pipeline only, no LLM calls
  assets/
    ingestion.py        # Raw data → DuckDB asset
    observability.py    # Syncs SQLite logs + Dagster run history → DuckDB raw_observability
    dbt_tests.py        # Runs dbt test, writes results directly to DuckDB (no SQLite)
    schema_context.py   # dbt_docs_generate asset — runs dbt docs generate via subprocess
    transformations.py  # @dbt_assets
  checks/
    freshness.py        # Asset freshness checks
  resources/
    connections.py      # DuckDB resource, dbt resource
  schedules/
    daily.py            # Empty — all triggers are sensor-based (kept as escape hatch)
  sensors/
    data_freshness.py   # Polls DuckDB every 30 min, fires when data ≥ 1 day stale
    dbt_build.py        # Polls DuckDB every 10 min, fires dbt run when historical_data date advances
    dbt_tests.py        # Polls DuckDB every 10 min, fires dbt test when historical_data date advances
    dbt_docs.py         # Watches manifest.json mtime every 10 min, fires on dbt build
    observability.py    # Watches SQLite mtime every 5 min, fires when log file changes
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

### Before every commit
Run `just lint && just test` before committing or pushing. CI is a backstop — catching failures there means a wasted round-trip. Never push a separate "fix lint" commit; fold fixes into the original commit before the first push.

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
- **Dagster Definitions** pattern — `all_assets`, `all_checks`, `all_schedules`, `all_sensors` lists wired in `pipeline/__init__.py`
- **Event-based sensors** — no cron schedules; sensors gate on real conditions (file mtime, data age) and self-correct after machine sleep
- **Observability write path** — `ObservabilityLogger.log_span()` is fire-and-forget (`asyncio.create_task` + `asyncio.to_thread`); logging never blocks or raises. All 5 stages logged: `decompose` (sub_question_count), `sql_gen` (domain, sql_length, attempt), `sql_exec` (row_count), `narrative` (chart_source), `news` (news_items). Domain captured at both request and span level via `QueryAgent.classify_domains()`.
- **Observability read path** — Dagster ELT (SQLite → DuckDB) + dbt marts; same pattern scales to Postgres → Snowflake without changing downstream models
- **dbt test results** — written directly to DuckDB by `dbt_test_runner` (Dagster process owns the write connection; no SQLite hop needed)
- **Eval tagging** — `eval_runner.py` prefixes `request_id` with `eval_{fixture_id}_` so fixture runs are queryable alongside prod traffic in all observability marts
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

raw_observability schema        SQLite + Dagster run history via observability_sync asset
  |                             dbt test results via dbt_test_runner (direct DuckDB write)
  └── staging (views)           stg_obs_requests, stg_obs_spans, stg_obs_dagster_runs,
  |                             stg_obs_dbt_tests
       └── marts/
            observability/      mart_request_metrics    — per-request audit (prod + eval runs)
                                mart_stage_latency      — P50/P95/P99 by pipeline stage
                                mart_fallback_analysis  — fallback rate by domain
                                mart_pipeline_health    — Dagster job success/duration
                                mart_dbt_test_health    — dbt pass rate + failing rows per model
```

**Eval fixture observability**: `eval_runner.py` tags every run with `eval_{fixture_id}_...` as the `request_id`. Filter `WHERE request_id LIKE 'eval_%'` in any mart to isolate eval runs from prod traffic and correlate fixture failures to specific observability signals.

**LLM schema injection strategy**: The orchestrator classifies the user's question into a domain
(equity / sector / risk) and injects only that domain's mart schema into the prompt. The LLM
generates simple queries against pre-joined marts — not raw multi-table joins.

**Adding a new domain**: Create `dbt/models/marts/<domain>/`, add schema config to `dbt_project.yml`,
register with the schema injection classifier in `src/agent/orchestrator.py`.

## CI Maintenance Rules

When adding or moving source files, you MUST also:
1. **Update `scripts/ci_test_resolver.py`** — add an explicit mapping in `EXPLICIT_MAPPINGS` if the new file maps to multiple test files or follows a non-standard naming pattern. Convention-based discovery (`tests/unit/test_{module}.py`) handles the standard case automatically.
2. **Update CLAUDE.md and README.md** — the `staleness` CI job will block PRs that change `src/`, `api/`, or `pipeline/assets/` without touching these docs.
3. **Add a test file** — the `staleness` CI job will hard-fail if a new source file has no corresponding `tests/unit/test_{module}.py`.

The CI has three jobs: `lint` (ruff + mypy), `test` (targeted by changed files, falls back to full suite), `staleness` (docs + coverage gap check). All three must pass to merge.

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
