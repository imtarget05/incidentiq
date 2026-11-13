# Deployment Runbook — IncidentIQ (Document-Grounded Incident Triage)

Generated: 2026-11-13
Scope: Preview deploy, production deploy, frontend auth, tenant isolation,
ETL failure drills, monitoring.

Prerequisites:
- `CLOUDFLARE_PREVIEW_API_TOKEN` + `CLOUDFLARE_PROD_API_TOKEN` (GitHub Secrets)
- `CLOUDFLARE_ACCOUNT_ID` (GitHub Variable)
- `SONAR_TOKEN` + `SONAR_HOST_URL` (GitHub Secrets/Variables)
- `PROD_SMOKE_API_KEY` (GitHub Secret)
- GitHub repo admin access (for branch protection + environment reviewer)

---

## Step 0 — CI Prerequisites (before any deploy)

1. Configure `SONAR_TOKEN` (and `SONAR_HOST_URL` if self-hosted) in repo
   Secrets/Variables — CI `quality` job requires it.
2. Configure preview vars in repo Settings → Variables:
   - `PREVIEW_D1_DATABASE_ID`, `PREVIEW_VECTORIZE_INDEX`,
     `PREVIEW_ETL_QUEUE`, `PREVIEW_ETL_DLQ`,
     `PREVIEW_API_WORKER_URL`, `PREVIEW_MCP_WORKER_URL`
3. Configure preview secrets:
   - `CLOUDFLARE_PREVIEW_API_TOKEN`, `PREVIEW_SMOKE_API_KEY`
4. Configure production vars:
   - `PROD_API_WORKER_URL`, `PROD_MCP_WORKER_URL`
5. Configure production secrets:
   - `CLOUDFLARE_PROD_API_TOKEN`, `PROD_SMOKE_API_KEY`
6. Enable GitHub branch protection on `main`:
   - Require PR, require review, require CI status checks
   - Require production environment approval (for `deploy-prod.yml`)

---

## Step 1 — Preview Deploy (P2.1)

Goal: Isolated preview environment with separate D1/Vectorize/Queue.

1. Dispatch `deploy-preview.yml` (workflow_dispatch).
2. Verify all 13 steps pass:
   - Setup, checkout, Node, uv, Wrangler install
   - Validate isolated preview resources
   - Apply migrations to preview D1 only
   - Deploy preview Workers
   - Verify preview API behavior
   - Verify MCP protocol endpoint
   - Collect deploy evidence artifact
3. Verify preview URLs contain "preview" (not production).

Evidence to collect: CI run ID, deploy artifact, preview smoke test results.

---

## Step 2 — Frontend Authentication (G7 / HIGH)

Goal: Frontend login/logout, session binding with tenant.

1. Implement frontend authentication flow (login page, session storage,
   protected routes).
2. Bind frontend session to tenant via API key hash.
3. Verify: user from tenant A cannot access tenant B's documents/incidents.
4. Run `tests/api/test_tenant_isolation.py` — 4 tests must pass.

Evidence to collect: Frontend login screenshot, tenant isolation test output.

---

## Step 3 — Production Deploy (P2.5)

Goal: Production workers deployed via GitHub Actions.

1. `deploy-prod.yml` is gated by `production` environment required-reviewer.
2. Approve deployment through GitHub UI (imtarget05 reviewer).
3. Alternative: manual wrangler CLI deploy if GitHub Actions blocked.
4. Deploy workers: API, ETL, MCP (service binding → API).
5. Verify health endpoints:
   - `GET /health` → 200 `{"status":"ok"}`
   - `GET /health/live` → 200 `{"status":"ok"}`
   - `GET /health/ready` → 200 `{"status":"ok", checks all ok}`

Evidence to collect: Deploy approval log, health check responses.

---

## Step 4 — ETL Failure / DLQ Drill (P2.3)

Goal: Document never marked processed when embedding/Vectorize/D1 fails.

1. Run `tests/api/test_etl_failure.py` — 5 tests must pass.
2. Verify: document stays `uploaded` status when AI/Vectorize/D1 write fails.
3. Verify: falls back to queue/DLQ instead of silently succeeding.
4. Verify: retry after partial write succeeds.

Evidence to collect: Test run output.

---

## Step 5 — Monitoring & Observability (P2.6)

Goal: Cost tracking and health monitoring.

1. Enable observability in all wrangler configs (`[observability] enabled = true`).
2. Track: Workers AI token usage, D1 read/write, Vectorize index size.
3. Configure alert on health check failure.

Evidence to collect: Monitoring dashboard screenshot, cost report.

---

## Step 6 — DR Drills (Task 6)

Goal: Disaster recovery procedures verified.

1. ETL failure / DLQ test (preview):
   - Set `ETL_TEST_FAIL_EMBEDDING=1`, redeploy preview ETL
   - Insert test document, send ETL message, verify DLQ
   - Revert and redeploy to normal state
2. D1 backup + restore:
   - `wrangler d1 export` may fail on FTS5 tables
   - Use manual logical backup (schema + data dump)
3. Rollback procedure:
   - `wrangler deployments list --name <worker>`
   - `wrangler rollback --version <id>`
   - Redeploy for recovery

Evidence to collect: Backup file, rollback log, health check after recovery.

---

## Rollback

- Production worker bad deploy: `wrangler rollback --version <id>`
- D1 migration issue: restore from manual logical backup
- ETL queue stuck: purge `etl-queue`, reprocess from DLQ

---

## Sign-off checklist

- [x] SONAR_TOKEN configured, CI quality job passes (verified 2026-11-13)
- [x] Branch protection enabled on main (verified 2026-11-13)
- [x] Preview deploy passes all 13 steps (run 43372097886, 2026-11-12)
- [ ] Frontend authentication implemented and tested
- [x] Production workers deployed (API, ETL, MCP) (run 43371813019, 2026-11-12)
- [ ] Health checks all pass (D1, Vectorize, Workers AI, ETL queue)
- [ ] Tenant isolation tests pass (4/4)
- [ ] ETL failure tests pass (5/5)
- [ ] Monitoring configured
- [ ] DR drills documented and tested