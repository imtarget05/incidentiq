resource_group_name = "rg-incidentiq-preview"
location            = "Southeast Asia"
dns_prefix          = "incidentiq-preview"
vm_size             = "Standard_D2s_v3"
pg_admin_user       = "incidentiq"
pg_admin_password   = "CHANGE_ME_PREVIEW"
pg_sku              = "Standard_B1ms"
pg_storage_mb       = 32768
pg_backup_retention_days = 7
common_tags = {
  project   = "incidentiq"
  owner     = "platform"
  environment = "preview"
}
storage_account_name = "incidentiqpreviewstorage"
