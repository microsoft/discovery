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
}

variable "location" {
  description = "Azure region. Must be a Discovery-supported region."
  type        = string

  validation {
    condition     = contains(["eastus", "eastus2", "uksouth", "swedencentral"], var.location)
    error_message = "Location must be one of: eastus, eastus2, uksouth, swedencentral."
  }
}

variable "managed_resource_group_location" {
  description = "Deprecated fallback region for Discovery-managed resource groups; use the resource-specific location variables"
  type        = string
  default     = null
}

variable "supercomputer_managed_resource_group_location" {
  description = "Region for the Supercomputer managed resource group and its compute infrastructure"
  type        = string
  default     = null
}

variable "workspace_managed_resource_group_location" {
  description = "Region for the Workspace managed resource group"
  type        = string
  default     = null
}

variable "bookshelf_managed_resource_group_location" {
  description = "Region for the Bookshelf managed resource group"
  type        = string
  default     = null
}

# ---- bring your own resources -----------------------------------------------

variable "existing_supercomputer_id" {
  description = "Resource ID of an existing Discovery Supercomputer to link the Workspace to. When set, the Supercomputer module is skipped and the rest of the stack is created around it."
  type        = string
  default     = null
}

variable "existing_workspace_id" {
  description = "Resource ID of an existing Discovery Workspace. When set, the Workspace module (and its chat model deployments and projects) is skipped."
  type        = string
  default     = null
}

variable "existing_bookshelf_id" {
  description = "Resource ID of an existing Discovery Bookshelf. When set, the Bookshelf module is skipped."
  type        = string
  default     = null
}

# ---- tags -------------------------------------------------------------------

variable "common_tags" {
  description = "Tags applied to every Microsoft Discovery resource"
  type        = map(string)
  default     = {}
}

variable "supercomputer_tags" {
  description = "Additional tags applied to the Discovery Supercomputer"
  type        = map(string)
  default     = {}
}

variable "node_pool_tags" {
  description = "Additional tags applied to the Supercomputer node pool"
  type        = map(string)
  default     = {}
}

variable "workspace_tags" {
  description = "Additional tags applied to the Discovery Workspace"
  type        = map(string)
  default     = {}
}

variable "chat_model_deployment_tags" {
  description = "Additional tags applied to the chat model deployment"
  type        = map(string)
  default     = {}
}

variable "project_tags" {
  description = "Additional tags applied to the Discovery project"
  type        = map(string)
  default     = {}
}

variable "bookshelf_tags" {
  description = "Additional tags applied to the Discovery Bookshelf"
  type        = map(string)
  default     = {}
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
  description = "Node pool name (3-12 lowercase alphanumeric, starts with a letter)."
  type        = string
  default     = "nodepool1"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,11}$", var.node_pool_name))
    error_message = "node_pool_name must be 3-12 lowercase alphanumeric characters starting with a letter."
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

variable "project_name" {
  description = "Discovery Project name (3-24 chars, alphanumeric + hyphen)."
  type        = string
  default     = null
}

variable "bookshelf_name" {
  description = "Discovery Bookshelf name (3-24 chars, alphanumeric + hyphen)"
  type        = string
  default     = null

  validation {
    condition     = var.bookshelf_name == null || can(regex("^[a-zA-Z0-9-]{3,24}$", var.bookshelf_name))
    error_message = "bookshelf_name must contain 3 to 24 alphanumeric or hyphen characters."
  }
}

variable "blob_container_name" {
  description = "Blob container inside the storage account used for Discovery outputs."
  type        = string
  default     = "discoveryoutputs"
}

# ---- networking -------------------------------------------------------------

variable "vnet_address_prefix" {
  description = "Address space for the Workspace VNet"
  type        = string
  default     = "10.0.0.0/16"
}

variable "supercomputer_vnet_address_prefix" {
  description = "Address space for the Supercomputer VNet"
  type        = string
  default     = "10.1.0.0/16"
}

variable "supercomputer_nodepool_subnet_prefix" {
  description = "Address prefix for the Supercomputer node pool subnet."
  type        = string
  default     = "10.1.1.0/24"
}

variable "aks_subnet_prefix" {
  description = "Address prefix for the AKS system subnet used by the Supercomputer."
  type        = string
  default     = "10.1.2.0/24"
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

variable "search_subnet_prefix" {
  description = "Address prefix for the search subnet (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.6.0/24"
}

# ---- workspace features -----------------------------------------------------

variable "enable_bookshelf" {
  description = "Whether to create a private Discovery Bookshelf"
  type        = bool
  default     = false
}

variable "bookshelf_public_network_access" {
  description = "Whether public network access is enabled for the Bookshelf"
  type        = string
  default     = "Disabled"

  validation {
    condition     = contains(["Disabled", "Enabled"], var.bookshelf_public_network_access)
    error_message = "bookshelf_public_network_access must be Disabled or Enabled."
  }
}

variable "network_isolation" {
  description = "Workspace network isolation mode, surfaced via the NetworkIsolation tag. Must be true whenever the agent/private-endpoint/workspace subnet IDs are supplied (as they always are here): the Discovery RP then VNet-injects the managed Container Apps environment and creates private endpoints (Cosmos, Search, etc.) in the private endpoint subnet. Setting this false while passing subnet IDs produces a broken hybrid where Cosmos public access is disabled but no private endpoint is created, leaving the managed backend unable to reach Cosmos (agent upsert then fails with InternalServerError and teardown deadlocks)."
  type        = bool
  default     = true
}

variable "enable_ghcp_ai_features" {
  description = "Enable GitHub Copilot and AI features in the Discovery workspace via the discovery.workbench.enableGhcpAiFeatures tag."
  type        = bool
  default     = true
}

variable "enable_extensions" {
  description = "Enable the VS Code Extension Marketplace in the Discovery workspace via the discovery.workbench.enableExtensions tag."
  type        = bool
  default     = true
}

# ---- node pool sizing -------------------------------------------------------

variable "node_pool_vm_size" {
  description = "VM SKU for the node pool."
  type        = string
  default     = "Standard_NC4as_T4_v3"

  validation {
    condition = contains([
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
    ], var.node_pool_vm_size)
    error_message = "node_pool_vm_size must be a VM SKU supported by Discovery node pools."
  }
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
