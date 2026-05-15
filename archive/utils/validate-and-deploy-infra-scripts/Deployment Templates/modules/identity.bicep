param uamiName string
param location string = resourceGroup().location

@allowed([
  'None'
  'Regional'
])
param isolationScope string = 'Regional'

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: uamiName
  location: location
  properties: {
    isolationScope: isolationScope
  }
}

output uamiId string = uami.id
output uamiClientId string = uami.properties.clientId
output uamiPrincipalId string = uami.properties.principalId
