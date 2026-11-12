# IncidentIQ Infrastructure

Cloudflare infrastructure uses the Terraform configuration in `infrastructure/terraform` (Cloudflare provider v5). Vectorize is managed with Wrangler because the installed provider has no Vectorize index resource.

## Resources managed

| Resource | Preview name | Production name |
|---|---|---|
| D1 database | `incidentiq-preview` | `ai-knowledge-platform` |
| Vectorize index (Wrangler) | `ai-knowledge-vectors-preview` | `ai-knowledge-vectors` |
| ETL queue | `etl-queue-preview` | `etl-queue` |
| ETL DLQ | `etl-dlq-preview` | `etl-dlq` |
| KV namespace | `preview-incidentiq-rate-limit` | `prod-incidentiq-rate-limit` |

## Prerequisites

1. [Install Terraform ≥ 1.9](https://developer.hashicorp.com/terraform/install)
2. Create a Cloudflare API token with:
   - Workers Scripts: Edit
   - Workers KV Storage: Edit
   - Workers Routes: Edit
   - D1: Edit
   - Vectorize: Edit
   - Queues: Edit

## Usage

### Preview environment

```bash
cd infrastructure/terraform
terraform init
terraform plan -var-file=environments/preview/terraform.tfvars \
  -var="cloudflare_api_token=$CF_PREVIEW_TOKEN" \
  -var="cloudflare_account_id=$CF_ACCOUNT_ID"
```

### Production environment

```bash
cd infrastructure/terraform
terraform init
terraform plan -var-file=environments/production/terraform.tfvars \
  -var="cloudflare_api_token=$CF_PROD_TOKEN" \
  -var="cloudflare_account_id=$CF_ACCOUNT_ID"
```

The production D1 database and ETL queues already exist in Cloudflare. Configure a durable Terraform state backend and import those resources before an `apply`; an empty state would try to create duplicate resources. Verify the Vectorize index separately with `wrangler vectorize list` (1024 dimensions, cosine metric). For a new environment, create its index with `wrangler vectorize create <name> --dimensions=1024 --metric=cosine` before deploying Workers.

## Disaster Recovery

### D1 Backup

Cloudflare D1 supports time-travel queries (point-in-time restore) for the last 30 days.
Run scheduled exports for long-term backup:

```bash
# Export production D1 to JSON (run from CI or cron)
wrangler d1 export ai-knowledge-platform --remote --output backups/d1-$(date +%Y%m%d).sql
```

Store exports in a Cloudflare R2 bucket or external object storage.

### Dead-Letter Queue Reprocessing

Messages in the DLQ (`etl-dlq`) represent documents that failed all ETL retries.
Reprocess them by pulling and re-enqueueing to `etl-queue`:

```bash
# View DLQ messages (using Cloudflare dashboard or REST API)
# Re-enqueue a failed document by ID:
wrangler queues send etl-queue '{"job":"etl.process","document_id":"<id>","tenant_id":"<tid>","version":1}'
```
