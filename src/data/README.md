# src/data/ — Data Layer

DuckDB access, schema introspection, and raw data loading. No LLM calls here.

## Files

| File | Responsibility |
|------|---------------|
| `db.py` | DuckDB connection management — `get_read_connection()` for agent reads |
| `schema.py` | Schema introspection + prompt injection helpers (mart → prompt string) |
| `loader.py` | CSV/Parquet → DuckDB ingestion, called by Dagster `raw_market_data` asset |
| `fetcher.py` | yfinance data fetching — downloads prices, fundamentals, market snapshots |
| `news.py` | Live news context via yfinance — appended to narrative prompts |

## Connection model

- Agent uses **read-only** connections from `get_read_connection()`
- Dagster assets use a **write** connection managed by `pipeline/resources/connections.py`
- Never open a write connection from `src/` — that's `pipeline/`'s job

## Schema injection

`schema.py` provides `get_domain_schema(domain)` which returns a prompt-ready string of the relevant mart columns. The orchestrator classifies the question domain (equity / sector / risk) and injects only that subset to stay within the 4096-token budget.
