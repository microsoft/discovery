# -----------------------------------------------------------------------------
# examples/05-bookshelf -- optional Bookshelf control-plane resource
#
# Consumes the shared prerequisites from 01 and creates ONLY the Discovery
# Bookshelf through the low-level control-plane module. The Bookshelf is an
# OPTIONAL knowledge-base resource; it is heavy (~40 min) and provisions its own
# managed Foundry + AI Search tier, so it is deployed as its own stage/state.
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

module "bookshelf" {
  source = "../../modules/control-plane/bookshelf"

  name              = "bs-${local.prereqs.name_suffix}"
  location          = local.prereqs.location
  resource_group_id = local.prereqs.resource_group_id

  search_subnet_id           = local.prereqs.search_subnet_id
  private_endpoint_subnet_id = local.prereqs.private_endpoint_subnet_id
  workload_identity_ids      = [local.prereqs.workload_identity_id]
  public_network_access      = var.public_network_access

  tags = {
    scenario = "module-to-full"
    stage    = "bookshelf"
  }
}
