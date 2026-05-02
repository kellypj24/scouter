# assignments/ — Work Tracking

Structured task definitions and eval fixtures. Kept in the repo for traceability.

## Directories

| Directory | Contents |
|-----------|---------|
| `active/` | Current work in progress — one file per task |
| `completed/` | Finished tasks — reference for patterns and decisions |
| `templates/` | Task definition templates |
| `eval/` | `fixtures.yaml` — eval fixture definitions used by the Go runner |

## Fixture format

`eval/fixtures.yaml` is the source of truth for the eval suite. The Go runner (`eval/`) loads this file and runs each fixture against the live agent. See `eval/README.md` for the full fixture schema.

## Active tasks

Check `active/` for current phase 5 work. When a task is complete, move the file to `completed/`.
