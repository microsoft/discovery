# -----------------------------------------------------------------------------
# roles.tf   [PROVIDER: azurerm]
#
# Three role assignments against the workspace UAMI, matching ../discovery.bicep.
#
# Why AzureRM: azurerm_role_assignment is the right tool; azapi_resource
# would just wrap Microsoft.Authorization/roleAssignments with less validation.
#
# Discovery Platform Contributor is a Discovery-owned built-in role. Its
# display name is subject to rebrand, so we pin the GUID exactly as the
# Bicep template does. The other two (Storage Blob Data Contributor and
# AcrPull) are standard built-ins.
#
# Every assignment has explicit depends_on -> UAMI to avoid the classic
# "PrincipalNotFoundError" race on first apply, since Terraform's implicit
# dependency graph does not know about AAD replication lag.
# -----------------------------------------------------------------------------

locals {
  role_id_storage_blob_data_contributor  = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
  role_id_discovery_platform_contributor = "01288891-85ee-45a7-b367-9db3b752fc65"
  role_id_acr_pull                       = "7f951dda-4ed3-4680-a7ca-43fe172d538d"

  subscription_id_scope = "/subscriptions/${data.azurerm_client_config.current.subscription_id}"
}

data "azurerm_client_config" "current" {}

# Storage Blob Data Contributor -> UAMI, scoped to the storage account.
resource "azurerm_role_assignment" "storage_blob_data_contributor" {
  scope              = azurerm_storage_account.outputs.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_storage_blob_data_contributor}"
  principal_id       = azurerm_user_assigned_identity.workspace.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workspace]
}

# Discovery Platform Contributor -> UAMI, scoped to the resource group.
resource "azurerm_role_assignment" "discovery_platform_contributor" {
  scope              = data.azurerm_resource_group.rg.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_discovery_platform_contributor}"
  principal_id       = azurerm_user_assigned_identity.workspace.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workspace]
}

# AcrPull -> UAMI, scoped to the resource group. Currently a placeholder for
# any future ACR added to this RG (Discovery does not create one for us).
resource "azurerm_role_assignment" "acr_pull" {
  scope              = data.azurerm_resource_group.rg.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_acr_pull}"
  principal_id       = azurerm_user_assigned_identity.workspace.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workspace]
}
