output "kubernetes_cluster_id" {
  value     = azurerm_kubernetes_cluster.main.id
  sensitive = false
}

output "kubernetes_cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "postgres_fqdn" {
  value     = azurerm_postgresql_flexible_server.main.fqdn
  sensitive = true
}

output "redis_hostname" {
  value     = azurerm_redis_cache.main.hostname
  sensitive = true
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "resource_group_name" {
  value = azurerm_resource_group.main.name
}
