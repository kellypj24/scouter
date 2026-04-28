-- Drawdown time series mart
-- Grain: ticker + date
-- Tracks peak-to-trough drawdown over time.
-- Example queries:
--   "What was AAPL's worst drawdown in 2023?"
--   "Which stocks have been in drawdown for the longest streak?"

with prices as (
    select
        ticker,
        date,
        company_name,
        sector,
        market_cap_tier,
        close,
        year,
        quarter,
        month
    from {{ ref('fct_daily_prices') }}
),

with_peaks as (
    select
        *,
        -- Running peak (all-time high up to each date per ticker)
        max(close) over (
            partition by ticker
            order by date
            rows between unbounded preceding and current row
        )                           as running_peak,

        -- Calendar year peak
        max(close) over (
            partition by ticker, year
            order by date
            rows between unbounded preceding and current row
        )                           as year_peak

    from prices
),

with_drawdown as (
    select
        *,
        -- Drawdown from all-time high
        (close / nullif(running_peak, 0)) - 1       as drawdown_from_peak,

        -- Drawdown from calendar year high
        (close / nullif(year_peak, 0)) - 1          as drawdown_from_year_high,

        -- Flag: currently in drawdown
        close < running_peak                         as is_in_drawdown,

        -- Consecutive days in drawdown (streak)
        sum(case when close < running_peak then 1 else 0 end) over (
            partition by ticker
            order by date
            rows between unbounded preceding and current row
        )                                            as cumulative_drawdown_days

    from with_peaks
)

select * from with_drawdown
