package main

import (
	"fmt"
	"strings"
	"text/tabwriter"
	"os"
)

const (
	colorReset  = "\033[0m"
	colorRed    = "\033[31m"
	colorGreen  = "\033[32m"
	colorYellow = "\033[33m"
	colorDim    = "\033[2m"
	colorBold   = "\033[1m"
)

func green(s string) string  { return colorGreen + s + colorReset }
func red(s string) string    { return colorRed + s + colorReset }
func dim(s string) string    { return colorDim + s + colorReset }
func bold(s string) string   { return colorBold + s + colorReset }

func printSummary(results []FixtureResult) {
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(w, bold("ID\tSTATUS\tELAPSED\tFAILURES"))
	fmt.Fprintln(w, strings.Repeat("─", 72))

	for _, fr := range results {
		status := green("PASS")
		if !fr.Passed {
			status = red("FAIL")
		}

		var failures []string
		if fr.Error != "" {
			failures = append(failures, red("exception: ")+truncate(fr.Error, 60))
		} else {
			for _, c := range fr.Checks {
				if !c.Passed {
					detail := ""
					if c.Detail != "" {
						detail = ": " + c.Detail
					}
					failures = append(failures, red(c.Name)+detail)
				}
			}
		}

		failStr := dim("—")
		if len(failures) > 0 {
			failStr = failures[0]
		}

		fmt.Fprintf(w, "%s\t%s\t%.1fs\t%s\n",
			fr.ID, status, fr.Elapsed.Seconds(), failStr,
		)

		// Additional failure lines (indented under same row)
		for _, f := range failures[1:] {
			fmt.Fprintf(w, "\t\t\t%s\n", f)
		}
	}
	w.Flush()

	nPass := 0
	var totalElapsed float64
	for _, r := range results {
		if r.Passed {
			nPass++
		}
		totalElapsed += r.Elapsed.Seconds()
	}
	nTotal := len(results)

	fmt.Println()
	summary := fmt.Sprintf("%d/%d fixtures passed", nPass, nTotal)
	if nPass == nTotal {
		fmt.Printf("%s  %s\n", green(bold(summary)), dim(fmt.Sprintf("(%.1fs total)", totalElapsed)))
	} else {
		fmt.Printf("%s  %s\n", red(bold(summary)), dim(fmt.Sprintf("(%.1fs total)", totalElapsed)))
	}
}

func printFailures(results []FixtureResult) {
	var failed []FixtureResult
	for _, r := range results {
		if !r.Passed {
			failed = append(failed, r)
		}
	}
	if len(failed) == 0 {
		return
	}

	fmt.Printf("\n%s\n", red(bold("── Failure details ──────────────────────────────────────────────────")))
	for _, fr := range failed {
		fmt.Printf("\n%s: %s\n", red(bold(fr.ID)), fr.Question)
		if fr.Error != "" {
			fmt.Printf("  %s %s\n", red("exception:"), fr.Error)
			continue
		}
		if fr.Run != nil {
			primary := primaryBlock(fr.Run.Blocks)
			if primary != nil {
				fmt.Printf("  SQL: %s\n", dim(truncate(primary.SQL, 120)))
				chartType := "none"
				if primary.ChartType != nil {
					chartType = *primary.ChartType
				}
				fmt.Printf("  rows=%d  chart=%s  color=%v\n",
					primary.RowCount, chartType, primary.ColorCol)
			}
		}
		for _, c := range fr.Checks {
			if !c.Passed {
				detail := ""
				if c.Detail != "" {
					detail = ": " + c.Detail
				}
				fmt.Printf("  %s %s%s\n", red("✗"), c.Name, detail)
			}
		}
	}
	fmt.Println()
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
