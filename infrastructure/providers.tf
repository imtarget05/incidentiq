# IncidentIQ — Terraform: Cloudflare provider.
#
# The provider is configured with a scoped API token only; the account id is
# NEVER hardcoded here — every resource takes `var.cloudflare_account_id`,
# supplied per environment via environments/*.tfvars (or CLOUDFLARE_ACCOUNT_ID).
terraform {
  required_version = ">= 1.5"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
  # account_id intentionally omitted: data-plane resources below pass
  # var.cloudflare_account_id explicitly.
}
