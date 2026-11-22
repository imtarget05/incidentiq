# Runbook — IncidentIQ ETL DLQ Depth (>10)

## Trigger
Alert `IncidentIQEtlDlqDepth` fire: ETL DLQ có > 10 tin nhắn trong 5 phút.

## Severity
Warning

## Impact
Tài liệu upload nhưng không được xử lý embedding/index, người dùng không tìm thấy tài liệu vừa upload.

## Owner
Ops team

## Quy trình xử lý

1. **Xác nhận**: Cloudflare Dashboard → Workers & Pages → Queues → etl-dlq → Messages.
2. **Xem lý do DLQ**: Xem messages trong DLQ, tìm lỗi phổ biến (D1 down, Vectorize timeout, embedding model lỗi).
3. **Khắc phục**:
   - Nếu D1/Vectorize khôi phục: reprocess DLQ messages qua `wrangler queue retry` hoặc consumer worker.
   - Nếu embedding lỗi: kiểm tra Workers AI binding `[ai]` trong wrangler.toml.
4. **Verify**: DLQ depth giảm về 0 trong 30 phút, tài liệu mới được index vào Qdrant/Vectorize.

## Runbook liênket
- `d1-unavailable.md` nếu DLQ do D1 lỗi.
