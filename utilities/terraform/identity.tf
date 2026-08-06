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
# The Supercomputer MRG may be in a different region from its Discovery
# control-plane resource. Do not set Regional isolation_scope because it would
# prevent those identities from being assigned across that intended boundary.
# -----------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "workspace" {
  name                = local.managed_identity_name
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "cluster" {
  name                = local.cluster_identity_name
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "kubelet" {
  name                = local.kubelet_identity_name
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "workload" {
  name                = local.workload_identity_name
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}
