-- Date spine generated from the range of available price data
with date_range as (
    select
        min(date) as start_date,
        max(date) as end_date
    from {{ ref('stg_prices') }}
),

spine as (
    select
        unnest(
            generate_series(
                (select start_date from date_range),
                (select end_date from date_range),
                interval '1 day'
            )
        )::date                                             as date
),

enriched as (
    select
        date,
        extract(year from date)::int                       as year,
        extract(quarter from date)::int                    as quarter,
        extract(month from date)::int                      as month,
        extract(week from date)::int                       as week_of_year,
        extract(day from date)::int                        as day_of_month,
        extract(dow from date)::int                        as day_of_week,
        strftime(date, '%A')                               as day_of_week_name,
        strftime(date, '%B')                               as month_name,

        -- Trading day flag (Mon–Fri; does not account for market holidays)
        case
            when extract(dow from date) between 1 and 5 then true
            else false
        end                                                as is_weekday,

        -- Useful period flags
        date_trunc('month', date)::date                    as month_start,
        date_trunc('quarter', date)::date                  as quarter_start,
        date_trunc('year', date)::date                     as year_start

    from spine
)

select * from enriched
