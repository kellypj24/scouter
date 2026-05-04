package main

import (
	"encoding/json"
	"os"
	"time"
)

// EvalRunJSON is the schema written to last_run.json after every eval run.
// Consumed by scripts/load_eval_results.py → DuckDB → mart_eval_runs.
type EvalRunJSON struct {
	RunAt    time.Time        `json:"run_at"`
	Total    int              `json:"total"`
	Passed   int              `json:"passed"`
	Fixtures []FixtureRunJSON `json:"fixtures"`
}

type FixtureRunJSON struct {
	ID        string   `json:"id"`
	Passed    bool     `json:"passed"`
	Failures  []string `json:"failures"`
	ElapsedMs int64    `json:"elapsed_ms"`
}

// writeResultsJSON serialises the final results slice to path as indented JSON.
// Called unconditionally after every eval run so last_run.json is always fresh.
func writeResultsJSON(path string, results []FixtureResult) error {
	nPass := 0
	summaries := make([]FixtureRunJSON, 0, len(results))
	for _, r := range results {
		if r.Passed {
			nPass++
		}
		var failures []string
		if r.Error != "" {
			failures = []string{"exception: " + r.Error}
		} else {
			for _, c := range r.Checks {
				if !c.Passed {
					msg := c.Name
					if c.Detail != "" {
						msg += ": " + c.Detail
					}
					failures = append(failures, msg)
				}
			}
		}
		if failures == nil {
			failures = []string{}
		}
		summaries = append(summaries, FixtureRunJSON{
			ID:        r.ID,
			Passed:    r.Passed,
			Failures:  failures,
			ElapsedMs: r.Elapsed.Milliseconds(),
		})
	}

	run := EvalRunJSON{
		RunAt:    time.Now().UTC(),
		Total:    len(results),
		Passed:   nPass,
		Fixtures: summaries,
	}
	data, err := json.MarshalIndent(run, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}
