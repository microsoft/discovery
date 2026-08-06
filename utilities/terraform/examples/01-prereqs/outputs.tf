# -----------------------------------------------------------------------------
# examples/01-prereqs -- outputs
#
# Consumed by 02-supercomputer, 03-workspace, and 04-complete-e2e via
# terraform_remote_state.
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

# ---- storage ----------------------------------------------------------------

output "storage_account_id" {
  description = "Storage account resource ID."
  value       = azurerm_storage_account.outputs.id
}

output "storage_container_id" {
  description = "Discovery StorageContainer (control-plane binding) resource ID."
  value       = azapi_resource.discovery_storage_container.id
}
