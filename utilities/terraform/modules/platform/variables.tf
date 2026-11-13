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
  description = "Discovery control-plane region for the StorageContainer binding."
  type        = string
}

variable "infrastructure_location" {
  description = "Shared region for the VNet, identities, storage and infrastructure inside the Discovery-managed groups."
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
  description = "Address space for the shared Discovery VNet."
  type        = string
  default     = "10.0.0.0/16"
}

variable "workspace_subnet_prefix" {
  description = "Workspace subnet prefix (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.3.0/24"
}

variable "private_endpoint_subnet_prefix" {
  description = "Private endpoint subnet prefix."
  type        = string
  default     = "10.0.4.0/24"
}

variable "agent_subnet_prefix" {
  description = "Agent subnet prefix (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.5.0/24"
}

variable "search_subnet_prefix" {
  description = "Search subnet prefix (delegated to Microsoft.App/environments)."
  type        = string
  default     = "10.0.6.0/24"
}

variable "aks_subnet_prefix" {
  description = "AKS system subnet prefix in the shared VNet."
  type        = string
  default     = "10.0.2.0/24"
}

variable "supercomputer_nodepool_subnet_prefix" {
  description = "Supercomputer node pool subnet prefix in the shared VNet."
  type        = string
  default     = "10.0.1.0/24"
}

variable "management_subnet_prefix" {
  description = "Dedicated AKS management subnet; IPv4 /28 or larger."
  type        = string
  default     = "10.0.7.0/28"

  validation {
    condition     = can(cidrnetmask(var.management_subnet_prefix)) ? tonumber(split("/", var.management_subnet_prefix)[1]) <= 28 : false
    error_message = "management_subnet_prefix must be an IPv4 CIDR with at least 16 addresses (/28 or larger)."
  }
}

variable "supercomputer_outbound_type" {
  description = "Supercomputer outbound mode; UDR creates compute-subnet routes to an existing firewall/NVA."
  type        = string
  default     = "LoadBalancer"
  nullable    = false

  validation {
    condition     = contains(["LoadBalancer", "UserDefinedRouting"], var.supercomputer_outbound_type)
    error_message = "supercomputer_outbound_type must be LoadBalancer or UserDefinedRouting."
  }
}

variable "udr_next_hop_ip" {
  description = "IPv4 private address of an existing reachable firewall/NVA; required for UDR and omitted for LoadBalancer."
  type        = string
  default     = null

  validation {
    condition = var.udr_next_hop_ip == null ? var.supercomputer_outbound_type == "LoadBalancer" : (
      var.supercomputer_outbound_type == "UserDefinedRouting" &&
      can(cidrnetmask("${var.udr_next_hop_ip}/32"))
    )
    error_message = "UserDefinedRouting requires an IPv4 udr_next_hop_ip; LoadBalancer requires it to be null."
  }
}
