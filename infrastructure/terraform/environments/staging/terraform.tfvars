# Staging environment Terraform variables
# Apply: terraform -chdir=../../ apply -var-file=environments/staging/terraform.tfvars

environment             = "staging"
d1_database_name        = "incidentiq-staging"
vectorize_index_name    = "ai-knowledge-vectors-staging"
etl_queue_name          = "etl-queue-staging"
etl_dlq_name            = "etl-dlq-staging"
kv_rate_limit_namespace = "staging-incidentiq-rate-limit"

# Sensitive vars — set via TF_VAR_cloudflare_api_token / TF_VAR_cloudflare_account_id
