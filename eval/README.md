# eval — Go concurrent fixture runner

Runs Scouter eval fixtures in parallel and scores each against its expected properties.
Exits with code 1 on any failure — suitable for CI.

## Usage

Use `just` from the **project root** (recommended):

```bash
just eval-go
just eval-go-filter screener
just eval-go-build
```

Or run Go directly — the `-root` flag tells the runner where the project root is:

```bash
# From the eval/ directory
go run . -root ..
go run . -root .. -filter screener
go run . -root .. -concurrency 4 -timeout 120s
go run . -root .. -fail-fast

# Compile a binary, then run from project root
go build -o scouter-eval .
./scouter-eval -root ..
```

## How it works

Each fixture in `assignments/eval/fixtures.yaml` becomes a goroutine. A counting semaphore
(buffered `chan struct{}`) limits how many Python subprocesses run at once. Each goroutine:

1. Acquires a semaphore slot
2. Spawns `uv run python scripts/eval_runner.py --json "<question>"` with a timeout context
3. Decodes the JSON output into a `RunResult`
4. Scores the result against the fixture's `expect:` block
5. Sends its `FixtureResult` into the results slice (pre-allocated, no mutex needed for writes)

All goroutines are waited on with a `sync.WaitGroup`. Results print in fixture-file order.

## Go concepts in play

| Concept | Where |
|---------|-------|
| Goroutines | one per fixture in `main.go` |
| Counting semaphore | `chan struct{}` in `main.go` |
| `sync.WaitGroup` | wait for all fixtures to finish |
| `context.WithTimeout` | per-fixture deadline passed to `exec.CommandContext` |
| `os/exec` | spawn Python subprocess, capture stdout |
| `encoding/json` | decode runner output into Go structs |
| `gopkg.in/yaml.v3` | load fixtures.yaml |
| `text/tabwriter` | aligned summary table |
| `flag` | CLI flag parsing |

## Relationship to Python scripts

```
eval/ (this package)           concurrent orchestrator — scores fixtures
    │  os/exec subprocess
    ▼
scripts/eval_runner.py         required — runs the full agent pipeline and
                               outputs JSON that this package decodes
```

`scripts/eval_score.py` has been removed; this package replaces it.

## Fixture format

See `assignments/eval/fixtures.yaml`. Each fixture:

```yaml
- id: screener_top10_ytd
  question: "What are the top 10 best performing stocks this year?"
  expect:
    min_rows: 10
    max_blocks: 1
    fallback: false          # rule-based fallback must not be used
    chart_type: bar
    color_col_required: false
    sql_table: mart_equity_screener
    sql_not_contains: "date" # optional: substring that must NOT appear in SQL
    unanswerable: false      # if true: expect 0 rows + no SQL (metric absent)
```

All `expect` fields are optional — omit any you don't want to assert.
