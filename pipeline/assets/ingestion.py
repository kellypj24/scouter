"""Raw data ingestion assets.

Loads CSV/Parquet source files into DuckDB.
Triggered by Dagster schedule or manually via `just pipeline`.
"""

from dagster import AssetExecutionContext, asset

from src.data.loader import ingest_raw_data


@asset(group_name="ingestion", compute_kind="duckdb")
def raw_market_data(context: AssetExecutionContext) -> None:
    """Ingest raw market data CSV files into DuckDB staging tables.

    Args:
        context: Dagster asset execution context.
    """
    rows = ingest_raw_data()
    context.log.info(f"Ingested {rows} rows into DuckDB")
