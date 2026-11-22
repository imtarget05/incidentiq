# Runbook — IncidentIQ Worker CPU/Time Limit (>80%)

## Trigger
Alert `IncidentIQWorkerCpuLimit` fire: Worker CPU time > 80% của limit trong 10 phút.

## Severity
Warning

## Impact
Worker gần hết CPU time, latency tăng, có thể bị Cloudflare chặn requests.

## Owner
Platform team

## Quy trình xử lý

1. **Xác nhận**: Cloudflare Dashboard → Workers Metrics → CPU time.
2. **Xác định routes tốn CPU**: Xem routes nào gọi embedding/LLM nhiều nhất.
3. **Khắc phục**:
   - Chuyển xử lý embedding từ inline sang queue (ETL_MODE = "queue") để giảm tải Worker request.
   - Tối ưu code: giảm kích thước chunk, cache embedding.
   - Nên nâng cấp Workers plan (paid) nếu cần CPU time cao hơn.
4. **Verify**: CPU time quay lại < 70% và ổn định.

## Runbook liên kết
- `etl-dlq.md` nếu queue bị sâu do chuyển sang ETL_MODE=queue.
