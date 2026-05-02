# src/data/ — Claude Context

## No LLM calls

This layer has no LLM imports or calls. Data access only.

## Read-only from agent

`get_read_connection()` returns a read-only DuckDB connection. The agent must never open a write connection — that belongs to `pipeline/`. If you need to write from the harness, route it through `src/observability/` (SQLite) or add a Dagster asset.

## No SELECT *

Generated queries validated in `QueryAgent` must not use `SELECT *`. The schema injection pattern in `schema.py` is what makes this possible — the LLM knows the exact columns available.

## loader.py is Dagster-only

`loader.py` is called by `pipeline/assets/ingestion.py`. Do not call it directly from agent or API code.
