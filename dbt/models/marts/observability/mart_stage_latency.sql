-- Latency percentiles and failure rate per pipeline stage.
-- Primary use: identify which stage is the bottleneck or most error-prone.

with spans as (
    select * from {{ ref('stg_obs_spans') }}
)

select
    stage,
    count(*)                                                         as call_count,
    round(avg(latency_ms), 1)                                        as avg_latency_ms,
    percentile_cont(0.50) within group (order by latency_ms)         as p50_latency_ms,
    percentile_cont(0.95) within group (order by latency_ms)         as p95_latency_ms,
    percentile_cont(0.99) within group (order by latency_ms)         as p99_latency_ms,
    count_if(not success)                                            as failure_count,
    round(100.0 * count_if(not success) / count(*), 2)              as failure_rate_pct

from spans
group by stage
order by avg_latency_ms desc
