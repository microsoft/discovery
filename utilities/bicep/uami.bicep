@description('Azure region for all resources. Must be a Discovery-supported region.')
@allowed([
  'eastus'
  'swedencentral'
  'uksouth'
])
param location string = 'uksouth'

@description('Name of the Microsoft Discovery Supercomputer. Must be 3-24 characters, alphanumeric and hyphens only.')
@minLength(3)
@maxLength(24)
param supercomputerName string = 'sc-${uniqueString(resourceGroup().id)}'

@description('Name of the Node Pool created under the Supercomputer. Must be 1-12 lowercase alphanumeric characters, starting with a letter.')
@minLength(1)
@maxLength(12)
param nodePoolName string = 'nodepool1'

@description('Name of the Microsoft Discovery Workspace. Must be 3-24 characters, alphanumeric and hyphens only.')
@minLength(3)
@maxLength(24)
param workspaceName string = 'ws-${uniqueString(resourceGroup().id)}'

@description('Name of the Chat Model Deployment created under the Workspace.')
@minLength(3)
@maxLength(24)
param chatModelDeploymentName string = 'gpt-5-2'

@description('Name of the Microsoft Discovery Storage Container resource. Must be 3-24 characters, alphanumeric and hyphens only.')
@minLength(3)
@maxLength(24)
param storageContainerName string = 'stc-${uniqueString(resourceGroup().id)}'

@description('Name of the Project created under the Workspace. Must be 3-24 characters, alphanumeric and hyphens only.')
@minLength(3)
@maxLength(24)
param projectName string = 'prj-${uniqueString(resourceGroup().id)}'

@description('Name of the Virtual Network.')
param vnetName string = 'vnet-${uniqueString(resourceGroup().id)}'

@description('Name of the Workspace User-Assigned Managed Identity (workspace control plane + data plane).')
param workspaceIdentityName string = 'uami-ws-${uniqueString(resourceGroup().id)}'

@description('Name of the Supercomputer Cluster User-Assigned Managed Identity (AKS control plane).')
param clusterIdentityName string = 'uami-cluster-${uniqueString(resourceGroup().id)}'

@description('Name of the Supercomputer Kubelet User-Assigned Managed Identity (node-level image pulls + startup data access).')
param kubeletIdentityName string = 'uami-kubelet-${uniqueString(resourceGroup().id)}'

@description('Name of the Supercomputer Workload User-Assigned Managed Identity (agent/tool federated data access - keep minimally privileged).')
param workloadIdentityName string = 'uami-workload-${uniqueString(resourceGroup().id)}'

@description('Globally unique name of the Azure Storage Account (3-24 lowercase alphanumeric characters).')
@minLength(3)
@maxLength(24)
param storageAccountName string = 'stg${uniqueString(resourceGroup().id)}'

@description('Name of the blob container inside the Storage Account used for Discovery outputs.')
param blobContainerName string = 'discoveryoutputs'

@description('Address space for the Virtual Network.')
param vnetAddressPrefix string = '10.0.0.0/16'

@description('Address prefix for the Supercomputer Node Pool subnet.')
param supercomputerNodepoolSubnetPrefix string = '10.0.1.0/24'

@description('Address prefix for the AKS system subnet used by the Supercomputer.')
param aksSubnetPrefix string = '10.0.2.0/24'

@description('Address prefix for the Workspace subnet (delegated to Microsoft.App/environments).')
param workspaceSubnetPrefix string = '10.0.3.0/24'

@description('Address prefix for the Private Endpoint subnet.')
param privateEndpointSubnetPrefix string = '10.0.4.0/24'

@description('Address prefix for the Agent subnet.')
param agentSubnetPrefix string = '10.0.5.0/24'

@description('Address prefix for Search Subnet.')
param searchSubnetPrefix string = '10.0.6.0/24'

@description('VM SKU for the Node Pool.')
param nodePoolVmSize string = 'Standard_D4s_v6'

