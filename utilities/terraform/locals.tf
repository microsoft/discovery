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

  # Schema-version pin the Discovery RP reads from resource tags.
  discovery_resource_version = "v2"

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

  supercomputer_name     = coalesce(var.supercomputer_name, "sc-${local.suffix}")
  workspace_name         = coalesce(var.workspace_name, "ws-${local.suffix}")
  storage_container_name = coalesce(var.storage_container_name, "stc-${local.suffix}")
  project_name           = coalesce(var.project_name, "prj-${local.suffix}")
  bookshelf_name         = coalesce(var.bookshelf_name, "bs-${local.suffix}")
  vnet_name              = coalesce(var.vnet_name, "vnet-${local.suffix}")
  supercomputer_vnet_name = coalesce(
    var.supercomputer_vnet_name,
    "vnet-sc-${local.suffix}",
  )
  managed_identity_name  = coalesce(var.managed_identity_name, "uami-ws-${local.suffix}")
  cluster_identity_name  = coalesce(var.cluster_identity_name, "uami-cluster-${local.suffix}")
  kubelet_identity_name  = coalesce(var.kubelet_identity_name, "uami-kubelet-${local.suffix}")
  workload_identity_name = coalesce(var.workload_identity_name, "uami-workload-${local.suffix}")
  storage_account_name   = coalesce(var.storage_account_name, "stg${local.suffix}")
}
