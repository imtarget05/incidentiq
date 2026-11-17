terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# ── Resource Group ────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.common_tags
}

# ── Log Analytics (AKS diagnostics) ───────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-incidentiq-${random_string.suffix.result}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.common_tags
}

# ── VNet + Subnet cho AKS ─────────────────────────────────────────────────────
resource "azurerm_virtual_network" "main" {
  name                = "vnet-incidentiq-${random_string.suffix.result}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = ["10.0.0.0/16"]
  tags                = var.common_tags
}

resource "azurerm_subnet" "aks" {
  name                 = "aks-subnet"
  virtual_network_name = azurerm_virtual_network.main.name
  resource_group_name  = azurerm_resource_group.main.name
  address_prefixes     = ["10.0.1.0/24"]
  service_endpoints    = ["Microsoft.Storage"]
}

# ── AKS Cluster (3 node, 1 replica/service để fit node capacity) ─────────────
resource "azurerm_kubernetes_cluster" "main" {
  name                              = "aks-incidentiq-${random_string.suffix.result}"
  location                          = var.location
  resource_group_name               = azurerm_resource_group.main.name
  dns_prefix                        = var.dns_prefix
  role_based_access_control_enabled = true

  api_server_access_profile {
    authorized_ip_ranges = var.aks_api_authorized_ip_ranges
  }

  default_node_pool {
    name                = "agentpool"
    vm_size             = var.vm_size
    node_count          = 3
    vnet_subnet_id      = azurerm_subnet.aks.id
    enable_auto_scaling = false
    max_pods            = 30
  }

  network_profile {
    network_plugin    = "azure"
    network_policy    = "azure"
    load_balancer_sku = "standard"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.common_tags
}

# ── Azure Database for PostgreSQL Flexible Server ─────────────────────────────
resource "azurerm_postgresql_flexible_server" "main" {
  name                  = "pg-incidentiq-${random_string.suffix.result}"
  location              = var.location
  resource_group_name   = azurerm_resource_group.main.name
  administrator_login   = var.pg_admin_user
  sku_name              = var.pg_sku
  storage_mb            = var.pg_storage_mb
  backup_retention_days = var.pg_backup_retention_days
  tags                  = var.common_tags
}

# ── Azure Cache for Redis ─────────────────────────────────────────────────────
resource "azurerm_redis_cache" "main" {
  name                 = "redis-incidentiq-${random_string.suffix.result}"
  location             = var.location
  resource_group_name  = azurerm_resource_group.main.name
  capacity             = 1
  family               = "C"
  sku_name             = "Basic"
  non_ssl_port_enabled = false
  minimum_tls_version  = "1.2"
  tags                 = var.common_tags
}

# ── Azure Storage Account (object storage, backup artifacts) ──────────────────
resource "azurerm_storage_account" "main" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  network_rules {
    default_action             = "Deny"
    virtual_network_subnet_ids = [azurerm_subnet.aks.id]
    bypass                     = ["AzureServices"]
  }
  tags = var.common_tags
}

resource "azurerm_storage_container" "backups" {
  name                  = "backups"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}
