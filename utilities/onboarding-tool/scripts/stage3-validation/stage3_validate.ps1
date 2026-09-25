#Requires -Version 7.0
<#
.SYNOPSIS  Stage 3 / FR3.1-FR3.8 — run infra validation checks (single consolidated script).
.DESCRIPTION
    Self-contained headless CLI for read-only control-plane checks, with opt-in test VM probes.
    Consolidates the former dependency_spec / check_* / testvm_lifecycle / probe_* sub-scripts
    into one file. Read-only except the opt-in -WithVm ephemeral probe VM (always torn down).
    Spec: ../../script-specs/stage3-validation/stage3_validate.md
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [string]$JsonPath,
    [ValidateSet('supercomputer', 'workspace', 'bookshelf')][string]$Profile = 'supercomputer',
    [switch]$WithVm,
    [switch]$PassThru
)
Import-Module (Join-Path $PSScriptRoot '..\lib\OnboardingCommon.psm1') -Force
$cfg = Get-OnboardingConfig -Path $ConfigPath
$results = [System.Collections.Generic.List[object]]::new()

# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------
function Get-DefaultRemediation {
    param([object]$Result)
    $id = if ($Result.PSObject.Properties.Name -contains 'id') { [string]$Result.id } else { '' }
    $detail = if ($Result.PSObject.Properties.Name -contains 'detail') { [string]$Result.detail } else { '' }
    if ($id -like 'dns-*' -or $id -like 'private-dns-*') { return 'Fix VNet DNS / private DNS zone links.' }
    if ($id -like 'tcp443-*' -or $id -like 'nsg-*') { return 'NSG denies egress or UDR black-holes the route.' }
    if ($id -like 'https-*' -or $id -like 'artifact-*') { return 'NVA allowlist incomplete or TLS-inspecting the FQDN.' }
    if ($id -like 'pe-resolution-*' -or $id -like 'private-endpoint-*') { return 'Fix private DNS zone links / VNet DNS.' }
    if ($id -like 'eastwest-*' -or $detail -like '*10250*') { return 'Allow east-west 10250 (symmetric routing or explicit rule).' }
    if ($id -like 'effective-routes-managedcluster*') { return 'Managed cluster routed via NVA, AKS NotReady -> Set managed cluster subnet to VnetLocal; delete+recreate route.' }
    if ($id -like 'dependency-spec*') { return 'Update the dependency spec in the feature PR that changed the dependency.' }
    return 'Fix the failing Stage 3 prerequisite and re-run validation.'
}
function Add-Results {
    param([object[]]$Items)
    foreach ($item in @($Items)) {
        if ($item.status -eq 'Fail' -and [string]::IsNullOrWhiteSpace($item.remediation)) {
            $item.remediation = Get-DefaultRemediation -Result $item
        }
        $results.Add($item)
    }
}

# ---------------------------------------------------------------------------
# Shared network-discovery helpers
# ---------------------------------------------------------------------------
function Get-NetworkResourceGroup {
    param([object]$Config)
    if ($Config.network.PSObject.Properties.Name -contains 'networkResourceGroup' -and $Config.network.networkResourceGroup) { return $Config.network.networkResourceGroup }
    if ($Config.PSObject.Properties.Name -contains 'resourceGroup' -and $Config.resourceGroup) { return $Config.resourceGroup }
    return ''
}
function Get-SubnetPrefixes {
    param([object]$Subnet)
    $prefixes = @()
    if ($Subnet.PSObject.Properties.Name -contains 'addressPrefix' -and $Subnet.addressPrefix) { $prefixes += $Subnet.addressPrefix }
    if ($Subnet.PSObject.Properties.Name -contains 'addressPrefixes' -and $Subnet.addressPrefixes) { $prefixes += @($Subnet.addressPrefixes) }
    return $prefixes
}
function Get-ConfiguredVnets {
    <#
    .SYNOPSIS Return the VNet(s) to search for subnets, honoring config.network.vnetId/vnetName.
    .DESCRIPTION
        When the config pins a VNet (vnetId or vnetName), only that VNet is returned so subnet
        resolution stays consistent with Get-VnetId (DNS check). This disambiguates environments
        where two VNets in the same RG share an address space. Falls back to all VNets in the RG.
    #>
    param([object]$Config, [string]$Rg)
    if (-not $Rg) { return @() }
    if ($Config.network.PSObject.Properties.Name -contains 'vnetId' -and $Config.network.vnetId) {
        $v = Get-AzJson -Args @('network', 'vnet', 'show', '--ids', $Config.network.vnetId) -AllowFail
        if ($v) { return @($v) }
    }
    if ($Config.network.PSObject.Properties.Name -contains 'vnetName' -and $Config.network.vnetName) {
        $v = Get-AzJson -Args @('network', 'vnet', 'show', '-g', $Rg, '-n', $Config.network.vnetName) -AllowFail
        if ($v) { return @($v) }
    }
    return @(Get-AzJson -Args @('network', 'vnet', 'list', '-g', $Rg) -AllowFail)
}

