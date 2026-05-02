# gateway/ — Claude Context

This is a Go package. The user is learning Go here — keep it idiomatic and use it as a teaching surface.

## Go version and style

- Go 1.26 (see `go.mod`)
- `log/slog` for structured logging
- Standard library only — no third-party router or middleware frameworks
- `net/http` + `httputil.ReverseProxy` or manual proxy (see `proxy.go`)

## SSE proxy requirement

The proxy must stream the response body without buffering — SSE requires each `event: block\ndata: ...\n\n` chunk to reach the client immediately. Do not use `io.ReadAll` or any buffered copy in the proxy path. Flush after each write.

## Graceful shutdown

The server uses `signal.Notify` + `srv.Shutdown()` with a 10-second context. Maintain this pattern — do not remove it or replace with `os.Exit`.

## Middleware is additive

New cross-cutting concerns (auth, rate limiting, logging) belong in new middleware functions that wrap the mux, not inline in handler functions.

## WriteTimeout

Set to 5 minutes to accommodate long SSE streams. Do not reduce this without considering the worst-case query + narrative latency.
