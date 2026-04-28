"""Raw data ingestion assets.

Loads yfinance data (S&P 500 prices + snapshots) into DuckDB raw tables.
Triggered by Dagster schedule or manually via `just pipeline`.
"""

from dagster import AssetExecutionContext, asset

from src.data.db import get_connection
from src.data.loader import ingest_raw_data


@asset(
    group_name="ingestion",
    compute_kind="duckdb",
    description="Ingest S&P 500 OHLCV prices, company metadata, and market snapshots from yfinance into DuckDB.",
)
def raw_market_data(context: AssetExecutionContext) -> None:
    """Ingest raw market data from yfinance into DuckDB raw tables.

    Creates three tables in DuckDB main schema:
      - companies: S&P 500 constituent metadata
      - historical_data: 5 years of daily OHLCV per ticker
      - market_summaries: current market snapshot per ticker

    Args:
        context: Dagster asset execution context.
    """
    conn = get_connection()
    counts = ingest_raw_data(conn=conn)

    for table, rows in counts.items():
        context.log.info("  %s: %s rows upserted", table, f"{rows:,}")

    context.add_output_metadata({
        "companies": counts["companies"],
        "historical_data_rows": counts["historical_data"],
        "market_summaries": counts["market_summaries"],
    })
