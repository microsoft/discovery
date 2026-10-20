$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
$stage3Path = Join-Path $PSScriptRoot '..\scripts\stage3-validation\stage3_validate.ps1'
Import-Module $modulePath -Force
$script:Stage3ScriptRoot = Split-Path -Parent $stage3Path

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $stage3Path),
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }
foreach ($name in @(
        'Get-NetworkResourceGroup',
        'Get-SubnetPrefixes',
        'Get-ConfiguredVnets',
        'Get-ProfileSubnetRoles',
        'Invoke-CheckNsgEffective',
        'Invoke-CheckEffectiveRoutes',
        'Invoke-CheckDnsAndPe'
    )) {
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
        }, $true)
    if (-not $functionAst) { throw "$name was not found in $stage3Path." }
    Invoke-Expression $functionAst.Extent.Text
}

function New-Stage3DnsConfig {
    [pscustomobject]@{
        resourceGroup = 'platform-rg'
        network       = [pscustomobject]@{
            networkResourceGroup = 'network-rg'
            dnsResourceGroup     = 'dns-rg'
            vnetName              = 'vnet'
        }
        storage       = [pscustomobject]@{
            accountId = '/subscriptions/sub/resourceGroups/storage-rg/providers/Microsoft.Storage/storageAccounts/data'
        }
    }
}

# The stage function reads dependency-spec.json relative to its script location. These focused
# tests exercise one supplied subnet at a time, so no profile filtering is needed.
function Get-ProfileSubnetRoles {
    param([string]$Profile)
    return $null
}

function New-Stage3NetworkConfig {
    param(
        [string]$Role = 'nodepool',
        [string]$OutboundType = 'UserDefinedRouting',
        [string]$NvaNextHop = '10.0.0.4'
    )
    [pscustomobject]@{
        subscriptionId = 'sub'
        resourceGroup  = 'platform-rg'
        network        = [pscustomobject]@{
            networkResourceGroup = 'network-rg'
            outboundType         = $OutboundType
            nvaNextHop            = $NvaNextHop
            subnets              = @([pscustomobject]@{
                    role = $Role
                    cidr = '10.0.0.0/26'
                    id   = "/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/$Role"
                })
        }
    }
}

function New-AllowRule {
    param(
        [string]$Name,
        [string]$Direction,
        [string]$Access = 'Allow',
        [int]$Priority = 200,
        [string]$Port = '*',
        [string]$Source = '*',
        [string]$Destination = '*'
    )
    [pscustomobject]@{
        name                     = $Name
        direction                = $Direction
        access                   = $Access
        priority                 = $Priority
        destinationPortRange     = $Port
        sourceAddressPrefix      = $Source
        destinationAddressPrefix = $Destination
    }
}

Describe 'Stage 3 effective NSG validation' {
    BeforeEach {
        $global:Stage3Subnet = [pscustomobject]@{
            id                   = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/nodepool'
            networkSecurityGroup = $null
        }
        $global:Stage3Nics = @()
        $global:Stage3Nsg = $null
        $global:Stage3EffectiveNsg = @()
        Mock Get-AzJson { $global:Stage3Subnet } -ParameterFilter { $Args -contains 'subnet' -and $Args -contains 'show' }
        Mock Get-AzJson { @($global:Stage3Nics) } -ParameterFilter { $Args -contains 'nic' -and $Args -contains 'list' }
        Mock Get-AzJson { @($global:Stage3EffectiveNsg) } -ParameterFilter { $Args -contains 'list-effective-nsg' }
        Mock Get-AzJson { $global:Stage3Nsg } -ParameterFilter { $Args -contains 'nsg' -and $Args -contains 'show' }
    }

    AfterEach {
        Remove-Variable Stage3Subnet, Stage3Nics, Stage3Nsg, Stage3EffectiveNsg -Scope Global -ErrorAction SilentlyContinue
    }

    It 'passes when the subnet has no NSG and Azure implicit defaults apply' {
        $result = @(Invoke-CheckNsgEffective -Config (New-Stage3NetworkConfig) -Profile 'supercomputer')

        $result[0].status | Should Be 'Pass'
        $result[0].data.source | Should Be 'no-nsg'
    }

    It 'passes the no-NIC fallback when the subnet NSG allows internet and east-west traffic' {
        $global:Stage3Subnet.networkSecurityGroup = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/networkSecurityGroups/nsg' }
        $global:Stage3Nsg = [pscustomobject]@{
            securityRules = @(
                (New-AllowRule -Name 'internet' -Direction 'Outbound' -Port '443' -Destination 'Internet'),
                (New-AllowRule -Name 'east-west' -Direction 'Inbound' -Port '10250' -Source 'VirtualNetwork' -Destination 'VirtualNetwork')
            )
            defaultSecurityRules = @()
        }

        $result = @(Invoke-CheckNsgEffective -Config (New-Stage3NetworkConfig) -Profile 'supercomputer')

        $result[0].status | Should Be 'Pass'
        $result[0].data.source | Should Be 'subnet-nsg-fallback'
    }

    It 'honors a higher-priority deny over a lower-priority internet allow' {
        $global:Stage3Subnet.networkSecurityGroup = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/networkSecurityGroups/nsg' }
        $global:Stage3Nsg = [pscustomobject]@{
            securityRules = @(
                (New-AllowRule -Name 'deny-internet' -Direction 'Outbound' -Access 'Deny' -Priority 100 -Port '443' -Destination 'Internet'),
                (New-AllowRule -Name 'allow-internet' -Direction 'Outbound' -Priority 200 -Port '443' -Destination 'Internet'),
                (New-AllowRule -Name 'east-west' -Direction 'Inbound' -Priority 200 -Port '10250' -Source 'VirtualNetwork' -Destination 'VirtualNetwork')
            )
            defaultSecurityRules = @()
        }

        $result = @(Invoke-CheckNsgEffective -Config (New-Stage3NetworkConfig) -Profile 'supercomputer')

        $result[0].status | Should Be 'Fail'
        ($result[0].data.missingRules -contains 'Allow-Internet-Out-443') | Should Be $true
    }

    It 'fails rather than falling back when a usable NIC has no readable effective rules' {
        $subnetId = $global:Stage3Subnet.id
        $global:Stage3Nics = @([pscustomobject]@{
                id                = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/networkInterfaces/nic'
                provisioningState = 'Succeeded'
                virtualMachine    = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Compute/virtualMachines/vm' }
                ipConfigurations  = @([pscustomobject]@{ subnet = [pscustomobject]@{ id = $subnetId } })
            })

        $result = @(Invoke-CheckNsgEffective -Config (New-Stage3NetworkConfig) -Profile 'supercomputer')

        $result[0].status | Should Be 'Fail'
        $result[0].data.source | Should Be 'effective'
    }
}

