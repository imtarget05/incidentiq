select 1 as mismatch where
 (select count(*) from {{ ref('stg_events') }}) <>
 (select coalesce(sum(executions),0) from {{ ref('daily_metrics') }})
