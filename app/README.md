# app/ — Streamlit UI

Chat interface for the Scouter agent. Connects to the FastAPI service via SSE — no direct imports from `src/`.

## Files

| File | Responsibility |
|------|---------------|
| `main.py` | Streamlit app shell — chat loop, state management, SSE client |
| `components/block_renderer.py` | Renders a `NarrativeBlock` as HTML + Plotly in the Streamlit layout |

## Architecture

The app is a pure HTTP client. It sends `POST /ask` to the Go gateway (or directly to FastAPI in dev) and renders the `block` SSE events as they arrive. It has no agent, data, or pipeline logic.

```
User types question
  → app/main.py (httpx SSE client)
  → POST gateway:8080/ask
  → gateway proxies → FastAPI:8001/ask
  → streams NarrativeBlock events
  → app renders each block as it arrives
```

## Running

```bash
just ui     # starts Streamlit on :8501
```

Requires the FastAPI service (and optionally the gateway) to be running.
