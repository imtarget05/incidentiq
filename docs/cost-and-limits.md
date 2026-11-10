# IncidentIQ — Cost and Limits

## Cost objective and evidence

The project targets Cloudflare's lower-cost services. No billing export, account usage history, or verified live workload is included in this repository, so monthly cost is not measured and a `$0/month` outcome is not guaranteed. Confirm current plan quotas and charges in the Cloudflare account before deploying preview resources.

## Enforced application limits

- AI inference guardrail: 100 requests per tenant per daily window in API code, with HTTP 429 when the recorded bucket reaches the limit.
- Document upload: 1 MB maximum in the API.
- ETL: at most 25 chunks per document, with an 800 character chunk target.
- Generated answer: model request is capped at 512 tokens in triage.

These are application limits, not proof of platform capacity or a service-level objective. The quota middleware's D1 failure path is best effort and needs operational verification.

## Architectural trade-offs

- D1 keeps operational metadata and metric records near the Workers runtime, but it is not an enterprise warehouse.
- Vectorize and D1 do not share a transaction; incomplete indexing requires retries and operator reconciliation.
- Queue ETL adds asynchronous recovery paths and separate resources. Preview queues/index/database must be isolated from production resources.
- Platform limits, service pricing, and free-plan eligibility can change. Re-check the provider dashboard and official pricing before creating resources.
