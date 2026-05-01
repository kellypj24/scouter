# Scouter

Financial data narrative agent. Ask a question in plain English; Scouter generates SQL, runs it against DuckDB, and returns a chart + prose narrative — showing all its work.

> "It's over 9000." — reads the power level of your data.

## Stack

- **Agent harness** — Python 3.13, Pydantic, async/await
- **LLM providers** — Claude (Anthropic), Bedrock, Ollama (local) — swappable via `SCOUTER_LLM_PROVIDER`
- **Data layer** — DuckDB + dbt dimensional model (equity / sector / risk marts)
- **Pipeline** — Dagster (ingest + dbt transforms on schedule)
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

# Python sequential scorer (reference / fallback)
uv run python scripts/eval_score.py
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
`scripts/eval_score.py` is superseded by the Go runner for multi-fixture runs but kept as a reference.

## Data pipeline

```bash
just pipeline      # Start Dagster dev server
just ingest        # Ingest raw data into DuckDB
just dbt           # Run dbt transformations
just dbt-test      # Run dbt tests
```

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
