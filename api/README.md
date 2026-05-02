# api/ — FastAPI SSE Service

Internal HTTP boundary between the agent harness and any client (Go gateway, Streamlit, curl). All agent logic stays in `src/`; this module is thin wiring only.

## Files

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app, middleware, `/health` + `/ask` endpoints |
| `deps.py` | FastAPI dependency injection — builds `Orchestrator` with configured provider |
| `streaming.py` | `serialize_block()` — serializes `NarrativeBlock` to JSON string for SSE |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/ask` | Stream `NarrativeBlock` objects as SSE events |

## SSE event shape

```
event: block
data: <NarrativeBlock as JSON>

event: done
data: {}
```

## Request ID flow

The Go gateway sets `X-Request-ID` on every proxied request. The `request_id_middleware` picks this up (or generates a UUID for direct calls) and stores it in `request_id_var` ContextVar so all coroutines within the request inherit it automatically.

## Running

```bash
just run   # starts API on :8001
```
