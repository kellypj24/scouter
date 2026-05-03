"""Observability sync sensor — triggers observability_sync when logs change.

Uses file mtime as the event signal: when the SQLite log file is modified
(by a user request hitting the FastAPI service), the sensor detects the change
and triggers a sync into DuckDB.

The cursor persists the last-seen mtime across sensor evaluations so only
genuine changes (new requests logged) trigger a sync, not idle polling.

Production analogue: replace the mtime check with a message from an event
bus (SQS, Pub/Sub) that the FastAPI service publishes after each request batch.
The sensor body becomes a queue consumer; the rest of the pipeline is unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, sensor

from pipeline.assets.observability import observability_sync

_LOGS_DB = Path(os.getenv("SCOUTER_LOGS_DB", "logs/scouter_logs.db"))


@sensor(
    target=observability_sync,
    minimum_interval_seconds=300,  # poll at most every 5 min
    default_status=DefaultSensorStatus.RUNNING,
    description=(
        "Triggers observability_sync whenever the Scouter SQLite log file "
        "is modified. Replaces the hourly cron schedule."
    ),
)
def obs_log_sensor(context: SensorEvaluationContext) -> Iterator[RunRequest]:
    """Sync observability logs into DuckDB when new requests have been logged.

    Compares the SQLite file's mtime against the stored cursor. If the file
    was modified since the last evaluation, requests an observability sync.
    The run_key is the integer mtime so each distinct modification triggers
    exactly one sync regardless of how many times the sensor polls.

    Args:
        context: Dagster sensor evaluation context.
    """
    if not _LOGS_DB.exists():
        context.log.debug("No observability log at %s — nothing to sync", _LOGS_DB)
        return

    mtime = _LOGS_DB.stat().st_mtime
    last_mtime = float(context.cursor or "0")

    if mtime > last_mtime:
        context.update_cursor(str(mtime))
        context.log.info(
            "Observability log modified (mtime %.0f > last %.0f) — requesting sync",
            mtime,
            last_mtime,
        )
        yield RunRequest(run_key=f"obs_{int(mtime)}")
    else:
        context.log.debug("Observability log unchanged — no sync needed")
