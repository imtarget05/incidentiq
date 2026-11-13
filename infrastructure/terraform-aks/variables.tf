variable "resource_group_name" {
  description = "Tên Azure Resource Group"
  type        = string
  default     = "rg-incidentiq"
}

variable "location" {
  description = "Vùng Azure"
  type        = string
  default     = "Southeast Asia"
}

variable "dns_prefix" {
  description = "DNS prefix cho AKS"
  type        = string
  default     = "incidentiq"
}

variable "vm_size" {
  description = "Kích thước VM node pool AKS"
  type        = string
  default     = "Standard_D2s_v3"
}

variable "common_tags" {
  description = "Tags gắn mọi tài nguyên"
  type        = map(string)
  default = {
    project   = "incidentiq"
    owner     = "platform"
    environment = "dev"
  }
}

variable "pg_admin_user" {
  description = "Admin user PostgreSQL"
  type        = string
  default     = "incidentiq"
}

variable "pg_admin_password" {
  description = "Mật khẩu admin PostgreSQL (set qua tfvars / secret, không hardcode)"
  type        = string
  sensitive   = true
}

variable "pg_sku" {
  description = "SKU PostgreSQL Flexible Server"
  type        = string
  default     = "Standard_B1ms"
}

variable "pg_storage_mb" {
  description = "Dung lượng lưu trữ PostgreSQL (MB)"
  type        = number
  default     = 32768
}

variable "pg_backup_retention_days" {
  description = "Thời gian lưu backup PostgreSQL (ngày)"
  type        = number
  default     = 7
}

variable "storage_account_name" {
  description = "Tên storage account (phải duy nhất toàn cầu Azure)"
  type        = string
}
