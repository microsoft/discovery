param location string
param uamiId string
param uamiPrincipalId string
param uamiClientId string
param aksSubnetId string
param supercomputerNodepoolSubnetId string
param supercomputerName string

resource supercomputer 'Microsoft.Discovery/supercomputers@2025-07-01-preview' = {
  name: supercomputerName
  location: location
  properties: {
    subnetId: aksSubnetId
    identities: {
      clusterIdentity: {
        id: uamiId
        principalId: uamiPrincipalId
        clientId: uamiClientId
      }
      kubeletIdentity: {
        id: uamiId
        principalId: uamiPrincipalId
        clientId: uamiClientId
      }
      workloadIdentities: {
        '${uamiId}': {
          principalId: uamiPrincipalId
          clientId: uamiClientId
        }
      }
    }
  }
}

// Microsoft.Discovery/supercomputers/nodepools resource
resource defaultpool 'Microsoft.Discovery/supercomputers/nodepools@2025-07-01-preview' = {
  parent: supercomputer
  name: 'defaultpool'
  location: location
  properties: {
    subnetId: supercomputerNodepoolSubnetId
    vmSize: 'Standard_D4s_v6'
    minNodeCount: 1
    maxNodeCount: 3
  }
}

// Outputs
output supercomputerId string = supercomputer.id
output defaultNodepoolId string = defaultpool.id
