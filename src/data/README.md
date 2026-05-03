# src/data/ — Data Layer

DuckDB access, schema introspection, and raw data loading. No LLM calls here.

## Files

| File | Responsibility |
|------|---------------|
| `db.py` | DuckDB connection management — `get_read_connection()` for agent reads |
| `schema.py` | Schema introspection + prompt injection — reads dbt artifacts, TTL-cached, includes few-shot |
| `context.py` | Claude-curated few-shot SQL examples from `learned_patterns.yaml` |
| `loader.py` | CSV/Parquet → DuckDB ingestion, called by Dagster `raw_market_data` asset |
| `fetcher.py` | yfinance data fetching — downloads prices, fundamentals, market snapshots |
| `news.py` | Live news context via yfinance — appended to narrative prompts |

## Connection model

- Agent uses **read-only** connections from `get_read_connection()`
- Dagster assets use a **write** connection managed by `pipeline/resources/connections.py`
- Never open a write connection from `src/` — that's `pipeline/`'s job

## Schema injection

`schema.py::get_schema_prompt(conn, domains)` returns a prompt-ready string combining:
1. **Structural schema** — mart column names, types, descriptions, and accepted values for low-cardinality VARCHARs (from dbt artifacts or INFORMATION_SCHEMA fallback)
2. **Few-shot examples** — Claude-curated patterns from `learned_patterns.yaml` via `context.py`

The schema context is TTL-cached (1 hour) so long-running processes pick up `dbt docs generate` output without restart. Call `reload_schema_context()` to force an immediate refresh.

## learned_patterns.yaml

Lives at the project root. Claude promotes validated patterns here after reviewing `mart_query_patterns` in DuckDB. The local agent reads this file but never writes to it.
