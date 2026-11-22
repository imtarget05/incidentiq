# Cloudflare Workers (IncidentIQ) — không có K8s nên Helm & ArgoCD KHÔNG áp dụng.

## Lý do
- IncidentIQ chạy trên Cloudflare Workers (serverless), D1, Vectorize, Queues — tất cả do Cloudflare quản lý.
- Không có Kubernetes cluster ⇒ không có Helm chart, không có ArgoCD Application/AppProject.

## Ap analogues (đã có sẵn)
| Thành phần plan | Tương đương IncidentIQ | Vị trí |
|-----------------|------------------------|--------|
| Helm chart | wrangler.toml + wrangler.preview.toml | `wrangler.toml` |
| ArgoCD sync | `deploy-preview.yml` / `deploy-prod.yml` | `.github/workflows/` |
| Terraform IaC | Cloudflare provider (D1, Vectorize, Queues, KV) | `infrastructure/terraform/` |
| CI security gates | Trivy, pip-audit, npm audit, gitleaks, Syft, Cosign | `.github/workflows/ci.yml` |
| Environments | preview, production, staging | `infrastructure/terraform/environments/` |
| Observability | Cloudflare Workers built-in analytics + Prometheus scrape (CF API) | `infra/observability/` |

## Multi-cloud
IncidentIQ thiết kế cloud-agnostic qua Wrangler (có thể deploy lên Workers trên bất kỳ account CF nào). Việc chứng minh multi-cloud (AWS/GCP) cần tài khoản cloud thật — xem `QuanLyKho/docs/multi-cloud/evidence-template.md`.
