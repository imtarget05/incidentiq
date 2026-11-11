# IncidentIQ — Terraform: input variables.
#
# Secrets are supplied via TF_VAR_cloudflare_api_token or CLOUDFLARE_API_TOKEN;
# never commit tfvars containing the token.

variable "cloudflare_api_token" {
  description = "Cloudflare API token scoped to D1/Vectorize/Queues/KV administration."
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account id the data-plane resources belong to."
  type        = string
}

variable "environment" {
  description = "Environment label (preview | production)."
  type        = string
}

variable "worker_name" {
  description = "Informational: name of the API worker script (deployed by wrangler, not Terraform)."
  type        = string
  default     = "ai-knowledge-platform"
}

variable "d1_database_name" {
  description = "Name of the D1 database backing the platform."
  type        = string
}

variable "vectorize_index_name" {
  description = "Name of the Vectorize index (must be a 1024-dim cosine index)."
  type        = string
}

variable "etl_queue_name" {
  description = "Name of the ETL work queue."
  type        = string
}

variable "etl_dlq_name" {
  description = "Name of the ETL dead-letter queue."
  type        = string
}

variable "kv_namespace_name" {
  description = "Workers KV namespace reserved for a future config cache."
  type        = string
}
