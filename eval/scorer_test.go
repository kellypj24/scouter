package main

import (
	"testing"
)

func strPtr(s string) *string { return &s }
func boolPtr(b bool) *bool    { return &b }

func makeRun(blockCount int, fallback bool, blocks []BlockResult) *RunResult {
	return &RunResult{
		Question:     "test question",
		BlockCount:   blockCount,
		FallbackUsed: fallback,
		Blocks:       blocks,
	}
}

func makeBlock(rows int, chartType, colorCol, sql string) BlockResult {
	b := BlockResult{RowCount: rows, SQL: sql}
	if chartType != "" {
		b.ChartType = strPtr(chartType)
		b.ChartBuilt = true
	}
	if colorCol != "" {
		b.ColorCol = strPtr(colorCol)
	}
	return b
}

// checkNamed finds a CheckResult by name or returns the zero value.
func checkNamed(checks []CheckResult, name string) (CheckResult, bool) {
	for _, c := range checks {
		if c.Name == name {
			return c, true
		}
	}
	return CheckResult{}, false
}

func TestScore_BlockCount(t *testing.T) {
	run := makeRun(3, false, nil)

	checks := score(run, Expect{MaxBlocks: 2})
	c, ok := checkNamed(checks, "block_count")
	if !ok {
		t.Fatal("block_count check missing")
	}
	if c.Passed {
		t.Error("expected block_count to fail when 3 > max 2")
	}

	run.BlockCount = 1
	checks = score(run, Expect{MaxBlocks: 2})
	c, _ = checkNamed(checks, "block_count")
	if !c.Passed {
		t.Error("expected block_count to pass when 1 <= max 2")
	}
}

func TestScore_NoFallback(t *testing.T) {
	run := makeRun(1, true, []BlockResult{makeBlock(5, "", "", "SELECT 1")})

	// fallback: false in fixture → check emitted and must fail
	checks := score(run, Expect{MaxBlocks: 2, Fallback: boolPtr(false)})
	c, ok := checkNamed(checks, "no_fallback")
	if !ok {
		t.Fatal("no_fallback check missing")
	}
	if c.Passed {
		t.Error("expected no_fallback to fail when fallback was used")
	}

	// fallback: nil → check not emitted
	run.FallbackUsed = true
	checks = score(run, Expect{MaxBlocks: 2})
	if _, ok := checkNamed(checks, "no_fallback"); ok {
		t.Error("no_fallback check should not be emitted when Fallback is nil")
	}
}

func TestScore_Unanswerable(t *testing.T) {
	// Correct unanswerable: 0 rows, no SQL
	run := makeRun(1, false, []BlockResult{{RowCount: 0, SQL: ""}})
	checks := score(run, Expect{Unanswerable: true, MaxBlocks: 2})
	c, ok := checkNamed(checks, "unanswerable_block")
	if !ok {
		t.Fatal("unanswerable_block check missing")
	}
	if !c.Passed {
		t.Errorf("expected unanswerable_block to pass, got detail: %s", c.Detail)
	}

	// Wrong: has rows
	run = makeRun(1, false, []BlockResult{{RowCount: 5, SQL: ""}})
	checks = score(run, Expect{Unanswerable: true, MaxBlocks: 2})
	c, _ = checkNamed(checks, "unanswerable_block")
	if c.Passed {
		t.Error("expected unanswerable_block to fail when rows > 0")
	}

	// Wrong: has SQL
	run = makeRun(1, false, []BlockResult{{RowCount: 0, SQL: "SELECT 1"}})
	checks = score(run, Expect{Unanswerable: true, MaxBlocks: 2})
	c, _ = checkNamed(checks, "unanswerable_block")
	if c.Passed {
		t.Error("expected unanswerable_block to fail when SQL is non-empty")
	}
}

func TestScore_MinRows(t *testing.T) {
	block := makeBlock(10, "", "", "SELECT 1")
	run := makeRun(1, false, []BlockResult{block})

	checks := score(run, Expect{MinRows: 10, MaxBlocks: 2})
	c, _ := checkNamed(checks, "min_rows")
	if !c.Passed {
		t.Errorf("expected min_rows to pass with 10 rows (need 10), detail: %s", c.Detail)
	}

	checks = score(run, Expect{MinRows: 11, MaxBlocks: 2})
	c, _ = checkNamed(checks, "min_rows")
	if c.Passed {
		t.Error("expected min_rows to fail with 10 rows (need 11)")
	}
}

