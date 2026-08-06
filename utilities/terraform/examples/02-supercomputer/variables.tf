# -----------------------------------------------------------------------------
# examples/02-supercomputer -- variables
# -----------------------------------------------------------------------------

variable "node_pool_name" {
  description = "Node pool name (1-24 alphanumeric or hyphen)."
  type        = string
  default     = "nodepool1"
}

variable "node_pool_vm_size" {
  description = "GPU VM SKU for the node pool."
  type        = string
  default     = "Standard_NC4as_T4_v3"
}

variable "node_pool_max_node_count" {
  description = "Maximum nodes in the node pool."
  type        = number
  default     = 3
}

variable "node_pool_min_node_count" {
  description = "Minimum nodes (0 = scale to zero, no GPU cores consumed at rest)."
  type        = number
  default     = 0
}

variable "node_pool_scale_set_priority" {
  description = "Node pool scale set priority."
  type        = string
  default     = "Regular"
}
