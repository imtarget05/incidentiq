# SLI/SLO — IncidentIQ (Cloudflare Workers AI Knowledge Platform)

Mục tiêu: chuyển alert rules (`infra/observability/cf-workers-alerts.yaml`) thành SLO đo lường có trigger, severity, impact, owner và bước verify rõ ràng.

## 1. Chỉ số SLI đã định nghĩa

| SLI | Metric | Cửa sổ | Target (SLO) | Alert liên kết |
|-----|--------|--------|--------------|----------------|
| Error rate (Worker) | `rate(cloudflare_worker_requests_total{status=~\"5..\"}[5m]) / rate(cloudflare_worker_requests_total[5m])` | 5 phút | ≤ 1% | `IncidentIQWorkerHighErrorRate` |
| CPU/time saturation | `rate(cloudflare_worker_cpu_time_seconds_total[5m])` | 10 phút | ≤ 80% | `IncidentIQWorkerCpuLimit` |
| D1 availability | `cloudflare_d1_query_errors_total{database=\"incidentiq\"}` | 2 phút | = 0 | `IncidentIQD1Unavailable` |
| ETL DLQ depth | `cloudflare_queue_dead_letter_messages{queue=\"etl-dlq\"}` | 5 phút | ≤ 10 | `IncidentIQEtlDlqDepth` |

## 2. Error budget

- SLO 99% error rate ⇒ error budget = 1% trong 30 ngày (~43.2 phút downtime/lỗi 5xx).
- Nếu error budget tiêu hết trong tháng → kỉ túc release mới, chỉ deploy hotfix.

## 3. Owner & trigger

| SLI | Owner | Trigger | Severity |
|-----|-------|---------|----------|
| Error rate (Worker) | Platform team | > 1% trong 5 phút | Critical |
| CPU/time saturation | Platform team | > 80% trong 10 phút | Warning |
| D1 availability | Platform team | errors > 0 trong 2 phút | Critical |
| ETL DLQ depth | Ops team | > 10 tin nhắn trong 5 phút | Warning |

## 4. Cách verify khi incident

1. Mở Cloudflare Dashboard → Workers & Pages → ai-knowledge-platform → Metrics.
2. Xem Error rate, CPU time, D1 query errors, Queue DLQ depth.
3. So sánh với SLO trong bảng trên.
4. Nếu vượt → vào runbook chi tiết tương ứng (xem các file bên dưới).
5. Sau khi khôi phục, ghi incident vào error budget tracker.
