-- Staging view over raw_observability.eval_fixture_results.
-- Written by scripts/load_eval_results.py after each `just eval-go` run.
-- Grain: one row per fixture per eval run.

with source as (
    select * from {{ source('raw_observability', 'eval_fixture_results') }}
)

select
    fixture_id,
    cast(run_at as timestamp) as run_at,
    passed,
    failures,
    elapsed_ms
from source
