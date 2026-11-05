variable "name" {
  description = "Discovery Tool name"
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9-]{3,24}$", var.name))
    error_message = "name must contain 3 to 24 alphanumeric or hyphen characters."
  }
}

variable "location" {
  description = "Azure region for the Tool"
  type        = string
}

variable "resource_group_id" {
  description = "Resource ID of the existing resource group"
  type        = string
}

variable "definition_content" {
  description = "Arbitrary Tool definition content passed directly to the Discovery API"
  type        = any

  validation {
    condition     = var.definition_content != null && can(keys(var.definition_content))
    error_message = "definition_content must be a non-null object."
  }
}

variable "tool_version" {
  description = "Version of the Tool definition"
  type        = string

  validation {
    condition     = length(trimspace(var.tool_version)) > 0
    error_message = "tool_version cannot be empty."
  }
}

variable "environment_variables" {
  description = "Environment variables made available to the Tool"
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Tags applied to the Tool"
  type        = map(string)
  default     = {}
}

variable "resource_timeouts" {
  description = "Timeouts for Tool control-plane operations"
  type = object({
    create = optional(string, "30m")
    update = optional(string, "30m")
    delete = optional(string, "30m")
  })
  default = {}
}