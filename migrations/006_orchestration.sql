-- Phase 3 — ETL retry circuit breaker state (per-tenant key, e.g. "etl:t1").
-- Plain CREATE TABLE so it also loads in the sqlite test fake (tests/api/sqlite_d1.py).
CREATE TABLE IF NOT EXISTS etl_circuit_state (
    key                  TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    opened_at            INTEGER,          -- epoch ms when the circuit first opened / probe started
    half_open_after_ms   INTEGER NOT NULL DEFAULT 60000  -- cooldown before a half-open probe
);
