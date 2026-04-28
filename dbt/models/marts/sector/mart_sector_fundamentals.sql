-- Sector fundamentals mart
-- Grain: sector (latest snapshot, one row per sector)
-- Aggregates risk and return metrics across constituents.
-- Example queries:
--   "Which sector has the highest average Sharpe ratio?"
--   "Compare volatility profiles across sectors."

with screener as (
    select * from {{ ref('mart_equity_screener') }}
    where sector != 'Unknown'
)

select
    sector,
    count(distinct ticker)                      as ticker_count,

    -- Market cap
    sum(market_cap)                             as total_market_cap,
    avg(market_cap)                             as avg_market_cap,

    -- Returns
    avg(ytd_return)                             as avg_ytd_return_ew,
    avg(mtd_return)                             as avg_mtd_return_ew,
    median(ytd_return)                          as median_ytd_return,

    -- Risk
    avg(volatility_20d)                         as avg_volatility_20d,
    avg(sharpe_20d)                             as avg_sharpe_20d,
    avg(drawdown_from_52w_high)                 as avg_drawdown_from_52w_high,

    -- Breadth
    sum(case when ytd_return > 0 then 1 else 0 end)::double
        / nullif(count(ytd_return), 0)          as pct_constituents_positive_ytd

from screener
group by sector
