# -----------------------------------------------------------------------------
# identity.tf   [PROVIDER: azurerm]
#
# Four user-assigned managed identities implementing the same least-privilege
# split as ../discovery.bicep, so each Discovery identity slot holds only the
# roles it needs (see roles.tf):
#   * workspace -> Workspace control + data plane (workspaceIdentity)
#   * cluster   -> Supercomputer AKS control plane (clusterIdentity)
#   * kubelet   -> node-level image pulls + startup data access (kubeletIdentity)
#   * workload  -> agent/tool federated data access (workloadIdentities)
#
# Why AzureRM: azurerm_user_assigned_identity is stable and covers everything
# we need for Phase 0.
#
# Known gap: the Bicep sets `isolationScope: 'Regional'` on the UAMI (added in
# API 2024-11-30). AzureRM 4.x does not yet expose isolationScope. Two ways to
# match Bicep parity if your policy requires it:
#   1. Add an azapi_update_resource block that patches the same UAMI:
#        resource "azapi_update_resource" "uami_regional" {
#          type        = "Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30"
#          resource_id = azurerm_user_assigned_identity.workspace.id
#          body = { properties = { isolationScope = "Regional" } }
#        }
#   2. Replace this whole file with a single azapi_resource targeting the
#      same ARM type.
# For a first apply, the default isolation is fine.
# -----------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "workspace" {
  name                = local.managed_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "cluster" {
  name                = local.cluster_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "kubelet" {
  name                = local.kubelet_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "workload" {
  name                = local.workload_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
}
