# IncidentIQ — Terraform: DATA-PLANE resources only.
#
# SCOPE (recommended split — see README.md): Terraform provisions the durable
# data plane (D1, Vectorize, Queues, KV). The three worker scripts
# (ai-knowledge-platform, ai-knowledge-etl, and the MCP worker) are deployed by
# `wrangler deploy` in the GitHub Actions workflows (deploy-preview.yml /
# deploy-prod.yml), NOT by Terraform. Provisioning python_workers scripts via
# `cloudflare_worker_script` is invasive and would fight wrangler's ownership
# of the script bundles; wrangler keeps validating and deploying them.
#
# The resource names mirror the bindings in wrangler.toml:
#   [[d1_databases]] DB          -> cloudflare_d1_database.main
#   [[vectorize]] VECTORIZE_INDEX -> cloudflare_vectorize_index.main (1024-dim cosine)
#   [[queues.producers]] ETL_QUEUE -> cloudflare_queue.etl
#   [[queues.producers]] ETL_DLQ   -> cloudflare_queue.etl_dlq

resource "cloudflare_d1_database" "main" {
  account_id = var.cloudflare_account_id
  name       = var.d1_database_name
}

resource "cloudflare_vectorize_index" "main" {
  account_id = var.cloudflare_account_id
  name       = var.vectorize_index_name
  dimensions = 1024
  type       = "cosine"
}

resource "cloudflare_queue" "etl" {
  account_id = var.cloudflare_account_id
  name       = var.etl_queue_name
}

resource "cloudflare_queue" "etl_dlq" {
  account_id = var.cloudflare_account_id
  name       = var.etl_dlq_name
}

# Reserved for a future configuration cache (not yet bound in wrangler.toml —
# when needed, add a [[kv_namespaces]] entry with the namespace id from
# `terraform output kv_namespace_id`; documented in README.md).
resource "cloudflare_workers_kv_namespace" "config" {
  account_id = var.cloudflare_account_id
  title      = var.kv_namespace_name
}
