# Scouter

Financial data narrative agent. Ask a question in plain English; Scouter generates SQL, runs it against DuckDB, and returns a chart + prose narrative — showing all its work.

> "It's over 9000." — reads the power level of your data.

## Stack

- **Agent harness** — Python 3.13, Pydantic, async/await
- **LLM providers** — Claude (Anthropic), Bedrock, Ollama (local) — swappable via `SCOUTER_LLM_PROVIDER`
- **Data layer** — DuckDB + dbt dimensional model (equity / sector / risk marts)
- **Pipeline** — Dagster (ingest + dbt transforms, event-based sensors — no crons)
- **Observability** — SQLite write store → Dagster ELT → DuckDB analytical marts (fallback rate, latency, pipeline health)
- **UI** — Streamlit (PoC scaffolding; harness is UI-agnostic)
- **Eval runner** — Go 1.26 (concurrent fixture execution)

## Quick start

```bash
# Install Python deps
uv sync

# Copy env and set your LLM provider + API key
cp .env.example .env

# Run a single question (no UI needed)
just ask "What are the top 10 best performing stocks this year?"

# Start the Streamlit UI
just run
```

## Asking questions headlessly

```bash
# Rich terminal output
just ask "Which sectors have performed best this year?"

# Save chart as HTML
just ask-chart "Show Apple's 50-day moving average"

# JSON output (for scripting)
uv run python scripts/eval_runner.py --json "Show me Nvidia's price history"
```

## Running evals

Evals run fixture questions defined in `assignments/eval/fixtures.yaml` through the full pipeline and score each against expected properties (row count, chart type, SQL table used, etc.).

```bash
# Run all fixtures concurrently (Go runner — recommended)
just eval-go

# Filter to a subset
just eval-go-filter screener
just eval-go-filter timeseries

# Tune concurrency / timeout
go run ./eval -concurrency 4 -timeout 120s
```

The Go runner exits with code 1 if any fixture fails, making it CI-friendly.

### Eval architecture

```
assignments/eval/fixtures.yaml   fixture definitions
        │
        ▼
eval/ (Go runner)                loads fixtures, dispatches goroutines
        │  subprocess per fixture
        ▼
scripts/eval_runner.py           runs full pipeline, outputs JSON
        │
        ▼
src/ (Python agent harness)      orchestrator → query agent → narrative agent
```

`scripts/eval_runner.py` is the subprocess target — it must stay in place.

## Data pipeline

```bash
just pipeline      # Start Dagster dev server (sensors activate automatically)
just ingest        # Manually trigger raw data ingest
just dbt           # Run dbt transformations
just dbt-test      # Run dbt tests
```

### Sensors (event-based, no crons)

Dagster pipelines are driven by sensors rather than cron schedules. Sensors self-correct when the machine sleeps — no missed windows, no silent failures.

| Sensor | Polls | Fires when |
|--------|-------|-----------|
| `data_freshness_sensor` | every 30 min | `historical_data` is ≥ 1 day stale |
| `dbt_test_after_ingest` | every 10 min | `historical_data` date advances (new ingest) |
| `obs_log_sensor` | every 5 min | `logs/scouter_logs.db` file is modified |

All sensors start in `RUNNING` status so they activate as soon as `just pipeline` starts.

## Observability

Every request through the FastAPI service is instrumented end-to-end. Telemetry writes to SQLite (non-blocking, WAL mode) and is synced into DuckDB for SQL analysis via Dagster.

### What's captured

| Stage | Metrics |
|-------|---------|
| Request | question, domain, total latency, block count, fallback used |
| `sql_gen` | per-attempt latency, success/failure, error message, SQL length |
| `sql_exec` | latency, row count returned |
| `narrative` | latency, success/failure, chart source (llm / inferred / none) |
| `news` | latency, items fetched, success/failure |
| Dagster runs | job name, status, duration, last success time |
| dbt tests | test name, model, pass/fail, failing row count, run timestamp |

### Analytical marts (DuckDB, built by dbt)

```sql
-- Which domains trigger the most LLM fallbacks? (targets for prompt hardening)
SELECT * FROM main_observability.mart_fallback_analysis ORDER BY fallback_rate_pct DESC;

-- Where is latency worst?
SELECT * FROM main_observability.mart_stage_latency ORDER BY p95_latency_ms DESC;

-- Full per-request view — filter to eval fixture runs
SELECT * FROM main_observability.mart_request_metrics
WHERE request_id LIKE 'eval_%' ORDER BY started_at DESC LIMIT 50;

-- Dagster pipeline health
SELECT * FROM main_observability.mart_pipeline_health;

-- dbt data quality — which models have failing tests?
SELECT * FROM main_observability.mart_dbt_test_health WHERE failing_tests > 0;
```

Scouter request telemetry is synced by `obs_log_sensor` when the log file changes. dbt test results are written directly to DuckDB by `dbt_test_runner` after each ingest — no sync step needed.

### Eval fixture observability

Every `just eval-go` run tags each fixture's requests in the observability database with `eval_{fixture_id}_...` as the `request_id`. This means you can query `mart_fallback_analysis` or `mart_request_metrics` filtered to eval runs to see exactly which fixtures are driving fallbacks, SQL retries, or slow latency — the direct data feed for answer quality improvement decisions.

## Development

```bash
just test          # pytest
just lint          # ruff + mypy
just fmt           # ruff autofix + format
```

### Adding an eval fixture

Add an entry to `assignments/eval/fixtures.yaml`:

```yaml
- id: my_new_fixture
  question: "Which stocks have the highest Sharpe ratio?"
  expect:
    min_rows: 10
    max_blocks: 1
    fallback: false
    chart_type: bar
    sql_table: mart_equity_screener
```

Run `just eval-go-filter my_new_fixture` to validate it in isolation.

### Adding a new data domain

1. Create `dbt/models/marts/<domain>/`
2. Add schema config to `dbt_project.yml`
3. Register the domain classifier in `src/agent/orchestrator.py`

### Adding a new observability dimension

1. Add the field to `ObservabilityLogger._sync_write_span` in `src/observability/logger.py`
2. Call `await obs.log_span(..., new_field=value)` at the instrumentation point
3. Add the column to `dbt/models/staging/stg_obs_spans.sql`
4. Reference it in the relevant mart model
