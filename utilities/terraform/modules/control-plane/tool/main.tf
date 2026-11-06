resource "azapi_resource" "main" {
  type      = "Microsoft.Discovery/tools@2026-06-01"
  name      = var.name
  location  = var.location
  parent_id = var.resource_group_id
  tags      = var.tags

  body = {
    properties = {
      definitionContent    = var.definition_content
      environmentVariables = var.environment_variables
      version              = var.tool_version
    }
  }

  timeouts {
    create = var.resource_timeouts.create
    update = var.resource_timeouts.update
    delete = var.resource_timeouts.delete
  }
}