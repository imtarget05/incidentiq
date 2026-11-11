# Infrastructure — IncidentIQ Cloudflare

Terraform configuration for provisioning Cloudflare resources used by IncidentIQ:

- **D1 Database** — tenant metadata, documents, incidents, audit logs
- **Vectorize Index** — document embeddings for RAG retrieval
- **Cloudflare Queues** — ETL processing queue + dead-letter queue
- **KV Namespace** — distributed rate limiting (replaces in-memory Map)

## Usage

```bash
# Preview environment
terraform init
terraform plan -var-file=preview.tfvars
terraform apply -var-file=preview.tfvars

# Production environment
terraform init
terraform plan -var-file=production.tfvars
terraform apply -var-file=production.tfvars
```

## Required secrets/vars

| Name | Source |
|------|--------|
| `CLOUDFLARE_API_TOKEN` | GitHub Secret / env var |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub Variable / env var |

## Outputs

After `terraform apply`, use the output values to update `wrangler.toml`:
- `d1_database_id` → `wrangler.toml` `[[d1_databases]].database_id`
- `vectorize_index_name` → `wrangler.toml` `[[vectorize]].index_name`
- `etl_queue_name` / `etl_dlq_name` → `wrangler.toml` `[[queues.producers]].queue`
- `rate_limit_kv_namespace_id` → backend rate limiting binding