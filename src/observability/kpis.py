"""KPI targets and evaluation for the Scouter observability layer.

KPIs are computed against the DuckDB observability marts. Each KPI has a
target, direction (gte/lte), and unit. evaluate_kpis() returns current vs.
target for all five KPIs and is safe to call against an empty or partial DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)

_PATTERNS_FILE = Path(__file__).parents[2] / "learned_patterns.yaml"


@dataclass(frozen=True)
class KPITarget:
    """A single KPI definition.

    Attributes:
        name: Machine-readable identifier.
        description: Human-readable description for display.
        target: Numeric threshold.
        direction: "gte" (current >= target passes) or "lte" (current <= target passes).
        unit: Display unit — "ratio" or "ms".
    """

    name: str
    description: str
    target: float
    direction: str
    unit: str


TARGETS: list[KPITarget] = [
    KPITarget(
        "eval_pass_rate",
        "Eval fixture pass rate (latest run)",
        1.0,
        "gte",
        "ratio",
    ),
    KPITarget(
        "fallback_rate",
        "SQL fallback rate across all domains",
        0.10,
        "lte",
        "ratio",
    ),
    KPITarget(
        "first_attempt_sql_rate",
        "SQL success on first attempt (latest eval run)",
        0.80,
        "gte",
        "ratio",
    ),
    KPITarget(
        "p95_request_latency_ms",
        "P95 end-to-end request latency",
        30_000.0,
        "lte",
        "ms",
    ),
    KPITarget(
        "pattern_coverage",
        "Fraction of failing fixture domains with a learned pattern",
        1.0,
        "gte",
        "ratio",
    ),
]


def _passes(current: float, target: float, direction: str) -> bool:
    return current >= target if direction == "gte" else current <= target


def evaluate_kpis(
    conn: duckdb.DuckDBPyConnection,
    patterns_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Compute current value for each KPI and compare against its target.

    Args:
        conn: Read-only DuckDB connection with observability marts available.
        patterns_file: Path to learned_patterns.yaml. Defaults to repo root.

    Returns:
        List of dicts with keys: name, description, target, current, passing,
        direction, unit, error. current and passing are None/False if the
        underlying mart table is missing or the query fails.
    """
    results = []
    pf = patterns_file or _PATTERNS_FILE
    for kpi in TARGETS:
        try:
            current = _fetch(conn, kpi.name, pf)
            results.append(
                {
                    "name": kpi.name,
                    "description": kpi.description,
                    "target": kpi.target,
                    "current": current,
                    "passing": _passes(current, kpi.target, kpi.direction),
                    "direction": kpi.direction,
                    "unit": kpi.unit,
                    "error": None,
                }
            )
        except Exception as exc:
            logger.debug("KPI %s unavailable: %s", kpi.name, exc)
            results.append(
                {
                    "name": kpi.name,
                    "description": kpi.description,
                    "target": kpi.target,
                    "current": None,
                    "passing": False,
                    "direction": kpi.direction,
                    "unit": kpi.unit,
                    "error": str(exc),
                }
            )
    return results


def _fetch(conn: duckdb.DuckDBPyConnection, name: str, patterns_file: Path) -> float:
    if name == "eval_pass_rate":
        row = conn.execute("""
            SELECT COUNT_IF(passed) * 1.0 / NULLIF(COUNT(*), 0)
            FROM main_observability.mart_eval_runs
            WHERE run_at = (SELECT MAX(run_at) FROM main_observability.mart_eval_runs)
        """).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    if name == "fallback_rate":
        row = conn.execute("""
            SELECT COALESCE(
                SUM(fallback_count) * 1.0 / NULLIF(SUM(total_requests), 0),
                0.0
            )
            FROM main_observability.mart_fallback_analysis
        """).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    if name == "first_attempt_sql_rate":
        row = conn.execute("""
            SELECT COUNT_IF(sql_attempts = 1) * 1.0 / NULLIF(COUNT(*), 0)
            FROM main_observability.mart_eval_runs
            WHERE run_at = (SELECT MAX(run_at) FROM main_observability.mart_eval_runs)
        """).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    if name == "p95_request_latency_ms":
        row = conn.execute("""
            SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
            FROM main_observability.mart_request_metrics
            WHERE latency_ms IS NOT NULL
        """).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    if name == "pattern_coverage":
        return _pattern_coverage(conn, patterns_file)

    raise ValueError(f"Unknown KPI name: {name!r}")


def _pattern_coverage(conn: duckdb.DuckDBPyConnection, patterns_file: Path) -> float:
    """Fraction of failing fixture domains that have at least one learned pattern."""
    rows = conn.execute("""
        SELECT DISTINCT domain
        FROM main_observability.mart_eval_runs
        WHERE run_at = (SELECT MAX(run_at) FROM main_observability.mart_eval_runs)
          AND NOT passed
          AND domain IS NOT NULL
    """).fetchall()
    failing_domains = {row[0] for row in rows if row[0]}

    if not failing_domains:
        return 1.0  # No failures → trivially covered

    if not patterns_file.exists():
        return 0.0

    import yaml  # local import — only needed for this KPI

    with patterns_file.open() as f:
        data = yaml.safe_load(f) or {}
    pattern_domains = {p.get("domain", "all") for p in data.get("patterns", [])}

    covered = failing_domains & pattern_domains
    return len(covered) / len(failing_domains)
