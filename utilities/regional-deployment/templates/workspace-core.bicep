param location string
param overridemrgregion string
param supercomputerName string
param storageContainerName string
param workspaceName string
param projectName string
param chatModelDeploymentName string = 'gpt-5-4'
param chatModelName string = 'gpt-5.4'
param vnetName string
param managedIdentityName string

resource supercomputer 'Microsoft.Discovery/supercomputers@2026-06-01' existing = { name: supercomputerName }
resource storageContainer 'Microsoft.Discovery/storageContainers@2026-06-01' existing = { name: storageContainerName }
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = { name: vnetName }
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = { name: managedIdentityName }
resource workspace 'Microsoft.Discovery/workspaces@2026-06-01' = {
  name: workspaceName
  location: location
  tags: {
    version: 'v2'
    'discovery.overridemrgregion': overridemrgregion
    'discovery.workbench.enableGhcpAiFeatures': 'True'
    'discovery.workbench.enableExtensions': 'True'
    NetworkIsolation: 'True'
  }
  properties: {
    workspaceIdentity: { id: identity.id }
    supercomputerIds: [supercomputer.id]
    workspaceSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'workspaceSubnet')
    agentSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'agentSubnet')
    privateEndpointSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'privateEndpointSubnet')
  }
}
resource chatModel 'Microsoft.Discovery/workspaces/chatModelDeployments@2026-06-01' = {
  parent: workspace
  name: chatModelDeploymentName
  location: location
  properties: { modelFormat: 'OpenAI', modelName: chatModelName }
}
resource project 'Microsoft.Discovery/workspaces/projects@2026-06-01' = {
  parent: workspace
  name: projectName
  location: location
  dependsOn: [chatModel]
  properties: { storageContainerIds: [storageContainer.id] }
}
output workspaceId string = workspace.id
