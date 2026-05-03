"""Observability sync asset.

Centralises all telemetry into a single DuckDB analytical store:
  1. Scouter request telemetry — SQLite written by the FastAPI service
  2. Dagster pipeline telemetry — run history from the Dagster instance

Pattern: operational stores (SQLite, Dagster DB) → Dagster ELT → DuckDB (analytical)

In production, swap SQLite for Postgres by changing _read_sqlite only.
The Dagster telemetry path scales to any Dagster deployment automatically.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dagster import DagsterInstance, asset

from src.data.db import get_connection

_LOGS_DB = Path(os.getenv("SCOUTER_LOGS_DB", "logs/scouter_logs.db"))
_SCHEMA = "raw_observability"


def _read_sqlite(logs_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read requests and spans tables from SQLite into DataFrames."""
    with sqlite3.connect(logs_path) as conn:
        conn.row_factory = sqlite3.Row
        requests = pd.DataFrame(
            [dict(r) for r in conn.execute("SELECT * FROM requests ORDER BY started_at").fetchall()]
        )
        spans = pd.DataFrame(
            [dict(r) for r in conn.execute("SELECT * FROM spans ORDER BY started_at").fetchall()]
        )
    return requests, spans


def _read_dagster_runs(instance: DagsterInstance) -> pd.DataFrame:
    """Pull recent Dagster pipeline run history into a flat DataFrame.

    Captures run_id, job_name, status, start/end time, and duration so the
    same dbt observability pipeline can analyse both agent requests and
    data pipeline health side-by-side.
    """
    runs = instance.get_runs()
    if not runs:
        return pd.DataFrame()

    rows = []
    for run in runs:
        start_ts = (
            datetime.fromtimestamp(run.start_time, tz=UTC).isoformat() if run.start_time else None
        )
        end_ts = datetime.fromtimestamp(run.end_time, tz=UTC).isoformat() if run.end_time else None
        duration_ms = (
            int((run.end_time - run.start_time) * 1000) if run.start_time and run.end_time else None
        )
        rows.append(
            {
                "run_id": run.run_id,
                "job_name": run.job_name,
                "status": run.status.value,
                "started_at": start_ts,
                "completed_at": end_ts,
                "duration_ms": duration_ms,
                "tags": str(run.tags) if run.tags else None,
            }
        )
    return pd.DataFrame(rows)


def _materialize(conn: object, df: pd.DataFrame, table: str) -> None:  # type: ignore[type-arg]
    """Full-refresh load of a DataFrame into DuckDB."""
    conn.execute(f"DROP TABLE IF EXISTS {_SCHEMA}.{table}")  # type: ignore[union-attr]
    conn.execute(f"CREATE TABLE {_SCHEMA}.{table} AS SELECT * FROM df")  # type: ignore[union-attr]


@asset(
    group_name="observability",
    compute_kind="duckdb",
    description=(
        "Sync Scouter request telemetry (SQLite) and Dagster pipeline run history "
        "into DuckDB raw_observability schema for unified dbt analysis."
    ),
)
def observability_sync(context) -> None:  # type: ignore[no-untyped-def]
    """Load all observability data into DuckDB for dbt transformation.

    Syncs two sources:
      - Scouter request/span telemetry from SQLite (FastAPI service writes this)
      - Dagster pipeline run history from the active Dagster instance

    Performs a full refresh — idempotent and safe for telemetry table sizes.

    Args:
        context: Dagster asset execution context.
    """
    conn = get_connection()
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")

    # --- Scouter request telemetry (SQLite) ---
    scouter_requests = 0
    if not _LOGS_DB.exists():
        context.log.info("No Scouter observability logs at %s — skipping", _LOGS_DB)
    else:
        requests_df, spans_df = _read_sqlite(_LOGS_DB)
        if requests_df.empty:
            context.log.info("Scouter observability log is empty")
        else:
            _materialize(conn, requests_df, "requests")
            _materialize(conn, spans_df, "spans")
            scouter_requests = len(requests_df)
            context.log.info(
                "Scouter telemetry synced — %d requests, %d spans",
                len(requests_df),
                len(spans_df),
            )

    # --- Dagster pipeline run history ---
    instance = DagsterInstance.get()
    dagster_runs_df = _read_dagster_runs(instance)
    dagster_runs = len(dagster_runs_df)
    if dagster_runs_df.empty:
        context.log.info("No Dagster run history found")
    else:
        _materialize(conn, dagster_runs_df, "dagster_runs")
        context.log.info("Dagster runs synced — %d runs", dagster_runs)

    context.add_output_metadata(
        {
            "scouter_requests_synced": scouter_requests,
            "dagster_runs_synced": dagster_runs,
            "source_db": str(_LOGS_DB),
        }
    )
