# Assignment: Contextual Knowledge Base

**Branch**: `feature/contextual-knowledge`  
**Phase**: 5 (Production Harness)  
**Status**: Planning  
**Depends on**: `feature/observability` merged to `main`

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

### 1. Merge `feature/observability` → `main` and cut new branch
- Open PR for observability branch
- Create `feature/contextual-knowledge` from updated `main`

### 2. dbt docs Dagster integration
- `dbt_docs_sensor`: poll `dbt/target/manifest.json` mtime every 10 min, fire on change
- `dbt_docs_sync` asset: parse `manifest.json` (models, columns, descriptions, tests) and `catalog.json` (statistics); write to `raw_schema_context` tables in DuckDB
- Handle missing `catalog.json` gracefully (it requires `dbt docs generate`, not just `dbt run`)
- Unit test: manifest parser with fixture JSON files

### 3. dbt schema context marts
- `mart_schema_context`: join models + columns + statistics; include accepted_values from tests
- `mart_query_patterns`: aggregate successful candidate patterns; join eval signal; flag `eval_validated`
- Add both to `dbt_project.yml`

### 4. Extend observability span logging
- Add `query_pattern` span type to `ObservabilityLogger`
- `QueryAgent` logs on successful execution: domain, mart(s) referenced, question_type (coarse classification), SQL hash
- Update `observability_sync` Dagster asset to handle the new span type
- Update `stg_obs_spans` staging view

### 5. Enriched schema injection
- `src/data/context.py`: `get_enriched_context(domain) -> str` — reads `mart_schema_context` + `learned_patterns.yaml`
- Update `schema.py` to call `context.py`; maintain token budget (descriptions may push close to 4096 limit — truncate low-value columns first)
- Fallback: if DuckDB context mart is empty or stale, fall back to current `information_schema` introspection
- Unit tests: token budget enforcement with rich context

### 6. learned_patterns.yaml + promotion workflow
- Define schema for `learned_patterns.yaml` (domain, question_type, sql_template, notes, promoted_by, promoted_at)
- Write an initial seed from existing eval fixture SQL that passes
- Document the promotion workflow in `assignments/README.md`: Claude queries `mart_query_patterns`, verifies, adds entry to yaml, commits
- `context.py` reads yaml at startup (not per-request — cache it)

### 7. Eval harness integration
- Add new eval fixtures targeting currently high-fallback domains (identify from `mart_fallback_analysis` once observability branch is in prod)
- Ensure `mart_query_patterns.eval_validated` correctly joins on `eval_` prefixed request IDs
- Add a Go scorer check: `context_used` flag in runner output (did the agent use an enriched context hit?)
- Target: eval fixture pass rate does not regress; high-fallback domains improve

### 8. Docs + cleanup
- Update `src/data/README.md` and `CLAUDE.md` — new context injection path
- Update `pipeline/README.md` — new sensor + asset
- Update `dbt/README.md` — new mart domain
- Update root `CLAUDE.md` — Phase 5 status, new architecture diagram entry

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
