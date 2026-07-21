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
# isolationScope: each UAMI sets `isolation_scope = "Regional"` to harden the
# identity -- a Regional identity can only be assigned to source resources in the
# same region, which shrinks the blast radius if it is ever compromised and
# contains identity-plane failures to one region. All our source resources live
# in var.location, so Regional is a clean fit. (The azurerm provider exposes
# isolation_scope natively; do NOT also patch it via azapi_update_resource or the
# two providers fight and each plan flips the value.) See:
# https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/managed-identities-isolation-scope
# -----------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "workspace" {
  name                = local.managed_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  isolation_scope     = "Regional"
}

resource "azurerm_user_assigned_identity" "cluster" {
  name                = local.cluster_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  isolation_scope     = "Regional"
}

resource "azurerm_user_assigned_identity" "kubelet" {
  name                = local.kubelet_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  isolation_scope     = "Regional"
}

resource "azurerm_user_assigned_identity" "workload" {
  name                = local.workload_identity_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  isolation_scope     = "Regional"
}