Describe 'Stage 3 effective route validation' {
    BeforeEach {
        $global:Stage3Subnet = [pscustomobject]@{
            id         = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/nodepool'
            routeTable = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/routeTables/rt' }
        }

        $global:Stage3Nics = @()
        $global:Stage3RouteTable = [pscustomobject]@{ routes = @() }
        Mock Get-AzJson { $global:Stage3Subnet } -ParameterFilter { $Args -contains 'subnet' -and $Args -contains 'show' }
        Mock Get-AzJson { @($global:Stage3Nics) } -ParameterFilter { $Args -contains 'nic' -and $Args -contains 'list' }
        Mock Get-AzJson { $global:Stage3RouteTable } -ParameterFilter { $Args -contains 'route-table' -and $Args -contains 'show' }
    }

    AfterEach {
        Remove-Variable Stage3Subnet, Stage3Nics, Stage3RouteTable -Scope Global -ErrorAction SilentlyContinue
    }

    It 'passes UDR fallback when the default route targets the configured appliance' {
        $global:Stage3RouteTable.routes = @([pscustomobject]@{
                addressPrefix   = '0.0.0.0/0'
                nextHopType     = 'VirtualAppliance'
                nextHopIpAddress = '10.0.0.4'
            })

        $result = @(Invoke-CheckEffectiveRoutes -Config (New-Stage3NetworkConfig) -Profile 'supercomputer')

        $result[0].status | Should Be 'Pass'
        $result[0].data.source | Should Be 'route-table-fallback'
    }

    It 'fails UDR fallback when the appliance IP does not match configuration' {
        $global:Stage3RouteTable.routes = @([pscustomobject]@{
                addressPrefix   = '0.0.0.0/0'
                nextHopType     = 'VirtualAppliance'
                nextHopIpAddress = '10.0.0.5'
            })

        $result = @(Invoke-CheckEffectiveRoutes -Config (New-Stage3NetworkConfig) -Profile 'supercomputer')

        $result[0].status | Should Be 'Fail'
    }

    It 'passes LoadBalancer mode when no user default route overrides Azure routing' {
        $result = @(Invoke-CheckEffectiveRoutes -Config (New-Stage3NetworkConfig -OutboundType 'LoadBalancer' -NvaNextHop '') -Profile 'supercomputer')

        $result[0].status | Should Be 'Pass'
    }

    It 'fails when the managed-cluster subnet is routed through an appliance' {
        $global:Stage3Subnet.id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/managedcluster'
        $global:Stage3RouteTable.routes = @([pscustomobject]@{
                addressPrefix   = '10.0.0.0/26'
                nextHopType     = 'VirtualAppliance'
                nextHopIpAddress = '10.0.0.4'
            })

        $result = @(Invoke-CheckEffectiveRoutes -Config (New-Stage3NetworkConfig -Role 'managedcluster') -Profile 'supercomputer')

        $result[0].status | Should Be 'Fail'
    }
}

