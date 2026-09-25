// Stage 2 — Discovery landing-zone network template.
// Provisions the VNet, subnets, a shared NSG (FR2.3 allow-list), route tables
// (FR2.4, UserDefinedRouting only) and the private DNS zones + links (FR2.5) in
// one RG-scoped deployment. Parameters are generated from the Stage 1 config by
// stage2_prepare.ps1 (New-Stage2NetworkParamFile); do not hand-edit values —
// change config.json and re-run.
//
// Topologies (switched by outboundType):
//   UserDefinedRouting (byo-spoke / forced tunneling) — default:
//       route tables send 0.0.0.0/0 and 10.0.0.0/8 to the customer NVA; the
//       managedcluster subnet keeps its own CIDR VnetLocal. Requires nvaNextHop.
//   LoadBalancer (greenfield / dev):
//       no user route tables (rely on system routes); the NSG allow-list governs
//       egress and Azure-managed load balancer handles outbound.

targetScope = 'resourceGroup'

@description('Region for the VNet and all network resources.')
param location string

@description('Virtual network name.')
param vnetName string

@description('VNet address space (CIDR).')
param vnetCidr string

@description('Subnets to lay out. Each item: { role, name, cidr, delegation }. delegation "none"/"" means no delegation.')
param subnets array

@description('AKS/pod overlay CIDR used in NSG allow-list rules.')
param podCidr string = '10.244.0.0/16'

@description('Egress model. UserDefinedRouting = forced tunneling via the customer NVA; LoadBalancer = Azure-managed egress.')
@allowed([
  'UserDefinedRouting'
  'LoadBalancer'
])
param outboundType string = 'UserDefinedRouting'

@description('Firewall/NVA private IP (next hop). Required when outboundType = UserDefinedRouting.')
param nvaNextHop string = ''

@description('Corporate DNS resolver IPs for the DNS egress rule. Empty = allow DNS to any (*) on 53.')
param corpDns array = []

@description('Override the shared NSG name. Empty = nsg-<vnetName>.')
param nsgName string = ''

@description('Create and link the privatelink.* DNS zones (FR2.5).')
param createPrivateDns bool = true

@description('Private DNS zones to create and link to the VNet.')
param privateDnsZones array = [
  'privatelink.blob.core.windows.net'
  'privatelink.queue.core.windows.net'
  'privatelink.file.core.windows.net'
  'privatelink.table.core.windows.net'
  'privatelink.dfs.core.windows.net'
  'privatelink.vaultcore.azure.net'
  'privatelink.search.windows.net'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.services.ai.azure.com'
  'privatelink.documents.azure.com'
  'privatelink.azurecr.io'
]

@description('Tags applied to the network resources.')
param tags object = {}

var isUdr = outboundType == 'UserDefinedRouting'
var nsgNameResolved = empty(nsgName) ? 'nsg-${vnetName}' : nsgName
var spokeRtName = 'rt-spoke-${vnetName}'
var mcRtName = 'rt-managedcluster-${vnetName}'
var mcMatches = filter(subnets, s => s.role == 'managedcluster')
var managedClusterCidr = length(mcMatches) > 0 ? mcMatches[0].cidr : ''
var dnsDestinations = empty(corpDns) ? [ '*' ] : corpDns

