
param storageAccountName string
param location string
param storageSubnetId string
param supercomputerNodepoolSubnetId string
param aksSubnetId string  

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {id: storageSubnetId
        action: 'Allow'
        }
        {id: supercomputerNodepoolSubnetId
        action: 'Allow'
        }
        {id: aksSubnetId
        action: 'Allow'
        }
      ]
    }
  }
}

resource storageAccounts_newdiscstorage_name_default 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
    name: 'default'
  properties: {
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    cors: {
      corsRules: [
        {
          allowedOrigins: [
            'https://studio.discovery.microsoft.com'
          ]
          allowedMethods: [
            'GET'
            'DELETE'
            'PUT'
          ]
          maxAgeInSeconds: 200
          exposedHeaders: [
            '*'
          ]
          allowedHeaders: [
            '*'
          ]
        }
      ]
    }
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      enabled: true
      days: 7
    }
  }
}

resource Microsoft_Storage_storageAccounts_fileServices_storageAccounts_newdiscstorage_name_default 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' = {
  parent: storage
    name: 'default'
  properties: {
    protocolSettings: {
      smb: {}
    }
    cors: {
      corsRules: []
    }
    shareDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource Microsoft_Storage_storageAccounts_queueServices_storageAccounts_newdiscstorage_name_default 'Microsoft.Storage/storageAccounts/queueServices@2025-01-01' = {
  parent: storage
    name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
  }
}

resource Microsoft_Storage_storageAccounts_tableServices_storageAccounts_newdiscstorage_name_default 'Microsoft.Storage/storageAccounts/tableServices@2025-01-01' = {
  parent: storage
    name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
  }
}

resource storageAccounts_newdiscstorage_name_default_discoveryoutputs 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: storageAccounts_newdiscstorage_name_default
    name: 'discoveryoutputs'
  properties: {
    immutableStorageWithVersioning: {
      enabled: false
    }
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
    publicAccess: 'None'
  }
}

output storageId string = storage.id
