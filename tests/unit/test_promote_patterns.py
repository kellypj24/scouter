"""Unit tests for scripts/promote_patterns.py."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import yaml

# scripts/ is not a package; add project root to path so the import works.
sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.promote_patterns import (
    find_consistent_failures,
    infer_domain,
    load_existing_candidates,
    write_candidates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_eval_runs(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the mart_eval_runs view in an in-memory DuckDB.

    Uses a plain table behind a view named main_observability.mart_eval_runs
    so the function under test can query it with the same SQL.
    """
    conn.execute("CREATE SCHEMA IF NOT EXISTS main_observability")
    conn.execute("""
        CREATE TABLE main_observability.mart_eval_runs (
            fixture_id  VARCHAR      NOT NULL,
            run_at      TIMESTAMPTZ  NOT NULL,
            passed      BOOLEAN      NOT NULL,
            failures    VARCHAR[]    NOT NULL
        )
    """)


def _insert_run(
    conn: duckdb.DuckDBPyConnection,
    fixture_id: str,
    run_at: str,
    passed: bool,
    failures: list[str] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO main_observability.mart_eval_runs VALUES (?, ?, ?, ?)",
        [fixture_id, run_at, passed, failures or []],
    )


# ---------------------------------------------------------------------------
# infer_domain
# ---------------------------------------------------------------------------


class TestInferDomain:
    def test_screener(self):
        assert infer_domain("screener_top10_ytd") == "equity"

    def test_timeseries(self):
        assert infer_domain("timeseries_apple_6m") == "equity"

    def test_multistock(self):
        assert infer_domain("multistock_faang_comparison") == "equity"

    def test_moving_avg(self):
        assert infer_domain("moving_avg_apple") == "equity"

    def test_sector(self):
        assert infer_domain("sector_ytd_performance") == "sector"

    def test_risk(self):
        assert infer_domain("risk_drawdown") == "risk"

    def test_drawdown(self):
        assert infer_domain("drawdown_longest_streak") == "risk"

    def test_unanswerable(self):
        assert infer_domain("unanswerable_revenue") == "all"

    def test_unknown_prefix(self):
        assert infer_domain("mystery_fixture") == "all"


# ---------------------------------------------------------------------------
# find_consistent_failures
# ---------------------------------------------------------------------------


class TestFindConsistentFailures:
    def test_returns_fixture_failing_in_two_of_three_runs(self):
        conn = duckdb.connect(":memory:")
        _seed_eval_runs(conn)
        # 3 distinct run_at values; "bad_fixture" fails in 2 of 3
        _insert_run(
            conn, "bad_fixture", "2026-05-01T10:00:00Z", passed=False, failures=["min_rows"]
        )
        _insert_run(conn, "bad_fixture", "2026-05-02T10:00:00Z", passed=True)
        _insert_run(
            conn, "bad_fixture", "2026-05-03T10:00:00Z", passed=False, failures=["chart_type"]
        )

        results = find_consistent_failures(conn)
        fixture_ids = [r["fixture_id"] for r in results]
        assert "bad_fixture" in fixture_ids

    def test_excludes_fixture_passing_in_all_runs(self):
        conn = duckdb.connect(":memory:")
        _seed_eval_runs(conn)
        _insert_run(conn, "good_fixture", "2026-05-01T10:00:00Z", passed=True)
        _insert_run(conn, "good_fixture", "2026-05-02T10:00:00Z", passed=True)
        _insert_run(conn, "good_fixture", "2026-05-03T10:00:00Z", passed=True)

        results = find_consistent_failures(conn)
        assert all(r["fixture_id"] != "good_fixture" for r in results)

    def test_excludes_fixture_failing_only_once(self):
        conn = duckdb.connect(":memory:")
        _seed_eval_runs(conn)
        _insert_run(conn, "flaky_fixture", "2026-05-01T10:00:00Z", passed=True)
        _insert_run(conn, "flaky_fixture", "2026-05-02T10:00:00Z", passed=True)
        _insert_run(conn, "flaky_fixture", "2026-05-03T10:00:00Z", passed=False)

        results = find_consistent_failures(conn)
        assert all(r["fixture_id"] != "flaky_fixture" for r in results)

    def test_returns_empty_when_table_missing(self):
        conn = duckdb.connect(":memory:")
        # No mart_eval_runs table — should return [] not raise
        results = find_consistent_failures(conn)
        assert results == []

    def test_fail_count_populated(self):
        conn = duckdb.connect(":memory:")
        _seed_eval_runs(conn)
        _insert_run(conn, "bad_fixture", "2026-05-01T10:00:00Z", passed=False)
        _insert_run(conn, "bad_fixture", "2026-05-02T10:00:00Z", passed=False)
        _insert_run(conn, "bad_fixture", "2026-05-03T10:00:00Z", passed=False)

        results = find_consistent_failures(conn)
        assert results[0]["fail_count"] == 3


