# pipeline/sensors/ — Event-Based Sensors

| File | Sensor | Target | Poll interval | Fires when |
|------|--------|--------|--------------|-----------|
| `data_freshness.py` | `data_freshness_sensor` | `raw_market_data` | 30 min | MAX(date) in historical_data ≥ 1 day old |
| `dbt_tests.py` | `dbt_test_after_ingest` | `dbt_test_runner` | 10 min | historical_data date advances (new ingest detected) |
| `observability.py` | `obs_log_sensor` | `observability_sync` | 5 min | `logs/scouter_logs.db` mtime changes |

## Design principle

Sensors fire on real conditions, not clocks. A `run_key` scoped to a date or mtime ensures at most one run per event — duplicate sensor evaluations within the same window are no-ops.

## Production analogue

On a real deployment, the mtime check becomes an S3 event notification and the date check becomes a Kafka offset comparison. The sensor body stays the same; only the trigger source changes.
