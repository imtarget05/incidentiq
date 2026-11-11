select event_key from {{ ref('stg_events') }}
where tokens<0 or latency_ms<0 or cost_usd<0 or citations<0
