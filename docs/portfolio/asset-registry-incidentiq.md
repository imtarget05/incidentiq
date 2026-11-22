# Portfolio Asset Registry — IncidentIQ (Cloudflare Workers AI Knowledge Platform)

| Asset | Loại | Đường dẫn | Mô tả | Evidence |
|-------|------|-----------|-------|----------|
| Cloudflare Workers (Python) | Serverless | `api/src/main.py`, `wrangler.toml` | Python Workers, D1 binding, Vectorize binding, Queues producer, AI binding | `wrangler deploy --dry-run` |
| D1 Database | Serverless DB | `infrastructure/terraform/main.tf` | Cloudflare D1 (SQLite-compatible) for metadata | `terraform validate` |
| Vectorize | Vector DB | `infrastructure/terraform/main.tf`, `wrangler.toml` | Vector index `ai-knowledge-vectors` | — |
| Cloudflare Queues | Event streaming | `infrastructure/terraform/main.tf` | etl-queue, etl-dlq | — |
| KV Namespace | KV store | `infrastructure/terraform/main.tf` | rate-limit, feature flags | — |
| Terraform Cloudflare | IaC | `infrastructure/terraform/` | D1, Queues, KV, environments preview/production/staging | `terraform validate` success |
| CI/CD | CI/CD | `.github/workflows/ci.yml` | Trivy, pip-audit, npm audit, gitleaks, Syft, Cosign, SonarQube | — |
| Observability | Observability | `infra/observability/` | CF Workers Prometheus scrape, alert rules (error rate, CPU, D1, DLQ) | — |
| k6 Load Test | Load test | `loadtest/k6-workers.js` | Ingest/search spike, error rate + p95 thresholds | — |
| SLI/SLO Runbooks | Runbook | `docs/runbooks/*.md` | error rate, CPU limit, D1 unavailable, DLQ depth | — |

## Chưa có / cần bổ sung (gap)
- Helm chart / ArgoCD: KHÔNG áp dụng (Cloudflare Workers serverless, không K8s) — xem `docs/helm-argocd-n-a.md`
- Multi-cloud deploy evidence (chỉ Cloudflare Terraform có)
- DR drill thực tế đã chạy + video/screenshot (chỉ có runbook)
