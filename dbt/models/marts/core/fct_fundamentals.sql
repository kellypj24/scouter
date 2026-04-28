with snapshots as (
    select * from {{ ref('stg_market_snapshots') }}
),

companies as (
    select ticker, company_name, sector, industry, market_cap_tier
    from {{ ref('dim_company') }}
),

joined as (
    select
        s.ticker,
        s.snapshot_at,

        -- Company context
        c.company_name,
        c.sector,
        c.industry,
        c.market_cap_tier,

        -- Price snapshot
        s.current_price,
        s.day_high,
        s.day_low,
        s.volume,
        s.market_cap,

        -- Range
        s.fifty_two_week_high,
        s.fifty_two_week_low,

        -- Derived: price position within 52w range (0 = at low, 1 = at high)
        case
            when s.fifty_two_week_high > s.fifty_two_week_low
            then (s.current_price - s.fifty_two_week_low)
                / (s.fifty_two_week_high - s.fifty_two_week_low)
            else null
        end                         as price_position_52w

    from snapshots s
    left join companies c using (ticker)
)

select * from joined
