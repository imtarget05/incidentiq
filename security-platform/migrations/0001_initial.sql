-- security-platform/migrations/0001_initial.sql
-- Cybersecurity Dashboard schema on PostgreSQL

CREATE TABLE IF NOT EXISTS tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    api_key_prefix  TEXT NOT NULL UNIQUE,
    api_key_hash    TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assets (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,
    ip_address    TEXT,
    environment   TEXT NOT NULL DEFAULT 'production',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vulnerabilities (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    asset_id       UUID REFERENCES assets(id) ON DELETE SET NULL,
    cve_id         TEXT,
    severity       TEXT NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','remediated','false_positive')),
    description    TEXT,
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    remediated_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS alerts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    asset_id       UUID REFERENCES assets(id) ON DELETE SET NULL,
    vulnerability_id UUID REFERENCES vulnerabilities(id) ON DELETE SET NULL,
    severity       TEXT NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    status         TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','acknowledged','resolved','dismissed')),
    title          TEXT NOT NULL,
    description    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS incidents (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    severity       TEXT NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','investigating','resolved')),
    service        TEXT NOT NULL,
    environment    TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS scan_results (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    asset_id       UUID REFERENCES assets(id) ON DELETE SET NULL,
    scan_type      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','failed')),
    findings_count INTEGER NOT NULL DEFAULT 0,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    resource   TEXT NOT NULL,
    metadata   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for optimized lookups (security dashboard queries)
CREATE INDEX IF NOT EXISTS idx_assets_tenant_id ON assets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_assets_active ON assets(tenant_id, is_active);
CREATE INDEX IF NOT EXISTS idx_vuln_tenant_id ON vulnerabilities(tenant_id);
CREATE INDEX IF NOT EXISTS idx_vuln_severity ON vulnerabilities(tenant_id, severity);
CREATE INDEX IF NOT EXISTS idx_vuln_status ON vulnerabilities(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_tenant_id ON alerts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(tenant_id, severity);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_tenant_id ON incidents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(tenant_id, severity);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_results_tenant_id ON scan_results(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id, created_at DESC);

-- Trigger to auto-update assets.updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_assets_updated_at
BEFORE UPDATE ON assets
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_incidents_updated_at
BEFORE UPDATE ON incidents
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
