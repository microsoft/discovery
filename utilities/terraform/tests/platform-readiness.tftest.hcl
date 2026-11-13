variables {
  resource_group_name                 = "rg-discovery-test"
  location                            = "uksouth"
  name_suffix                         = "uktst123"
  workspace_contributor_principal_ids = []
}

mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test"
      name     = "rg-discovery-test"
      location = "uksouth"
    }
  }

  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "00000000-0000-0000-0000-000000000001"
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Storage/storageAccounts/stgtest"
    }
  }

  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test"
    }
  }

  mock_resource "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/test"
    }
  }

  mock_resource "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net"
    }
  }

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test"
      principal_id = "00000000-0000-0000-0000-000000000006"
      client_id    = "00000000-0000-0000-0000-000000000007"
    }
  }

  mock_resource "azurerm_route_table" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/routeTables/rt-test"
    }
  }
}

run "same_region_bookshelf" {
  command = plan

  variables {
    resource_group_name = "rg-discovery-test"
    location            = "uksouth"
    enable_bookshelf    = true
  }

  assert {
    condition     = length(module.bookshelf) == 1
    error_message = "A same-region Bookshelf must remain supported."
  }
}

run "shared_cross_region_infrastructure" {
  command = plan

  variables {
    managed_resource_group_location = "eastus"
  }

  assert {
    condition = (
      module.platform.location == "uksouth" &&
      module.platform.infrastructure_location == "eastus" &&
      local.managed_resource_group_tags["discovery.overridemrgregion"] == "eastus"
    )
    error_message = "All platform and managed infrastructure must share the selected region without moving the control plane."
  }
}

run "shared_region_bookshelf" {
  command = plan

  variables {
    enable_bookshelf                = true
    managed_resource_group_location = "eastus"
  }

  assert {
    condition     = length(module.bookshelf) == 1 && module.platform.infrastructure_location == local.managed_resource_group_location
    error_message = "Bookshelf and its attached subnets must follow the common infrastructure region."
  }
}

run "reject_invalid_infrastructure_region" {
  command = plan

  variables {
    managed_resource_group_location = "West Europe"
  }

  expect_failures = [var.managed_resource_group_location]
}

run "default_load_balancer" {
  command = apply

  override_resource {
    target = module.supercomputer.azapi_resource.main
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Discovery/supercomputers/sc-test"
    }
  }

  override_resource {
    target = module.workspace.azapi_resource.main
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Discovery/workspaces/ws-test"
    }
  }

  assert {
    condition = (
      module.supercomputer.outbound_type == "LoadBalancer" &&
      module.supercomputer.management_subnet_id == null &&
      module.platform.workspace_vnet_id == module.platform.supercomputer_vnet_id
    )
    error_message = "The root must explicitly select LoadBalancer, omit managementSubnetId and use one shared VNet."
  }
}

run "root_udr_management_subnet" {
  command = apply

  variables {
    supercomputer_outbound_type   = "UserDefinedRouting"
    supercomputer_udr_next_hop_ip = "10.0.254.4"
  }

  override_resource {
    target = module.supercomputer.azapi_resource.main
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Discovery/supercomputers/sc-test"
    }
  }

  override_resource {
    target = module.workspace.azapi_resource.main
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Discovery/workspaces/ws-test"
    }
  }

  assert {
    condition = (
      module.supercomputer.outbound_type == "UserDefinedRouting" &&
      module.supercomputer.management_subnet_id == module.platform.management_subnet_id
    )
    error_message = "UDR must pass the separately delegated management subnet to the Supercomputer."
  }
}

run "bookshelf_disabled" {
  command = plan

  variables {
    enable_bookshelf                = false
    managed_resource_group_location = "eastus"
  }

  assert {
    condition     = length(module.bookshelf) == 0
    error_message = "Bookshelf must remain optional."
  }
}

