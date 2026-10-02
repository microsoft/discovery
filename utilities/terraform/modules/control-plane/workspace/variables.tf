variable "name" {
  description = "Discovery Workspace name"
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9-]{3,24}$", var.name))
    error_message = "name must contain 3 to 24 alphanumeric or hyphen characters."
  }
}

variable "location" {
  description = "Azure region for the Workspace and child resources"
  type        = string
}

variable "resource_group_id" {
  description = "Resource ID of the existing resource group"
  type        = string
}

variable "workspace_identity_id" {
  description = "Resource ID of the Workspace user-assigned managed identity"
  type        = string
}

variable "supercomputer_ids" {
  description = "Resource IDs of linked Discovery Supercomputers"
  type        = list(string)
  default     = []
}

variable "network_isolation" {
  description = "Whether to deploy the Workspace with private network isolation"
  type        = bool
  default     = false
}

variable "agent_subnet_id" {
  description = "Optional resource ID of the agent subnet"
  type        = string
  default     = null
}

variable "private_endpoint_subnet_id" {
  description = "Optional resource ID of the private endpoint subnet"
  type        = string
  default     = null
}

variable "workspace_subnet_id" {
  description = "Optional resource ID of the Workspace subnet"
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
  description = "Optional Key Vault key used for customer-managed encryption"
  type = object({
    keyName     = string
    keyVaultUri = string
    keyVersion  = optional(string)
  })
  default = null
}

variable "log_analytics_cluster_id" {
  description = "Optional Log Analytics Cluster resource ID"
  type        = string
  default     = null
}

variable "enable_ghcp_ai_features" {
  description = "Whether to enable GitHub Copilot and AI features"
  type        = bool
  default     = true
}

variable "enable_extensions" {
  description = "Whether to enable the VS Code Extension Marketplace"
  type        = bool
  default     = true
}

variable "chat_model_deployments" {
  description = "Chat model deployments keyed by a stable logical key; the Azure name defaults to the key."
  type = map(object({
    name          = optional(string)
    model_format  = string
    model_name    = string
    model_version = optional(string)
    sku_name      = optional(string)
    capacity      = optional(number)
    tags          = optional(map(string), {})
  }))
  default = {}

  validation {
    condition = alltrue([
      for key, deployment in var.chat_model_deployments :
      can(regex("^[a-zA-Z0-9-]{3,24}$", coalesce(deployment.name, key))) &&
      (deployment.capacity == null || deployment.capacity >= 1)
    ])
    error_message = "Chat model names must contain 3 to 24 alphanumeric or hyphen characters, and capacity must be at least 1."
  }
}

variable "projects" {
  description = "Projects keyed by a stable logical key; the Azure name defaults to the key."
  type = map(object({
    name                  = optional(string)
    storage_container_ids = optional(list(string), [])
    behavior_preferences  = optional(string)
    tags                  = optional(map(string), {})
  }))
  default = {}

  validation {
    condition = alltrue([
      for key, project in var.projects :
      can(regex("^[a-zA-Z0-9-]{3,24}$", coalesce(project.name, key))) &&
      (project.behavior_preferences == null || length(project.behavior_preferences) <= 5000)
    ])
    error_message = "Project names must contain 3 to 24 alphanumeric or hyphen characters, and behavior preferences cannot exceed 5000 characters."
  }
}

variable "tags" {
  description = "Tags applied to the Workspace"
  type        = map(string)
  default     = {}
}

variable "resource_timeouts" {
  description = "Timeouts for Workspace control-plane operations"
  type = object({
    create = optional(string, "60m")
    update = optional(string, "60m")
    delete = optional(string, "60m")
  })
  default = {}
}