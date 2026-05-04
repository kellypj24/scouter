"""Print mart_eval_runs summary for the latest eval run."""

from __future__ import annotations

from pathlib import Path

import duckdb


def main() -> None:
    root = Path(__file__).parent.parent
    conn = duckdb.connect(str(root / "data" / "scouter.duckdb"), read_only=True)
    df = conn.execute("""
        WITH latest AS (
            SELECT MAX(run_at) AS run_at
            FROM main_observability.mart_eval_runs
        )
        SELECT
            fixture_id,
            CASE WHEN passed THEN '✓' ELSE '✗' END AS status,
            sql_attempts,
            fallback_used,
            chart_source,
            failures[1] AS first_failure
        FROM main_observability.mart_eval_runs
        WHERE run_at = (SELECT run_at FROM latest)
        QUALIFY ROW_NUMBER() OVER (PARTITION BY fixture_id ORDER BY started_at DESC NULLS LAST) = 1
        ORDER BY passed ASC, fixture_id
    """).df()
    conn.close()

    if df.empty:
        print("No eval results found. Run `just eval-go && just eval-load-results` first.")
        return

    passed = df["status"].eq("✓").sum()
    total = len(df)
    print(f"\nLatest eval run — {passed}/{total} passed\n")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
