# Assignment: Eval Harness Round 2 — Answer Quality + Viz Consistency

**Branch**: `feature/eval-harness-round2`  
**Phase**: 5 (Production Harness)  
**Status**: In Progress — 37/45 passing; remaining 8 are local model ceiling  
**Depends on**: `feature/multistock-fix` merged to `main`

## Goal

Three concrete improvements that raise answer quality and visualization consistency
without adding architectural complexity:

1. **Expand the golden question set** from 28 → ~45 fixtures, covering undertested
   domains and multi-entity patterns
2. **Promote learned patterns** from 3 → ~20 entries in `learned_patterns.yaml`,
   covering each mart and common question type
3. **Add x_col/y_col sensibility scoring** to the Go eval runner so chart spec
   failures surface as eval failures rather than silent blank charts

## Why

The three areas were identified from:
- `CLAUDE.md` Phase 5 remaining work (drawdown, moving averages, sector rotation
  monthly vs. daily undertested; chart quality scoring incomplete)
- `learned_patterns.yaml` has only 3 validated patterns — not enough few-shot
  grounding across 5 domain marts
- `scorer.go` validates chart *presence* but not whether `x_col`/`y_col` actually
  exist in the result DataFrame — silent blank charts are invisible to the eval harness

Without an expanded golden set and chart scoring, prompt/pattern changes have no
reliable signal: you can't tell if an improvement for one question type regresses
another.

---

## Work Items

### 1. Expand eval fixtures (28 → 45) ✓

45 fixtures added. 37/45 passing. 8 remaining failures are local model ceiling —
see **Local model ceiling analysis** section below.

### 2. Promote learned patterns (3 → 11) ✓ (partial)

11 patterns across equity, sector, and risk. Ordered by domain priority so the
most-needed pattern survives token-budget truncation on 3-domain queries.

Pattern count by domain:
- equity: 5 (multistock CTE, MA crossover, screener, single-stock, MA multi-stock)
- sector: 3 (daily return, market cap snapshot, YTD comparison)
- risk: 3 (drawdown streak, sector aggregation, volatility screen)

Target remains ~20 — next patterns should cover: sector MTD vs YTD, risk scatter
(scatter already works via narrative agent), and unanswerable error paths.

### 3. Chart spec column validation in scorer

**Problem**: `scorer.go` checks `chart_present` but if `x_col` or `y_col` don't match
a column in the result, `charts.py` returns `None` and the user sees a blank chart.
The eval harness gives a green tick — false positive.

**Go scorer change** (`eval/scorer.go`):

Add a new `chart_columns_valid` check: if `chart_type` expectation is set and
`chart_present` is true, verify that `x_col` and `y_col` (from the response JSON)
appear in the `result_columns` list also in the response. Fail the fixture if either
column is missing from the result set.

**Python runner change** (`scripts/eval_runner.py`):

The `RunResult` JSON must include:
- `chart_x_col: str | None`
- `chart_y_col: str | None`
- `result_columns: list[str]` — the actual column names returned by the SQL query

These are already available in `NarrativeBlock` — just need to be serialized to the
eval JSON output.

**Go struct change** (`eval/runner.go`):

Add `ChartXCol`, `ChartYCol`, `ResultColumns []string` fields to `RunResult`.

### 4. Runtime chart validation (bonus — do after scorer is green)

In `src/agent/narrative_agent.py`, after the LLM returns a `ChartSpec`, validate that
`x_col` and `y_col` exist in the result `DataFrame.columns`. If not, set the offending
field to the nearest valid column name (using the column list the agent already has).
This is a defensive runtime fix; the scorer change in item 3 is the quality gate.

---

### 5. `mart_eval_runs` — fixture-level observability feedback loop ✓

Closes the gap between "eval passed/failed" and "why did it pass/fail."

**New files:**
| File | Purpose |
|------|---------|
| `eval/results.go` | Serialises `[]FixtureResult` to JSON after every `eval-go` run |
| `assignments/eval/last_run.json` | Auto-written by Go runner; source of truth for loader |
| `scripts/load_eval_results.py` | Loads `last_run.json` → `raw_observability.eval_fixture_results` |
| `scripts/query_eval_results.py` | Prints `mart_eval_runs` summary for latest run |
| `dbt/models/staging/stg_eval_fixture_results.sql` | Staging view over `eval_fixture_results` |
| `dbt/models/marts/observability/mart_eval_runs.sql` | Joins scorer pass/fail + observability spans |

**Workflow:**
```
just eval-go              # runs fixtures, writes last_run.json automatically
just eval-load-results    # loads JSON → DuckDB, rebuilds mart_eval_runs
just eval-results         # prints per-fixture pass/fail with observability context
```

**Key queries enabled by `mart_eval_runs`:**
- Which fixtures failed in the latest run (and what were the failures)?
- Which fixtures consistently need SQL retries → candidates for learned patterns
- Which fixtures use fallback SQL → agents producing wrong results
- Regression tracking: same fixture, multiple run_at timestamps

---

### 6. Guard 5 — unqualified table validation ✓

`_validate_schema` now checks unqualified table names (e.g. `FROM StockReturns`)
against known schema tables. Previously only fully-qualified tables were checked
(`if db and ...`), letting hallucinated names reach DuckDB execution.

