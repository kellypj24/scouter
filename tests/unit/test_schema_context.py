"""Unit tests for pipeline/assets/schema_context.py — dbt_docs_generate asset."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dagster import build_asset_context


def _mock_result(returncode: int = 0, stderr: str = "", stdout: str = "") -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stderr = stderr
    r.stdout = stdout
    return r


class TestDbtDocsGenerateUsesSubprocess:
    """dbt_docs_generate must use subprocess, not DbtCliResource."""

    def test_source_uses_subprocess(self):
        path = "pipeline/assets/schema_context.py"
        with open(path) as f:
            source = f.read()
        assert "subprocess" in source
        assert "dbt.cli" not in source

    def test_runs_correct_dbt_command(self):
        """subprocess.run is called with dbt docs generate."""
        from pipeline.assets.schema_context import dbt_docs_generate

        with (
            patch(
                "pipeline.assets.schema_context.subprocess.run", return_value=_mock_result()
            ) as mock_run,
            build_asset_context() as ctx,
        ):
            dbt_docs_generate(ctx)

        call_args = mock_run.call_args[0][0]
        assert "dbt" in call_args
        assert "docs" in call_args
        assert "generate" in call_args

    def test_does_not_raise_on_nonzero_exit(self):
        """Non-zero returncode is logged as warning, not raised."""
        from pipeline.assets.schema_context import dbt_docs_generate

        with (
            patch(
                "pipeline.assets.schema_context.subprocess.run",
                return_value=_mock_result(returncode=1, stderr="dbt error"),
            ),
            build_asset_context() as ctx,
        ):
            dbt_docs_generate(ctx)  # must not raise

    def test_succeeds_on_zero_exit(self):
        from pipeline.assets.schema_context import dbt_docs_generate

        with (
            patch("pipeline.assets.schema_context.subprocess.run", return_value=_mock_result()),
            build_asset_context() as ctx,
        ):
            dbt_docs_generate(ctx)  # must not raise
