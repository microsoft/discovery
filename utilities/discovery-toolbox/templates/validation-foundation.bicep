// Minimum-viable Discovery foundation for the Validation Section's
// Stage 0 ("create workspace") path. This template is a strict subset
// of `templates/main.bicep`:
//
//   Keep (13): vnet + 6 subnets, managedIdentity, RG-scoped role
//              assignments (discoveryPlatformContributor + acrPull),
//              supercomputer + nodePool, workspace.
//   Strip  (7): storageAccount, blobServices, blobContainer, storage
//              role assignment, chatModelDeployment, discovery
//              storageContainer, project. Stages 2..6 of the Validation
//              plan provision those layers on top of the foundation.
//
// Parameter defaults and role-assignment GUID formulas mirror
// `main.bicep` exactly so a foundation deploy is bit-compatible with a
// subsequent full `main.bicep` partial deploy into the same RG.

@description('Location for all resources. Discovery is currently supported in eastus, swedencentral and uksouth.')
param location string = resourceGroup().location

@description('Optional override for the Discovery managed resource group region. When set to a non-empty value, the workspace and supercomputer are stamped with the `discovery.overridemrgregion` tag so the Discovery RP provisions the MRG (AKS / VMSS / NetApp) in that region instead of the workspace region. Use lowercase, no-spaces form (e.g. `westus3`). Must stay bit-compatible with templates/main.bicep.')
param computeRegion string = ''

@description('Name of the Microsoft Discovery Supercomputer. Must be 3-24 characters, alphanumeric and hyphens only.')
@minLength(3)
@maxLength(24)
param supercomputerName string = 'sc-${uniqueString(resourceGroup().id)}'

@description('Name of the Node Pool created under the Supercomputer. Must be 1-12 lowercase alphanumeric characters, starting with a letter.')
@minLength(1)
@maxLength(12)
param nodePoolName string = 'nodepool1'

@description('Name of the Microsoft Discovery Workspace. Must be 3-24 characters, alphanumeric and hyphens only.')
@minLength(3)
@maxLength(24)
param workspaceName string = 'ws-${uniqueString(resourceGroup().id)}'

@description('Name of the Virtual Network.')
param vnetName string = 'vnet-${uniqueString(resourceGroup().id)}'

@description('Name of the User-Assigned Managed Identity.')
param managedIdentityName string = 'uami-${uniqueString(resourceGroup().id)}'

@description('Address space for the Virtual Network.')
param vnetAddressPrefix string = '10.0.0.0/16'

@description('Address prefix for the Supercomputer Node Pool subnet.')
param supercomputerNodepoolSubnetPrefix string = '10.0.1.0/24'

@description('Address prefix for the AKS system subnet used by the Supercomputer.')
param aksSubnetPrefix string = '10.0.2.0/24'

@description('Address prefix for the Workspace subnet (delegated to Microsoft.App/environments).')
param workspaceSubnetPrefix string = '10.0.3.0/24'

@description('Address prefix for the Private Endpoint subnet.')
param privateEndpointSubnetPrefix string = '10.0.4.0/24'

@description('Address prefix for the Agent subnet.')
param agentSubnetPrefix string = '10.0.5.0/24'

@description('Address prefix for the Search subnet (delegated to Microsoft.App/environments).')
param searchSubnetPrefix string = '10.0.6.0/24'

@description('VM SKU for the Node Pool.')
param nodePoolVmSize string = 'Standard_D4s_v6'

@description('Maximum number of nodes in the Node Pool.')
@minValue(1)
param nodePoolMaxNodeCount int = 3

@description('Minimum number of nodes in the Node Pool (0 allows scale-to-zero).')
@minValue(0)
param nodePoolMinNodeCount int = 0

@description('Scale set priority for the Node Pool.')
@allowed([
  'Regular'
  'Spot'
])
param nodePoolScaleSetPriority string = 'Regular'

@description('Deploy a second "heavy" node pool sized for compute-hungry tools that do not fit on the default Standard_D4s_v6 pool. Off by default to avoid extra spend. Must stay bit-compatible with templates/main.bicep.')
param deployHeavyNodePool bool = false

@description('Name of the optional heavy Node Pool (used when deployHeavyNodePool=true). Must be 1-12 lowercase alphanumeric characters, starting with a letter.')
@minLength(1)
@maxLength(12)
param heavyNodePoolName string = 'nodepoolhvy'

