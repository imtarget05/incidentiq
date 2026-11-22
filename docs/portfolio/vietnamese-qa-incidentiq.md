# Vietnamese Q&A — IncidentIQ Defense (DevOps/Platform + Serverless)

Câu trả lời bằng tiếng Việt, dùng cho phỏng vấn DevOps Platform / Cloudflare / Serverless.

## 1. DevOps / Platform

**Q: IncidentIQ triển khai trên stack nào?**
A: Cloudflare Workers (Python), D1 (serverless SQL), Vectorize (vector index), Cloudflare Queues (ETL), KV (rate-limit/feature flags). Terraform Cloudflare quản lý toàn bộ infra (`infrastructure/terraform/`).

**Q: Terraform có bao nhiêu environment?**
A: 3 environment: preview, staging, production. Mỗi environment có D1 database, Vectorize index, Queues, KV namespace riêng biệt (`infrastructure/terraform/environments/`).

**Q: Secret management như thế nào?**
A: Cloudflare API token qua `TF_VAR_cloudflare_api_token` / secret repo, không hardcode trong `.tfvars`. Wrangler secrets cho Workers.

**Q: CI security gates có gì?**
A: Trivy filesystem scan (vuln/secret/misconfig), pip-audit (Python), npm audit (MCP TypeScript), gitleaks (secret), Syft (SBOM), Cosign (sign), SonarQube quality gate.

**Q: Wrangler được validate như thế nào?**
A: `wrangler deploy --dry-run` cho API, ETL, MCP worker — xác nhận config hợp lệ mà không cần credential thật.

## 2. Serverless / Cloudflare

**Q: Worker xử lý ETL như thế nào?**
A: `ETL_MODE = "inline"` trong wrangler.toml: embedding và upsert vector thực hiện ngay trong request upload. Có thể chuyển sang `"queue"`: enqueue chỉ, consumer worker xử lý async (giảm tải CPU time).

**Q: Vector search hoạt động như thế nào?**
A: Tài liệu được embed qua Workers AI binding `[ai]`, upsert vào Vectorize index `ai-knowledge-vectors`. Truy vấn semantic search query vectors và lấy top-K, sau đó join metadata từ D1.

**Q: Canary / rollback như thế nào?**
A: Cloudflare Workers không có Argo Rollouts. Rollback qua `wrangler rollback` hoặc redeploy phiên bản trước từ Git (`deploy-preview.yml` / `deploy-prod.yml`).

## 3. Observability / SLO

**Q: SLI/SLO của IncidentIQ là gì?**
A: Error rate Worker ≤ 1%, CPU/time saturation ≤ 80%, D1 query errors = 0, ETL DLQ depth ≤ 10. Alert rules trong `infra/observability/cf-workers-alerts.yaml`, scrape qua Prometheus từ Cloudflare API.

**Q: Làm sao verify incident?**
A: Mở Cloudflare Dashboard → Workers & Pages → Metrics (Errors, CPU time), D1 → Queries (Errors), Queues → DLQ depth. So sánh với SLO trong `docs/runbooks/sli-slo-overview.md`.

## 4. Dev / Fullstack

**Q: Type safety trong IncidentIQ?**
A: Python type hints (ruff E4/E7/E9/F), TypeScript cho MCP (`npm run typecheck`), Pydantic models cho request/response. CI chạy pytest coverage + MCP test coverage.

**Q: Eval như thế nào?**
A: `scripts/eval_harness.py` (fake-backed evaluation), `scripts/demo.py` (demo scenarios). Golden set hiện đang là fake — cần chuyển sang live eval với LLM-as-judge.
