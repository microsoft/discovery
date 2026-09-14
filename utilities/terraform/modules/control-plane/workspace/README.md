---
title: Discovery Workspace Terraform Module
description: Deploy a Microsoft Discovery Workspace with chat models and projects
---

## Usage

This control-plane module deploys one Workspace with optional chat model
deployments and projects. Supply an existing identity and any linked
Supercomputer, subnet, and storage container resource IDs.

```hcl
module "workspace" {
  source = "../../modules/control-plane/workspace"

  name                  = "ws-discovery-dev"
  location              = "uksouth"
  resource_group_id     = azurerm_resource_group.example.id
  workspace_identity_id = azurerm_user_assigned_identity.workspace.id
  supercomputer_ids     = [module.supercomputer.id]

  network_isolation          = true
  agent_subnet_id            = azurerm_subnet.agent.id
  private_endpoint_subnet_id = azurerm_subnet.private_endpoint.id
  workspace_subnet_id        = azurerm_subnet.workspace.id

  chat_model_deployments = {
    gpt-5-2 = {
      model_format = "OpenAI"
      model_name   = "gpt-5.2"
    }
  }

  projects = {
    project-dev = {
      storage_container_ids = [azapi_resource.storage_container.id]
    }
  }
}
```

The module rejects partial private-network configurations. Projects wait for all
configured chat model deployments because the service requires a successful
model deployment before creating a version 2 project.
