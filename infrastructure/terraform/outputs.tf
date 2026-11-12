output "d1_database_id" {
  description = "D1 database ID — paste into wrangler.toml database_id."
  value       = cloudflare_d1_database.main.id
}

output "vectorize_index_name" {
  description = "Vectorize index name managed with Wrangler; matches wrangler.toml index_name."
  value       = var.vectorize_index_name
}

output "etl_queue_id" {
  description = "ETL queue ID."
  value       = cloudflare_queue.etl_queue.id
}

output "etl_dlq_id" {
  description = "ETL dead-letter queue ID."
  value       = cloudflare_queue.etl_dlq.id
}

output "kv_rate_limit_id" {
  description = "KV namespace ID for rate-limit data."
  value       = cloudflare_workers_kv_namespace.rate_limit.id
}
