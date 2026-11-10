-- AI Knowledge Platform — D1 schema (Migration 001)
-- Applied with: wrangler d1 migrations apply ai-knowledge-platform [--local | --remote]

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenants (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS api_keys (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_prefix  TEXT NOT NULL,          -- first 8 chars of the key
    key_hash    TEXT NOT NULL,          -- sha256 of the full key
    created_at  INTEGER NOT NULL,
    last_used_at INTEGER,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS documents (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    filename         TEXT NOT NULL,
    content          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'uploaded', -- uploaded | processed | failed
    idempotency_key  TEXT,
    uploaded_at      INTEGER NOT NULL,
    processed_at     INTEGER,
    error            TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id   TEXT NOT NULL,
    content     TEXT NOT NULL,
    vector_id   TEXT NOT NULL,          -- id in Vectorize index
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id        TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    resource  TEXT NOT NULL,
    metadata  TEXT NOT NULL,            -- JSON
    created_at INTEGER NOT NULL
);

-- Indexes for query performance and tenant isolation.
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_idempotency ON documents(idempotency_key, tenant_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_created ON audit_logs(tenant_id, created_at);
