# -----------------------------------------------------------------------------
# examples/02-supercomputer -- outputs
# -----------------------------------------------------------------------------

output "supercomputer_id" {
  description = "Resource ID of the Discovery Supercomputer."
  value       = module.supercomputer.id
}

output "node_pool_ids" {
  description = "Resource IDs of node pools keyed by name."
  value       = module.supercomputer.node_pool_ids
}
