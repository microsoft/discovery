# -----------------------------------------------------------------------------
# modules/platform -- outputs
#
# IDs consumed by the control-plane modules (supercomputer, workspace,
# bookshelf) and surfaced by the root and staged examples.
# -----------------------------------------------------------------------------

output "resource_group_id" {
  description = "Resource ID of the target resource group."
  value       = data.azurerm_resource_group.rg.id
}

output "resource_group_name" {
  description = "Name of the target resource group."
  value       = data.azurerm_resource_group.rg.name
}

output "location" {
  description = "Control-plane region."
  value       = var.location
}

output "supercomputer_infrastructure_location" {
  description = "Region for the Supercomputer managed resource group (GPU)."
  value       = var.supercomputer_infrastructure_location
}

output "name_suffix" {
  description = "Resolved resource name suffix."
  value       = local.suffix
}

# ---- subnets ----------------------------------------------------------------

output "aks_subnet_id" {
  description = "AKS system subnet ID (Supercomputer)."
  value       = azurerm_subnet.aks.id
}

output "supercomputer_nodepool_subnet_id" {
  description = "Supercomputer node pool subnet ID."
  value       = azurerm_subnet.supercomputer_nodepool.id
}

output "workspace_subnet_id" {
  description = "Workspace subnet ID."
  value       = azurerm_subnet.workspace.id
}

output "private_endpoint_subnet_id" {
  description = "Private endpoint subnet ID."
  value       = azurerm_subnet.private_endpoint.id
}

output "agent_subnet_id" {
  description = "Agent subnet ID."
  value       = azurerm_subnet.agent.id
}

output "search_subnet_id" {
  description = "Search subnet ID."
  value       = azurerm_subnet.search.id
}

# ---- identities -------------------------------------------------------------

output "workspace_identity_id" {
  description = "Workspace user-assigned managed identity ID."
  value       = azurerm_user_assigned_identity.workspace.id
}

output "workspace_identity_principal_id" {
  description = "Workspace user-assigned managed identity principal (object) ID."
  value       = azurerm_user_assigned_identity.workspace.principal_id
}

output "cluster_identity_id" {
  description = "Cluster user-assigned managed identity ID."
  value       = azurerm_user_assigned_identity.cluster.id
}

output "kubelet_identity_id" {
  description = "Kubelet user-assigned managed identity ID."
  value       = azurerm_user_assigned_identity.kubelet.id
}

output "workload_identity_id" {
  description = "Workload user-assigned managed identity ID."
  value       = azurerm_user_assigned_identity.workload.id
}

output "workload_identity_client_id" {
  description = "Workload user-assigned managed identity client ID."
  value       = azurerm_user_assigned_identity.workload.client_id
}

# ---- storage ----------------------------------------------------------------

output "storage_account_id" {
  description = "Storage account resource ID."
  value       = azurerm_storage_account.outputs.id
}

output "storage_account_name" {
  description = "Storage account name."
  value       = azurerm_storage_account.outputs.name
}

output "storage_container_id" {
  description = "Discovery StorageContainer (control-plane binding) resource ID."
  value       = azapi_resource.discovery_storage_container.id
}

# ---- networks ---------------------------------------------------------------

output "workspace_vnet_id" {
  description = "Resource ID of the Workspace virtual network."
  value       = azurerm_virtual_network.workspace.id
}

output "supercomputer_vnet_id" {
  description = "Resource ID of the Supercomputer virtual network."
  value       = azurerm_virtual_network.supercomputer.id
}
