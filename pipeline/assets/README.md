# pipeline/assets/ — Dagster Assets

| File | Asset(s) | Writes to |
|------|---------|-----------|
| `ingestion.py` | `raw_market_data` | DuckDB `historical_data`, `companies`, `market_snapshots` |
| `transformations.py` | `dbt_transformations` (`@dbt_assets`) | DuckDB staging → intermediate → marts |
| `observability.py` | `observability_sync` | DuckDB `raw_observability` schema (from SQLite + Dagster run history) |
| `dbt_tests.py` | `dbt_test_runner` | DuckDB `raw_observability.dbt_test_results` directly |
| `schema_context.py` | `dbt_docs_generate` | `dbt/target/catalog.json` (via `dbt docs generate`) |

## Dependency order

```
raw_market_data
  ↓ (dbt_test_after_ingest sensor gates this)
dbt_transformations
  ↓ (obs_log_sensor gates this)
observability_sync
  ↓
dbt_test_runner
```
