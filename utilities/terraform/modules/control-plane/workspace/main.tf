locals {
  network_properties = var.network_isolation ? {
    agentSubnetId           = var.agent_subnet_id
    privateEndpointSubnetId = var.private_endpoint_subnet_id
    workspaceSubnetId       = var.workspace_subnet_id
  } : {}

  properties = merge(
    {
      workspaceIdentity = { id = var.workspace_identity_id }
      supercomputerIds  = var.supercomputer_ids
    },
    local.network_properties,
    var.customer_managed_keys == null ? {} : { customerManagedKeys = var.customer_managed_keys },
    var.key_vault_properties == null ? {} : { keyVaultProperties = var.key_vault_properties },
    var.log_analytics_cluster_id == null ? {} : { logAnalyticsClusterId = var.log_analytics_cluster_id },
    var.public_network_access == null ? {} : { publicNetworkAccess = var.public_network_access },
  )

  required_tags = {
    version                                    = "v2"
    NetworkIsolation                           = tostring(var.network_isolation)
    "discovery.workbench.enableGhcpAiFeatures" = tostring(var.enable_ghcp_ai_features)
    "discovery.workbench.enableExtensions"     = tostring(var.enable_extensions)
  }
}

resource "azapi_resource" "main" {
  type      = "Microsoft.Discovery/workspaces@2026-06-01"
  name      = var.name
  location  = var.location
  parent_id = var.resource_group_id
  tags      = merge(var.tags, local.required_tags)

  body = {
    properties = local.properties
  }

  lifecycle {
    precondition {
      condition = var.network_isolation ? alltrue([
        var.agent_subnet_id != null,
        var.private_endpoint_subnet_id != null,
        var.workspace_subnet_id != null,
        ]) : alltrue([
        var.agent_subnet_id == null,
        var.private_endpoint_subnet_id == null,
        var.workspace_subnet_id == null,
      ])
      error_message = "Network isolation requires all three subnet IDs; non-isolated workspaces must omit them."
    }

    precondition {
      condition = var.customer_managed_keys != "Enabled" || (
        var.key_vault_properties != null &&
        var.log_analytics_cluster_id != null
      )
      error_message = "Enabled customer-managed keys require key_vault_properties and log_analytics_cluster_id."
    }

    precondition {
      condition     = length(var.projects) == 0 || length(var.chat_model_deployments) > 0
      error_message = "Projects require at least one chat model deployment in the same Workspace module."
    }
  }

  timeouts {
    create = var.resource_timeouts.create
    update = var.resource_timeouts.update
    delete = var.resource_timeouts.delete
  }
}

resource "azapi_resource" "chat_model_deployment" {
  for_each = var.chat_model_deployments

  type      = "Microsoft.Discovery/workspaces/chatModelDeployments@2026-06-01"
  name      = coalesce(each.value.name, each.key)
  location  = var.location
  parent_id = azapi_resource.main.id
  tags      = each.value.tags

  body = {
    properties = merge(
      {
        modelFormat = each.value.model_format
        modelName   = each.value.model_name
      },
      each.value.capacity == null ? {} : { capacity = each.value.capacity },
      each.value.model_version == null ? {} : { modelVersion = each.value.model_version },
      each.value.sku_name == null ? {} : { skuName = each.value.sku_name },
    )
  }
}

resource "azapi_resource" "project" {
  for_each = var.projects

  type      = "Microsoft.Discovery/workspaces/projects@2026-06-01"
  name      = coalesce(each.value.name, each.key)
  location  = var.location
  parent_id = azapi_resource.main.id
  tags      = each.value.tags

  body = {
    properties = merge(
      { storageContainerIds = each.value.storage_container_ids },
      each.value.behavior_preferences == null ? {} : {
        settings = { behaviorPreferences = each.value.behavior_preferences }
      },
    )
  }

  depends_on = [azapi_resource.chat_model_deployment]
}