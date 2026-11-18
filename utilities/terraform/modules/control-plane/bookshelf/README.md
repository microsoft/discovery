---
title: Discovery Bookshelf Terraform Module
description: Deploy a Microsoft Discovery Bookshelf using existing prerequisites
---

## Usage

This control-plane module deploys one Discovery Bookshelf. Supply existing
subnets and workload identities when private networking or knowledge base
workloads require them.

```hcl
module "bookshelf" {
  source = "../../modules/control-plane/bookshelf"

  name                       = "bs-discovery-dev"
  location                   = "uksouth"
  resource_group_id          = azurerm_resource_group.example.id
  private_endpoint_subnet_id = azurerm_subnet.private_endpoint.id
  search_subnet_id           = azurerm_subnet.search.id
  public_network_access      = "Disabled"
  workload_identity_ids = [
    azurerm_user_assigned_identity.workload.id,
  ]
}
```

Customer-managed encryption requires Key Vault properties and a Log Analytics
Cluster. The Key Vault identity client ID must correspond to one of the supplied
workload identities.
