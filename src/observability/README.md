# src/observability/ — Telemetry Write Path

Captures per-request and per-stage telemetry to SQLite. Designed to never block or fail the hot path.

## Files

| File | Responsibility |
|------|---------------|
| `context.py` | `request_id_var` ContextVar — set by API middleware, flows to all coroutines |
| `logger.py` | `ObservabilityLogger` — SQLite WAL writer, asyncio.to_thread, fire-and-forget |

## Write path

```
API middleware sets request_id_var
  → Orchestrator calls obs.start_request() / obs.finish_request()
  → QueryAgent / NarrativeAgent call obs.log_span()
  → Each call: asyncio.create_task(asyncio.to_thread(sqlite_write))
  → SQLite WAL (logs/scouter_logs.db) — never blocks the response path
```

## Read path (analytical)

SQLite is not queried directly. Dagster's `obs_log_sensor` detects file mtime changes and triggers `observability_sync`, which ETLs SQLite → DuckDB `raw_observability` schema. dbt then builds the five analytical marts.

## Eval tagging

`eval_runner.py` sets `request_id` to `eval_{fixture_id}_...`. Filter `WHERE request_id LIKE 'eval_%'` in any mart to isolate eval runs from production traffic.
