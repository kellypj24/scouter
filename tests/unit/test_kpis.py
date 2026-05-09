"""Unit tests for src/observability/kpis.py."""

from pathlib import Path

import duckdb
import pytest

from src.observability.kpis import TARGETS, _passes, evaluate_kpis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the three observability mart tables."""
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA main_observability")

    conn.execute("""
        CREATE TABLE main_observability.mart_eval_runs (
            fixture_id   VARCHAR,
            run_at       TIMESTAMP,
            passed       BOOLEAN,
            sql_attempts INTEGER,
            domain       VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE main_observability.mart_fallback_analysis (
            domain          VARCHAR,
            total_requests  INTEGER,
            fallback_count  INTEGER,
            fallback_rate_pct DOUBLE
        )
    """)
    conn.execute("""
        CREATE TABLE main_observability.mart_request_metrics (
            request_id VARCHAR,
            latency_ms INTEGER
        )
    """)
    return conn


def _seed_eval_runs(conn: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    """Insert rows into mart_eval_runs. Tuple: (fixture_id, run_at, passed, sql_attempts, domain)."""
    conn.executemany(
        "INSERT INTO main_observability.mart_eval_runs VALUES (?, ?, ?, ?, ?)", rows
    )


# ---------------------------------------------------------------------------
# _passes
# ---------------------------------------------------------------------------


class TestPasses:
    def test_gte_passes_when_current_equals_target(self):
        assert _passes(1.0, 1.0, "gte") is True

    def test_gte_passes_when_current_above_target(self):
        assert _passes(0.95, 0.80, "gte") is True

    def test_gte_fails_when_current_below_target(self):
        assert _passes(0.79, 0.80, "gte") is False

    def test_lte_passes_when_current_equals_target(self):
        assert _passes(0.10, 0.10, "lte") is True

    def test_lte_passes_when_current_below_target(self):
        assert _passes(0.05, 0.10, "lte") is True

    def test_lte_fails_when_current_above_target(self):
        assert _passes(0.15, 0.10, "lte") is False


# ---------------------------------------------------------------------------
# evaluate_kpis — structure
# ---------------------------------------------------------------------------


class TestEvaluateKpisStructure:
    def test_returns_all_five_kpis(self):
        conn = _make_conn()
        results = evaluate_kpis(conn)
        names = {r["name"] for r in results}
        expected = {t.name for t in TARGETS}
        assert names == expected

    def test_each_result_has_required_keys(self):
        conn = _make_conn()
        results = evaluate_kpis(conn)
        required = {"name", "description", "target", "current", "passing", "direction", "unit", "error"}
        for r in results:
            assert required <= r.keys()

    def test_missing_table_sets_error_field(self):
        conn = duckdb.connect(":memory:")  # no schemas created
        results = evaluate_kpis(conn)
        # All KPIs should fail gracefully with an error
        assert all(r["error"] is not None for r in results)
        assert all(r["passing"] is False for r in results)


# ---------------------------------------------------------------------------
# eval_pass_rate
# ---------------------------------------------------------------------------


class TestEvalPassRate:
    def test_all_passing(self):
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", True, 1, "equity"),
            ("fix_b", "2026-05-09 10:00:00", True, 1, "sector"),
        ])
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "eval_pass_rate")
        assert kpi["current"] == pytest.approx(1.0)
        assert kpi["passing"] is True

    def test_partial_passing(self):
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", True, 1, "equity"),
            ("fix_b", "2026-05-09 10:00:00", False, 2, "sector"),
        ])
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "eval_pass_rate")
        assert kpi["current"] == pytest.approx(0.5)
        assert kpi["passing"] is False

    def test_empty_table_returns_zero(self):
        conn = _make_conn()
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "eval_pass_rate")
        assert kpi["current"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# fallback_rate
# ---------------------------------------------------------------------------


class TestFallbackRate:
    def test_below_target_passes(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO main_observability.mart_fallback_analysis VALUES (?, ?, ?, ?)",
            ("equity", 100, 5, 5.0),
        )
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "fallback_rate")
        assert kpi["current"] == pytest.approx(0.05)
        assert kpi["passing"] is True

    def test_above_target_fails(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO main_observability.mart_fallback_analysis VALUES (?, ?, ?, ?)",
            ("equity", 100, 20, 20.0),
        )
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "fallback_rate")
        assert kpi["current"] == pytest.approx(0.20)
        assert kpi["passing"] is False


# ---------------------------------------------------------------------------
# first_attempt_sql_rate
# ---------------------------------------------------------------------------


class TestFirstAttemptSqlRate:
    def test_all_first_attempt(self):
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", True, 1, "equity"),
            ("fix_b", "2026-05-09 10:00:00", True, 1, "sector"),
        ])
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "first_attempt_sql_rate")
        assert kpi["current"] == pytest.approx(1.0)
        assert kpi["passing"] is True

    def test_half_first_attempt(self):
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", True, 1, "equity"),
            ("fix_b", "2026-05-09 10:00:00", False, 2, "sector"),
        ])
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "first_attempt_sql_rate")
        assert kpi["current"] == pytest.approx(0.5)
        assert kpi["passing"] is False


# ---------------------------------------------------------------------------
# pattern_coverage
# ---------------------------------------------------------------------------


class TestPatternCoverage:
    def test_no_failures_returns_full_coverage(self):
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", True, 1, "equity"),
        ])
        results = evaluate_kpis(conn)
        kpi = next(r for r in results if r["name"] == "pattern_coverage")
        assert kpi["current"] == pytest.approx(1.0)
        assert kpi["passing"] is True

    def test_missing_patterns_file_returns_zero(self, tmp_path: Path):
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", False, 2, "equity"),
        ])
        results = evaluate_kpis(conn, patterns_file=tmp_path / "nonexistent.yaml")
        kpi = next(r for r in results if r["name"] == "pattern_coverage")
        assert kpi["current"] == pytest.approx(0.0)
        assert kpi["passing"] is False

    def test_covered_domain_passes(self, tmp_path: Path):
        pf = tmp_path / "patterns.yaml"
        pf.write_text("patterns:\n  - id: p1\n    domain: equity\n    example_sql: SELECT 1\n")
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", False, 2, "equity"),
        ])
        results = evaluate_kpis(conn, patterns_file=pf)
        kpi = next(r for r in results if r["name"] == "pattern_coverage")
        assert kpi["current"] == pytest.approx(1.0)
        assert kpi["passing"] is True

    def test_uncovered_domain_fails(self, tmp_path: Path):
        pf = tmp_path / "patterns.yaml"
        pf.write_text("patterns:\n  - id: p1\n    domain: equity\n    example_sql: SELECT 1\n")
        conn = _make_conn()
        _seed_eval_runs(conn, [
            ("fix_a", "2026-05-09 10:00:00", False, 2, "sector"),
        ])
        results = evaluate_kpis(conn, patterns_file=pf)
        kpi = next(r for r in results if r["name"] == "pattern_coverage")
        assert kpi["current"] == pytest.approx(0.0)
        assert kpi["passing"] is False
