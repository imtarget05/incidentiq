{{ config(materialized='incremental', unique_key='event_key', incremental_strategy='delete+insert') }}
-- https://docs.getdbt.com/docs/build/incremental-models
select md5(source || chr(31) || event_id) as event_key, *,
       (occurred_at at time zone 'UTC')::date as event_date
from {{ source('raw', 'events') }}
{% if is_incremental() %}
where loaded_at >= (select coalesce(max(loaded_at),'1970-01-01'::timestamptz)-interval '48 hours' from {{ this }})
{% endif %}
