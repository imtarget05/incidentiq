# IncidentIQ — Interview Defense (≥25 questions)

Answers are grounded in the actual code, tests, and trade-offs in this repository.

## Product / business questions

**Q1. What problem does IncidentIQ solve?**
Engineers investigating Production incidents waste time gathering logs, runbooks, past incidents and docs from scattered sources. IncidentIQ combines them and proposes likely root causes, read-only checks, and citations.

**Q2. Who uses it?**
Backend Developers, DevOps Engineers, SREs, Technical Leads.

**Q3. What does it NOT do?**
It never mutates Production: no restart, no deploy, no DB/config change. All recommended checks are read-only.

**Q4. How do you measure effectiveness?**
A 30-case synthetic evaluation harness checks retrieval and response behavior against fakes — see `docs/evaluation.md`. It is not evidence of live RAG quality, latency, or MTTR improvement.

**Q5. Why this instead of a generic RAG chatbot?**
It has a business workflow (incident lifecycle, status transitions, timeline, audit), RBAC/tenant isolation, hybrid retrieval, MCP tools, and a quantitative evaluation — not just a Q&A demo.

## RAG / AI questions

**Q6. RAG vs fine-tuning?**
RAG provides verifiable citations (doc ID/version/section), picks up changed runbooks via re-indexing, fits the Workers AI free tier, and can abstain with `insufficient_evidence`. Fine-tuning cannot cite and would need retraining for new docs. See `docs/adr/rag-vs-finetuning.md`.

**Q7. Hybrid vs pure vector search?**
Keyword (FTS5) is intended to catch exact codes (OOMKilled, exit 137); vector search may catch paraphrases. The fake-backed golden set reports recall@5 = 1.0 for its fixtures only; it is not a representative benchmark. The API falls back to keyword search when Vectorize is unavailable.

**Q8. What if the AI hallucinates?**
The prompt requires evidence-based output and the response includes citations. The harness checks citation/abstention behavior against fakes; it does not establish a real-world hallucination rate. No-context requests return `insufficient_evidence`.

**Q9. What if a document contains "ignore all instructions"?**
Documents are untrusted context only. The system prompt is fixed and instructs read-only recommendations only. Tests assert the system prompt is not overridden.

## Reliability questions

**Q10. What if the same Queue event is delivered twice?**
`Idempotency-Key` + payload hash on incident creation and document upload; duplicates return 202 with the same id. Tests: `test_create_incident_idempotent_duplicate`.

**Q11. What if Vectorize is down?**
Graceful degradation → keyword-only (D1 FTS5). Never 500. Tests: `test_vectorize_unavailable_falls_back_to_keyword`.

**Q12. What if Workers AI times out?**
The API catches the inference error and returns a conservative fallback summary with retrieved evidence and read-only checks. This behavior has local fake-backed test coverage; live timeout behavior and D1 failure cases still need verification.

**Q13. What about concurrent incident status updates?**
Optimistic concurrency via `If-Match`/`version`; stale version returns 409. Test: `test_update_incident_concurrency_stale`.

**Q14. ETL retry / DLQ?**
The ETL uses up to three application-level retries, preserves version/reindex metadata when re-enqueuing, and writes terminal failures to the DLQ. It does not implement jitter. Tests cover failed embedding, retry metadata, and DLQ delivery failure.

## Security questions

**Q15. How do you stop tenant A from seeing tenant B's data?**
Every query is scoped by `tenant_id`; Vectorize uses `filter={tenant_id}`; FTS5 joins `documents` on `tenant_id`. Two workspaces prove isolation. Test: `test_idor_cross_tenant_triage_blocked`, `test_no_cross_tenant_citation_leakage`.

**Q16. How is auth handled?**
API: tenant API key hashed (SHA-256), only prefix stored. MCP: Bearer tenant API key is checked against its D1 hash, the authenticated tenant is bound to the tool request, and mismatched `tenant_id` arguments are rejected. The same tenant key is forwarded to the API. RBAC: reader/investigator/admin.

**Q17. Prompt injection / data leakage / malicious docs?**
Covered by threat model. System prompt fixed; context sandboxed; no cross-tenant citations.

## Cloudflare / architecture questions

**Q18. Why Cloudflare Workers instead of Kubernetes?**
The repository explores an edge-worker operating model and queue-based ETL, which reduces the amount of infrastructure managed in the project. Free-tier fit and actual cost have not been measured; platform limits should be verified against the active account and workload.

**Q19. Can it handle 10,000 users?**
There is no load-test evidence for that scale. The repository sets application-level document and AI limits but does not establish throughput or capacity.

**Q20. What if inference cost/quota rises?**
Per-tenant rate-limit buckets + daily AI cap (429 when exceeded) + quota dashboard `GET /api/v1/metrics/quota`. No auto-upgrade to paid.

## Data engineering questions

**Q21. Is D1 a real data warehouse?**
No. D1 stores operational data and triage metrics; `rag_eval_runs` is currently schema-only. There is no demonstrated analytics ingestion or warehouse pipeline.

**Q22. How is ETL designed?**
Document ingestion → validation → normalization → chunking → embedding → Vectorize index → retrieval. Versioned chunk IDs, reindex deletes old vectors before upsert, retry + DLQ.

**Q23. How are documents versioned?**
`version` column on documents/chunks; chunk IDs include version (`doc-vN-i`); reindex deletes old vectors before upsert.

## Code / testing questions

**Q24. How do you prove the numbers are real?**
`scripts/eval_harness.py` runs synthetic cases against fakes and writes `docs/evaluation.md`. Those results describe the fixture run, not production. CI now includes pytest, MCP type-check/tests, Trivy, SonarQube quality gate, and Wrangler dry runs; hosted results are required to claim the gates passed.

**Q25. Where are the interview-defense answers?**
This document, grounded in `api/src/main.py`, `api/src/etl.py`, `mcp/src/index.ts`, `tests/`, and `docs/`.

## Honest limitations
- No verified production deployment or billing/usage history is attached.
- Evaluation run against fakes; `--live` mode available against a deployed worker when credentials exist.
