"""Unit tests for src/data/context.py — learned pattern cache and few-shot injection."""

from __future__ import annotations

import textwrap

import pytest

import src.data.context as ctx_mod


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the in-memory pattern cache between tests."""
    ctx_mod._cache = None
    yield
    ctx_mod._cache = None


class TestGetFewShotExamples:
    """get_few_shot_examples() returns formatted SQL blocks or empty string."""

    def test_returns_empty_string_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ctx_mod, "_PATTERNS_FILE", tmp_path / "nonexistent.yaml")
        result = ctx_mod.get_few_shot_examples("equity")
        assert result == ""

    def test_returns_empty_string_for_empty_file(self, tmp_path, monkeypatch):
        f = tmp_path / "patterns.yaml"
        f.write_text("patterns: []\n")
        monkeypatch.setattr(ctx_mod, "_PATTERNS_FILE", f)
        result = ctx_mod.get_few_shot_examples("equity")
        assert result == ""

    def test_returns_examples_for_matching_domain(self, tmp_path, monkeypatch):
        f = tmp_path / "patterns.yaml"
        f.write_text(
            textwrap.dedent("""\
            patterns:
              - id: test_equity
                domain: equity
                notes: top performers
                example_sql: "SELECT ticker FROM mart_equity_performance LIMIT 5"
        """)
        )
        monkeypatch.setattr(ctx_mod, "_PATTERNS_FILE", f)
        result = ctx_mod.get_few_shot_examples("equity")
        assert "SELECT ticker FROM mart_equity_performance" in result
        assert "top performers" in result

    def test_no_cross_domain_leakage(self, tmp_path, monkeypatch):
        f = tmp_path / "patterns.yaml"
        f.write_text(
            textwrap.dedent("""\
            patterns:
              - id: equity_only
                domain: equity
                notes: equity pattern
                example_sql: "SELECT ticker FROM mart_equity_performance LIMIT 5"
        """)
        )
        monkeypatch.setattr(ctx_mod, "_PATTERNS_FILE", f)
        result = ctx_mod.get_few_shot_examples("risk")
        assert result == ""

    def test_none_domain_returns_all_patterns(self, tmp_path, monkeypatch):
        f = tmp_path / "patterns.yaml"
        f.write_text(
            textwrap.dedent("""\
            patterns:
              - id: eq
                domain: equity
                notes: equity
                example_sql: "SELECT 1"
              - id: rk
                domain: risk
                notes: risk
                example_sql: "SELECT 2"
        """)
        )
        monkeypatch.setattr(ctx_mod, "_PATTERNS_FILE", f)
        result = ctx_mod.get_few_shot_examples(None)
        assert "SELECT 1" in result
        assert "SELECT 2" in result

    def test_caps_at_max_examples(self, tmp_path, monkeypatch):
        patterns = "\n".join(
            f'  - id: p{i}\n    domain: equity\n    notes: n{i}\n    example_sql: "SELECT {i}"'
            for i in range(10)
        )
        f = tmp_path / "patterns.yaml"
        f.write_text(f"patterns:\n{patterns}\n")
        monkeypatch.setattr(ctx_mod, "_PATTERNS_FILE", f)
        result = ctx_mod.get_few_shot_examples("equity")
        # Only _MAX_EXAMPLES (5) should appear
        count = sum(1 for i in range(10) if f"SELECT {i}" in result)
        assert count <= ctx_mod._MAX_EXAMPLES


class TestInvalidateCache:
    """invalidate_cache() clears in-memory state."""

    def test_invalidate_resets_cache(self, tmp_path, monkeypatch):
        f = tmp_path / "patterns.yaml"
        f.write_text("patterns: []\n")
        monkeypatch.setattr(ctx_mod, "_PATTERNS_FILE", f)
        ctx_mod.get_few_shot_examples("equity")  # populate cache
        assert ctx_mod._cache is not None
        ctx_mod.invalidate_cache()
        assert ctx_mod._cache is None
