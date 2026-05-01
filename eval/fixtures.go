package main

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

// Expect mirrors the fields in assignments/eval/fixtures.yaml.
type Expect struct {
	MinRows          int    `yaml:"min_rows"`
	MaxBlocks        int    `yaml:"max_blocks"`
	Fallback         *bool  `yaml:"fallback"`   // nil means "don't check"
	ChartType        string `yaml:"chart_type"` // empty means "don't check"
	ColorColRequired bool   `yaml:"color_col_required"`
	SQLTable         string `yaml:"sql_table"`        // substring that must appear in SQL
	SQLNotContains   string `yaml:"sql_not_contains"` // substring that must NOT appear
	Unanswerable     bool   `yaml:"unanswerable"`
}

type Fixture struct {
	ID       string `yaml:"id"`
	Question string `yaml:"question"`
	Expect   Expect `yaml:"expect"`
}

type fixtureFile struct {
	Fixtures []Fixture `yaml:"fixtures"`
}

func loadFixtures(path string) ([]Fixture, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read fixtures: %w", err)
	}
	var f fixtureFile
	if err := yaml.Unmarshal(b, &f); err != nil {
		return nil, fmt.Errorf("parse fixtures: %w", err)
	}
	return f.Fixtures, nil
}