@description('Maximum number of nodes in the Node Pool.')
@minValue(1)
param nodePoolMaxNodeCount int = 3

@description('Minimum number of nodes in the Node Pool (0 allows scale-to-zero).')
@minValue(0)
param nodePoolMinNodeCount int = 0

@description('Scale set priority for the Node Pool.')
@allowed([
  'Regular'
  'Spot'
])
param nodePoolScaleSetPriority string = 'Regular'

@description('Chat model format.')
param chatModelFormat string = 'OpenAI'

@description('Chat model name to deploy.')
param chatModelName string = 'gpt-5.2'

@description('Enable GitHub Copilot and AI features in the Discovery workspace via the discovery.workbench.enableGhcpAiFeatures tag.')
param enableGhcpAiFeatures bool = true

@description('Enable the VS Code Extension Marketplace in the Discovery workspace via the discovery.workbench.enableExtensions tag.')
param enableExtensions bool = true

@description('Workspace network isolation mode via the NetworkIsolation tag. Must be true whenever agentSubnetId/privateEndpointSubnetId/workspaceSubnetId are supplied: the RP then VNet-injects the managed Container Apps environment and creates private endpoints (Cosmos, Search, etc.) in the privateEndpointSubnet. Setting this false while passing subnet IDs produces a broken hybrid where Cosmos public access is disabled but no private endpoint is created, leaving the managed backend unable to reach Cosmos.')
param networkIsolation bool = true

// Built-in role definition IDs
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var discoveryPlatformContributorRoleId = '01288891-85ee-45a7-b367-9db3b752fc65'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var networkContributorRoleId = '4d97b98b-1d4f-4787-a291-c67834d212e7'
var managedIdentityOperatorRoleId = 'f1a07417-d97a-45cb-824c-7a7467783830'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: 'supercomputerNodepoolSubnet'
        properties: {
          addressPrefix: supercomputerNodepoolSubnetPrefix
        }
      }
      {
        name: 'aksSubnet'
        properties: {
          addressPrefix: aksSubnetPrefix
        }
      }
      {
        name: 'workspaceSubnet'
        properties: {
          addressPrefix: workspaceSubnetPrefix
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'privateEndpointSubnet'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
        }
      }
      {
        name: 'agentSubnet'
        properties: {
          addressPrefix: agentSubnetPrefix
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'searchSubnet'
        properties: {
          addressPrefix: searchSubnetPrefix
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
    ]
  }
}

resource workspaceIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: workspaceIdentityName
  location: location
  properties: {
    isolationScope: 'Regional'
  }
}

resource clusterIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: clusterIdentityName
  location: location
  properties: {
    isolationScope: 'Regional'
  }
}

resource kubeletIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: kubeletIdentityName
  location: location
  properties: {
    isolationScope: 'Regional'
  }
}

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: workloadIdentityName
  location: location
  properties: {
    isolationScope: 'Regional'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    cors: {
      corsRules: [
        {
          allowedOrigins: [
            'https://studio.discovery.microsoft.com'
            'https://*.vscode-cdn.net'
            'https://vscode.dev'
          ]
          allowedMethods: [
            'GET'
            'HEAD'
            'DELETE'
            'PUT'
          ]
          allowedHeaders: [
            '*'
          ]
          exposedHeaders: [
            '*'
          ]
          maxAgeInSeconds: 200
        }
      ]
    }
  }
}

resource blobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: blobContainerName
}

// -----------------------------------------------------------------------------
// Least-privilege role assignments (per identity slot)
// Source: https://learn.microsoft.com/azure/microsoft-discovery/concept-managed-identities
//         #advanced-configuration-granular-role-assignments-per-identity
// -----------------------------------------------------------------------------

// Workspace identity: manage Discovery workspace resources (projects, deployments, storage containers).
resource workspaceDiscoveryPlatformContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, workspaceIdentity.id, discoveryPlatformContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      discoveryPlatformContributorRoleId
    )
    principalId: workspaceIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Workspace identity: read/write workspace, chat-model, and project data in the backing storage account.
