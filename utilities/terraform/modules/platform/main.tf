# -----------------------------------------------------------------------------
# modules/platform -- main
#
# All non-Discovery prerequisites plus the RG-level Discovery storageContainer
# binding. This is the single definition of the platform substrate; the
# end-to-end root and the staged examples both consume it.
# -----------------------------------------------------------------------------

resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
  numeric = true
}

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  suffix = coalesce(var.name_suffix, random_string.suffix.result)

  vnet_name               = "vnet-${local.suffix}"
  supercomputer_vnet_name = "vnet-sc-${local.suffix}"
  storage_account_name    = "stg${local.suffix}"
  storage_container_name  = "stc-${local.suffix}"

  subscription_id_scope = "/subscriptions/${data.azurerm_client_config.current.subscription_id}"

  role_id_storage_blob_data_contributor  = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
  role_id_discovery_platform_contributor = "01288891-85ee-45a7-b367-9db3b752fc65"
  role_id_acr_pull                       = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
  role_id_network_contributor            = "4d97b98b-1d4f-4787-a291-c67834d212e7"
  role_id_managed_identity_operator      = "f1a07417-d97a-45cb-824c-7a7467783830"
}

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------
resource "azurerm_virtual_network" "workspace" {
  name                = local.vnet_name
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
  address_space       = [var.vnet_address_prefix]
  tags                = var.common_tags
}

resource "azurerm_virtual_network" "supercomputer" {
  name                = local.supercomputer_vnet_name
  location            = var.supercomputer_infrastructure_location
  resource_group_name = data.azurerm_resource_group.rg.name
  address_space       = [var.supercomputer_vnet_address_prefix]
  tags                = var.common_tags
}

resource "azurerm_virtual_network_peering" "workspace_to_supercomputer" {
  name                      = "workspace-to-supercomputer"
  resource_group_name       = data.azurerm_resource_group.rg.name
  virtual_network_name      = azurerm_virtual_network.workspace.name
  remote_virtual_network_id = azurerm_virtual_network.supercomputer.id
}

resource "azurerm_virtual_network_peering" "supercomputer_to_workspace" {
  name                      = "supercomputer-to-workspace"
  resource_group_name       = data.azurerm_resource_group.rg.name
  virtual_network_name      = azurerm_virtual_network.supercomputer.name
  remote_virtual_network_id = azurerm_virtual_network.workspace.id
}

