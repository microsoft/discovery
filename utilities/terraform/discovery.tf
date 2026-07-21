# -----------------------------------------------------------------------------
# discovery.tf   [PROVIDER: azapi -- 100% of this file]
#
# All Microsoft.Discovery/* resources. There are NO azurerm_discovery_*
# resources in the AzureRM provider today, so every block here uses azapi.
#
# API version pin: "@2026-02-01-preview" on every resource -- this matches
# ../discovery.bicep and is what AzAPI v2.10's embedded schema recognizes.
# The Discovery RP also exposes a GA `2026-06-01` per Learn, but the AzAPI
# provider hasn't shipped schemas for it yet (validate fails for at least
# `supercomputers`, `nodePools`, `workspaces`, and `storageContainers`).
# When AzAPI catches up, do a single find/replace here to bump the pin.
#
# Ordering: Terraform infers order from the references in `body`, so the
# explicit `dependsOn: [vnet]` blocks from ../discovery.bicep are unnecessary
# here. The only depends_on entries below are for things Terraform CANNOT see
# from a reference chain (role assignments -> Discovery resources that
# consume the UAMI's permissions).
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Supercomputer
#
# Notable HCL shape: `workloadIdentities` is a map keyed by the UAMI's ARM
# resource ID, with an empty object as the value. The parentheses around
# `azurerm_user_assigned_identity.workspace.id` are how HCL builds a map with
# an interpolated key expression -- this is the single trickiest line of the
# whole port, and the reason we use azapi v2's HCL-native `body = { ... }`
# rather than jsonencode(...).
# -----------------------------------------------------------------------------
resource "azapi_resource" "supercomputer" {
  type      = "Microsoft.Discovery/supercomputers@2026-02-01-preview"
  name      = local.supercomputer_name
  location  = var.location
  parent_id = data.azurerm_resource_group.rg.id

  body = {
    properties = {
      subnetId = azurerm_subnet.aks.id
      identities = {
        clusterIdentity = {
          id = azurerm_user_assigned_identity.workspace.id
        }
        kubeletIdentity = {
          id = azurerm_user_assigned_identity.workspace.id
        }
        workloadIdentities = {
          (azurerm_user_assigned_identity.workspace.id) = {}
        }
      }
    }
  }

  # AcrPull is scoped to the RG; ensure it lands before the SC comes up so any
  # image pulls into the SC's AKS cluster succeed on first try.
  depends_on = [azurerm_role_assignment.acr_pull]

  # Supercomputer create provisions an AKS cluster; azapi's 30m default is
  # too tight. Bump to 60m to avoid `context deadline exceeded` on cold RGs.
  timeouts {
    create = "60m"
    update = "60m"
    delete = "60m"
  }
}

# -----------------------------------------------------------------------------
# Node pool (child of Supercomputer)
# -----------------------------------------------------------------------------
resource "azapi_resource" "node_pool" {
  type      = "Microsoft.Discovery/supercomputers/nodePools@2026-02-01-preview"
  name      = var.node_pool_name
  location  = var.location
  parent_id = azapi_resource.supercomputer.id

  body = {
    properties = {
      subnetId         = azurerm_subnet.supercomputer_nodepool.id
      vmSize           = var.node_pool_vm_size
      maxNodeCount     = var.node_pool_max_node_count
      minNodeCount     = var.node_pool_min_node_count
      scaleSetPriority = var.node_pool_scale_set_priority
    }
  }
}

