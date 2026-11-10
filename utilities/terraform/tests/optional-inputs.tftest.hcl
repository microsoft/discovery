mock_provider "azapi" {}

variables {
  name              = "optional-inputs"
  location          = "uksouth"
  resource_group_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test"
  network_isolation = false
}

run "supercomputer_optional_nulls" {
  command = plan
  providers = {
    azapi = azapi
  }

  module {
    source = "./modules/control-plane/supercomputer"
  }

  variables {
    system_subnet_id    = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/system"
    cluster_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cluster"
    kubelet_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/kubelet"
    node_pools = {
      minimal = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_NC4as_T4_v3"
        max_node_count = 1
      }
      loweronly = {
        subnet_id                   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size                     = "Standard_NC4as_T4_v3"
        max_node_count              = 1
        image_cache_lower_threshold = 0
      }
      upperonly = {
        subnet_id                   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size                     = "Standard_NC4as_T4_v3"
        max_node_count              = 1
        image_cache_upper_threshold = 100
      }
    }
  }

  assert {
    condition = (
      !contains(keys(azapi_resource.main.body.properties), "customerManagedKeys") &&
      !contains(keys(azapi_resource.node_pool["minimal"].body.properties), "minNodeCount") &&
      !contains(keys(azapi_resource.node_pool["minimal"].body.properties), "osDiskSizeGb")
    )
    error_message = "Null optional Supercomputer and node-pool settings must be omitted."
  }
}

run "supercomputer_optional_values" {
  command = plan

  module {
    source = "./modules/control-plane/supercomputer"
  }

  variables {
    system_subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/system"
    cluster_identity_id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cluster"
    kubelet_identity_id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/kubelet"
    outbound_type         = "None"
    system_sku            = "Standard_D4s_v6"
    customer_managed_keys = "Disabled"
    node_pools = {
      configured = {
        subnet_id                   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size                     = "Standard_NC4as_T4_v3"
        max_node_count              = 1
        min_node_count              = 0
        scale_set_priority          = "Spot"
        os_disk_size_gb             = 30
        image_cache_lower_threshold = 0
        image_cache_upper_threshold = 100
      }
    }
  }

  assert {
    condition = (
      azapi_resource.main.body.properties.customerManagedKeys == "Disabled" &&
      azapi_resource.node_pool["configured"].body.properties.minNodeCount == 0 &&
      azapi_resource.node_pool["configured"].body.properties.imageCacheUpperThreshold == 100
    )
    error_message = "Explicit optional values and valid boundaries must be preserved."
  }
}

run "supercomputer_rejects_invalid_values" {
  command = plan

  module {
    source = "./modules/control-plane/supercomputer"
  }

  variables {
    system_subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/system"
    cluster_identity_id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cluster"
    kubelet_identity_id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/kubelet"
    outbound_type         = "invalid"
    system_sku            = "invalid"
    customer_managed_keys = "invalid"
    node_pools = {
      invalid = {
        subnet_id                   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size                     = "Standard_NC4as_T4_v3"
        max_node_count              = 1
        min_node_count              = 2
        scale_set_priority          = "invalid"
        os_disk_size_gb             = 29
        image_cache_lower_threshold = 90
        image_cache_upper_threshold = 80
      }
    }
  }

  expect_failures = [
    var.outbound_type,
    var.system_sku,
    var.customer_managed_keys,
    var.node_pools,
  ]
}

run "workspace_optional_nulls" {
  command = plan

  module {
    source = "./modules/control-plane/workspace"
  }

  variables {
    workspace_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/workspace"
    chat_model_deployments = {
      chat = {
        model_format = "OpenAI"
        model_name   = "gpt-5.2"
      }
    }
    projects = {
      project = {}
    }
  }

  assert {
    condition = (
      !contains(keys(azapi_resource.main.body.properties), "publicNetworkAccess") &&
      !contains(keys(azapi_resource.chat_model_deployment["chat"].body.properties), "capacity") &&
      !contains(keys(azapi_resource.project["project"].body.properties), "settings")
    )
    error_message = "Null optional Workspace, chat-model and project settings must be omitted."
  }
}

run "workspace_optional_values" {
  command = plan

  module {
    source = "./modules/control-plane/workspace"
  }

  variables {
    workspace_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/workspace"
    public_network_access = "Disabled"
    customer_managed_keys = "Disabled"
    chat_model_deployments = {
      chat = {
        model_format = "OpenAI"
        model_name   = "gpt-5.2"
        capacity     = 1
      }
    }
    projects = {
      project = {
        behavior_preferences = join("", [for i in range(500) : "0123456789"])
      }
    }
  }

  assert {
    condition = (
      azapi_resource.chat_model_deployment["chat"].body.properties.capacity == 1 &&
      length(azapi_resource.project["project"].body.properties.settings.behaviorPreferences) == 5000
    )
    error_message = "Valid explicit capacity and the 5000-character preference boundary must be accepted."
  }
}

run "workspace_rejects_invalid_values" {
  command = plan

  module {
    source = "./modules/control-plane/workspace"
  }

  variables {
    workspace_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/workspace"
    public_network_access = "invalid"
    customer_managed_keys = "invalid"
    chat_model_deployments = {
      chat = {
        model_format = "OpenAI"
        model_name   = "gpt-5.2"
        capacity     = 0
      }
    }
    projects = {
      project = {
        behavior_preferences = "${join("", [for i in range(500) : "0123456789"])}x"
      }
    }
  }

  expect_failures = [
    var.public_network_access,
    var.customer_managed_keys,
    var.chat_model_deployments,
    var.projects,
  ]
}

run "bookshelf_optional_nulls" {
  command = plan

  module {
    source = "./modules/control-plane/bookshelf"
  }

  assert {
    condition     = !contains(keys(azapi_resource.main.body.properties), "keyVaultProperties")
    error_message = "An omitted Key Vault configuration must not be dereferenced."
  }
}

run "bookshelf_optional_values" {
  command = plan

  module {
    source = "./modules/control-plane/bookshelf"
  }

  variables {
    public_network_access = "Disabled"
    customer_managed_keys = "Enabled"
    key_vault_properties = {
      identity_client_id = "00000000-0000-0000-0000-000000000002"
      key_name           = "test-key"
      key_vault_uri      = "https://discovery-test.vault.azure.net/"
    }
    workload_identity_client_ids = ["00000000-0000-0000-0000-000000000002"]
    log_analytics_cluster_id     = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.OperationalInsights/clusters/test-cluster"
  }

  assert {
    condition     = azapi_resource.main.body.properties.keyVaultProperties.identityClientId == "00000000-0000-0000-0000-000000000002"
    error_message = "A matching Key Vault identity must remain supported."
  }
}

run "bookshelf_rejects_invalid_modes" {
  command = plan

  module {
    source = "./modules/control-plane/bookshelf"
  }

  variables {
    public_network_access = "invalid"
    customer_managed_keys = "invalid"
  }

  expect_failures = [var.public_network_access, var.customer_managed_keys]
}

run "bookshelf_rejects_unassigned_key_identity" {
  command = plan

  module {
    source = "./modules/control-plane/bookshelf"
  }

  variables {
    key_vault_properties = {
      identity_client_id = "00000000-0000-0000-0000-000000000002"
      key_name           = "test-key"
      key_vault_uri      = "https://discovery-test.vault.azure.net/"
    }
  }

  expect_failures = [azapi_resource.main]
}
