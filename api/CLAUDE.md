# api/ — Claude Context

## Thin wiring only

This module has no agent logic. It imports from `src/` but never implements business rules. If you find yourself adding conditional logic, LLM calls, or data transforms here, it belongs in `src/agent/` or `src/data/` instead.

## Request ID is required

The `request_id_middleware` must run on every request. Do not bypass it or add routes outside the app's middleware stack. The ContextVar must be set before any `src/` code is called — observability telemetry depends on it.

## SSE contract is stable

The `block` / `done` event names are consumed by the Streamlit client and Go eval runner. Do not change them without updating `app/components/` and `scripts/eval_runner.py`.

## Dependency injection

`deps.py` is where the `Orchestrator` (and its `provider`, `query_agent`, `narrative_agent` dependencies) is constructed. Add new dependencies here, not inside route handlers.
