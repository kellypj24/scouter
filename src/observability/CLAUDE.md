# src/observability/ — Claude Context

## Fire-and-forget contract

All `ObservabilityLogger` calls must be wrapped in `asyncio.create_task()`. Never await them directly in the request path. Never let logging raise or propagate exceptions — failures are swallowed silently.

```python
# correct
asyncio.create_task(obs.log_span(...))

# NEVER — blocks the hot path
await obs.log_span(...)
```

## ContextVar propagation

`request_id_var` is a `contextvars.ContextVar` set by the FastAPI middleware. It automatically propagates to all coroutines spawned within that request context. Do not pass `request_id` as a function argument — read it from the ContextVar.

## SQLite only

This layer writes to SQLite (`logs/scouter_logs.db`) via WAL mode. Do not add DuckDB writes here — that's the Dagster ELT job's responsibility. Keeping the write path simple means logging can never deadlock with the pipeline.

## kpis.py is read-only

`kpis.py` is the exception to the SQLite-only rule — it reads from DuckDB observability marts to compute KPI values. It never writes. Use a read-only connection: `duckdb.connect(path, read_only=True)`.

## domain_confidence on sql_gen spans

`ObservabilityLogger.log_span()` accepts `domain_confidence: float` as a metadata kwarg for `sql_gen` spans. It is populated by `QueryAgent.run()` from `DomainClassification.confidence`. Pass it alongside `domain` when logging SQL generation.
