output "id" {
  description = "Resource ID of the Discovery Supercomputer"
  value       = azapi_resource.main.id
}

output "node_pool_ids" {
  description = "Resource IDs of node pools keyed by node pool name"
  value       = { for name, node_pool in azapi_resource.node_pool : name => node_pool.id }
}