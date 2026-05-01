// eval runs Scouter eval fixtures concurrently and scores each against its
// expected properties. Exits with code 1 if any fixture fails (CI-friendly).
//
// Run from the project root or pass -root:
//
//	go run ./eval [flags]
//	go run ./eval -filter screener
//	go run ./eval -concurrency 6 -timeout 120s
//	go run ./eval -fail-fast
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

func main() {
	filter      := flag.String("filter", "", "Only run fixtures whose ID contains this substring")
	concurrency := flag.Int("concurrency", runtime.NumCPU(), "Max fixtures to run in parallel")
	timeout     := flag.Duration("timeout", 90*time.Second, "Per-fixture timeout")
	failFast    := flag.Bool("fail-fast", false, "Stop after first failing fixture")
	root        := flag.String("root", "", "Project root directory (default: current working directory)")
	flag.Parse()

	projectRoot := *root
	if projectRoot == "" {
		wd, err := os.Getwd()
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			os.Exit(1)
		}
		projectRoot = wd
	}

	fixturePath := filepath.Join(projectRoot, "assignments", "eval", "fixtures.yaml")
	fixtures, err := loadFixtures(fixturePath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	if *filter != "" {
		var filtered []Fixture
		for _, fx := range fixtures {
			if strings.Contains(fx.ID, *filter) {
				filtered = append(filtered, fx)
			}
		}
		if len(filtered) == 0 {
			fmt.Fprintf(os.Stderr, "no fixtures match filter %q\n", *filter)
			os.Exit(1)
		}
		fixtures = filtered
	}

	fmt.Printf("Running %d fixture(s) with concurrency=%d timeout=%s\n\n",
		len(fixtures), *concurrency, *timeout)

	// sem is a counting semaphore — at most *concurrency goroutines run the
	// Python subprocess at once. We still launch all goroutines immediately so
	// the WaitGroup and results slice are simple, but goroutines block on sem
	// until a slot is free.
	sem     := make(chan struct{}, *concurrency)
	results := make([]FixtureResult, len(fixtures))
	var (
		mu       sync.Mutex
		stopped  bool
		wg       sync.WaitGroup
	)

	for i, fx := range fixtures {
		wg.Add(1)
		go func(idx int, fixture Fixture) {
			defer wg.Done()

			// Check fail-fast before acquiring semaphore slot.
			mu.Lock()
			if stopped {
				mu.Unlock()
				results[idx] = FixtureResult{
					ID:       fixture.ID,
					Question: fixture.Question,
					Error:    "skipped (fail-fast)",
				}
				return
			}
			mu.Unlock()

			sem <- struct{}{}        // acquire
			defer func() { <-sem }() // release

			ctx, cancel := context.WithTimeout(context.Background(), *timeout)
			defer cancel()

			fmt.Printf("  → %s\n", dim(fixture.ID))
			t0 := time.Now()
			run, runErr := runFixture(ctx, projectRoot, fixture.Question)
			elapsed := time.Since(t0)

			var fr FixtureResult
			fr.ID       = fixture.ID
			fr.Question = fixture.Question
			fr.Elapsed  = elapsed
			fr.Run      = run

			if runErr != nil {
				fr.Error  = runErr.Error()
				fr.Passed = false
			} else {
				fr.Checks = score(run, fixture.Expect)
				fr.Passed = true
				for _, c := range fr.Checks {
					if !c.Passed {
						fr.Passed = false
						break
					}
				}
			}

			icon := green("✓")
			if !fr.Passed {
				icon = red("✗")
			}
			fmt.Printf("  %s %s (%.1fs)\n", icon, dim(fixture.ID), elapsed.Seconds())

			results[idx] = fr

			if *failFast && !fr.Passed {
				mu.Lock()
				stopped = true
				mu.Unlock()
				fmt.Println(yellow("  --fail-fast: stopping after first failure"))
			}
		}(i, fx)
	}

	wg.Wait()
	fmt.Println()

	// Filter out skipped (empty) entries when fail-fast cut things short.
	var final []FixtureResult
	for _, r := range results {
		if r.ID != "" {
			final = append(final, r)
		}
	}

	printSummary(final)
	printFailures(final)

	for _, r := range final {
		if !r.Passed {
			os.Exit(1)
		}
	}
}

func yellow(s string) string { return colorYellow + s + colorReset }
