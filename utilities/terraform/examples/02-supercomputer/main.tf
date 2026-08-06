# -----------------------------------------------------------------------------
# examples/02-supercomputer -- individual Supercomputer control-plane resource
#
# Consumes the shared prerequisites from 01 and creates ONLY the Discovery
# Supercomputer (+ one node pool) through the low-level control-plane module.
# This is the first "resource one by one" step of the module -> full test.
# -----------------------------------------------------------------------------

data "terraform_remote_state" "prereqs" {
  backend = "local"

  config = {
    path = "${path.module}/../01-prereqs/terraform.tfstate"
  }
}

locals {
  prereqs = data.terraform_remote_state.prereqs.outputs
}

module "supercomputer" {
  source = "../../modules/control-plane/supercomputer"

  name              = "sc-${local.prereqs.name_suffix}"
  location          = local.prereqs.location
  resource_group_id = local.prereqs.resource_group_id

  system_subnet_id      = local.prereqs.aks_subnet_id
  cluster_identity_id   = local.prereqs.cluster_identity_id
  kubelet_identity_id   = local.prereqs.kubelet_identity_id
  workload_identity_ids = [local.prereqs.workload_identity_id]

  node_pools = {
    (var.node_pool_name) = {
      subnet_id          = local.prereqs.supercomputer_nodepool_subnet_id
      vm_size            = var.node_pool_vm_size
      max_node_count     = var.node_pool_max_node_count
      min_node_count     = var.node_pool_min_node_count
      scale_set_priority = var.node_pool_scale_set_priority
    }
  }

  tags = {
    "discovery.overridemrgregion" = local.prereqs.supercomputer_infrastructure_location
    scenario                      = "module-to-full"
    stage                         = "supercomputer"
  }
}