# ---------------------------------------------------------------------------
# FR3.8 — dependency spec (formerly dependency_spec.ps1)
# ---------------------------------------------------------------------------
function Invoke-DependencySpec {
    param(
        [object]$Config,
        [ValidateSet('supercomputer', 'workspace', 'bookshelf')][string]$Profile = 'supercomputer',
        [string]$SpecPath = (Join-Path $PSScriptRoot 'dependency-spec.json')
    )
    $null = $Config
    $out = [System.Collections.Generic.List[object]]::new()
    if (-not (Test-Path -LiteralPath $SpecPath)) {
        $out.Add((New-CheckResult -Id 'dependency-spec' -Name "dependency spec $Profile" -Status 'Warn' -Fr 'FR3.8' `
                    -Detail "Dependency spec not found: $SpecPath" `
                    -Remediation 'Update the dependency spec in the feature PR that changed the dependency.'))
    } else {
        try {
            $spec = Get-Content -LiteralPath $SpecPath -Raw | ConvertFrom-Json -ErrorAction Stop
            $hasProfile = $spec.PSObject.Properties.Name -contains 'profiles' -and
                $spec.profiles.PSObject.Properties.Name -contains $Profile
            if (-not $hasProfile) {
                $out.Add((New-CheckResult -Id 'dependency-spec' -Name "dependency spec $Profile" -Status 'Fail' -Fr 'FR3.8' `
                            -Detail "Profile '$Profile' is missing from $SpecPath." `
                            -Remediation 'Update the dependency spec in the feature PR that changed the dependency.'))
            } else {
                $updated = [datetime]::Parse($spec.updated).Date
                $maxAgeDays = if ($spec.PSObject.Properties.Name -contains 'maxAgeDays') { [int]$spec.maxAgeDays } else { 180 }
                $ageDays = [int]((Get-Date).Date - $updated).TotalDays
                $stale = $ageDays -gt $maxAgeDays
                $profileSpec = $spec.profiles.$Profile
                $out.Add((New-CheckResult -Id 'dependency-spec' -Name "dependency spec $Profile" -Status ($stale ? 'Warn' : 'Pass') -Fr 'FR3.8' `
                            -Detail "specVersion=$($spec.schemaVersion) updated=$($spec.updated) ageDays=$ageDays checks=$(@($profileSpec.checks).Count)" `
                            -Remediation ($stale ? 'Update the dependency spec in the feature PR that changed the dependency.' : '') `
                            -Data ([pscustomobject]@{ path = $SpecPath; schemaVersion = $spec.schemaVersion; updated = $spec.updated; profile = $Profile; dependencySet = $profileSpec })))
            }
        } catch {
            $out.Add((New-CheckResult -Id 'dependency-spec' -Name "dependency spec $Profile" -Status 'Fail' -Fr 'FR3.8' `
                        -Detail "Dependency spec is invalid JSON or has an invalid date: $($_.Exception.Message)" `
                        -Remediation 'Update the dependency spec in the feature PR that changed the dependency.'))
        }
    }
    return $out.ToArray()
}

# ---------------------------------------------------------------------------
# FR3.6a — subnet delegations (formerly check_subnet_delegation.ps1)
# ---------------------------------------------------------------------------
function Invoke-CheckSubnetDelegation {
    param([object]$Config, [string]$Profile = 'supercomputer')
    $out = [System.Collections.Generic.List[object]]::new()
    $expected = @{
        'agent-containerapp'     = 'Microsoft.App/environments'
        'workspace-containerapp' = 'Microsoft.App/environments'
        'search-containerapp'    = 'Microsoft.App/environments'
        'managedcluster'         = 'Microsoft.ContainerService/managedClusters'
        'nodepool'               = 'none'
        'private-endpoints'      = 'none'
        'spare'                  = 'none'
    }
    function Find-Subnet {
        param([object]$Config, [object]$Subnet)
        if ($Subnet.PSObject.Properties.Name -contains 'id' -and $Subnet.id) {
            return Get-AzJson -Args @('network', 'vnet', 'subnet', 'show', '--ids', $Subnet.id) -AllowFail
        }
        $rg = Get-NetworkResourceGroup -Config $Config
        if (-not $rg) { return $null }
        foreach ($vnet in (Get-ConfiguredVnets -Config $Config -Rg $rg)) {
            foreach ($sn in @($vnet.subnets)) {
                if ((Get-SubnetPrefixes -Subnet $sn) -contains $Subnet.cidr) { return $sn }
            }
        }
        return $null
    }
    foreach ($sn in @($Config.network.subnets)) {
        $role = $sn.role
        if (-not $expected.ContainsKey($role)) { continue }
        $id = "subnet-delegation-$role"
        if (Test-ConfigWaiver -Config $Config -CheckId $id) {
            $out.Add((New-CheckResult -Id $id -Name "subnet delegation $role" -Status 'Waived' -Fr 'FR3.6a' -Detail 'Waived by config.'))
            continue
        }
        $actualSubnet = Find-Subnet -Config $Config -Subnet $sn
        if (-not $actualSubnet) {
            $out.Add((New-CheckResult -Id $id -Name "subnet delegation $role" -Status 'Fail' -Fr 'FR3.6a' `
                        -Detail "Unable to locate deployed subnet for role=$role cidr=$($sn.cidr)." `
                        -Remediation 'Wrong delegation: set the required delegation (Stage 2 network_provision).' `
                        -Data ([pscustomobject]@{ role = $role; expected = $expected[$role]; actual = $null; ok = $false })))
            continue
        }
        $actualDelegations = @($actualSubnet.delegations | ForEach-Object { $_.serviceName } | Where-Object { $_ })
        $actual = if ($actualDelegations.Count) { $actualDelegations -join ',' } else { 'none' }
        $ok = $actual -eq $expected[$role]
        $out.Add((New-CheckResult -Id $id -Name "subnet delegation $role" -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR3.6a' `
                    -Detail "expected=$($expected[$role]) actual=$actual subnet=$($actualSubnet.name)" `
                    -Remediation ($ok ? '' : 'Wrong delegation: set the required delegation (Stage 2 network_provision).') `
                    -Data ([pscustomobject]@{ role = $role; expected = $expected[$role]; actual = $actual; ok = $ok; subnetId = $actualSubnet.id })))
    }
    return $out.ToArray()
}

# ---------------------------------------------------------------------------
# FR3.6b — effective NSG (formerly check_nsg_effective.ps1)
# ---------------------------------------------------------------------------
function Invoke-CheckNsgEffective {
    param([object]$Config, [string]$Profile = 'supercomputer')
    $out = [System.Collections.Generic.List[object]]::new()
    function Find-Subnet {
        param([object]$Config, [object]$Subnet)
        if ($Subnet.PSObject.Properties.Name -contains 'id' -and $Subnet.id) { return Get-AzJson -Args @('network', 'vnet', 'subnet', 'show', '--ids', $Subnet.id) -AllowFail }
        $rg = Get-NetworkResourceGroup -Config $Config
        if (-not $rg) { return $null }
        foreach ($vnet in (Get-ConfiguredVnets -Config $Config -Rg $rg)) {
            foreach ($candidate in @($vnet.subnets)) {
                if ((Get-SubnetPrefixes -Subnet $candidate) -contains $Subnet.cidr) { return $candidate }
            }
        }
        return $null
    }
    function Find-NicForSubnet {
        param([string]$ResourceGroup, [string]$SubnetId)
        if (-not $ResourceGroup -or -not $SubnetId) { return $null }
        $nics = @(Get-AzJson -Args @('network', 'nic', 'list', '-g', $ResourceGroup) -AllowFail)
        foreach ($nic in $nics) {
            foreach ($ipcfg in @($nic.ipConfigurations)) {
                if ($ipcfg.subnet.id -eq $SubnetId -and $nic.provisioningState -eq 'Succeeded') { return $nic }
            }
        }
        return $null
    }
    function Test-Allow443Rule {
        param([object[]]$Rules)
        foreach ($r in @($Rules)) {
            $direction = if ($r.PSObject.Properties.Name -contains 'direction') { $r.direction } else { '' }
            $access = if ($r.PSObject.Properties.Name -contains 'access') { $r.access } else { '' }
            $ports = @()
            if ($r.PSObject.Properties.Name -contains 'destinationPortRange' -and $r.destinationPortRange) { $ports += $r.destinationPortRange }
            if ($r.PSObject.Properties.Name -contains 'destinationPortRanges' -and $r.destinationPortRanges) { $ports += @($r.destinationPortRanges) }
            if ($direction -eq 'Outbound' -and $access -eq 'Allow' -and ($ports -contains '443' -or $ports -contains '*')) { return $true }
        }
        return $false
    }
    function Test-EastWestRule {
        param([object[]]$Rules)
        foreach ($r in @($Rules)) {
            $direction = if ($r.PSObject.Properties.Name -contains 'direction') { $r.direction } else { '' }
            $access = if ($r.PSObject.Properties.Name -contains 'access') { $r.access } else { '' }
            $ports = @()
            if ($r.PSObject.Properties.Name -contains 'destinationPortRange' -and $r.destinationPortRange) { $ports += $r.destinationPortRange }
            if ($r.PSObject.Properties.Name -contains 'destinationPortRanges' -and $r.destinationPortRanges) { $ports += @($r.destinationPortRanges) }
            $source = if ($r.PSObject.Properties.Name -contains 'sourceAddressPrefix') { $r.sourceAddressPrefix } else { '' }
            $dest = if ($r.PSObject.Properties.Name -contains 'destinationAddressPrefix') { $r.destinationAddressPrefix } else { '' }
            $portOk = $ports -contains '*' -or $ports -contains '10250' -or $ports -contains '443'
            if ($direction -eq 'Inbound' -and $access -eq 'Allow' -and $portOk -and ($source -eq 'VirtualNetwork' -or $dest -eq 'VirtualNetwork' -or $source -eq '*' -or $dest -eq '*')) { return $true }
        }
        return $false
    }
    $rg = Get-NetworkResourceGroup -Config $Config
    foreach ($sn in @($Config.network.subnets)) {
        $role = $sn.role
        $id = "nsg-effective-$role"
        if (Test-ConfigWaiver -Config $Config -CheckId $id) {
            $out.Add((New-CheckResult -Id $id -Name "effective NSG $role" -Status 'Waived' -Fr 'FR3.6b' -Detail 'Waived by config.'))
            continue
        }
        $subnet = Find-Subnet -Config $Config -Subnet $sn
        if (-not $subnet) {
            $out.Add((New-CheckResult -Id $id -Name "effective NSG $role" -Status 'Fail' -Fr 'FR3.6b' `
                        -Detail "Unable to locate subnet for role=$role." -Remediation 'NSG denies egress or UDR black-holes the route.'))
            continue
        }
        $nic = Find-NicForSubnet -ResourceGroup $rg -SubnetId $subnet.id
        $rules = @()
        $source = 'effective'
        if ($nic) {
            $effective = @(Get-AzJson -Args @('network', 'nic', 'list-effective-nsg', '--ids', $nic.id) -AllowFail)
            foreach ($group in $effective) { $rules += @($group.effectiveSecurityRules) }
        } elseif ($subnet.PSObject.Properties.Name -contains 'networkSecurityGroup' -and $subnet.networkSecurityGroup -and $subnet.networkSecurityGroup.id) {
            $nsg = Get-AzJson -Args @('network', 'nsg', 'show', '--ids', $subnet.networkSecurityGroup.id) -AllowFail
            if ($nsg) { $rules = @($nsg.securityRules) + @($nsg.defaultSecurityRules); $source = 'subnet-nsg-fallback' }
        }
        $allow443 = Test-Allow443Rule -Rules $rules
        $eastWest = Test-EastWestRule -Rules $rules
        $missing = @()
        if (-not $allow443) { $missing += 'Allow-Internet-Out-443' }
        if (-not $eastWest) { $missing += 'East-West-Discovery' }
        $status = if ($missing.Count) { 'Fail' } elseif ($source -eq 'subnet-nsg-fallback') { 'Warn' } else { 'Pass' }
        $detail = if ($missing.Count) { "missing=$($missing -join ',') source=$source" } else { "required allow paths present source=$source" }
        $out.Add((New-CheckResult -Id $id -Name "effective NSG $role" -Status $status -Fr 'FR3.6b' `
                    -Detail $detail -Remediation ($missing.Count ? 'NSG denies egress or UDR black-holes the route.' : '') `
                    -Data ([pscustomobject]@{ role = $role; subnetId = $subnet.id; nicId = if ($nic) { $nic.id } else { $null }; missingRules = $missing; source = $source })))
    }
    return $out.ToArray()
}

# ---------------------------------------------------------------------------
# FR3.6c — effective routes (formerly check_effective_routes.ps1)
# ---------------------------------------------------------------------------
function Invoke-CheckEffectiveRoutes {
    param([object]$Config, [string]$Profile = 'supercomputer')
    $out = [System.Collections.Generic.List[object]]::new()
    function Find-Subnet {
        param([object]$Config, [object]$Subnet)
        if ($Subnet.PSObject.Properties.Name -contains 'id' -and $Subnet.id) { return Get-AzJson -Args @('network', 'vnet', 'subnet', 'show', '--ids', $Subnet.id) -AllowFail }
        $rg = Get-NetworkResourceGroup -Config $Config
        if (-not $rg) { return $null }
        foreach ($vnet in (Get-ConfiguredVnets -Config $Config -Rg $rg)) {
            foreach ($candidate in @($vnet.subnets)) {
                if ((Get-SubnetPrefixes -Subnet $candidate) -contains $Subnet.cidr) { return $candidate }
            }
        }
        return $null
    }
    function Find-NicForSubnet {
        param([string]$ResourceGroup, [string]$SubnetId)
        if (-not $ResourceGroup -or -not $SubnetId) { return $null }
        $nics = @(Get-AzJson -Args @('network', 'nic', 'list', '-g', $ResourceGroup) -AllowFail)
        foreach ($nic in $nics) {
            foreach ($ipcfg in @($nic.ipConfigurations)) {
                if ($ipcfg.subnet.id -eq $SubnetId -and $ipcfg.privateIPAddress) { return $nic }
            }
        }
        return $null
    }
    function ConvertFrom-UInt32Ip {
        param([Parameter(Mandatory)][uint64]$Value)
        $bytes = [System.BitConverter]::GetBytes([uint32]$Value)
        [Array]::Reverse($bytes)
        return ([System.Net.IPAddress]::new($bytes)).IPAddressToString
    }
    function Get-ProbeIpInCidr {
        param([Parameter(Mandatory)][string]$Cidr)
        $info = Get-CidrInfo -Cidr $Cidr
        return ConvertFrom-UInt32Ip -Value ([uint64]$info.Network + 4)
    }
    function Test-RouteCovers {
        param([string]$RoutePrefix, [string]$TargetCidr)
        if (-not $RoutePrefix -or -not $TargetCidr -or $RoutePrefix -eq 'Internet') { return $false }
        try { return Test-CidrContains -Outer $RoutePrefix -Inner $TargetCidr } catch { return $false }
    }
    function Get-RouteTableFromSubnet {
        param([object]$Subnet)
        if ($Subnet.PSObject.Properties.Name -contains 'routeTable' -and $Subnet.routeTable -and $Subnet.routeTable.id) {
            return Get-AzJson -Args @('network', 'route-table', 'show', '--ids', $Subnet.routeTable.id) -AllowFail
        }
        return $null
    }
    function Get-NicPrivateIp {
        param([object]$Nic, [string]$SubnetId)
        foreach ($ipcfg in @($Nic.ipConfigurations)) {
            if ($ipcfg.subnet.id -eq $SubnetId -and $ipcfg.privateIPAddress) { return $ipcfg.privateIPAddress }
        }
        return ''
    }
    function Get-VmParts {
        param([string]$VmId)
        if (-not $VmId) { return $null }
        $parts = $VmId -split '/'
        [pscustomobject]@{ resourceGroup = $parts[4]; name = $parts[-1] }
    }
    $rg = Get-NetworkResourceGroup -Config $Config
    $nvaNextHop = if ($Config.network.PSObject.Properties.Name -contains 'nvaNextHop') { $Config.network.nvaNextHop } else { '' }
    $managed = @($Config.network.subnets | Where-Object { $_.role -eq 'managedcluster' } | Select-Object -First 1)
    $managedCidr = if ($managed.Count) { $managed[0].cidr } else { '' }
    foreach ($sn in @($Config.network.subnets)) {
        $role = $sn.role
        $id = "effective-routes-$role"
        if (Test-ConfigWaiver -Config $Config -CheckId $id) {
            $out.Add((New-CheckResult -Id $id -Name "effective routes $role" -Status 'Waived' -Fr 'FR3.6c' -Detail 'Waived by config.'))
            continue
        }
        $subnet = Find-Subnet -Config $Config -Subnet $sn
        if (-not $subnet) {
            $missingRemediation = if ($role -eq 'managedcluster') { 'Managed cluster routed via NVA, AKS NotReady -> Set managed cluster subnet to VnetLocal; delete+recreate route.' } else { 'NSG denies egress or UDR black-holes the route.' }
            $out.Add((New-CheckResult -Id $id -Name "effective routes $role" -Status 'Fail' -Fr 'FR3.6c' `
                        -Detail "Unable to locate subnet for role=$role." -Remediation $missingRemediation))
            continue
        }
        $nic = Find-NicForSubnet -ResourceGroup $rg -SubnetId $subnet.id
        $source = 'effective'
        $nextHopType = ''
        $nextHopIp = ''
        $nwNextHop = $null
        if ($nic) {
            $routes = @(Get-AzJson -Args @('network', 'nic', 'show-effective-route-table', '--ids', $nic.id) -AllowFail)
            $flatRoutes = @($routes | Where-Object { $_.PSObject.Properties.Name -contains 'value' } | ForEach-Object { $_.value } | ForEach-Object { $_ })
            if ($role -eq 'managedcluster') {
                $match = $flatRoutes | Where-Object { @($_.addressPrefix | Where-Object { Test-RouteCovers -RoutePrefix $_ -TargetCidr $sn.cidr }).Count -gt 0 -and $_.nextHopType -eq 'VnetLocal' } | Select-Object -First 1
            } else {
                $match = $flatRoutes | Where-Object { @($_.addressPrefix) -contains '0.0.0.0/0' } | Select-Object -First 1
            }
            if ($match) {
                $nextHopType = $match.nextHopType
                $nextHopIp = if ($match.PSObject.Properties.Name -contains 'nextHopIpAddress') { $match.nextHopIpAddress } else { '' }
            }
            $vm = if ($nic.PSObject.Properties.Name -contains 'virtualMachine' -and $nic.virtualMachine) { Get-VmParts -VmId $nic.virtualMachine.id } else { $null }
            if ($vm) {
                $sourceIp = Get-NicPrivateIp -Nic $nic -SubnetId $subnet.id
                $destIp = if ($role -eq 'managedcluster') { Get-ProbeIpInCidr -Cidr $sn.cidr } else { '23.221.220.83' }
                $nwNextHop = Get-AzJson -Args @('network', 'watcher', 'show-next-hop', '-g', $vm.resourceGroup, '--vm', $vm.name, '--source-ip', $sourceIp, '--dest-ip', $destIp) -AllowFail
            }
        } else {
            $source = 'route-table-fallback'
            $rt = Get-RouteTableFromSubnet -Subnet $subnet
            if ($rt) {
                $routes = @($rt.routes)
                if ($role -eq 'managedcluster') {
                    $match = $routes | Where-Object { $_.addressPrefix -eq $sn.cidr -and $_.nextHopType -eq 'VnetLocal' } | Select-Object -First 1
                } else {
                    $match = $routes | Where-Object { $_.addressPrefix -eq '0.0.0.0/0' } | Select-Object -First 1
                }
                if ($match) {
                    $nextHopType = $match.nextHopType
                    $nextHopIp = if ($match.PSObject.Properties.Name -contains 'nextHopIpAddress') { $match.nextHopIpAddress } else { '' }
                }
            }
        }
        $ok = if ($role -eq 'managedcluster') {
            $nextHopType -eq 'VnetLocal'
        } else {
            $nextHopType -eq 'VirtualAppliance' -and ((-not $nvaNextHop) -or $nextHopIp -eq $nvaNextHop)
        }
        $status = if ($ok -and $source -eq 'route-table-fallback') { 'Warn' } elseif ($ok) { 'Pass' } else { 'Fail' }
        $remediation = if ($ok) { '' } elseif ($role -eq 'managedcluster') { 'Managed cluster routed via NVA, AKS NotReady -> Set managed cluster subnet to VnetLocal; delete+recreate route.' } else { 'NSG denies egress or UDR black-holes the route.' }
        $out.Add((New-CheckResult -Id $id -Name "effective routes $role" -Status $status -Fr 'FR3.6c' `
                    -Detail "nextHopType=$nextHopType nextHopIp=$nextHopIp source=$source" -Remediation $remediation `
                    -Data ([pscustomobject]@{ role = $role; subnetId = $subnet.id; nicId = if ($nic) { $nic.id } else { $null }; nextHop = $nextHopType; nextHopIp = $nextHopIp; networkWatcher = $nwNextHop; source = $source; managedCidr = $managedCidr })))
    }
    return $out.ToArray()
}

# ---------------------------------------------------------------------------
# FR3.6d — private DNS zones + private endpoints (formerly check_dns_and_pe.ps1)
# ---------------------------------------------------------------------------
function Invoke-CheckDnsAndPe {
    param([object]$Config, [string]$Profile = 'supercomputer')
    $out = [System.Collections.Generic.List[object]]::new()
    $defaultZones = @(
        'privatelink.blob.core.windows.net',
        'privatelink.queue.core.windows.net',
        'privatelink.file.core.windows.net',
        'privatelink.table.core.windows.net',
        'privatelink.dfs.core.windows.net',
        'privatelink.vaultcore.azure.net',
        'privatelink.search.windows.net',
        'privatelink.cognitiveservices.azure.com',
        'privatelink.openai.azure.com',
        'privatelink.services.ai.azure.com',
        'privatelink.documents.azure.com'
    )
    function Get-DnsResourceGroup {
        param([object]$Config)
        if ($Config.network.PSObject.Properties.Name -contains 'dnsResourceGroup' -and $Config.network.dnsResourceGroup) { return $Config.network.dnsResourceGroup }
        if ($Config.PSObject.Properties.Name -contains 'dnsResourceGroup' -and $Config.dnsResourceGroup) { return $Config.dnsResourceGroup }
        if ($Config.network.PSObject.Properties.Name -contains 'networkResourceGroup' -and $Config.network.networkResourceGroup) { return $Config.network.networkResourceGroup }
        if ($Config.PSObject.Properties.Name -contains 'resourceGroup' -and $Config.resourceGroup) { return $Config.resourceGroup }
        return ''
    }
    function Get-VnetId {
        param([object]$Config, [string]$Rg)
        if ($Config.network.PSObject.Properties.Name -contains 'vnetId' -and $Config.network.vnetId) { return $Config.network.vnetId }
        if (-not $Rg) { return '' }
        if ($Config.network.PSObject.Properties.Name -contains 'vnetName' -and $Config.network.vnetName) {
            $vnet = Get-AzJson -Args @('network', 'vnet', 'show', '-g', $Rg, '-n', $Config.network.vnetName) -AllowFail
            if ($vnet) { return $vnet.id }
        }
        $vnets = @(Get-AzJson -Args @('network', 'vnet', 'list', '-g', $Rg) -AllowFail)
        foreach ($vnet in $vnets) {
            $spaces = if ($vnet.PSObject.Properties.Name -contains 'addressSpace' -and $vnet.addressSpace) { @($vnet.addressSpace.addressPrefixes) } else { @() }
            foreach ($space in $spaces) {
                if ($space -eq $Config.network.vnetCidr) { return $vnet.id }
            }
        }
        return ''
    }
    function Get-Zones {
        param([string]$ProfileName)
        $specPath = Join-Path $PSScriptRoot 'dependency-spec.json'
        if (Test-Path -LiteralPath $specPath) {
            try {
                $spec = Get-Content -LiteralPath $specPath -Raw | ConvertFrom-Json -ErrorAction Stop
                if ($spec.profiles.PSObject.Properties.Name -contains $ProfileName) { return @($spec.profiles.$ProfileName.privateDnsZones) }
            } catch {}
        }
        return $defaultZones
    }
    function Get-PrivateEndpointsResourceGroups {
        param([object]$Config, [string]$DefaultRg)
        $groups = @($DefaultRg)
        if ($Config.PSObject.Properties.Name -contains 'privateEndpointResourceGroups' -and $Config.privateEndpointResourceGroups) { $groups += @($Config.privateEndpointResourceGroups) }
        if ($Config.PSObject.Properties.Name -contains 'managedResourceGroup' -and $Config.managedResourceGroup) { $groups += $Config.managedResourceGroup }
        return @($groups | Where-Object { $_ } | Sort-Object -Unique)
    }
    $rg = Get-DnsResourceGroup -Config $Config
    $vnetId = Get-VnetId -Config $Config -Rg $rg
    $zones = Get-Zones -ProfileName $Profile
    foreach ($zoneName in $zones) {
        $id = "private-dns-zone-$zoneName"
        if (Test-ConfigWaiver -Config $Config -CheckId $id) {
            $out.Add((New-CheckResult -Id $id -Name "private DNS $zoneName" -Status 'Waived' -Fr 'FR3.6d' -Detail 'Waived by config.'))
            continue
        }
        $zone = if ($rg) { Get-AzJson -Args @('network', 'private-dns', 'zone', 'show', '-g', $rg, '-n', $zoneName) -AllowFail } else { $null }
        if (-not $zone) {
            $out.Add((New-CheckResult -Id $id -Name "private DNS $zoneName" -Status 'Fail' -Fr 'FR3.6d' `
                        -Detail "Zone not found in resource group '$rg'." -Remediation 'Fix private DNS zone links / VNet DNS.' `
                        -Data ([pscustomobject]@{ zone = $zoneName; linked = $false; exists = $false })))
            continue
        }
        $links = @(Get-AzJson -Args @('network', 'private-dns', 'link', 'vnet', 'list', '-g', $rg, '-z', $zoneName) -AllowFail)
        $linked = if ($vnetId) { [bool]($links | Where-Object { $_.PSObject.Properties.Name -contains 'virtualNetwork' -and $_.virtualNetwork -and $_.virtualNetwork.id -eq $vnetId }) } else { @($links).Count -gt 0 }
        $out.Add((New-CheckResult -Id $id -Name "private DNS $zoneName" -Status ($linked ? 'Pass' : 'Fail') -Fr 'FR3.6d' `
                    -Detail ($linked ? "linked to VNet" : "zone exists but no matching VNet link for $vnetId") `
                    -Remediation ($linked ? '' : 'Fix private DNS zone links / VNet DNS.') `
                    -Data ([pscustomobject]@{ zone = $zoneName; linked = $linked; exists = $true; linkCount = @($links).Count })))
    }
    $peGroups = Get-PrivateEndpointsResourceGroups -Config $Config -DefaultRg $rg
    $pes = @()
    foreach ($peRg in $peGroups) {
        $pes += @(Get-AzJson -Args @('network', 'private-endpoint', 'list', '-g', $peRg) -AllowFail | ForEach-Object { $_ })
    }
    $expectedPeCount = if ($Profile -eq 'bookshelf') { 3 } else { 0 }
    if ($expectedPeCount -gt 0 -and @($pes).Count -lt $expectedPeCount) {
        $out.Add((New-CheckResult -Id 'private-endpoint-count' -Name "private endpoint count $Profile" -Status 'Fail' -Fr 'FR3.6d' `
                    -Detail "expected at least $expectedPeCount private endpoints; found $(@($pes).Count)." `
                    -Remediation 'Fix private DNS zone links / VNet DNS.'))
    }
    foreach ($pe in @($pes)) {
        $connections = @()
        if ($pe.PSObject.Properties.Name -contains 'privateLinkServiceConnections' -and $pe.privateLinkServiceConnections) { $connections += @($pe.privateLinkServiceConnections) }
        if ($pe.PSObject.Properties.Name -contains 'manualPrivateLinkServiceConnections' -and $pe.manualPrivateLinkServiceConnections) { $connections += @($pe.manualPrivateLinkServiceConnections) }
        $approved = $false
        foreach ($conn in $connections) {
            if ($conn.PSObject.Properties.Name -contains 'privateLinkServiceConnectionState' -and $conn.privateLinkServiceConnectionState.status -eq 'Approved') { $approved = $true }
        }
        $dnsConfigs = if ($pe.PSObject.Properties.Name -contains 'customDnsConfigs' -and $pe.customDnsConfigs) { @($pe.customDnsConfigs) } else { @() }
        $dnsCount = @($dnsConfigs | Where-Object { ($_.PSObject.Properties.Name -contains 'fqdn' -and $_.fqdn) -or ($_.PSObject.Properties.Name -contains 'ipAddresses' -and @($_.ipAddresses).Count) }).Count
        $ok = $approved -and $dnsCount -gt 0
        $peSubnetId = if ($pe.PSObject.Properties.Name -contains 'subnet' -and $pe.subnet -and $pe.subnet.id) { $pe.subnet.id } else { '' }
        $out.Add((New-CheckResult -Id "private-endpoint-$($pe.name)" -Name "private endpoint $($pe.name)" -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR3.6d' `
                    -Detail "approved=$approved dnsConfigs=$dnsCount subnet=$peSubnetId" `
                    -Remediation ($ok ? '' : 'Fix private DNS zone links / VNet DNS.') `
                    -Data ([pscustomobject]@{ name = $pe.name; approved = $approved; dnsCount = $dnsCount; id = $pe.id })))
    }
    if (-not @($pes).Count) {
        $out.Add((New-CheckResult -Id 'private-endpoints-present' -Name 'private endpoints discovered' -Status 'Warn' -Fr 'FR3.6d' `
                    -Detail "No private endpoints found in: $($peGroups -join ', ')." `
                    -Remediation 'Fix private DNS zone links / VNet DNS.'))
    }
    return $out.ToArray()
}

# ---------------------------------------------------------------------------
# FR3.7a-f — probe output parsers (formerly probe_*.ps1)
# ---------------------------------------------------------------------------
function Invoke-ProbeDns {
    param([object]$Config, [string]$RemoteOutput)
    $out = [System.Collections.Generic.List[object]]::new()
    $probeHosts = @(
        'mcr.microsoft.com',
        'packages.aks.azure.com',
        'packages.microsoft.com',
        'management.azure.com',
        'login.microsoftonline.com',
        "$($Config.workloadRegion).data.mcr.microsoft.com"
    )
    $lines = if ($RemoteOutput -and (Test-Path -LiteralPath $RemoteOutput)) { Get-Content -LiteralPath $RemoteOutput } else { @() }
    foreach ($hostName in $probeHosts) {
        $line = $lines | Where-Object { $_ -match "^DNS\s+$([regex]::Escape($hostName))\s+" } | Select-Object -First 1
        if ($line) {
            $m = [regex]::Match($line, '^DNS\s+(\S+)\s+(OK|FAIL)\s+(.+)$')
            $ok = $m.Success -and $m.Groups[2].Value -eq 'OK'
            $ip = if ($ok) { $m.Groups[3].Value.Trim() } else { '' }
        } else {
            try {
                $addr = [System.Net.Dns]::GetHostAddresses($hostName) | Select-Object -First 1
                $ok = $null -ne $addr
                $ip = if ($ok) { $addr.IPAddressToString } else { '' }
            } catch {
                $ok = $false
                $ip = ''
            }
        }
        $out.Add((New-CheckResult -Id "dns-$hostName" -Name "DNS $hostName" -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR3.7a' `
                    -Detail ($ok ? "resolved $ip" : 'DNS FAIL') -Remediation ($ok ? '' : 'Fix VNet DNS / private DNS zone links.') `
                    -Data ([pscustomobject]@{ host = $hostName; resolved = $ok; ip = $ip })))
    }
    return $out.ToArray()
}
function Invoke-ProbeTcp443 {
    param([object]$Config, [string]$RemoteOutput)
    $out = [System.Collections.Generic.List[object]]::new()
    $probeHosts = @('mcr.microsoft.com', 'packages.aks.azure.com', 'packages.microsoft.com', 'management.azure.com', 'login.microsoftonline.com', "$($Config.workloadRegion).data.mcr.microsoft.com")
    $lines = if ($RemoteOutput -and (Test-Path -LiteralPath $RemoteOutput)) { Get-Content -LiteralPath $RemoteOutput } else { @() }
    foreach ($hostName in $probeHosts) {
        $line = $lines | Where-Object { $_ -match "^TCP443\s+$([regex]::Escape($hostName))\s+" } | Select-Object -First 1
        if (-not $line) {
            $out.Add((New-CheckResult -Id "tcp443-$hostName" -Name "TCP 443 $hostName" -Status 'Skip' -Fr 'FR3.7b' `
                        -Detail 'No TCP443 probe output found.' -Data ([pscustomobject]@{ host = $hostName; port443 = $null })))
            continue
        }
        $open = $line -match '\sOPEN\s*$'
        $out.Add((New-CheckResult -Id "tcp443-$hostName" -Name "TCP 443 $hostName" -Status ($open ? 'Pass' : 'Fail') -Fr 'FR3.7b' `
                    -Detail ($open ? '443 OPEN' : '443 BLOCKED') -Remediation ($open ? '' : 'NSG denies egress or UDR black-holes the route.') `
                    -Data ([pscustomobject]@{ host = $hostName; port443 = $open })))
    }
    return $out.ToArray()
}
function Invoke-ProbeHttps {
    param([object]$Config, [string]$RemoteOutput)
    $null = $Config
    $out = [System.Collections.Generic.List[object]]::new()
    $expected = @(
        @{ Host = 'mcr.microsoft.com'; Codes = @(200) },
        @{ Host = 'packages.aks.azure.com'; Codes = @(400) },
        @{ Host = 'management.azure.com'; Codes = @(400, 401) },
        @{ Host = 'login.microsoftonline.com'; Codes = @(200) }
    )
    $lines = if ($RemoteOutput -and (Test-Path -LiteralPath $RemoteOutput)) { Get-Content -LiteralPath $RemoteOutput } else { @() }
    foreach ($probe in $expected) {
        $line = $lines | Where-Object { $_ -match "^HTTPS\s+$([regex]::Escape($probe.Host))\s+" } | Select-Object -First 1
        if (-not $line) {
            $out.Add((New-CheckResult -Id "https-$($probe.Host)" -Name "HTTPS $($probe.Host)" -Status 'Skip' -Fr 'FR3.7c' `
                        -Detail 'No HTTPS probe output found.' -Data ([pscustomobject]@{ host = $probe.Host; expected = $probe.Codes; actual = $null })))
            continue
        }
        $m = [regex]::Match($line, '^HTTPS\s+\S+\s+(\d{3}|000)$')
        $actual = if ($m.Success) { [int]$m.Groups[1].Value } else { 0 }
        $ok = $probe.Codes -contains $actual
        $out.Add((New-CheckResult -Id "https-$($probe.Host)" -Name "HTTPS $($probe.Host)" -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR3.7c' `
                    -Detail "HTTP $actual; expected $($probe.Codes -join '/')" -Remediation ($ok ? '' : 'NVA allowlist incomplete or TLS-inspecting the FQDN.') `
                    -Data ([pscustomobject]@{ host = $probe.Host; expected = $probe.Codes; actual = $actual })))
    }
    return $out.ToArray()
}
function Invoke-ProbeArtifacts {
    param([object]$Config, [string]$RemoteOutput)
    $null = $Config
    $out = [System.Collections.Generic.List[object]]::new()
    $artifacts = @('packages-microsoft-prod.deb', 'kubernetes-node-linux-amd64.tar.gz', 'ubuntu-jammy-Release')
    $lines = if ($RemoteOutput -and (Test-Path -LiteralPath $RemoteOutput)) { Get-Content -LiteralPath $RemoteOutput } else { @() }
    foreach ($artifact in $artifacts) {
        $line = $lines | Where-Object { $_ -match "^ARTIFACT\s+$([regex]::Escape($artifact))\s+" } | Select-Object -First 1
        if (-not $line) {
            $out.Add((New-CheckResult -Id "artifact-$artifact" -Name "artifact $artifact" -Status 'Skip' -Fr 'FR3.7d' `
                        -Detail 'No artifact probe output found.' -Data ([pscustomobject]@{ artifact = $artifact; ok = $null; bytes = $null })))
            continue
        }
        $m = [regex]::Match($line, '^ARTIFACT\s+(\S+)\s+(OK|FAIL)\s+(\d+)$')
        $ok = $m.Success -and $m.Groups[2].Value -eq 'OK'
        $bytes = if ($m.Success) { [int64]$m.Groups[3].Value } else { 0 }
        $out.Add((New-CheckResult -Id "artifact-$artifact" -Name "artifact $artifact" -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR3.7d' `
                    -Detail ($ok ? "downloaded $bytes bytes" : 'download failed') -Remediation ($ok ? '' : 'NVA allowlist incomplete or TLS-inspecting the FQDN.') `
                    -Data ([pscustomobject]@{ artifact = $artifact; ok = $ok; bytes = $bytes })))
    }
    return $out.ToArray()
}
function Invoke-ProbePeResolution {
    param([object]$Config, [string]$RemoteOutput)
    $out = [System.Collections.Generic.List[object]]::new()
    function Test-PrivateIp {
        param([Parameter(Mandatory)][string]$Ip)
        try {
            $u = ConvertTo-UInt32Ip $Ip
            return (Test-CidrContains -Outer '10.0.0.0/8' -Inner "$Ip/32") -or
                (Test-CidrContains -Outer '172.16.0.0/12' -Inner "$Ip/32") -or
                (Test-CidrContains -Outer '192.168.0.0/16' -Inner "$Ip/32") -or
                ($u -ge (ConvertTo-UInt32Ip '100.64.0.0') -and $u -le (ConvertTo-UInt32Ip '100.127.255.255'))
        } catch {
            return $false
        }
    }
    $fqdnProps = @('privateEndpointFqdns', 'privateEndpointFQDNs', 'privatelinkFqdns')
    $fqdns = @()
    foreach ($p in $fqdnProps) {
        if ($Config.PSObject.Properties.Name -contains $p -and $Config.$p) { $fqdns += @($Config.$p) }
        if ($Config.network.PSObject.Properties.Name -contains $p -and $Config.network.$p) { $fqdns += @($Config.network.$p) }
    }
    if ($Config.PSObject.Properties.Name -contains 'privateEndpoints' -and $Config.privateEndpoints) {
        foreach ($pe in @($Config.privateEndpoints)) {
            if ($pe.PSObject.Properties.Name -contains 'fqdn' -and $pe.fqdn) { $fqdns += $pe.fqdn }
            if ($pe.PSObject.Properties.Name -contains 'fqdns' -and $pe.fqdns) { $fqdns += @($pe.fqdns) }
        }
    }
    $fqdns = @($fqdns | Where-Object { $_ -and $_ -like '*privatelink*' } | Sort-Object -Unique)
    $lines = if ($RemoteOutput -and (Test-Path -LiteralPath $RemoteOutput)) { Get-Content -LiteralPath $RemoteOutput } else { @() }
    if (-not $fqdns.Count) {
        $out.Add((New-CheckResult -Id 'pe-resolution-input' -Name 'private endpoint FQDN input' -Status 'Warn' -Fr 'FR3.7e' `
                    -Detail 'No privatelink FQDNs were present in config; PE DNS probe skipped.' `
                    -Remediation 'Fix private DNS zone links / VNet DNS.'))
    } else {
        foreach ($fqdn in $fqdns) {
            $line = $lines | Where-Object { $_ -match "^PE\s+$([regex]::Escape($fqdn))\s+" } | Select-Object -First 1
            $m = if ($line) { [regex]::Match($line, '^PE\s+(\S+)\s+(OK|FAIL)\s+(.+)$') } else { $null }
            $ip = if ($m -and $m.Success) { $m.Groups[3].Value.Trim() } else { '' }
            $isPrivate = $ip -and (Test-PrivateIp -Ip $ip)
            $ok = ($m -and $m.Success -and $m.Groups[2].Value -eq 'OK' -and $isPrivate)
            $out.Add((New-CheckResult -Id "pe-resolution-$fqdn" -Name "PE DNS $fqdn" -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR3.7e' `
                        -Detail ($ok ? "private IP $ip" : "resolved '$ip' (private=$isPrivate)") -Remediation ($ok ? '' : 'Fix private DNS zone links / VNet DNS.') `
                        -Data ([pscustomobject]@{ fqdn = $fqdn; ip = $ip; isPrivate = $isPrivate })))
        }
    }
    return $out.ToArray()
}
function Invoke-ProbeEastwest {
    param([object]$Config, [string]$RemoteOutput)
    $null = $Config
    $out = [System.Collections.Generic.List[object]]::new()
    $lines = if ($RemoteOutput -and (Test-Path -LiteralPath $RemoteOutput)) { Get-Content -LiteralPath $RemoteOutput } else { @() }
    $eastwest = @($lines | Where-Object { $_ -match '^EASTWEST\s+' })
    if (-not $eastwest.Count) {
        $out.Add((New-CheckResult -Id 'eastwest-10250' -Name 'east-west TCP 10250' -Status 'Skip' -Fr 'FR3.7f' `
                    -Detail 'No east-west targets were supplied to conntest.sh.' `
                    -Remediation 'Allow east-west 10250 (symmetric routing or explicit rule).'))
    } else {
        foreach ($line in $eastwest) {
            $m = [regex]::Match($line, '^EASTWEST\s+(\S+)\s+(OPEN|BLOCKED)$')
            $target = if ($m.Success) { $m.Groups[1].Value } else { 'unknown' }
            $open = $m.Success -and $m.Groups[2].Value -eq 'OPEN'
            $out.Add((New-CheckResult -Id "eastwest-10250-$target" -Name "east-west 10250 $target" -Status ($open ? 'Pass' : 'Fail') -Fr 'FR3.7f' `
                        -Detail ($open ? '10250 OPEN' : '10250 blocked or timed out') `
                        -Remediation ($open ? '' : 'Allow east-west 10250 (symmetric routing or explicit rule).') `
                        -Data ([pscustomobject]@{ target = $target; port10250Ok = $open })))
        }
    }
    return $out.ToArray()
}

