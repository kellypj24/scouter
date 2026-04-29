-- Risk profile mart
-- Grain: ticker (latest snapshot)
-- Example queries:
--   "Which S&P 500 stocks have the highest Sharpe ratio?"
--   "Show me low-volatility large-cap stocks."
--   "What is the risk profile of energy sector stocks?"

with screener as (
    select
        ticker,
        company_name,
        sector,
        industry,
        market_cap_tier,
        latest_close,
        ytd_return,
        volatility_20d,
        sharpe_20d,
        drawdown_from_52w_high,
        rolling_52w_high,
        rolling_52w_low,
        price_position_52w,
        market_cap
    from {{ ref('mart_equity_screener') }}
),

risk_ranked as (
    select
        *,
        -- Percentile ranks within sector for relative comparison
        percent_rank() over (
            partition by sector
            order by volatility_20d asc
        )                           as volatility_pctile_in_sector,

        percent_rank() over (
            partition by sector
            order by sharpe_20d desc nulls last
        )                           as sharpe_pctile_in_sector,

        -- Cross-market ranks
        percent_rank() over (order by volatility_20d asc)
                                    as volatility_pctile_market,

        percent_rank() over (order by sharpe_20d desc nulls last)
                                    as sharpe_pctile_market

    from screener
)

select * from risk_ranked
