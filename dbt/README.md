# dbt/ — Analytical Transforms

Kimball-style dimensional model on top of the raw DuckDB data ingested by Dagster.

## Model layers

```
raw (DuckDB main schema)
  └── staging/          Views over raw tables — light rename + type cast, no joins
       └── intermediate/ Tables — business logic, multi-table joins, derived metrics
            └── marts/   Agent-ready aggregations (no joins required at query time)
```

## Mart domains

| Domain | Path | What's there |
|--------|------|-------------|
| `core/` | `marts/core/` | `dim_company`, `dim_date`, `fct_daily_prices`, `fct_fundamentals` |
| `equity/` | `marts/equity/` | `mart_equity_performance`, `mart_equity_screener` |
| `sector/` | `marts/sector/` | `mart_sector_rotation`, `mart_sector_fundamentals` |
| `risk/` | `marts/risk/` | `mart_risk_profile`, `mart_drawdown` |
| `observability/` | `marts/observability/` | Five analytical marts over `raw_observability` |

## Observability marts

Built on `raw_observability` schema (populated by Dagster's `observability_sync` asset):

| Mart | Purpose |
|------|---------|
| `mart_request_metrics` | Per-request audit — prod + eval runs |
| `mart_stage_latency` | P50/P95/P99 by pipeline stage |
| `mart_fallback_analysis` | Fallback rate by domain — use to find answer quality targets |
| `mart_pipeline_health` | Dagster job success/duration history |
| `mart_dbt_test_health` | dbt test pass rate + failing rows per model |

## Running dbt

```bash
just dbt-run    # materialise all models
just dbt-test   # run all tests
```

Or via Dagster (preferred in production): assets run dbt after each ingest.
