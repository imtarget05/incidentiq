# IncidentIQ — Failure Modes

| Component | Failure | Detection | Recovery / fallback |
|---|---|---|---|
| Workers AI embedding | Timeout, error, or incomplete vector batch | ETL job remains retryable; after retry limit it is dead-lettered | Document is not marked processed without vectors; operators can inspect/retry or reindex |
| Workers AI LLM | Timeout or error | Triage response and structured logs | Returns a conservative summary based on retrieved evidence; this path needs live failure testing |
| Vectorize | Unavailable | Exception caught | Keyword-only search via D1 FTS5 |
| D1 | Query or write error | API reports an error; triage report persistence failure returns 503 | Do not claim a report is saved unless persistence succeeds; generic D1 retry/backoff is not implemented for every route |
| Queues / ETL | Job fails | Retry up to 3 application attempts, then DLQ | Version/reindex metadata is preserved across retries; failed D1/DLQ writes keep the message unacknowledged for queue retry |
| Rate limit exceeded | 429 | `Retry-After` header | Client backs off; quota dashboard shows usage |
| AI quota exhausted | 429 `ai_quota_exceeded` | Quota dashboard | No AI calls until window resets; keyword search still works |
| Cross-tenant access | 404 | Authorization test suite | Enforced by `tenant_id` scoping in every query |

## Graceful degradation boundary
Vectorize errors can fall back to D1 full-text search. AI failures are intended to avoid unsupported recommendations, while incomplete document embeddings remain retryable. D1 is a required system of record: the API can return 5xx when D1 fails and does not promise universal exponential retries. Mutating work is not blindly replayed.
