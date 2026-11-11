select distinct tenant_id,event_date from {{ ref('stg_events') }}
