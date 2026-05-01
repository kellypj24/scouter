package main

import (
	"fmt"
	"strings"
)

// CheckResult is a single pass/fail assertion within a fixture run.
type CheckResult struct {
	Name   string
	Passed bool
	Detail string
}

func check(name string, passed bool, detail string) CheckResult {
	return CheckResult{Name: name, Passed: passed, Detail: detail}
}

// primaryBlock returns the block with the most rows, or nil.
func primaryBlock(blocks []BlockResult) *BlockResult {
	if len(blocks) == 0 {
		return nil
	}
	best := &blocks[0]
	for i := range blocks[1:] {
		if blocks[i+1].RowCount > best.RowCount {
			best = &blocks[i+1]
		}
	}
	return best
}

// score evaluates a RunResult against fixture expectations and returns all checks.
func score(run *RunResult, ex Expect) []CheckResult {
	var checks []CheckResult

	// Block count
	maxBlocks := ex.MaxBlocks
	if maxBlocks == 0 {
		maxBlocks = 2
	}
	checks = append(checks, check(
		"block_count",
		run.BlockCount <= maxBlocks,
		fmt.Sprintf("%d block(s) (max %d)", run.BlockCount, maxBlocks),
	))

	// Fallback — only checked when explicitly set to false in fixture
	if ex.Fallback != nil && !*ex.Fallback {
		checks = append(checks, check(
			"no_fallback",
			!run.FallbackUsed,
			func() string {
				if run.FallbackUsed {
					return "rule-based fallback SQL was used"
				}
				return ""
			}(),
		))
	}

	// Unanswerable — expect all blocks have 0 rows and at least one has no SQL
	if ex.Unanswerable {
		allEmpty := true
		anyNoSQL := false
		for _, b := range run.Blocks {
			if b.RowCount > 0 {
				allEmpty = false
			}
			if b.SQL == "" {
				anyNoSQL = true
			}
		}
		passed := allEmpty && anyNoSQL
		detail := ""
		if !passed {
			detail = "expected 0-row block with no SQL"
		}
		checks = append(checks, check("unanswerable_block", passed, detail))
		return checks // nothing else to check
	}

	// Min rows
	minRows := ex.MinRows
	if minRows == 0 {
		minRows = 1
	}
	bestRows := 0
	for _, b := range run.Blocks {
		if b.RowCount > bestRows {
			bestRows = b.RowCount
		}
	}
	checks = append(checks, check(
		"min_rows",
		bestRows >= minRows,
		fmt.Sprintf("best block had %d rows (need %d)", bestRows, minRows),
	))

	primary := primaryBlock(run.Blocks)
	if primary == nil {
		return checks
	}

	// Chart type
	if ex.ChartType != "" {
		got := ""
		if primary.ChartType != nil {
			got = *primary.ChartType
		}
		checks = append(checks, check(
			"chart_type",
			got == ex.ChartType,
			fmt.Sprintf("got %q, expected %q", got, ex.ChartType),
		))
		checks = append(checks, check(
			"chart_built",
			primary.ChartBuilt,
			func() string {
				if primary.ChartType != nil {
					return "chart spec present but figure failed to build"
				}
				return "no chart spec"
			}(),
		))
	}

	// Color col required
	if ex.ColorColRequired {
		checks = append(checks, check(
			"color_col",
			primary.ColorCol != nil,
			fmt.Sprintf("color_col=%v (should be non-null for multi-entity chart)", primary.ColorCol),
		))
	}

	// SQL table substring
	if ex.SQLTable != "" && primary.SQL != "" {
		checks = append(checks, check(
			"sql_table",
			strings.Contains(strings.ToLower(primary.SQL), strings.ToLower(ex.SQLTable)),
			fmt.Sprintf("expected %q in SQL", ex.SQLTable),
		))
	}

	// SQL must-not-contain
	if ex.SQLNotContains != "" && primary.SQL != "" {
		checks = append(checks, check(
			"sql_clean",
			!strings.Contains(strings.ToLower(primary.SQL), strings.ToLower(ex.SQLNotContains)),
			fmt.Sprintf("SQL must not contain %q", ex.SQLNotContains),
		))
	}

	return checks
}
