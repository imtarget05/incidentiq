# JD implementation acceptance backlog

Source of scope: [plan.md](plan.md). `implemented` is not `verified_cloud`.

- [x] 0.1 Record original revisions and existing working-tree changes (docs/evidence/BASELINE_2026-11-10.md).
- [x] 0.2 Add explicit runtime versions, locked Python environment and isolated `python -I -m pytest` runner.
- [x] 0.3 Add `scripts/jd.py` setup/test/build/collect entrypoints and JD matrix.
- [ ] 0.4 Complete clean-environment baseline for all suites, exact Node22/Java17; review raw artifacts.
- [ ] 0.5 Verify full Docker/local stack; current Docker daemon unavailable.
- [ ] 1.E1 Enterprise document-text workflow, correct transient retry, durable outbox publisher/consumer version dedup.
- [ ] 1.E2 Enterprise reconciliation and durable leased HITL external idempotency.
- [ ] 1.I1 IncidentIQ atomic tenant/operation idempotency, payload conflict and duplicate-safe migration.
- [ ] 1.I2 IncidentIQ queue/version guard, reconcile/DLQ replay, deadlines and shared atomic quota.
- [ ] 1.A Acceptance: concurrency/duplicate/broker/vector outage/restart with durable visible recovery.
- [ ] 2.1 Each: OpenAPI/error/request-ID/validation/pagination/size limits and current/previous contract tests.
- [ ] 2.2 Each: official MCP SDK lifecycle/Streamable HTTP real-client tests and deprecated adapter compatibility.
- [ ] 2.3 Each: identity binding, API key lifecycle/scope, IncidentIQ UI auth, Enterprise OIDC/owner tests.
- [ ] 2.4 Each: end-to-end deadline, safe retry/jitter, durable redacted privileged audit and export-failure alerts.
- [ ] 3.1 Each: end-to-end ingestion/retrieval/answer, index versions, update/delete/reindex/cache and abstention.
- [ ] 3.2 Each: 100 labelled questions (60/20/20), fixed 30-dev/70-acceptance split; human label review pending.
- [ ] 3.3 Live acceptance: Recall@5≥.80, citations≥.90, abstention≥.90, zero security-set leakage; retain raw artifacts.
- [ ] 4.1 Each: separate PostgreSQL analytics, raw/staging/mart, facts/dimensions, tenant read policy.
- [ ] 4.2 Each: incremental exporter/post-commit checkpoint, 48h overlap, upsert/date backfill.
- [ ] 4.3 Each: dbt aggregates/quality/freshness/reconciliation; replay/backfill/restart equivalence.
- [ ] 5.1 Each: distributed traces, health/readiness, dashboards and configured threshold alerts.
- [ ] 5.2 Each: real load 1/5/10 concurrency and optimization before/after, cost success denominators.
- [ ] 5.3 Each: scans and auth/injection/SSRF tests; restore/rollback and actual alert delivery evidence.
- [ ] C.1 Cost estimate and approved spending cap BEFORE any paid resources.
- [ ] C.2 Isolated Azure/Cloudflare staging, supported toolchain, migration/smoke on exact passing revision.
- [ ] C.3 Live evaluation/load/fault/recovery; ≥24h observed run (not assumed permanent uptime).
- [ ] C.4 Export/redact evidence, measure actual costs and clean resources.
- [ ] D.1 Each: acceptance report, raw data, reproduction, demo video/architecture/ADRs, honest CV statements.

These are shared scope checkboxes, not a claim that a concurrent implementation worker's edits have already passed independent verification. Update only after reviewing test artifacts.
