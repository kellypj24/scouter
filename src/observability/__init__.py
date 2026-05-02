"""Observability module — structured request telemetry.

Write path: FastAPI middleware → ObservabilityLogger → SQLite (WAL mode)
Read path:  Dagster asset syncs SQLite → DuckDB raw_observability schema → dbt marts
"""
