# -----------------------------------------------------------------------------
# variables.tf
#
# Mirrors the parameters in ../discovery.bicep. Names, defaults, and
# constraints are kept in sync so this module is a drop-in Terraform port.
# -----------------------------------------------------------------------------

# ---- resource group + region ------------------------------------------------

variable "resource_group_name" {
  description = "Existing resource group that will hold every resource. Created imperatively in Step 2 of the quickstart."
  type        = string
  default     = "rg-discovery-terraform"
}

variable "location" {
  description = "Azure region. Must be a Discovery-supported region."
  type        = string
  default     = "uksouth"

  validation {
    condition     = contains(["eastus", "eastus2", "uksouth", "swedencentral"], var.location)
    error_message = "Location must be one of: eastus, eastus2, uksouth, swedencentral."
  }
}

# ---- naming (all optional; a random suffix fills in blanks) -----------------

variable "name_suffix" {
  description = "Optional lowercase-alphanumeric suffix used when a specific *_name variable is null. Leave null to auto-generate."
  type        = string
  default     = null

  validation {
    condition     = var.name_suffix == null || can(regex("^[a-z0-9]{1,13}$", var.name_suffix))
    error_message = "name_suffix must be 1-13 lowercase alphanumeric characters."
  }
}

variable "supercomputer_name" {
  description = "Discovery Supercomputer name (3-24 chars, alphanumeric + hyphen)."
  type        = string
  default     = null
}

variable "node_pool_name" {
  description = "Node pool name (1-12 lowercase alphanumeric, starts with a letter)."
  type        = string
  default     = "nodepool1"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{0,11}$", var.node_pool_name))
    error_message = "node_pool_name must be 1-12 lowercase alphanumeric characters starting with a letter."
  }
}

variable "workspace_name" {
  description = "Discovery Workspace name (3-24 chars, alphanumeric + hyphen)."
  type        = string
  default     = null
}

variable "chat_model_deployment_name" {
  description = "Chat model deployment name (3-24 chars, alphanumeric + hyphen)."
  type        = string
  default     = "gpt-5-2"
}

variable "storage_container_name" {
  description = "Discovery StorageContainer (control-plane binding) name (3-24 chars, alphanumeric + hyphen)."
  type        = string
  default     = null
}

variable "project_name" {
  description = "Discovery Project name (3-24 chars, alphanumeric + hyphen)."
  type        = string
  default     = null
}

variable "vnet_name" {
  description = "Virtual network name."
  type        = string
  default     = null
}

variable "managed_identity_name" {
  description = "User-assigned managed identity name."
  type        = string
  default     = null
}

variable "storage_account_name" {
  description = "Globally unique storage account name (3-24 lowercase alphanumeric)."
  type        = string
  default     = null

  validation {
    condition     = var.storage_account_name == null || can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "storage_account_name must be 3-24 lowercase alphanumeric characters."
  }
}

variable "blob_container_name" {
  description = "Blob container inside the storage account used for Discovery outputs."
  type        = string
  default     = "discoveryoutputs"
}

# ---- networking -------------------------------------------------------------

variable "vnet_address_prefix" {
  description = "Address space for the VNet."
  type        = string
  default     = "10.0.0.0/16"
}

variable "supercomputer_nodepool_subnet_prefix" {
  description = "Address prefix for the Supercomputer node pool subnet."
  type        = string
  default     = "10.0.1.0/24"
}

variable "aks_subnet_prefix" {
  description = "Address prefix for the AKS system subnet used by the Supercomputer."
  type        = string
  default     = "10.0.2.0/24"
}

variable "workspace_subnet_prefix" {
  description = "Address prefix for the workspace subnet (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.3.0/24"
}

variable "private_endpoint_subnet_prefix" {
  description = "Address prefix for the private endpoint subnet."
  type        = string
  default     = "10.0.4.0/24"
}

variable "agent_subnet_prefix" {
  description = "Address prefix for the agent subnet (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.5.0/24"
}

# ---- node pool sizing -------------------------------------------------------

variable "node_pool_vm_size" {
  description = "VM SKU for the node pool."
  type        = string
  default     = "Standard_D4s_v6"
}

variable "node_pool_max_node_count" {
  description = "Maximum number of nodes in the node pool."
  type        = number
  default     = 3

  validation {
    condition     = var.node_pool_max_node_count >= 1
    error_message = "node_pool_max_node_count must be at least 1."
  }
}

variable "node_pool_min_node_count" {
  description = "Minimum number of nodes in the node pool (0 allows scale-to-zero)."
  type        = number
  default     = 0

  validation {
    condition     = var.node_pool_min_node_count >= 0
    error_message = "node_pool_min_node_count must be >= 0."
  }
}

variable "node_pool_scale_set_priority" {
  description = "Scale set priority for the node pool."
  type        = string
  default     = "Regular"

  validation {
    condition     = contains(["Regular", "Spot"], var.node_pool_scale_set_priority)
    error_message = "node_pool_scale_set_priority must be Regular or Spot."
  }
}

# ---- chat model -------------------------------------------------------------

variable "chat_model_format" {
  description = "Chat model format (see Discovery model catalog)."
  type        = string
  default     = "OpenAI"
}

variable "chat_model_name" {
  description = "Canonical chat model name available in the selected region."
  type        = string
  default     = "gpt-5.2"
}
