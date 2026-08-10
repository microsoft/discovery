# -----------------------------------------------------------------------------
# modules/platform -- variables
#
# Shared, non-Discovery prerequisites (network, identities, storage, RBAC) plus
# the RG-level Discovery storageContainer binding. Consumed by both the staged
# BYO examples and the single-apply end-to-end root.
# -----------------------------------------------------------------------------

variable "resource_group_name" {
  description = "Existing resource group that holds every resource."
  type        = string
}

variable "location" {
  description = "Azure region for the control-plane resources and Workspace VNet."
  type        = string
}

variable "supercomputer_infrastructure_location" {
  description = "Region for the Supercomputer VNet / AKS subnets and its managed resource group (needs GPU quota)."
  type        = string
}

variable "name_suffix" {
  description = "Optional fixed suffix for resource names. Null generates a random one."
  type        = string
  default     = null
}

variable "common_tags" {
  description = "Tags applied to every platform resource."
  type        = map(string)
  default     = {}
}

variable "blob_container_name" {
  description = "Blob container Discovery mounts for outputs."
  type        = string
  default     = "discoveryoutputs"
}

# ---- address space ----------------------------------------------------------

variable "vnet_address_prefix" {
  description = "Workspace VNet address space."
  type        = string
  default     = "10.0.0.0/16"
}

variable "supercomputer_vnet_address_prefix" {
  description = "Supercomputer VNet address space."
  type        = string
  default     = "10.1.0.0/16"
}

variable "workspace_subnet_prefix" {
  description = "Workspace subnet prefix (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.1.0/24"
}

variable "private_endpoint_subnet_prefix" {
  description = "Private endpoint subnet prefix."
  type        = string
  default     = "10.0.2.0/24"
}

variable "agent_subnet_prefix" {
  description = "Agent subnet prefix (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.3.0/24"
}

variable "search_subnet_prefix" {
  description = "Search subnet prefix (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.6.0/24"
}

variable "aks_subnet_prefix" {
  description = "AKS system subnet prefix (in the Supercomputer VNet)."
  type        = string
  default     = "10.1.1.0/24"
}

variable "supercomputer_nodepool_subnet_prefix" {
  description = "Supercomputer node pool subnet prefix (in the Supercomputer VNet)."
  type        = string
  default     = "10.1.2.0/24"
}
