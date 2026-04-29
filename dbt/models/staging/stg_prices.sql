with source as (
    select * from {{ source('raw', 'historical_data') }}
),

cleaned as (
    select
        symbol                      as ticker,
        cast(date as date)          as date,
        cast(open as double)        as open,
        cast(high as double)        as high,
        cast(low as double)         as low,
        cast(close as double)       as close,
        cast(volume as bigint)      as volume,
        cast(last_updated as timestamp) as ingested_at

    from source
    where close is not null
      and close > 0
      and volume > 0
)

select * from cleaned