run "nonisolated_workspace_retains_platform" {
  command = plan

  variables {
    network_isolation               = false
    managed_resource_group_location = "eastus"
  }

  assert {
    condition     = module.platform.infrastructure_location == "eastus" && local.managed_resource_group_location == "eastus"
    error_message = "Workspace isolation must not change the shared platform region."
  }
}

run "reject_udr_without_next_hop" {
  command = plan

  variables {
    supercomputer_outbound_type = "UserDefinedRouting"
  }

  expect_failures = [var.supercomputer_udr_next_hop_ip]
}

mock_provider "azapi" {}

mock_provider "random" {
  mock_resource "random_string" {
    defaults = {
      result = "uktst123"
    }
  }
}

run "cluster_permissions" {
  command = apply

  module {
    source = "./modules/platform"
  }

  variables {
    infrastructure_location = "swedencentral"
  }

  override_resource {
    target = azurerm_user_assigned_identity.cluster
    values = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami-cluster"
      principal_id = "00000000-0000-0000-0000-000000000002"
    }
  }

  override_resource {
    target = azurerm_user_assigned_identity.kubelet
    values = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami-kubelet"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }

  override_resource {
    target = azurerm_subnet.aks
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/aksSubnet"
    }
  }

  override_resource {
    target = azurerm_subnet.supercomputer_nodepool
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/supercomputerNodepoolSubnet"
    }
  }

  override_resource {
    target = azurerm_subnet.workspace
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/workspaceSubnet"
    }
  }

  override_resource {
    target = azurerm_subnet.private_endpoint
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/privateEndpointSubnet"
    }
  }

  override_resource {
    target = azurerm_subnet.agent
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/agentSubnet"
    }
  }

  override_resource {
    target = azurerm_subnet.search
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/searchSubnet"
    }
  }

  override_resource {
    target = azurerm_subnet.management
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-test/subnets/aksManagementSubnet"
    }
  }

  assert {
    condition = (
      azurerm_role_assignment.kubelet_managed_identity_operator.principal_id == azurerm_user_assigned_identity.cluster.principal_id &&
      azurerm_role_assignment.kubelet_managed_identity_operator.scope == azurerm_user_assigned_identity.kubelet.id &&
      endswith(azurerm_role_assignment.kubelet_managed_identity_operator.role_definition_id, "/f1a07417-d97a-45cb-824c-7a7467783830")
    )
    error_message = "The cluster identity must have Managed Identity Operator on the kubelet identity."
  }

  assert {
    condition = (
      azurerm_role_assignment.cluster_network_contributor.principal_id == azurerm_user_assigned_identity.cluster.principal_id &&
      azurerm_role_assignment.cluster_network_contributor.scope == azurerm_subnet.aks.id &&
      azurerm_role_assignment.cluster_nodepool_network_contributor.principal_id == azurerm_user_assigned_identity.cluster.principal_id &&
      azurerm_role_assignment.cluster_nodepool_network_contributor.scope == azurerm_subnet.supercomputer_nodepool.id &&
      endswith(azurerm_role_assignment.cluster_nodepool_network_contributor.role_definition_id, "/4d97b98b-1d4f-4787-a291-c67834d212e7")
    )
    error_message = "The cluster identity must have Network Contributor on both compute subnets."
  }

  assert {
    condition = length(distinct([
      azurerm_subnet.aks.id, azurerm_subnet.supercomputer_nodepool.id,
      azurerm_subnet.workspace.id, azurerm_subnet.private_endpoint.id,
      azurerm_subnet.agent.id, azurerm_subnet.search.id, azurerm_subnet.management.id,
    ])) == 7
    error_message = "The shared VNet must retain seven distinct purpose-specific subnets."
  }

  assert {
    condition = alltrue([
      for subnet in [
        azurerm_subnet.aks, azurerm_subnet.supercomputer_nodepool,
        azurerm_subnet.workspace, azurerm_subnet.private_endpoint,
        azurerm_subnet.agent, azurerm_subnet.search, azurerm_subnet.management,
      ] :
      subnet.virtual_network_name == azurerm_virtual_network.workspace.name &&
      subnet.default_outbound_access_enabled == true
    ])
    error_message = "All seven subnets must use the single VNet with default outbound access explicitly enabled."
  }

  assert {
    condition = (
      azurerm_virtual_network.workspace.location == "swedencentral" &&
      azurerm_storage_account.outputs.location == "swedencentral" &&
      azurerm_user_assigned_identity.cluster.location == "swedencentral" &&
      azapi_resource.discovery_storage_container.location == "uksouth" &&
      azurerm_storage_account.outputs.public_network_access_enabled == false &&
      azurerm_storage_account.outputs.shared_access_key_enabled == false &&
      length(azurerm_route_table.supercomputer) == 0 &&
      length(azurerm_role_assignment.cluster_management_network_contributor) == 0
    )
    error_message = "Shared infrastructure placement must preserve private storage and the separate Discovery control-plane location."
  }
}

