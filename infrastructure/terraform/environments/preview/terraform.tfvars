# Preview environment Terraform variables
# Apply: terraform -chdir=../../ apply -var-file=environments/preview/terraform.tfvars

environment             = "preview"
d1_database_name        = "incidentiq-preview"
vectorize_index_name    = "ai-knowledge-vectors-preview"
etl_queue_name          = "etl-queue-preview"
etl_dlq_name            = "etl-dlq-preview"
kv_rate_limit_namespace = "preview-incidentiq-rate-limit"

# Sensitive vars — set via TF_VAR_cloudflare_api_token / TF_VAR_cloudflare_account_id
# or pass on the command line:
#   terraform apply -var="cloudflare_api_token=..." -var="cloudflare_account_id=..."
