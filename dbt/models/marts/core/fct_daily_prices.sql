with returns as (
    select * from {{ ref('int_daily_returns') }}
),

volatility as (
    select
        ticker,
        date,
        volatility_20d,
        volatility_60d,
        drawdown_from_52w_high,
        sharpe_20d
    from {{ ref('int_volatility') }}
),

companies as (
    select
        ticker,
        company_name,
        sector,
        industry,
        market_cap_tier
    from {{ ref('dim_company') }}
),

dates as (
    select date, year, quarter, month, week_of_year
    from {{ ref('dim_date') }}
),

joined as (
    select
        -- Keys
        r.ticker,
        r.date,

        -- Company attributes (denormalised for query convenience)
        c.company_name,
        c.sector,
        c.industry,
        c.market_cap_tier,

        -- Date attributes
        d.year,
        d.quarter,
        d.month,
        d.week_of_year,

        -- Price
        r.open,
        r.high,
        r.low,
        r.close,
        r.prev_close,
        r.volume,
        r.avg_volume_20d,

        -- Returns
        r.daily_return,
        r.cumulative_return,

        -- Range
        r.rolling_52w_high,
        r.rolling_52w_low,

        -- Risk (from volatility model)
        v.volatility_20d,
        v.volatility_60d,
        v.drawdown_from_52w_high,
        v.sharpe_20d

    from returns r
    left join companies c using (ticker)
    left join dates d using (date)
    left join volatility v using (ticker, date)
)

select * from joined
