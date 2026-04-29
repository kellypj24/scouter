"""Unit tests for pipeline/assets/ingestion.py."""

from unittest.mock import patch

import duckdb
import pytest
from dagster import build_asset_context


class TestRawMarketDataAsset:
    """Tests for the raw_market_data Dagster asset."""

    @pytest.fixture
    def mock_counts(self):
        return {
            "companies": 503,
            "historical_data": 632_000,
            "market_summaries": 498,
        }

    @pytest.fixture
    def in_memory_conn(self):
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    def test_asset_runs_without_error(self, mock_counts, in_memory_conn):
        with (
            patch("pipeline.assets.ingestion.get_connection", return_value=in_memory_conn),
            patch("pipeline.assets.ingestion.ingest_raw_data", return_value=mock_counts),
        ):
            from pipeline.assets.ingestion import raw_market_data

            ctx = build_asset_context()
            raw_market_data(ctx)  # should not raise

    def test_asset_logs_row_counts(self, mock_counts, in_memory_conn):
        with (
            patch("pipeline.assets.ingestion.get_connection", return_value=in_memory_conn),
            patch("pipeline.assets.ingestion.ingest_raw_data", return_value=mock_counts),
        ):
            from pipeline.assets.ingestion import raw_market_data

            ctx = build_asset_context()
            raw_market_data(ctx)
            # Dagster's build_asset_context captures logs — basic smoke test that it ran

    def test_asset_passes_conn_to_ingest(self, mock_counts, in_memory_conn):
        """Verifies the asset passes the DuckDB connection into ingest_raw_data."""
        captured_kwargs: dict = {}

        def capture_ingest(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_counts

        with (
            patch("pipeline.assets.ingestion.get_connection", return_value=in_memory_conn),
            patch("pipeline.assets.ingestion.ingest_raw_data", side_effect=capture_ingest),
        ):
            from pipeline.assets.ingestion import raw_market_data

            ctx = build_asset_context()
            raw_market_data(ctx)

        assert "conn" in captured_kwargs
        assert captured_kwargs["conn"] is in_memory_conn