// Shared NSG — FR2.3 allow-list applied to every subnet.
resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: nsgNameResolved
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'Allow-VNet-In'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'Allow-AzureLB-In'
        properties: {
          priority: 210
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          destinationAddressPrefix: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'Allow-PodCIDR-In'
        properties: {
          priority: 220
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: podCidr
          destinationAddressPrefixes: [
            vnetCidr
            podCidr
          ]
          sourcePortRange: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'Allow-DNS-Out'
        properties: {
          priority: 220
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefixes: [
            vnetCidr
            podCidr
          ]
          destinationAddressPrefixes: dnsDestinations
          sourcePortRange: '*'
          destinationPortRange: '53'
        }
      }
      {
        name: 'Allow-AzureCloud-Out'
        properties: {
          priority: 230
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefixes: [
            vnetCidr
            podCidr
          ]
          destinationAddressPrefix: 'AzureCloud'
          sourcePortRange: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'Allow-AzureCloud-KMS-Out'
        properties: {
          priority: 235
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefixes: [
            vnetCidr
            podCidr
          ]
          destinationAddressPrefix: 'AzureCloud'
          sourcePortRange: '*'
          destinationPortRange: '1688'
        }
      }
      {
        name: 'Allow-Internet-Out'
        properties: {
          priority: 250
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefixes: [
            vnetCidr
            podCidr
          ]
          destinationAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'Allow-PodCIDR-Out'
        properties: {
          priority: 260
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefixes: [
            vnetCidr
            podCidr
          ]
          destinationAddressPrefix: podCidr
          sourcePortRange: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

// Spoke route table (UDR only) — default and RFC1918-10 to the customer NVA.
resource spokeRouteTable 'Microsoft.Network/routeTables@2023-11-01' = if (isUdr) {
  name: spokeRtName
  location: location
  tags: tags
  properties: {
    disableBgpRoutePropagation: true
    routes: [
      {
        name: 'default-to-nva'
        properties: {
          addressPrefix: '0.0.0.0/0'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: nvaNextHop
        }
      }
      {
        name: 'rfc1918-10-to-nva'
        properties: {
          addressPrefix: '10.0.0.0/8'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: nvaNextHop
        }
      }
    ]
  }
}

// managedcluster route table (UDR only) — NVA routes plus the cluster CIDR kept VnetLocal.
resource mcRouteTable 'Microsoft.Network/routeTables@2023-11-01' = if (isUdr && !empty(managedClusterCidr)) {
  name: mcRtName
  location: location
  tags: tags
  properties: {
    disableBgpRoutePropagation: true
    routes: [
      {
        name: 'default-to-nva'
        properties: {
          addressPrefix: '0.0.0.0/0'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: nvaNextHop
        }
      }
      {
        name: 'rfc1918-10-to-nva'
        properties: {
          addressPrefix: '10.0.0.0/8'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: nvaNextHop
        }
      }
      {
        name: 'managedcluster-vnetlocal'
        properties: {
          addressPrefix: managedClusterCidr
          nextHopType: 'VnetLocal'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetCidr
      ]
    }
    subnets: [for sn in subnets: {
      name: sn.name
      properties: {
        addressPrefix: sn.cidr
        networkSecurityGroup: {
          id: nsg.id
        }
        routeTable: isUdr ? {
          id: sn.role == 'managedcluster' ? resourceId('Microsoft.Network/routeTables', mcRtName) : resourceId('Microsoft.Network/routeTables', spokeRtName)
        } : null
        delegations: (contains(sn, 'delegation') && sn.delegation != 'none' && !empty(sn.delegation)) ? [
          {
            name: replace(sn.delegation, '/', '.')
            properties: {
              serviceName: sn.delegation
            }
          }
        ] : []
        privateEndpointNetworkPolicies: sn.role == 'private-endpoints' ? 'Disabled' : 'Enabled'
      }
    }]
  }
  dependsOn: [
    spokeRouteTable
    mcRouteTable
  ]
}

resource privateDns 'Microsoft.Network/privateDnsZones@2020-06-01' = [for zone in privateDnsZones: if (createPrivateDns) {
  name: zone
  location: 'global'
  tags: tags
}]

resource privateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (zone, i) in privateDnsZones: if (createPrivateDns) {
  name: '${zone}/link-${vnetName}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
  dependsOn: [
    privateDns[i]
  ]
}]

output vnetId string = vnet.id
output vnetName string = vnet.name
output nsgId string = nsg.id
output subnetIds array = [for sn in subnets: {
  role: sn.role
  name: sn.name
  id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, sn.name)
}]
