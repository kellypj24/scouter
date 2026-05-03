"""Unit tests for pipeline/sensors/dbt_build.py and related sensor logic."""

from unittest.mock import MagicMock, patch

import pytest
from dagster import build_sensor_context


class TestDbtBuildAfterIngest:
    """Tests for the dbt_build_after_ingest sensor."""

    def _make_context(self, cursor: str | None = None) -> object:
        ctx = build_sensor_context(cursor=cursor)
        return ctx

    def test_no_op_when_data_current(self):
        """Sensor yields nothing when cursor matches latest date."""
        from pipeline.sensors.dbt_build import dbt_build_after_ingest

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-01",)

        ctx = self._make_context(cursor="2026-05-01")
        with patch("src.data.db.fresh_read_connection", return_value=mock_conn):
            results = list(dbt_build_after_ingest(ctx))

        assert results == []

    def test_fires_when_date_advances(self):
        """Sensor yields a RunRequest when historical_data has a newer date."""
        from dagster import RunRequest

        from pipeline.sensors.dbt_build import dbt_build_after_ingest

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-02",)

        ctx = self._make_context(cursor="2026-05-01")
        with patch("src.data.db.fresh_read_connection", return_value=mock_conn):
            results = list(dbt_build_after_ingest(ctx))

        assert len(results) == 1
        assert isinstance(results[0], RunRequest)
        assert results[0].run_key == "dbt_build_2026-05-02"

    def test_fires_on_first_run_no_cursor(self):
        """Sensor fires when there is no cursor (first run)."""
        from dagster import RunRequest

        from pipeline.sensors.dbt_build import dbt_build_after_ingest

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = ("2026-05-01",)

        ctx = self._make_context(cursor=None)
        with patch("src.data.db.fresh_read_connection", return_value=mock_conn):
            results = list(dbt_build_after_ingest(ctx))

        assert len(results) == 1
        assert isinstance(results[0], RunRequest)

    def test_skips_when_db_error(self):
        """Sensor yields nothing and does not raise when DB query fails."""
        from pipeline.sensors.dbt_build import dbt_build_after_ingest

        ctx = self._make_context(cursor=None)
        with patch(
            "src.data.db.fresh_read_connection",
            side_effect=Exception("DB unavailable"),
        ):
            results = list(dbt_build_after_ingest(ctx))

        assert results == []

    def test_skips_when_table_empty(self):
        """Sensor yields nothing when historical_data has no rows."""
        from pipeline.sensors.dbt_build import dbt_build_after_ingest

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (None,)

        ctx = self._make_context(cursor=None)
        with patch("src.data.db.fresh_read_connection", return_value=mock_conn):
            results = list(dbt_build_after_ingest(ctx))

        assert results == []
