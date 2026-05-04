# Assignment: Eval Harness Round 2 — Answer Quality + Viz Consistency

**Branch**: `feature/eval-harness-round2`  
**Phase**: 5 (Production Harness)  
**Status**: Planning  
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

### 1. Expand eval fixtures (28 → ~45)

Target gaps identified from `assignments/eval/fixtures.yaml`:

| Domain gap | Count | Example questions |
|---|---|---|
| Drawdown (more variants) | +3 | worst single-day drawdown, sector drawdown distribution, recovery time |
| Moving averages | +3 | 50d vs 200d crossover, MA comparison across tickers, golden cross screen |
| Sector rotation — daily vs monthly distinction | +2 | daily sector momentum, which sectors improved last month |
| Multi-entity time-series (equity) | +3 | AAPL vs MSFT vs GOOGL YTD, compare two sectors trend |
| Risk — Sharpe vs volatility scatter | +2 | plot Sharpe vs volatility for all S&P500 stocks, risk/return quadrant |
| Screener — combined filters | +2 | high Sharpe + low volatility, top YTD in a specific sector |
| Unanswerable — additional | +2 | dividend yield, P/E ratio (not in schema) |

Each new fixture must include `chart_type` and `sql_table` expectations where applicable.
Add `color_col_required: true` for any multi-entity chart fixture.

### 2. Promote learned patterns (3 → ~20)

Run `just eval-go` on the current 28 fixtures, query `mart_query_patterns WHERE
eval_validated = true`, and promote high-quality patterns for each domain:

| Domain | Target pattern count | Covers |
|---|---|---|
| equity — screener | 3 | top YTD, low volatility, combined filter |
| equity — time-series | 4 | single stock, multi-stock CTE, MA window |
| sector | 3 | YTD ranked, monthly rotation, fundamentals snapshot |
| risk | 3 | drawdown by sector, Sharpe/vol scatter, risk screener |
| unanswerable | 2 | error path — 0-row result + graceful prose |

Each promoted pattern must pass the full eval suite before promotion (no regressions).
Add `notes:` field explaining what makes the pattern generalizable.

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

## Acceptance Criteria

- `just eval-go` passes 45/45 fixtures after new fixtures added
- `just eval-load-results && just eval-results` shows full per-fixture pass/fail with sql_attempts and chart_source
- `mart_stage_latency` sql_gen first-attempt failure rate ≤ 5% across eval runs
- All promoted patterns in `learned_patterns.yaml` have `eval_validated: true` in
  `mart_query_patterns` before promotion
- `scorer.go` `chart_columns_valid` check runs on every fixture with `chart_type` set
- Zero fixtures that previously reported `chart_present: true` now show a blank chart
  in the Streamlit UI (spot-check 5 chart fixtures manually)
- `learned_patterns.yaml` has ≥ 15 promoted patterns after task 2 complete

## Out of Scope

- News → tool-calling upgrade (separate task, Anthropic provider only)
- Anthropic provider elevated trust / self-promotion
- Vector search over dbt docs
- New domain marts (no new dbt models in this branch)
- Multi-turn / follow-up context threading (future Phase 6 task)
