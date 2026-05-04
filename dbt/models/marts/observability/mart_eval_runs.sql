-- Eval run analytics mart.
-- Grain: one row per fixture per eval run.
--
-- Joins Go scorer pass/fail (from stg_eval_fixture_results) with observability
-- request and span data so you can answer: "which fixtures regressed, and why?"
--
-- Key queries:
--   -- Latest run summary
--   SELECT fixture_id, passed, failures, sql_attempts, chart_source
--   FROM main_observability.mart_eval_runs
--   WHERE run_at = (SELECT MAX(run_at) FROM main_observability.mart_eval_runs)
--   ORDER BY passed ASC, fixture_id;
--
--   -- Fixtures that regressed (passed before, failing now)
--   SELECT fixture_id, passed, failures
--   FROM main_observability.mart_eval_runs
--   WHERE run_at = (SELECT MAX(run_at) FROM main_observability.mart_eval_runs)
--     AND NOT passed
--   ORDER BY fixture_id;
--
--   -- Fixtures with high SQL retry rate across all runs
--   SELECT fixture_id, ROUND(AVG(sql_attempts), 2) AS avg_attempts, COUNT(*) AS runs
--   FROM main_observability.mart_eval_runs
--   GROUP BY fixture_id HAVING avg_attempts > 1.1
--   ORDER BY avg_attempts DESC;

with fixture_results as (
    select * from {{ ref('stg_eval_fixture_results') }}
),

-- Parse fixture_id from request_ids like 'eval_screener_top10_ytd_8ecaf02f'
eval_requests as (
    select
        request_id,
        regexp_extract(request_id, '^eval_([a-z][a-z0-9_]*)_[0-9a-f]{8}$', 1) as fixture_id,
        question,
        domain,
        started_at,
        latency_ms,
        block_count,
        fallback_used,
        error
    from {{ ref('stg_obs_requests') }}
    where request_id like 'eval_%'
      and request_id similar to 'eval_[a-z][a-z0-9_]*_[0-9a-f]{8}'
),

sql_spans as (
    select
        request_id,
        max(attempt)                                          as sql_attempts,
        count_if(not success)                                 as sql_gen_failures
    from {{ ref('stg_obs_spans') }}
    where stage = 'sql_gen'
      and request_id like 'eval_%'
    group by request_id
),

narrative_spans as (
    select request_id, chart_source
    from {{ ref('stg_obs_spans') }}
    where stage = 'narrative'
      and request_id like 'eval_%'
    qualify row_number() over (partition by request_id order by started_at desc) = 1
)

select
    fr.fixture_id,
    fr.run_at,
    fr.passed,
    fr.failures,
    fr.elapsed_ms                               as scorer_elapsed_ms,
    r.question,
    r.domain,
    r.started_at,
    r.latency_ms                                as agent_latency_ms,
    r.block_count,
    r.fallback_used,
    coalesce(s.sql_attempts, 1)                 as sql_attempts,
    coalesce(s.sql_gen_failures, 0)             as sql_gen_failures,
    coalesce(n.chart_source, 'none')            as chart_source,
    r.error

from fixture_results fr
-- Match each fixture result to its observability request by fixture_id and time proximity.
-- Eval runs take up to 60 min total; a 90-min window safely handles stragglers.
left join eval_requests r
    on r.fixture_id = fr.fixture_id
    and r.started_at >= fr.run_at - interval '5 minutes'
    and r.started_at <= fr.run_at + interval '90 minutes'
left join sql_spans s using (request_id)
left join narrative_spans n using (request_id)

order by fr.run_at desc, fr.fixture_id
