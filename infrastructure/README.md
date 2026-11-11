# IncidentIQ — Infrastructure (Terraform, data plane)

Terraform provisions the **durable Cloudflare data plane** for IncidentIQ:

| Resource | Provider resource | Maps to (wrangler.toml binding) |
| --- | --- | --- |
| D1 database | `cloudflare_d1_database` | `[[d1_databases]] DB` |
| Vectorize index (1024-dim, cosine) | `cloudflare_vectorize_index` | `[[vectorize]] VECTORIZE_INDEX` |
| ETL queue | `cloudflare_queue` | `[[queues.producers]] ETL_QUEUE` |
| ETL dead-letter queue | `cloudflare_queue` | `[[queues.producers]] ETL_DLQ` |
| Config-cache KV namespace (future) | `cloudflare_workers_kv_namespace` | *(not yet bound — see below)* |

## Ownership split (important)

**Terraform owns data-plane resources only. Worker scripts are NOT managed by
Terraform.** The three workers — `ai-knowledge-platform` (API, `wrangler.toml`),
`ai-knowledge-etl` (queue consumer, `wrangler.etl.toml`), and the MCP worker —
are deployed exclusively by `wrangler deploy` in the GitHub Actions workflows
(`.github/workflows/deploy-preview.yml`, `deploy-prod.yml`).

Rationale: `cloudflare_worker_script` for `python_workers` bundles would fight
wrangler's ownership of the build/dry-run/deploy pipeline (CI runs
`wrangler deploy --dry-run` on `wrangler.toml`, `wrangler.etl.toml`,
`mcp/wrangler.toml`), and any drift between a Terraform-managed bundle and the
repo would break the deploy gate. Provisioning with Terraform + deploying with
wrangler is the recommended split for this stack.

## Secrets & no hardcoded account ids

- `cloudflare_api_token` is `sensitive` and supplied via env
  (`TF_VAR_cloudflare_api_token` or `CLOUDFLARE_API_TOKEN`). Never commit it.
- The **account id is never hardcoded** in `.tf` files; every resource takes
  `var.cloudflare_account_id`, provided per environment (`environments/*.tfvars`
  is committed with names only — no ids, no secrets).

## Apply commands

```bash
cd infrastructure

# Preview environment
terraform init
terraform plan  -var-file=environments/preview.tfvars
terraform apply -var-file=environments/preview.tfvars

# Production environment
terraform init
terraform plan  -var-file=environments/production.tfvars
terraform apply -var-file=environments/production.tfvars
```

## Outputs → GitHub Actions variables

Apply then wire the outputs into repository **Variables**
(`PREVIEW_*` from the preview apply, `PROD_*` from production):

```bash
terraform output -json database_id            # -> PREVIEW_D1_DATABASE_ID / PROD_D1_DATABASE_ID
terraform output -json vectorize_index_name   # -> PREVIEW_VECTORS_INDEX   / PROD_VECTORS_INDEX
terraform output -json etl_queue_id           # -> PREVIEW_ETL_QUEUE_ID    / PROD_ETL_QUEUE_ID
terraform output -json etl_dlq_id             # -> PREVIEW_ETL_DLQ_ID      / PROD_ETL_DLQ_ID
terraform output -json kv_namespace_id        # -> PREVIEW_CONFIG_KV_ID    / PROD_CONFIG_KV_ID
```

`database_id` feeds `[[d1_databases]].database_id` in the environment's
wrangler config; `vectorize_index_name` and the queue names feed the
`[[vectorize]]` / `[[queues.producers]]` entries.

### KV namespace (future config cache)

The KV namespace is provisioned now but **not** bound in `wrangler.toml` (CI
dry-run must keep passing unchanged). When a config cache is needed, add:

```toml
[[kv_namespaces]]
binding = "CONFIG_KV"
id = "<terraform output kv_namespace_id>"
```

to the relevant wrangler config and let CI validate it as usual.

## Disaster recovery (DR)

- **Backups:** `scripts/backup_d1.sh` exports the remote D1 database to
  `backups/ai-knowledge-<timestamp>.sql` and prunes to the last N (default 14).
  Schedule it with a GitHub Actions cron workflow (hourly recommended) or any
  cron runner with `wrangler` + `CLOUDFLARE_API_TOKEN` on PATH.
- **Restore:** `scripts/restore_d1.sh <backup-file>` executes a backup against
  the remote database with a confirmation prompt (`FORCE=1` to skip). Prefer
  **D1 Time Travel** (30-day point-in-time) for recent incidents; file restores
  are for older snapshots.
- **DLQ reprocess:** `scripts/dlq_reprocess.py` lists dead documents
  (`status='failed'`) from D1, prints the queue payloads they would produce,
  and (`--apply`) resets them to `status='uploaded', error=NULL` so the
  operator can re-enqueue via `POST /api/v1/documents/{id}/reindex`. The CLI
  has **no** `wrangler queues` message-send subcommand (verified on wrangler
  4.125.0 and the repo-bundled 4.160.0); the Queues REST API
  (`PUT /accounts/{account_id}/queues/{queue_id}/messages`) is the alternative
  push path if you have queue ids and account access.
- **Circuit breaker state:** the `etl_circuit_state` table (migration
  `migrations/006_orchestration.sql`) is runtime state, not source data — it is
  safe to lose in a restore and must never be used to bypass reprocessing.
