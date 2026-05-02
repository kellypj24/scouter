with source as (
    select * from {{ source('raw_observability', 'requests') }}
)

select
    request_id,
    question,
    domain,
    cast(started_at   as timestamp) as started_at,
    cast(completed_at as timestamp) as completed_at,
    latency_ms,
    block_count,
    cast(fallback_used as boolean)  as fallback_used,
    error

from source
where request_id is not null
