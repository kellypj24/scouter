"""Shared pytest fixtures."""

import duckdb
import pytest


@pytest.fixture
def duckdb_conn():
    """In-memory DuckDB connection for tests — never touches the real data file."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()