resource "azurerm_subnet" "aks" {
  name                            = "aksSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.supercomputer.name
  address_prefixes                = [var.aks_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "supercomputer_nodepool" {
  name                            = "supercomputerNodepoolSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.supercomputer.name
  address_prefixes                = [var.supercomputer_nodepool_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "workspace" {
  name                            = "workspaceSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.workspace.name
  address_prefixes                = [var.workspace_subnet_prefix]
  default_outbound_access_enabled = false

  delegation {
    name = "Microsoft.App.environments"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoint" {
  name                            = "privateEndpointSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.workspace.name
  address_prefixes                = [var.private_endpoint_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "agent" {
  name                            = "agentSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.workspace.name
  address_prefixes                = [var.agent_subnet_prefix]
  default_outbound_access_enabled = false

  delegation {
    name = "Microsoft.App.environments"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "search" {
  name                            = "searchSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.workspace.name
  address_prefixes                = [var.search_subnet_prefix]
  default_outbound_access_enabled = false

  delegation {
    name = "Microsoft.App.environments"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# -----------------------------------------------------------------------------
# Identities (four-identity least-privilege split)
# -----------------------------------------------------------------------------
resource "azurerm_user_assigned_identity" "workspace" {
  name                = "uami-ws-${local.suffix}"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "cluster" {
  name                = "uami-cluster-${local.suffix}"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "kubelet" {
  name                = "uami-kubelet-${local.suffix}"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_user_assigned_identity" "workload" {
  name                = "uami-workload-${local.suffix}"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.rg.name
}

# -----------------------------------------------------------------------------
# Storage account + blob private endpoint + container
# -----------------------------------------------------------------------------
resource "azurerm_storage_account" "outputs" {
  name                = local.storage_account_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  access_tier              = "Hot"

  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  public_network_access_enabled   = false

  tags = var.common_tags

  blob_properties {
    cors_rule {
      allowed_origins = [
        "https://studio.discovery.microsoft.com",
        "https://*.vscode-cdn.net",
        "https://vscode.dev",
      ]
      allowed_methods    = ["GET", "HEAD", "DELETE", "PUT"]
      allowed_headers    = ["*"]
      exposed_headers    = ["*"]
      max_age_in_seconds = 200
    }
  }
}

resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                  = "link-blob-${local.storage_account_name}"
  resource_group_name   = data.azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.workspace.id
  registration_enabled  = false
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob_supercomputer" {
  name                  = "link-blob-${local.supercomputer_vnet_name}"
  resource_group_name   = data.azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.supercomputer.id
  registration_enabled  = false
}

resource "azurerm_private_endpoint" "blob" {
  name                = "pe-blob-${local.storage_account_name}"
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  subnet_id           = azurerm_subnet.private_endpoint.id

  private_service_connection {
    name                           = "pe-blob-conn"
    private_connection_resource_id = azurerm_storage_account.outputs.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob.id]
  }
}

resource "azapi_resource" "outputs_container" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = var.blob_container_name
  parent_id = "${azurerm_storage_account.outputs.id}/blobServices/default"

  body = {
    properties = {}
  }

  depends_on = [azurerm_storage_account.outputs]
}

# -----------------------------------------------------------------------------
# Role assignments (seven, least-privilege)
# -----------------------------------------------------------------------------
resource "azurerm_role_assignment" "workspace_discovery_platform_contributor" {
  scope              = data.azurerm_resource_group.rg.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_discovery_platform_contributor}"
  principal_id       = azurerm_user_assigned_identity.workspace.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workspace]
}

resource "azurerm_role_assignment" "workspace_storage_blob_data_contributor" {
  scope              = azurerm_storage_account.outputs.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_storage_blob_data_contributor}"
  principal_id       = azurerm_user_assigned_identity.workspace.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workspace]
}

resource "azurerm_role_assignment" "cluster_network_contributor" {
  scope              = azurerm_subnet.aks.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_network_contributor}"
  principal_id       = azurerm_user_assigned_identity.cluster.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.cluster]
}

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

resource "azurerm_role_assignment" "kubelet_acr_pull" {
  scope              = data.azurerm_resource_group.rg.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_acr_pull}"
  principal_id       = azurerm_user_assigned_identity.kubelet.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.kubelet]
}

resource "azurerm_role_assignment" "kubelet_storage_blob_data_contributor" {
  scope              = azurerm_storage_account.outputs.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_storage_blob_data_contributor}"
  principal_id       = azurerm_user_assigned_identity.kubelet.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.kubelet]
}

resource "azurerm_role_assignment" "workload_storage_blob_data_contributor" {
  scope              = azurerm_storage_account.outputs.id
  role_definition_id = "${local.subscription_id_scope}/providers/Microsoft.Authorization/roleDefinitions/${local.role_id_storage_blob_data_contributor}"
  principal_id       = azurerm_user_assigned_identity.workload.principal_id
  principal_type     = "ServicePrincipal"

  depends_on = [azurerm_user_assigned_identity.workload]
}

# -----------------------------------------------------------------------------
# Discovery StorageContainer binding (RG-level control-plane projection)
#
# No control-plane module exists for Microsoft.Discovery/storageContainers, so
# it lives here with the storage prerequisites it depends on.
# -----------------------------------------------------------------------------
resource "azapi_resource" "discovery_storage_container" {
  type      = "Microsoft.Discovery/storageContainers@2026-06-01"
  name      = local.storage_container_name
  location  = var.location
  parent_id = data.azurerm_resource_group.rg.id
  tags      = var.common_tags

  body = {
    properties = {
      storageStore = {
        kind             = "AzureStorageBlob"
        storageAccountId = azurerm_storage_account.outputs.id
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.workspace_storage_blob_data_contributor,
    azapi_resource.outputs_container,
  ]
}
