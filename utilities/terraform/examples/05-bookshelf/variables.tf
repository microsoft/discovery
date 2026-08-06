# -----------------------------------------------------------------------------
# examples/05-bookshelf -- variables
# -----------------------------------------------------------------------------

variable "public_network_access" {
  description = "Public network access mode for the Bookshelf. Disabled keeps the isolated posture consistent with the workspace."
  type        = string
  default     = "Disabled"

  validation {
    condition     = contains(["Disabled", "Enabled"], var.public_network_access)
    error_message = "public_network_access must be Disabled or Enabled."
  }
}
