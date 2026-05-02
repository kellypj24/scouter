# scripts/ — Utility Scripts

| File | Purpose | Called by |
|------|---------|-----------|
| `eval_runner.py` | Runs one question through the full agent pipeline, outputs JSON | Go eval runner (`eval/`) |

## eval_runner.py

Headless single-question runner. The Go eval runner spawns it as a subprocess per fixture.

```bash
# JSON output (used by Go runner)
uv run python scripts/eval_runner.py --json "What are the top 10 stocks YTD?"

# Human-readable output (debugging)
uv run python scripts/eval_runner.py "What are the top 10 stocks YTD?"
```

### JSON output contract

The Go runner (`eval/runner.go`) decodes stdout into a `RunResult` struct. The contract:

```json
{
  "question": "...",
  "blocks": [
    {
      "sql": "SELECT ...",
      "row_count": 10,
      "chart_type": "bar",
      "prose": "...",
      "fallback_used": false
    }
  ],
  "error": null
}
```

**Do not change this schema without updating `eval/runner.go`.**

### Eval tagging

`eval_runner.py` prefixes `request_id` with `eval_{fixture_id}_` so fixture runs are queryable alongside production traffic in all observability marts.
