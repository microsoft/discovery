---
title: Discovery Tool Terraform Module
description: Deploy a Microsoft Discovery Tool from arbitrary definition content
---

## Usage

This control-plane module deploys one Discovery Tool. It passes the definition
content through to the Discovery API without imposing a private schema.

```hcl
module "tool" {
  source = "../../modules/control-plane/tool"

  name              = "molecule-search"
  location          = "uksouth"
  resource_group_id = azurerm_resource_group.example.id
  tool_version      = "1.0.0"

  definition_content = {
    name        = "molecule-search"
    description = "Search molecular records"
    version     = "1.0.0"
    category    = "Scientific Computing"
    infra = [{
      name       = "worker"
      infra_type = "container"
      image = {
        acr = "example.azurecr.io/molecule-search:1.0.0"
      }
    }]
  }

  environment_variables = {
    LOG_LEVEL = "INFO"
  }
}
```

Container image publication and prerequisite role assignments remain outside
this module. Provisioning compositions can build the definition object from an
existing registry, image, identity, storage resource, or Supercomputer.
