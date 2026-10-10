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

  # Region for each Discovery resource's managed infrastructure (managed
  # resource group). A resource-specific override wins; otherwise fall back to
  # the shared (deprecated) override, then the control-plane location.
  managed_resource_group_locations = {
    for resource, override in {
      supercomputer = var.supercomputer_managed_resource_group_location
      workspace     = var.workspace_managed_resource_group_location
      bookshelf     = var.bookshelf_managed_resource_group_location
    } :
    resource => coalesce(override, var.managed_resource_group_location, var.location)
  }

  # `discovery.overridemrgregion` tag per resource, derived from the resolved
  # MRG location above. Merged onto each managed-resource-group-producing
  # Discovery resource.
  managed_resource_group_tags = {
    for resource, location in local.managed_resource_group_locations :
    resource => { "discovery.overridemrgregion" = location }
  }

  supercomputer_name = coalesce(var.supercomputer_name, "sc-${local.suffix}")
  workspace_name     = coalesce(var.workspace_name, "ws-${local.suffix}")
  project_name       = coalesce(var.project_name, "prj-${local.suffix}")
  bookshelf_name     = coalesce(var.bookshelf_name, "bs-${local.suffix}")
}
