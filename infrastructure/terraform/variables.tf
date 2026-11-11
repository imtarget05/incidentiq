variable "cloudflare_api_token" {
  description = "Cloudflare API token with Workers, D1, Vectorize and Queue permissions."
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID."
  type        = string
}

variable "environment" {
  description = "Deployment environment: preview or production."
  type        = string
  validation {
    condition     = contains(["preview", "production"], var.environment)
    error_message = "environment must be 'preview' or 'production'."
  }
}

variable "d1_database_name" {
  description = "Name of the D1 database."
  type        = string
}

variable "vectorize_index_name" {
  description = "Name of the Vectorize index."
  type        = string
}

variable "etl_queue_name" {
  description = "Name of the ETL main queue."
  type        = string
}

variable "etl_dlq_name" {
  description = "Name of the ETL dead-letter queue."
  type        = string
}

variable "kv_rate_limit_namespace" {
  description = "Name of the KV namespace for auxiliary rate-limit data."
  type        = string
  default     = ""
}
