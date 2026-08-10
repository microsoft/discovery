# -----------------------------------------------------------------------------
# main.tf -- end-to-end Discovery deployment (single apply)
#
# The root composes the same modules the staged BYO examples use:
#   * modules/platform                     -- network, identities, storage, RBAC
#   * modules/control-plane/supercomputer  -- supercomputer + node pool
#   * modules/control-plane/workspace      -- workspace + chat model + project
#   * modules/control-plane/bookshelf      -- optional, behind enable_bookshelf
#
# There are no inline Discovery or platform resources here: the modules are the
# single source of truth, so the BYO and E2E paths cannot drift.
# -----------------------------------------------------------------------------

module "platform" {
  source = "./modules/platform"

  resource_group_name                   = var.resource_group_name
  location                              = var.location
  supercomputer_infrastructure_location = local.managed_resource_group_locations.supercomputer
  name_suffix                           = local.suffix
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

  create_supercomputer_network = var.existing_supercomputer_id == null
}

module "supercomputer" {
  source = "./modules/control-plane/supercomputer"
  count  = var.existing_supercomputer_id == null ? 1 : 0

  name              = local.supercomputer_name
  location          = var.location
  resource_group_id = module.platform.resource_group_id

  system_subnet_id      = module.platform.aks_subnet_id
  cluster_identity_id   = module.platform.cluster_identity_id
  kubelet_identity_id   = module.platform.kubelet_identity_id
  workload_identity_ids = [module.platform.workload_identity_id]

  node_pools = {
    (var.node_pool_name) = {
      subnet_id          = module.platform.supercomputer_nodepool_subnet_id
      vm_size            = var.node_pool_vm_size
      max_node_count     = var.node_pool_max_node_count
      min_node_count     = var.node_pool_min_node_count
      scale_set_priority = var.node_pool_scale_set_priority
      tags               = merge(var.common_tags, var.node_pool_tags)
    }
  }

  tags = merge(
    var.common_tags,
    var.supercomputer_tags,
    local.managed_resource_group_tags.supercomputer,
  )
}

locals {
  # Use the caller-provided resource when set (BYO); otherwise the one we create.
  supercomputer_id = coalesce(var.existing_supercomputer_id, one(module.supercomputer[*].id))
  workspace_id     = coalesce(var.existing_workspace_id, one(module.workspace[*].id))
  bookshelf_id     = var.existing_bookshelf_id != null ? var.existing_bookshelf_id : one(module.bookshelf[*].id)
}

module "workspace" {
  source = "./modules/control-plane/workspace"
  count  = var.existing_workspace_id == null ? 1 : 0

  name              = local.workspace_name
  location          = var.location
  resource_group_id = module.platform.resource_group_id

  workspace_identity_id = module.platform.workspace_identity_id
  supercomputer_ids     = [local.supercomputer_id]

  network_isolation          = var.network_isolation
  agent_subnet_id            = var.network_isolation ? module.platform.agent_subnet_id : null
  private_endpoint_subnet_id = var.network_isolation ? module.platform.private_endpoint_subnet_id : null
  workspace_subnet_id        = var.network_isolation ? module.platform.workspace_subnet_id : null

  enable_ghcp_ai_features = var.enable_ghcp_ai_features
  enable_extensions       = var.enable_extensions

  chat_model_deployments = {
    (var.chat_model_deployment_name) = {
      model_format = var.chat_model_format
      model_name   = var.chat_model_name
      tags         = merge(var.common_tags, var.chat_model_deployment_tags)
    }
  }

  projects = {
    (local.project_name) = {
      storage_container_ids = [module.platform.storage_container_id]
      tags                  = merge(var.common_tags, var.project_tags)
    }
  }

  tags = merge(
    var.common_tags,
    var.workspace_tags,
    local.managed_resource_group_tags.workspace,
  )
}

module "bookshelf" {
  source = "./modules/control-plane/bookshelf"
  count  = var.enable_bookshelf && var.existing_bookshelf_id == null ? 1 : 0

  name              = local.bookshelf_name
  location          = var.location
  resource_group_id = module.platform.resource_group_id

  private_endpoint_subnet_id   = module.platform.private_endpoint_subnet_id
  search_subnet_id             = module.platform.search_subnet_id
  public_network_access        = var.bookshelf_public_network_access
  workload_identity_ids        = [module.platform.workload_identity_id]
  workload_identity_client_ids = [module.platform.workload_identity_client_id]

  tags = merge(
    var.common_tags,
    var.bookshelf_tags,
    local.managed_resource_group_tags.bookshelf,
  )
}
