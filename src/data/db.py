"""DuckDB connection management.

Single connection per process. All agent queries go through get_connection().
"""

import os
from pathlib import Path

import duckdb

_connection: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the shared DuckDB connection, creating it if necessary.

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
