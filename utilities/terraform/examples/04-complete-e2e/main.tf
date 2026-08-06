# -----------------------------------------------------------------------------
# examples/04-complete-e2e -- the "full" deployment (module -> full)
#
# This is the composition step. It brings the individually-created control-plane
# resources in as EXISTING inputs -- the Supercomputer-linked Workspace (03) and
# the StorageContainer binding (01) -- and completes the end-to-end Discovery
# environment by attaching the remaining workspace children:
#
#   * one chat model deployment (required before any V2 project)
#   * one project bound to the StorageContainer
#
# This mimics a bring-your-own-dependencies deployment, except the "dependencies"
# brought in are our own Discovery control-plane resources rather than fresh ones.
# The chat model and project are separate ARM resources parented by the existing
# workspace ID, so this root can own them without recreating the workspace.
# -----------------------------------------------------------------------------

data "terraform_remote_state" "prereqs" {
  backend = "local"

  config = {
    path = "${path.module}/../01-prereqs/terraform.tfstate"
  }
}

data "terraform_remote_state" "workspace" {
  backend = "local"

  config = {
    path = "${path.module}/../03-workspace/terraform.tfstate"
  }
}

locals {
  workspace_id         = data.terraform_remote_state.workspace.outputs.workspace_id
  location             = data.terraform_remote_state.prereqs.outputs.location
  name_suffix          = data.terraform_remote_state.prereqs.outputs.name_suffix
  storage_container_id = data.terraform_remote_state.prereqs.outputs.storage_container_id
}

# Chat model deployment (child of the existing workspace).
resource "azapi_resource" "chat_model" {
  type      = "Microsoft.Discovery/workspaces/chatModelDeployments@2026-06-01"
  name      = var.chat_model_deployment_name
  location  = local.location
  parent_id = local.workspace_id

  body = {
    properties = {
      modelFormat = var.chat_model_format
      modelName   = var.chat_model_name
    }
  }

  timeouts {
    create = "60m"
    update = "60m"
    delete = "60m"
  }
}

# Project (child of the existing workspace), bound to the StorageContainer from 01.
#
# The RP validates that at least one chat model deployment is in Succeeded state
# before a V2 project can be created, so depends_on forces the ordering that
# Terraform cannot infer from references alone.
resource "azapi_resource" "project" {
  type      = "Microsoft.Discovery/workspaces/projects@2026-06-01"
  name      = coalesce(var.project_name, "prj-${local.name_suffix}")
  location  = local.location
  parent_id = local.workspace_id

  body = {
    properties = {
      storageContainerIds = [local.storage_container_id]
    }
  }

  depends_on = [azapi_resource.chat_model]

  timeouts {
    create = "60m"
    update = "60m"
    delete = "60m"
  }
}
