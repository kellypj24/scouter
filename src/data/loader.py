"""Raw data ingestion — CSV/Parquet → DuckDB.

Called by the Dagster ingestion asset. Can also be run directly:
    uv run python -m src.data.loader
"""

from pathlib import Path

from src.data.db import get_connection

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def ingest_raw_data() -> int:
    """Scan data/ for CSV/Parquet files and load each into a DuckDB table.

    Table name is derived from the filename stem (e.g. sp500.csv → sp500).
    Existing tables are replaced on each ingest run.

    Returns:
        Total number of rows ingested across all files.
    """
    conn = get_connection()
    total_rows = 0

    for path in sorted(DATA_DIR.glob("*.csv")):
        table = path.stem
        conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto('{path}')")
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # type: ignore[index]
        total_rows += count

    for path in sorted(DATA_DIR.glob("*.parquet")):
        table = path.stem
        conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet('{path}')")
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # type: ignore[index]
        total_rows += count

    return total_rows


if __name__ == "__main__":
    rows = ingest_raw_data()
    print(f"Ingested {rows} total rows")
