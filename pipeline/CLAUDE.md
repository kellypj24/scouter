# pipeline/ — Claude Context

## No LLM calls

This package has no LLM imports or calls. Data pipeline only. If you find yourself importing from `src/agent/` or any LLM provider in pipeline code, stop — that's an architecture violation.

## Never use `from __future__ import annotations` in pipeline files

Dagster evaluates `@asset` and `@asset_check` parameter annotations at decoration time. PEP 563 (`from __future__ import annotations`) makes all annotations lazy strings — Dagster gets `"AssetExecutionContext"` instead of the class and throws `DagsterInvalidDefinitionError`, poisoning the entire `pipeline/__init__.py` import chain. Use concrete type annotations only.

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

## pattern_promotion asset

`pipeline/assets/pattern_promotion.py` runs `scripts/promote_patterns.py` as a subprocess after each `observability_sync`. It writes to `pattern_candidates.yaml` (gitignored) — never to `learned_patterns.yaml`. It is safe to re-run; existing `promoted` entries are preserved.

## kpi_health_check

`pipeline/checks/kpi_health.py` defines an `@asset_check` on `observability_sync` that calls `src/observability/kpis.py:evaluate_kpis()`. It opens a **read-only** DuckDB connection — it does not use the `DuckDBResource`. Severity is WARN (not ERROR) so a below-target KPI surfaces in the UI without blocking the pipeline.
