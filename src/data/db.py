"""DuckDB connection management.

Single connection per process for the agent harness (get_read_connection).
Short-lived connections for Dagster sensors (fresh_read_connection context manager) —
sensors run in the long-lived daemon process, so they must close connections
immediately after use to avoid blocking write connections in worker subprocesses.
"""

import os
from collections.abc import Generator
from contextlib import contextmanager
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

    Do NOT call this from Dagster sensors — they run in the long-lived daemon
    process and would hold the connection indefinitely, blocking asset write
    connections. Use fresh_read_connection() instead.

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


@contextmanager
def fresh_read_connection() -> Generator[duckdb.DuckDBPyConnection]:
    """Open a short-lived read-only connection and close it on exit.

    Use this in Dagster sensors and any other code that runs in long-lived
    processes. Opens, yields, and closes — never caches.

    Yields:
        Active read-only DuckDB connection.
    """
    path = os.getenv("DUCKDB_PATH", "data/scouter.duckdb")
    conn = duckdb.connect(path, read_only=True)
    try:
        yield conn
    finally:
        conn.close()
