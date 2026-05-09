"""Load assignments/eval/last_run.json into DuckDB raw_observability.eval_fixture_results.

Run after every eval-go run to make mart_eval_runs queryable:

    just eval-load-results
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import duckdb

_LOCK_RETRIES = 12        # 12 × 5s = up to 60s wait for a write lock
_LOCK_RETRY_DELAY = 5.0


def _connect_with_retry(db_path: str) -> duckdb.DuckDBPyConnection:
    """Acquire a write connection, retrying if another writer (Dagster, dbt) holds the lock.

    DuckDB raises IOException with "Conflicting lock is held" when contended. The lock
    typically clears in <30s as the other writer commits and closes its connection.
    """
    last_exc: Exception | None = None
    for attempt in range(_LOCK_RETRIES):
        try:
            return duckdb.connect(db_path)
        except duckdb.IOException as exc:
            if "Conflicting lock" not in str(exc):
                raise
            last_exc = exc
            if attempt < _LOCK_RETRIES - 1:
                wait = _LOCK_RETRY_DELAY
                print(
                    f"  DuckDB write lock held (attempt {attempt + 1}/{_LOCK_RETRIES}), "
                    f"retrying in {wait:.0f}s...",
                    file=sys.stderr,
                )
                time.sleep(wait)
    raise RuntimeError(
        f"Could not acquire DuckDB write lock after {_LOCK_RETRIES} attempts. "
        "Stop any running Dagster process (`just compose-down` or kill the dev server) "
        "and retry. Last error: " + str(last_exc)
    )


def main() -> None:
    root = Path(__file__).parent.parent
    results_path = root / "assignments" / "eval" / "last_run.json"

    if not results_path.exists():
        print(f"No results file at {results_path}. Run `just eval-go` first.")
        sys.exit(1)

    data = json.loads(results_path.read_text())
    run_at: str = data["run_at"]
    fixtures: list[dict] = data["fixtures"]

    conn = _connect_with_retry(str(root / "data" / "scouter.duckdb"))

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
