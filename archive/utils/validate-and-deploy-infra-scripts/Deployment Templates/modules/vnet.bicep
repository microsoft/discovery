param vnetName string
param location string

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [ '10.0.0.0/16' ]
    }
    subnets: [
      {
        name: 'default'
        properties: {
          addressPrefix: '10.0.0.0/24'
        }
      }
      {
        name: 'supercomputerNodepoolSubnet'
        properties: {
          addressPrefix: '10.0.2.0/24'
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                location
              ]
            }
          ]
        }
      }
      {
        name: 'aksSubnet'
        properties: {
          addressPrefix: '10.0.3.0/24'
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                location
              ]
            }
          ]
        }
      }
      {
        name: 'storageSubnet'
        properties: {
          addressPrefix: '10.0.1.0/24'
          delegations: [
            {
              name: 'NetAppDelegation'
              properties: {
                serviceName: 'Microsoft.Netapp/volumes'
              }
            }
          ]
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                location
              ]
            }
          ]
        }
      }
      {
        name: 'copilot-subnet'
        properties: {
          addressPrefix: '10.0.4.0/24'
          delegations: [
            {
              name: 'FuncAppDelegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                location
              ]
            }
          ]
        }
      }
    ]
  }
}

// Outputs
output vnetId string = vnet.id
output defaultId string = vnet.properties.subnets[0].id
output supercomputerNodepoolSubnetId string = vnet.properties.subnets[1].id
output aksSubnetId string = vnet.properties.subnets[2].id
output storageSubnetId string = vnet.properties.subnets[3].id
