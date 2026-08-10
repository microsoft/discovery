# -----------------------------------------------------------------------------
# examples/01-prereqs -- main
#
# Stage 1 of the staged BYO deployment. Creates every non-Discovery prerequisite
# plus the RG-level Discovery storageContainer binding by calling the shared
# modules/platform module -- the same module the end-to-end root uses. The
# per-resource control-plane roots (02, 03, 05) consume these outputs via
# terraform_remote_state.
# -----------------------------------------------------------------------------

module "platform" {
  source = "../../modules/platform"

  resource_group_name                   = var.resource_group_name
  location                              = var.location
  supercomputer_infrastructure_location = var.supercomputer_infrastructure_location
  name_suffix                           = var.name_suffix
  common_tags                           = var.common_tags
  blob_container_name                   = var.blob_container_name

  vnet_address_prefix                  = var.vnet_address_prefix
  supercomputer_vnet_address_prefix    = var.supercomputer_vnet_address_prefix
  workspace_subnet_prefix              = var.workspace_subnet_prefix
  private_endpoint_subnet_prefix       = var.private_endpoint_subnet_prefix
  agent_subnet_prefix                  = var.agent_subnet_prefix
  search_subnet_prefix                 = var.search_subnet_prefix
  aks_subnet_prefix                    = var.aks_subnet_prefix
  supercomputer_nodepool_subnet_prefix = var.supercomputer_nodepool_subnet_prefix
}
