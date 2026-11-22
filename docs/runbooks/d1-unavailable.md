# Runbook — IncidentIQ D1 Unavailable

## Trigger
Alert `IncidentIQD1Unavailable` fire: D1 query errors > 0 trong 2 phút.

## Severity
Critical

## Impact
Không thể đọc/ghi metadata tài liệu, người dùng không thể truy cập kiến thức đã lưu.

## Owner
Platform team

## Quy trình xử lý

1. **Xác nhận**: Cloudflare Dashboard → D1 → ai-knowledge-platform → Queries → Errors.
2. **Kiểm tra**: D1 database có bị suspended không? Quota đã hết chưa?
3. **Khắc phục**:
   - Nếu D1 bị lỗi tạm thời: đợi Cloudflare khôi phục (thường < 5 phút).
   - Nếu quota hết: nâng cấp D1 plan hoặc xóa dữ liệu cũ.
   - Nếu schema lỗi: chạy migration lại qua `wrangler d1 migrations apply`.
4. **Verify**: `wrangler d1 execute ai-knowledge-platform --command="SELECT count(*) FROM documents"` thành công.

## Runbook liên kết
- `worker-high-error-rate.md` nếu Worker lỗi do D1.
