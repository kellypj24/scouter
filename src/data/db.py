"""DuckDB connection management.

Single connection per process. All agent queries go through get_connection().
"""

import os
from pathlib import Path

import duckdb

_connection: duckdb.DuckDBPyConnection | None = None
_read_connection: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the shared read-write DuckDB connection (Dagster / pipeline use).

    Reads DUCKDB_PATH from environment, falling back to data/scouter.duckdb.

    Returns:
        Active DuckDB connection.
    """
    global _connection
    if _connection is None:
        path = os.getenv("DUCKDB_PATH", "data/scouter.duckdb")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _connection = duckdb.connect(path)
    return _connection


def get_read_connection() -> duckdb.DuckDBPyConnection:
    """Return a shared read-only DuckDB connection (agent / app use).

    Read-only mode allows multiple concurrent readers without conflicting with
    the pipeline writer. All agent queries are SELECT-only, so this is safe.

    Reads DUCKDB_PATH from environment, falling back to data/scouter.duckdb.

    Returns:
        Active read-only DuckDB connection.
    """
    global _read_connection
    if _read_connection is None:
        path = os.getenv("DUCKDB_PATH", "data/scouter.duckdb")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _read_connection = duckdb.connect(path, read_only=True)
    return _read_connection
