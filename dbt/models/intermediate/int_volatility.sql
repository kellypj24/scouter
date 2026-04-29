with returns as (
    select
        ticker,
        date,
        sector,
        daily_return,
        close

    from {{ ref('int_daily_returns') }}
    where daily_return is not null
),

volatility as (
    select
        ticker,
        date,
        sector,
        close,
        daily_return,

        -- 20-day rolling volatility (annualised)
        stddev(daily_return) over (
            partition by ticker
            order by date
            rows between 19 preceding and current row
        ) * sqrt(252)                           as volatility_20d,

        -- 60-day rolling volatility (annualised)
        stddev(daily_return) over (
            partition by ticker
            order by date
            rows between 59 preceding and current row
        ) * sqrt(252)                           as volatility_60d,

        -- Max drawdown from rolling 252-day peak
        (close / nullif(max(close) over (
            partition by ticker
            order by date
            rows between 251 preceding and current row
        ), 0)) - 1                              as drawdown_from_52w_high,

        -- Average daily return (20d, annualised)
        avg(daily_return) over (
            partition by ticker
            order by date
            rows between 19 preceding and current row
        ) * 252                                 as annualised_return_20d

    from returns
),

with_sharpe as (
    select
        *,
        -- Sharpe ratio (risk-free rate = 0 for simplicity; update when macro data added)
        case
            when volatility_20d > 0
            then annualised_return_20d / volatility_20d
            else null
        end                                     as sharpe_20d

    from volatility
)

select * from with_sharpe
