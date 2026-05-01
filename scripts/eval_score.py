"""Scouter eval scorer — runs all fixtures and reports pass/fail.

Loads assignments/eval/fixtures.yaml, runs each question through the full pipeline,
scores each against its expected properties, and prints a summary table. Exits with
code 1 if any fixture fails so this can run in CI.

Usage:
    uv run python scripts/eval_score.py
    uv run python scripts/eval_score.py --filter screener
    uv run python scripts/eval_score.py --chart-dir /tmp/scouter_eval
    uv run python scripts/eval_score.py --fail-fast
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich import box

from scripts.eval_runner import RunResult, BlockResult, _run

console = Console()
logging.basicConfig(level=logging.WARNING)

_FIXTURE_PATH = Path(__file__).parent.parent / "assignments" / "eval" / "fixtures.yaml"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class FixtureResult:
    fixture_id: str
    question: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None
    elapsed: float = 0.0
    run: RunResult | None = None


def _score(run: RunResult, expect: dict[str, Any]) -> list[CheckResult]:
    """Score a RunResult against the fixture expectations. Returns all checks."""
    checks: list[CheckResult] = []

    # ── Block count ──────────────────────────────────────────────────────────
    max_blocks = expect.get("max_blocks", 2)
    checks.append(CheckResult(
        "block_count",
        run.block_count <= max_blocks,
        f"{run.block_count} block(s) (max {max_blocks})",
    ))

    # ── Fallback ─────────────────────────────────────────────────────────────
    if not expect.get("fallback", True):
        checks.append(CheckResult(
            "no_fallback",
            not run.fallback_used,
            "rule-based fallback SQL was used" if run.fallback_used else "",
        ))

    # Unanswerable path: we expect all blocks to have no SQL / 0 rows.
    if expect.get("unanswerable", False):
        all_empty = all(b.row_count == 0 for b in run.blocks)
        any_no_sql = any(b.sql == "" for b in run.blocks)
        checks.append(CheckResult(
            "unanswerable_block",
            all_empty and any_no_sql,
            "expected 0-row block with no SQL" if not (all_empty and any_no_sql) else "",
        ))
        return checks  # nothing else to check for unanswerable fixtures

    # ── Data presence ─────────────────────────────────────────────────────────
    min_rows = expect.get("min_rows", 1)
    best_rows = max((b.row_count for b in run.blocks), default=0)
    checks.append(CheckResult(
        "min_rows",
        best_rows >= min_rows,
        f"best block had {best_rows} rows (need {min_rows})",
    ))

    # For per-block checks, use the block with the most rows.
    primary = max(run.blocks, key=lambda b: b.row_count, default=None)
    if primary is None:
        return checks

    # ── Chart type ────────────────────────────────────────────────────────────
    expected_chart = expect.get("chart_type")
    if expected_chart:
        got = primary.chart_type
        checks.append(CheckResult(
            "chart_type",
            got == expected_chart,
            f"got {got!r}, expected {expected_chart!r}",
        ))
        checks.append(CheckResult(
            "chart_built",
            primary.chart_built,
            "chart spec present but figure failed to build" if primary.chart_type else "no chart spec",
        ))

    # ── Color col ─────────────────────────────────────────────────────────────
    if expect.get("color_col_required", False):
        checks.append(CheckResult(
            "color_col",
            primary.color_col is not None,
            f"color_col={primary.color_col!r} (should be non-null for multi-entity chart)",
        ))

    # ── SQL table ─────────────────────────────────────────────────────────────
    sql_table = expect.get("sql_table")
    if sql_table and primary.sql:
        checks.append(CheckResult(
            "sql_table",
            sql_table.lower() in primary.sql.lower(),
            f"expected {sql_table!r} in SQL",
        ))

    # ── SQL must-not-contain ──────────────────────────────────────────────────
    sql_not = expect.get("sql_not_contains")
    if sql_not and primary.sql:
        checks.append(CheckResult(
            "sql_clean",
            sql_not.lower() not in primary.sql.lower(),
            f"SQL must not contain {sql_not!r}",
        ))

    return checks


async def _run_fixture(fixture: dict[str, Any], chart_dir: Path | None) -> FixtureResult:
    fixture_id = fixture["id"]
    question = fixture["question"]
    expect = fixture.get("expect", {})
    t0 = time.monotonic()
    try:
        run = await _run(question, chart_dir)
        checks = _score(run, expect)
        passed = all(c.passed for c in checks)
        return FixtureResult(
            fixture_id=fixture_id,
            question=question,
            passed=passed,
            checks=checks,
            elapsed=time.monotonic() - t0,
            run=run,
        )
    except Exception as exc:
        return FixtureResult(
            fixture_id=fixture_id,
            question=question,
            passed=False,
            error=str(exc),
            elapsed=time.monotonic() - t0,
        )


def _render_summary(results: list[FixtureResult]) -> None:
    table = Table(box=box.ROUNDED, show_lines=True)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Question", max_width=50)
    table.add_column("Status", justify="center", no_wrap=True)
    table.add_column("Elapsed", justify="right", no_wrap=True)
    table.add_column("Failures")

    for fr in results:
        status = "[green]PASS[/green]" if fr.passed else "[red]FAIL[/red]"
        failures: list[str] = []

        if fr.error:
            failures.append(f"[red]exception: {fr.error[:80]}[/red]")
        else:
            for c in fr.checks:
                if not c.passed:
                    failures.append(f"[red]{c.name}[/red]: {c.detail}")

        table.add_row(
            fr.fixture_id,
            fr.question[:50] + ("…" if len(fr.question) > 50 else ""),
            status,
            f"{fr.elapsed:.1f}s",
            "\n".join(failures) if failures else "[dim]—[/dim]",
        )

    console.print()
    console.print(table)

    n_pass = sum(1 for r in results if r.passed)
    n_total = len(results)
    total_time = sum(r.elapsed for r in results)
    color = "green" if n_pass == n_total else "red"
    console.print(
        f"\n[bold {color}]{n_pass}/{n_total} fixtures passed[/bold {color}]  "
        f"[dim]({total_time:.1f}s total)[/dim]\n"
    )


def _render_failures(results: list[FixtureResult]) -> None:
    """Print detailed output for every failing fixture."""
    failed = [r for r in results if not r.passed]
    if not failed:
        return

    console.rule("[red]Failure details[/red]")
    for fr in failed:
        console.print(f"\n[bold red]{fr.fixture_id}[/bold red]: {fr.question}")
        if fr.error:
            console.print(f"  [red]Exception:[/red] {fr.error}")
            continue
        if fr.run:
            primary = max(fr.run.blocks, key=lambda b: b.row_count, default=None)
            if primary:
                console.print(f"  SQL: [dim]{primary.sql[:120]}[/dim]")
                console.print(f"  rows={primary.row_count}  chart={primary.chart_type}  color={primary.color_col}")
        for c in fr.checks:
            if not c.passed:
                console.print(f"  [red]✗[/red] {c.name}: {c.detail}")


async def _main(args: argparse.Namespace) -> int:
    with _FIXTURE_PATH.open() as f:
        data = yaml.safe_load(f)
    fixtures: list[dict[str, Any]] = data["fixtures"]

    if args.filter:
        fixtures = [fx for fx in fixtures if args.filter.lower() in fx["id"].lower()]
        if not fixtures:
            console.print(f"[red]No fixtures match filter {args.filter!r}[/red]")
            return 1

    chart_dir = Path(args.chart_dir) if args.chart_dir else None

    console.print(f"[bold]Running {len(fixtures)} fixture(s)…[/bold]")
    if chart_dir:
        console.print(f"Charts → {chart_dir}")

    results: list[FixtureResult] = []
    for fx in fixtures:
        console.print(f"  [dim]{fx['id']}[/dim] …", end="")
        fr = await _run_fixture(fx, chart_dir)
        icon = "[green]✓[/green]" if fr.passed else "[red]✗[/red]"
        console.print(f"\r  {icon} [dim]{fx['id']}[/dim] ({fr.elapsed:.1f}s)")
        results.append(fr)

        if args.fail_fast and not fr.passed:
            console.print("[yellow]--fail-fast: stopping after first failure[/yellow]")
            break

    _render_summary(results)
    _render_failures(results)

    return 0 if all(r.passed for r in results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Scouter against eval fixtures.")
    parser.add_argument(
        "--filter",
        metavar="SUBSTR",
        default=None,
        help="Only run fixtures whose ID contains this substring",
    )
    parser.add_argument(
        "--chart-dir",
        metavar="DIR",
        default=None,
        help="Save generated charts as HTML files in this directory",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failing fixture",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
