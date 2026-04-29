with returns as (
    select * from {{ ref('int_daily_returns') }}
    where sector is not null
      and sector != 'Unknown'
),

aggregated as (
    select
        sector,
        date,

        -- Constituent count
        count(distinct ticker)                  as ticker_count,

        -- Equal-weight sector return (average of individual daily returns)
        avg(daily_return)                       as sector_daily_return_ew,

        -- Price-weighted proxy (average close, not true market-cap weight)
        avg(close)                              as avg_close,

        -- Volume
        sum(volume)                             as total_volume,
        avg(volume)                             as avg_volume_per_ticker,

        -- Breadth: % of tickers up on the day
        sum(case when daily_return > 0 then 1 else 0 end)::double
            / nullif(count(daily_return), 0)    as pct_tickers_advancing,

        -- Cumulative return (equal weight)
        avg(cumulative_return)                  as sector_cumulative_return_ew

    from returns
    group by sector, date
)

select * from aggregated
