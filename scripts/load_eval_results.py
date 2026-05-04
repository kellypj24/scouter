"""Load assignments/eval/last_run.json into DuckDB raw_observability.eval_fixture_results.

Run after every eval-go run to make mart_eval_runs queryable:

    just eval-load-results
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb


def main() -> None:
    root = Path(__file__).parent.parent
    results_path = root / "assignments" / "eval" / "last_run.json"

    if not results_path.exists():
        print(f"No results file at {results_path}. Run `just eval-go` first.")
        sys.exit(1)

    data = json.loads(results_path.read_text())
    run_at: str = data["run_at"]
    fixtures: list[dict] = data["fixtures"]

    conn = duckdb.connect(str(root / "data" / "scouter.duckdb"))

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_observability.eval_fixture_results (
            fixture_id  VARCHAR      NOT NULL,
            run_at      TIMESTAMPTZ  NOT NULL,
            passed      BOOLEAN      NOT NULL,
            failures    VARCHAR[]    NOT NULL,
            elapsed_ms  INTEGER      NOT NULL
        )
    """)

    inserted = 0
    for fx in fixtures:
        conn.execute(
            """
            INSERT INTO raw_observability.eval_fixture_results
                (fixture_id, run_at, passed, failures, elapsed_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            [fx["id"], run_at, fx["passed"], fx["failures"], fx["elapsed_ms"]],
        )
        inserted += 1

    conn.close()
    passed = sum(1 for fx in fixtures if fx["passed"])
    print(
        f"Loaded {inserted} fixture results "
        f"({passed}/{inserted} passed, run_at={run_at})"
    )


if __name__ == "__main__":
    main()
