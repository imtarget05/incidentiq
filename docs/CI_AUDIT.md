# CI Audit — IncidentIQ

Generated: 2026-11-12
Source: `.github/workflows/*.yml`

## Workflows

### `.github/workflows/ci.yml` — CI
**Triggers:** `push` to `main`, `pull_request` to `main`  
**Runs on PR:** Yes.

| Job | Purpose | Gating |
|-----|---------|--------|
| quality | Ruff Python lint (`E4,E7,E9,F`), MCP `npm run typecheck` + `npm run test:coverage`, Python `pytest --cov=api/src`, `scripts/eval_harness.py`, `scripts/demo.py`, Wrangler dry-run for api/etl/mcp, **SonarQube required** (`SONAR_HOST_URL` var + `SONAR_TOKEN` secret, qualitygate.wait) | Blocking (SonarQube config required or job fails) |
| security | Trivy fs scan `vuln,secret,misconfig`, severity HIGH/CRITICAL, `--exit-code 1`, `--ignore-unfixed` | Blocking |
| dependency-audit | `pip-audit==2.10.1` on `api/requirements.txt`, `npm audit --audit-level=high` on MCP | Blocking |

### `.github/workflows/deploy-preview.yml` — Deploy IncidentIQ preview
**Triggers:** `workflow_dispatch`  
**Environment:** `preview`  
**Token:** `CLOUDFLARE_PREVIEW_API_TOKEN || CLOUDFLARE_API_TOKEN`  
**Validation:** isolated preview resources required — separate `PREVIEW_D1_DATABASE_ID`, `PREVIEW_VECTORIZE_INDEX`, `PREVIEW_ETL_QUEUE`/`PREVIEW_ETL_DLQ` (must not collide with production), URLs must contain "preview". Renders `wrangler.preview.toml`, `wrangler.etl.preview.toml`, `mcp/wrangler.preview.toml`.  
**Steps:** dry-run pywrangler/wrangler → `wrangler d1 migrations apply incidentiq-preview --remote` → deploy preview Workers → `scripts/smoke_test.sh` → MCP `tools/list` verification (`search_runbooks`, `get_incident`, `get_triage_report`) → collect `deploy-evidence/` artifact.

### `.github/workflows/deploy-prod.yml` — Deploy IncidentIQ production
**Triggers:** `push` to `main`, `workflow_dispatch`  
**Environment:** `production` (requires branch-protection approval)  
**Token:** `CLOUDFLARE_PROD_API_TOKEN || CLOUDFLARE_API_TOKEN`  
**Validation:** required secrets `CLOUDFLARE_API_TOKEN`, `PROD_SMOKE_API_KEY`; required vars `CLOUDFLARE_ACCOUNT_ID`, `PROD_API_WORKER_URL`, `PROD_MCP_WORKER_URL`; URLs must be HTTPS origins and must NOT contain "preview".  
**Steps:** dry-run → `wrangler d1 migrations apply ai-knowledge-platform --remote` → deploy production Workers → smoke test → MCP `tools/list` → health `/health/live` == ok, `/health/ready` in (ok, degraded) → collect `deploy-evidence/` artifact.

## Findings
- Preview and production use isolated Cloudflare resources (separate D1 DB, Vectorize index, ETL queues/DLQ) — good practice.
- Production deploy is gated behind GitHub environment approval (`environment: production`) — aligns with P0.4 branch protection.
- CI requires SonarQube (`SONAR_TOKEN` must be configured) — confirm secret is set in repo settings.
- Trivy secret scanner covers `vuln,secret,misconfig` at HIGH/CRITICAL with exit-code 1.

## To do (P0)
- [ ] Configure `SONAR_TOKEN` (and `SONAR_HOST_URL` if using self-hosted) in repo Secrets/Variables.
- [ ] Configure preview vars: `PREVIEW_D1_DATABASE_ID`, `PREVIEW_VECTORIZE_INDEX`, `PREVIEW_ETL_QUEUE`, `PREVIEW_ETL_DLQ`, `PREVIEW_API_WORKER_URL`, `PREVIEW_MCP_WORKER_URL`, secrets `CLOUDFLARE_PREVIEW_API_TOKEN`, `PREVIEW_SMOKE_API_KEY`.
- [ ] Configure production vars: `PROD_API_WORKER_URL`, `PROD_MCP_WORKER_URL`, secrets `CLOUDFLARE_PROD_API_TOKEN`, `PROD_SMOKE_API_KEY`.
- [ ] Enable GitHub branch protection on `main`: require PR, require review, require CI status checks, require production environment approval.
