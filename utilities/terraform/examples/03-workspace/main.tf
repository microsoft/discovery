# -----------------------------------------------------------------------------
# examples/03-workspace -- Workspace control-plane resource with children
#
# Consumes the shared prerequisites from 01 and the Supercomputer ID from 02,
# then creates the Discovery Workspace linked to that Supercomputer, plus its
# chat model deployment and a project bound to the StorageContainer from 01.
# This completes the staged BYO deployment using the same workspace module the
# end-to-end root uses.
#
# network_isolation = true (with all three subnets) is required by the module
# and is the healthy posture: the RP VNet-injects the managed Container Apps
# environment and creates the Cosmos/Search private endpoints. Setting it false
# while passing subnets produces the broken-hybrid InternalServerError.
# -----------------------------------------------------------------------------

data "terraform_remote_state" "prereqs" {
  backend = "local"

  config = {
    path = "${path.module}/../01-prereqs/terraform.tfstate"
  }
}

data "terraform_remote_state" "supercomputer" {
  backend = "local"

  config = {
    path = "${path.module}/../02-supercomputer/terraform.tfstate"
  }
}

locals {
  prereqs = data.terraform_remote_state.prereqs.outputs
}

module "workspace" {
  source = "../../modules/control-plane/workspace"

  name              = "ws-${local.prereqs.name_suffix}"
  location          = local.prereqs.location
  resource_group_id = local.prereqs.resource_group_id

  workspace_identity_id = local.prereqs.workspace_identity_id
  supercomputer_ids     = [data.terraform_remote_state.supercomputer.outputs.supercomputer_id]

  network_isolation          = true
  agent_subnet_id            = local.prereqs.agent_subnet_id
  private_endpoint_subnet_id = local.prereqs.private_endpoint_subnet_id
  workspace_subnet_id        = local.prereqs.workspace_subnet_id

  chat_model_deployments = {
    "gpt-5-2" = {
      model_format = "OpenAI"
      model_name   = "gpt-5.2"
    }
  }

  projects = {
    "prj-${local.prereqs.name_suffix}" = {
      storage_container_ids = [local.prereqs.storage_container_id]
    }
  }

  tags = {
    scenario = "module-to-full"
    stage    = "workspace"
  }
}
