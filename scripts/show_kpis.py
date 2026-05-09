"""Print current KPI values vs targets. Usage: uv run python scripts/show_kpis.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

from src.observability.kpis import evaluate_kpis

conn = duckdb.connect("data/scouter.duckdb", read_only=True)
results = evaluate_kpis(conn)
conn.close()

w = max(len(r["name"]) for r in results)
for r in results:
    if r["error"]:
        print(f"{r['name']:<{w}}  {'N/A':>10}  target {r['target']:.2f}  ERROR: {r['error'][:60]}")
    else:
        status = "PASS" if r["passing"] else "FAIL"
        unit = "%" if r["unit"] == "ratio" else "ms"
        val = f"{r['current'] * 100:.1f}" if r["unit"] == "ratio" else f"{r['current']:.0f}"
        tgt = f"{r['target'] * 100:.1f}" if r["unit"] == "ratio" else f"{r['target']:.0f}"
        print(f"{r['name']:<{w}}  {val:>8}{unit}  target {tgt}{unit}  [{status}]")
