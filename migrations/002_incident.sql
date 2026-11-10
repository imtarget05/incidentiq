-- AI Knowledge Platform / IncidentIQ — Migration 002
-- Incident management, workspaces, RBAC, rate-limit buckets, FTS5 keyword baseline.
-- Applied with: wrangler d1 migrations apply ai-knowledge-platform [--local | --remote]

PRAGMA foreign_keys = ON;

-- Workspaces (tenants). One workspace per tenant for MVP; enables tenant isolation.
CREATE TABLE IF NOT EXISTS workspaces (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    is_active    INTEGER NOT NULL DEFAULT 1
);

-- Link tenants to workspaces (many tenants can share a workspace; MVP: 1:1).
CREATE TABLE IF NOT EXISTS workspace_members (
    id          TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'reader',  -- reader | investigator | admin
    created_at  INTEGER NOT NULL,
    UNIQUE (workspace_id, tenant_id)
);

-- Incident lifecycle records.
CREATE TABLE IF NOT EXISTS incidents (
    id             TEXT PRIMARY KEY,
    workspace_id   TEXT NOT NULL REFERENCES workspaces(id),
    tenant_id      TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    severity       TEXT NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    service        TEXT NOT NULL,
    environment    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','INVESTIGATING','RESOLVED')),
    version        INTEGER NOT NULL DEFAULT 1,
    payload_hash   TEXT,
    idempotency_key TEXT,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    resolved_at    INTEGER
);

-- Immutable append-only event log for an incident (timeline + audit).
CREATE TABLE IF NOT EXISTS incident_events (
    id             TEXT PRIMARY KEY,
    incident_id    TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    tenant_id      TEXT NOT NULL,
    event_type     TEXT NOT NULL,           -- created | status_changed | event_added | triage_requested
    severity       TEXT,
    service        TEXT,
    environment    TEXT,
    timestamp      INTEGER NOT NULL,        -- when the observed symptom occurred
    logs           TEXT,                    -- sanitized log excerpt
    deploy_context TEXT,                    -- deploy version / commit / image
    created_at     INTEGER NOT NULL
);

-- Grounded triage reports produced by the AI triage path (read-only recommendations).
CREATE TABLE IF NOT EXISTS triage_reports (
    id               TEXT PRIMARY KEY,
    incident_id      TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    tenant_id        TEXT NOT NULL,
    status           TEXT NOT NULL,         -- ok | insufficient_evidence
    summary          TEXT,
    hypotheses       TEXT,                  -- JSON array of {text, confirmed}
    evidence         TEXT,                  -- JSON array of {doc_id, version, section, quote}
    similar_incidents TEXT,                 -- JSON array of incident ids
    read_only_checks TEXT,                  -- JSON array of read-only commands
    citations        TEXT,                  -- JSON array of citation ids
    created_at       INTEGER NOT NULL
);

-- Per-tenant rate-limit / AI quota buckets.
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    bucket_key  TEXT NOT NULL,              -- e.g. "question:daily" or "ai:daily"
    count       INTEGER NOT NULL DEFAULT 0,
    window_start INTEGER NOT NULL,
    UNIQUE (tenant_id, bucket_key)
);

-- FTS5 keyword baseline over document content (hybrid retrieval with Vectorize).
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    content,
    content=documents,
    content_rowid=rowid,
    tokenize='unicode61'
);

-- Keep FTS5 external-content index in sync with documents table.
CREATE TRIGGER IF NOT EXISTS documents_fts_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS documents_fts_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS documents_fts_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    INSERT INTO documents_fts(rowid, content) VALUES (new.rowid, new.content);
END;

-- Indexes.
CREATE INDEX IF NOT EXISTS idx_incidents_tenant ON incidents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_incidents_workspace ON incidents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_service ON incidents(service);
CREATE INDEX IF NOT EXISTS idx_incident_events_incident ON incident_events(incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_workspace_members_tenant ON workspace_members(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rate_limit_buckets_tenant ON rate_limit_buckets(tenant_id, bucket_key);

-- Versioning support for documents and chunks (001 created them without version).
ALTER TABLE documents ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE chunks ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_documents_version ON documents(version);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(version);
