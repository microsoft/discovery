locals {
  properties = merge(
    {
      subnetId = var.system_subnet_id
      identities = {
        clusterIdentity = {
          id = var.cluster_identity_id
        }
        kubeletIdentity = {
          id = var.kubelet_identity_id
        }
        workloadIdentities = {
          for identity_id in var.workload_identity_ids : identity_id => {}
        }
      }
    },
    var.customer_managed_keys == null ? {} : { customerManagedKeys = var.customer_managed_keys },
    var.disk_encryption_set_id == null ? {} : { diskEncryptionSetId = var.disk_encryption_set_id },
    var.log_analytics_cluster_id == null ? {} : { logAnalyticsClusterId = var.log_analytics_cluster_id },
    var.management_subnet_id == null ? {} : { managementSubnetId = var.management_subnet_id },
    var.outbound_type == null ? {} : { outboundType = var.outbound_type },
    var.system_sku == null ? {} : { systemSku = var.system_sku },
  )
}

resource "azapi_resource" "main" {
  type      = "Microsoft.Discovery/supercomputers@2026-06-01"
  name      = var.name
  location  = var.location
  parent_id = var.resource_group_id
  tags      = merge(var.tags, { version = "v2" })

  body = {
    properties = local.properties
  }

  lifecycle {
    precondition {
      condition = var.customer_managed_keys != "Enabled" || (
        var.disk_encryption_set_id != null &&
        var.log_analytics_cluster_id != null
      )
      error_message = "Enabled customer-managed keys require disk_encryption_set_id and log_analytics_cluster_id."
    }
  }

  timeouts {
    create = var.resource_timeouts.create
    update = var.resource_timeouts.update
    delete = var.resource_timeouts.delete
  }
}

resource "azapi_resource" "node_pool" {
  for_each = var.node_pools

  type      = "Microsoft.Discovery/supercomputers/nodePools@2026-06-01"
  name      = each.key
  location  = var.location
  parent_id = azapi_resource.main.id
  tags      = each.value.tags

  body = {
    properties = merge(
      {
        maxNodeCount = each.value.max_node_count
        subnetId     = each.value.subnet_id
        vmSize       = each.value.vm_size
      },
      each.value.image_cache_lower_threshold == null ? {} : { imageCacheLowerThreshold = each.value.image_cache_lower_threshold },
      each.value.image_cache_upper_threshold == null ? {} : { imageCacheUpperThreshold = each.value.image_cache_upper_threshold },
      each.value.min_node_count == null ? {} : { minNodeCount = each.value.min_node_count },
      each.value.os_disk_size_gb == null ? {} : { osDiskSizeGb = each.value.os_disk_size_gb },
      each.value.scale_set_priority == null ? {} : { scaleSetPriority = each.value.scale_set_priority },
    )
  }
}