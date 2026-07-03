# -----------------------------------------------------------------------------
# locals.tf
#
# Central place to resolve default names. If a *_name variable is null, we
# derive it from a shared random suffix so a fresh apply always succeeds.
# -----------------------------------------------------------------------------

resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
  numeric = true
}

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

locals {
  suffix = coalesce(var.name_suffix, random_string.suffix.result)

  supercomputer_name     = coalesce(var.supercomputer_name, "sc-${local.suffix}")
  workspace_name         = coalesce(var.workspace_name, "ws-${local.suffix}")
  storage_container_name = coalesce(var.storage_container_name, "stc-${local.suffix}")
  project_name           = coalesce(var.project_name, "prj-${local.suffix}")
  vnet_name              = coalesce(var.vnet_name, "vnet-${local.suffix}")
  managed_identity_name  = coalesce(var.managed_identity_name, "uami-${local.suffix}")
  storage_account_name   = coalesce(var.storage_account_name, "stg${local.suffix}")
}
