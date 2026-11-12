# IncidentIQ — Deployment Runbook

The repository defines isolated preview and gated production workflows. A green CI run validates the source and Worker bundles; only a successful deploy workflow and live smoke test establish a deployment.

## Preview prerequisites

Create isolated preview resources in Cloudflare before running the workflow:

- A D1 database with a database ID different from the production ID in `wrangler.toml`.
- A Vectorize index name different from the production index.
- Separate ETL queue and dead-letter queue names.
- Preview Worker URLs for the API and MCP endpoint.
- A low-privilege preview API token and a preview tenant API key stored only as GitHub environment secrets.

Configure the GitHub `preview` environment with `CLOUDFLARE_ACCOUNT_ID`, `PREVIEW_D1_DATABASE_ID`, `PREVIEW_VECTORIZE_INDEX`, `PREVIEW_ETL_QUEUE`, `PREVIEW_ETL_DLQ`, `PREVIEW_API_WORKER_URL`, and `PREVIEW_MCP_WORKER_URL` as variables. Store `CLOUDFLARE_PREVIEW_API_TOKEN` and `PREVIEW_SMOKE_API_KEY` as secrets. Never copy production credentials into this environment.

Run **Actions → Deploy IncidentIQ preview → Run workflow**. The workflow validates that the resource IDs/names differ from the base config, dry-runs only preview Wrangler files, applies migrations to the preview database, deploys preview Workers, and runs authenticated API/MCP smoke checks. A successful workflow run is the evidence for preview deployment; this document alone is not.

## ETL modes

- `ETL_MODE=inline` in the base config runs chunking/embedding/upsert during the upload request. An embedding failure is reported as retryable work; the request path can fall back to the queue.
- Preview uses `ETL_MODE=queue`. The ETL Worker retries transient failures, preserves document version/reindex metadata between attempts, and only acknowledges a failed job after its DLQ record is accepted. If persistence or DLQ delivery fails, the queue message is retried rather than silently acknowledged.

## Manual preview smoke checks

```bash
./scripts/smoke_test.sh "$PREVIEW_API_WORKER_URL" "$PREVIEW_SMOKE_API_KEY"
```

The script creates a low-severity test incident in the supplied environment. Use only the isolated preview URL and key. The workflow also calls MCP `tools/list` with the same tenant API key.

## Failure handling

- `/health` reports Worker availability only; it does not check D1, Vectorize, or Workers AI end to end.
- A failed SonarQube quality gate or Trivy scan blocks CI. No deploy should be triggered until CI is green.
- `report_persist_failed` means triage output could not be durably recorded; retry after D1 is healthy and verify `GET /api/v1/incidents/{id}/report`.
- ETL retry/DLQ records should be checked before manually reprocessing. Reindexing is tenant- and workspace-protected.
- Roll back a Worker by redeploying the last known-good commit. Do not roll back a shared or production D1 migration without a reviewed recovery procedure.

## Production release

The GitHub `production` environment admits only `main` and requires reviewer approval. Set `CLOUDFLARE_ACCOUNT_ID`, `PROD_API_WORKER_URL`, and `PROD_MCP_WORKER_URL` as repository variables. Store a scoped `CLOUDFLARE_PROD_API_TOKEN` and an active tenant key `PROD_SMOKE_API_KEY` as production environment secrets. The smoke key must match an active `api_keys` record in the production D1 database; do not use a Cloudflare token as this key.

After CI passes and the production environment is configured, merge the reviewed PR into `main`, approve **Deploy IncidentIQ production**, and inspect the run. The workflow applies pending D1 migrations, deploys the Python API and ETL Workers with `pywrangler`, deploys the MCP Worker with Wrangler, then checks authenticated API behavior, MCP `tools/list`, and `/health/live` and `/health/ready`. Download the `incidentiq-deploy-evidence` artifact and check the live Worker URLs before declaring the release complete.

If a migration or deploy step fails, inspect the failed job and Cloudflare Worker logs before retrying. The workflow is serialized with `cancel-in-progress: false` so another push cannot interrupt a production release. A successful deployment does not by itself prove live retrieval quality, tenant isolation, alerting, retention, restore, or rollback behavior; verify those separately before relying on the service for incidents.
