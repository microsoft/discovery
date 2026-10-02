variable "name" {
  description = "Discovery Bookshelf name"
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9-]{3,24}$", var.name))
    error_message = "name must contain 3 to 24 alphanumeric or hyphen characters."
  }
}

variable "location" {
  description = "Azure region for the Bookshelf"
  type        = string
}

variable "resource_group_id" {
  description = "Resource ID of the existing resource group"
  type        = string
}

variable "private_endpoint_subnet_id" {
  description = "Optional resource ID of the private endpoint subnet"
  type        = string
  default     = null
}

variable "search_subnet_id" {
  description = "Optional resource ID of the search subnet"
  type        = string
  default     = null
}

variable "public_network_access" {
  description = "Optional public network access mode"
  type        = string
  default     = null

  validation {
    condition     = var.public_network_access == null || contains(["Disabled", "Enabled"], var.public_network_access)
    error_message = "public_network_access must be Disabled or Enabled."
  }
}

variable "workload_identity_ids" {
  description = "Resource IDs of user-assigned managed identities for knowledge base workloads"
  type        = set(string)
  default     = []
}

variable "workload_identity_client_ids" {
  description = "Client IDs corresponding to workload identities, used to validate Key Vault access"
  type        = set(string)
  default     = []
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

variable "key_vault_properties" {
  description = "Optional Key Vault key and identity used for customer-managed encryption"
  type = object({
    identity_client_id = string
    key_name           = string
    key_vault_uri      = string
    key_version        = optional(string)
  })
  default = null
}

variable "log_analytics_cluster_id" {
  description = "Optional Log Analytics Cluster resource ID"
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to the Bookshelf"
  type        = map(string)
  default     = {}
}

variable "resource_timeouts" {
  description = "Timeouts for Bookshelf control-plane operations"
  type = object({
    create = optional(string, "60m")
    update = optional(string, "60m")
    delete = optional(string, "60m")
  })
  default = {}
}