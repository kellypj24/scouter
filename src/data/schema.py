"""Schema introspection and prompt injection helpers.

The agent always receives the current DuckDB schema before generating SQL.
This module builds that schema string from live DuckDB metadata.
"""

import duckdb


def get_schema_prompt(conn: duckdb.DuckDBPyConnection) -> str:
    """Return a compact schema description suitable for LLM prompt injection.

    Queries DuckDB information_schema to list all user tables and their columns.

    Args:
        conn: Active DuckDB connection.

    Returns:
        Multi-line string describing available tables and columns.
    """
    rows = conn.execute("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
    """).fetchall()

    if not rows:
        return "No tables found in database."

    tables: dict[str, list[str]] = {}
    for table, column, dtype in rows:
        tables.setdefault(table, []).append(f"  {column} ({dtype})")

    lines = []
    for table, cols in tables.items():
        lines.append(f"Table: {table}")
        lines.extend(cols)
    return "\n".join(lines)
