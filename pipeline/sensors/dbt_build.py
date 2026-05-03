"""dbt build sensor — triggers scouter_dbt_assets when new market data is ingested.

Mirrors the dbt_test_after_ingest sensor but targets the transformation step:
raw_market_data populates raw tables; this sensor triggers dbt run to rebuild
all marts from that fresh data.

Without this sensor the pipeline was: ingest raw → (nothing) → stale marts.
With it: ingest raw → dbt build → fresh marts → dbt test (via separate sensor).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, sensor

from pipeline.assets.transformations import _dbt_assets_list

logger = logging.getLogger(__name__)


def check_and_yield(context: SensorEvaluationContext) -> Iterator[RunRequest]:
    """Core sensor logic — check historical_data freshness and yield a RunRequest if stale.

    Extracted so it can be unit-tested regardless of whether the dbt manifest
    exists in the test environment (the manifest controls which sensor variant
    is registered, but the logic is the same either way).

    Args:
        context: Dagster sensor evaluation context.
    """
    from src.data.db import fresh_read_connection

    try:
        with fresh_read_connection() as conn:
            row = conn.execute("SELECT MAX(date) FROM historical_data").fetchone()
    except Exception as exc:
        context.log.warning("Could not read historical_data for dbt build trigger: %s", exc)
        return

    if not row or not row[0]:
        return

    latest_date = str(row[0])
    if latest_date == context.cursor:
        context.log.debug(
            "historical_data unchanged (latest: %s) — dbt marts already current", latest_date
        )
        return

    context.update_cursor(latest_date)
    context.log.info(
        "New market data detected (latest: %s, was: %s) — triggering dbt build",
        latest_date,
        context.cursor or "never",
    )
    yield RunRequest(run_key=f"dbt_build_{latest_date}")


if _dbt_assets_list:

    @sensor(
        target=_dbt_assets_list[0],
        minimum_interval_seconds=600,
        default_status=DefaultSensorStatus.RUNNING,
        description=(
            "Triggers scouter_dbt_assets (dbt build) whenever historical_data advances "
            "to a new date, keeping all marts current after each market data ingest."
        ),
    )
    def dbt_build_after_ingest(context: SensorEvaluationContext) -> Iterator[RunRequest]:
        """Rebuild dbt marts when new market data is detected.

        Args:
            context: Dagster sensor evaluation context.
        """
        yield from check_and_yield(context)

else:
    # Manifest not yet compiled (e.g. fresh clone before first dbt build).
    # Register a no-op so imports don't fail; activate by running `just dbt-docs`.
    @sensor(
        minimum_interval_seconds=600,
        default_status=DefaultSensorStatus.RUNNING,
        description="No-op — dbt manifest not yet compiled. Run `just dbt-docs` to activate.",
    )
    def dbt_build_after_ingest(
        context: SensorEvaluationContext,
    ) -> Iterator[RunRequest]:
        """No-op sensor — dbt manifest not yet compiled."""
        context.log.info("dbt manifest not found — skipping dbt build trigger")
        return
        yield  # pragma: no cover
