"""KPI health check — runs after observability_sync to assert all KPIs are on target."""

from __future__ import annotations

import duckdb
from dagster import AssetCheckResult, AssetCheckSeverity, AssetExecutionContext, asset_check

from pipeline.assets.observability import observability_sync
from src.observability.kpis import evaluate_kpis

_DB_PATH = "data/scouter.duckdb"


@asset_check(
    asset=observability_sync,
    description="Assert all five Scouter KPIs are at or above target.",
)
def kpi_health_check(context: AssetExecutionContext) -> AssetCheckResult:
    """Evaluate all KPIs and fail the check if any are below target.

    Returns a WARN (not ERROR) on failure so a below-target KPI doesn't
    block the pipeline — it surfaces in the Dagster UI for review.

    Returns:
        AssetCheckResult with per-KPI current values as metadata.
    """
    conn = duckdb.connect(_DB_PATH, read_only=True)
    try:
        results = evaluate_kpis(conn)
    finally:
        conn.close()

    failing = [r for r in results if not r["passing"]]
    metadata = {
        r["name"]: f"{r['current']:.3f}" if r["current"] is not None else f"error: {r['error']}"
        for r in results
    }

    if failing:
        names = ", ".join(r["name"] for r in failing)
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.WARN,
            description=f"{len(failing)} KPI(s) below target: {names}",
            metadata=metadata,
        )

    return AssetCheckResult(
        passed=True,
        description="All KPIs on target.",
        metadata=metadata,
    )