# -----------------------------------------------------------------------------
# Workspace
#
# Notes:
#   * `workspaceIdentity` is a Discovery-specific identity block, NOT the
#     standard ARM `identity` envelope. AzAPI passes it through as-is; any
#     future azurerm_discovery_workspace will need its own schema for this.
#   * `tags.version = "v2"` is a schema-version pin the Discovery RP reads.
#     Preserve it verbatim -- do not treat as a normal cosmetic tag.
#   * `tags.NetworkIsolation` MUST be "true" while the agent/private-endpoint/
#     workspace subnet IDs below are set. false + subnets is a broken hybrid:
#     the RP disables Cosmos public access but never creates the private
#     endpoint or VNet-injects the ACA environment, so the managed backend
#     cannot reach Cosmos, the agent upsert fails (InternalServerError), and
#     teardown deadlocks. See variable "network_isolation" for the full note.
# -----------------------------------------------------------------------------
resource "azapi_resource" "workspace" {
  type      = "Microsoft.Discovery/workspaces@2026-02-01-preview"
  name      = local.workspace_name
  location  = var.location
  parent_id = data.azurerm_resource_group.rg.id

  tags = {
    version                                    = "v2"
    "discovery.workbench.enableGhcpAiFeatures" = tostring(var.enable_ghcp_ai_features)
    "discovery.workbench.enableExtensions"     = tostring(var.enable_extensions)
    NetworkIsolation                           = tostring(var.network_isolation)
  }

  body = {
    properties = {
      workspaceIdentity = {
        id = azurerm_user_assigned_identity.workspace.id
      }
      supercomputerIds = [
        azapi_resource.supercomputer.id,
      ]
      agentSubnetId           = azurerm_subnet.agent.id
      privateEndpointSubnetId = azurerm_subnet.private_endpoint.id
      workspaceSubnetId       = azurerm_subnet.workspace.id
    }
  }

  # Workspace create validates the UAMI has Discovery Platform Contributor
  # on the RG. Force ordering so this is not racy on first apply.
  depends_on = [azurerm_role_assignment.discovery_platform_contributor]

  # Workspace create can take 30-45 min under load; extend past azapi's
  # 30m default so we don't cancel a healthy in-flight provision.
  timeouts {
    create = "60m"
    update = "60m"
    delete = "60m"
  }
}

# -----------------------------------------------------------------------------
# Chat model deployment (child of workspace)
#
# The Discovery schema exposes an optional `capacity` (min 1) for provisioned
# SKUs; left unset here to match ../discovery.bicep behavior.
# -----------------------------------------------------------------------------
resource "azapi_resource" "chat_model" {
  type      = "Microsoft.Discovery/workspaces/chatModelDeployments@2026-02-01-preview"
  name      = var.chat_model_deployment_name
  location  = var.location
  parent_id = azapi_resource.workspace.id

  body = {
    properties = {
      modelFormat = var.chat_model_format
      modelName   = var.chat_model_name
    }
  }
}

# -----------------------------------------------------------------------------
# Discovery StorageContainer (top-level control-plane binding, NOT the blob
# container itself)
#
# This is a control-plane projection over an existing Storage account -- it
# references `storageStore.storageAccountId` and lets Discovery attach that
# account to the workspace. The schema exposes an optional `mountProtocol`;
# left unset to match the Bicep quickstart.
# -----------------------------------------------------------------------------
resource "azapi_resource" "discovery_storage_container" {
  type      = "Microsoft.Discovery/storageContainers@2026-02-01-preview"
  name      = local.storage_container_name
  location  = var.location
  parent_id = data.azurerm_resource_group.rg.id

  body = {
    properties = {
      storageStore = {
        kind             = "AzureStorageBlob"
        storageAccountId = azurerm_storage_account.outputs.id
      }
    }
  }

  # Discovery RP validates access via the workspace UAMI; make sure the
  # Storage Blob Data Contributor grant and the blob container both exist
  # before we try to bind.
  depends_on = [
    azurerm_role_assignment.storage_blob_data_contributor,
    azapi_resource.outputs_container,
  ]
}

# -----------------------------------------------------------------------------
# Project (child of workspace)
#
# Implicit RP-side ordering (not visible to Terraform from references):
#   * V2 project create validates that at least one ChatModelDeployment on the
#     workspace is in `Succeeded` state -- otherwise it returns 400
#     "Cannot create a V2 project: no ChatModelDeployment in Succeeded state
#     found in workspace ...". Chat model and project both hang off the
#     workspace as parallel children, so without an explicit depends_on
#     Terraform will submit them concurrently and lose the race.
# -----------------------------------------------------------------------------
resource "azapi_resource" "project" {
  type      = "Microsoft.Discovery/workspaces/projects@2026-02-01-preview"
  name      = local.project_name
  location  = var.location
  parent_id = azapi_resource.workspace.id

  body = {
    properties = {
      storageContainerIds = [
        azapi_resource.discovery_storage_container.id,
      ]
    }
  }

  depends_on = [azapi_resource.chat_model]
}
