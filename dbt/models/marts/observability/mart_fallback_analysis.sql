-- Fallback rate and SQL retry frequency by domain.
-- Primary use: identify which question domains need prompt hardening.

with requests as (
    select * from {{ ref('stg_obs_requests') }}
),

sql_retries as (
    select
        request_id,
        count_if(stage = 'sql_gen' and not success) as retry_count
    from {{ ref('stg_obs_spans') }}
    group by request_id
)

select
    coalesce(r.domain, 'unknown')                              as domain,
    count(*)                                                   as total_requests,
    count_if(r.fallback_used)                                  as fallback_count,
    round(100.0 * count_if(r.fallback_used) / count(*), 2)    as fallback_rate_pct,
    round(avg(r.latency_ms), 1)                                as avg_latency_ms,
    sum(coalesce(s.retry_count, 0))                            as total_sql_retries,
    round(avg(coalesce(s.retry_count, 0)), 2)                  as avg_retries_per_request

from requests r
left join sql_retries s using (request_id)
group by r.domain
order by fallback_rate_pct desc
