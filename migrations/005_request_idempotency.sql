-- Durable, leased single-flight ledger for operations without a unique source row.
-- A crashed owner becomes reclaimable after lease_until; owner_token fences completion.
CREATE TABLE request_idempotency (
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('processing','completed','failed')),
    owner_token TEXT NOT NULL,
    lease_until INTEGER NOT NULL,
    response_json TEXT,
    response_status INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, operation, idempotency_key)
);
CREATE INDEX idx_request_idempotency_lease ON request_idempotency(state, lease_until);
