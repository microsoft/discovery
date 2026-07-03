# -----------------------------------------------------------------------------
# identity.tf   [PROVIDER: azurerm]
#
# One user-assigned managed identity used by:
#   * the Supercomputer (clusterIdentity, kubeletIdentity, workloadIdentities)
#   * the Workspace (workspaceIdentity)
#   * pods running in the Supercomputer's AKS cluster (via workload identity)
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
