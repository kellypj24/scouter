-- One row per request — joins span aggregates for a complete per-request view.
-- Primary use: understand what happened in a single request end-to-end.

with requests as (
    select * from {{ ref('stg_obs_requests') }}
),

spans as (
    select * from {{ ref('stg_obs_spans') }}
),

span_agg as (
    select
        request_id,
        count_if(stage = 'sql_gen' and not success)  as sql_retry_count,
        count_if(stage = 'news')                     as news_stage_count,
        max(case when stage = 'news' then news_items end) as news_items_fetched,
        max(case when stage = 'narrative' then chart_source end) as chart_source
    from spans
    group by request_id
)

select
    r.request_id,
    r.question,
    r.domain,
    r.started_at,
    r.latency_ms,
    r.block_count,
    r.fallback_used,
    r.error,
    coalesce(s.sql_retry_count, 0)   as sql_retry_count,
    s.news_stage_count > 0           as news_fetched,
    coalesce(s.news_items_fetched, 0) as news_items_fetched,
    coalesce(s.chart_source, 'none') as chart_source

from requests r
left join span_agg s using (request_id)
order by r.started_at desc
