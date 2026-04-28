-- Sector rotation mart
-- Grain: sector + date
-- Equal-weight aggregation of constituent performance.
-- Example queries:
--   "Which sectors have led YTD and which have lagged?"
--   "Show sector breadth — what % of tech stocks are up this month?"

with sector_agg as (
    select * from {{ ref('int_sector_aggregates') }}
),

dates as (
    select date, year, quarter, month from {{ ref('dim_date') }}
),

-- YTD cumulative return anchor per sector
ytd_anchors as (
    select
        sector,
        date,
        first_value(sector_cumulative_return_ew) over (
            partition by sector, extract(year from date)
            order by date
            rows between unbounded preceding and current row
        )                           as ytd_anchor_return

    from sector_agg
),

final as (
    select
        s.sector,
        s.date,
        d.year,
        d.quarter,
        d.month,
        s.ticker_count,

        -- Returns
        s.sector_daily_return_ew,
        s.sector_cumulative_return_ew,

        -- YTD return relative to sector's own year-start
        s.sector_cumulative_return_ew - coalesce(y.ytd_anchor_return, 0)
                                    as sector_ytd_return,

        -- Volume / breadth
        s.total_volume,
        s.avg_volume_per_ticker,
        s.pct_tickers_advancing,

        -- Rank sectors by YTD return (calculated in window for LLM convenience)
        rank() over (
            partition by s.date
            order by s.sector_cumulative_return_ew desc
        )                           as sector_rank_by_cumulative_return

    from sector_agg s
    left join dates d using (date)
    left join ytd_anchors y using (sector, date)
)

select * from final
