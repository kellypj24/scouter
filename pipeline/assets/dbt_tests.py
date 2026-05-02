"""dbt test runner asset.

Runs `dbt test` after market data ingestion and materialises results directly
into DuckDB raw_observability — no SQLite middleman needed since this runs
inside the Dagster process which already owns a DuckDB write connection.

Triggered by dbt_test_after_ingest sensor whenever historical_data is updated.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dagster import asset
from dagster_dbt import DbtCliResource

from src.data.db import get_connection

logger = logging.getLogger(__name__)

_SCHEMA = "raw_observability"
_DBT_PROJECT_DIR = Path(__file__).resolve().parents[2] / "dbt"


def _parse_results(run_results: dict) -> list[dict]:
    """Flatten dbt run_results.json into a list of row dicts."""
    run_at = run_results.get("metadata", {}).get("generated_at") or datetime.now(UTC).isoformat()
    rows = []
    for result in run_results.get("results", []):
        uid = result.get("unique_id", "")
        parts = uid.split(".")
        # unique_id: test.{project}.{test_name}.{hash}
        test_name = parts[2] if len(parts) > 2 else uid
        # Best-effort model extraction: test names are {type}_{model}_{column}
        # e.g. not_null_stg_prices_ticker → stg_prices
        model = _extract_model(test_name)
        rows.append(
            {
                "test_unique_id": uid,
                "test_name": test_name,
                "model": model,
                "status": result.get("status", "unknown"),
                "execution_time_s": result.get("execution_time"),
                "failures": result.get("failures") or 0,
                "message": result.get("message"),
                "run_at": run_at,
            }
        )
    return rows


def _extract_model(test_name: str) -> str | None:
    """Pull a model name from a dbt generic test name heuristically.

    Generic test names follow {test_type}_{model}_{column}, e.g.:
      not_null_stg_prices_ticker  → stg_prices
      unique_dim_company_ticker   → dim_company
    """
    for prefix in ("not_null_", "unique_", "accepted_values_", "relationships_"):
        if test_name.startswith(prefix):
            remainder = test_name[len(prefix):]
            # Take the longest matching staging/mart prefix by splitting on '_'
            # and walking forward until we hit a known dbt name pattern
            parts = remainder.split("_")
            # Model names have at least 2 parts (e.g. stg_prices, dim_company)
            if len(parts) >= 3:
                return "_".join(parts[:2])  # e.g. stg_prices, dim_company, mart_equity
            if len(parts) == 2:
                return remainder
    return None


@asset(
    group_name="observability",
    compute_kind="duckdb",
    required_resource_keys={"dbt"},
    description=(
        "Run dbt test suite and write pass/fail results directly to "
        "DuckDB raw_observability for analysis alongside request telemetry."
    ),
)
def dbt_test_runner(context) -> None:  # type: ignore[no-untyped-def]
    """Execute dbt tests and store results in DuckDB.

    Runs the full dbt test suite regardless of pass/fail — results are always
    captured so flapping tests and regressions are visible in the marts.
    Writing directly to DuckDB (not SQLite) since this runs inside the
    Dagster process which has synchronous access to the database.

    Args:
        context: Dagster asset execution context.
    """
    dbt: DbtCliResource = context.resources.dbt

    # Run dbt test — capture results even when tests fail
    try:
        dbt.cli(["test"], context=context).wait()
        context.log.info("dbt test completed successfully")
    except Exception as exc:
        context.log.warning("dbt test finished with failures: %s", exc)

    results_path = _DBT_PROJECT_DIR / "target" / "run_results.json"
    if not results_path.exists():
        context.log.warning("run_results.json not found at %s — no results to store", results_path)
        return

    with open(results_path) as f:
        run_results = json.load(f)

    rows = _parse_results(run_results)
    if not rows:
        context.log.info("No dbt test results in run_results.json")
        return

    df = pd.DataFrame(rows)  # noqa: F841 — referenced by name in DuckDB SQL below
    conn = get_connection()
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    conn.execute(f"DROP TABLE IF EXISTS {_SCHEMA}.dbt_test_results")
    conn.execute(f"CREATE TABLE {_SCHEMA}.dbt_test_results AS SELECT * FROM df")

    pass_count = sum(1 for r in rows if r["status"] == "pass")
    fail_count = sum(1 for r in rows if r["status"] in ("fail", "error"))
    context.log.info(
        "dbt test results stored — %d passed, %d failed (%d total)",
        pass_count,
        fail_count,
        len(rows),
    )
    context.add_output_metadata(
        {
            "total_tests": len(rows),
            "passing": pass_count,
            "failing": fail_count,
            "run_at": rows[0]["run_at"] if rows else None,
        }
    )
