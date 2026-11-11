-- Refuse ambiguous historical keys BEFORE changing schema; never delete source data.
-- Preflight both queries below and resolve duplicate records/keys with their owners:
-- SELECT tenant_id,idempotency_key,count(*) FROM documents WHERE idempotency_key IS NOT NULL GROUP BY tenant_id,idempotency_key HAVING count(*)>1;
-- SELECT tenant_id,idempotency_key,count(*) FROM incidents WHERE idempotency_key IS NOT NULL GROUP BY tenant_id,idempotency_key HAVING count(*)>1;
CREATE UNIQUE INDEX idx_documents_tenant_idempotency_unique
    ON documents(tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX idx_incidents_tenant_idempotency_unique
    ON incidents(tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
ALTER TABLE documents ADD COLUMN upload_payload_hash TEXT;
