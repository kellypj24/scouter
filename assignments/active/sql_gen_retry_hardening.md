# Assignment: SQL Gen Retry Hardening (Schema-Level Guards)

**Branch**: `feature/sql-gen-retry-hardening`  
**Phase**: 5 (Production Harness)  
**Status**: Planning  
**Depends on**: `feature/observability` merged to `main`

## Goal

Reduce the ~20% sql_gen first-attempt failure rate for three persistent offenders identified
by the observability framework. All three already recover on retry and pass evals — this is a
latency and token-cost problem, not a correctness problem. The fix is schema-level validation
guards (same pattern as the existing `date`-on-screener guard) rather than more prompt text,
which has shown diminishing returns.

## Background

Two rounds of eval-go (20 fixtures each) surfaced these consistent first-attempt failures:

| Fixture | Error | Current state |
|---------|-------|---------------|
| `sector_ytd_performance` | LLM references `year` column in `mart_sector_fundamentals` | Fails attempt 1, recovers attempt 2. Prompt additions not working. |
| `risk_profile_sharpe` | LLM selects `volatility_pctile_in_sector` from `mart_equity_screener` instead of `mart_risk_profile` | Fails attempt 1, recovers attempt 2. Prompt additions not working. |
| `multistock_top5_trend` | LLM adds `LIMIT` to outer `mart_equity_performance` query | Already has `_validate_sql` guard; fails attempt 1, recovers attempt 2. |
| `moving_avg_apple` | LLM uses `AVG() GROUP BY` instead of window function | Intermittent (appeared once). Existing guard fires correctly. |

Prompt hardening was tried for the first two — adding explicit `NEVER` instructions with column
lists. It did not reduce the failure rate. The LLM generates the wrong column confidently before
the constraint is reached in the prompt. Schema-level validation is the right layer.

## Implementation Plan

### 1. `year`-in-sector-fundamentals guard (`query_agent._validate_schema`)

Add a check analogous to the existing screener `date` guard (lines 531–541 of `query_agent.py`):

```python
# In _validate_schema, after the screener-date block:
sector_fundamentals_in_query = any(
    "mart_sector_fundamentals" in name for _, name in alias_to_table.values()
)
if sector_fundamentals_in_query:
    for col in statement.find_all(exp.Column):
        if col.name.lower() in ("year", "date", "month", "quarter") and not col.table:
            errors.append(
                "mart_sector_fundamentals has no time-dimension columns (no date, year, "
                "month, or quarter). It is a current snapshot. Remove all date filters. "
                "Available columns: sector, avg_ytd_return_ew, avg_mtd_return_ew, "
                "avg_volatility_20d, avg_sharpe_20d, avg_drawdown_from_52w_high, "
                "median_ytd_return, pct_constituents_positive_ytd, ticker_count, "
                "total_market_cap, avg_market_cap."
            )
            break
```

### 2. `volatility_pctile_in_sector` / `sharpe_pctile_in_sector` wrong-table guard

Two options (pick one):

**Option A — validation guard** (consistent with the pattern above):
In `_validate_schema`, after resolving column→table, if a percentile column
(`volatility_pctile_in_sector`, `sharpe_pctile_in_sector`, `risk_score`) is
referenced against `mart_equity_screener`, emit a specific error pointing to
`mart_risk_profile`.

**Option B — denormalize** (eliminates the problem at the data layer):
Add `volatility_pctile_in_sector` and `sharpe_pctile_in_sector` to
`dbt/models/marts/equity/mart_equity_screener.sql` via a JOIN to `mart_risk_profile`.
The LLM's instinct to look in screener would then be correct. Downside: increases
screener complexity and couples the equity/risk mart layers.

**Recommendation**: Option A — keeps mart boundaries clean and is consistent with
how the `date`-on-screener guard works.

### 3. `moving_avg_apple` AVG-GROUP-BY guard

The guard already exists in `_validate_sql` (lines 423–436 of `query_agent.py`) and fires
correctly. No new work needed — this is LLM variability on a rare code path.

## Acceptance Criteria

- `just eval-go` runs 20/20 with zero sql_gen retries for `sector_ytd_performance` and
  `risk_profile_sharpe` across two consecutive runs
- No change to eval pass rate (still 20/20)
- Observability `mart_stage_latency` shows sql_gen failure rate < 5% across eval runs
- No new prompt text added (guards live in `_validate_schema` / `_validate_sql` only)
