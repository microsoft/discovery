locals {
  properties = merge(
    {
      workloadIdentities = {
        for identity_id in var.workload_identity_ids : identity_id => {}
      }
    },
    var.customer_managed_keys == null ? {} : { customerManagedKeys = var.customer_managed_keys },
    var.key_vault_properties == null ? {} : {
      keyVaultProperties = {
        identityClientId = var.key_vault_properties.identity_client_id
        keyName          = var.key_vault_properties.key_name
        keyVaultUri      = var.key_vault_properties.key_vault_uri
        keyVersion       = var.key_vault_properties.key_version
      }
    },
    var.log_analytics_cluster_id == null ? {} : { logAnalyticsClusterId = var.log_analytics_cluster_id },
    var.private_endpoint_subnet_id == null ? {} : { privateEndpointSubnetId = var.private_endpoint_subnet_id },
    var.public_network_access == null ? {} : { publicNetworkAccess = var.public_network_access },
    var.search_subnet_id == null ? {} : { searchSubnetId = var.search_subnet_id },
  )
}

resource "azapi_resource" "main" {
  type      = "Microsoft.Discovery/bookshelves@2026-06-01"
  name      = var.name
  location  = var.location
  parent_id = var.resource_group_id
  tags      = var.tags

  body = {
    properties = local.properties
  }

  lifecycle {
    precondition {
      condition = var.customer_managed_keys != "Enabled" || (
        var.key_vault_properties != null &&
        var.log_analytics_cluster_id != null
      )
      error_message = "Enabled customer-managed keys require key_vault_properties and log_analytics_cluster_id."
    }

    precondition {
      condition = var.key_vault_properties == null || contains(
        var.workload_identity_client_ids,
        var.key_vault_properties.identity_client_id,
      )
      error_message = "The Key Vault identity client ID must be included in workload_identity_client_ids."
    }
  }

  timeouts {
    create = var.resource_timeouts.create
    update = var.resource_timeouts.update
    delete = var.resource_timeouts.delete
  }
}