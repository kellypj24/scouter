#!/usr/bin/env python3
"""Staleness checks for CI.

Warns when a PR:
  - Adds new source files without a corresponding test file
  - Changes project structure (new src/ modules or pipeline assets) without touching CLAUDE.md
  - Changes project structure without touching README.md

Exits non-zero if hard failures are found; prints warnings for soft signals.
"""
import os
import subprocess
import sys
from pathlib import Path


# Source prefixes that require a test counterpart
TESTED_PREFIXES = ("src/", "api/", "pipeline/assets/")

# Files whose change signals doc updates are needed
STRUCTURE_SIGNALS = ("src/", "api/", "pipeline/assets/", "pipeline/sensors/")

# __init__ and private helpers don't need dedicated test files
SKIP_PATTERNS = ("__init__.py", "conftest.py")

DOC_FILES = ("CLAUDE.md", "README.md")


def get_changed_files(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def get_added_files(base_ref: str) -> list[str]:
    """Files added (A) or renamed (R) vs base — not modified."""
    result = subprocess.run(
        ["git", "diff", "--name-status", "--diff-filter=AR", f"origin/{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    files = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            files.append(parts[-1])  # rename records have two paths; take destination
    return files


def missing_test_files(added_files: list[str]) -> list[tuple[str, str]]:
    """Return (source_file, expected_test_path) for newly added source files with no test."""
    gaps = []
    for f in added_files:
        if not f.endswith(".py"):
            continue
        if any(Path(f).name == skip for skip in SKIP_PATTERNS):
            continue
        if not any(f.startswith(p) for p in TESTED_PREFIXES):
            continue
        # Skip files that are themselves in tests/
        if f.startswith("tests/"):
            continue

        module = Path(f).stem
        expected = f"tests/unit/test_{module}.py"
        if not Path(expected).exists():
            gaps.append((f, expected))
    return gaps


def structure_changed(changed_files: list[str]) -> bool:
    return any(
        f.endswith(".py") and any(f.startswith(p) for p in STRUCTURE_SIGNALS)
        for f in changed_files
    )


def docs_touched(changed_files: list[str]) -> dict[str, bool]:
    return {doc: doc in changed_files for doc in DOC_FILES}


def main() -> None:
    base_ref = os.environ.get("BASE_REF", "main")

    changed = get_changed_files(base_ref)
    added = get_added_files(base_ref)

    failures: list[str] = []
    warnings: list[str] = []

    # Hard check: new source files must have a test file
    gaps = missing_test_files(added)
    for src, expected in gaps:
        failures.append(
            f"  NEW FILE WITHOUT TEST: {src}\n"
            f"    Expected: {expected}\n"
            f"    Add a test file or add an explicit mapping in scripts/ci_test_resolver.py"
        )

    # Soft check: structural changes without doc updates
    if structure_changed(changed):
        touched = docs_touched(changed)
        for doc, was_touched in touched.items():
            if not was_touched:
                warnings.append(
                    f"  STALE DOCS: {doc} was not updated but source structure changed.\n"
                    f"    Consider updating {doc} to reflect the new module/file."
                )

    if warnings:
        print(":: Staleness warnings ::")
        for w in warnings:
            print(w)
        print()

    if failures:
        print(":: Staleness failures (blocking) ::")
        for f in failures:
            print(f)
        print()
        sys.exit(1)

    if not warnings and not failures:
        print("Staleness check passed — no gaps found.")


if __name__ == "__main__":
    main()
