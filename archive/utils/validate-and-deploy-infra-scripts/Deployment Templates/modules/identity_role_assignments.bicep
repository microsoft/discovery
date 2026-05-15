// This file assigns the necessary roles to the user-assigned managed identity (UAMI)
// The roles are: Microsoft Discovery Platform Contributor (Preview), Storage Blob Data Contributor, and ACRPull

param uamiPrincipalId string
param subscriptionId string
param scopeResourceGroupName string

// Define the role definition IDs
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var microsoftDiscoveryContributorRoleId = '01288891-85ee-45a7-b367-9db3b752fc65'

// Create a variable for the subscription scope
var subscriptionScope = '/subscriptions/${subscriptionId}'
var resourceGroupScope = '${subscriptionScope}/resourceGroups/${scopeResourceGroupName}'

// Microsoft Discovery Platform Contributor (Preview) role assignment
resource microsoftDiscoveryPlatformContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupScope, uamiPrincipalId, microsoftDiscoveryContributorRoleId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: extensionResourceId(
      subscriptionScope, 
      'Microsoft.Authorization/roleDefinitions', 
      microsoftDiscoveryContributorRoleId
    )
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Storage Blob Data Contributor role assignment
resource storageBlobDataContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupScope, uamiPrincipalId, storageBlobDataContributorRoleId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: extensionResourceId(
      subscriptionScope, 
      'Microsoft.Authorization/roleDefinitions', 
      storageBlobDataContributorRoleId
    )
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ACRPull role assignment
resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupScope, uamiPrincipalId, acrPullRoleId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: extensionResourceId(
      subscriptionScope, 
      'Microsoft.Authorization/roleDefinitions', 
      acrPullRoleId
    )
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}
