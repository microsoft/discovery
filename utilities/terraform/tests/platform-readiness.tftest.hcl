variables {
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

run "reject_workspace_region_mismatch" {
  command = plan

  variables {
    resource_group_name                       = "rg-discovery-test"
    location                                  = "uksouth"
    workspace_managed_resource_group_location = "eastus"
  }

  expect_failures = [var.workspace_managed_resource_group_location]
}

run "reject_bookshelf_region_mismatch" {
  command = plan

  variables {
    resource_group_name                       = "rg-discovery-test"
    location                                  = "uksouth"
    enable_bookshelf                          = true
    bookshelf_managed_resource_group_location = "eastus"
  }

  expect_failures = [var.bookshelf_managed_resource_group_location]
}

run "reject_shared_region_mismatch" {
  command = plan

  variables {
    resource_group_name             = "rg-discovery-test"
    location                        = "uksouth"
    enable_bookshelf                = true
    managed_resource_group_location = "eastus"
  }

  expect_failures = [
    var.workspace_managed_resource_group_location,
    var.bookshelf_managed_resource_group_location,
  ]
}

run "specific_regions_override_shared_region" {
  command = plan

  variables {
    resource_group_name                       = "rg-discovery-test"
    location                                  = "uksouth"
    enable_bookshelf                          = true
    managed_resource_group_location           = "eastus"
    workspace_managed_resource_group_location = "uksouth"
    bookshelf_managed_resource_group_location = "uksouth"
  }

  assert {
    condition = (
      module.platform.supercomputer_infrastructure_location == "eastus" &&
      local.managed_resource_group_locations.workspace == "uksouth" &&
      local.managed_resource_group_locations.bookshelf == "uksouth"
    )
    error_message = "Specific overrides must win without blocking independent Supercomputer placement."
  }
}

run "independent_supercomputer_region" {
  command = plan

  variables {
    resource_group_name                           = "rg-discovery-test"
    location                                      = "uksouth"
    supercomputer_managed_resource_group_location = "eastus"
  }

  assert {
    condition     = module.platform.supercomputer_infrastructure_location == "eastus"
    error_message = "The Supercomputer VNet must follow its independent region."
  }
}

run "unused_bookshelf_override" {
  command = plan

  variables {
    resource_group_name                       = "rg-discovery-test"
    location                                  = "uksouth"
    enable_bookshelf                          = false
    bookshelf_managed_resource_group_location = "eastus"
  }

  assert {
    condition     = length(module.bookshelf) == 0
    error_message = "A disabled Bookshelf must not constrain regional placement."
  }
}

run "nonisolated_workspace_override" {
  command = plan

  variables {
    resource_group_name                       = "rg-discovery-test"
    location                                  = "uksouth"
    network_isolation                         = false
    workspace_managed_resource_group_location = "eastus"
  }

  assert {
    condition     = local.managed_resource_group_locations.workspace == "eastus"
    error_message = "A Workspace without attached subnets must not inherit their regional restriction."
  }
}

run "nonisolated_workspace_still_rejects_bookshelf_mismatch" {
  command = plan

  variables {
    resource_group_name                       = "rg-discovery-test"
    location                                  = "uksouth"
    network_isolation                         = false
    enable_bookshelf                          = true
    bookshelf_managed_resource_group_location = "eastus"
  }

  expect_failures = [var.bookshelf_managed_resource_group_location]
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
    resource_group_name                   = "rg-discovery-test"
    location                              = "uksouth"
    supercomputer_infrastructure_location = "uksouth"
    name_suffix                           = "uktst123"
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
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-sc/subnets/aksSubnet"
    }
  }

  override_resource {
    target = azurerm_subnet.supercomputer_nodepool
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-sc/subnets/supercomputerNodepoolSubnet"
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
}

run "all_uk_south" {
  command = plan

  variables {
    resource_group_name                           = "rg-discovery-test"
    location                                      = "uksouth"
    supercomputer_managed_resource_group_location = "uksouth"
    workspace_managed_resource_group_location     = "uksouth"
    bookshelf_managed_resource_group_location     = "uksouth"
    name_suffix                                   = "uktst123"
    node_pool_vm_size                             = "Standard_NC4as_T4_v3"
  }

  assert {
    condition     = length(azurerm_role_assignment.workspace_contributor) == 0
    error_message = "Workspace user access must be opt-in."
  }

  assert {
    condition = (
      module.platform.location == "uksouth" &&
      module.platform.supercomputer_infrastructure_location == "uksouth" &&
      alltrue([for location in values(local.managed_resource_group_locations) : location == "uksouth"])
    )
    error_message = "All control-plane and managed infrastructure regions must resolve to UK South."
  }
}

run "managed_regions_follow_location" {
  command = plan

  variables {
    resource_group_name                           = "rg-discovery-test"
    location                                      = "eastus"
    managed_resource_group_location               = null
    supercomputer_managed_resource_group_location = null
    workspace_managed_resource_group_location     = null
    bookshelf_managed_resource_group_location     = null
  }

  assert {
    condition = (
      module.platform.location == "eastus" &&
      module.platform.supercomputer_infrastructure_location == "eastus" &&
      alltrue([for location in values(local.managed_resource_group_locations) : location == "eastus"])
    )
    error_message = "Without overrides, managed infrastructure regions must follow location rather than stay pinned to UK South."
  }
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
