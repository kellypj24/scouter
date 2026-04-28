"""Raw data ingestion — yfinance → DuckDB.

Called by the Dagster ingestion asset. Can also be run directly:
    uv run python -m src.data.loader

Tables created in DuckDB main schema (raw layer for dbt):
  companies        — S&P 500 constituent metadata
  historical_data  — daily OHLCV per ticker
  market_summaries — point-in-time snapshot per ticker
"""

import logging
import os
from datetime import datetime

import duckdb
import pandas as pd

from src.data.db import get_connection
from src.data.fetcher import (
    fetch_historical_prices,
    fetch_market_snapshots,
    get_sp500_constituents,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


def create_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create raw ingestion tables if they do not exist.

    Args:
        conn: Active DuckDB connection.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            symbol        VARCHAR PRIMARY KEY,
            long_name     VARCHAR,
            sector        VARCHAR,
            industry      VARCHAR,
            exchange      VARCHAR,
            market_cap    DOUBLE,
            last_updated  TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS historical_data (
            symbol        VARCHAR,
            date          DATE,
            open          DOUBLE,
            high          DOUBLE,
            low           DOUBLE,
            close         DOUBLE,
            volume        BIGINT,
            last_updated  TIMESTAMP,
            PRIMARY KEY (symbol, date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_summaries (
            symbol        VARCHAR PRIMARY KEY,
            current_price DOUBLE,
            day_high      DOUBLE,
            day_low       DOUBLE,
            volume        BIGINT,
            market_cap    DOUBLE,
            week_52_high  DOUBLE,
            week_52_low   DOUBLE,
            last_updated  TIMESTAMP
        )
    """)

    logger.info("Raw tables ready")


# ---------------------------------------------------------------------------
# Per-table ingestion
# ---------------------------------------------------------------------------


def ingest_companies(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Upsert company metadata into the companies table.

    Args:
        conn: Active DuckDB connection.
        df: DataFrame from ``get_sp500_constituents()``.

    Returns:
        Number of rows upserted.
    """
    if df.empty:
        return 0

    conn.execute("""
        INSERT OR REPLACE INTO companies
            (symbol, long_name, sector, industry, exchange, market_cap, last_updated)
        SELECT
            symbol, long_name, sector, industry, exchange,
            CAST(market_cap AS DOUBLE),
            CAST(last_updated AS TIMESTAMP)
        FROM df
    """)
    count: int = len(df)
    logger.info("Upserted %d companies", count)
    return count


def ingest_prices(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Upsert OHLCV price data into historical_data.

    Args:
        conn: Active DuckDB connection.
        df: DataFrame from ``fetch_historical_prices()``.

    Returns:
        Number of rows upserted.
    """
    if df.empty:
        return 0

    conn.execute("""
        INSERT OR REPLACE INTO historical_data
            (symbol, date, open, high, low, close, volume, last_updated)
        SELECT
            symbol,
            CAST(date AS DATE),
            CAST(open AS DOUBLE),
            CAST(high AS DOUBLE),
            CAST(low AS DOUBLE),
            CAST(close AS DOUBLE),
            CAST(volume AS BIGINT),
            CAST(last_updated AS TIMESTAMP)
        FROM df
    """)
    count: int = len(df)
    logger.info("Upserted %d price rows", count)
    return count


def ingest_snapshots(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Upsert market snapshot data into market_summaries.

    Args:
        conn: Active DuckDB connection.
        df: DataFrame from ``fetch_market_snapshots()``.

    Returns:
        Number of rows upserted.
    """
    if df.empty:
        return 0

    conn.execute("""
        INSERT OR REPLACE INTO market_summaries
            (symbol, current_price, day_high, day_low, volume,
             market_cap, week_52_high, week_52_low, last_updated)
        SELECT
            symbol,
            CAST(current_price AS DOUBLE),
            CAST(day_high AS DOUBLE),
            CAST(day_low AS DOUBLE),
            CAST(volume AS BIGINT),
            CAST(market_cap AS DOUBLE),
            CAST(week_52_high AS DOUBLE),
            CAST(week_52_low AS DOUBLE),
            CAST(last_updated AS TIMESTAMP)
        FROM df
    """)
    count: int = len(df)
    logger.info("Upserted %d snapshot rows", count)
    return count


# ---------------------------------------------------------------------------
# Full ingestion orchestration
# ---------------------------------------------------------------------------


def ingest_raw_data(conn: duckdb.DuckDBPyConnection | None = None) -> dict[str, int]:
    """Run the full ingestion pipeline: yfinance → DuckDB raw tables.

    Fetches S&P 500 constituents, 5 years of daily prices, and current
    market snapshots. Creates tables if they don't exist.

    Args:
        conn: DuckDB connection. Uses shared connection if not provided.

    Returns:
        Dict mapping table name → rows upserted, e.g.
        {'companies': 503, 'historical_data': 631234, 'market_summaries': 498}
    """
    if conn is None:
        conn = get_connection()

    create_tables(conn)

    # Step 1: constituent list
    companies_df = get_sp500_constituents()
    tickers = companies_df["symbol"].tolist()

    # Step 2: historical prices
    prices_df = fetch_historical_prices(tickers)

    # Step 3: market snapshots
    snapshots_df = fetch_market_snapshots(tickers)

    # Step 4: ingest all three
    counts = {
        "companies": ingest_companies(conn, companies_df),
        "historical_data": ingest_prices(conn, prices_df),
        "market_summaries": ingest_snapshots(conn, snapshots_df),
    }

    logger.info("Ingestion complete: %s", counts)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = ingest_raw_data()
    for table, rows in result.items():
        print(f"  {table}: {rows:,} rows")
