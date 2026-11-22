# Runbook — IncidentIQ Worker High Error Rate (>1%)

## Trigger
Alert `IncidentIQWorkerHighErrorRate` fire: Worker tỷ lệ 5xx > 1% trong 5 phút.

## Severity
Critical

## Impact
Người dùng không thể upload tài liệu, tìm kiếm semantic, hoặc truy cập dashboard.

## Owner
Platform team

## Quy trình xử lý

1. **Xác nhận**: Cloudflare Dashboard → Workers & Pages → ai-knowledge-platform → Metrics → Errors. Xác nhận status 5xx.
2. **Xác định scope**: Tất cả routes hay chỉ `/api/ingest` / `/api/search`?
3. **Kiểm tra dependency**:
   - D1: `wrangler d1 execute ai-knowledge-platform --command="SELECT 1"` (local) hoặc Cloudflare Dashboard D1.
   - Vectorize: kiểm tra index `ai-knowledge-vectors` có up không.
   - Queues: kiểm tra `etl-queue` / `etl-dlq` có choked không.
4. **Rollback nếu deploy mới**: Nếu error bắt đầu sau release mới, `wrangler rollback` hoặc redeploy phiên bản trước qua `deploy-preview.yml` / `deploy-prod.yml`.
5. **Verify**: error rate quay lại < 1% và ổn định 15 phút. Ghi incident vào error budget.

## Runbook liên kết
- `d1-unavailable.md` nếu D1 lỗi.
- `etl-dlq.md` nếu DLQ quá sâu.
