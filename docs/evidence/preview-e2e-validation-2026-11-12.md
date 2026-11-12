# Preview End-to-End Validation — 2026-11-12

Full E2E validation of the hardened preview deployment. Four production bugs
were found and fixed (commit `620fdac`); all flows re-verified after the fixes.

## Deployed components (preview)

| Worker | URL | Status |
|---|---|---|
| API | https://incidentiq-preview.tanmainguyenbinh.workers.dev | deployed, version `a2d4e762` |
| ETL consumer | incidentiq-etl-preview | deployed, consumer of `etl-queue-preview` (1 consumer) |
| MCP | https://incidentiq-mcp-preview.tanmainguyenbinh.workers.dev | deployed, service binding → API |

Bindings (preview): D1 `incidentiq-preview` (`8e1a7127-b9d3-43fc-82ff-c2dca620c82f`),
Vectorize `ai-knowledge-vectors-preview` (1024-dim cosine, metadata index
`tenant_id` created this session), queues `etl-queue-preview` / `etl-dlq-preview`,
Workers AI `ai`.

## Validation results

| # | Check | Result |
|---|---|---|
| 1 | `GET /health/ready` — d1/vectorize/workers_ai/etl_queue all ok | PASS (`{"checks":{"d1":"ok","vectorize":"ok","workers_ai":"ok","etl_queue":"ok"}}`) |
| 2 | Smoke script `scripts/smoke_test.sh` (health, incident create/get, event append, triage, quota) | PASS 7/7 |
| 3 | Upload → queue (`ETL_MODE=queue`) → ETL consumer → D1 `processed` + Vectorize upsert | PASS (`{"status":"uploaded","etl":"queued"}` → consumer log `{'status':'ok','chunks':1}` → status `processed`) |
| 4 | Tenant A RAG question (`POST /api/v1/question`) | PASS — grounded Vietnamese answer + 1 citation (score 0.825): "Trước khi khởi động lại pod, bạn nên thu thập heap dump từ endpoint /debug/pprof [1]" |
| 5 | Tenant B same question | PASS (isolation) — 0 citations, "I don't have enough information to answer" |
| 6 | MCP `tools/list` with tenant key | PASS — 7 tools |
| 7 | MCP `ask_question` Tenant A (service binding → API) | PASS — grounded answer + citation |
| 8 | MCP `ask_question` Tenant B | PASS — 0 citations |
| 9 | MCP cross-tenant guard (B sends A's tenant_id) | PASS — `-32001 "Tenant does not match authenticated API key"` |
| 10 | Local suite after fixes | PASS — 103 pytest green |

## Production bugs found by live validation (fixed in 620fdac)

1. **`list_documents` KeyError: 0** — tuple-indexed D1 rows; remote runtime
   returns dict rows. Fixed with `_row_col()`.
2. **`embed_texts` never produced vectors** — read `vectors` key; Workers AI
   qwen3-embedding returns `{"data": [...]}`. ETL retry-looped forever
   (`embedding_incomplete`), documents stayed `uploaded`.
3. **`VECTORIZE_INDEX.query(vector=...)` empty-vector error (40006)** — Python
   bindings need positional `query(vector, {options})`; MCP worker's
   object-form `{vector, ...}` fixed identically.
4. **`VECTORIZE_INDEX.delete(ids=...)` → AttributeError: delete** — binding
   method is `deleteByIds`. Fixed with `deleteByIds` + `delete` fallback +
   transient-error retry. This silently broke every document reindex.
5. **MCP → API fetch failed with Cloudflare error 1042** — same-account
   Worker-to-Worker fetch over public URL. Fixed with a service binding
   (`API` → `ai-knowledge-platform` prod / `incidentiq-preview` preview).
6. **gpt-oss-20b LLM answers parsed as empty** — model returns OpenAI-format
   `choices[0].message.content`; parser now handles both schemas
   (`_llm_text` helper in question + triage).
7. **Tenant isolation hardened to Vectorize namespaces** — vectors upserted
   into the tenant's namespace; queries pass `namespace` + `filter`.
   Rationale: metadata-index backfill lag (~10 min) delayed filter-only
   isolation for freshly-ingested docs; namespaces are the documented
   multi-tenant pattern.

## Tenant credentials (preview only, in-session)

- Tenant A `e20cde55-a228-4df3-9a45-b3511dc2a679` (Preview Tenant A)
- Tenant B `03cc2b2d-ba25-4c8f-80bc-f56654e57f0b` (Preview Tenant B)
- API keys shown once during seeding; hash-only persisted in D1 (`api_keys`).
  Keys are in the session transcript, not stored in the repo.

## Operational note (documented behavior)

Vectorize query visibility for fresh upserts lags the write-ahead-log by
minutes (async index rebuild, documented platform behavior). A document is
retrievable via namespace/metadata-filtered search ~5–15 min after ingestion.
Unfiltered raw queries see new vectors sooner; D1-backed lookups are immediate.
No action required — noted for SLO expectations on RAG freshness.

## Production smoke tenant (seeded 2026-11-12)

Tenant `5f42b259-9004-46dc-b59e-280ccaa69c89` ("Production Smoke") seeded into
production D1 `ai-knowledge-platform` (`aa3e2700-ccdc-4ab5-af89-abd5f3b01d26`)
via `scripts/seed_tenant.py`; INSERT verified with a follow-up SELECT. Its API
key is set as the GitHub secret `PROD_SMOKE_API_KEY` (repo scope, shown once).
`scripts/seed.sql` was applied then deleted. Pending before merge: user-created
`CLOUDFLARE_PREVIEW_API_TOKEN` + `CLOUDFLARE_PROD_API_TOKEN` GitHub secrets and
the `production` environment approval.

## Known residuals

- `etl-dlq-preview` has 0 consumers (by design — inspection only).
- `mcp/tests/streamable.test.ts`: 4 pre-existing failures (verified pre-existing
  on a clean tree earlier in the session; unrelated to these changes).
- `tests/api/test_atomic_ingestion.py` hangs locally (pre-existing, excluded).
