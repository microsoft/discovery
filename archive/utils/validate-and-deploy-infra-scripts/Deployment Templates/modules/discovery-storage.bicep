param location string
param storageSubnetId string
param discoveryStorageName string

// Two Microsoft.Discovery/storage resources
resource discoveryStorage1 'Microsoft.Discovery/storages@2025-07-01-preview' = {
  name: discoveryStorageName
  location: location
  properties: {
    store: {
      kind: 'AzureNetApp'
    }
    subnetId: storageSubnetId
  }
}

output discoveryStorageId string = discoveryStorage1.id
