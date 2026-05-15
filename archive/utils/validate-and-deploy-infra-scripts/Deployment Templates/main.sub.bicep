targetScope = 'subscription'

// az deployment sub create --location <location> --template-file main.sub.bicep

param location string = deployment().location
param prefix string = 'test'
param suffix string = '001'
param resourceGroupName string = '${prefix}rg${suffix}'

param vnetName string = '${prefix}vnet'
param storageAccountName string = '${prefix}sa${suffix}'
param uamiName string = '${prefix}UAMI${suffix}'
param discoveryStorageName string = '${prefix}DS${suffix}'
param supercomputerName string = '${prefix}SC${suffix}'
param discoveryWorkspace string = '${prefix}Wkp${suffix}'

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: resourceGroupName
  location: location
}

module vnetModule './modules/vnet.bicep' = {
  name: 'vnetDeployment'
  scope: rg
  params: {
    vnetName: vnetName
    location: location
  }
}

module identityModule './modules/identity.bicep' = {
  name: 'identityDeployment'
  scope: rg
  params: {
    uamiName: uamiName
    location: location
  }
}

module identityRoleAssignmentsModule './modules/identity_role_assignments.bicep' = {
  name: 'identityRoleAssignmentsDeployment'
  scope: rg
  params: {
    uamiPrincipalId: identityModule.outputs.uamiPrincipalId
    subscriptionId: subscription().subscriptionId
    scopeResourceGroupName: rg.name
  }
}

module storageModule './modules/storage.bicep' = {
  name: 'storageDeployment'
  scope: rg
  params: {
    storageAccountName: storageAccountName
    location: location
    storageSubnetId: vnetModule.outputs.storageSubnetId
    aksSubnetId: vnetModule.outputs.aksSubnetId
    supercomputerNodepoolSubnetId: vnetModule.outputs.supercomputerNodepoolSubnetId
  }
}

module discoveryStorageModule './modules/discovery-storage.bicep' = {
  name: 'discoveryStorageDeployment'
  scope: rg
  params: {
    discoveryStorageName: discoveryStorageName
    location: location
    storageSubnetId: vnetModule.outputs.storageSubnetId
  }
}

module supercomputerModule './modules/supercomputer.bicep' = {
  name: 'supercomputerDeployment'
  scope: rg
  params: {
    location: location
    uamiId: identityModule.outputs.uamiId
    uamiPrincipalId: identityModule.outputs.uamiPrincipalId
    uamiClientId: identityModule.outputs.uamiClientId
    aksSubnetId: vnetModule.outputs.aksSubnetId
    supercomputerNodepoolSubnetId: vnetModule.outputs.supercomputerNodepoolSubnetId
    supercomputerName: supercomputerName
  }
}

module discoveryModule './modules/discovery.bicep' = {
  name: 'discoveryDeployment'
  scope: rg
  params: {
    discoveryWorkspace: discoveryWorkspace
    location: location
    discoveryStorageId: discoveryStorageModule.outputs.discoveryStorageId
    supercomputerId: supercomputerModule.outputs.supercomputerId
    uamiId: identityModule.outputs.uamiId
  }
}
