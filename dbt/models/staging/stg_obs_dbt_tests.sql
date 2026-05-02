with source as (
    select * from {{ source('raw_observability', 'dbt_test_results') }}
)

select
    test_unique_id,
    test_name,
    model,
    status,
    cast(execution_time_s as double) as execution_time_s,
    cast(failures as integer)        as failures,
    message,
    cast(run_at as timestamp)        as run_at

from source
where test_unique_id is not null
