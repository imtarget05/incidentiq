select distinct tenant_id from {{ ref('stg_events') }}
