# IncidentIQ — Terraform: outputs.
#
# These map 1:1 into GitHub Actions repository variables (settings -> secrets
# and variables -> Actions -> Variables), e.g. for preview:
#   PREVIEW_D1_DATABASE_ID   <- database_id
#   PREVIEW_VECTORS_INDEX    <- vectorize_index_name
#   PREVIEW_ETL_QUEUE_ID     <- etl_queue_id
#   PREVIEW_ETL_DLQ_ID       <- etl_dlq_id
#   PREVIEW_CONFIG_KV_ID     <- kv_namespace_id
# and the PROD_* equivalents from the production apply.

output "database_id" {
  description = "D1 database id (uuid) — goes into [[d1_databases]].database_id."
  value       = cloudflare_d1_database.main.id
}

output "database_name" {
  description = "D1 database name."
  value       = cloudflare_d1_database.main.name
}

output "vectorize_index_name" {
  description = "Vectorize index name — goes into [[vectorize]].index_name."
  value       = cloudflare_vectorize_index.main.name
}

output "etl_queue_id" {
  description = "ETL queue id (uuid) for Queues REST consumers / GH Actions vars."
  value       = cloudflare_queue.etl.id
}

output "etl_queue_name" {
  description = "ETL queue name — goes into [[queues.producers]].queue."
  value       = cloudflare_queue.etl.name
}

output "etl_dlq_id" {
  description = "ETL dead-letter queue id (uuid)."
  value       = cloudflare_queue.etl_dlq.id
}

output "etl_dlq_name" {
  description = "ETL dead-letter queue name — goes into dead_letter_queue."
  value       = cloudflare_queue.etl_dlq.name
}

output "kv_namespace_id" {
  description = "Workers KV namespace id for the future config cache."
  value       = cloudflare_workers_kv_namespace.config.id
}
