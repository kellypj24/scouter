# Status

Current state only; history is in git and the PRs. Update this file in the same PR as the
work it describes.

_Updated 2026-10-28._

## Now

- Parked. Phases 1–4 done (query agent, narrative and charts, orchestrator, FastAPI + Go
  gateway + Streamlit). Phase 5, the production harness, is in progress.
- Last merged: ORACLE patterns (#19), eval tune round 37 (#20), CI lint and full suite
  on push to main (#21).
- Eval: 45 fixtures; the failures left are local-model ceiling (see CLAUDE.md, "Local
  model capability ceiling").

## Next

1. Run the eval on `SCOUTER_LLM_PROVIDER=anthropic` to confirm the ceiling fixtures pass.
2. Chart `x_col`/`y_col` validation in the Go scorer
   (`assignments/active/eval_harness_round2.md`, Task 3).
3. Per-domain fallback SQL in place of the single generic screener.
4. Load dbt's `manifest.json` and `catalog.json` for schema context.
5. Pattern synthesis: an LLM pass that proposes `learned_patterns` from eval failures.

## Open decisions

- News via tool calling once on the Anthropic provider.

## Blocked on

Nothing; parked by choice.
