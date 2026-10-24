@description('Discovery-only resume deployment. Existing foundation resources are never redeployed.')
@allowed([
  'eastus'
  'swedencentral'
  'uksouth'
])
param location string
param overridemrgregion string = location
param supercomputerName string
param nodePoolName string = 'nodepool1'
param workspaceName string
param chatModelDeploymentName string = 'gpt-5-4'
param storageContainerName string
param projectName string
param vnetName string
param managedIdentityName string
param storageAccountName string
param nodePoolVmSize string = 'Standard_D4s_v6'

param systemSku string = 'Standard_D4s_v6'
@minValue(0)
param nodePoolMinNodeCount int = 0
@minValue(1)
param nodePoolMaxNodeCount int = 3
@allowed([
  'Regular'
  'Spot'
])
param nodePoolScaleSetPriority string = 'Regular'
param chatModelFormat string = 'OpenAI'
param chatModelName string = 'gpt-5.4'
param enableGhcpAiFeatures bool = true
param enableExtensions bool = true
param networkIsolation bool = true

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: managedIdentityName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource supercomputer 'Microsoft.Discovery/supercomputers@2026-06-01' = {
  name: supercomputerName
  location: location
  tags: {
    version: 'v2'
    'discovery.overridemrgregion': overridemrgregion
  }
  properties: {
    subnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'aksSubnet')
    systemSku: systemSku
    managementSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'sc-mgmt')
    identities: {
      clusterIdentity: {
        id: managedIdentity.id
      }
      kubeletIdentity: {
        id: managedIdentity.id
      }
      workloadIdentities: {
        '${managedIdentity.id}': {}
      }
    }
  }
}

resource nodePool 'Microsoft.Discovery/supercomputers/nodePools@2026-06-01' = {
  parent: supercomputer
  name: nodePoolName
  location: location
  properties: {
    subnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'supercomputerNodepoolSubnet')
    vmSize: nodePoolVmSize
    maxNodeCount: nodePoolMaxNodeCount
    minNodeCount: nodePoolMinNodeCount
    scaleSetPriority: nodePoolScaleSetPriority
  }
}

resource workspace 'Microsoft.Discovery/workspaces@2026-06-01' = {
  name: workspaceName
  location: location
  tags: {
    version: 'v2'
    'discovery.workbench.enableGhcpAiFeatures': string(enableGhcpAiFeatures)
    'discovery.workbench.enableExtensions': string(enableExtensions)
    'discovery.overridemrgregion': overridemrgregion
    NetworkIsolation: string(networkIsolation)
  }
  properties: {
    workspaceIdentity: {
      id: managedIdentity.id
    }
    supercomputerIds: [
      supercomputer.id
    ]
    agentSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'agentSubnet')
    privateEndpointSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'privateEndpointSubnet')
    workspaceSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'workspaceSubnet')
  }
}

resource chatModelDeployment 'Microsoft.Discovery/workspaces/chatModelDeployments@2026-06-01' = {
  parent: workspace
  name: chatModelDeploymentName
  location: location
  properties: {
    modelFormat: chatModelFormat
    modelName: chatModelName
  }
}

resource discoveryStorageContainer 'Microsoft.Discovery/storageContainers@2026-06-01' = {
  name: storageContainerName
  location: location
  properties: {
    storageStore: {
      kind: 'AzureStorageBlob'
      storageAccountId: storageAccount.id
    }
  }
}

resource project 'Microsoft.Discovery/workspaces/projects@2026-06-01' = {
  parent: workspace
  name: projectName
  location: location
  dependsOn: [
    chatModelDeployment
  ]
  properties: {
    storageContainerIds: [
      discoveryStorageContainer.id
    ]
  }
}

output supercomputerId string = supercomputer.id
output nodePoolId string = nodePool.id
output workspaceId string = workspace.id
output chatModelDeploymentId string = chatModelDeployment.id
output storageContainerId string = discoveryStorageContainer.id
output projectId string = project.id
