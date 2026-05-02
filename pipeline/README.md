# pipeline/ — Dagster Data Pipeline

Manages all data ingestion and dbt transformations. No LLM or agent logic lives here.

## Entry point

`pipeline/__init__.py` — `Definitions` object wiring assets, checks, sensors, and schedules.

## Asset topology

```
raw_market_data          ← data_freshness_sensor triggers on stale DuckDB data
  → dbt_transformations  ← dbt_test_after_ingest sensor triggers after data advances
  → observability_sync   ← obs_log_sensor triggers on SQLite mtime change
  → dbt_test_runner      ← runs dbt test, writes results directly to DuckDB
```

## Sensors (event-based, no crons)

| Sensor | Polls | Fires when |
|--------|-------|-----------|
| `data_freshness_sensor` | DuckDB MAX(date) every 30 min | historical_data ≥ 1 day stale |
| `dbt_test_after_ingest` | DuckDB date column every 10 min | date advances after ingest |
| `obs_log_sensor` | SQLite mtime every 5 min | scouter_logs.db changes |
| `dbt_docs_sensor` | `dbt/target/manifest.json` mtime every 10 min | dbt build runs and manifest updates |

Sensor-based triggers self-correct after machine sleep — a fixed cron would either fire redundantly or miss windows. `schedules/daily.py` exists as an escape hatch but is intentionally empty.

## Resources

- `DuckDBResource` — write connection for Dagster assets (separate from agent's read-only connection)
- `dbt resource` — configured dbt project path for `@dbt_assets`

## Running locally

```bash
just pipeline          # start Dagster UI at localhost:3000
```
