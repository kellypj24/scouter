# tests/ — Test Suite

## Structure

```
tests/
  unit/           Pure unit tests — no I/O, fast
  integration/    Tests that hit DuckDB, SQLite, or the API
  conftest.py     Shared fixtures
```

## Requirements

- **>= 80% coverage** — enforced in CI (`just test` runs with `--cov`)
- Unit tests alongside implementation — not batched at the end of a feature
- Integration tests for anything touching DuckDB or external state

## Running

```bash
just test           # unit + integration with coverage
just test-unit      # unit only (faster, no DB required)
```

## Conventions

- Fixtures in `conftest.py` — shared DB connections, sample DataFrames, mock providers
- Use `pytest.mark.integration` for tests that need DuckDB
- LLM provider is mocked in unit tests via a test double implementing `LLMProvider` protocol
- Never mock DuckDB itself — integration tests hit a real in-memory or temp-file DuckDB instance