Describe 'Stage 3 private DNS validation' {
    BeforeEach {
        $global:Stage3DnsLinks = @([pscustomobject]@{
                virtualNetwork = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet' }
            })
        $global:Stage3PrivateEndpoints = @()
        $global:Stage3DnsZoneGroups = @()
        Mock Get-AzJson { [pscustomobject]@{ name = 'zone' } } -ParameterFilter {
            $Args -contains 'private-dns' -and $Args -contains 'zone' -and $Args -contains 'show'
        }
        Mock Get-AzJson { @($global:Stage3DnsLinks) } -ParameterFilter {
            $Args -contains 'private-dns' -and $Args -contains 'link' -and $Args -contains 'list'
        }
        Mock Get-AzJson { @($global:Stage3PrivateEndpoints) } -ParameterFilter {
            $Args -contains 'private-endpoint' -and $Args -contains 'list'
        }
        Mock Get-AzJson { @($global:Stage3DnsZoneGroups) } -ParameterFilter {
            $Args -contains 'dns-zone-group' -and $Args -contains 'list'
        }
        Mock Get-AzJson {
            [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet' }
        } -ParameterFilter {
            $Args -contains 'vnet' -and $Args -contains 'show' -and $Args -contains 'network-rg'
        }
    }

    AfterEach {
        Remove-Variable Stage3DnsLinks, Stage3PrivateEndpoints, Stage3DnsZoneGroups -Scope Global -ErrorAction SilentlyContinue
    }

    It 'passes private DNS zones only when they link to the configured VNet' {
        $results = @(Invoke-CheckDnsAndPe -Config (New-Stage3DnsConfig) -Profile 'supercomputer')
        $zones = @($results | Where-Object { $_.id -like 'private-dns-zone-*' })

        ($zones.Count -gt 0) | Should Be $true
        @($zones | Where-Object status -ne 'Pass').Count | Should Be 0
    }

    It 'fails zones linked to a different VNet' {
        $global:Stage3DnsLinks = @([pscustomobject]@{
                virtualNetwork = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/other-vnet' }
            })

        $results = @(Invoke-CheckDnsAndPe -Config (New-Stage3DnsConfig) -Profile 'supercomputer')
        $zones = @($results | Where-Object { $_.id -like 'private-dns-zone-*' })

        @($zones | Where-Object status -eq 'Fail').Count | Should Be $zones.Count
    }

    It 'resolves the VNet from the network resource group and searches endpoint resource groups' {
        $null = @(Invoke-CheckDnsAndPe -Config (New-Stage3DnsConfig) -Profile 'supercomputer')

        Assert-MockCalled Get-AzJson -Scope It -Times 1 -ParameterFilter {
            $Args -contains 'vnet' -and $Args -contains 'show' -and
            $Args -contains 'network-rg' -and $Args -notcontains 'dns-rg'
        }
        foreach ($resourceGroup in @('network-rg', 'platform-rg', 'storage-rg')) {
            Assert-MockCalled Get-AzJson -Scope It -Times 1 -ParameterFilter {
                $Args -contains 'private-endpoint' -and $Args -contains 'list' -and $Args -contains $resourceGroup
            }
        }
        Assert-MockCalled Get-AzJson -Scope It -Times 0 -ParameterFilter {
            $Args -contains 'private-endpoint' -and $Args -contains 'list' -and $Args -contains 'dns-rg'
        }
    }

    It 'accepts a succeeded DNS zone group when custom DNS configs are empty' {
        $global:Stage3PrivateEndpoints = @([pscustomobject]@{
                id                            = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/privateEndpoints/pe'
                name                          = 'pe'
                provisioningState             = 'Succeeded'
                subnet                        = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/pe' }
                privateLinkServiceConnections = @([pscustomobject]@{
                        privateLinkServiceConnectionState = [pscustomobject]@{ status = 'Approved' }
                    })
                customDnsConfigs              = @()
            })
        $global:Stage3DnsZoneGroups = @([pscustomobject]@{
                provisioningState     = 'Succeeded'
                privateDnsZoneConfigs = @([pscustomobject]@{
                        privateDnsZoneId = '/subscriptions/sub/resourceGroups/dns-rg/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net'
                    })
            })

        $results = @(Invoke-CheckDnsAndPe -Config (New-Stage3DnsConfig) -Profile 'supercomputer')
        $endpoint = @($results | Where-Object id -eq 'private-endpoint-pe')[0]

        $endpoint.status | Should Be 'Pass'
        $endpoint.data.approved | Should Be $true
        $endpoint.data.succeededDnsZoneGroups | Should Be 1
        $endpoint.data.customDnsConfigCount | Should Be 0
    }

    It 'fails an approved endpoint without a succeeded DNS zone group or custom DNS configuration' {
        $global:Stage3PrivateEndpoints = @([pscustomobject]@{
                id                            = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/privateEndpoints/pe'
                name                          = 'pe'
                provisioningState             = 'Succeeded'
                subnet                        = [pscustomobject]@{ id = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/pe' }
                privateLinkServiceConnections = @([pscustomobject]@{
                        privateLinkServiceConnectionState = [pscustomobject]@{ status = 'Approved' }
                    })
                customDnsConfigs              = @()
            })

        $results = @(Invoke-CheckDnsAndPe -Config (New-Stage3DnsConfig) -Profile 'supercomputer')
        $endpoint = @($results | Where-Object id -eq 'private-endpoint-pe')[0]

        $endpoint.status | Should Be 'Fail'
        $endpoint.data.succeededDnsZoneGroups | Should Be 0
        $endpoint.data.customDnsConfigCount | Should Be 0
    }
}