func TestScore_ChartType(t *testing.T) {
	block := makeBlock(10, "bar", "", "SELECT 1")
	run := makeRun(1, false, []BlockResult{block})

	checks := score(run, Expect{ChartType: "bar", MaxBlocks: 2})
	c, ok := checkNamed(checks, "chart_type")
	if !ok {
		t.Fatal("chart_type check missing")
	}
	if !c.Passed {
		t.Errorf("expected chart_type to pass, detail: %s", c.Detail)
	}

	checks = score(run, Expect{ChartType: "line", MaxBlocks: 2})
	c, _ = checkNamed(checks, "chart_type")
	if c.Passed {
		t.Error("expected chart_type to fail when got 'bar' but expected 'line'")
	}
}

func TestScore_ColorColRequired(t *testing.T) {
	block := makeBlock(10, "line", "ticker", "SELECT 1")
	run := makeRun(1, false, []BlockResult{block})

	checks := score(run, Expect{ColorColRequired: true, MaxBlocks: 2})
	c, ok := checkNamed(checks, "color_col")
	if !ok {
		t.Fatal("color_col check missing")
	}
	if !c.Passed {
		t.Errorf("expected color_col to pass when color_col is set, detail: %s", c.Detail)
	}

	// No color col
	block2 := makeBlock(10, "line", "", "SELECT 1")
	run2 := makeRun(1, false, []BlockResult{block2})
	checks = score(run2, Expect{ColorColRequired: true, MaxBlocks: 2})
	c, _ = checkNamed(checks, "color_col")
	if c.Passed {
		t.Error("expected color_col to fail when color_col is nil")
	}
}

func TestScore_SQLTable(t *testing.T) {
	block := makeBlock(10, "", "", "SELECT ticker FROM main_equity.mart_equity_screener LIMIT 10")
	run := makeRun(1, false, []BlockResult{block})

	checks := score(run, Expect{SQLTable: "mart_equity_screener", MaxBlocks: 2})
	c, _ := checkNamed(checks, "sql_table")
	if !c.Passed {
		t.Errorf("expected sql_table to pass, detail: %s", c.Detail)
	}

	checks = score(run, Expect{SQLTable: "mart_equity_performance", MaxBlocks: 2})
	c, _ = checkNamed(checks, "sql_table")
	if c.Passed {
		t.Error("expected sql_table to fail when table is absent from SQL")
	}
}

func TestScore_SQLNotContains(t *testing.T) {
	block := makeBlock(10, "", "", "SELECT ticker, date FROM mart_equity_performance")
	run := makeRun(1, false, []BlockResult{block})

	checks := score(run, Expect{SQLNotContains: "moving_average", MaxBlocks: 2})
	c, _ := checkNamed(checks, "sql_clean")
	if !c.Passed {
		t.Errorf("expected sql_clean to pass, detail: %s", c.Detail)
	}

	checks = score(run, Expect{SQLNotContains: "date", MaxBlocks: 2})
	c, _ = checkNamed(checks, "sql_clean")
	if c.Passed {
		t.Error("expected sql_clean to fail when forbidden substring is present")
	}
}

func TestPrimaryBlock_EmptyBlocks(t *testing.T) {
	if p := primaryBlock(nil); p != nil {
		t.Error("expected nil for empty blocks")
	}
	if p := primaryBlock([]BlockResult{}); p != nil {
		t.Error("expected nil for empty blocks")
	}
}

func TestPrimaryBlock_PicksMostRows(t *testing.T) {
	blocks := []BlockResult{
		{RowCount: 5},
		{RowCount: 100},
		{RowCount: 20},
	}
	p := primaryBlock(blocks)
	if p == nil || p.RowCount != 100 {
		t.Errorf("expected primary block to have 100 rows, got %v", p)
	}
}

func TestLoadFixtures(t *testing.T) {
	fixtures, err := loadFixtures("../assignments/eval/fixtures.yaml")
	if err != nil {
		t.Fatalf("loadFixtures: %v", err)
	}
	if len(fixtures) == 0 {
		t.Fatal("expected at least one fixture")
	}
	for _, fx := range fixtures {
		if fx.ID == "" {
			t.Error("fixture has empty ID")
		}
		if fx.Question == "" {
			t.Errorf("fixture %q has empty question", fx.ID)
		}
	}
}
