select tenant_id,event_date,event_type,count(*) as executions,
 count(tokens) as measured_token_rows,sum(tokens) as tokens,
 count(cost_usd) as measured_cost_rows,sum(cost_usd) as cost_usd,
 count(latency_ms) as measured_latency_rows,avg(latency_ms) as mean_latency_ms,
 count(*) filter (where status in ('FAILED','failed','error','dlq')) as failures
from {{ ref('stg_events') }} group by tenant_id,event_date,event_type
