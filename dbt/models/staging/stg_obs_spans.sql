with source as (
    select * from {{ source('raw_observability', 'spans') }}
)

select
    id,
    request_id,
    stage,
    attempt,
    cast(started_at as timestamp) as started_at,
    latency_ms,
    cast(success as boolean)      as success,
    error,
    sql_length,
    row_count,
    chart_source,
    news_items,
    domain,
    mart,
    sql_hash

from source
where request_id is not null