run "storage_data_protection" {
  command = plan

  module {
    source = "./modules/platform"
  }

  variables {
    infrastructure_location = "uksouth"
  }

  assert {
    condition     = azurerm_storage_account.outputs.account_replication_type == "GRS"
    error_message = "Output storage must use geo-redundant replication."
  }

  assert {
    condition = (
      azurerm_storage_account.outputs.blob_properties[0].delete_retention_policy[0].days == 7 &&
      azurerm_storage_account.outputs.blob_properties[0].container_delete_retention_policy[0].days == 7
    )
    error_message = "Blob and container soft delete must each retain deleted data for seven days."
  }
}

run "all_uk_south" {
  command = plan

  variables {
    managed_resource_group_location = "uksouth"
    node_pool_vm_size               = "Standard_D4s_v6"
    node_pool_name                  = "abcdefghijkl"
  }

  assert {
    condition     = length(azurerm_role_assignment.workspace_contributor) == 0
    error_message = "Workspace user access must be opt-in."
  }

  assert {
    condition = (
      module.platform.location == "uksouth" &&
      module.platform.infrastructure_location == "uksouth" &&
      local.managed_resource_group_location == "uksouth"
    )
    error_message = "All control-plane and managed infrastructure regions must resolve to UK South."
  }
}

run "managed_regions_follow_location" {
  command = plan

  variables {
    location                        = "eastus"
    managed_resource_group_location = null
  }

  assert {
    condition = (
      module.platform.location == "eastus" &&
      module.platform.infrastructure_location == "eastus" &&
      local.managed_resource_group_location == "eastus"
    )
    error_message = "Without overrides, managed infrastructure regions must follow location rather than stay pinned to UK South."
  }
}

run "platform_udr_routes_and_permissions" {
  command = apply

  module {
    source = "./modules/platform"
  }

  variables {
    infrastructure_location     = "uksouth"
    supercomputer_outbound_type = "UserDefinedRouting"
    udr_next_hop_ip             = "10.0.254.4"
  }

  assert {
    condition = (
      length(azurerm_route_table.supercomputer) == 1 &&
      length(azurerm_subnet_route_table_association.supercomputer) == 2 &&
      azurerm_route.supercomputer_egress[0].address_prefix == "0.0.0.0/0" &&
      azurerm_route.supercomputer_egress[0].next_hop_type == "VirtualAppliance" &&
      azurerm_route.supercomputer_egress[0].next_hop_in_ip_address == "10.0.254.4" &&
      azurerm_role_assignment.cluster_management_network_contributor[0].scope == azurerm_subnet.management.id &&
      azurerm_role_assignment.cluster_management_network_contributor[0].principal_id == azurerm_user_assigned_identity.cluster.principal_id &&
      azurerm_subnet.management.delegation[0].service_delegation[0].name == "Microsoft.ContainerService/managedClusters"
    )
    error_message = "UDR requires a default NVA route on both compute subnets and cluster permissions on the delegated management subnet."
  }
}