# ---------------------------------------------------------------------------
# FR3.7 — disposable test VM lifecycle (formerly testvm_lifecycle.ps1)
# ---------------------------------------------------------------------------
function Invoke-TestVmLifecycle {
    param(
        [object]$Config,
        [string]$ConfigPath,
        [string]$Profile = 'supercomputer',
        [string]$SubnetId,
        [string]$ResourceGroup,
        [string]$VmName
    )
    $out = [System.Collections.Generic.List[object]]::new()
    function Find-SubnetId {
        param([object]$Config)
        $preferred = @($Config.network.subnets | Where-Object { $_.role -eq 'nodepool' } | Select-Object -First 1)
        if (-not $preferred.Count) { $preferred = @($Config.network.subnets | Where-Object { $_.role -ne 'managedcluster' } | Select-Object -First 1) }
        if (-not $preferred.Count) { return '' }
        $sn = $preferred[0]
        if ($sn.PSObject.Properties.Name -contains 'id' -and $sn.id) { return $sn.id }
        $rg = Get-NetworkResourceGroup -Config $Config
        if (-not $rg) { return '' }
        $vnets = @(Get-AzJson -Args @('network', 'vnet', 'list', '-g', $rg) -AllowFail)
        foreach ($vnet in $vnets) {
            foreach ($candidate in @($vnet.subnets)) {
                if ((Get-SubnetPrefixes -Subnet $candidate) -contains $sn.cidr) { return $candidate.id }
            }
        }
        return ''
    }
    function Select-VmSize {
        param([string]$Location)
        $preferred = @('Standard_D2s_v5', 'Standard_D2s_v4', 'Standard_B2s')
        foreach ($size in $preferred) {
            $sku = @(Get-AzJson -Args @('vm', 'list-skus', '--location', $Location, '--size', $size, '--all') -AllowFail | Where-Object { $_.name -eq $size } | Select-Object -First 1)
            $restrictions = if ($sku.Count -and $sku[0].PSObject.Properties.Name -contains 'restrictions') { @($sku[0].restrictions) } else { @() }
            if ($sku.Count -and -not $restrictions.Count) { return $size }
        }
        return 'Standard_D2s_v5'
    }
    function ConvertTo-BashArrayLiteral {
        param([string[]]$Values)
        if (-not $Values -or -not $Values.Count) { return '()' }
        $quoted = $Values | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }
        return '(' + ($quoted -join ' ') + ')'
    }
    function Get-ConfigArray {
        param([object]$Root, [string[]]$Names)
        $values = @()
        foreach ($name in $Names) {
            if ($Root.PSObject.Properties.Name -contains $name -and $Root.$name) { $values += @($Root.$name) }
        }
        return @($values | Where-Object { $_ } | Sort-Object -Unique)
    }
    if (-not $ResourceGroup) { $ResourceGroup = Get-NetworkResourceGroup -Config $Config }
    if (-not $SubnetId) { $SubnetId = Find-SubnetId -Config $Config }
    if (-not $VmName) { $VmName = ('disc-conntest-{0}' -f (Get-Random -Minimum 10000 -Maximum 99999)) }
    $region = $Config.workloadRegion
    $size = Select-VmSize -Location $region
    $outFile = Join-Path ([System.IO.Path]::GetTempPath()) "$VmName-conntest.txt"
    $nicIds = @()
    $diskIds = @()
    $peFqdns = Get-ConfigArray -Root $Config -Names @('privateEndpointFqdns', 'privateEndpointFQDNs', 'privatelinkFqdns')
    if ($Config.PSObject.Properties.Name -contains 'privateEndpoints' -and $Config.privateEndpoints) {
        foreach ($pe in @($Config.privateEndpoints)) {
            if ($pe.PSObject.Properties.Name -contains 'fqdn' -and $pe.fqdn) { $peFqdns += $pe.fqdn }
            if ($pe.PSObject.Properties.Name -contains 'fqdns' -and $pe.fqdns) { $peFqdns += @($pe.fqdns) }
        }
    }
    $peFqdns = @($peFqdns | Where-Object { $_ -and $_ -like '*privatelink*' } | Sort-Object -Unique)
    $eastWestTargets = @()
    $eastWestTargets += Get-ConfigArray -Root $Config -Names @('eastWestTargets', 'eastWestProbeTargets', 'nodeTargets')
    $eastWestTargets += Get-ConfigArray -Root $Config.network -Names @('eastWestTargets', 'eastWestProbeTargets', 'nodeTargets')
    $peArray = ConvertTo-BashArrayLiteral -Values $peFqdns
    $eastWestArray = ConvertTo-BashArrayLiteral -Values $eastWestTargets
    $scriptHeader = @"
