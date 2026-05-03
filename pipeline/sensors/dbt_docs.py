"""dbt docs sensor — triggers dbt_docs_generate whenever a dbt build runs.

Watches manifest.json mtime. Every `dbt build` or `dbt run` regenerates
manifest.json, so this sensor fires immediately after each successful build
and requests a catalog regeneration.

Pattern mirrors obs_log_sensor: mtime cursor → RunRequest with mtime-keyed
run_key so duplicate evaluations within the same build window are no-ops.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, sensor

from pipeline.assets.schema_context import dbt_docs_generate

_MANIFEST = Path(__file__).resolve().parents[2] / "dbt" / "target" / "manifest.json"


@sensor(
    target=dbt_docs_generate,
    minimum_interval_seconds=600,  # poll at most every 10 min
    default_status=DefaultSensorStatus.RUNNING,
    description=(
        "Triggers dbt_docs_generate whenever manifest.json is updated by a dbt build. "
        "Keeps catalog.json current so schema injection has fresh column statistics."
    ),
)
def dbt_docs_sensor(context: SensorEvaluationContext) -> Iterator[RunRequest]:
    """Request a docs generate when dbt has run a new build.

    Compares manifest.json mtime to the stored cursor. A new mtime means
    dbt build succeeded and the catalog may be stale.
    The run_key is the integer mtime so each build triggers exactly one docs run.

    Args:
        context: Dagster sensor evaluation context.
    """
    if not _MANIFEST.exists():
        context.log.debug("manifest.json not found at %s — skipping", _MANIFEST)
        return

    mtime = _MANIFEST.stat().st_mtime
    last_mtime = float(context.cursor or "0")

    if mtime > last_mtime:
        context.update_cursor(str(mtime))
        context.log.info(
            "manifest.json updated (mtime %.0f > last %.0f) — requesting docs generate",
            mtime,
            last_mtime,
        )
        yield RunRequest(run_key=f"dbt_docs_{int(mtime)}")
    else:
        context.log.debug("manifest.json unchanged — no docs generate needed")
