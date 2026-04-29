with companies as (
    select * from {{ ref('stg_companies') }}
),

snapshots as (
    select
        ticker,
        market_cap,
        snapshot_at
    from {{ ref('stg_market_snapshots') }}
),

-- Use snapshot market cap where available (more current than ingested metadata)
enriched as (
    select
        c.ticker,
        c.company_name,
        c.sector,
        c.industry,
        c.exchange,
        coalesce(s.market_cap, c.market_cap)    as market_cap,

        case
            when coalesce(s.market_cap, c.market_cap) >= 200e9 then 'mega_cap'
            when coalesce(s.market_cap, c.market_cap) >= 10e9  then 'large_cap'
            when coalesce(s.market_cap, c.market_cap) >= 2e9   then 'mid_cap'
            when coalesce(s.market_cap, c.market_cap) > 0      then 'small_cap'
            else 'unknown'
        end                                     as market_cap_tier

    from companies c
    left join snapshots s using (ticker)
)

select * from enriched
