-- dbt test health by model — pass rate, flapping tests, total failing rows.
-- Pairs with mart_pipeline_health: a model with failures means downstream
-- agent queries may be returning dirty data, degrading answer quality.

with tests as (
    select * from {{ ref('stg_obs_dbt_tests') }}
)

select
    coalesce(model, split_part(test_name, '_', 1) || '_' || split_part(test_name, '_', 2)) as model,
    count(*)                                                             as total_tests,
    count_if(status = 'pass')                                           as passing_tests,
    count_if(status in ('fail', 'error'))                               as failing_tests,
    round(100.0 * count_if(status = 'pass') / count(*), 2)             as pass_rate_pct,
    sum(failures)                                                        as total_failing_rows,
    round(avg(execution_time_s), 3)                                      as avg_execution_time_s,
    max(run_at)                                                          as last_run_at,
    max(case when status in ('fail', 'error') then run_at end)          as last_failure_at

from tests
group by 1
order by failing_tests desc, total_tests desc
