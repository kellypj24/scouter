"""Schema context for LLM prompt injection.

Loads dbt artifacts (manifest.json + catalog.json) from dbt/target/ to build
rich, domain-keyed schema context. Falls back to INFORMATION_SCHEMA if artifacts
are missing (e.g. first run before dbt docs generate).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

_DBT_TARGET = Path(__file__).parents[2] / "dbt" / "target"

# Schemas exposed to the LLM — staging/intermediate are internal.
_DOMAIN_MAP: dict[str, str] = {
    "main_core": "core",
    "main_equity": "equity",
    "main_sector": "sector",
    "main_risk": "risk",
}

# Reverse map for building fully-qualified table names in prompts.
_SCHEMA_FOR_DOMAIN: dict[str, str] = {v: k for k, v in _DOMAIN_MAP.items()}


@dataclass
class ColumnSchema:
    name: str
    dtype: str
    description: str = ""


@dataclass
class ModelSchema:
    name: str
    domain: str
    description: str
    columns: list[ColumnSchema] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Render as a compact block for LLM injection."""
        qualified = f"{_SCHEMA_FOR_DOMAIN.get(self.domain, self.domain)}.{self.name}"
        lines = [f"Table: {qualified}"]
        if self.description:
            lines.append(f"  -- {self.description}")
        for col in self.columns:
            col_line = f"  {col.name} ({col.dtype})"
            if col.description:
                col_line += f"  -- {col.description}"
            lines.append(col_line)
        return "\n".join(lines)


@dataclass
class SchemaContext:
    """Parsed dbt artifact context, domain-keyed and ready for prompt injection."""

    models: list[ModelSchema]

    def by_domain(self, domain: str) -> list[ModelSchema]:
        return [m for m in self.models if m.domain == domain]

    def domains(self) -> list[str]:
        return sorted({m.domain for m in self.models})

    def to_prompt(self, domains: list[str] | None = None) -> str:
        """Return schema prompt string, optionally filtered to specific domains."""
        targets = (
            self.models if domains is None else [m for m in self.models if m.domain in domains]
        )
        if not targets:
            return "No schema available."
        sections: list[str] = []
        current_domain = None
        for model in sorted(targets, key=lambda m: (m.domain, m.name)):
            if model.domain != current_domain:
                current_domain = model.domain
                sections.append(f"\n-- Domain: {current_domain} --")
            sections.append(model.to_prompt_block())
        return "\n".join(sections).strip()


def _load_from_artifacts() -> SchemaContext | None:
    """Parse manifest.json + catalog.json into a SchemaContext."""
    manifest_path = _DBT_TARGET / "manifest.json"
    catalog_path = _DBT_TARGET / "catalog.json"

    if not manifest_path.exists() or not catalog_path.exists():
        return None

    with manifest_path.open() as f:
        manifest = json.load(f)
    with catalog_path.open() as f:
        catalog = json.load(f)

    models: list[ModelSchema] = []

    for node_id, cat_node in catalog["nodes"].items():
        schema_name = cat_node["metadata"]["schema"]
        domain = _DOMAIN_MAP.get(schema_name)
        if domain is None:
            continue  # skip staging/intermediate

        man_node = manifest["nodes"].get(node_id, {})
        man_columns: dict[str, dict[str, str]] = man_node.get("columns", {})

        columns = [
            ColumnSchema(
                name=col_name,
                dtype=col_info["type"],
                description=man_columns.get(col_name, {}).get("description", ""),
            )
            for col_name, col_info in cat_node["columns"].items()
        ]

        models.append(
            ModelSchema(
                name=cat_node["metadata"]["name"],
                domain=domain,
                description=man_node.get("description", ""),
                columns=columns,
            )
        )

    logger.info("Loaded schema context from dbt artifacts: %d models", len(models))
    return SchemaContext(models=models)


def _load_from_duckdb(conn: duckdb.DuckDBPyConnection) -> SchemaContext:
    """Fallback: build minimal SchemaContext from INFORMATION_SCHEMA."""
    rows = conn.execute("""
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema IN ('main_core', 'main_equity', 'main_sector', 'main_risk')
        ORDER BY table_schema, table_name, ordinal_position
    """).fetchall()

    models_map: dict[tuple[str, str], ModelSchema] = {}
    for schema, table, col, dtype in rows:
        domain = _DOMAIN_MAP.get(schema, schema)
        key = (domain, table)
        if key not in models_map:
            models_map[key] = ModelSchema(name=table, domain=domain, description="")
        models_map[key].columns.append(ColumnSchema(name=col, dtype=dtype))

    logger.warning("dbt artifacts not found — using INFORMATION_SCHEMA fallback")
    return SchemaContext(models=list(models_map.values()))


# Module-level cache — artifacts are loaded once per process.
_context: SchemaContext | None = None


def load_schema_context(conn: duckdb.DuckDBPyConnection | None = None) -> SchemaContext:
    """Return the cached SchemaContext, loading it if needed.

    Prefers dbt artifacts. Pass a DuckDB connection to enable the fallback.
    """
    global _context
    if _context is None:
        _context = _load_from_artifacts() or (
            _load_from_duckdb(conn) if conn is not None else SchemaContext(models=[])
        )
    return _context


def get_schema_prompt(
    conn: duckdb.DuckDBPyConnection,
    domains: list[str] | None = None,
) -> str:
    """Return a schema prompt string for LLM injection.

    Args:
        conn: DuckDB connection (used only if dbt artifacts are missing).
        domains: Optional list of domains to include (e.g. ['equity', 'core']).
                 None returns all mart/core domains.

    Returns:
        Multi-line schema description ready for prompt injection.
    """
    ctx = load_schema_context(conn)
    return ctx.to_prompt(domains=domains)