run "reject_next_hop_with_load_balancer" {
  command = plan
  variables {
    supercomputer_udr_next_hop_ip = "10.0.254.4"
  }
  expect_failures = [var.supercomputer_udr_next_hop_ip]
}

run "reject_invalid_next_hop" {
  command = plan
  variables {
    supercomputer_outbound_type   = "UserDefinedRouting"
    supercomputer_udr_next_hop_ip = "not-an-ip"
  }
  expect_failures = [var.supercomputer_udr_next_hop_ip]
}

run "reject_small_management_subnet" {
  command = plan
  variables {
    management_subnet_prefix = "10.0.7.0/29"
  }
  expect_failures = [var.management_subnet_prefix]
}

run "accept_three_character_node_pool_name" {
  command = plan
  variables {
    node_pool_name = "abc"
  }
  assert {
    condition     = contains(keys(module.supercomputer.node_pool_ids), "abc")
    error_message = "The three-character node-pool name boundary must remain valid."
  }
}

run "reject_two_character_node_pool_name" {
  command = plan
  variables {
    node_pool_name = "ab"
  }
  expect_failures = [var.node_pool_name]
}

run "reject_empty_node_pool_name" {
  command = plan
  variables {
    node_pool_name = ""
  }
  expect_failures = [var.node_pool_name]
}

run "reject_long_node_pool_name" {
  command = plan
  variables {
    node_pool_name = "abcdefghijklm"
  }
  expect_failures = [var.node_pool_name]
}

run "reject_uppercase_node_pool_name" {
  command = plan
  variables {
    node_pool_name = "Pool"
  }
  expect_failures = [var.node_pool_name]
}

run "reject_hyphenated_node_pool_name" {
  command = plan
  variables {
    node_pool_name = "pool-1"
  }
  expect_failures = [var.node_pool_name]
}

run "reject_digit_prefix_node_pool_name" {
  command = plan
  variables {
    node_pool_name = "1pool"
  }
  expect_failures = [var.node_pool_name]
}

run "reject_fractional_max_node_count" {
  command = plan
  variables {
    node_pool_max_node_count = 1.5
  }
  expect_failures = [var.node_pool_max_node_count]
}

run "reject_fractional_min_node_count" {
  command = plan
  variables {
    node_pool_min_node_count = 0.5
  }
  expect_failures = [var.node_pool_min_node_count]
}

run "reject_min_above_max" {
  command = plan
  variables {
    node_pool_min_node_count = 2
    node_pool_max_node_count = 1
  }
  expect_failures = [var.node_pool_min_node_count]
}

run "workspace_user_access" {
  command = apply

  variables {
    resource_group_name = "rg-discovery-test"
    location            = "uksouth"
    workspace_contributor_principal_ids = [
      "00000000-0000-0000-0000-000000000004",
      "00000000-0000-0000-0000-000000000005",
    ]
  }

  override_resource {
    target = module.workspace.azapi_resource.main
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Discovery/workspaces/ws-test"
    }
  }

  override_resource {
    target = module.supercomputer.azapi_resource.main
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Discovery/supercomputers/sc-test"
    }
  }

  assert {
    condition = (
      length(azurerm_role_assignment.workspace_contributor) == 2 &&
      alltrue([
        for id, assignment in azurerm_role_assignment.workspace_contributor :
        assignment.principal_id == id &&
        assignment.scope == module.workspace.id &&
        assignment.role_definition_id == "/subscriptions/00000000-0000-0000-0000-000000000001/providers/Microsoft.Authorization/roleDefinitions/01288891-85ee-45a7-b367-9db3b752fc65"
      ])
    )
    error_message = "Each configured principal must receive Discovery Contributor at workspace scope."
  }
}
