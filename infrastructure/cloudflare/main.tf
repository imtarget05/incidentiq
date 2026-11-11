terraform {
  required_version = ">= 1.0"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

variable "account_id" {
  description = "Cloudflare Account ID"
  type        = string
}

variable "api_token" {
  description = "Cloudflare API Token"
  type        = string
  sensitive   = true
}

variable "environment" {
  description = "Deployment environment (preview or production)"
  type        = string
}

provider "cloudflare" {
  account_id = var.account_id
  api_token  = var.api_token
}

# ── D1 Database ──────────────────────────────────────────────────────────────

resource "cloudflare_d1_database" "incidentiq" {
  name = var.environment == "production"
    ? "ai-knowledge-platform"
    : "incidentiq-${var.environment}"
}

# ── Vectorize Index ─────────────────────────────────────────────────────────

resource "cloudflare_vectorize_index" "incidentiq" {
  name        = var.environment == "production"
    ? "ai-knowledge-vectors"
    : "incidentiq-${var.environment}-vectors"
  dimensions  = 1024
  metric      = "cosine"
  description = "Vector index for IncidentIQ document embeddings (${var.environment})"
}

# ── Cloudflare Queues ────────────────────────────────────────────────────────

resource "cloudflare_queues_queue" "etl_queue" {
  name = var.environment == "production"
    ? "etl-queue"
    : "incidentiq-${var.environment}-etl-queue"
}

resource "cloudflare_queues_queue" "etl_dlq" {
  name = var.environment == "production"
    ? "etl-dlq"
    : "incidentiq-${var.environment}-etl-dlq"
}

# ── KV Namespace (rate limiting, session) ────────────────────────────────────

resource "cloudflare_kv_namespace" "rate_limit" {
  title = var.environment == "production"
    ? "incidentiq-rate-limit"
    : "incidentiq-${var.environment}-rate-limit"
}

# ── Outputs ──────────────────────────────────────────────────────────────────

output "d1_database_id" {
  value = cloudflare_d1_database.incidentiq.id
  description = "D1 Database ID for wrangler.toml"
}

output "vectorize_index_name" {
  value = cloudflare_vectorize_index.incidentiq.name
  description = "Vectorize index name for wrangler.toml"
}

output "etl_queue_name" {
  value = cloudflare_queues_queue.etl_queue.name
  description = "ETL queue name for wrangler.toml"
}

output "etl_dlq_name" {
  value = cloudflare_queues_queue.etl_dlq.name
  description = "ETL DLQ name for wrangler.toml"
}

output "rate_limit_kv_namespace_id" {
  value = cloudflare_kv_namespace.rate_limit.id
  description = "KV namespace ID for rate limiting"
}