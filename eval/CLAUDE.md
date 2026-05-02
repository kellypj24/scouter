# eval/ — Claude Context

This is the only Go package in the project. The user is actively learning Go here — keep code idiomatic and use it as a teaching surface when relevant.

## Go version and style

- Go 1.26 (see `go.mod`)
- `log/slog` for structured logging (not `log` or `fmt.Println`)
- `flag` for CLI parsing — do not introduce third-party CLI frameworks
- Standard library only except `gopkg.in/yaml.v3` for fixture loading

## Package structure — keep it flat

One package (`package main`), no sub-packages. Files are split by concern:

| File | Responsibility |
|------|---------------|
| `main.go` | CLI flags, semaphore setup, goroutine dispatch, WaitGroup |
| `runner.go` | Subprocess invocation (`exec.CommandContext`) + JSON decode |
| `scorer.go` | Score `RunResult` against fixture `expect` block |
| `scorer_test.go` | Unit tests for scorer — run with `go test ./...` |
| `fixtures.go` | YAML loading into `Fixture` structs |
| `report.go` | `tabwriter` summary table + failure detail output |

## Subprocess contract

The runner calls `uv run python scripts/eval_runner.py --json "<question>"` as a subprocess. The Python script must output a single JSON object on stdout matching the `RunResult` struct. Do not change this contract without updating both sides.

## Concurrency pattern

Semaphore is a buffered `chan struct{}` — acquire before spawning Python, release in `defer`. Pre-allocate the results slice before launching goroutines so index-based writes are race-free without a mutex. Do not introduce `sync.Mutex` unless a genuinely shared map/slice is added.

## Testing

`scorer_test.go` covers scorer logic — run via `go test ./...` from `eval/`. No integration tests here; the Go runner is tested end-to-end by `just eval-go`.
