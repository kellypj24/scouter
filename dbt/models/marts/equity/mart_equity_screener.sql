-- Equity screener mart
-- Grain: ticker (latest snapshot)
-- Combines latest price data with fundamentals for screening queries.
-- Example queries:
--   "Show me large-cap tech stocks with Sharpe > 1 and drawdown < 10%."
--   "Which S&P 500 stocks are nearest their 52-week highs?"

with latest_prices as (
    select *
    from {{ ref('mart_equity_performance') }}
    qualify row_number() over (partition by ticker order by date desc) = 1
),

fundamentals as (
    select *
    from {{ ref('fct_fundamentals') }}
    qualify row_number() over (partition by ticker order by snapshot_at desc) = 1
)

select
    lp.ticker,
    lp.company_name,
    lp.sector,
    lp.industry,
    lp.market_cap_tier,

    -- Latest price data
    lp.date                         as price_date,
    lp.close                        as latest_close,
    lp.volume,
    lp.avg_volume_20d,

    -- Returns
    lp.daily_return,
    lp.mtd_return,
    lp.ytd_return,

    -- Risk
    lp.volatility_20d,
    lp.sharpe_20d,
    lp.drawdown_from_52w_high,
    lp.rolling_52w_high,
    lp.rolling_52w_low,

    -- Fundamentals snapshot
    f.market_cap,
    f.fifty_two_week_high,
    f.fifty_two_week_low,
    f.price_position_52w

from latest_prices lp
left join fundamentals f using (ticker)
