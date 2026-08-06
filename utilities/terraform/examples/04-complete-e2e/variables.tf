# -----------------------------------------------------------------------------
# examples/04-complete-e2e -- variables
# -----------------------------------------------------------------------------

variable "chat_model_deployment_name" {
  description = "Chat model deployment name (3-24 chars, alphanumeric + hyphen)."
  type        = string
  default     = "gpt-5-2"
}

variable "chat_model_format" {
  description = "Chat model format."
  type        = string
  default     = "OpenAI"
}

variable "chat_model_name" {
  description = "Canonical chat model name available in the selected region."
  type        = string
  default     = "gpt-5.2"
}

variable "project_name" {
  description = "Optional Discovery Project name. Null derives prj-<suffix>."
  type        = string
  default     = null
}
