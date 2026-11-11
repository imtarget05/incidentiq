select distinct tenant_id,service from {{ ref('stg_events') }} where service is not null
