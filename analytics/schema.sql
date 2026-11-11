CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.events (
 source text NOT NULL, event_id text NOT NULL, tenant_id text NOT NULL,
 event_type text NOT NULL CHECK(event_type IN ('ingestion','retrieval','llm_request','incident','triage','etl')),
 occurred_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
 entity_id text NOT NULL, status text, model text, service text,
 tokens bigint CHECK(tokens>=0), latency_ms bigint CHECK(latency_ms>=0),
 cost_usd numeric(18,8) CHECK(cost_usd>=0), citations bigint CHECK(citations>=0),
 loaded_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source,event_id)
);
CREATE INDEX IF NOT EXISTS events_updated_at ON raw.events(updated_at);
CREATE TABLE IF NOT EXISTS raw.checkpoints (source text PRIMARY KEY, watermark timestamptz NOT NULL);

CREATE TABLE IF NOT EXISTS raw.tenant_readers (role_name name PRIMARY KEY, tenant_id text NOT NULL);
ALTER TABLE raw.tenant_readers ENABLE ROW LEVEL SECURITY;
