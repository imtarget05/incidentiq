select source,event_id from {{ source('raw','events') }}
except select source,event_id from {{ ref('stg_events') }}