@description('VM SKU for the heavy Node Pool. Defaults to Standard_D8s_v6 (~7 vCPU / ~29 GiB guaranteed after Kubernetes + Discovery overhead).')
param heavyNodePoolVmSize string = 'Standard_D8s_v6'

@description('Maximum number of nodes in the heavy Node Pool.')
@minValue(1)
param heavyNodePoolMaxNodeCount int = 4

@description('Minimum number of nodes in the heavy Node Pool (0 allows scale-to-zero so the pool is free when idle).')
@minValue(0)
param heavyNodePoolMinNodeCount int = 0

@description('Stamps the `networkIsolation` tag on the workspace for network-hardened (NSP) mode. Public parameter — the upstream Azure Quickstart template defaults it true; defaults false here so the toolbox sets it per-tenant via `mdToolbox.workspace.networkIsolation`. Must stay bit-compatible with templates/main.bicep.')
param networkIsolation bool = false

@description('Stamps the `SkipAssociateKeyVaultToNsp: "true"` tag on the workspace so the Discovery RP skips auto-associating the managed Key Vault with the parent Network Security Perimeter. Microsoft tenant only — feature flag tag not part of the public Microsoft.Discovery API. Must stay bit-compatible with templates/main.bicep.')
param skipKvNspAssociation bool = false

@description('Add a system-assigned identity on the supercomputer ARM resource (in addition to the existing UAMI cluster / kubelet / workload identities). New at Discovery GA (`2026-06-01`). Must stay bit-compatible with templates/main.bicep.')
param enableSupercomputerSystemIdentity bool = false

@description('Provision the NetApp Files account, capacity pool, and delegated subnet at foundation time. Off by default — turning this on creates a single capacity pool that is billed for its full provisioned size (~$1,500/mo for Standard 4 TiB) the moment it is created, regardless of whether any volumes occupy it. Validation runs then carve cheap per-run volumes out of this shared pool via Stage 2.')
param enableNetAppFiles bool = false

@description('Service level for the foundation NetApp capacity pool. Standard = ~$0.000202/GiB/sec ($1.5k/mo for 4 TiB), Premium ~2x, Ultra ~4x. Ignored when `enableNetAppFiles` is false.')
@allowed([
  'Standard'
  'Premium'
  'Ultra'
])
param netAppServiceLevel string = 'Standard'

@description('Provisioned size of the foundation NetApp capacity pool in tebibytes. Azure NetApp Files enforces a 4 TiB minimum. You pay for the full provisioned size; per-run volumes carve out of this quota. Ignored when `enableNetAppFiles` is false.')
@minValue(4)
param netAppPoolSizeTiB int = 4

@description('Address prefix for the NetApp delegated subnet. Must not overlap any other subnet in the foundation vnet (default subnets use 10.0.1.0/24 through 10.0.6.0/24). Ignored when `enableNetAppFiles` is false.')
param netAppSubnetPrefix string = '10.0.7.0/24'

@description('Name of the foundation NetApp account. Auto-derived from the workspace name when blank. Ignored when `enableNetAppFiles` is false.')
param netAppAccountName string = ''

@description('Name of the foundation NetApp capacity pool. Auto-derived from the workspace name when blank. Ignored when `enableNetAppFiles` is false.')
param netAppPoolName string = ''

// Built-in role definition IDs (subset of main.bicep — storage role
// is dropped because the storage account itself is provisioned by a
// later stage).
var discoveryPlatformContributorRoleId = '01288891-85ee-45a7-b367-9db3b752fc65'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
// Built-in Contributor role on the NetApp account scope. Lets the
// workspace UAMI PUT volumes inside the foundation pool from the
// validation executor's Stage 2 'netapp-create' branch. Scoped to
// the account (not the whole RG) — narrowest practical scope.
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

var effectiveNetAppAccountName = empty(netAppAccountName) ? 'na-${uniqueString(resourceGroup().id)}' : netAppAccountName
var effectiveNetAppPoolName = empty(netAppPoolName) ? 'pool1' : netAppPoolName
// AzureNetApp capacityPools.properties.size is in BYTES.
// 1 TiB = 1024^4 bytes.
var netAppPoolSizeBytes = netAppPoolSizeTiB * 1024 * 1024 * 1024 * 1024

