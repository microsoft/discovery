// Stage 4 — Discovery platform baseline template.
// Deploys the platform in one RG-scoped deployment: supercomputer (+ node pool),
// bookshelf storage container, workspace, validation chat model, and project.
// Parameters are generated from the Stage 1 config by stage4_deploy.ps1
// (New-Stage4BicepParamFile); do not hand-edit values — change config.json and re-run.

targetScope = 'resourceGroup'

@description('Region for all Discovery resources. Must equal the BYO VNet/subnet region.')
param location string

@description('workloadRegion tag (discovery.overridemrgregion) for the managed RGs.')
param workloadRegion string = location

param supercomputerName string
param workspaceName string
param projectName string
param nodePoolName string
param storageContainerName string
param chatModelDeploymentName string = 'gpt-5-4'
param chatModelName string = 'gpt-5.4'

@description('User-assigned managed identity resource id used by all platform resources.')
param managedIdentityId string

@description('managedcluster-role subnet id (AKS control plane / management).')
param managedClusterSubnetId string
@description('nodepool-role subnet id.')
param nodePoolSubnetId string
@description('agent-containerapp-role subnet id.')
param agentSubnetId string
@description('workspace-containerapp-role subnet id.')
param workspaceSubnetId string
@description('private-endpoints-role subnet id.')
param privateEndpointSubnetId string

@description('Storage account id backing the bookshelf container.')
param storageAccountId string = ''
@description('Whether the bookshelf storage container is in scope.')
param bookshelfInScope bool = true

@description('AKS egress model, decided at planning (Stage 1). UserDefinedRouting = forced tunneling via the customer firewall/NVA; LoadBalancer = Azure-managed egress.')
@allowed([
  'UserDefinedRouting'
  'LoadBalancer'
])
param outboundType string = 'UserDefinedRouting'

param systemSku string = ''
param nodePoolVmSize string = 'Standard_D4ds_v6'
param nodePoolMinNodeCount int = 0
param nodePoolMaxNodeCount int = 3
param nodePoolScaleSetPriority string = 'Regular'
param publicNetworkAccess string = 'Disabled'

#disable-next-line BCP081
resource supercomputer 'Microsoft.Discovery/supercomputers@2026-06-01' = {
  name: supercomputerName
  location: location
  tags: {
    version: 'v2'
    'discovery.overridemrgregion': workloadRegion
  }
  properties: {
    subnetId: managedClusterSubnetId
    managementSubnetId: managedClusterSubnetId
    outboundType: outboundType
    systemSku: empty(systemSku) ? null : systemSku
    identities: {
      clusterIdentity: { id: managedIdentityId }
      kubeletIdentity: { id: managedIdentityId }
      workloadIdentities: {
        '${managedIdentityId}': {}
      }
    }
  }
}

#disable-next-line BCP081
resource nodePool 'Microsoft.Discovery/supercomputers/nodePools@2026-06-01' = {
  parent: supercomputer
  name: nodePoolName
  location: location
  properties: {
    subnetId: nodePoolSubnetId
    vmSize: nodePoolVmSize
    minNodeCount: nodePoolMinNodeCount
    maxNodeCount: nodePoolMaxNodeCount
    scaleSetPriority: nodePoolScaleSetPriority
  }
}

#disable-next-line BCP081
resource storageContainer 'Microsoft.Discovery/storageContainers@2026-06-01' = if (bookshelfInScope && !empty(storageAccountId)) {
  name: storageContainerName
  location: location
  properties: {
    storageStore: {
      kind: 'AzureStorageBlob'
      storageAccountId: storageAccountId
    }
  }
}

#disable-next-line BCP081
resource workspace 'Microsoft.Discovery/workspaces@2026-06-01' = {
  name: workspaceName
  location: location
  tags: {
    version: 'v2'
    'discovery.workbench.enableGhcpAiFeatures': 'true'
    'discovery.workbench.enableExtensions': 'true'
    'discovery.overridemrgregion': workloadRegion
    NetworkIsolation: 'true'
    SkipAssociateKeyVaultToNsp: 'true'
    SkipAssociateCosmosDBToNsp: 'true'
    SkipAssociateStorageAccountsToNsp: 'true'
  }
  properties: {
    workspaceIdentity: { id: managedIdentityId }
    supercomputerIds: [ supercomputer.id ]
    agentSubnetId: agentSubnetId
    workspaceSubnetId: workspaceSubnetId
    privateEndpointSubnetId: privateEndpointSubnetId
    publicNetworkAccess: publicNetworkAccess
  }
  dependsOn: [ nodePool ]
}

#disable-next-line BCP081
resource chatModel 'Microsoft.Discovery/workspaces/chatModelDeployments@2026-06-01' = {
  parent: workspace
  name: chatModelDeploymentName
  location: location
  properties: {
    modelFormat: 'OpenAI'
    modelName: chatModelName
  }
}

#disable-next-line BCP081
resource project 'Microsoft.Discovery/workspaces/projects@2026-06-01' = {
  parent: workspace
  name: projectName
  location: location
  properties: {
    storageContainerIds: (bookshelfInScope && !empty(storageAccountId)) ? [ storageContainer.id ] : []
  }
  dependsOn: [ chatModel ]
}

output supercomputerId string = supercomputer.id
output workspaceId string = workspace.id
output projectId string = project.id