resource workspaceStorageBlobDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, workspaceIdentity.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: workspaceIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Reference the AKS subnet so the cluster identity's Network Contributor role is scoped to that subnet only.
resource aksSubnetResource 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: 'aksSubnet'
}

// Cluster identity: AKS control plane joins nodes and manages the load balancer on the AKS subnet only.
resource clusterNetworkContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aksSubnetResource.id, clusterIdentity.id, networkContributorRoleId)
  scope: aksSubnetResource
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', networkContributorRoleId)
    principalId: clusterIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Kubelet identity: must hold Managed Identity Operator on the cluster identity (Discovery API requirement).
resource kubeletManagedIdentityOperatorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(clusterIdentity.id, kubeletIdentity.id, managedIdentityOperatorRoleId)
  scope: clusterIdentity
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', managedIdentityOperatorRoleId)
    principalId: kubeletIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Kubelet identity: pull custom tool container images - scoped to resource group (no ACR defined in this template).
resource kubeletAcrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, kubeletIdentity.id, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: kubeletIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Kubelet identity: read workload artifacts/inputs from storage during pod startup.
resource kubeletStorageBlobDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, kubeletIdentity.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: kubeletIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Workload identity: minimally privileged - only data-plane access used by agent tool execution.
resource workloadStorageBlobDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, workloadIdentity.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource supercomputer 'Microsoft.Discovery/supercomputers@2026-06-01' = {
  name: supercomputerName
  location: location
  tags: {
    version: 'v2'
  }
  dependsOn: [
    vnet
    clusterNetworkContributorAssignment
    kubeletManagedIdentityOperatorAssignment
  ]
  properties: {
    subnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'aksSubnet')
    identities: {
      clusterIdentity: {
        id: clusterIdentity.id
      }
      kubeletIdentity: {
        id: kubeletIdentity.id
      }
      workloadIdentities: {
        '${workloadIdentity.id}': {}
      }
    }
  }
}

resource nodePool 'Microsoft.Discovery/supercomputers/nodePools@2026-06-01' = {
  parent: supercomputer
  name: nodePoolName
  location: location
  dependsOn: [
    vnet
  ]
  properties: {
    subnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'supercomputerNodepoolSubnet')
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
    NetworkIsolation: string(networkIsolation)
  }
  dependsOn: [
    vnet
  ]
  properties: {
    workspaceIdentity: {
      id: workspaceIdentity.id
    }
    supercomputerIds: [
      supercomputer.id
    ]
    agentSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'agentSubnet')
    privateEndpointSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'privateEndpointSubnet')
    workspaceSubnetId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'workspaceSubnet')
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

@description('Resource ID of the Supercomputer.')
output supercomputerId string = supercomputer.id

@description('Resource ID of the Node Pool.')
output nodePoolId string = nodePool.id

@description('Resource ID of the Workspace.')
output workspaceId string = workspace.id

@description('Resource ID of the Chat Model Deployment.')
output chatModelDeploymentId string = chatModelDeployment.id

@description('Resource ID of the Discovery Storage Container.')
output storageContainerId string = discoveryStorageContainer.id

@description('Resource ID of the Project.')
output projectId string = project.id

@description('Resource ID of the Workspace User-Assigned Managed Identity.')
output workspaceIdentityId string = workspaceIdentity.id

@description('Resource ID of the Supercomputer Cluster User-Assigned Managed Identity.')
output clusterIdentityId string = clusterIdentity.id

@description('Resource ID of the Supercomputer Kubelet User-Assigned Managed Identity.')
output kubeletIdentityId string = kubeletIdentity.id

@description('Resource ID of the Supercomputer Workload User-Assigned Managed Identity.')
output workloadIdentityId string = workloadIdentity.id

@description('Resource ID of the Storage Account.')
output storageAccountId string = storageAccount.id

@description('Resource ID of the Virtual Network.')
output vnetId string = vnet.id
