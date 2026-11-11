# Hoàn thiện hai dự án theo JD và tạo bằng chứng cho CV

## Mục tiêu và giới hạn

Mỗi dự án có nghiệm thu riêng cho AI API, MCP, RAG, ETL, Data Mart/DWH, bảo mật, kiểm thử, observability, performance và cost. Cloud là mô phỏng nội bộ doanh nghiệp với dữ liệu công khai/tổng hợp, không phải hệ thống doanh nghiệp đang có người dùng thật. Bằng chứng dự án không được quy đổi thành 3–4 năm kinh nghiệm.

Phân biệt `implemented` (mã + test), `verified_local` (kết quả local gắn revision), `verified_cloud` (cloud artifact gắn revision), `unproven` (thiếu/chưa đạt). Không gắn nhãn cloud cho kết quả synthetic hoặc local. Không tạo tài nguyên tính phí trước khi có dự toán cấu hình/thời lượng và mức trần được chốt. Không thêm gRPC, Kubernetes hoặc fine-tuning mới.

## Mốc 0 — Nền tảng và evidence

Ghi HEAD/status, giữ nguyên thay đổi hiện có. Khóa Python/Node/Java/dependencies, cô lập pytest IncidentIQ, dựng lại router venv. Tạo ma trận JD → chức năng → test → artifact và lệnh setup/test/build/up/benchmark/collect. Evidence ghi revision, cấu hình không chứa secret, thời điểm và giới hạn. Người khác phải dựng lại được môi trường.

## Mốc 1 — Reliability

Enterprise: workflow tải text theo document ID; Kafka là ingestion chính; transactional outbox đồng giao dịch tài liệu; publisher xác nhận; consumer dedup event ID/document version; phân loại transient/permanent, retry và DLQ; reconciliation; poller cũ chỉ chuyển đổi không cạnh tranh. HITL có durable state, lease chống đồng thời và idempotency ở hệ thống nhận.

IncidentIQ: unique tenant/operation/key, xử lý duplicate trước migration; payload hash và 409 khi đổi payload; queue ETL trên cloud; kiểm tra document version trước vector write; reconciliation D1–Vectorize, DLQ replay/index status; deadline; atomic quota dùng chung.

Nghiệm thu: concurrency, duplicate messages, broker/vector failure và restart không mất việc âm thầm; mọi việc hoàn thành hoặc ở trạng thái lỗi/retry truy được.

## Mốc 2 — Contract, MCP và identity

Mỗi dự án: OpenAPI; validation/error/request ID/pagination/payload limit; MCP SDK chính thức và lifecycle/Streamable HTTP với real client. Giữ adapter cũ deprecated, test client cũ; REST/MCP dùng chung nghiệp vụ/phân quyền. Identity từ auth không từ tool arguments. Enterprise OIDC/JWT owner/role; IncidentIQ giao diện login/workspace roles. API key có rotate/revoke/scope. Deadline xuyên chuỗi, backoff/jitter cho transient và thao tác an toàn. Audit actor/tenant/action/resource/outcome/trace ID, redaction; privileged change có durable audit, cảnh báo khi xuất log lỗi. Test API/event phiên bản hiện tại và trước.

## Mốc 3 — RAG và đánh giá

Enterprise Python/Qdrant là retrieval chính, Spring lexical fallback được gắn nhãn. IncidentIQ hybrid lexical–Vectorize có tenant/workspace filtering và degradation tests. Cả hai: upload/parse/chunk/embed/index/retrieve/cited answer; version/update/delete/reindex/cache invalidation; abstention khi thiếu evidence.

Mỗi dự án 100 câu: 60 answerable, 20 unanswerable, 20 auth/injection. Rà soát source labels; 30 dev, 70 acceptance. Lưu raw retrieval/answer/error, tách synthetic/live. Ngưỡng ban đầu: Recall@5 ≥ .80 (answerable), citation correctness ≥ .90, correct abstention ≥ .90 (unanswerable), không leak trong security set. Không hạ ngưỡng để xanh.

## Mốc 4 — Data Foundation / DWH

Database PostgreSQL analytics riêng và dbt pipeline riêng từng dự án, không dashboard trực tiếp OLTP. Lớp raw → staging → mart. Enterprise facts ingestion/retrieval/LLM request, dimensions tenant/document/model/date. IncidentIQ facts incident/triage/ETL, dimensions tenant/service/date. Grain event/execution có dedup ID. Python incremental export, checkpoint sau commit, lookback 48 giờ, upsert, date-range backfill. dbt daily aggregates, freshness/not-null/unique/relationships/reconciliation; tenant read isolation. Nghiệm thu replay không phình row, backfill giống kết quả, restart phục hồi, dashboard đối chiếu source.

## Mốc 5 — Observability, performance và safety

Trace REST/MCP → API → queue → retrieval → model. Dashboard riêng: traffic/error/latency/lag/DLQ/retrieval/tokens/cost/freshness. Liveness khác readiness dependency-bound. Alert: error >5%/5 phút; queue lag >5 phút; DLQ xuất hiện; analytics trễ hai chu kỳ. Đo workload cố định 1/5/10 concurrent users, p50/p95/throughput/errors/resources/cost per successful answer, before/after cache/context/routing. Secret/dependency/container scans: không critical/high chưa giải quyết hoặc chưa đánh giá cụ thể. Diễn tập auth/injection/SSRF connector, backup/restore/rollback; nhận alert thật, trace được request, lưu recovery record, tách cost measured/estimated.

## Cloud và bàn giao

Enterprise Azure Container Apps, managed PostgreSQL, Blob, Kafka và Qdrant private có volume, model trên cloud private; confidential không đi ra provider ngoài policy. IncidentIQ Cloudflare Workers/D1/Vectorize/Queues/DLQ và analytics PostgreSQL/job riêng; nâng toolchain hỗ trợ trước deploy.

CI xanh → isolated staging → migration/smoke → live RAG/load → fault/restart/restore/rollback → quan sát ít nhất 24 giờ → export/redact evidence → dọn tài nguyên. Budget alert không tự chặn spend.

Mỗi dự án bàn giao: acceptance/revision matrix; CI/test/scan/migration results; evaluation dataset/raw benchmark/reproduction; dashboards/traces/alert/recovery; measured cost window; demo video 5–7 phút, architecture/ADRs; CV chỉ dùng số đo thật, ghi dự án cá nhân cloud mô phỏng doanh nghiệp. Hoàn tất khi từng dự án đạt matrix, mọi gap công khai, ứng viên tự giải thích data/auth/failure/recovery/metrics/contribution. Bằng cấp và lịch sử làm việc ngoài phạm vi repo.
