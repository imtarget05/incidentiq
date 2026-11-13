terraform {
  backend "azurerm" {
    resource_group_name  = "tfstate-incidentiq"
    storage_account_name = "tfstateincidentiq"
    container_name       = "tfstate"
    key                  = "incidentiq.terraform.state"
  }
}
