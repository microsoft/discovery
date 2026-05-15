@description('The Azure region where resources will be deployed')
param location string

@description('Prefix for all resource names')
param prefix string

@description('The UAMI to use')
param uamiId string

@description('ARM ID for HN Blob account')
param hnBlobAccountId string

@description('ARM ID for non-HN Blob account')
param nohnBlobAccountId string

@description('ARM ID for inaccessible Blob account')
param noaccBlobAccountId string

@description('ARM ID for Discovery Storage')
param discoveryStorageId string

// Uses @onlyIfNotExists() since dc/da do not currently support re-PUT.

// HN and non-HN blob account DCs, each with data assets pointing to a container and a subpath
@onlyIfNotExists()
resource hnBlobDataContainer 'Microsoft.Discovery/datacontainers@2025-07-01-preview' = {
  name: 'sc-${prefix}-hnblob-dc'
  location: location
  properties: {
    dataStore: {
      kind: 'AzureStorageBlob'
      storageAccountId: hnBlobAccountId
    }
    credentials: [
      {
        identityId: uamiId
        name: 'uami'
        kind: 'ManagedIdentity'
        description: 'UAMI for access'
      }
    ]
  }
}

@onlyIfNotExists()
resource hnBlobDataAsset 'Microsoft.Discovery/datacontainers/dataassets@2025-07-01-preview' = {
  parent: hnBlobDataContainer
  name: 'sc-${prefix}-da'
  location: location
  properties: {
    description: 'Blob container data asset'
    path: '/assets'
  }
}

@onlyIfNotExists()
resource hnBlobSubDataAsset 'Microsoft.Discovery/datacontainers/dataassets@2025-07-01-preview' = {
  parent: hnBlobDataContainer
  name: 'sc-${prefix}-subda'
  location: location
  properties: {
    description: 'Blob container subfolder data asset'
    path: '/assets/subdir'
  }
}

@onlyIfNotExists()
resource nohnBlobDataContainer 'Microsoft.Discovery/datacontainers@2025-07-01-preview' = {
  name: 'sc-${prefix}-nohnblob-dc'
  location: location
  properties: {
    dataStore: {
      kind: 'AzureStorageBlob'
      storageAccountId: nohnBlobAccountId
    }
    credentials: [
      {
        identityId: uamiId
        name: 'uami'
        kind: 'ManagedIdentity'
        description: 'UAMI for access'
      }
    ]
  }
}

@onlyIfNotExists()
resource nohnBlobDataAsset 'Microsoft.Discovery/datacontainers/dataassets@2025-07-01-preview' = {
  parent: nohnBlobDataContainer
  name: 'sc-${prefix}-da'
  location: location
  properties: {
    description: 'Blob container data asset'
    path: '/assets'
  }
}

@onlyIfNotExists()
resource nohnBlobSubDataAsset 'Microsoft.Discovery/datacontainers/dataassets@2025-07-01-preview' = {
  parent: nohnBlobDataContainer
  name: 'sc-${prefix}-subda'
  location: location
  properties: {
    description: 'Blob container subfolder data asset'
    path: '/assets/subdir'
  }
}

// Blob data asset for inaccessible account
@onlyIfNotExists()
resource noaccBlobDataContainer 'Microsoft.Discovery/datacontainers@2025-07-01-preview' = {
  name: 'sc-${prefix}-noacc-dc'
  location: location
  properties: {
    dataStore: {
      kind: 'AzureStorageBlob'
      storageAccountId: noaccBlobAccountId
    }
    credentials: [
      {
        identityId: uamiId
        name: 'uami'
        kind: 'ManagedIdentity'
        description: 'UAMI for access'
      }
    ]
  }
}

@onlyIfNotExists()
resource noaccBlobDataAsset 'Microsoft.Discovery/datacontainers/dataassets@2025-07-01-preview' = {
  parent: noaccBlobDataContainer
  name: 'sc-${prefix}-da'
  location: location
  properties: {
    description: 'Blob container data asset'
    path: '/assets'
  }
}

// Data asset for path in Discovery storage
@onlyIfNotExists()
resource storageDataContainer 'Microsoft.Discovery/datacontainers@2025-07-01-preview' = {
  name: 'sc-${prefix}-storage-dc'
  location: location
  properties: {
    dataStore: {
      kind: 'DiscoveryStorage'
      discoveryStorageId: discoveryStorageId
    }
    credentials: [
      {
        identityId: uamiId
        name: 'uami'
        kind: 'ManagedIdentity'
        description: 'UAMI for access'
      }
    ]
  }
}

@onlyIfNotExists()
resource storageDataAsset 'Microsoft.Discovery/datacontainers/dataassets@2025-07-01-preview' = {
  parent: storageDataContainer
  name: 'sc-${prefix}-da'
  location: location
  properties: {
    description: 'Discovery storage data asset'
    path: '/'
  }
}

// Outputs
output dataContainerIds array = [
  hnBlobDataContainer.id
  nohnBlobDataContainer.id
  noaccBlobDataContainer.id
  storageDataContainer.id
]
