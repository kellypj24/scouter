package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// BlockResult mirrors the Python BlockResult dataclass JSON output.
type BlockResult struct {
	SubQuestion string   `json:"sub_question"`
	SQL         string   `json:"sql"`
	RowCount    int      `json:"row_count"`
	Columns     []string `json:"columns"`
	ChartType   *string  `json:"chart_type"`
	ColorCol    *string  `json:"color_col"`
	XCol        *string  `json:"x_col"`
	YCol        *string  `json:"y_col"`
	ChartBuilt  bool     `json:"chart_built"`
	Prose       string   `json:"prose"`
}

// RunResult mirrors the Python RunResult dataclass JSON output.
type RunResult struct {
	Question     string        `json:"question"`
	BlockCount   int           `json:"block_count"`
	FallbackUsed bool          `json:"fallback_used"`
	ContextUsed  bool          `json:"context_used"` // true when learned_patterns.yaml injected examples
	Blocks       []BlockResult `json:"blocks"`
}

// FixtureResult holds the scored outcome for a single fixture.
type FixtureResult struct {
	ID      string
	Question string
	Passed  bool
	Checks  []CheckResult
	Error   string
	Elapsed time.Duration
	Run     *RunResult
}

// runFixture calls `uv run python scripts/eval_runner.py --json --fixture-id <id> "<question>"`
// from the project root and parses the JSON output into a RunResult.
// The fixture ID is passed so eval runs are tagged in the observability database,
// enabling correlation between fixture failures and prod request telemetry.
func runFixture(ctx context.Context, projectRoot string, fixtureID string, question string) (*RunResult, error) {
	cmd := exec.CommandContext(ctx,
		"uv", "run", "python", "scripts/eval_runner.py", "--json", "--fixture-id", fixtureID, question,
	)
	cmd.Dir = projectRoot

	out, err := cmd.Output()
	if err != nil {
		var stderr string
		if ee, ok := err.(*exec.ExitError); ok {
			stderr = strings.TrimSpace(string(ee.Stderr))
		}
		if stderr != "" {
			return nil, fmt.Errorf("runner exited non-zero: %s", stderr)
		}
		return nil, fmt.Errorf("runner failed: %w", err)
	}

	var result RunResult
	if err := json.Unmarshal(out, &result); err != nil {
		return nil, fmt.Errorf("parse runner output: %w", err)
	}
	return &result, nil
}
