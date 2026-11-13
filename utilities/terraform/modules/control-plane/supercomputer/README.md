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

## Egress and validation

`outbound_type` defaults to `LoadBalancer` and is always sent explicitly. The
other supported value is `UserDefinedRouting`; `None` is not accepted.
UDR requires a separate `management_subnet_id`, delegated to
`Microsoft.ContainerService/managedClusters`, plus caller-provided working
routes through a firewall/NVA. The cluster identity needs permissions on the
management subnet as well as the compute subnets. This module does not create
those network resources or prove their connectivity.

Node-pool names accept 3-12 lowercase alphanumeric characters, starting with a
letter. This is the intersection of the live API's 1-12 character rule and the
pinned AzAPI provider's generic 3-24 character schema; schema validation stays enabled.
The Supercomputer resource name retains its separate 3-24 character validation.
Workload VM SKUs
are passed through without a hard-coded enumeration; a non-empty SKU is required,
and service support, regional availability and quota must be checked separately.
Node counts, disk size and cache thresholds must be integers within their
documented ranges. The optional system-node SKU validation is unchanged.

Consumers that require node pools to finish before starting dependent services
must depend on the complete Supercomputer module or the relevant node-pool
outputs, not only the parent `id` output. The full-stack root explicitly makes
Workspace depend on this module.

See [Supercomputer networking](https://learn.microsoft.com/azure/microsoft-discovery/how-to-configure-supercomputer-network-security)
for the UDR, management-subnet and private-Supercomputer requirements.