// Cross-region compute placement (single-VNet-in-target model). When
// `computeRegion` differs from `location`, the Discovery RP resolves
// BOTH the supercomputer's compute region (SupercomputerModelValidator
// -> RegionMismatch 400 if the subnet vnet != resolved region) AND the
// workspace's MRG region (ResolveWorkspaceMrgRegion) from the
// `discovery.overridemrgregion` tag -- so the workspace's managed
// resources (OpenAI / Cosmos / Search / agent env) ALSO land in
// `computeRegion`. Because UAMIs have isolationScope:'Regional', one
// identity can only serve one region -- so we put the ONE vnet (all
// subnets), the ONE UAMI, and NetApp in `computeRegion`, and the
// workspace + supercomputer ARM records stay in `location` (an onboarded
// Discovery region) referencing those target-region subnets + UAMI.
// This matches the cross-region deployment guide and avoids the
// workspace-side FailedIdentityOperation the earlier two-VNet / two-UAMI
// split left unfixed (it moved only the supercomputer's compute +
// identity to the target region, not the workspace's).
var normalizedComputeRegion = toLower(replace(computeRegion, ' ', ''))
var hasCrossRegionCompute = !empty(computeRegion) && normalizedComputeRegion != toLower(location)

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: hasCrossRegionCompute ? normalizedComputeRegion : location
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
  }
}

resource supercomputerNodepoolSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'supercomputerNodepoolSubnet'
  properties: {
    addressPrefix: supercomputerNodepoolSubnetPrefix
  }
}

resource aksSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'aksSubnet'
  dependsOn: [
    supercomputerNodepoolSubnet
  ]
  properties: {
    addressPrefix: aksSubnetPrefix
  }
}