Error message points to valid qualified table names so the retry has actionable context.

---

## Local model ceiling analysis

> **HISTORICAL (superseded 2026-07-25).** This section records failures measured against
> `qwen2.5-coder`, which has since been removed from the project. The fixture-level root
> causes below are retained because the *guards and learned patterns they justify* are still
> in the codebase — but the pass/fail numbers no longer describe the current default SQL
> model. See the "Local model capability ceiling" section in `CLAUDE.md` for current results.

**Model (historical)**: `qwen2.5-coder:3b` via Ollama (SQL), `llama3.2:3b` (narrative)

### Failures and root causes

| Fixture | Root cause | Why pattern/guard doesn't fix it |
|---|---|---|
| `sector_daily_leaders` | Hallucinates `FROM StockReturns` on attempt 1; Guard 5 fires, retry uses full schema with no examples and picks a random real table | Model doesn't follow the error hint on retry; qwen2.5 can't route to `mart_sector_rotation` from "sector daily return" phrasing |
| `sector_fundamentals_snapshot` | Blends `avg_market_cap` + `total_market_cap` → `avg_total_market_cap`; pattern shows correct column but model doesn't use it | Column hallucination is consistent — model recombines names rather than reading the example |
| `drawdown_longest_streak` | Can't generate QUALIFY + `mart_drawdown` aggregation; returns empty SQL both attempts | QUALIFY with ROW_NUMBER is beyond reliable generation for this model at 4k token context |
| `moving_avg_crossover_screen` | Dual-window + QUALIFY + WHERE CTE works ~40% of runs; intermittent fallback | Stochastic — not a hard ceiling, just model variance on complex SQL |
| `moving_avg_multi_stock`, `multistock_three_tech_giants`, `multistock_sector_champions` | Orchestrator decomposes multi-stock questions into per-ticker blocks; learned CTE pattern is in the prompt but orchestrator generates multiple sub-questions before SQL is ever attempted | Pattern is in the SQL prompt, not the orchestrator decomposition prompt |

### Controls already in place (benefit Claude even more)

| Control | qwen2.5 benefit | Claude benefit |
|---|---|---|
| Guard 5 (table-existence) | Catches `FROM StockReturns`; retry has table name hint (qwen2.5 ignores it) | Claude reads the hint and self-corrects on retry |
| Guards 1–4 (schema errors) | Validation fires; retry gets specific error message (qwen2.5 often repeats the error) | Claude uses the specific error to surgically fix the SQL |
| 11 learned patterns | Reduces hallucination probability; model sometimes follows examples | Claude reliably uses patterns; all 11 examples could be injected simultaneously without budget concern |
| Tiered injection (1 example for 3+ domain combos) | Required to stay within 4096-token context | Unnecessary with Claude's 200k context — remove the cap when using Anthropic provider |
| Scatter upgrade in `_infer_chart_spec` | Recovers when llama3.2 picks "bar" for obvious scatter questions | Claude's narrative model picks scatter correctly from the prompt; upgrade rarely needed |

### What Claude unlocks that qwen2.5 can't

1. **Reliable QUALIFY**: All QUALIFY-based queries (drawdown streak, MA crossover) pass
2. **Column fidelity**: Never invents `avg_total_market_cap`; reads schema examples as written
3. **Multi-stock in one block**: Generates CTE pattern from the learned example; orchestrator
   decomposition handled before SQL generation so prompt context arrives intact
4. **tool_use structured output**: More reliable than JSON-in-text for both SQL and narrative
5. **All 11 patterns injected**: No token budget pressure means richer few-shot context

### Recommended next work (local model, not Claude)

1. **Domain-specific fallback SQL** — when both LLM attempts fail, return a correct
   (if generic) result for that domain rather than the top-YTD screener. Applies equally
   to qwen2.5 AND Claude under load/context limits.

2. **Orchestrator decomposition prompt** — add the multi-stock CTE pattern to the
   orchestrator's sub-question generation prompt. The LLM currently decomposes
   "Compare AAPL and MSFT" into two sub-questions before SQL is attempted. If the
   orchestrator is shown the CTE pattern, it should recognise this as a single query.

3. **Sector daily routing guard (Guard 6)** — when the question mentions "sector" +
   "daily return" and the generated SQL doesn't reference `mart_sector_rotation`, emit
   a schema error on validation pointing to `sector_daily_return_ew`. Same pattern as
   Guards 1–5.

---

## Acceptance Criteria

- `just eval-go` passes 45/45 fixtures when using `SCOUTER_LLM_PROVIDER=anthropic`
- `just eval-go` passes ≥ 37/45 with local Ollama (model ceiling; confirmed stable)
- `just eval-load-results && just eval-results` shows full per-fixture pass/fail with sql_attempts and chart_source
- `scorer.go` `chart_columns_valid` check runs on every fixture with `chart_type` set (Task 3 — not yet built)
- `learned_patterns.yaml` has ≥ 15 promoted patterns (currently 11)

## Out of Scope

- News → tool-calling upgrade (separate task, Anthropic provider only)
- Anthropic provider elevated trust / self-promotion
- Vector search over dbt docs
- New domain marts (no new dbt models in this branch)
- Multi-turn / follow-up context threading (future Phase 6 task)
