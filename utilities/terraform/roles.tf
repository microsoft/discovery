# -----------------------------------------------------------------------------
# roles.tf   [PROVIDER: azurerm]
#
# Seven least-privilege role assignments across the four UAMIs, matching the
# per-identity split in ../discovery.bicep:
#   * workspace -> Discovery Platform Contributor (RG) + Storage Blob Data
#     Contributor (storage account)
#   * cluster   -> Network Contributor (AKS subnet only)
#   * kubelet   -> Managed Identity Operator (cluster identity) + AcrPull (RG) +
#     Storage Blob Data Contributor (storage account)
#   * workload  -> Storage Blob Data Contributor (storage account) only
#
# Why AzureRM: azurerm_role_assignment is the right tool; azapi_resource
# would just wrap Microsoft.Authorization/roleAssignments with less validation.
#
# Discovery Platform Contributor is a Discovery-owned built-in role. Its
# display name is subject to rebrand, so we pin the GUID exactly as the Bicep
# template does. The rest (Storage Blob Data Contributor, AcrPull, Network
# Contributor, Managed Identity Operator) are standard built-ins.
#
# Every assignment has explicit depends_on -> UAMI to avoid the classic
# "PrincipalNotFoundError" race on first apply, since Terraform's implicit
# dependency graph does not know about AAD replication lag.
# -----------------------------------------------------------------------------

locals {
  role_id_storage_blob_data_contributor  = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
  role_id_discovery_platform_contributor = "01288891-85ee-45a7-b367-9db3b752fc65"
  role_id_acr_pull                       = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
  role_id_network_contributor            = "4d97b98b-1d4f-4787-a291-c67834d212e7"
  role_id_managed_identity_operator      = "f1a07417-d97a-45cb-824c-7a7467783830"

  subscription_id_scope = "/subscriptions/${data.azurerm_client_config.current.subscription_id}"
}

data "azurerm_client_config" "current" {}

# --- Workspace identity ------------------------------------------------------

# Discovery Platform Contributor -> workspace UAMI, scoped to the resource group.
resource "azurerm_role_assignment" "workspace_discovery_platform_contributor" {
  scope              = data.azurerm_resource_group.rg.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_discovery_platform_contributor}"
  principal_id       = azurerm_user_assigned_identity.workspace.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workspace]
}

# Storage Blob Data Contributor -> workspace UAMI, scoped to the storage account.
resource "azurerm_role_assignment" "workspace_storage_blob_data_contributor" {
  scope              = azurerm_storage_account.outputs.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_storage_blob_data_contributor}"
  principal_id       = azurerm_user_assigned_identity.workspace.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workspace]
}

# --- Cluster identity (AKS control plane) ------------------------------------

# Network Contributor -> cluster UAMI, scoped to the AKS subnet only.
resource "azurerm_role_assignment" "cluster_network_contributor" {
  scope              = azurerm_subnet.aks.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_network_contributor}"
  principal_id       = azurerm_user_assigned_identity.cluster.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.cluster]
}

# --- Kubelet identity (node level) -------------------------------------------

# Managed Identity Operator -> kubelet UAMI, scoped to the cluster identity.
resource "azurerm_role_assignment" "kubelet_managed_identity_operator" {
  scope              = azurerm_user_assigned_identity.cluster.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_managed_identity_operator}"
  principal_id       = azurerm_user_assigned_identity.kubelet.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [
    azurerm_user_assigned_identity.kubelet,
    azurerm_user_assigned_identity.cluster,
  ]
}

# AcrPull -> kubelet UAMI, scoped to the resource group. Placeholder for any
# future ACR added to this RG (Discovery does not create one for us).
resource "azurerm_role_assignment" "kubelet_acr_pull" {
  scope              = data.azurerm_resource_group.rg.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_acr_pull}"
  principal_id       = azurerm_user_assigned_identity.kubelet.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.kubelet]
}

# Storage Blob Data Contributor -> kubelet UAMI, scoped to the storage account.
resource "azurerm_role_assignment" "kubelet_storage_blob_data_contributor" {
  scope              = azurerm_storage_account.outputs.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_storage_blob_data_contributor}"
  principal_id       = azurerm_user_assigned_identity.kubelet.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.kubelet]
}

# --- Workload identity (agent/tool federated access) -------------------------

# Storage Blob Data Contributor -> workload UAMI, scoped to the storage account.
# Minimally privileged: only the data-plane access agent tool execution needs.
resource "azurerm_role_assignment" "workload_storage_blob_data_contributor" {
  scope              = azurerm_storage_account.outputs.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_storage_blob_data_contributor}"
  principal_id       = azurerm_user_assigned_identity.workload.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workload]
}
