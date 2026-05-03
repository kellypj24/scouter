"""Unit tests for src/data/db.py — connection management and sensor safety."""

from __future__ import annotations

import contextlib
import os
from unittest.mock import patch

import duckdb
import pytest

import src.data.db as db_mod


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level connection singletons between tests."""
    db_mod._connection = None
    db_mod._read_connection = None
    yield
    # Close any connections opened during the test.
    for attr in ("_connection", "_read_connection"):
        conn = getattr(db_mod, attr, None)
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
    db_mod._connection = None
    db_mod._read_connection = None


class TestFreshReadConnection:
    """fresh_read_connection() must open and close without leaving a cached handle."""

    def test_yields_a_connection(self, tmp_path):
        db_path = str(tmp_path / "test.duckdb")
        duckdb.connect(db_path).close()  # pre-create so read-only open succeeds
        with (
            patch.dict(os.environ, {"DUCKDB_PATH": db_path}),
            db_mod.fresh_read_connection() as conn,
        ):
            assert conn is not None
            assert isinstance(conn, duckdb.DuckDBPyConnection)

    def test_connection_closed_after_context_exit(self, tmp_path):
        """Verify the connection is closed (not cached) after the context exits."""
        db_path = str(tmp_path / "test.duckdb")
        # Pre-create a writable DB so the read-only open succeeds.
        duckdb.connect(db_path).close()

        with (
            patch.dict(os.environ, {"DUCKDB_PATH": db_path}),
            db_mod.fresh_read_connection() as conn,
        ):
            held_conn = conn

        # After exit, the connection should be closed — executing should raise.
        with pytest.raises(duckdb.ConnectionException):
            held_conn.execute("SELECT 1")

    def test_does_not_pollute_singleton_cache(self, tmp_path):
        """fresh_read_connection must not touch _read_connection."""
        db_path = str(tmp_path / "test.duckdb")
        duckdb.connect(db_path).close()

        with patch.dict(os.environ, {"DUCKDB_PATH": db_path}), db_mod.fresh_read_connection():
            pass

        assert db_mod._read_connection is None

    def test_multiple_sequential_opens_succeed(self, tmp_path):
        """Each context manager call creates an independent short-lived connection."""
        db_path = str(tmp_path / "test.duckdb")
        duckdb.connect(db_path).close()

        with patch.dict(os.environ, {"DUCKDB_PATH": db_path}):
            for _ in range(3):
                with db_mod.fresh_read_connection() as conn:
                    row = conn.execute("SELECT 42").fetchone()
                    assert row[0] == 42


class TestSensorConnectionSafety:
    """Sensors must use fresh_read_connection, not get_read_connection.

    These tests enforce the contract that long-lived daemon processes do not
    hold DuckDB connections open, which would block asset write connections.
    """

    def test_data_freshness_sensor_uses_fresh_connection(self):
        """data_freshness_sensor must import fresh_read_connection, not get_read_connection.

        Sensors run in the long-lived Dagster daemon process. Using the cached
        get_read_connection() would hold a DuckDB read lock indefinitely, blocking
        asset write connections from worker subprocesses.
        """
        path = "pipeline/sensors/data_freshness.py"
        with open(path) as f:
            source = f.read()
        assert "fresh_read_connection" in source, (
            f"{path}: sensor must use fresh_read_connection() not get_read_connection()"
        )
        assert "get_read_connection" not in source, (
            f"{path}: sensor must not use get_read_connection() — caches connection in daemon"
        )

    def test_dbt_test_sensor_uses_fresh_connection(self):
        """dbt_test_after_ingest must use fresh_read_connection, not get_read_connection."""
        path = "pipeline/sensors/dbt_tests.py"
        with open(path) as f:
            source = f.read()
        assert "fresh_read_connection" in source, (
            f"{path}: sensor must use fresh_read_connection() not get_read_connection()"
        )
        assert "get_read_connection" not in source, (
            f"{path}: sensor must not use get_read_connection() — caches connection in daemon"
        )


class TestDbtDocsGenerateAsset:
    """dbt_docs_generate must not pass context= to dbt.cli()."""

    def test_uses_subprocess_not_dbt_cli(self):
        """dbt_docs_generate must use subprocess, not DbtCliResource.cli().

        DbtCliResource.cli() with context= raises a 'manifest metadata' error in plain
        @asset functions (only valid for @dbt_assets). Without context= it raises a
        different error when processing dbt events. Using subprocess avoids all of this.
        """
        path = "pipeline/assets/schema_context.py"
        with open(path) as f:
            source = f.read()
        assert "subprocess" in source, (
            f"{path}: dbt_docs_generate must use subprocess to run dbt docs generate"
        )
        assert "dbt.cli" not in source, (
            f"{path}: dbt_docs_generate must not use DbtCliResource.cli() — "
            "causes dbt-dagster event processing errors in plain @asset functions"
        )
