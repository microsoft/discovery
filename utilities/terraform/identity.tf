# -----------------------------------------------------------------------------
# identity.tf   [PROVIDER: azurerm + azapi]
#
# Four user-assigned managed identities implementing the same least-privilege
# split as ../discovery.bicep, so each Discovery identity slot holds only the
# roles it needs (see roles.tf):
#   * workspace -> Workspace control + data plane (workspaceIdentity)
#   * cluster   -> Supercomputer AKS control plane (clusterIdentity)
#   * kubelet   -> node-level image pulls + startup data access (kubeletIdentity)
#   * workload  -> agent/tool federated data access (workloadIdentities)
#
# Why AzureRM for the identities: azurerm_user_assigned_identity is stable and
# covers everything we need for the base resource.
#
# isolationScope: the Bicep sets `isolationScope: 'Regional'` on every UAMI
# (Managed Identity API 2024-11-30) to harden the identities -- a Regional
# identity can only be assigned to source resources in the same region, which
# shrinks the blast radius if it is ever compromised and contains identity-plane
# failures to one region. AzureRM 4.x does not expose isolationScope, so we patch
# it on with an azapi_update_resource per identity (all our source resources live
# in var.location, so Regional is a clean fit). See:
# https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/managed-identities-isolation-scope
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

# -----------------------------------------------------------------------------
# isolationScope = "Regional" patches (azapi)
#
# azurerm_user_assigned_identity cannot set isolationScope, so we PATCH each
# identity to Regional via ARM. Pinned to 2024-11-30, the API version that
# introduced the property (matching ../discovery.bicep).
# -----------------------------------------------------------------------------
resource "azapi_update_resource" "workspace_isolation" {
  type        = "Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30"
  resource_id = azurerm_user_assigned_identity.workspace.id
  body = {
    properties = {
      isolationScope = "Regional"
    }
  }
}

resource "azapi_update_resource" "cluster_isolation" {
  type        = "Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30"
  resource_id = azurerm_user_assigned_identity.cluster.id
  body = {
    properties = {
      isolationScope = "Regional"
    }
  }
}

resource "azapi_update_resource" "kubelet_isolation" {
  type        = "Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30"
  resource_id = azurerm_user_assigned_identity.kubelet.id
  body = {
    properties = {
      isolationScope = "Regional"
    }
  }
}

resource "azapi_update_resource" "workload_isolation" {
  type        = "Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30"
  resource_id = azurerm_user_assigned_identity.workload.id
  body = {
    properties = {
      isolationScope = "Regional"
    }
  }
}
