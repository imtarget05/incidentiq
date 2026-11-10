# IncidentIQ — Threat Model

## Security boundaries
- **Trust boundary 1**: Client → API/MCP. The API authenticates `X-Api-Key`; MCP authenticates a tenant API key as a Bearer token, validates its stored hash, binds the principal to that key's tenant, and forwards the same key to the API. Store keys only in a secret manager; never commit them.
- **Trust boundary 2**: Tenant ↔ Tenant. Every document, chunk, incident, and retrieval is scoped by `tenant_id`. Two workspaces (Tenant A, Tenant B) prove isolation.
- **Trust boundary 3**: Ingested documents → LLM prompt. Documents are treated as untrusted context only; they cannot alter system instructions or tool invocation.
- **Trust boundary 4**: Triage → Production. Triage does not perform production remediation or configuration changes; it writes its triage report, audit entry, and usage metric to the platform's D1 data store.

## Attack scenarios and mitigations

| Threat | Mitigation |
|---|---|
| IDOR: tenant A guesses tenant B incident id | All incident/doc queries filter by `tenant_id`; cross-tenant access returns 404. |
| Data leakage in citations | Vectorize queries filtered by `tenant_id`; FTS5 joins `documents` on `tenant_id`; no cross-tenant chunks in citations. |
| Prompt injection in a document | Document content is injected only into the user context; system prompt is fixed and tells the model to ignore instructions in context. Tests assert system prompt is not overridden. |
| Malicious document ("ignore all instructions") | Sandboxed in context only; system prompt instructs the model to make read-only recommendations only. |
| Duplicate submissions / replay | `Idempotency-Key` + payload hash; duplicates return 202 same id; conflicting payload returns 409. |
| Concurrent status updates | Optimistic concurrency via `If-Match`/`version`; stale version returns 409. |
| Rate limit / quota abuse | Per-tenant rate-limit buckets; AI inference daily cap (429 when exceeded). |
| Vectorize / Workers AI failure | Graceful degradation: keyword-only (FTS5) or abstention with `insufficient_evidence`; never 500 on dependency failure. |
| API Token leakage | Token only in GitHub Secrets / `wrangler secret put`; never committed. |

## Authentication & authorization
- API: tenant API key hashed (SHA-256), only prefix stored in D1.
- MCP: Bearer tenant API key; each tool's `tenant_id` must match the authenticated key's tenant. A shared service key plus caller-supplied tenant ID is not a supported authorization model.
- RBAC: roles `reader` / `investigator` / `admin` on `workspace_members`.
