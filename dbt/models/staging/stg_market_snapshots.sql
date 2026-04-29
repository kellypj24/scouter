with source as (
    select * from {{ source('raw', 'market_summaries') }}
),

cleaned as (
    select
        upper(symbol)                       as ticker,
        cast(current_price as double)       as current_price,
        cast(day_high as double)            as day_high,
        cast(day_low as double)             as day_low,
        cast(volume as bigint)              as volume,
        cast(market_cap as double)          as market_cap,
        cast(week_52_high as double)        as fifty_two_week_high,
        cast(week_52_low as double)         as fifty_two_week_low,
        cast(last_updated as timestamp)     as snapshot_at

    from source
    where current_price is not null
      and current_price > 0
)

select * from cleaned