# ---------------------------------------------------------------------------
# load_existing_candidates / write_candidates
# ---------------------------------------------------------------------------


class TestCandidateIO:
    def test_load_returns_empty_when_file_missing(self, tmp_path):
        result = load_existing_candidates(tmp_path / "nonexistent.yaml")
        assert result == {"version": 1, "candidates": []}

    def test_write_creates_file(self, tmp_path):
        output = tmp_path / "candidates.yaml"
        existing = load_existing_candidates(output)
        new_candidates = [
            {
                "id": "candidate_bad_fixture",
                "source_fixture": "bad_fixture",
                "domain": "equity",
                "status": "pending_review",
                "fail_count": 2,
                "failure_reasons": [],
                "example_sql": "",
                "notes": "test",
                "generated_at": "2026-05-09",
            }
        ]
        write_candidates(output, new_candidates, existing)
        assert output.exists()

    def test_existing_promoted_not_overwritten(self, tmp_path):
        output = tmp_path / "candidates.yaml"

        # Seed a promoted entry
        promoted_entry = {
            "id": "candidate_promoted_fixture",
            "source_fixture": "promoted_fixture",
            "domain": "equity",
            "status": "promoted",
            "example_sql": "SELECT 1",
            "notes": "already promoted",
            "generated_at": "2026-04-01",
        }
        output.write_text(
            yaml.dump({"version": 1, "candidates": [promoted_entry]}, default_flow_style=False)
        )

        existing = load_existing_candidates(output)
        new_candidates = [
            {
                "id": "candidate_new_failure",
                "source_fixture": "new_failure",
                "domain": "sector",
                "status": "pending_review",
                "fail_count": 2,
                "failure_reasons": [],
                "example_sql": "",
                "notes": "auto",
                "generated_at": "2026-05-09",
            }
        ]
        write_candidates(output, new_candidates, existing)

        result = yaml.safe_load(output.read_text())
        fixtures = {c["source_fixture"] for c in result["candidates"]}
        assert "promoted_fixture" in fixtures
        statuses = {c["source_fixture"]: c["status"] for c in result["candidates"]}
        assert statuses["promoted_fixture"] == "promoted"

    def test_pending_entry_updated_not_duplicated(self, tmp_path):
        output = tmp_path / "candidates.yaml"

        existing_entry = {
            "id": "candidate_bad_fixture",
            "source_fixture": "bad_fixture",
            "domain": "equity",
            "status": "pending_review",
            "fail_count": 2,
            "failure_reasons": [],
            "example_sql": "",
            "notes": "old",
            "generated_at": "2026-05-01",
        }
        output.write_text(
            yaml.dump({"version": 1, "candidates": [existing_entry]}, default_flow_style=False)
        )

        existing = load_existing_candidates(output)
        updated_candidate = {**existing_entry, "fail_count": 3, "generated_at": "2026-05-09"}
        write_candidates(output, [updated_candidate], existing)

        result = yaml.safe_load(output.read_text())
        bad_entries = [c for c in result["candidates"] if c["source_fixture"] == "bad_fixture"]
        # Should be exactly 1 entry (updated, not duplicated)
        assert len(bad_entries) == 1
        assert bad_entries[0]["fail_count"] == 3
