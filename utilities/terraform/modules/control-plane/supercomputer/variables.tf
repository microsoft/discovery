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
  description = "Node pools keyed by stable name (3-12 lowercase alphanumeric characters, starting with a letter)"
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
      can(regex("^[a-z][a-z0-9]{2,11}$", name)) &&
      (node_pool.vm_size == null ? false : length(trimspace(node_pool.vm_size)) > 0) &&
      (node_pool.max_node_count == null ? false : node_pool.max_node_count >= 1 && floor(node_pool.max_node_count) == node_pool.max_node_count) &&
      (node_pool.min_node_count == null ? true : node_pool.max_node_count == null ? false : node_pool.min_node_count >= 0 && floor(node_pool.min_node_count) == node_pool.min_node_count && node_pool.min_node_count <= node_pool.max_node_count) &&
      (node_pool.scale_set_priority == null ? true : contains(["Regular", "Spot"], node_pool.scale_set_priority)) &&
      (node_pool.os_disk_size_gb == null ? true : floor(node_pool.os_disk_size_gb) == node_pool.os_disk_size_gb && node_pool.os_disk_size_gb >= 30 && node_pool.os_disk_size_gb <= 2048) &&
      (node_pool.image_cache_lower_threshold == null ? true : floor(node_pool.image_cache_lower_threshold) == node_pool.image_cache_lower_threshold && node_pool.image_cache_lower_threshold >= 0 && node_pool.image_cache_lower_threshold <= 100) &&
      (node_pool.image_cache_upper_threshold == null ? true : floor(node_pool.image_cache_upper_threshold) == node_pool.image_cache_upper_threshold && node_pool.image_cache_upper_threshold >= 0 && node_pool.image_cache_upper_threshold <= 100) &&
      (node_pool.image_cache_lower_threshold == null || node_pool.image_cache_upper_threshold == null ? true : node_pool.image_cache_lower_threshold <= node_pool.image_cache_upper_threshold)
    ])
    error_message = "Each node pool requires a 3-12 character lowercase alphanumeric name starting with a letter, non-empty VM SKU, integer counts/disk/cache settings, valid ranges and priority."
  }
}

variable "management_subnet_id" {
  description = "Optional resource ID of the delegated AKS API server subnet"
  type        = string
  default     = null

  validation {
    condition     = var.management_subnet_id == null ? true : length(trimspace(var.management_subnet_id)) > 0
    error_message = "management_subnet_id must be null or a non-empty delegated subnet resource ID."
  }
}

variable "outbound_type" {
  description = "Supercomputer egress type; UDR requires a management subnet and caller-provided working routing"
  type        = string
  default     = "LoadBalancer"
  nullable    = false

  validation {
    condition     = contains(["LoadBalancer", "UserDefinedRouting"], var.outbound_type)
    error_message = "outbound_type must be LoadBalancer or UserDefinedRouting."
  }
}

variable "system_sku" {
  description = "Optional VM SKU for the system node pool"
  type        = string
  default     = null

  validation {
    condition     = var.system_sku == null ? true : contains(["Standard_D4s_v4", "Standard_D4s_v5", "Standard_D4s_v6"], var.system_sku)
    error_message = "system_sku must be Standard_D4s_v4, Standard_D4s_v5, or Standard_D4s_v6."
  }
}

variable "customer_managed_keys" {
  description = "Optional customer-managed key mode"
  type        = string
  default     = null

  validation {
    condition     = var.customer_managed_keys == null ? true : contains(["Disabled", "Enabled"], var.customer_managed_keys)
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