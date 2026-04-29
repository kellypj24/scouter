with source as (
    select * from {{ source('raw', 'companies') }}
),

cleaned as (
    select
        upper(symbol)               as ticker,
        long_name                   as company_name,
        coalesce(sector, 'Unknown') as sector,
        coalesce(industry, 'Unknown') as industry,
        exchange,
        cast(market_cap as double)  as market_cap,
        cast(last_updated as timestamp) as ingested_at

    from source
    where symbol is not null
)

select * from cleaned
