# -----------------------------------------------------------------------------
# variables.tf
#
# Inputs for the full-stack Terraform deployment described in README.md.
# -----------------------------------------------------------------------------

# ---- resource group + region ------------------------------------------------

variable "resource_group_name" {
  description = "Existing resource group for the customer-managed resources, created outside Terraform as shown in the README quickstart"
  type        = string
}

variable "location" {
  description = "Azure region. Must be a Discovery-supported region that actually accepts new creates."
  type        = string

  # eastus2 is intentionally excluded: the Discovery RP advertises support in
  # metadata but rejects new supercomputer creates there, so an apply fails
  # ~30m in. Input validation rejects it during planning. Review service
  # availability with Discovery Toolbox before changing this allowlist.
  validation {
    condition     = contains(["eastus", "uksouth", "swedencentral"], var.location)
    error_message = "Location must be one of: eastus, uksouth, swedencentral. See the README Configure section for region restrictions."
  }
}

variable "managed_resource_group_location" {
  description = "Shared region for the VNet, platform resources and infrastructure inside every Discovery-managed resource group; null follows location"
  type        = string
  default     = null

  validation {
    condition     = var.managed_resource_group_location == null ? true : can(regex("^[a-z0-9]+$", var.managed_resource_group_location))
    error_message = "managed_resource_group_location must be null or a programmatic Azure region name such as uksouth."
  }
}

# ---- tags -------------------------------------------------------------------

variable "workspace_contributor_principal_ids" {
  description = "Entra user or group object IDs in the deployment tenant to grant Discovery data access at workspace scope"
  type        = set(string)
  default     = []
  nullable    = false

  validation {
    condition = alltrue([
      for id in var.workspace_contributor_principal_ids :
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", id))
    ])
    error_message = "Workspace contributor principal IDs must be Entra object IDs in GUID format."
  }
}

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
  description = "Discovery node pool name (3-12 lowercase alphanumeric characters, starting with a letter)."
  type        = string
  default     = "nodepool1"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,11}$", var.node_pool_name))
    error_message = "node_pool_name must contain 3 to 12 lowercase alphanumeric characters, starting with a letter."
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
  description = "Address space for the single VNet shared by Discovery resources"
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

variable "search_subnet_prefix" {
  description = "Address prefix for the search subnet (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.6.0/24"
}

variable "management_subnet_prefix" {
  description = "Separate AKS management subnet prefix; IPv4 /28 or larger, without overlapping the other subnets"
  type        = string
  default     = "10.0.7.0/28"

  validation {
    condition     = can(cidrnetmask(var.management_subnet_prefix)) ? tonumber(split("/", var.management_subnet_prefix)[1]) <= 28 : false
    error_message = "management_subnet_prefix must be an IPv4 CIDR with at least 16 addresses (/28 or larger)."
  }
}

variable "supercomputer_outbound_type" {
  description = "Supercomputer egress mode; UserDefinedRouting requires a reachable existing firewall/NVA"
  type        = string
  default     = "LoadBalancer"
  nullable    = false

  validation {
    condition     = contains(["LoadBalancer", "UserDefinedRouting"], var.supercomputer_outbound_type)
    error_message = "supercomputer_outbound_type must be LoadBalancer or UserDefinedRouting."
  }
}

variable "supercomputer_udr_next_hop_ip" {
  description = "Private IPv4 address of an existing reachable firewall/NVA for UserDefinedRouting; omit for LoadBalancer. A NAT Gateway public IP is not a valid NVA next hop."
  type        = string
  default     = null

  validation {
    condition = var.supercomputer_udr_next_hop_ip == null ? var.supercomputer_outbound_type == "LoadBalancer" : (
      var.supercomputer_outbound_type == "UserDefinedRouting" &&
      can(cidrnetmask("${var.supercomputer_udr_next_hop_ip}/32"))
    )
    error_message = "UserDefinedRouting requires supercomputer_udr_next_hop_ip to be an IPv4 address; LoadBalancer requires it to be null."
  }
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
  description = "Workspace network isolation mode, surfaced via the NetworkIsolation tag. True supplies all three workspace subnet IDs; false omits them. The shared VNet, subnets and private storage endpoint are created in either mode"
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
  description = "Workload node-pool VM SKU; verify service support, regional availability and quota before deployment"
  type        = string
  default     = "Standard_NC4as_T4_v3"

  validation {
    condition     = var.node_pool_vm_size == null ? false : length(trimspace(var.node_pool_vm_size)) > 0
    error_message = "node_pool_vm_size must be a non-empty VM SKU."
  }
}

variable "node_pool_max_node_count" {
  description = "Maximum number of nodes in the node pool."
  type        = number
  default     = 3

  validation {
    condition     = var.node_pool_max_node_count == null ? false : var.node_pool_max_node_count >= 1 && floor(var.node_pool_max_node_count) == var.node_pool_max_node_count
    error_message = "node_pool_max_node_count must be an integer of at least 1."
  }
}

variable "node_pool_min_node_count" {
  description = "Minimum number of nodes in the node pool (0 allows scale-to-zero)."
  type        = number
  default     = 0

  validation {
    condition = var.node_pool_min_node_count == null ? false : var.node_pool_max_node_count == null ? false : (
      var.node_pool_min_node_count >= 0 &&
      floor(var.node_pool_min_node_count) == var.node_pool_min_node_count &&
      var.node_pool_min_node_count <= var.node_pool_max_node_count
    )
    error_message = "node_pool_min_node_count must be a non-negative integer no larger than node_pool_max_node_count."
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
