-- Successful query patterns logged by the local agent, aggregated for promotion review.
--
-- Worker-bee candidates: the local agent writes signal here but never self-promotes.
-- Claude reviews this mart and promotes high-quality patterns to learned_patterns.yaml.
--
-- eval_validated = true when the pattern appears in eval_ prefixed requests
-- that completed without fallback — the eval harness is the quality gate.

with pattern_spans as (
    select *
    from {{ ref('stg_obs_spans') }}
    where stage = 'query_pattern'
      and success
      and row_count > 0
      and mart is not null
      and sql_hash is not null
),

eval_requests as (
    select request_id
    from {{ ref('stg_obs_requests') }}
    where request_id like 'eval_%'
      and not fallback_used
)

select
    ps.domain,
    ps.mart,
    ps.sql_hash,
    count(*)                                                as usage_count,
    round(avg(ps.row_count), 1)                             as avg_row_count,
    min(ps.started_at)                                      as first_seen_at,
    max(ps.started_at)                                      as last_used_at,
    count_if(er.request_id is not null) > 0                 as eval_validated,
    count_if(er.request_id is not null)                     as eval_pass_count

from pattern_spans ps
left join eval_requests er on ps.request_id = er.request_id
group by ps.domain, ps.mart, ps.sql_hash
order by usage_count desc
