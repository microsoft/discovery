# -----------------------------------------------------------------------------
# outputs.tf
#
# Mirrors the outputs at the bottom of ../discovery.bicep so downstream
# tooling (Toolbox, scripts, azd wrappers) sees the same values.
# -----------------------------------------------------------------------------

output "supercomputer_id" {
  description = "Resource ID of the Discovery Supercomputer."
  value       = azapi_resource.supercomputer.id
}

output "node_pool_id" {
  description = "Resource ID of the Supercomputer node pool."
  value       = azapi_resource.node_pool.id
}

output "workspace_id" {
  description = "Resource ID of the Discovery Workspace."
  value       = azapi_resource.workspace.id
}

output "chat_model_deployment_id" {
  description = "Resource ID of the chat model deployment."
  value       = azapi_resource.chat_model.id
}

output "storage_container_id" {
  description = "Resource ID of the Discovery StorageContainer (control-plane binding)."
  value       = azapi_resource.discovery_storage_container.id
}

output "project_id" {
  description = "Resource ID of the Discovery Project."
  value       = azapi_resource.project.id
}

output "managed_identity_id" {
  description = "Resource ID of the workspace user-assigned managed identity (workspaceIdentity)."
  value       = azurerm_user_assigned_identity.workspace.id
}

output "managed_identity_principal_id" {
  description = "AAD object ID of the workspace user-assigned managed identity (workspaceIdentity)."
  value       = azurerm_user_assigned_identity.workspace.principal_id
}

output "cluster_identity_id" {
  description = "Resource ID of the Supercomputer cluster user-assigned managed identity (clusterIdentity)."
  value       = azurerm_user_assigned_identity.cluster.id
}

output "kubelet_identity_id" {
  description = "Resource ID of the Supercomputer kubelet user-assigned managed identity (kubeletIdentity)."
  value       = azurerm_user_assigned_identity.kubelet.id
}

output "workload_identity_id" {
  description = "Resource ID of the Supercomputer workload user-assigned managed identity (workloadIdentities)."
  value       = azurerm_user_assigned_identity.workload.id
}

output "storage_account_id" {
  description = "Resource ID of the storage account backing the Discovery StorageContainer."
  value       = azurerm_storage_account.outputs.id
}

output "vnet_id" {
  description = "Resource ID of the virtual network."
  value       = azurerm_virtual_network.this.id
}
