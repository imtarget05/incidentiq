# Deploy evidence sample — IncidentIQ (Cloudflare edge → Azure backend, Option B)

File này là mẫu định dạng evidence được thu thập sau mỗi deploy (CI `deploy-prod.yml` / `deploy-preview.yml`, artifact `incidentiq-deploy-evidence`).

## deploy-evidence/deploy.txt
```
deploy_time=2026-11-11T14:30:00Z
environment=production
api_worker_url=https://ai-knowledge-platform.<account>.workers.dev
mcp_worker_url=https://ai-knowledge-mcp.<account>.workers.dev
```

## deploy-evidence/health.txt (output `scripts/health-cf.sh` + `scripts/health-azure.sh`)
```
🔎 Checking Cloudflare Worker: https://ai-knowledge-platform.../workers.dev
HTTP 200 /health/live
{"status":"ok","service":"ai-knowledge-platform","ts":...}
HTTP 200 /health/ready
{"status":"ok","checks":{...}}
✅ Cloudflare Worker healthy.

🔎 Checking Azure backend: https://incidentiq-api.<region>.azurecontainerapps.io
HTTP 200 /health/live
{"status":"ok",...}
HTTP 200 /health/ready
{"status":"ok","checks":{...,"azure_backend":"ok"}}
✅ Azure backend healthy.
```

## Gate (định nghĩa done)
- `GET /health/live` → 200 `{status:"ok"}`; `GET /health/ready` → 200 `{status in (ok,degraded)}` (Cloudflare + Azure).
- MCP `tools/list` có `search_runbooks`, `get_incident`, `get_triage_report`.
- Unauthenticated protected endpoint → 401.
- Smoke test (`scripts/smoke-cf.sh` / `scripts/smoke-azure.sh`) pass.
- Trivy không phát hiện CRITICAL/HIGH fixable; Sonar quality gate xanh.
- Không deploy production khi có gate P0 mở.

## Lưu ý
- Secrets (Cloudflare API token, Azure credentials, AZURE_EDGE_SECRET) không được commit.
- `AZURE_BACKEND_URL` và `AZURE_EDGE_SECRET` được cấu hình qua wrangler secret / variable theo môi trường (preview/production tách biệt).
