with source as (
    select * from {{ source('raw_observability', 'dagster_runs') }}
)

select
    run_id,
    job_name,
    status,
    cast(started_at   as timestamp) as started_at,
    cast(completed_at as timestamp) as completed_at,
    duration_ms,
    tags

from source
where run_id is not null
