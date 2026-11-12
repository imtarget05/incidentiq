# ── D1 Database ──────────────────────────────────────────────────────────────
resource "cloudflare_d1_database" "main" {
  account_id = var.cloudflare_account_id
  name       = var.d1_database_name
}

# ── Queues ────────────────────────────────────────────────────────────────────
resource "cloudflare_queue" "etl_queue" {
  account_id = var.cloudflare_account_id
  queue_name = var.etl_queue_name

  settings = {
    # Delivery delay (seconds): 0 for immediate processing.
    delivery_delay = 0
    # Messages not acked within 60 s are retried. Max retention is 86400s (24h).
    message_retention_period = 86400
  }
}

resource "cloudflare_queue" "etl_dlq" {
  account_id = var.cloudflare_account_id
  queue_name = var.etl_dlq_name

  settings = {
    delivery_delay           = 0
    message_retention_period = 86400 # Max retention 24h for DLQ inspection
  }
}

# ── KV Namespace (auxiliary — rate-limit overflow, feature flags) ─────────────
resource "cloudflare_workers_kv_namespace" "rate_limit" {
  account_id = var.cloudflare_account_id
  title      = coalesce(var.kv_rate_limit_namespace, "${var.environment}-incidentiq-rate-limit")
}
