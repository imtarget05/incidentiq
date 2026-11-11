terraform {
  required_version = ">= 1.9"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }

  # Remote state — configure backend for your team.
  # Example: Terraform Cloud or S3-compatible.
  # backend "s3" {}
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
