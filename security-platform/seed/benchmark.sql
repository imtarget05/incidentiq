-- security-platform/seed/benchmark.sql
-- Benchmark data for Cybersecurity Dashboard performance testing.
-- Generates a larger dataset to validate query performance under load.

-- Generate 100 tenants
DO $$
DECLARE
    i int;
    tenant_id uuid;
BEGIN
    FOR i IN 1..100 LOOP
        INSERT INTO tenants (name, api_key_prefix, api_key_hash, is_active)
        VALUES ('tenant_' || i, 'tk_' || i, encode(digest('tenant_' || i, 'sha256'), 'hex'), TRUE)
        RETURNING id INTO tenant_id;

        -- 10 assets per tenant
        FOR j IN 1..10 LOOP
            INSERT INTO assets (tenant_id, name, type, ip_address, environment, is_active)
            VALUES (tenant_id, 'asset_' || i || '_' || j, 'server', '10.' || i || '.' || j || '.10', 'production', TRUE);
        END LOOP;

        -- 5 vulnerabilities per tenant
        FOR k IN 1..5 LOOP
            INSERT INTO vulnerabilities (tenant_id, severity, status, description, detected_at)
            VALUES (tenant_id,
                    CASE (k % 4) WHEN 0 THEN 'LOW' WHEN 1 THEN 'MEDIUM' WHEN 2 THEN 'HIGH' ELSE 'CRITICAL' END,
                    CASE (k % 3) WHEN 0 THEN 'open' WHEN 1 THEN 'in_progress' ELSE 'remediated' END,
                    'benchmark vulnerability ' || k,
                    NOW() - make_interval(days => k));
        END LOOP;

        -- 5 alerts per tenant
        FOR l IN 1..5 LOOP
            INSERT INTO alerts (tenant_id, severity, status, title, description, created_at)
            VALUES (tenant_id,
                    CASE (l % 4) WHEN 0 THEN 'LOW' WHEN 1 THEN 'MEDIUM' WHEN 2 THEN 'HIGH' ELSE 'CRITICAL' END,
                    CASE (l % 4) WHEN 0 THEN 'new' WHEN 1 THEN 'acknowledged' WHEN 2 THEN 'resolved' ELSE 'dismissed' END,
                    'benchmark alert ' || l,
                    'benchmark alert description ' || l,
                    NOW() - make_interval(hours => l));
        END LOOP;

        -- 2 incidents per tenant
        FOR m IN 1..2 LOOP
            INSERT INTO incidents (tenant_id, severity, status, service, environment, created_at)
            VALUES (tenant_id,
                    CASE (m % 4) WHEN 0 THEN 'LOW' WHEN 1 THEN 'MEDIUM' WHEN 2 THEN 'HIGH' ELSE 'CRITICAL' END,
                    CASE (m % 3) WHEN 0 THEN 'open' WHEN 1 THEN 'investigating' ELSE 'resolved' END,
                    'benchmark-service-' || m,
                    'production',
                    NOW() - make_interval(days => m));
        END LOOP;
    END LOOP;
END $$;
