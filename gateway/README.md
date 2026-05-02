# gateway/ — Go HTTP Proxy

External-facing HTTP server that proxies to the FastAPI harness. Adds request ID injection and timing middleware. Written in Go.

## Files

| File | Responsibility |
|------|---------------|
| `main.go` | Entry point — CLI flags, HTTP server setup, graceful shutdown |
| `proxy.go` | `proxySSE()` — reverse proxies SSE streams from FastAPI to the client |
| `middleware.go` | `requestID()` middleware — generates/propagates `X-Request-ID` header |

## Usage

```bash
# Default: port 8080 → upstream localhost:8001
go run .

# Override
go run . -port 9090 -upstream http://fastapi:8001
```

Via `just`:
```bash
just gateway
```

## Request ID flow

```
Client → gateway (generates X-Request-ID UUID)
       → FastAPI /ask (reads X-Request-ID, stores in ContextVar)
       → Observability (reads from ContextVar, writes to SQLite)
```

## Why Go here?

The gateway is a natural boundary for cross-cutting concerns (auth, rate limiting, TLS termination) in a production deployment. The SSE proxy keeps the stream intact end-to-end — no buffering or re-serialization.

## Ports

| Service | Port |
|---------|------|
| Gateway (external) | 8080 |
| FastAPI (internal) | 8001 |
| Streamlit | 8501 |
