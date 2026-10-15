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
  command = plan

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
    target          = azurerm_user_assigned_identity.cluster
    override_during = plan
    values = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami-cluster"
      principal_id = "00000000-0000-0000-0000-000000000002"
    }
  }

  override_resource {
    target          = azurerm_user_assigned_identity.kubelet
    override_during = plan
    values = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami-kubelet"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }

  override_resource {
    target          = azurerm_subnet.aks
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet-sc/subnets/aksSubnet"
    }
  }

  override_resource {
    target          = azurerm_subnet.supercomputer_nodepool
    override_during = plan
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
    node_pool_vm_size                             = "Standard_D4s_v6"
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

run "workspace_user_access" {
  command = plan

  variables {
    resource_group_name = "rg-discovery-test"
    location            = "uksouth"
    workspace_contributor_principal_ids = [
      "00000000-0000-0000-0000-000000000004",
      "00000000-0000-0000-0000-000000000005",
    ]
  }

  override_resource {
    target          = module.workspace.azapi_resource.main
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Discovery/workspaces/ws-test"
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
