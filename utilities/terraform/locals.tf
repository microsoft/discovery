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

locals {
  suffix = coalesce(var.name_suffix, random_string.suffix.result)

  managed_resource_group_location = coalesce(var.managed_resource_group_location, var.location)

  managed_resource_group_tags = {
    "discovery.overridemrgregion" = local.managed_resource_group_location
  }

  supercomputer_name = coalesce(var.supercomputer_name, "sc-${local.suffix}")
  workspace_name     = coalesce(var.workspace_name, "ws-${local.suffix}")
  project_name       = coalesce(var.project_name, "prj-${local.suffix}")
  bookshelf_name     = coalesce(var.bookshelf_name, "bs-${local.suffix}")
}
