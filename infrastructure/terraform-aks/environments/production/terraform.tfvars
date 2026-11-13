resource_group_name = "rg-incidentiq-prod"
location            = "Southeast Asia"
dns_prefix          = "incidentiq-prod"
vm_size             = "Standard_D4s_v3"
pg_admin_user       = "incidentiq"
pg_admin_password   = "CHANGE_ME_PROD"
pg_sku              = "Standard_B2ms"
pg_storage_mb       = 65536
pg_backup_retention_days = 30
common_tags = {
  project   = "incidentiq"
  owner     = "platform"
  environment = "production"
}
storage_account_name = "incidentiqprodstorage"
