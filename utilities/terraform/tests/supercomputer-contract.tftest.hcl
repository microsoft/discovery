mock_provider "azapi" {}

variables {
  name                = "contract-test"
  location            = "uksouth"
  resource_group_id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test"
  system_subnet_id    = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/system"
  cluster_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cluster"
  kubelet_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/kubelet"
  node_pools = {
    pool1 = {
      subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
      vm_size        = "Standard_D4s_v6"
      max_node_count = 1
      min_node_count = 0
    }
  }
}

run "default_egress_and_cpu_sku" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  assert {
    condition = (
      azapi_resource.main.body.properties.outboundType == "LoadBalancer" &&
      !contains(keys(azapi_resource.main.body.properties), "managementSubnetId") &&
      azapi_resource.node_pool["pool1"].body.properties.vmSize == "Standard_D4s_v6"
    )
    error_message = "Default egress must be explicit LoadBalancer, and workload SKUs must not be restricted to the former GPU list."
  }
}

run "null_outbound_uses_default" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    outbound_type = null
  }
  assert {
    condition     = azapi_resource.main.body.properties.outboundType == "LoadBalancer"
    error_message = "An explicitly null outbound type must normalize to the non-null LoadBalancer default."
  }
}

run "udr_management_payload" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    outbound_type        = "UserDefinedRouting"
    management_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/management"
  }
  assert {
    condition = (
      azapi_resource.main.body.properties.outboundType == "UserDefinedRouting" &&
      azapi_resource.main.body.properties.managementSubnetId == var.management_subnet_id
    )
    error_message = "UDR must retain its management subnet in the API payload."
  }
}

run "reject_udr_without_management" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    outbound_type = "UserDefinedRouting"
  }
  expect_failures = [azapi_resource.main]
}

run "reject_obsolete_none_mode" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    outbound_type = "None"
  }
  expect_failures = [var.outbound_type]
}

run "accept_12_character_pool_and_24_character_supercomputer" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    name = "ABCDEFGHIJKLMNOPQRSTUVWX"
    node_pools = {
      abcdefghijkl = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D8s_v6"
        max_node_count = 1
      }
    }
  }
  assert {
    condition = (
      azapi_resource.node_pool["abcdefghijkl"].name == "abcdefghijkl" &&
      azapi_resource.main.name == "ABCDEFGHIJKLMNOPQRSTUVWX"
    )
    error_message = "Node-pool and Supercomputer name limits must remain independently valid at 12 and 24 characters."
  }
}

run "accept_three_character_pool_name" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      abc = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
      }
    }
  }
  assert {
    condition     = azapi_resource.node_pool["abc"].name == "abc"
    error_message = "The three-character node-pool name boundary must remain valid."
  }
}

run "reject_two_character_pool_name" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      ab = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_13_character_pool_name" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      abcdefghijklm = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_empty_pool_name" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      "" = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_uppercase_pool_name" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      Pool = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_hyphenated_pool_name" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      "pool-1" = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_digit_prefix_pool_name" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      "1pool" = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_blank_vm_size" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      pool = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = " "
        max_node_count = 1
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_fractional_maximum" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      pool = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1.5
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_fractional_minimum" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      pool = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = 1
        min_node_count = 0.5
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_fractional_disk_size" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      pool = {
        subnet_id       = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size         = "Standard_D4s_v6"
        max_node_count  = 1
        os_disk_size_gb = 30.5
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_fractional_cache_threshold" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      pool = {
        subnet_id                   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size                     = "Standard_D4s_v6"
        max_node_count              = 1
        image_cache_lower_threshold = 20.5
      }
    }
  }
  expect_failures = [var.node_pools]
}

run "reject_null_maximum" {
  command = plan
  module {
    source = "./modules/control-plane/supercomputer"
  }
  variables {
    node_pools = {
      pool = {
        subnet_id      = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-discovery-test/providers/Microsoft.Network/virtualNetworks/vnet/subnets/workload"
        vm_size        = "Standard_D4s_v6"
        max_node_count = null
      }
    }
  }
  expect_failures = [var.node_pools]
}
