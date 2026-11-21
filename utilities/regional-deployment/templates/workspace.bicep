@allowed([
  'eastus'
  'uksouth'
  'swedencentral'
])
param location string
param overridemrgregion string
param supercomputerName string
param storageContainerName string
param storageAccountName string
param existingVnetName string
param workspaceName string
param projectName string
param chatModelDeploymentName string = 'gpt-5-4'
param chatModelName string = 'gpt-5.4'
param vnetName string
param managedIdentityName string
param natGatewayName string
param natGatewayPublicIpName string
param platformRoleAssignmentName string
param acrPullRoleAssignmentName string
param blobRoleAssignmentName string
param networkRoleAssignmentName string
param vnetAddressPrefix string = '10.10.0.0/16'
param workspaceSubnetPrefix string = '10.10.3.0/24'
param privateEndpointSubnetPrefix string = '10.10.4.0/24'
param agentSubnetPrefix string = '10.10.5.0/24'

resource supercomputer 'Microsoft.Discovery/supercomputers@2026-06-01' existing = {
  name: supercomputerName
}
resource storageContainer 'Microsoft.Discovery/storageContainers@2026-06-01' existing = {
  name: storageContainerName
}
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource retainedVnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: existingVnetName
}
resource blobDns 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: natGatewayPublicIpName
  location: overridemrgregion
  sku: { name: 'Standard', tier: 'Regional' }
  properties: { publicIPAllocationMethod: 'Static', publicIPAddressVersion: 'IPv4' }
}
resource nat 'Microsoft.Network/natGateways@2024-05-01' = {
  name: natGatewayName
  location: overridemrgregion
  sku: { name: 'Standard' }
  properties: { publicIpAddresses: [{ id: publicIp.id }] }
}
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: overridemrgregion
  properties: {
    addressSpace: { addressPrefixes: [vnetAddressPrefix] }
    subnets: [
      {
        name: 'workspaceSubnet'
        properties: {
          addressPrefix: workspaceSubnetPrefix
          defaultOutboundAccess: false
          natGateway: { id: nat.id }
          delegations: [{ name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }]
          serviceEndpoints: [{ service: 'Microsoft.Storage' }]
        }
      }
      {
        name: 'agentSubnet'
        properties: {
          addressPrefix: agentSubnetPrefix
          defaultOutboundAccess: false
          natGateway: { id: nat.id }
          delegations: [{ name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }]
          serviceEndpoints: [{ service: 'Microsoft.Storage' }]
        }
      }
      {
        name: 'privateEndpointSubnet'
        properties: { addressPrefix: privateEndpointSubnetPrefix, defaultOutboundAccess: false }
      }
    ]
  }
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: managedIdentityName
  location: overridemrgregion
  properties: { isolationScope: 'Regional' }
}
resource platformRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: platformRoleAssignmentName
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '01288891-85ee-45a7-b367-9db3b752fc65')
  }
}
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: acrPullRoleAssignmentName
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}
resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: blobRoleAssignmentName
  scope: storageAccount
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}
resource networkRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: networkRoleAssignmentName
  scope: vnet
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7')
  }
}
resource toRetainedVnet 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01' = {
  parent: vnet
  name: 'peer-to-retained-discovery'
  properties: {
    remoteVirtualNetwork: { id: retainedVnet.id }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: false
    allowGatewayTransit: false
    useRemoteGateways: false
  }
}
resource fromRetainedVnet 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01' = {
  parent: retainedVnet
  name: 'peer-to-${vnetName}'
  properties: {
    remoteVirtualNetwork: { id: vnet.id }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: false
    allowGatewayTransit: false
    useRemoteGateways: false
  }
}
// Reuse the original Blob endpoint and A record; a second endpoint could overwrite shared DNS.
resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobDns
  name: 'link-${vnetName}'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}
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
  dependsOn: [platformRole, acrPullRole, blobRole, networkRole, toRetainedVnet, fromRetainedVnet, blobDnsLink]
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
output reusedSupercomputerId string = supercomputer.id
output reusedStorageContainerId string = storageContainer.id
