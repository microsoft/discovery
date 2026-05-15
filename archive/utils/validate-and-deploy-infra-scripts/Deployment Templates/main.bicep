// az deployment group create --resource-group myResourceGroup --template-file main.bicep 
// ensure that the resource group exists and the correct subscription is chosen in az login

param location string = resourceGroup().location
param prefix string = 'test'
param suffix string = '001'

param vnetName string = '${prefix}vnet'
param storageAccountName string = '${prefix}sa${suffix}'
param uamiName string = '${prefix}UAMI${suffix}'
param discoveryStorageName string = '${prefix}DS${suffix}'
param supercomputerName string = '${prefix}SC${suffix}'
param discoveryWorkspace string = '${prefix}Wkp${suffix}'


module vnetModule './modules/vnet.bicep' = {
  name: 'vnetDeployment'
  params: {
    vnetName: vnetName
    location: location
  }
}

module identityModule './modules/identity.bicep' = {
  name: 'identityDeployment'
  params: {
    uamiName: uamiName
    location: location
  }
}

module identityRoleAssignmentsModule './modules/identity_role_assignments.bicep' = {
  name: 'identityRoleAssignmentsDeployment'
  params: {
    uamiPrincipalId: identityModule.outputs.uamiPrincipalId
    subscriptionId: subscription().subscriptionId
    scopeResourceGroupName: resourceGroup().name
  }
}

module storageModule './modules/storage.bicep' = {
  name: 'storageDeployment'
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
  params: {
    discoveryStorageName: discoveryStorageName
    location: location
    storageSubnetId: vnetModule.outputs.storageSubnetId
  }
}

module supercomputerModule './modules/supercomputer.bicep' = {
  name: 'supercomputerDeployment'
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
    params: {
      discoveryWorkspace: discoveryWorkspace
      location: location
      discoveryStorageId: discoveryStorageModule.outputs.discoveryStorageId
      supercomputerId: supercomputerModule.outputs.supercomputerId
      uamiId: identityModule.outputs.uamiId
    }
  }
