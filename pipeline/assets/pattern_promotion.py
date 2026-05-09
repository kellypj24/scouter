"""Pattern promotion asset — surfaces eval failures as pattern candidates.

Runs after observability_sync so that mart_eval_runs is up to date before
querying. Calls scripts/promote_patterns.py as a subprocess, consistent
with the dbt_docs_generate pattern.

Writes to pattern_candidates.yaml in the project root (gitignored). The
file is an inbox for human review; nothing is written to learned_patterns.yaml
automatically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dagster import AssetExecutionContext, MaterializeResult, asset

from pipeline.assets.observability import observability_sync

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _PROJECT_ROOT / "scripts" / "promote_patterns.py"
_OUTPUT = _PROJECT_ROOT / "pattern_candidates.yaml"


@asset(
    deps=[observability_sync],
    group_name="pattern_promotion",
    compute_kind="python",
    description=(
        "Surface consistently-failing eval fixtures as pattern candidates. "
        "Writes pattern_candidates.yaml for human review. "
        "Never modifies learned_patterns.yaml."
    ),
)
def pattern_promotion(context: AssetExecutionContext) -> MaterializeResult:
    """Run promote_patterns.py and report candidate count.

    Args:
        context: Dagster asset execution context.
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--output", str(_OUTPUT)],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )

    if result.stdout:
        context.log.info(result.stdout.strip())
    if result.stderr:
        context.log.warning(result.stderr.strip())

    if result.returncode not in (0, 1):
        context.log.error(
            "promote_patterns.py exited %d:\n%s",
            result.returncode,
            result.stderr or result.stdout,
        )

    # Count candidates in output file to report in metadata.
    candidates_written = 0
    if _OUTPUT.exists():
        import yaml

        data = yaml.safe_load(_OUTPUT.read_text()) or {}
        pending = [c for c in data.get("candidates", []) if c.get("status") == "pending_review"]
        candidates_written = len(pending)

    return MaterializeResult(
        metadata={
            "candidates_pending_review": candidates_written,
            "output_path": str(_OUTPUT),
        }
    )