#!/bin/bash
set +e
REGION='$region'
K8S_VER='v1.30.0'
PE_FQDNS=$peArray
EASTWEST_TARGETS=$eastWestArray
"@
    $scriptBody = @'
HOSTS=(mcr.microsoft.com packages.aks.azure.com packages.microsoft.com management.azure.com login.microsoftonline.com "${REGION}.data.mcr.microsoft.com")
for h in "${HOSTS[@]}"; do
  ip=$(getent hosts "$h" | awk '{print $1}' | head -1)
  if [ -n "$ip" ]; then echo "DNS $h OK $ip"; else echo "DNS $h FAIL -"; fi
done
for h in "${HOSTS[@]}"; do
  if timeout 5 bash -c "cat < /dev/null > /dev/tcp/$h/443" 2>/dev/null; then echo "TCP443 $h OPEN"; else echo "TCP443 $h BLOCKED"; fi
done
declare -A URLS
URLS[mcr.microsoft.com]="https://mcr.microsoft.com/v2/"
URLS[packages.aks.azure.com]="https://packages.aks.azure.com/"
URLS[management.azure.com]="https://management.azure.com/"
URLS[login.microsoftonline.com]="https://login.microsoftonline.com/"
for h in mcr.microsoft.com packages.aks.azure.com management.azure.com login.microsoftonline.com; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "${URLS[$h]}")
  echo "HTTPS $h $code"
