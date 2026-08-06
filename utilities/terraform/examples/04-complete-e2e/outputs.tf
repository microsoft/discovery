# -----------------------------------------------------------------------------
# examples/04-complete-e2e -- outputs
# -----------------------------------------------------------------------------

output "workspace_id" {
  description = "Resource ID of the (existing) Discovery Workspace this root completed."
  value       = local.workspace_id
}

output "chat_model_deployment_id" {
  description = "Resource ID of the chat model deployment."
  value       = azapi_resource.chat_model.id
}

output "project_id" {
  description = "Resource ID of the Discovery Project."
  value       = azapi_resource.project.id
}
