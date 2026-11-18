output "id" {
  description = "Resource ID of the Discovery Workspace"
  value       = azapi_resource.main.id
}

output "chat_model_deployment_ids" {
  description = "Resource IDs of chat model deployments keyed by name"
  value       = { for name, deployment in azapi_resource.chat_model_deployment : name => deployment.id }
}

output "project_ids" {
  description = "Resource IDs of projects keyed by name"
  value       = { for name, project in azapi_resource.project : name => project.id }
}