done
if curl -fsSL --max-time 20 -o /tmp/packages-microsoft-prod.deb https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb; then
  echo "ARTIFACT packages-microsoft-prod.deb OK $(stat -c%s /tmp/packages-microsoft-prod.deb)"
else
  echo "ARTIFACT packages-microsoft-prod.deb FAIL 0"
fi
KUBE_URL="https://packages.aks.azure.com/kubernetes/${K8S_VER}/binaries/kubernetes-node-linux-amd64.tar.gz"
if curl -fsSL --max-time 30 -r 0-1048575 -o /tmp/kubernetes-node-linux-amd64.tar.gz "$KUBE_URL"; then
  echo "ARTIFACT kubernetes-node-linux-amd64.tar.gz OK $(stat -c%s /tmp/kubernetes-node-linux-amd64.tar.gz)"
else
  echo "ARTIFACT kubernetes-node-linux-amd64.tar.gz FAIL 0"
fi
code=$(curl -s -o /tmp/ubuntu-jammy-Release -w "%{http_code}" --max-time 15 http://azure.archive.ubuntu.com/ubuntu/dists/jammy/Release)
if [ "$code" = "200" ]; then echo "ARTIFACT ubuntu-jammy-Release OK $(stat -c%s /tmp/ubuntu-jammy-Release)"; else echo "ARTIFACT ubuntu-jammy-Release FAIL 0"; fi
for f in "${PE_FQDNS[@]}"; do
  ip=$(getent hosts "$f" | awk '{print $1}' | head -1)
  case "$ip" in
    10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*|100.6[4-9].*|100.[7-9][0-9].*|100.1[0-1][0-9].*|100.12[0-7].*) echo "PE $f OK $ip" ;;
    "") echo "PE $f FAIL -" ;;
    *) echo "PE $f FAIL $ip" ;;
  esac
