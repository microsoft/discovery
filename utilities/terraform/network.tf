# -----------------------------------------------------------------------------
# network.tf   [PROVIDER: azurerm]
#
# One VNet, five subnets. Two of the subnets (workspace, agent) are delegated
# to Microsoft.App/environments so Discovery can attach Container Apps
# environments into them.
#
# Why AzureRM: virtual networks, subnets, and subnet delegations are all
# stable AzureRM resources. No reason to touch azapi here.
#
# Style note: we use standalone azurerm_subnet blocks instead of inline
# `subnet {}` blocks on azurerm_virtual_network. Mixing the two styles is a
# common source of drift; standalone is the AzureRM-recommended pattern.
#
# `default_outbound_access_enabled = false` is set explicitly on every
# subnet. The AzureRM provider defaults it to `true`, but the Discovery RP
# (via its AKS supercomputer) configures the subnets with default outbound
# disabled -- Azure's newer secure posture. Declaring `false` here keeps
# our stated intent aligned with what the RP wants, avoiding perpetual
# `plan` drift.
# -----------------------------------------------------------------------------

resource "azurerm_virtual_network" "this" {
  name                = local.vnet_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  address_space       = [var.vnet_address_prefix]
}

resource "azurerm_subnet" "supercomputer_nodepool" {
  name                            = "supercomputerNodepoolSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [var.supercomputer_nodepool_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "aks" {
  name                            = "aksSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [var.aks_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "workspace" {
  name                            = "workspaceSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.this.name
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
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [var.private_endpoint_subnet_prefix]
  default_outbound_access_enabled = false
}

resource "azurerm_subnet" "agent" {
  name                            = "agentSubnet"
  resource_group_name             = data.azurerm_resource_group.rg.name
  virtual_network_name            = azurerm_virtual_network.this.name
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
