-- AI Knowledge Platform / IncidentIQ — Migration 003
-- Data mart for analytics: aggregated triage + RAG evaluation metrics per tenant.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS triage_metrics (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    incident_id   TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    status        TEXT NOT NULL,          -- ok | insufficient_evidence
    citations     INTEGER NOT NULL DEFAULT 0,
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_triage_metrics_tenant ON triage_metrics(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_triage_metrics_incident ON triage_metrics(incident_id);

CREATE TABLE IF NOT EXISTS rag_eval_runs (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT,
    dataset       TEXT NOT NULL,
    metric        TEXT NOT NULL,          -- recall@k | mrr | faithfulness
    value         REAL NOT NULL,
    sample_size   INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_eval_tenant ON rag_eval_runs(tenant_id, created_at);