done
for t in "${EASTWEST_TARGETS[@]}"; do
  if timeout 5 bash -c "cat < /dev/null > /dev/tcp/$t/10250" 2>/dev/null; then echo "EASTWEST $t OPEN"; else echo "EASTWEST $t BLOCKED"; fi
done
'@
    $connTest = $scriptHeader + "`n" + $scriptBody
    try {
        if (-not $ResourceGroup -or -not $SubnetId) {
            throw "ResourceGroup and SubnetId are required or must be derivable from config."
        }
        $create = Get-AzJson -Args @('vm', 'create', '-g', $ResourceGroup, '-n', $VmName, '--location', $region, '--image', 'Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest', '--size', $size, '--subnet', $SubnetId, '--public-ip-address', '', '--nsg', '', '--admin-username', 'azureuser', '--generate-ssh-keys')
        $privateIp = if ($create -and $create.PSObject.Properties.Name -contains 'privateIpAddress') { $create.privateIpAddress } else { '' }
        $out.Add((New-CheckResult -Id 'testvm-create' -Name "create disposable VM $VmName" -Status 'Pass' -Fr 'FR3.7g' -Detail "size=$size privateIp=$privateIp" -Data $create))
        $vm = Get-AzJson -Args @('vm', 'show', '-g', $ResourceGroup, '-n', $VmName) -AllowFail
        if ($vm) {
            if ($vm.PSObject.Properties.Name -contains 'networkProfile' -and $vm.networkProfile) { $nicIds = @($vm.networkProfile.networkInterfaces | ForEach-Object { $_.id } | Where-Object { $_ }) }
            if ($vm.PSObject.Properties.Name -contains 'storageProfile' -and $vm.storageProfile.osDisk.managedDisk.id) { $diskIds = @($vm.storageProfile.osDisk.managedDisk.id) }
        }
        $run = Get-AzJson -Args @('vm', 'run-command', 'invoke', '-g', $ResourceGroup, '-n', $VmName, '--command-id', 'RunShellScript', '--scripts', $connTest)
        $message = if ($run -and $run.PSObject.Properties.Name -contains 'value') { (@($run.value | ForEach-Object { $_.message }) -join "`n") } else { '' }
        $message | Set-Content -LiteralPath $outFile -Encoding utf8
        $out.Add((New-CheckResult -Id 'testvm-run-command' -Name 'run conntest.sh' -Status 'Pass' -Fr 'FR3.7' -Detail "captured output to $outFile" -Data ([pscustomobject]@{ outputPath = $outFile })))
        foreach ($r in @(Invoke-ProbeDns -Config $Config -RemoteOutput $outFile)) { $out.Add($r) }
        foreach ($r in @(Invoke-ProbeTcp443 -Config $Config -RemoteOutput $outFile)) { $out.Add($r) }
        foreach ($r in @(Invoke-ProbeHttps -Config $Config -RemoteOutput $outFile)) { $out.Add($r) }
        foreach ($r in @(Invoke-ProbeArtifacts -Config $Config -RemoteOutput $outFile)) { $out.Add($r) }
        foreach ($r in @(Invoke-ProbePeResolution -Config $Config -RemoteOutput $outFile)) { $out.Add($r) }
        foreach ($r in @(Invoke-ProbeEastwest -Config $Config -RemoteOutput $outFile)) { $out.Add($r) }
    } catch {
        $out.Add((New-CheckResult -Id 'testvm-lifecycle' -Name "test VM lifecycle $VmName" -Status 'Fail' -Fr 'FR3.7g' `
                    -Detail $_.Exception.Message -Remediation 'VM create fails on SKU: pick a region-allowed SKU (see quota_sku).'))
    } finally {
        $cleanup = @()
        $vm = if ($ResourceGroup -and $VmName) { Get-AzJson -Args @('vm', 'show', '-g', $ResourceGroup, '-n', $VmName) -AllowFail } else { $null }
        if ($vm) {
            if (-not $nicIds.Count -and $vm.PSObject.Properties.Name -contains 'networkProfile' -and $vm.networkProfile) { $nicIds = @($vm.networkProfile.networkInterfaces | ForEach-Object { $_.id } | Where-Object { $_ }) }
            if (-not $diskIds.Count -and $vm.PSObject.Properties.Name -contains 'storageProfile' -and $vm.storageProfile.osDisk.managedDisk.id) { $diskIds = @($vm.storageProfile.osDisk.managedDisk.id) }
        }
        if ($ResourceGroup -and $VmName) {
            Invoke-Az -Args @('vm', 'delete', '-g', $ResourceGroup, '-n', $VmName, '--yes', '--no-wait') -AllowFail | Out-Null
            $cleanup += "vm=$VmName"
        }
        foreach ($nicId in @($nicIds)) {
            Invoke-Az -Args @('network', 'nic', 'delete', '--ids', $nicId) -AllowFail | Out-Null
            $cleanup += "nic=$nicId"
        }
        foreach ($diskId in @($diskIds)) {
            Invoke-Az -Args @('disk', 'delete', '--ids', $diskId, '--yes', '--no-wait') -AllowFail | Out-Null
            $cleanup += "disk=$diskId"
        }
        $out.Add((New-CheckResult -Id 'testvm-cleanup' -Name "delete disposable VM $VmName" -Status 'Pass' -Fr 'FR3.7g' `
                    -Detail "Cleanup requested for $($cleanup -join '; ')." `
                    -Data ([pscustomobject]@{ vmName = $VmName; resourceGroup = $ResourceGroup; nicIds = $nicIds; diskIds = $diskIds })))
    }
    return $out.ToArray()
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Assert-AzLogin -SubscriptionId $cfg.subscriptionId

$dependencyResults = Invoke-DependencySpec -Config $cfg -Profile $Profile
Add-Results -Items $dependencyResults
$dependency = @($dependencyResults | Where-Object { $_.id -eq 'dependency-spec' -and $_.Data } | Select-Object -First 1)
$checkNames = if ($dependency.Count) { @($dependency[0].Data.dependencySet.checks) } else { @('check_subnet_delegation', 'check_nsg_effective', 'check_effective_routes', 'check_dns_and_pe') }

$checkDispatch = @{
    'check_subnet_delegation' = { param($c, $p) Invoke-CheckSubnetDelegation -Config $c -Profile $p }
    'check_nsg_effective'     = { param($c, $p) Invoke-CheckNsgEffective -Config $c -Profile $p }
    'check_effective_routes'  = { param($c, $p) Invoke-CheckEffectiveRoutes -Config $c -Profile $p }
    'check_dns_and_pe'        = { param($c, $p) Invoke-CheckDnsAndPe -Config $c -Profile $p }
}

foreach ($check in $checkNames) {
    if (-not $checkDispatch.ContainsKey($check)) {
        Add-Results -Items @((New-CheckResult -Id "missing-$check" -Name "check script $check" -Status 'Fail' -Fr 'FR3.1' `
                    -Detail "No inlined check named: $check" -Remediation 'Update the dependency spec in the feature PR that changed the dependency.'))
        continue
    }
    $subResults = & $checkDispatch[$check] $cfg $Profile
    Add-Results -Items $subResults
}

if ($WithVm) {
    $vmResults = Invoke-TestVmLifecycle -Config $cfg -ConfigPath $ConfigPath -Profile $Profile
    Add-Results -Items $vmResults
} else {
    Add-Results -Items @((New-CheckResult -Id 'testvm-opt-in' -Name 'test VM connectivity harness' -Status 'Skip' -Fr 'FR3.7' `
                -Detail 'Use -WithVm to create the ephemeral probe VM and run connectivity probes.'))
}

if ($PassThru) { return $results.ToArray() }
$extra = [pscustomobject]@{ profile = $Profile; withVm = [bool]$WithVm; dependencySpec = if ($dependency.Count) { $dependency[0].Data.path } else { $null } }
$null = Write-OnboardingReport -Results $results.ToArray() -Title "Stage 3 · infra validation ($Profile)" -JsonPath $JsonPath -Extra $extra
Complete-Stage -Results $results.ToArray()
