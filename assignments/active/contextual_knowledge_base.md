# Assignment: Contextual Knowledge Base

**Branch**: `feature/contextual-knowledge`  
**Phase**: 5 (Production Harness)  
**Status**: In Progress  
**Depends on**: `feature/observability` merged to `main` ✓

## Goal

Replace bare `information_schema` schema injection with a rich, self-maintaining
context layer. The agent should know not just *what columns exist* but *what they mean*,
*what values are valid*, and *what SQL patterns have worked before* — without requiring
manual maintenance as the schema evolves.

## Why

Current failure modes that this directly addresses:
- LLM hallucinates column names or table names not in the schema
- LLM generates valid SQL against the wrong mart for a question type
- Multi-stock time-series queries are fragile because the LLM doesn't know the CTE pattern that works
- `mart_fallback_analysis` shows fallback spikes by domain but we can't act on them without richer context

## Trust Hierarchy

```
Claude (developer agent)          ← highest trust
  reviews eval signal, promotes   ← writes to schema.yml + learned_patterns.yaml
  patterns, approves changes       ← commits → Dagster picks up automatically
        ↓
Eval harness (Go runner)          ← quality gate
  validates candidates against     ← nothing promotes without fixture passes
  fixtures before promotion        ← eval_ tagged runs in mart_query_patterns
        ↓
Local Scouter agent               ← worker bee, generates signal only
  logs successful queries as       ← cannot write to schema context
  candidates to observability      ← cannot self-promote patterns
        ↓
Dagster ELT + dbt                 ← automation layer
  keeps everything fresh on events ← no human polling required
```

The local agent gains more autonomy when running on Anthropic provider + once eval
coverage is high enough to make self-promotion safe. That is a future unlock, not in scope here.

---

## Architecture

### New data flow

```
dbt run/compile
  → dbt/target/manifest.json + catalog.json updated
  → dbt_docs_sensor fires (watches manifest.json mtime)
  → dbt_docs_sync asset runs
  → raw_schema_context schema in DuckDB
       ├── schema_models     (model name, description, mart domain)
       ├── schema_columns    (model, column, type, description, tests)
       └── schema_statistics (distinct values, min/max, row counts from catalog)
  → dbt builds mart_schema_context (agent-ready view)

Agent runtime
  → QueryAgent executes successful query
  → logs candidate pattern to observability spans (extended span type)
  → obs_log_sensor fires → observability_sync runs
  → raw_observability.query_patterns populated
  → dbt builds mart_query_patterns
       ├── filters: fallback_used=false, row_count>0
       └── joins eval pass/fail signal on request_id LIKE 'eval_%'

Claude reviews
  → queries mart_query_patterns WHERE eval_validated=true
  → promotes high-quality patterns to learned_patterns.yaml
  → updates schema.yml with column descriptions
  → commits → dbt_docs_sensor + dbt_docs_sync picks up automatically

Schema injection (updated)
  → schema.py reads mart_schema_context (descriptions + constraints)
  → schema.py reads mart_query_patterns (eval-validated few-shot examples)
  → richer prompt context, same token budget management
```

### New files

| File | Layer | Purpose |
|------|-------|---------|
| `pipeline/sensors/dbt_docs.py` | Dagster | Watch `dbt/target/manifest.json` mtime, fire on change |
| `pipeline/assets/schema_context.py` | Dagster | Parse manifest.json + catalog.json → DuckDB `raw_schema_context` |
| `dbt/models/marts/schema_context/` | dbt | `mart_schema_context`, `mart_query_patterns` |
| `src/data/context.py` | Agent | Read enriched context from DuckDB marts into prompt strings |
| `learned_patterns.yaml` | Repo | Claude-curated query patterns, read by schema injector |

### Modified files

| File | Change |
|------|--------|
| `src/data/schema.py` | Read from `mart_schema_context` + `learned_patterns.yaml`; fall back to `information_schema` |
| `src/agent/query_agent.py` | Log successful query spans with extended fields (domain, mart, question_type) |
| `pipeline/assets/observability.py` | Handle new `query_pattern` span type in ELT |
| `pipeline/__init__.py` | Register new sensor + asset |
| `assignments/eval/fixtures.yaml` | Add fixtures for domains that currently have high fallback rates |

---

## Tasks

### 1. Merge `feature/observability` → `main` and cut new branch ✓
- PR #9 merged via squash
- `feature/contextual-knowledge` cut from updated main

### 2. dbt docs Dagster integration ✓
- `dbt_docs_sensor` (`pipeline/sensors/dbt_docs.py`): polls `manifest.json` mtime every 10 min
- `dbt_docs_generate` asset (`pipeline/assets/schema_context.py`): runs `dbt docs generate`
- Registered in `pipeline/sensors/__init__.py` and `pipeline/assets/__init__.py`
- Handles missing catalog.json gracefully (schema.py falls back to INFORMATION_SCHEMA)

### 3. dbt schema context marts ✓ (partial)
- `mart_query_patterns` created in `dbt/models/marts/observability/`
- `stg_obs_spans.sql` extended with `mart` and `sql_hash` columns
- Note: `mart_schema_context` deferred — `schema.py` already reads dbt artifacts directly; no DuckDB intermediate needed

### 4. Extend observability span logging ✓
- `mart` and `sql_hash` columns added to SQLite spans DDL + migration in `logger.py`
- `QueryAgent` logs `query_pattern` span on successful non-fallback execution
- `_extract_mart()` and `_sql_hash()` helpers in `query_agent.py`

### 5. Enriched schema injection ✓
- `src/data/context.py`: `get_few_shot_examples(domain) -> str` — reads `learned_patterns.yaml`
- `schema.py`: TTL cache (1 hour), `reload_schema_context()` for explicit invalidation
- `get_schema_prompt()` now appends few-shot examples to schema injection
- `QueryAgent.run()` calls `get_schema_prompt()` instead of `self._schema.to_prompt()` directly

### 6. learned_patterns.yaml + promotion workflow ✓
- Seeded with 5 patterns covering equity screener, single stock, sector, and risk domains
- `context.py` caches at startup, `invalidate_cache()` for programmatic refresh
- Promotion workflow documented in `assignments/README.md` section

### 7. Eval harness integration — TODO
- Add new eval fixtures targeting high-fallback domains (use `mart_fallback_analysis` after first prod runs)
- Add Go scorer check for `context_used` flag
- Target: eval pass rate does not regress from baseline

### 8. Docs + cleanup ✓
- Updated: `pipeline/README.md`, `pipeline/assets/README.md`, `pipeline/sensors/README.md`
- Updated: `src/data/README.md`, `dbt/README.md`

---

## Success Criteria

- `just eval-go` pass rate does not regress from baseline (record baseline before starting task 5)
- At least one previously high-fallback domain shows measurable improvement in `mart_fallback_analysis`
- `dbt_docs_sensor` fires automatically after every `dbt run` with no manual intervention
- `mart_query_patterns` correctly separates `eval_` runs from prod runs
- Schema injection remains within 4096-token budget with enriched context
- `learned_patterns.yaml` has at least 5 Claude-promoted patterns covering the main domains
- Promotion workflow is documented and Claude can execute it in a future session without re-explanation

## Out of Scope (this branch)

- Local agent self-promotion (worker bee only — no writes to schema context from runtime)
- Anthropic-provider elevated trust mode
- Vector search / semantic retrieval over dbt docs (overkill until descriptions are written and proven useful)
- Docker Compose (separate Phase 5 task)
