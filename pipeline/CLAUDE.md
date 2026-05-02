# pipeline/ — Claude Context

## No LLM calls

This package has no LLM imports or calls. Data pipeline only. If you find yourself importing from `src/agent/` or any LLM provider in pipeline code, stop — that's an architecture violation.

## Dagster Definitions pattern

All assets, checks, sensors, and schedules are collected into lists and wired in `__init__.py`. When adding a new asset or sensor:
1. Create it in the appropriate sub-directory
2. Add it to the `all_*` list in that sub-directory's `__init__.py` or equivalent
3. The root `Definitions` picks it up automatically

## Sensors over schedules

No new cron schedules. All triggers should be event-based sensors that check real conditions (file mtime, data age, date column advancing). This makes the pipeline self-healing after machine sleep.

## Write connection ownership

The Dagster `DuckDBResource` is the only write connection to the main DuckDB database. Assets must use this resource — never open a raw `duckdb.connect()` with write access from pipeline code.

## dbt test results

`dbt_test_runner` writes results directly to DuckDB (no SQLite hop). The Dagster process owns the write connection so this is safe. Do not route dbt test output through `src/observability/`.
