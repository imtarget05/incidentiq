# ADR: Cloudflare Workers vs Kubernetes

## Decision
Run the API on Cloudflare Workers (Python FastAPI) instead of a self-managed Kubernetes cluster.

## Rationale
- **Budget**: $0/month target on Cloudflare Free; no VPS, no AKS, no credit card.
- **Operational simplicity**: No cluster to patch, scale, or secure; Wrangler handles deployment.
- **Bounded workload**: Incident triage is request/response, short-lived, read-heavy — fits the 10 ms CPU free-tier limit when ETL is offloaded to Queues.
- **Portfolio signal**: Demonstrates understanding of when serverless fits and when it doesn't (no batch ETL inside a request).

## Trade-offs accepted
- 10 ms CPU/request limit → ETL (chunking/embedding) moved to Queues with retry/DLQ, not in the request path.
- 10,000 neurons/day AI cap → daily quota enforcement (429 when exceeded).
- Not suitable for 10,000 concurrent users on Free tier; capacity limits are documented honestly (see `docs/interview-defense.md`).

## Evidence
- `wrangler.toml` — Python 3.13 Worker, D1/Vectorize/Queues bindings.
- `api/src/etl.py` — Queue-based ETL with bounded retries and DLQ.
- `docs/cost-and-limits.md` — Free-tier quotas and guardrails.