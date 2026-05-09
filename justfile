set dotenv-load

# List available commands
default:
    @just --list

# Install dependencies
install:
    uv sync

# Run all tests
test:
    uv run pytest tests/ -v

# Lint all code
lint:
    uv run ruff check src/ pipeline/ app/ api/ tests/
    uv run ruff format --check src/ pipeline/ app/ api/ tests/
    uv run mypy src/ pipeline/

# Format all code
fmt:
    uv run ruff check --fix src/ pipeline/ app/ api/ tests/
    uv run ruff format src/ pipeline/ app/ api/ tests/

# Start Streamlit app
run:
    uv run streamlit run app/main.py

# Start Ollama + Streamlit together (Ctrl-C stops both)
dev:
    #!/usr/bin/env bash
    ollama serve &
    OLLAMA_PID=$!
    trap "kill $OLLAMA_PID 2>/dev/null" EXIT INT TERM
    sleep 2
    uv run streamlit run app/main.py
    kill $OLLAMA_PID 2>/dev/null

# Start Dagster dev server (pipeline UI + scheduler)
pipeline:
    uv run dagster dev

# Ingest raw data into DuckDB
ingest:
    uv run python -m src.data.loader

# Run dbt transformations
dbt:
    uv run dbt run --project-dir dbt/ --profiles-dir dbt/

# Run dbt tests
dbt-test:
    uv run dbt test --project-dir dbt/ --profiles-dir dbt/

# Generate dbt docs artifacts (manifest.json + catalog.json) for LLM schema context
dbt-docs:
    uv run dbt docs generate --project-dir dbt/ --profiles-dir dbt/

# Run a single question through the eval pipeline (headless, no Streamlit)
# Usage: just ask "What are the top 10 best performing stocks?"
ask question:
    uv run python scripts/eval_runner.py {{ quote(question) }}

# Run a single question and save the chart as HTML in /tmp/scouter_eval/
# Usage: just ask-chart "Show Apple's 50-day moving average"
ask-chart question:
    uv run python scripts/eval_runner.py --chart-dir /tmp/scouter_eval {{ quote(question) }}

# Run all eval fixtures and print a pass/fail table
eval:
    uv run python scripts/eval_score.py

# Run eval fixtures matching a substring filter
# Usage: just eval-filter screener
eval-filter substr:
    uv run python scripts/eval_score.py --filter {{ substr }}

# Run eval and save all charts to /tmp/scouter_eval/
eval-charts:
    uv run python scripts/eval_score.py --chart-dir /tmp/scouter_eval

# Build the Go eval runner binary
eval-go-build:
    go -C eval build -o scouter-eval .

# Run all eval fixtures concurrently using the Go runner
# Defaults: concurrency=3 (safe for local Ollama), timeout=3m
eval-go concurrency="3" timeout="3m" *args:
    go -C eval run . -root `pwd` -concurrency {{ concurrency }} -timeout {{ timeout }} {{ args }}

# Run Go eval fixtures matching a filter
# Usage: just eval-go-filter screener
eval-go-filter substr concurrency="3" timeout="3m":
    go -C eval run . -root `pwd` -filter {{ substr }} -concurrency {{ concurrency }} -timeout {{ timeout }}

# Load last eval run results into DuckDB and rebuild mart_eval_runs
# Run after `just eval-go` to make fixture-level results queryable
eval-load-results:
    uv run python scripts/load_eval_results.py
    uv run dbt run --project-dir dbt/ --profiles-dir dbt/ --select +mart_eval_runs

# Query mart_eval_runs for the latest run summary (requires eval-load-results first)
eval-results:
    uv run python scripts/query_eval_results.py

# Show current KPI values vs targets (requires observability data in DuckDB)
kpis:
    uv run python scripts/show_kpis.py

# Surface consistently-failing eval fixtures as pattern candidates for human review.
# Writes pattern_candidates.yaml (gitignored). Review entries, fill example_sql,
# then promote manually to learned_patterns.yaml.
promote-patterns:
    uv run python scripts/promote_patterns.py

# Start FastAPI harness service (port 8001)
api:
    uv run uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload

# Build container images (run after code or dep changes) and prune dangling layers
compose-build:
    docker compose build
    docker image prune -f

# Start containerised core runtime (FastAPI + gateway + Streamlit)
compose:
    docker compose up

# Start in background
compose-up:
    docker compose up -d

# Tear down containers (keeps volumes)
compose-down:
    docker compose down

# Build Go gateway binary
gateway-build:
    go -C gateway build -o scouter-gateway .

# Run Go gateway (proxies to FastAPI on 8001, listens on 8080)
gateway:
    go -C gateway run . -port 8080 -upstream http://localhost:8001

# Start full dev stack: FastAPI (8001) → gateway (8080) → Streamlit (8501)
# Ctrl-C stops all three.
serve:
    #!/usr/bin/env bash
    uv run uvicorn api.main:app --host 0.0.0.0 --port 8001 &
    API_PID=$!
    sleep 1
    go -C gateway run . -port 8080 -upstream http://localhost:8001 &
    GW_PID=$!
    trap "kill $API_PID $GW_PID 2>/dev/null" EXIT INT TERM
    sleep 1
    uv run streamlit run app/main.py

# Clean build artifacts
clean:
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type d -name .pytest_cache -exec rm -rf {} +
    find . -name "*.pyc" -delete
    find . -name ".coverage" -delete
    rm -f eval/scouter-eval
