"""Unit tests for src/data/schema.py."""

import json

import duckdb
import pytest

import src.data.schema as schema_mod
from src.data.schema import (
    ColumnSchema,
    ModelSchema,
    SchemaContext,
    _load_from_artifacts,
    _load_from_duckdb,
    get_schema_prompt,
    load_schema_context,
)


@pytest.fixture(autouse=True)
def reset_cache():
    schema_mod._context = None
    yield
    schema_mod._context = None


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def conn_with_marts(conn):
    conn.execute("CREATE SCHEMA main_core")
    conn.execute("CREATE SCHEMA main_equity")
    conn.execute("CREATE TABLE main_core.dim_company (company_id INTEGER, ticker VARCHAR)")
    conn.execute(
        "CREATE TABLE main_equity.mart_equity_performance (ticker VARCHAR, ytd_return DOUBLE)"
    )
    return conn


@pytest.fixture
def dbt_artifacts(tmp_path):
    manifest = {
        "nodes": {
            "model.scouter.dim_company": {
                "description": "Company dimension table",
                "columns": {
                    "company_id": {"description": "Primary key"},
                    "ticker": {"description": "Ticker symbol"},
                },
            },
            "model.scouter.mart_equity_performance": {
                "description": "Equity performance mart",
                "columns": {},
            },
            "model.scouter.stg_prices": {
                "description": "Staging prices — should be skipped",
                "columns": {},
            },
        }
    }
    catalog = {
        "nodes": {
            "model.scouter.dim_company": {
                "metadata": {"schema": "main_core", "name": "dim_company"},
                "columns": {
                    "company_id": {"type": "INTEGER"},
                    "ticker": {"type": "VARCHAR"},
                },
            },
            "model.scouter.mart_equity_performance": {
                "metadata": {"schema": "main_equity", "name": "mart_equity_performance"},
                "columns": {
                    "ticker": {"type": "VARCHAR"},
                    "ytd_return": {"type": "DOUBLE"},
                },
            },
            "model.scouter.stg_prices": {
                "metadata": {"schema": "main_staging", "name": "stg_prices"},
                "columns": {"price": {"type": "DOUBLE"}},
            },
        }
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    return tmp_path


class TestColumnSchema:
    def test_defaults(self):
        col = ColumnSchema(name="ticker", dtype="VARCHAR")
        assert col.description == ""

    def test_with_description(self):
        col = ColumnSchema(name="price", dtype="DOUBLE", description="Close price")
        assert col.description == "Close price"


class TestModelSchema:
    def _make_model(self, *, with_desc=False) -> ModelSchema:
        cols = [
            ColumnSchema(name="id", dtype="INTEGER", description="PK" if with_desc else ""),
            ColumnSchema(name="name", dtype="VARCHAR"),
        ]
        return ModelSchema(
            name="dim_company",
            domain="core",
            description="Company dim" if with_desc else "",
            columns=cols,
        )

    def test_prompt_block_includes_qualified_name(self):
        block = self._make_model().to_prompt_block()
        assert "main_core.dim_company" in block

    def test_prompt_block_lists_columns(self):
        block = self._make_model().to_prompt_block()
        assert "id (INTEGER)" in block
        assert "name (VARCHAR)" in block

    def test_prompt_block_with_descriptions(self):
        block = self._make_model(with_desc=True).to_prompt_block()
        assert "Company dim" in block
        assert "PK" in block

    def test_prompt_block_skips_empty_col_description(self):
        block = self._make_model(with_desc=False).to_prompt_block()
        assert "PK" not in block

    def test_unknown_domain_uses_domain_as_schema(self):
        model = ModelSchema(name="some_table", domain="custom", description="")
        block = model.to_prompt_block()
        assert "custom.some_table" in block


class TestSchemaContext:
    def _make_context(self) -> SchemaContext:
        return SchemaContext(
            models=[
                ModelSchema(name="dim_company", domain="core", description=""),
                ModelSchema(name="fct_prices", domain="core", description=""),
                ModelSchema(name="mart_equity", domain="equity", description=""),
            ]
        )

    def test_by_domain(self):
        ctx = self._make_context()
        core = ctx.by_domain("core")
        assert len(core) == 2
        assert all(m.domain == "core" for m in core)

    def test_domains(self):
        ctx = self._make_context()
        assert ctx.domains() == ["core", "equity"]

    def test_to_prompt_all_domains(self):
        ctx = self._make_context()
        prompt = ctx.to_prompt()
        assert "core" in prompt
        assert "equity" in prompt

    def test_to_prompt_filtered(self):
        ctx = self._make_context()
        prompt = ctx.to_prompt(domains=["equity"])
        assert "equity" in prompt
        assert "dim_company" not in prompt

    def test_to_prompt_empty_filter(self):
        ctx = self._make_context()
        prompt = ctx.to_prompt(domains=["risk"])
        assert prompt == "No schema available."

    def test_to_prompt_no_models(self):
        ctx = SchemaContext(models=[])
        assert ctx.to_prompt() == "No schema available."


class TestLoadFromArtifacts:
    def test_loads_mart_models(self, dbt_artifacts, monkeypatch):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", dbt_artifacts)
        ctx = _load_from_artifacts()
        assert ctx is not None
        names = {m.name for m in ctx.models}
        assert "dim_company" in names
        assert "mart_equity_performance" in names

    def test_skips_non_mart_schemas(self, dbt_artifacts, monkeypatch):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", dbt_artifacts)
        ctx = _load_from_artifacts()
        assert ctx is not None
        names = {m.name for m in ctx.models}
        assert "stg_prices" not in names

    def test_injects_column_descriptions_from_manifest(self, dbt_artifacts, monkeypatch):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", dbt_artifacts)
        ctx = _load_from_artifacts()
        assert ctx is not None
        dim = next(m for m in ctx.models if m.name == "dim_company")
        id_col = next(c for c in dim.columns if c.name == "company_id")
        assert id_col.description == "Primary key"

    def test_returns_none_when_artifacts_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", tmp_path)
        assert _load_from_artifacts() is None


class TestLoadFromDuckDB:
    def test_builds_context_from_information_schema(self, conn_with_marts):
        ctx = _load_from_duckdb(conn_with_marts)
        names = {m.name for m in ctx.models}
        assert "dim_company" in names
        assert "mart_equity_performance" in names

    def test_maps_domains_correctly(self, conn_with_marts):
        ctx = _load_from_duckdb(conn_with_marts)
        dim = next(m for m in ctx.models if m.name == "dim_company")
        assert dim.domain == "core"

    def test_empty_when_no_mart_tables(self, conn):
        ctx = _load_from_duckdb(conn)
        assert ctx.models == []


class TestLoadSchemaContext:
    def test_prefers_artifacts(self, dbt_artifacts, monkeypatch, conn):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", dbt_artifacts)
        ctx = load_schema_context(conn)
        assert len(ctx.models) > 0

    def test_falls_back_to_duckdb(self, tmp_path, monkeypatch, conn_with_marts):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", tmp_path)
        ctx = load_schema_context(conn_with_marts)
        assert len(ctx.models) > 0

    def test_returns_empty_without_conn_or_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", tmp_path)
        ctx = load_schema_context(None)
        assert ctx.models == []

    def test_caches_result(self, tmp_path, monkeypatch, conn_with_marts):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", tmp_path)
        ctx1 = load_schema_context(conn_with_marts)
        ctx2 = load_schema_context(conn_with_marts)
        assert ctx1 is ctx2


class TestGetSchemaPrompt:
    def test_returns_string(self, tmp_path, monkeypatch, conn_with_marts):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", tmp_path)
        prompt = get_schema_prompt(conn_with_marts)
        assert isinstance(prompt, str)

    def test_domain_filter(self, tmp_path, monkeypatch, conn_with_marts):
        monkeypatch.setattr(schema_mod, "_DBT_TARGET", tmp_path)
        prompt = get_schema_prompt(conn_with_marts, domains=["equity"])
        assert "equity" in prompt
