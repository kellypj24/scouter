# dbt/ — Claude Context

## Layer conventions

- **Staging** — views only, one-to-one with raw tables, rename/cast only, no joins
- **Intermediate** — tables (materialized), complex joins and derived metrics live here
- **Marts** — pre-joined, agent-ready; the LLM generates simple SELECTs against these, not multi-table joins

## Mart schema is injected into LLM prompts

`src/data/schema.py::get_domain_schema()` reads mart column metadata and formats it for the SQL generation prompt. When you add or rename columns in a mart, update the schema introspection to match — stale schema injection is a common source of SQL generation errors.

## Adding a new domain

1. Create `dbt/models/marts/<domain>/` with mart model files
2. Add schema config to `dbt_project.yml`
3. Register the domain with the classifier in `src/agent/orchestrator.py`
4. Add the domain's marts to the schema injection in `src/data/schema.py`

## No raw table references in marts

Marts must reference only staging or intermediate models — never `raw.*` tables directly. This keeps the lineage clean and makes source swaps transparent.

## dbt_project.yml is the source of truth

Materialization strategy (view vs table) is set in `dbt_project.yml`, not in model headers (unless overriding). Keep it consistent.
