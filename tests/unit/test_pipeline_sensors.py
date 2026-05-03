"""Unit tests for pipeline/sensors/dbt_build.py and related sensor logic."""

from unittest.mock import MagicMock, patch

from dagster import build_sensor_context


class TestDbtBuildAfterIngest:
    """Tests for the dbt_build_after_ingest sensor core logic.

    Tests target check_and_yield directly so they pass regardless of whether
    the dbt manifest exists in the test environment.
    """

    def _make_context(self, cursor: str | None = None) -> object:
        return build_sensor_context(cursor=cursor)

    def _mock_conn(self, return_value: tuple) -> MagicMock:
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = return_value
        return conn

    def test_no_op_when_data_current(self):
        """Yields nothing when cursor matches latest date."""
        from pipeline.sensors.dbt_build import check_and_yield

        ctx = self._make_context(cursor="2026-05-01")
        with patch("src.data.db.fresh_read_connection", return_value=self._mock_conn(("2026-05-01",))):
            results = list(check_and_yield(ctx))

        assert results == []

    def test_fires_when_date_advances(self):
        """Yields a RunRequest when historical_data has a newer date than the cursor."""
        from dagster import RunRequest

        from pipeline.sensors.dbt_build import check_and_yield

        ctx = self._make_context(cursor="2026-05-01")
        with patch("src.data.db.fresh_read_connection", return_value=self._mock_conn(("2026-05-02",))):
            results = list(check_and_yield(ctx))

        assert len(results) == 1
        assert isinstance(results[0], RunRequest)
        assert results[0].run_key == "dbt_build_2026-05-02"

    def test_fires_on_first_run_no_cursor(self):
        """Yields a RunRequest when there is no prior cursor."""
        from dagster import RunRequest

        from pipeline.sensors.dbt_build import check_and_yield

        ctx = self._make_context(cursor=None)
        with patch("src.data.db.fresh_read_connection", return_value=self._mock_conn(("2026-05-01",))):
            results = list(check_and_yield(ctx))

        assert len(results) == 1
        assert isinstance(results[0], RunRequest)

    def test_skips_when_db_error(self):
        """Yields nothing and does not raise when the DB query fails."""
        from pipeline.sensors.dbt_build import check_and_yield

        ctx = self._make_context(cursor=None)
        with patch("src.data.db.fresh_read_connection", side_effect=Exception("DB unavailable")):
            results = list(check_and_yield(ctx))

        assert results == []

    def test_skips_when_table_empty(self):
        """Yields nothing when historical_data has no rows."""
        from pipeline.sensors.dbt_build import check_and_yield

        ctx = self._make_context(cursor=None)
        with patch("src.data.db.fresh_read_connection", return_value=self._mock_conn((None,))):
            results = list(check_and_yield(ctx))

        assert results == []
