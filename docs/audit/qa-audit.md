# IncidentIQ QA and Engineering Audit

**Audit date:** 2026-11-09  
**Scope:** repository implementation, tests, migrations, CI and deployment controls. No production or preview environment was accessed.

## Readiness conclusion

**Production-ready:** Not established. Local tests and static checks provide useful evidence, but hosted SonarQube quality-gate results, Trivy results, Cloudflare preview deployment, live dependency health, load behavior, and operational recovery have not been verified.  
**Production-deployed:** No evidence; this audit performed no deployment. The former automatic production deployment path was removed and the deploy script is disabled. A separate manual preview workflow exists and requires isolated preview resources and secrets.

## Acceptance and evidence

| Area | Evidence / result | Status |
| --- | --- | --- |
| Retrieval and API | `pytest -q tests/api` covers API, ingestion and retrieval paths; full result recorded below | Local only |
| ETL queue, retry and DLQ | `tests/api/test_etl_modes.py` covers embedding failure, retry payload, DLQ failure, partial writes, and reindex vector cleanup failure | Local only |
| Evaluation harness | `python scripts/eval_harness.py` completed 30 fake-backed cases (20 sufficient, 10 insufficient); harness-reported scores are not live RAG or production quality evidence | Fake backend only |
| Demo failure scenarios | `python scripts/demo.py` completed grounded triage, insufficient evidence, dependency degradation, and cross-tenant/auth scenarios | Local fakes only |
| Tenant authorization | `mcp/tests/index.test.ts` checks invalid key hash, principal/tenant mismatch, no downstream call on mismatch, forwarded tenant key and audit redaction | Local only |
| Triage persistence | `tests/api/test_triage.py` verifies stored report and 503 when persistence fails | Local only |
| Upload authorization | `tests/api/test_ingestion.py` verifies investigator membership is required | Local only |
| MCP upload contract | MCP tests verify multipart file upload and forwarded idempotency key | Local only |
| CI quality gate | `.github/workflows/ci.yml` requires `SONAR_HOST_URL` and `SONAR_TOKEN`, runs SonarQube scan with `sonar.qualitygate.wait=true`; Trivy findings fail the workflow | Configured, hosted result unavailable |
| Preview deployment | `.github/workflows/deploy-preview.yml` is manual and validates isolated resource identifiers before deploy | Not run; external preview variables/resources absent |
| Production deployment | Production deploy job removed; `scripts/deploy.sh` exits with a disabled message | Guard verified locally |

## Architecture, flow, and trade-offs

The API authenticates tenant API keys and applies workspace roles for sensitive operations. Document ingestion stores tenant-scoped metadata in D1 and enqueues ETL work. The queue worker chunks content, obtains embeddings, upserts tenant-tagged points to Vectorize, and persists chunk metadata in D1. Retrieval combines vector and full-text search, then applies tenant scope before returning context. The MCP worker authenticates with the caller's tenant API key, binds every tool request to that authenticated tenant, and forwards requests to the API. Triage combines evidence and persists a report; it does not issue remediation actions.

The queue-based ETL path trades immediate completion for bounded retries and eventual processing. Vectorize and D1 do not share a transaction, so writes use deterministic chunk/vector identifiers and retry-safe upserts. Reindex and delete paths now fail closed when vector cleanup fails to avoid treating stale vectors as successfully removed. This can temporarily block updates/deletes during Vectorize outages; the API returns a service error or queue work retries instead of silently claiming success. MCP audit events retain parameter names and outcomes, not document or question content, reducing sensitive payload exposure while limiting forensic detail.

## Failure scenarios and handling

- Embedding failure returns retry, then DLQ after the configured retry limit; the document is not marked processed.
- Queue retry/DLQ publication failure is surfaced for retry rather than acknowledged silently.
- Partial D1 chunk writes can be replayed with deterministic IDs and upsert semantics.
- Reindex vector deletion failure prevents replacement upserts; queue retry/DLQ records the failure.
- API document delete/update and reindex preserve D1 records when vector cleanup fails and return a service error.
- Triage report persistence failure returns `503 report_persist_failed`, avoiding a success response without a durable report.
- MCP tenant mismatch returns 403 before API/vector/full-text downstream calls.

