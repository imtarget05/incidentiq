# Production environment Terraform variables
# Apply: terraform -chdir=../../ apply -var-file=environments/production/terraform.tfvars

environment             = "production"
d1_database_name        = "ai-knowledge-platform"
vectorize_index_name    = "ai-knowledge-vectors"
etl_queue_name          = "etl-queue"
etl_dlq_name            = "etl-dlq"
kv_rate_limit_namespace = "prod-incidentiq-rate-limit"

# Sensitive vars — set via TF_VAR_cloudflare_api_token / TF_VAR_cloudflare_account_id
# or pass on the command line:
#   terraform apply -var="cloudflare_api_token=..." -var="cloudflare_account_id=..."
