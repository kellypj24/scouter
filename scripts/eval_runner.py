"""Headless eval runner for a single Scouter question.

Runs the full pipeline (orchestrator → query agent → narrative agent) without
Streamlit and prints a structured report. Optionally saves charts as HTML.

Usage:
    uv run python scripts/eval_runner.py "What are the top 10 best performing stocks?"
    uv run python scripts/eval_runner.py --chart-dir /tmp/charts "Show Apple's 50-day MA"
    uv run python scripts/eval_runner.py --json "Which sectors performed best?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Project root on sys.path so src/ imports work without editable install.
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich import box

from src.agent.narrative_agent import NarrativeAgent
from src.agent.orchestrator import Orchestrator
from src.agent.providers.base import get_provider
from src.agent.query_agent import QueryAgent
from src.data.db import get_read_connection
from src.models.agent import AgentRequest
from src.viz.charts import build_chart

console = Console()

logging.basicConfig(level=logging.WARNING)


@dataclass
class BlockResult:
    sub_question: str
    sql: str
    row_count: int
    columns: list[str]
    chart_type: str | None
    color_col: str | None
    x_col: str | None
    y_col: str | None
    chart_built: bool
    chart_path: str | None
    prose: str
    follow_ups: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    question: str
    block_count: int
    fallback_used: bool
    blocks: list[BlockResult]


async def _run(question: str, chart_dir: Path | None) -> RunResult:
    provider = get_provider()
    try:
        conn = get_read_connection()
        orch = Orchestrator(
            provider=provider,
            query_agent=QueryAgent(provider=provider, conn=conn),
            narrative_agent=NarrativeAgent(provider=provider),
        )
        response = await orch.run(AgentRequest(question=question))

        blocks: list[BlockResult] = []
        for i, block in enumerate(response.blocks):
            spec = block.chart_spec
            chart_built = False
            chart_path = None

            if spec:
                fig = build_chart(spec, block.data)
                chart_built = fig is not None
                if fig is not None and chart_dir is not None:
                    chart_dir.mkdir(parents=True, exist_ok=True)
                    slug = "".join(c if c.isalnum() else "_" for c in question[:40])
                    chart_path = str(chart_dir / f"{slug}_block{i}.html")
                    fig.write_html(chart_path)

            blocks.append(BlockResult(
                sub_question=block.question,
                sql=block.query_result.sql,
                row_count=block.query_result.row_count,
                columns=block.query_result.columns,
                chart_type=spec.chart_type if spec else None,
                color_col=spec.color_col if spec else None,
                x_col=spec.x_col if spec else None,
                y_col=spec.y_col if spec else None,
                chart_built=chart_built,
                chart_path=chart_path,
                prose=block.prose,
                follow_ups=block.follow_ups,
            ))

        return RunResult(
            question=question,
            block_count=len(blocks),
            fallback_used=response.fallback_used,
            blocks=blocks,
        )
    finally:
        if hasattr(provider, "close"):
            await provider.close()


def _render(result: RunResult) -> None:
    console.print()
    console.rule(f"[bold cyan]{result.question}")

    meta = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    meta.add_row("Blocks", str(result.block_count))
    meta.add_row("Fallback used", "[red]YES[/red]" if result.fallback_used else "[green]no[/green]")
    console.print(meta)

    for i, block in enumerate(result.blocks):
        console.print(Panel(
            f"[bold]{block.sub_question}[/bold]",
            title=f"Block {i + 1}",
            border_style="blue",
        ))

        # SQL
        if block.sql:
            console.print(Syntax(block.sql, "sql", theme="monokai", word_wrap=True))
        else:
            console.print("[dim italic]  (no SQL executed)[/dim italic]")

        # Stats table
        stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        stats.add_row("Rows", str(block.row_count))
        stats.add_row("Columns", ", ".join(block.columns) if block.columns else "—")
        stats.add_row(
            "Chart",
            (
                f"[green]{block.chart_type}[/green]  "
                f"x={block.x_col}  y={block.y_col}  color={block.color_col or '—'}"
            ) if block.chart_type else "[dim]none[/dim]",
        )
        stats.add_row(
            "Chart built",
            "[green]yes[/green]" if block.chart_built else (
                "[yellow]spec exists but build failed[/yellow]"
                if block.chart_type else "[dim]—[/dim]"
            ),
        )
        if block.chart_path:
            stats.add_row("Chart saved", f"[link file://{block.chart_path}]{block.chart_path}[/link]")
        console.print(stats)

        # Prose
        console.print(f"[italic]{block.prose[:300]}{'…' if len(block.prose) > 300 else ''}[/italic]")

        # Quick pass/fail checks
        checks = _check_block(block)
        if checks:
            check_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
            for label, ok, detail in checks:
                icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
                check_table.add_row(icon, label, detail or "")
            console.print(check_table)

    console.print()


def _check_block(block: BlockResult) -> list[tuple[str, bool, str]]:
    """Return (label, passed, detail) tuples for inline checks."""
    checks = []
    checks.append(("rows > 0", block.row_count > 0, f"{block.row_count} rows"))
    if block.chart_type:
        checks.append(("chart built", block.chart_built, ""))
        # Warn if multi-entity data lacks color
        if block.chart_type == "line" and block.color_col is None and block.row_count > 30:
            checks.append((
                "color_col set",
                False,
                "line chart with many rows and no color may be a multi-entity chart",
            ))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single question through the Scouter pipeline.")
    parser.add_argument("question", help="Natural language question to evaluate")
    parser.add_argument(
        "--chart-dir",
        metavar="DIR",
        default=None,
        help="Save generated charts as HTML files in this directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of rich output",
    )
    args = parser.parse_args()

    chart_dir = Path(args.chart_dir) if args.chart_dir else None
    result = asyncio.run(_run(args.question, chart_dir))

    if args.json:
        def _serial(obj: object) -> object:
            if hasattr(obj, "__dataclass_fields__"):
                return asdict(obj)  # type: ignore[arg-type]
            return str(obj)
        print(json.dumps(asdict(result), default=_serial, indent=2))
    else:
        _render(result)


if __name__ == "__main__":
    main()
