"""Data freshness sensor — triggers raw_market_data when DuckDB data goes stale.

Event-based alternative to a cron schedule: the sensor polls every 30 minutes
and fires only when data is genuinely stale, not on a fixed clock. This means:
  - No missed windows when the laptop sleeps (catches up on next daemon cycle)
  - No redundant runs when the machine was on but data was already fresh
  - Self-healing: if an ingest fails, next sensor cycle re-triggers automatically

Production analogue: S3 event notification or Kafka message replaces the mtime
check; the sensor body becomes an event consumer rather than a poller.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, sensor

from pipeline.assets.ingestion import raw_market_data

logger = logging.getLogger(__name__)

_STALE_AFTER_DAYS = 1


@sensor(
    target=raw_market_data,
    minimum_interval_seconds=1800,  # poll at most every 30 min
    default_status=DefaultSensorStatus.RUNNING,
    description=(
        "Triggers raw_market_data when historical_data is more than "
        f"{_STALE_AFTER_DAYS} day(s) old. Replaces the daily cron schedule."
    ),
)
def data_freshness_sensor(context: SensorEvaluationContext) -> Iterator[RunRequest]:
    """Request a market data refresh when DuckDB data is stale.

    Checks MAX(date) in historical_data. If it's older than _STALE_AFTER_DAYS,
    yields a RunRequest with a date-scoped run_key so at most one refresh fires
    per calendar day regardless of how many times the sensor evaluates.

    Args:
        context: Dagster sensor evaluation context.
    """
    from src.data.db import fresh_read_connection

    try:
        with fresh_read_connection() as conn:
            row = conn.execute("SELECT MAX(date) FROM historical_data").fetchone()
    except Exception as exc:
        context.log.warning("Freshness check failed — skipping: %s", exc)
        return

    today = date.today()

    if not row or not row[0]:
        context.log.info("historical_data is empty — triggering initial ingest")
        yield RunRequest(run_key=f"init_{today.isoformat()}")
        return

    latest = row[0]
    if hasattr(latest, "date"):
        latest = latest.date()
    elif isinstance(latest, str):
        latest = date.fromisoformat(latest)

    age_days = (today - latest).days
    if age_days >= _STALE_AFTER_DAYS:
        context.log.info(
            "Market data is %d day(s) old (latest: %s) — requesting refresh",
            age_days,
            latest,
        )
        yield RunRequest(run_key=f"freshness_{today.isoformat()}")
    else:
        context.log.debug("Market data is current (latest: %s) — no action needed", latest)
