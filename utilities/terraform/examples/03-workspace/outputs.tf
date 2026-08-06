# -----------------------------------------------------------------------------
# examples/03-workspace -- outputs
# -----------------------------------------------------------------------------

output "workspace_id" {
  description = "Resource ID of the Discovery Workspace."
  value       = module.workspace.id
}
