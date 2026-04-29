"""Unit tests for src/data/loader.py."""

from datetime import datetime

import duckdb
import pandas as pd
import pytest

from src.data.loader import (
    create_tables,
    ingest_companies,
    ingest_prices,
    ingest_raw_data,
    ingest_snapshots,
)


@pytest.fixture
def conn():
    """In-memory DuckDB connection, closed after each test."""
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def companies_df():
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "long_name": "Apple Inc.",
                "sector": "Information Technology",
                "industry": "Technology Hardware",
                "exchange": "NASDAQ",
                "market_cap": 3_000_000_000_000.0,
                "last_updated": datetime(2026, 1, 1),
            },
            {
                "symbol": "MSFT",
                "long_name": "Microsoft Corporation",
                "sector": "Information Technology",
                "industry": "Systems Software",
                "exchange": "NASDAQ",
                "market_cap": 2_500_000_000_000.0,
                "last_updated": datetime(2026, 1, 1),
            },
        ]
    )


@pytest.fixture
def prices_df():
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "date": datetime(2026, 1, 2).date(),
                "open": 185.0,
                "high": 188.0,
                "low": 184.0,
                "close": 187.0,
                "volume": 50_000_000,
                "last_updated": datetime(2026, 1, 2),
            },
            {
                "symbol": "AAPL",
                "date": datetime(2026, 1, 3).date(),
                "open": 187.0,
                "high": 190.0,
                "low": 186.0,
                "close": 189.0,
                "volume": 45_000_000,
                "last_updated": datetime(2026, 1, 3),
            },
            {
                "symbol": "MSFT",
                "date": datetime(2026, 1, 2).date(),
                "open": 375.0,
                "high": 380.0,
                "low": 373.0,
                "close": 378.0,
                "volume": 30_000_000,
                "last_updated": datetime(2026, 1, 2),
            },
        ]
    )


@pytest.fixture
def snapshots_df():
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "current_price": 187.0,
                "day_high": 188.0,
                "day_low": 184.0,
                "volume": 50_000_000,
                "market_cap": 3_000_000_000_000.0,
                "week_52_high": 200.0,
                "week_52_low": 150.0,
                "last_updated": datetime(2026, 1, 2),
            },
            {
                "symbol": "MSFT",
                "current_price": 378.0,
                "day_high": 380.0,
                "day_low": 373.0,
                "volume": 30_000_000,
                "market_cap": 2_500_000_000_000.0,
                "week_52_high": 420.0,
                "week_52_low": 310.0,
                "last_updated": datetime(2026, 1, 2),
            },
        ]
    )


class TestCreateTables:
    def test_creates_all_three_tables(self, conn):
        create_tables(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert {"companies", "historical_data", "market_summaries"}.issubset(tables)

    def test_idempotent(self, conn):
        """Calling create_tables twice should not raise."""
        create_tables(conn)
        create_tables(conn)

    def test_historical_data_primary_key(self, conn):
        """Duplicate (symbol, date) should be replaced, not duplicated."""
        create_tables(conn)
        pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "date": "2026-01-02",
                    "open": 185.0,
                    "high": 188.0,
                    "low": 184.0,
                    "close": 187.0,
                    "volume": 50_000_000,
                    "last_updated": datetime(2026, 1, 2),
                }
            ]
        )
        conn.execute("""
            INSERT OR REPLACE INTO historical_data VALUES (
                'AAPL', '2026-01-02', 185.0, 188.0, 184.0, 187.0, 50000000, NOW()
            )
        """)
        conn.execute("""
            INSERT OR REPLACE INTO historical_data VALUES (
                'AAPL', '2026-01-02', 190.0, 192.0, 189.0, 191.0, 60000000, NOW()
            )
        """)
        result = conn.execute(
            "SELECT COUNT(*) FROM historical_data WHERE symbol = 'AAPL'"
        ).fetchone()[0]
        assert result == 1


class TestIngestCompanies:
    def test_inserts_rows(self, conn, companies_df):
        create_tables(conn)
        count = ingest_companies(conn, companies_df)
        assert count == 2
        result = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        assert result == 2

    def test_returns_zero_for_empty_df(self, conn):
        create_tables(conn)
        count = ingest_companies(conn, pd.DataFrame())
        assert count == 0

    def test_upsert_replaces_existing(self, conn, companies_df):
        create_tables(conn)
        ingest_companies(conn, companies_df)
        updated = companies_df.copy()
        updated.loc[updated["symbol"] == "AAPL", "long_name"] = "Apple Inc. Updated"
        ingest_companies(conn, updated)
        name = conn.execute("SELECT long_name FROM companies WHERE symbol = 'AAPL'").fetchone()[0]
        assert name == "Apple Inc. Updated"
        total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        assert total == 2  # no duplicates


class TestIngestPrices:
    def test_inserts_rows(self, conn, prices_df):
        create_tables(conn)
        count = ingest_prices(conn, prices_df)
        assert count == 3

    def test_returns_zero_for_empty_df(self, conn):
        create_tables(conn)
        assert ingest_prices(conn, pd.DataFrame()) == 0

    def test_correct_values(self, conn, prices_df):
        create_tables(conn)
        ingest_prices(conn, prices_df)
        row = conn.execute(
            "SELECT close, volume FROM historical_data WHERE symbol = 'AAPL' AND date = '2026-01-02'"
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(187.0)
        assert row[1] == 50_000_000


class TestIngestSnapshots:
    def test_inserts_rows(self, conn, snapshots_df):
        create_tables(conn)
        count = ingest_snapshots(conn, snapshots_df)
        assert count == 2

    def test_returns_zero_for_empty_df(self, conn):
        create_tables(conn)
        assert ingest_snapshots(conn, pd.DataFrame()) == 0

    def test_correct_values(self, conn, snapshots_df):
        create_tables(conn)
        ingest_snapshots(conn, snapshots_df)
        row = conn.execute(
            "SELECT current_price, week_52_high FROM market_summaries WHERE symbol = 'AAPL'"
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(187.0)
        assert row[1] == pytest.approx(200.0)


class TestIngestRawData:
    def test_orchestrates_all_tables(
        self, conn, monkeypatch, companies_df, prices_df, snapshots_df
    ):
        """ingest_raw_data calls all three ingestion steps and returns counts."""
        monkeypatch.setattr("src.data.loader.get_sp500_constituents", lambda: companies_df)
        monkeypatch.setattr("src.data.loader.fetch_historical_prices", lambda tickers: prices_df)
        monkeypatch.setattr("src.data.loader.fetch_market_snapshots", lambda tickers: snapshots_df)

        counts = ingest_raw_data(conn=conn)

        assert counts["companies"] == 2
        assert counts["historical_data"] == 3
        assert counts["market_summaries"] == 2

    def test_returns_dict_with_all_keys(
        self, conn, monkeypatch, companies_df, prices_df, snapshots_df
    ):
        monkeypatch.setattr("src.data.loader.get_sp500_constituents", lambda: companies_df)
        monkeypatch.setattr("src.data.loader.fetch_historical_prices", lambda tickers: prices_df)
        monkeypatch.setattr("src.data.loader.fetch_market_snapshots", lambda tickers: snapshots_df)

        counts = ingest_raw_data(conn=conn)
        assert set(counts.keys()) == {"companies", "historical_data", "market_summaries"}
