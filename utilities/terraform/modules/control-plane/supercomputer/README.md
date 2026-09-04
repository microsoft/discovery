---
title: Discovery Supercomputer Terraform Module
description: Deploy a Microsoft Discovery Supercomputer and its node pools
---

## Usage

This control-plane module deploys one Discovery Supercomputer and zero or more
node pools. Supply existing subnets and user-assigned managed identities. The
module does not create networking, identities, or role assignments.

```hcl
module "supercomputer" {
  source = "../../modules/control-plane/supercomputer"

  name                = "sc-discovery-dev"
  location            = "uksouth"
  resource_group_id   = azurerm_resource_group.example.id
  system_subnet_id    = azurerm_subnet.aks.id
  cluster_identity_id = azurerm_user_assigned_identity.cluster.id
  kubelet_identity_id = azurerm_user_assigned_identity.kubelet.id
  workload_identity_ids = [
    azurerm_user_assigned_identity.workload.id,
  ]

  node_pools = {
    nodepool1 = {
      subnet_id     = azurerm_subnet.compute.id
      vm_size       = "Standard_NC4as_T4_v3"
      max_node_count = 3
      min_node_count = 0
    }
  }
}
```

The caller must grant the documented network, managed identity, registry, and
data-access roles before creating the Supercomputer. Node pools use stable map
keys, so changing one pool does not renumber the others.
