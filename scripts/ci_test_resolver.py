#!/usr/bin/env python3
"""Resolve which test files to run based on changed source files.

Convention: src/foo/bar.py → tests/unit/test_bar.py + tests/integration/test_bar.py
Explicit overrides: files that map to more than one test file or follow a different pattern.
Fallback: if nothing resolves, run the full test suite (never silently skip).
"""

import os
import subprocess
import sys
from pathlib import Path

# Files that trigger the full suite (dependency changes)
FULL_SUITE_TRIGGERS = {"pyproject.toml", "uv.lock"}

# Explicit overrides for source files that map to multiple test files
# or whose test file name doesn't match the module name.
EXPLICIT_MAPPINGS: dict[str, list[str]] = {
    "src/agent/orchestrator.py": [
        "tests/unit/test_orchestrator.py",
        "tests/integration/test_orchestrator.py",
    ],
    "src/data/loader.py": [
        "tests/unit/test_loader.py",
        "tests/integration/test_loader.py",
    ],
    # scripts/ and pipeline assets that have dedicated test files
    "scripts/promote_patterns.py": ["tests/unit/test_promote_patterns.py"],
    "scripts/show_kpis.py": ["tests/unit/test_kpis.py"],
    "pipeline/assets/pattern_promotion.py": ["tests/unit/test_promote_patterns.py"],
    # models with dedicated test files
    "src/models/request_state.py": ["tests/unit/test_request_state.py"],
    "src/observability/kpis.py": ["tests/unit/test_kpis.py"],
    # api/ modules use a prefixed test name
    "api/main.py": ["tests/unit/test_api_main.py"],
    "api/streaming.py": ["tests/unit/test_api_streaming.py"],
    "api/deps.py": ["tests/unit/test_api_main.py", "tests/unit/test_api_streaming.py"],
}

# Source path prefixes that are eligible for dynamic test discovery
SOURCE_PREFIXES = ("src/", "api/", "pipeline/")


def discover_tests(source_file: str) -> list[str]:
    """Return test files that match a source file by naming convention."""
    module_name = Path(source_file).stem
    candidates = [
        f"tests/unit/test_{module_name}.py",
        f"tests/integration/test_{module_name}.py",
    ]
    return [f for f in candidates if Path(f).exists()]


def resolve(changed_files: list[str]) -> tuple[bool, list[str]]:
    """Return (run_full, sorted_test_files).

    run_full=True means run tests/ (full suite); test_files is empty in that case.
    """
    if any(f in FULL_SUITE_TRIGGERS for f in changed_files):
        return True, []

    test_files: set[str] = set()

    for f in changed_files:
        # Test files run themselves
        if f.startswith("tests/") and f.endswith(".py"):
            if Path(f).exists():
                test_files.add(f)
            continue

        # Explicit multi-file overrides take priority
        if f in EXPLICIT_MAPPINGS:
            for tf in EXPLICIT_MAPPINGS[f]:
                if Path(tf).exists():
                    test_files.add(tf)
            continue

        # Dynamic discovery for any source Python file
        if f.endswith(".py") and any(f.startswith(p) for p in SOURCE_PREFIXES):
            test_files.update(discover_tests(f))

    # Never silently skip — fall back to full suite when nothing resolves
    if not test_files:
        return True, []

    return False, sorted(test_files)


def main() -> None:
    base_ref = os.environ.get("BASE_REF", "main")

    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    changed_files = [line for line in result.stdout.splitlines() if line.strip()]

    print(f"Changed files ({len(changed_files)}):", file=sys.stderr)
    for f in changed_files:
        print(f"  {f}", file=sys.stderr)

    run_full, test_files = resolve(changed_files)

    if run_full:
        print("Resolved: full suite (tests/)", file=sys.stderr)
        files_value = "tests/"
    else:
        print(f"Resolved: targeted — {' '.join(test_files)}", file=sys.stderr)
        files_value = " ".join(test_files)

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    lines = f"run_full={'true' if run_full else 'false'}\ntest_files={files_value}\n"
    if github_output:
        with open(github_output, "a") as fh:
            fh.write(lines)
    else:
        # Local debug mode
        print(lines)


if __name__ == "__main__":
    main()
