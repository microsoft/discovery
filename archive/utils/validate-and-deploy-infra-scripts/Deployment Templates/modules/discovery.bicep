param discoveryWorkspace string

param location string
param discoveryStorageId string
param supercomputerId string
param uamiId string


// Workspace resource
resource workspace 'Microsoft.Discovery/workspaces@2025-07-01-preview' = {
  name: discoveryWorkspace  
  location: location
  properties: {
    storageIds: [
      discoveryStorageId
    ]
    supercomputerIds: [
      supercomputerId
    ]
    workspaceIdentity: {
      id: uamiId
    }
  }
}

// Outputs
output workspaceId string = workspace.id

