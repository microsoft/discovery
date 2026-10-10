variable "name" {
  description = "Discovery Supercomputer name"
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9-]{3,24}$", var.name))
    error_message = "name must contain 3 to 24 alphanumeric or hyphen characters."
  }
}

variable "location" {
  description = "Azure region for the Supercomputer and node pools"
  type        = string
}

variable "resource_group_id" {
  description = "Resource ID of the existing resource group"
  type        = string
}

variable "system_subnet_id" {
  description = "Resource ID of the AKS system subnet"
  type        = string
}

variable "cluster_identity_id" {
  description = "Resource ID of the cluster user-assigned managed identity"
  type        = string
}

variable "kubelet_identity_id" {
  description = "Resource ID of the kubelet user-assigned managed identity"
  type        = string
}

variable "workload_identity_ids" {
  description = "Resource IDs of user-assigned managed identities available to workloads"
  type        = set(string)
  default     = []
}

variable "node_pools" {
  description = "Node pools keyed by stable node pool name"
  type = map(object({
    subnet_id                   = string
    vm_size                     = string
    max_node_count              = number
    min_node_count              = optional(number)
    scale_set_priority          = optional(string)
    os_disk_size_gb             = optional(number)
    image_cache_lower_threshold = optional(number)
    image_cache_upper_threshold = optional(number)
    tags                        = optional(map(string), {})
  }))
  default = {}

  validation {
    condition = alltrue([
      for name, node_pool in var.node_pools :
      can(regex("^[a-zA-Z0-9-]{3,24}$", name)) &&
      contains([
        "Standard_NC4as_T4_v3",
        "Standard_NC8as_T4_v3",
        "Standard_NC16as_T4_v3",
        "Standard_NC64as_T4_v3",
        "Standard_NC24ads_A100_v4",
        "Standard_NC48ads_A100_v4",
        "Standard_NC96ads_A100_v4",
        "Standard_ND40rs_v2",
        "Standard_NV6ads_A10_v5",
        "Standard_NV12ads_A10_v5",
        "Standard_NV24ads_A10_v5",
        "Standard_NV36ads_A10_v5",
        "Standard_NV36adms_A10_v5",
        "Standard_NV72ads_A10_v5",
      ], node_pool.vm_size) &&
      node_pool.max_node_count >= 1 &&
      (node_pool.min_node_count == null || node_pool.min_node_count >= 0) &&
      (node_pool.min_node_count == null || node_pool.min_node_count <= node_pool.max_node_count) &&
      (node_pool.scale_set_priority == null || contains(["Regular", "Spot"], node_pool.scale_set_priority)) &&
      (node_pool.os_disk_size_gb == null || (node_pool.os_disk_size_gb >= 30 && node_pool.os_disk_size_gb <= 2048)) &&
      (node_pool.image_cache_lower_threshold == null || (node_pool.image_cache_lower_threshold >= 0 && node_pool.image_cache_lower_threshold <= 100)) &&
      (node_pool.image_cache_upper_threshold == null || (node_pool.image_cache_upper_threshold >= 0 && node_pool.image_cache_upper_threshold <= 100)) &&
      (node_pool.image_cache_lower_threshold == null || node_pool.image_cache_upper_threshold == null || node_pool.image_cache_lower_threshold <= node_pool.image_cache_upper_threshold)
    ])
    error_message = "Each node pool must satisfy the Discovery node pool name, count, priority, disk, and cache threshold constraints."
  }
}

variable "management_subnet_id" {
  description = "Optional resource ID of the delegated AKS API server subnet"
  type        = string
  default     = null
}

variable "outbound_type" {
  description = "Optional network egress type for Supercomputer workloads"
  type        = string
  default     = null

  validation {
    condition     = var.outbound_type == null || contains(["LoadBalancer", "None"], var.outbound_type)
    error_message = "outbound_type must be LoadBalancer or None."
  }
}

variable "system_sku" {
  description = "Optional VM SKU for the system node pool"
  type        = string
  default     = null

  validation {
    condition     = var.system_sku == null || contains(["Standard_D4s_v4", "Standard_D4s_v5", "Standard_D4s_v6"], var.system_sku)
    error_message = "system_sku must be Standard_D4s_v4, Standard_D4s_v5, or Standard_D4s_v6."
  }
}

variable "customer_managed_keys" {
  description = "Optional customer-managed key mode"
  type        = string
  default     = null

  validation {
    condition     = var.customer_managed_keys == null || contains(["Disabled", "Enabled"], var.customer_managed_keys)
    error_message = "customer_managed_keys must be Disabled or Enabled."
  }
}

variable "disk_encryption_set_id" {
  description = "Optional Disk Encryption Set resource ID"
  type        = string
  default     = null
}

variable "log_analytics_cluster_id" {
  description = "Optional Log Analytics Cluster resource ID"
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to the Supercomputer"
  type        = map(string)
  default     = {}
}

variable "resource_timeouts" {
  description = "Timeouts for Supercomputer control-plane operations"
  type = object({
    create = optional(string, "60m")
    update = optional(string, "60m")
    delete = optional(string, "60m")
  })
  default = {}
}