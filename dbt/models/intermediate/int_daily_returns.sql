with prices as (
    select * from {{ ref('stg_prices') }}
),

companies as (
    select ticker, sector, industry from {{ ref('stg_companies') }}
),

with_returns as (
    select
        p.ticker,
        p.date,
        p.open,
        p.high,
        p.low,
        p.close,
        p.volume,
        c.sector,
        c.industry,

        -- Prior close for return calculations
        lag(p.close) over (
            partition by p.ticker order by p.date
        )                                                       as prev_close,

        -- Daily return
        (p.close - lag(p.close) over (partition by p.ticker order by p.date))
            / nullif(lag(p.close) over (partition by p.ticker order by p.date), 0)
                                                                as daily_return,

        -- Cumulative return from first available date per ticker
        (p.close / first_value(p.close) over (
            partition by p.ticker order by p.date
            rows between unbounded preceding and current row
        )) - 1                                                  as cumulative_return,

        -- Rolling 20-day average volume
        avg(p.volume) over (
            partition by p.ticker
            order by p.date
            rows between 19 preceding and current row
        )                                                       as avg_volume_20d,

        -- 52-week high/low from price history
        max(p.high) over (
            partition by p.ticker
            order by p.date
            rows between 251 preceding and current row
        )                                                       as rolling_52w_high,

        min(p.low) over (
            partition by p.ticker
            order by p.date
            rows between 251 preceding and current row
        )                                                       as rolling_52w_low

    from prices p
    left join companies c using (ticker)
)

select * from with_returns
