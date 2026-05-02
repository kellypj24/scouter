"""dbt test sensor — triggers dbt_test_runner when new market data is ingested.

Uses the same data freshness check as data_freshness_sensor: if MAX(date) in
historical_data has advanced since the last cursor, new data was ingested and
the full dbt test suite should re-run to validate it.

The cursor stores the latest data date as a string so each new trading day
triggers exactly one test run, regardless of how many times the sensor polls.
"""

from __future__ import annotations

import logging

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, sensor

from pipeline.assets.dbt_tests import dbt_test_runner

logger = logging.getLogger(__name__)


@sensor(
    target=dbt_test_runner,
    minimum_interval_seconds=600,  # poll every 10 min — tests are slow, no need to rush
    default_status=DefaultSensorStatus.RUNNING,
    description=(
        "Triggers dbt_test_runner whenever historical_data advances to a new date, "
        "confirming the ingested data passes all quality checks."
    ),
)
def dbt_test_after_ingest(context: SensorEvaluationContext) -> None:
    """Run dbt tests when new market data is detected.

    Compares MAX(date) in historical_data against the stored cursor. If the
    date has advanced (new ingest completed), yields a RunRequest so the full
    dbt test suite validates the freshly ingested data.

    Args:
        context: Dagster sensor evaluation context.
    """
    from src.data.db import get_read_connection

    try:
        conn = get_read_connection()
        row = conn.execute("SELECT MAX(date) FROM historical_data").fetchone()
    except Exception as exc:
        context.log.warning("Could not read historical_data for dbt test trigger: %s", exc)
        return

    if not row or not row[0]:
        return

    latest_date = str(row[0])
    if latest_date == context.cursor:
        context.log.debug(
            "historical_data unchanged (latest: %s) — dbt tests already current", latest_date
        )
        return

    context.update_cursor(latest_date)
    context.log.info(
        "New market data detected (latest: %s, was: %s) — triggering dbt tests",
        latest_date,
        context.cursor or "never",
    )
    yield RunRequest(run_key=f"dbt_test_{latest_date}")
