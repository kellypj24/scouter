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
    uv run ruff check src/ pipeline/ app/ tests/
    uv run ruff format --check src/ pipeline/ app/ tests/
    uv run mypy src/ pipeline/

# Format all code
fmt:
    uv run ruff check --fix src/ pipeline/ app/ tests/
    uv run ruff format src/ pipeline/ app/ tests/

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

# Clean build artifacts
clean:
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type d -name .pytest_cache -exec rm -rf {} +
    find . -name "*.pyc" -delete
    find . -name ".coverage" -delete
