# -----------------------------------------------------------------------------
# outputs.tf
#
# Surfaces the module outputs so downstream tooling (Toolbox, scripts, azd
# wrappers) sees the same values as the Bicep path.
# -----------------------------------------------------------------------------

output "supercomputer_id" {
  description = "Resource ID of the Discovery Supercomputer."
  value       = module.supercomputer.id
}

output "node_pool_ids" {
  description = "Resource IDs of the Supercomputer node pools keyed by name."
  value       = module.supercomputer.node_pool_ids
}

output "workspace_id" {
  description = "Resource ID of the Discovery Workspace."
  value       = module.workspace.id
}

output "chat_model_deployment_ids" {
  description = "Resource IDs of the chat model deployments keyed by name."
  value       = module.workspace.chat_model_deployment_ids
}

output "project_ids" {
  description = "Resource IDs of the Discovery projects keyed by name."
  value       = module.workspace.project_ids
}

output "storage_container_id" {
  description = "Resource ID of the Discovery StorageContainer (control-plane binding)."
  value       = module.platform.storage_container_id
}

output "bookshelf_id" {
  description = "Resource ID of the optional Discovery Bookshelf (null when enable_bookshelf is false)."
  value       = one(module.bookshelf[*].id)
}

output "managed_identity_id" {
  description = "Resource ID of the workspace user-assigned managed identity (workspaceIdentity)."
  value       = module.platform.workspace_identity_id
}

output "managed_identity_principal_id" {
  description = "AAD object ID of the workspace user-assigned managed identity (workspaceIdentity)."
  value       = module.platform.workspace_identity_principal_id
}

output "cluster_identity_id" {
  description = "Resource ID of the Supercomputer cluster user-assigned managed identity (clusterIdentity)."
  value       = module.platform.cluster_identity_id
}

output "kubelet_identity_id" {
  description = "Resource ID of the Supercomputer kubelet user-assigned managed identity (kubeletIdentity)."
  value       = module.platform.kubelet_identity_id
}

output "workload_identity_id" {
  description = "Resource ID of the Supercomputer workload user-assigned managed identity (workloadIdentities)."
  value       = module.platform.workload_identity_id
}

output "storage_account_id" {
  description = "Resource ID of the storage account backing the Discovery StorageContainer."
  value       = module.platform.storage_account_id
}

output "vnet_id" {
  description = "Resource ID of the Workspace virtual network."
  value       = module.platform.workspace_vnet_id
}

output "supercomputer_vnet_id" {
  description = "Resource ID of the Supercomputer virtual network."
  value       = module.platform.supercomputer_vnet_id
}
