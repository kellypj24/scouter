-- Dagster pipeline run summary — success rate, duration, frequency by job.
-- Pairs with mart_request_metrics: data freshness affects answer quality.

with runs as (
    select * from {{ ref('stg_obs_dagster_runs') }}
)

select
    job_name,
    count(*)                                                          as total_runs,
    count_if(status = 'SUCCESS')                                      as successful_runs,
    count_if(status = 'FAILURE')                                      as failed_runs,
    round(100.0 * count_if(status = 'SUCCESS') / count(*), 2)        as success_rate_pct,
    round(avg(duration_ms) / 1000.0, 1)                              as avg_duration_sec,
    percentile_cont(0.95) within group (order by duration_ms) / 1000 as p95_duration_sec,
    max(started_at)                                                   as last_run_at,
    max(case when status = 'SUCCESS' then started_at end)            as last_success_at

from runs
group by job_name
order by total_runs desc