resource workspaceSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'workspaceSubnet'
  dependsOn: [
    aksSubnet
  ]
  properties: {
    addressPrefix: workspaceSubnetPrefix
    delegations: [
      {
        name: 'Microsoft.App.environments'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'privateEndpointSubnet'
  dependsOn: [
    workspaceSubnet
  ]
  properties: {
    addressPrefix: privateEndpointSubnetPrefix
  }
}

resource agentSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'agentSubnet'
  dependsOn: [
    privateEndpointSubnet
  ]
  properties: {
    addressPrefix: agentSubnetPrefix
    delegations: [
      {
        name: 'Microsoft.App.environments'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource searchSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'searchSubnet'
  dependsOn: [
    agentSubnet
  ]
  properties: {
    addressPrefix: searchSubnetPrefix
    delegations: [
      {
        name: 'Microsoft.App.environments'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

// Delegated subnet for Azure NetApp Files volume mount targets. The
// `Microsoft.NetApp/volumes` delegation is mandatory — volumes refuse
// to PUT into a non-delegated subnet. ANF requires a `/26` or larger
// (the default /24 satisfies that). Conditional on `enableNetAppFiles`
// so a foundation deploy with the flag off is bit-compatible with the
// previous version of the template.
resource netAppSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = if (enableNetAppFiles) {
  parent: vnet
  name: 'netAppSubnet'
  dependsOn: [
    searchSubnet
  ]
  properties: {
    addressPrefix: netAppSubnetPrefix
    delegations: [
      {
        name: 'Microsoft.NetApp.volumes'
        properties: {
          serviceName: 'Microsoft.NetApp/volumes'
        }
      }
    ]
  }
}

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: managedIdentityName
  location: hasCrossRegionCompute ? normalizedComputeRegion : location
  #disable-next-line BCP073
  properties: {
    isolationScope: 'Regional'
  }
}

resource discoveryPlatformContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, managedIdentity.id, discoveryPlatformContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      discoveryPlatformContributorRoleId
    )
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, managedIdentity.id, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Foundation NetApp account and capacity pool. The validation
// executor's Stage 2 'netapp-create' branch carves cheap per-run
// volumes out of this pool; Stage 2 'netapp-reuse' picks any
// pre-existing volume in the subscription (including any the user
// hand-created here). Both are conditional on `enableNetAppFiles`.
resource netAppAccount 'Microsoft.NetApp/netAppAccounts@2023-11-01' = if (enableNetAppFiles) {
  name: effectiveNetAppAccountName
  location: hasCrossRegionCompute ? normalizedComputeRegion : location
  properties: {}
}

resource netAppPool 'Microsoft.NetApp/netAppAccounts/capacityPools@2023-11-01' = if (enableNetAppFiles) {
  parent: netAppAccount
  name: effectiveNetAppPoolName
  location: hasCrossRegionCompute ? normalizedComputeRegion : location
  properties: {
    serviceLevel: netAppServiceLevel
    size: netAppPoolSizeBytes
    qosType: 'Auto'
  }
}

// Workspace UAMI needs Contributor on the NetApp account so the
// validation executor's Stage 2 'netapp-create' branch can PUT
// volumes into the pool. Account scope is the narrowest practical
// scope — pool-scope assignments don't cascade to child volumes.
resource netAppContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableNetAppFiles) {
  name: guid(resourceGroup().id, managedIdentity.id, netAppAccount.id, contributorRoleId)
  scope: netAppAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource supercomputer 'Microsoft.Discovery/supercomputers@2026-06-01' = {
  name: supercomputerName
  location: location
  tags: union(
    { version: 'v2' },
    networkIsolation ? { networkIsolation: 'true' } : {},
    skipKvNspAssociation ? { SkipAssociateKeyVaultToNsp: 'true' } : {},
    empty(computeRegion) ? {} : { 'discovery.overridemrgregion': toLower(replace(computeRegion, ' ', '')) }
  )
  identity: {
    type: enableSupercomputerSystemIdentity ? 'SystemAssigned' : 'None'
  }
  properties: {
    subnetId: aksSubnet.id
    identities: {
      clusterIdentity: {
        id: managedIdentity.id
      }
      kubeletIdentity: {
        id: managedIdentity.id
      }
      workloadIdentities: {
        '${managedIdentity.id}': {}
      }
    }
  }
}

resource nodePool 'Microsoft.Discovery/supercomputers/nodePools@2026-06-01' = {
  parent: supercomputer
  name: nodePoolName
  location: location
  properties: {
    subnetId: supercomputerNodepoolSubnet.id
    vmSize: nodePoolVmSize
    maxNodeCount: nodePoolMaxNodeCount
    minNodeCount: nodePoolMinNodeCount
    scaleSetPriority: nodePoolScaleSetPriority
  }
}

resource heavyNodePool 'Microsoft.Discovery/supercomputers/nodePools@2026-06-01' = if (deployHeavyNodePool) {
  parent: supercomputer
  name: heavyNodePoolName
  location: location
  properties: {
    subnetId: supercomputerNodepoolSubnet.id
    vmSize: heavyNodePoolVmSize
    maxNodeCount: heavyNodePoolMaxNodeCount
    minNodeCount: heavyNodePoolMinNodeCount
    scaleSetPriority: nodePoolScaleSetPriority
  }
}

resource workspace 'Microsoft.Discovery/workspaces@2026-06-01' = {
  name: workspaceName
  location: location
  tags: union(
    { version: 'v2' },
    networkIsolation ? { networkIsolation: 'true' } : {},
    skipKvNspAssociation ? { SkipAssociateKeyVaultToNsp: 'true' } : {},
    empty(computeRegion) ? {} : { 'discovery.overridemrgregion': toLower(replace(computeRegion, ' ', '')) }
  )
  properties: {
    workspaceIdentity: {
      id: managedIdentity.id
    }
    supercomputerIds: [
      supercomputer.id
    ]
    agentSubnetId: agentSubnet.id
    privateEndpointSubnetId: privateEndpointSubnet.id
    workspaceSubnetId: workspaceSubnet.id
  }
}

@description('Resource ID of the Supercomputer.')
output supercomputerId string = supercomputer.id

@description('Resource ID of the Node Pool.')
output nodePoolId string = nodePool.id

@description('Resource ID of the Workspace.')
output workspaceId string = workspace.id

@description('Resource ID of the User-Assigned Managed Identity.')
output managedIdentityId string = managedIdentity.id

@description('Resource ID of the Virtual Network.')
output vnetId string = vnet.id

@description('Resource ID of the cross-region compute Virtual Network. Retained for output-contract compatibility; always empty in the single-VNet-in-target model (compute now shares the primary VNet, which is deployed in `computeRegion` when cross-region).')
output computeVnetId string = ''

@description('Name of the resource group hosting the foundation.')
output resourceGroupName string = resourceGroup().name

@description('Resource ID of the foundation NetApp capacity pool. Empty string when `enableNetAppFiles` is false.')
output netAppPoolId string = enableNetAppFiles ? netAppPool.id : ''

@description('Resource ID of the foundation NetApp account. Empty string when `enableNetAppFiles` is false.')
output netAppAccountId string = enableNetAppFiles ? netAppAccount.id : ''

@description('Resource ID of the delegated NetApp subnet. Empty string when `enableNetAppFiles` is false.')
output netAppSubnetId string = enableNetAppFiles ? netAppSubnet.id : ''

@description('Service level of the foundation NetApp capacity pool. Empty string when `enableNetAppFiles` is false.')
output netAppServiceLevel string = enableNetAppFiles ? netAppServiceLevel : ''
