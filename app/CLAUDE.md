# app/ — Claude Context

## No agent logic

This directory is a pure UI client. Never import from `src/agent/`, `src/data/`, or `src/models/` here. The only allowed imports from the project are types needed for rendering (e.g. `NarrativeBlock`) — and even those should be deserialized from the API JSON, not imported directly.

## HTTP client only

All data flows through the FastAPI SSE service. Do not add direct DuckDB connections, LLM calls, or pipeline triggers in this layer.

## Streamlit is scaffolding

The UI is replaceable. Logic that belongs in the harness must not accumulate here just because it's convenient to prototype in Streamlit.