## Verification record

Verification was run with Python 3.11.9 and repeated under Python 3.13 where noted (matching project CI):

- `pytest -q tests/api`: **60 passed, 1 deprecation warning** (Python 3.11.9).
- Re-run during consolidation: `uv run --frozen pytest -q tests/api`: **60 passed, 1 deprecation warning** (Python 3.11.9; it resolves project dependencies from `uv.lock`).
- Python 3.13 CI parity check: `uv run --python 3.13 --frozen pytest -q tests/api`: **60 passed, 1 deprecation warning**; `uv run --python 3.13 --frozen ruff check --select E4,E7,E9,F api/src tests/api scripts`: **passed**. The fake evaluation harness initially exposed a missing locked `httpx` test dependency; `httpx==0.27.0` was added to the dev dependency group and lock file.
- `uv run --python 3.13 --frozen python scripts/eval_harness.py`: **30 fake-backed cases completed** (20 sufficient, 10 insufficient); synthetic scores are not live retrieval evidence.
- Re-run during consolidation: `cd mcp && npm run typecheck && npm test -- --run`: **typecheck passed; 15 tests passed**.
- `cd mcp && npm run typecheck && npm test -- --run`: **typecheck passed; 15 tests passed**.
- `ruff check --select E4,E7,E9,F api/src tests/api scripts`: **all checks passed**. Broader default Ruff rules reported 233 style/modernization findings at baseline; CI intentionally gates syntax/import/undefined-name checks using the explicit subset.
- Wrangler `deploy --dry-run` for API, ETL and MCP base configs and all three preview configs: **6 dry-runs succeeded**; dry-run only, no remote access. Wrangler 3.114.17 warns that Python Workers are experimental and that this Wrangler release is outdated.
- `scripts/deploy.sh`: expected disabled exit code 2; guard passed.
- `python scripts/eval_harness.py`: **30 fake-backed cases completed**; harness output includes recall@5 1.0, MRR proxy 0.5 and other synthetic scores, which must not be interpreted as live system quality.
- `python scripts/demo.py`: **four demo scenarios passed** against local fakes.
- `cd mcp && npm audit --json`: **12 findings (2 critical, 8 high, 2 moderate)**; fixes require major test/deploy toolchain upgrades.
- SonarQube and Trivy hosted scans: **not run**; require CI service configuration and hosted runner.

The deterministic fake-backed evaluation harness was rerun on Python 3.11 and completed 30 cases, with 20 marked sufficient and 10 insufficient. Its scores (including recall@5 and correctness proxies) are synthetic harness output, not measured live RAG quality, and no performance numbers, coverage percentage, or live service availability is asserted by this audit. `/health` reports configuration presence rather than end-to-end dependency readiness.

## Remaining risks and prerequisites

1. Coordinate supported major upgrades for the MCP test/deploy dependency tree and rerun `npm audit`, tests, and Wrangler dry-runs.
2. Configure a SonarQube Server project and CI variables/secrets `SONAR_HOST_URL` and `SONAR_TOKEN`; until then CI deliberately fails closed at the Sonar step.
3. Configure a separate GitHub `preview` environment with a rotated Cloudflare preview token, account ID, preview D1/Vectorize/queue resources, preview URLs, and a preview API key. Preview workflow has not been exercised.
4. Revoke and rotate any credentials previously exposed outside this repository; this audit did not read or reuse them.
5. Run hosted CI and retain raw coverage, SonarQube, Trivy, and Wrangler dry-run artifacts before making stronger readiness claims.
6. Validate service-level health, alerting, backup/restore, queue replay, and load behavior in the isolated preview environment.

## Production readiness statement

The repository has locally verified behaviors and explicit CI/deployment controls, but lacks hosted security/quality gate evidence and environment-level operational evidence. Wrangler dry-runs also warn that Cloudflare Python Workers are experimental and that the pinned local Wrangler 3 release is outdated; supported deployment compatibility must be confirmed before operational rollout. Treat it as **not yet demonstrated production-ready** and **not production-deployed** until the remaining evidence above is collected.
