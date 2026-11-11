-- security-platform/seed/seed.sql
-- Seed data for Cybersecurity Dashboard (development / local testing)
-- Run against a fresh PostgreSQL database with migrations applied.

INSERT INTO tenants (name, api_key_prefix, api_key_hash, is_active) VALUES
('Acme Corp', 'acme_live',  '$2y$dummy$placeholder_for_development_only', TRUE),
('Globex Corp', 'globex_live', '$2y$dummy$placeholder_for_development_only', TRUE),
('Soylent Corp', 'soylent_live', '$2y$dummy$placeholder_for_development_only', TRUE)
ON CONFLICT (api_key_prefix) DO NOTHING;

-- Acme assets
INSERT INTO assets (tenant_id, name, type, ip_address, environment, is_active)
SELECT id, 'web-prod-01', 'server', '10.0.1.10', 'production', TRUE FROM tenants WHERE name = 'Acme Corp'
UNION ALL
SELECT id, 'api-prod-02', 'server', '10.0.1.11', 'production', TRUE FROM tenants WHERE name = 'Acme Corp'
UNION ALL
SELECT id, 'dashboard-prod', 'webapp', '10.0.1.20', 'production', TRUE FROM tenants WHERE name = 'Acme Corp'
ON CONFLICT DO NOTHING;

-- Globex assets
INSERT INTO assets (tenant_id, name, type, ip_address, environment, is_active)
SELECT id, 'web-staging-01', 'server', '10.0.2.10', 'staging', TRUE FROM tenants WHERE name = 'Globex Corp'
UNION ALL
SELECT id, 'db-staging-01', 'database', '10.0.2.11', 'staging', TRUE FROM tenants WHERE name = 'Globex Corp'
ON CONFLICT DO NOTHING;

-- Soylent assets
INSERT INTO assets (tenant_id, name, type, ip_address, environment, is_active)
SELECT id, 'web-prod-01', 'server', '10.0.3.10', 'production', TRUE FROM tenants WHERE name = 'Soylent Corp'
ON CONFLICT DO NOTHING;

-- Acme vulnerabilities
INSERT INTO vulnerabilities (tenant_id, asset_id, cve_id, severity, status, description, detected_at)
SELECT t.id, a.id, 'CVE-2024-1234', 'CRITICAL', 'open', 'Remote code execution in web framework', NOW() - interval '2 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Acme Corp' AND a.name = 'web-prod-01'
UNION ALL
SELECT t.id, a.id, 'CVE-2024-5678', 'HIGH', 'in_progress', 'SQL injection in login endpoint', NOW() - interval '5 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Acme Corp' AND a.name = 'api-prod-02'
UNION ALL
SELECT t.id, a.id, 'CVE-2024-9999', 'MEDIUM', 'open', 'Outdated TLS version', NOW() - interval '10 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Acme Corp' AND a.name = 'dashboard-prod'
UNION ALL
SELECT t.id, a.id, 'CVE-2024-1111', 'LOW', 'remediated', 'Missing security header', NOW() - interval '20 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Acme Corp' AND a.name = 'web-prod-01'
ON CONFLICT DO NOTHING;

-- Globex vulnerabilities
INSERT INTO vulnerabilities (tenant_id, asset_id, cve_id, severity, status, description, detected_at)
SELECT t.id, a.id, 'CVE-2024-2222', 'CRITICAL', 'open', 'Privilege escalation in kernel module', NOW() - interval '1 day'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Globex Corp' AND a.name = 'web-staging-01'
UNION ALL
SELECT t.id, a.id, 'CVE-2024-3333', 'MEDIUM', 'open', 'Weak cipher suite', NOW() - interval '3 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Globex Corp' AND a.name = 'db-staging-01'
ON CONFLICT DO NOTHING;

-- Soylent vulnerabilities
INSERT INTO vulnerabilities (tenant_id, asset_id, cve_id, severity, status, description, detected_at)
SELECT t.id, a.id, 'CVE-2024-4444', 'HIGH', 'open', 'Authentication bypass', NOW() - interval '7 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Soylent Corp' AND a.name = 'web-prod-01'
ON CONFLICT DO NOTHING;

-- Acme alerts
INSERT INTO alerts (tenant_id, asset_id, vulnerability_id, severity, status, title, description, created_at)
SELECT t.id, a.id, v.id, 'CRITICAL', 'new', 'RCE detected on web-prod-01', 'Critical vulnerability CVE-2024-1234 exploited', NOW() - interval '2 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
JOIN vulnerabilities v ON v.tenant_id = t.id AND v.cve_id = 'CVE-2024-1234'
WHERE t.name = 'Acme Corp' AND a.name = 'web-prod-01'
UNION ALL
SELECT t.id, a.id, v.id, 'HIGH', 'acknowledged', 'SQL injection on api-prod-02', 'High severity SQL injection', NOW() - interval '5 days'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
JOIN vulnerabilities v ON v.tenant_id = t.id AND v.cve_id = 'CVE-2024-5678'
WHERE t.name = 'Acme Corp' AND a.name = 'api-prod-02'
UNION ALL
SELECT t.id, a.id, v.id, 'CRITICAL', 'new', 'Privilege escalation on web-staging-01', 'Critical kernel exploit', NOW() - interval '1 day'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
JOIN vulnerabilities v ON v.tenant_id = t.id AND v.cve_id = 'CVE-2024-2222'
WHERE t.name = 'Globex Corp' AND a.name = 'web-staging-01'
ON CONFLICT DO NOTHING;

-- Acme incidents
INSERT INTO incidents (tenant_id, title, severity, status, service, environment, created_at)
SELECT t.id, 'Production outage - web-prod-01', 'CRITICAL', 'resolved', 'web-api', 'production', NOW() - interval '3 days'
FROM tenants t WHERE t.name = 'Acme Corp'
UNION ALL
SELECT t.id, 'API latency spike', 'HIGH', 'investigating', 'api-gateway', 'production', NOW() - interval '1 day'
FROM tenants t WHERE t.name = 'Acme Corp'
UNION ALL
SELECT t.id, 'Staging database slow queries', 'MEDIUM', 'open', 'postgres', 'staging', NOW() - interval '6 hours'
FROM tenants t WHERE t.name = 'Globex Corp'
ON CONFLICT DO NOTHING;

-- Scan results
INSERT INTO scan_results (tenant_id, asset_id, scan_type, status, findings_count, started_at, completed_at)
SELECT t.id, a.id, 'full', 'completed', 3, NOW() - interval '2 days', NOW() - interval '2 days' + interval '10 minutes'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Acme Corp' AND a.name = 'web-prod-01'
UNION ALL
SELECT t.id, a.id, 'full', 'completed', 1, NOW() - interval '5 days', NOW() - interval '5 days' + interval '8 minutes'
FROM tenants t JOIN assets a ON a.tenant_id = t.id
WHERE t.name = 'Acme Corp' AND a.name = 'api-prod-02'
ON CONFLICT DO NOTHING;

-- Audit logs
INSERT INTO audit_logs (tenant_id, actor, action, resource, metadata, created_at)
SELECT t.id, 'admin@acme.com', 'vulnerability.remediated', 'vulnerability', '{"cve_id": "CVE-2024-1111"}', NOW() - interval '20 days'
FROM tenants t WHERE t.name = 'Acme Corp'
UNION ALL
SELECT t.id, 'analyst@globex.com', 'alert.acknowledged', 'alert', '{"alert_id": "web-staging-01-rce"}', NOW() - interval '1 day'
FROM tenants t WHERE t.name = 'Globex Corp'
ON CONFLICT DO NOTHING;
