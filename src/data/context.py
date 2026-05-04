"""Learned pattern context — Claude-curated few-shot SQL examples for prompt injection.

Reads learned_patterns.yaml from the project root. The local Scouter agent reads
this file at startup; only Claude (the developer agent) writes to it after
reviewing eval-validated patterns in mart_query_patterns.

Patterns are injected into the SQL generation prompt alongside schema definitions
to reduce hallucination on known-good query shapes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PATTERNS_FILE = Path(__file__).parents[2] / "learned_patterns.yaml"
_MAX_EXAMPLES = 5  # cap to protect token budget

_cache: dict[str, list[dict[str, Any]]] | None = None


def _load() -> dict[str, list[dict[str, Any]]]:
    global _cache
    if _cache is not None:
        return _cache

    if not _PATTERNS_FILE.exists():
        logger.debug("learned_patterns.yaml not found — no few-shot examples available")
        _cache = {}
        return _cache

    try:
        with _PATTERNS_FILE.open() as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed to load learned_patterns.yaml: %s", exc)
        _cache = {}
        return _cache

    patterns: list[dict[str, Any]] = data.get("patterns", [])
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for p in patterns:
        domain = p.get("domain", "all")
        by_domain.setdefault(domain, []).append(p)

    _cache = by_domain
    logger.info(
        "Loaded %d learned patterns from %s",
        sum(len(v) for v in by_domain.values()),
        _PATTERNS_FILE,
    )
    return _cache


def get_few_shot_examples(domain: str | None, max_examples: int = _MAX_EXAMPLES) -> str:
    """Return a formatted few-shot SQL block for the given domain.

    Injected after the schema definition in SQL generation prompts. Capped
    at max_examples to stay within the 4096-token budget.

    Args:
        domain: Agent domain string ('equity', 'sector', 'risk', 'core') or None.
        max_examples: Hard cap on examples returned. Callers with wide schemas
            (3+ domains) should pass 1 to avoid blowing the token budget.

    Returns:
        Formatted prompt string, or empty string if no patterns are available.
    """
    by_domain = _load()
    if not by_domain:
        return ""

    if domain:
        candidates = by_domain.get(domain, []) + by_domain.get("all", [])
    else:
        candidates = [p for patterns in by_domain.values() for p in patterns]

    if not candidates:
        return ""

    lines = ["-- Validated example queries for this domain (adapt as needed):"]
    for p in candidates[:max_examples]:
        note = p.get("notes") or p.get("id", "")
        lines.append(f"-- {note}")
        sql = p.get("example_sql", "").strip()
        if sql:
            lines.append(sql)

    return "\n".join(lines)


def invalidate_cache() -> None:
    """Clear the in-memory pattern cache.

    Call after learned_patterns.yaml is updated in the same process (rare —
    the file is edited externally and the cache refreshes on process restart).
    """
    global _cache
    _cache = None
