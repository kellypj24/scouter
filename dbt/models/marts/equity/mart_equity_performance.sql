-- Equity performance mart
-- Grain: ticker + date
-- Optimised for time-series questions about individual stocks or peer groups.
-- Example queries:
--   "How has AAPL performed YTD vs the S&P 500 average?"
--   "Show me the top 10 performers in tech this quarter."

with prices as (
    select * from {{ ref('fct_daily_prices') }}
),

-- YTD and MTD return anchors per ticker
period_anchors as (
    select
        ticker,
        -- YTD: first close of the calendar year
        first_value(close) over (
            partition by ticker, year
            order by date
            rows between unbounded preceding and current row
        )                           as ytd_anchor_close,

        -- MTD: first close of the calendar month
        first_value(close) over (
            partition by ticker, year, month
            order by date
            rows between unbounded preceding and current row
        )                           as mtd_anchor_close,

        ticker as _ticker_key,
        date   as _date_key

    from prices
),

final as (
    select
        p.ticker,
        p.date,
        p.company_name,
        p.sector,
        p.industry,
        p.market_cap_tier,
        p.year,
        p.quarter,
        p.month,

        -- Price
        p.open,
        p.high,
        p.low,
        p.close,
        p.volume,
        p.avg_volume_20d,

        -- Returns
        p.daily_return,
        p.cumulative_return,

        -- Period returns
        (p.close / nullif(a.ytd_anchor_close, 0)) - 1  as ytd_return,
        (p.close / nullif(a.mtd_anchor_close, 0)) - 1  as mtd_return,

        -- Risk
        p.volatility_20d,
        p.volatility_60d,
        p.drawdown_from_52w_high,
        p.sharpe_20d,
        p.rolling_52w_high,
        p.rolling_52w_low

    from prices p
    left join period_anchors a
        on p.ticker = a._ticker_key
        and p.date = a._date_key
)

select * from final
