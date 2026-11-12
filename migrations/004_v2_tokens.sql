-- AI Knowledge Platform / IncidentIQ — Migration 004
-- API v2 token tracking table and circuit-breaker event log.

PRAGMA foreign_keys = ON;

-- Token usage log per tenant per day for quota enforcement and billing analytics.
CREATE TABLE IF NOT EXISTS token_usage_log (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    endpoint      TEXT NOT NULL,         -- e.g. 'triage' | 'question'
    model         TEXT NOT NULL,         -- e.g. '@cf/openai/gpt-oss-20b'
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_token_usage_tenant ON token_usage_log(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_token_usage_endpoint ON token_usage_log(endpoint, created_at);

-- ETL circuit-breaker events (soft log — Workers AI failures, circuit open/close).
CREATE TABLE IF NOT EXISTS circuit_breaker_events (
    id          TEXT PRIMARY KEY,
    worker      TEXT NOT NULL,           -- 'etl_consumer'
    event_type  TEXT NOT NULL,           -- 'failure' | 'open' | 'half_open' | 'close'
    details     TEXT,                    -- JSON
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cb_events_worker ON circuit_breaker_events(worker, created_at);
