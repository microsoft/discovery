#Requires -Version 7.0
<#
.SYNOPSIS  Stage 2 / FR2.1-FR2.9 — prepare the Discovery landing zone.
.DESCRIPTION
    Single self-contained Stage 2 script. Prepares the landing zone in dependency order and aggregates reports.

    Folds in the former sub-scripts:
      rp_register.ps1                  rbac_assign.ps1
      nsp_perimeter_joiner_role.ps1    network_provision.ps1
      byo_storage.ps1                  firewall_request_artifact.ps1
      quota_exemption_requests.ps1

    network_provision.ps1 now deploys network.bicep (VNet, subnets, shared NSG,
    UDR route tables, and private DNS zones/links — FR2.2-FR2.5) instead of the
    former imperative nsg_rules.ps1 / route_tables.ps1 / private_dns.ps1 az calls.

    Spec: ../../script-specs/stage2-landing-zone/stage2_prepare.md
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [string]$JsonPath,
    [switch]$PassThru
)
Import-Module (Join-Path $PSScriptRoot '..\lib\OnboardingCommon.psm1') -Force

function Invoke-RpRegister {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$ConfigPath,
        [switch]$PassThru,
        [string]$JsonPath,
        [int]$TimeoutSeconds = 900,
        [int]$PollSeconds = 15
    )
    $cfg = $Config
    $results = [System.Collections.Generic.List[object]]::new()


$providers = @(
    'Microsoft.Discovery',
    'Microsoft.Network',
    'Microsoft.Compute',
    'Microsoft.Storage',
    'Microsoft.ManagedIdentity',
    'Microsoft.Authorization',
    'Microsoft.CognitiveServices',
    'Microsoft.ContainerService',
    'Microsoft.ContainerRegistry',
    'Microsoft.DocumentDB',
    'Microsoft.KeyVault',
    'Microsoft.MachineLearningServices',
    'Microsoft.NetApp',
    'Microsoft.Search',
    'Microsoft.Web',
    'Microsoft.App',
    'Microsoft.Insights',
    'Microsoft.OperationalInsights',
    'Microsoft.Sql',
    'Microsoft.Bing'
)

try {
    Assert-AzLogin -SubscriptionId $cfg.subscriptionId
}
catch {
    $results.Add((New-CheckResult -Id 'rp-login' -Name 'Azure CLI login' -Status 'Fail' -Fr 'FR2.1' `
                -Detail $_.Exception.Message -Remediation "Run 'az login' and ensure access to subscription $($cfg.subscriptionId)."))
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 2 · resource provider registration (FR2.1)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

foreach ($namespace in $providers) {
    $id = "rp-$($namespace.ToLowerInvariant().Replace('.', '-'))"
    try {
        $before = Get-AzJson -Args @('provider', 'show', '--namespace', $namespace) -AllowFail
        if (-not $before -or $before.registrationState -ne 'Registered') {
            Invoke-Az -Args @('provider', 'register', '--namespace', $namespace) | Out-Null
        }

        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $state = $null
        do {
            $rp = Get-AzJson -Args @('provider', 'show', '--namespace', $namespace) -AllowFail
            $state = if ($rp) { [string]$rp.registrationState } else { 'Unknown' }
            if ($state -eq 'Registered') { break }
            Start-Sleep -Seconds $PollSeconds
        } while ((Get-Date) -lt $deadline)

        $status = ($state -eq 'Registered') ? 'Pass' : 'Fail'
        $results.Add((New-CheckResult -Id $id -Name "resource provider $namespace" -Status $status -Fr 'FR2.1' `
                    -Detail "registrationState=$state" `
                    -Remediation "Confirm the deploying identity has Microsoft.Resources/subscriptions/providers/register/action, then retry. If $namespace remains Registering beyond $TimeoutSeconds seconds, escalate to Azure support." `
                    -Data @{ namespace = $namespace; registrationState = $state }))
    }
    catch {
        $results.Add((New-CheckResult -Id $id -Name "resource provider $namespace" -Status 'Fail' -Fr 'FR2.1' `
                    -Detail $_.Exception.Message `
                    -Remediation "Register $namespace manually or rerun with Owner/Contributor plus provider register permission."))
    }
}

    return $results.ToArray()
}

function Invoke-RbacAssign {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$ConfigPath,
        [switch]$PassThru,
        [string]$JsonPath
    )
    $cfg = $Config
    $results = [System.Collections.Generic.List[object]]::new()


function Get-ConfigValue {
    param([object]$Object, [string[]]$Names)
    if (-not $Object) { return $null }
    foreach ($name in $Names) {
        if ($Object.PSObject.Properties.Name -contains $name -and $Object.$name) { return $Object.$name }
    }
    return $null
}

function Get-TargetResourceGroups {
    $set = [ordered]@{}
    $candidates = @(
        (Get-ConfigValue $cfg.network @('networkResourceGroup', 'resourceGroup', 'rg')),
        (Get-ConfigValue $cfg @('resourceGroup', 'resourceGroupName', 'discoveryResourceGroup')),
        (Get-ConfigValue $cfg.storage @('resourceGroup', 'resourceGroupName')),
        (Get-ConfigValue $cfg @('dnsResourceGroup'))
    )
    foreach ($rg in $candidates) {
        if ($rg -and -not $set.Contains($rg)) { $set[$rg] = $true }
    }
    return @($set.Keys)
}

$roles = [ordered]@{
    'Platform Administrator'       = '7a2b6e6c-472e-4b39-8878-a26eb63d75c6'
    'Platform Contributor'         = '01288891-85ee-45a7-b367-9db3b752fc65'
    'Platform Reader'              = '3bb7c424-af4e-436b-bfcc-8779c8934c31'
    'Bookshelf Index Data Reader'  = '8ec773c5-7ce6-4b78-91d1-182f8faa536d'
}

function Get-PrincipalsForRole {
    param([string]$RoleName)
    $items = @()
    if ($cfg.PSObject.Properties.Name -contains 'principals' -and $cfg.principals) {
        $matches = @($cfg.principals | Where-Object {
                $r = Get-ConfigValue $_ @('role', 'roleName', 'discoveryRole')
                $r -eq $RoleName -or $r -eq ($RoleName -replace ' ', '') -or $r -eq ($RoleName -replace ' ', '-')
            })
        foreach ($p in $matches) {
            $oid = Get-ConfigValue $p @('objectId', 'principalId', 'id')
            if ($oid) {
                $items += [pscustomobject]@{ ObjectId = $oid; Type = (Get-ConfigValue $p @('type', 'principalType')) }
            }
        }
    }
    if ($items.Count -eq 0 -and $cfg.deployingIdentity.objectId) {
        $items += [pscustomobject]@{ ObjectId = $cfg.deployingIdentity.objectId; Type = $cfg.deployingIdentity.type }
    }
    return $items
}

function Convert-PrincipalType {
    param([string]$Type)
    switch -Regex ($Type) {
        '^user$' { 'User'; break }
        'servicePrincipal' { 'ServicePrincipal'; break }
        'managedIdentity' { 'ServicePrincipal'; break }
        default { $null }
    }
}

$resourceGroups = Get-TargetResourceGroups
if ($resourceGroups.Count -eq 0) {
    $results.Add((New-CheckResult -Id 'rbac-target-rg' -Name 'target resource groups' -Status 'Fail' -Fr 'FR2.1' `
                -Detail 'No target resource group found in config.' `
                -Remediation 'Set config.network.networkResourceGroup and any Discovery/storage resource-group fields emitted by Stage 1.'))
}
else {
    try { Assert-AzLogin -SubscriptionId $cfg.subscriptionId }
    catch {
        $results.Add((New-CheckResult -Id 'rbac-login' -Name 'Azure CLI login' -Status 'Fail' -Fr 'FR2.1' `
                    -Detail $_.Exception.Message -Remediation "Run 'az login' and select subscription $($cfg.subscriptionId)."))
    }
}

foreach ($rg in $resourceGroups) {
    $scope = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$rg"
    foreach ($roleName in $roles.Keys) {
        foreach ($principal in @(Get-PrincipalsForRole -RoleName $roleName)) {
            $roleId = $roles[$roleName]
            $resultId = "rbac-$($rg)-$($roleName.ToLowerInvariant().Replace(' ', '-'))-$($principal.ObjectId)"
            try {
                $exists = Get-AzJson -Args @('role', 'assignment', 'list', '--assignee', $principal.ObjectId, '--role', $roleId, '--scope', $scope) -AllowFail
                if ($exists -and @($exists).Count -gt 0) {
                    $results.Add((New-CheckResult -Id $resultId -Name "$roleName on $rg" -Status 'Pass' -Fr 'FR2.1' `
                                -Detail "Already assigned to $($principal.ObjectId)." `
                                -Data @{ principal = $principal.ObjectId; role = $roleName; roleDefinitionId = $roleId; scope = $scope; state = 'exists' }))
                    continue
                }

                $args = @('role', 'assignment', 'create', '--assignee-object-id', $principal.ObjectId, '--role', $roleId, '--scope', $scope)
                $ptype = Convert-PrincipalType $principal.Type
                if ($ptype) { $args += @('--assignee-principal-type', $ptype) }
                Invoke-Az -Args $args | Out-Null
                $results.Add((New-CheckResult -Id $resultId -Name "$roleName on $rg" -Status 'Pass' -Fr 'FR2.1' `
                            -Detail "Assigned to $($principal.ObjectId)." `
                            -Data @{ principal = $principal.ObjectId; role = $roleName; roleDefinitionId = $roleId; scope = $scope; state = 'created' }))
            }
            catch {
                $results.Add((New-CheckResult -Id $resultId -Name "$roleName on $rg" -Status 'Fail' -Fr 'FR2.1' `
                            -Detail $_.Exception.Message `
                            -Remediation 'Run as Owner, User Access Administrator, or Role Based Access Control Administrator at the target resource group scope.'))
            }
        }
    }
}

    return $results.ToArray()
}

function Invoke-NspPerimeterJoinerRole {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$ConfigPath,
        [switch]$PassThru,
        [string]$JsonPath
    )
    $cfg = $Config
    $results = [System.Collections.Generic.List[object]]::new()

$roleName = 'Discovery NSP Perimeter Joiner'
$controlPlaneAppId = '92c174ac-8e41-4815-a1b7-d81b19ab03ce'
$scope = "/subscriptions/$($cfg.subscriptionId)"
$actions = @(
    'Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action',
    'Microsoft.Network/locations/networkSecurityPerimeterOperationStatuses/read'
)

try {
    Assert-AzLogin -SubscriptionId $cfg.subscriptionId
    $existing = Get-AzJson -Args @('role', 'definition', 'list', '--name', $roleName) -AllowFail
    $role = if ($existing -and @($existing).Count -gt 0) { @($existing)[0] } else { $null }
    $needsWrite = $true
    if ($role) {
        $currentActions = @($role.permissions[0].actions | Sort-Object)
        $wantedActions = @($actions | Sort-Object)
        $needsWrite = (Compare-Object -ReferenceObject $currentActions -DifferenceObject $wantedActions) -or `
            @($role.permissions[0].notActions).Count -gt 0 -or @($role.permissions[0].dataActions).Count -gt 0 -or @($role.permissions[0].notDataActions).Count -gt 0
    }

    if ($needsWrite) {
        $body = [ordered]@{
            Name             = if ($role) { $role.name } else { $null }
            roleName         = $roleName
            description      = 'Allows the Microsoft Discovery control plane to join resources to network security perimeters.'
            type             = 'CustomRole'
            assignableScopes = @($scope)
            permissions      = @([ordered]@{
                    actions        = $actions
                    notActions     = @()
                    dataActions    = @()
                    notDataActions = @()
                })
        }
        if (-not $role) { $body.Remove('Name') }
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) "discovery-nsp-joiner-$([guid]::NewGuid()).json"
        try {
            ([pscustomobject]$body | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $tmp -Encoding utf8
            if ($role) {
                Invoke-Az -Args @('role', 'definition', 'update', '--role-definition', $tmp) | Out-Null
            }
            else {
                Invoke-Az -Args @('role', 'definition', 'create', '--role-definition', $tmp) | Out-Null
            }
        }
        finally {
            if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
        }
    }

    $roleAfter = @(Get-AzJson -Args @('role', 'definition', 'list', '--name', $roleName) -AllowFail)[0]
    $sp = Get-AzJson -Args @('ad', 'sp', 'show', '--id', $controlPlaneAppId) -AllowFail
    if (-not $sp -or -not $sp.id) { throw "Control-plane service principal not found for appId $controlPlaneAppId." }

    $assignment = Get-AzJson -Args @('role', 'assignment', 'list', '--assignee', $sp.id, '--role', $roleAfter.name, '--scope', $scope) -AllowFail
    if (-not $assignment -or @($assignment).Count -eq 0) {
        Invoke-Az -Args @('role', 'assignment', 'create', '--assignee-object-id', $sp.id, '--assignee-principal-type', 'ServicePrincipal', '--role', $roleAfter.name, '--scope', $scope) | Out-Null
        $assignedState = 'created'
    }
    else {
        $assignedState = 'exists'
    }

    $results.Add((New-CheckResult -Id 'nsp-perimeter-joiner-role' -Name 'NSP Perimeter Joiner custom role and assignment' -Status 'Pass' -Fr 'FR2.1a' `
                -Detail "role=$roleName state=$(($needsWrite) ? 'created-or-updated' : 'exists'); assignment=$assignedState" `
                -Data @{ roleName = $roleName; roleDefinitionId = $roleAfter.name; appId = $controlPlaneAppId; principalObjectId = $sp.id; scope = $scope; actions = $actions; assigned = $assignedState }))
}
catch {
    $results.Add((New-CheckResult -Id 'nsp-perimeter-joiner-role' -Name 'NSP Perimeter Joiner custom role and assignment' -Status 'Fail' -Fr 'FR2.1a' `
                -Detail $_.Exception.Message `
                -Remediation 'Create the custom role at subscription scope and assign it to the Discovery control-plane service principal before deploying workspaces, supercomputers, or Bookshelf.'))
}

    return $results.ToArray()
}

function New-Stage2NetworkParamFile {
    param([object]$Config, [string]$VnetName, [string]$Location)
    $net = $Config.network
    $subnets = @()
    foreach ($sn in $net.subnets) {
        $name = if (($sn.PSObject.Properties.Name -contains 'name') -and $sn.name) { [string]$sn.name } else { "snet-$($sn.role)" }
        $deleg = if (($sn.PSObject.Properties.Name -contains 'delegation') -and $sn.delegation) { [string]$sn.delegation } else { 'none' }
        $subnets += [ordered]@{ role = [string]$sn.role; name = $name; cidr = [string]$sn.cidr; delegation = $deleg }
    }
    $corpDns = @()
    if (($net.PSObject.Properties.Name -contains 'corpDns') -and $net.corpDns) {
        $corpDns = @($net.corpDns | ForEach-Object { $s = [string]$_; ($s -match '/') ? $s : "$s/32" })
    }
    $outboundType = if (($net.PSObject.Properties.Name -contains 'outboundType') -and $net.outboundType) { [string]$net.outboundType } else { 'UserDefinedRouting' }
    $nvaNextHop = if (($net.PSObject.Properties.Name -contains 'nvaNextHop') -and $net.nvaNextHop) { [string]$net.nvaNextHop } else { '' }

    $p = [ordered]@{
        location     = $Location
        vnetName     = $VnetName
        vnetCidr     = [string]$net.vnetCidr
        subnets      = $subnets
        outboundType = $outboundType
        nvaNextHop   = $nvaNextHop
        corpDns      = $corpDns
    }
    $paramObject = [ordered]@{}
    foreach ($k in $p.Keys) { $paramObject[$k] = @{ value = $p[$k] } }
    $doc = [ordered]@{
        '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters     = $paramObject
    }
    $file = New-TemporaryFile
    $doc | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $file.FullName -Encoding utf8
    return $file.FullName
}

function Invoke-NetworkProvision {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$ConfigPath,
        [switch]$PassThru,
        [string]$JsonPath
    )
    $cfg = $Config
    $results = [System.Collections.Generic.List[object]]::new()


function Get-ConfigValue {
    param([object]$Object, [string[]]$Names)
    if (-not $Object) { return $null }
    foreach ($name in $Names) {
        if ($Object.PSObject.Properties.Name -contains $name -and $Object.$name) { return $Object.$name }
    }
    return $null
}

function Get-VNetName {
    $name = Get-ConfigValue $cfg.network @('vnetName', 'virtualNetworkName')
    if (-not $name) { $name = Get-ConfigValue $cfg.names @('vnet', 'virtualNetwork') }
    if (-not $name) { $name = "vnet-$($cfg.names.workspace)" }
    return $name
}

function Get-SubnetName {
    param([object]$Subnet)
    $name = Get-ConfigValue $Subnet @('name', 'subnetName')
    if (-not $name) { $name = "snet-$($Subnet.role)" }
    return $name
}

function New-ChildName {
    param([string]$Prefix, [object]$Subnet)
    $name = Get-ConfigValue $Subnet @("${Prefix}Name")
    if (-not $name) { $name = "$Prefix-$($Subnet.role)" }
    return $name
}

$rg = Get-ConfigValue $cfg.network @('networkResourceGroup', 'resourceGroup', 'rg')
$vnetName = Get-VNetName
$location = $cfg.workloadRegion

if (-not $rg) {
    $results.Add((New-CheckResult -Id 'network-rg' -Name 'network resource group' -Status 'Fail' -Fr 'FR2.2' `
                -Detail 'config.network.networkResourceGroup is missing.' -Remediation 'Set config.network.networkResourceGroup to the BYO network resource group.'))
    return $results.ToArray()
}

# network.model intents: byo / byo-spoke / greenfield => the tool lays out the VNet, subnets,
# NSG, routes and private DNS declaratively (network.bicep). byo-existing => validate only
# (Stage 3). managed => the Discovery RP creates the network, tool is a no-op here.
$model = [string]$cfg.network.model
$buildModels = @('byo', 'byo-spoke', 'greenfield')
if ($model -notin $buildModels) {
    $results.Add((New-CheckResult -Id 'network-model' -Name 'network model' -Status 'Skip' -Fr 'FR2.2' `
                -Detail "network.model=$model; the tool does not provision the VNet (byo-existing = validate in Stage 3, managed = RP-managed)."))
    return $results.ToArray()
}

$outboundType = [string]$cfg.network.outboundType
if (-not $outboundType) { $outboundType = 'UserDefinedRouting' }
if ($outboundType -eq 'UserDefinedRouting' -and -not $cfg.network.nvaNextHop) {
    $results.Add((New-CheckResult -Id 'network-nva-next-hop' -Name 'NVA next hop' -Status 'Fail' -Fr 'FR2.4' `
                -Detail 'network.outboundType=UserDefinedRouting requires config.network.nvaNextHop.' `
                -Remediation 'Set config.network.nvaNextHop to the firewall/NVA private IP, or set network.outboundType=LoadBalancer.'))
    return $results.ToArray()
}

try {
    Assert-AzLogin -SubscriptionId $cfg.subscriptionId
    Invoke-Az -Args @('group', 'create', '--name', $rg, '--location', $location) | Out-Null

    $bicepFile = Join-Path $PSScriptRoot 'network.bicep'
    if (-not (Test-Path -LiteralPath $bicepFile)) {
        $results.Add((New-CheckResult -Id 'network-provision' -Name 'network Bicep template' -Status 'Fail' -Fr 'FR2.2' `
                    -Detail "network.bicep not found next to stage2_prepare.ps1 ($bicepFile)." -Remediation 'Restore scripts/stage2-landing-zone/network.bicep.'))
        return $results.ToArray()
    }

    $paramFile = New-Stage2NetworkParamFile -Config $cfg -VnetName $vnetName -Location $location
    $deployName = "stage2-net-$(Get-Date -Format yyyyMMddHHmmss)"
    try {
        $deploy = Get-AzJson -Args @('deployment', 'group', 'create', '-g', $rg, '--name', $deployName, '--template-file', $bicepFile, '--parameters', "@$paramFile")
    }
    finally {
        Remove-Item -LiteralPath $paramFile -Force -ErrorAction SilentlyContinue
    }

    $outputs = $deploy.properties.outputs
    $vnetId = $outputs.vnetId.value
    $results.Add((New-CheckResult -Id 'network-vnet' -Name "VNet $vnetName" -Status 'Pass' -Fr 'FR2.2' `
                -Detail "deployed via network.bicep; cidr=$($cfg.network.vnetCidr) outboundType=$outboundType" `
                -Data @{ id = $vnetId; resourceGroup = $rg; name = $vnetName; cidr = $cfg.network.vnetCidr; deployment = $deployName }))

    foreach ($so in @($outputs.subnetIds.value)) {
        $results.Add((New-CheckResult -Id "network-subnet-$($so.role)" -Name "subnet $($so.role)" -Status 'Pass' -Fr 'FR2.2' `
                    -Detail "subnet=$($so.name) role=$($so.role) (declarative)" `
                    -Data @{ subnetId = $so.id; subnetName = $so.name; role = $so.role }))
    }

    $results.Add((New-CheckResult -Id 'network-nsg' -Name 'NSG allow-list rules' -Status 'Pass' -Fr 'FR2.3' `
                -Detail 'Shared NSG allow-list (VNet/AzureLB/PodCIDR in; DNS/AzureCloud/KMS/Internet/PodCIDR out) applied via network.bicep.' `
                -Data @{ nsgId = $outputs.nsgId.value }))

    if ($outboundType -eq 'UserDefinedRouting') {
        $results.Add((New-CheckResult -Id 'network-routes' -Name 'UDR route tables' -Status 'Pass' -Fr 'FR2.4' `
                    -Detail "0.0.0.0/0 and 10.0.0.0/8 -> NVA $($cfg.network.nvaNextHop); managedcluster CIDR kept VnetLocal (network.bicep)."))
    }
    else {
        $results.Add((New-CheckResult -Id 'network-routes' -Name 'route tables' -Status 'Skip' -Fr 'FR2.4' `
                    -Detail 'outboundType=LoadBalancer; no user route tables (Azure system routes + NSG allow-list govern egress).'))
    }

    $results.Add((New-CheckResult -Id 'network-private-dns' -Name 'private DNS zones' -Status 'Pass' -Fr 'FR2.5' `
                -Detail 'privatelink.* zones created and linked to the VNet via network.bicep.'))
}
catch {
    $results.Add((New-CheckResult -Id 'network-provision' -Name 'network provisioning' -Status 'Fail' -Fr 'FR2.2' `
                -Detail $_.Exception.Message -Remediation 'Run with Network Contributor on the network resource group and retry; check network.bicep parameter values.'))
}

    return $results.ToArray()
}

function Invoke-ByoStorage {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$ConfigPath,
        [switch]$PassThru,
        [string]$JsonPath
    )
    $cfg = $Config
    $results = [System.Collections.Generic.List[object]]::new()


function Get-ConfigValue {
    param([object]$Object, [string[]]$Names)
    if (-not $Object) { return $null }
    foreach ($name in $Names) {
        if ($Object.PSObject.Properties.Name -contains $name -and $Object.$name) { return $Object.$name }
    }
    return $null
}
function Get-VNetName {
    $name = Get-ConfigValue $cfg.network @('vnetName', 'virtualNetworkName')
    if (-not $name) { $name = Get-ConfigValue $cfg.names @('vnet', 'virtualNetwork') }
    if (-not $name) { $name = "vnet-$($cfg.names.workspace)" }
    return $name
}
function Get-SubnetName {
    param([object]$Subnet)
    $name = Get-ConfigValue $Subnet @('name', 'subnetName')
    if (-not $name) { $name = "snet-$($Subnet.role)" }
    return $name
}
function Get-StorageAccountName {
    $name = Get-ConfigValue $cfg.storage @('account', 'accountName', 'name')
    if (-not $name) { $name = Get-ConfigValue $cfg.names @('storageAccount') }
    return $name
}

if (-not $cfg.storage -or $cfg.storage.model -ne 'byo') {
    $results.Add((New-CheckResult -Id 'byo-storage-model' -Name 'BYO storage model' -Status 'Skip' -Fr 'FR2.6' `
                -Detail "storage.model=$(if ($cfg.storage) { $cfg.storage.model } else { 'absent' }); no BYO storage requested."))
}
else {
    $networkRg = Get-ConfigValue $cfg.network @('networkResourceGroup', 'resourceGroup', 'rg')
    $storageRg = Get-ConfigValue $cfg.storage @('resourceGroup', 'resourceGroupName')
    if (-not $storageRg) { $storageRg = $networkRg }
    $account = Get-StorageAccountName
    $access = Get-ConfigValue $cfg.storage @('access')
    if (-not $access) { $access = 'privateEndpoint' }
    $containers = @()
    if ($cfg.storage.PSObject.Properties.Name -contains 'containers' -and $cfg.storage.containers) { $containers = @($cfg.storage.containers) }
    elseif ($cfg.names.PSObject.Properties.Name -contains 'storageContainer' -and $cfg.names.storageContainer) { $containers = @($cfg.names.storageContainer) }

    if (-not $account) {
        $results.Add((New-CheckResult -Id 'byo-storage-account-name' -Name 'BYO storage account name' -Status 'Fail' -Fr 'FR2.6' `
                    -Detail 'config.storage.account is missing.' -Remediation 'Set config.storage.account to the customer-owned storage account name.'))
    }
    else {
        try {
            Assert-AzLogin -SubscriptionId $cfg.subscriptionId
            Invoke-Az -Args @('group', 'create', '--name', $storageRg, '--location', $cfg.workloadRegion) | Out-Null
            $st = Get-AzJson -Args @('storage', 'account', 'show', '-g', $storageRg, '-n', $account) -AllowFail
            if (-not $st) {
                Invoke-Az -Args @('storage', 'account', 'create', '-g', $storageRg, '-n', $account, '-l', $cfg.workloadRegion, '--sku', 'Standard_LRS', '--kind', 'StorageV2', '--https-only', 'true', '--min-tls-version', 'TLS1_2', '--allow-blob-public-access', 'false') | Out-Null
                $state = 'created'
            }
            else { $state = 'exists' }

            $defaultAction = ($access -eq 'serviceEndpoint') ? 'Deny' : 'Deny'
            Invoke-Az -Args @('storage', 'account', 'update', '-g', $storageRg, '-n', $account, '--allow-blob-public-access', 'false', '--default-action', $defaultAction) | Out-Null

            $containerStates = @()
            foreach ($container in $containers) {
                Invoke-Az -Args @('storage', 'container', 'create', '--account-name', $account, '--name', [string]$container, '--auth-mode', 'login') -AllowFail | Out-Null
                $containerStates += @{ name = [string]$container; state = 'ensured' }
            }

            $accessData = @{ model = $access }
            if ($access -eq 'serviceEndpoint') {
                $vnet = Get-VNetName
                foreach ($sn in $cfg.network.subnets) {
                    $subnetName = Get-SubnetName $sn
                    Invoke-Az -Args @('network', 'vnet', 'subnet', 'update', '-g', $networkRg, '--vnet-name', $vnet, '-n', $subnetName, '--service-endpoints', 'Microsoft.Storage') | Out-Null
                    Invoke-Az -Args @('storage', 'account', 'network-rule', 'add', '-g', $storageRg, '--account-name', $account, '--vnet-name', $vnet, '--subnet', $subnetName) -AllowFail | Out-Null
                }
                $accessData.vnet = $vnet
            }
            elseif ($access -eq 'privateEndpoint') {
                $peSubnet = @($cfg.network.subnets | Where-Object { $_.role -eq 'private-endpoints' } | Select-Object -First 1)
                if ($peSubnet) {
                    $vnet = Get-VNetName
                    $subnetName = Get-SubnetName $peSubnet
                    $subnetId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$networkRg/providers/Microsoft.Network/virtualNetworks/$vnet/subnets/$subnetName"
                    $accountId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$storageRg/providers/Microsoft.Storage/storageAccounts/$account"
                    $peName = "pe-$account-blob"
                    $pe = Get-AzJson -Args @('network', 'private-endpoint', 'show', '-g', $storageRg, '-n', $peName) -AllowFail
                    if (-not $pe) {
                        Invoke-Az -Args @('network', 'private-endpoint', 'create', '-g', $storageRg, '-n', $peName, '--location', $cfg.workloadRegion, '--subnet', $subnetId, '--private-connection-resource-id', $accountId, '--group-id', 'blob', '--connection-name', "$peName-conn") | Out-Null
                        $peState = 'created'
                    }
                    else { $peState = 'exists' }
                    $accessData.privateEndpoint = @{ name = $peName; state = $peState; subnetId = $subnetId }
                }
                else {
                    $results.Add((New-CheckResult -Id 'byo-storage-pe-subnet' -Name 'BYO storage private endpoint subnet' -Status 'Warn' -Fr 'FR2.6' `
                                -Detail 'No subnet role=private-endpoints was found; storage account was ensured but no private endpoint was created.' `
                                -Remediation 'Add a private-endpoints subnet and rerun.'))
                }
            }

            $st = Get-AzJson -Args @('storage', 'account', 'show', '-g', $storageRg, '-n', $account)
            $results.Add((New-CheckResult -Id 'byo-storage-account' -Name "BYO storage account $account" -Status 'Pass' -Fr 'FR2.6' `
                        -Detail "storage=$state access=$access containers=$($containers -join ',')" `
                        -Data @{ id = $st.id; resourceGroup = $storageRg; account = $account; state = $state; containers = $containerStates; access = $accessData }))
        }
        catch {
            $results.Add((New-CheckResult -Id 'byo-storage-account' -Name "BYO storage account $account" -Status 'Fail' -Fr 'FR2.6' `
                        -Detail $_.Exception.Message `
                        -Remediation 'Grant Storage Account Contributor and Network Contributor as needed. If public-access policy denies managed Bookshelf storage, use the FR2.8 exemption artifact.'))
        }
    }
}

    return $results.ToArray()
}

function Invoke-FirewallRequestArtifact {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$ConfigPath,
        [switch]$PassThru,
        [string]$JsonPath,
        [string]$OutFile
    )
    $cfg = $Config
    $results = [System.Collections.Generic.List[object]]::new()

$outDir = Join-Path $PSScriptRoot 'out'
if (-not $OutFile) { $OutFile = Join-Path $outDir "firewall-request-$($cfg.names.workspace).md" }
$jsonArtifact = [System.IO.Path]::ChangeExtension($OutFile, '.json')

$spokeCidr = if ($cfg.network.PSObject.Properties.Name -contains 'spokeCidr' -and $cfg.network.spokeCidr) { $cfg.network.spokeCidr } else { $cfg.network.vnetCidr }
$corpDns = @()
if ($cfg.network.PSObject.Properties.Name -contains 'corpDns' -and $cfg.network.corpDns) { $corpDns = @($cfg.network.corpDns) }
$subnetCidrs = @($cfg.network.subnets | ForEach-Object { $_.cidr })

$artifact = [ordered]@{
    title          = 'Microsoft Discovery firewall request'
    generatedUtc   = (Get-Date).ToUniversalTime().ToString('o')
    workspace      = $cfg.names.workspace
    workloadRegion = $cfg.workloadRegion
    sourceCidr     = $spokeCidr
    networkRules   = @(
        [ordered]@{ name = 'DNS'; source = $spokeCidr; destinations = $corpDns; protocol = 'TCP/UDP'; ports = @(53); purpose = 'Corporate DNS resolution' },
        [ordered]@{ name = 'Azure PaaS HTTPS'; source = $spokeCidr; destinations = @('Azure service tags and PaaS FQDNs below'); protocol = 'TCP'; ports = @(443); purpose = 'Discovery managed PaaS dependencies' },
        [ordered]@{ name = 'NTP'; source = $spokeCidr; destinations = @('time.windows.com', 'ntp.ubuntu.com', 'customer-approved NTP'); protocol = 'UDP'; ports = @(123); purpose = 'Node time synchronization' }
    )
    aksBootstrapFqdns = @(
        [ordered]@{ fqdn = 'packages.microsoft.com'; ports = @(80, 443) },
        [ordered]@{ fqdn = 'mcr.microsoft.com'; ports = @(80, 443) },
        [ordered]@{ fqdn = '*.data.mcr.microsoft.com'; ports = @(443) },
        [ordered]@{ fqdn = 'acs-mirror.azureedge.net'; ports = @(443) },
        [ordered]@{ fqdn = 'management.azure.com'; ports = @(443) },
        [ordered]@{ fqdn = 'login.microsoftonline.com'; ports = @(443) }
    )
    discoveryFoundryPaaSFqdns = @(
        '*.cognitiveservices.azure.com',
        '*.openai.azure.com',
        '*.services.ai.azure.com',
        '*.search.windows.net',
        '*.vault.azure.net',
        '*.blob.core.windows.net',
        '*.queue.core.windows.net',
        '*.table.core.windows.net',
        '*.file.core.windows.net',
        '*.dfs.core.windows.net',
        '*.documents.azure.com',
        '*.azurecr.io',
        '*.azurecontainerapps.io',
        '*.monitor.azure.com',
        '*.windows.net'
    )
    eastWest = [ordered]@{
        sourceCidrs       = $subnetCidrs
        destinationCidrs  = $subnetCidrs
        preferred         = 'Allow any/any between Discovery subnets inside the spoke.'
        specificFallback  = @(
            [ordered]@{ protocol = 'TCP'; ports = @(10250); purpose = 'AKS kubelet' },
            [ordered]@{ protocol = 'TCP'; ports = @(443); purpose = 'AKS/API/PaaS private endpoint HTTPS' },
            [ordered]@{ protocol = 'TCP/UDP'; ports = @(53); purpose = 'DNS' },
            [ordered]@{ protocol = 'TCP'; ports = @(80); purpose = 'HTTP bootstrap/probes' },
            [ordered]@{ protocol = 'TCP'; ports = @(4443); purpose = 'Optional admission/webhook fallback' },
            [ordered]@{ protocol = 'TCP'; ports = @('30000-32767'); purpose = 'Optional Kubernetes NodePort range if used' }
        )
        reference = 'firewall-request-discovery-eastwest.md'
    }
}

try {
    $dir = Split-Path -Parent $OutFile
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($artifact | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $jsonArtifact -Encoding utf8

    $md = @"
# Microsoft Discovery firewall request

Generated: $($artifact.generatedUtc)

Source spoke CIDR: `$spokeCidr`
Workload region: `$($cfg.workloadRegion)`

## Network rules

| Name | Source | Destination | Protocol | Ports | Purpose |
| --- | --- | --- | --- | --- | --- |
| DNS | $spokeCidr | $($corpDns -join ', ') | TCP/UDP | 53 | Corporate DNS resolution |
| Azure PaaS HTTPS | $spokeCidr | Azure service tags and FQDNs below | TCP | 443 | Discovery managed PaaS dependencies |
| NTP | $spokeCidr | customer-approved NTP | UDP | 123 | Node time synchronization |

## AKS bootstrap FQDNs

| FQDN | Ports |
| --- | --- |
$(@($artifact.aksBootstrapFqdns | ForEach-Object { "| $($_.fqdn) | $($_.ports -join ', ') |" }) -join "`n")

## Discovery and Foundry PaaS FQDNs

$(@($artifact.discoveryFoundryPaaSFqdns | ForEach-Object { "- $_" }) -join "`n")

## East-west Discovery subnet allow

Preferred: allow any/any between these Discovery subnet CIDRs:

$(@($subnetCidrs | ForEach-Object { "- $_" }) -join "`n")

If any/any east-west is not permitted, allow the specific fallback ports between all Discovery subnets:

| Protocol | Ports | Purpose |
| --- | --- | --- |
$(@($artifact.eastWest.specificFallback | ForEach-Object { "| $($_.protocol) | $($_.ports -join ', ') | $($_.purpose) |" }) -join "`n")

Reference: firewall-request-discovery-eastwest.md
"@
    $md | Set-Content -LiteralPath $OutFile -Encoding utf8
    $results.Add((New-CheckResult -Id 'firewall-request-artifact' -Name 'firewall request artifact' -Status 'Pass' -Fr 'FR2.7' `
                -Detail "Wrote $OutFile and $jsonArtifact using source CIDR $spokeCidr." `
                -Data @{ markdownPath = $OutFile; jsonPath = $jsonArtifact; sourceCidr = $spokeCidr }))
}
catch {
    $results.Add((New-CheckResult -Id 'firewall-request-artifact' -Name 'firewall request artifact' -Status 'Fail' -Fr 'FR2.7' `
                -Detail $_.Exception.Message -Remediation 'Ensure the output path is writable and rerun.'))
}

    return $results.ToArray()
}

function Invoke-QuotaExemptionRequests {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$ConfigPath,
        [switch]$PassThru,
        [string]$JsonPath,
        [string]$OutDir
    )
    $cfg = $Config
    $results = [System.Collections.Generic.List[object]]::new()

if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'out' }

function Get-ConfigValue {
    param([object]$Object, [string[]]$Names)
    if (-not $Object) { return $null }
    foreach ($name in $Names) {
        if ($Object.PSObject.Properties.Name -contains $name -and $Object.$name) { return $Object.$name }
    }
    return $null
}

function Get-QuotaGaps {
    $gaps = @()
    foreach ($prop in @('quotaGaps', 'quotaShortfalls')) {
        if ($cfg.PSObject.Properties.Name -contains $prop -and $cfg.$prop) { $gaps += @($cfg.$prop) }
    }
    if ($cfg.PSObject.Properties.Name -contains 'quota' -and $cfg.quota) {
        foreach ($prop in @('gaps', 'shortfalls')) {
            if ($cfg.quota.PSObject.Properties.Name -contains $prop -and $cfg.quota.$prop) { $gaps += @($cfg.quota.$prop) }
        }
    }
    if ($gaps.Count -gt 0) { return $gaps }

    $tier = $cfg.sizingTier
    $tierSpec = $null
    if ($cfg.PSObject.Properties.Name -contains 'sizingMap' -and $cfg.sizingMap -and $cfg.sizingMap.PSObject.Properties.Name -contains $tier) {
        $tierSpec = $cfg.sizingMap.$tier
    }
    $derived = @(
        [ordered]@{ service = 'Microsoft.CognitiveServices/OpenAI'; region = $cfg.workloadRegion; requested = 'Discovery model TPM per FR1.5 sizing'; reason = "No explicit FR1.5 shortfall found; review sizing tier $tier before deployment." },
        [ordered]@{ service = 'Microsoft.Compute/cores'; region = $cfg.workloadRegion; requested = if ($tierSpec -and $tierSpec.vcpuByFamily) { $tierSpec.vcpuByFamily } else { 'AKS VM-family vCPU headroom for Bookshelf/supercomputer' }; reason = "Review compute quota for sizing tier $tier." },
        [ordered]@{ service = 'Microsoft.Search/services'; region = $cfg.workloadRegion; requested = 'At least one S1/standard search service'; reason = "Discovery provisions AI Search in the workload region." }
    )
    return $derived
}

try {
    if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

    $quotaRequests = [ordered]@{
        title        = 'Discovery quota increase requests'
        generatedUtc = (Get-Date).ToUniversalTime().ToString('o')
        subscription = $cfg.subscriptionId
        sizingTier   = $cfg.sizingTier
        workloadRegion = $cfg.workloadRegion
        requests     = @(Get-QuotaGaps)
    }
    $quotaJson = Join-Path $OutDir "quota-increase-requests-$($cfg.names.workspace).json"
    $quotaMd = Join-Path $OutDir "quota-increase-requests-$($cfg.names.workspace).md"
    ($quotaRequests | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $quotaJson -Encoding utf8
    @"
# Discovery quota increase requests

Subscription: `$($cfg.subscriptionId)`
Region: `$($cfg.workloadRegion)`
Sizing tier: `$($cfg.sizingTier)`

Submit quota increases for the following FR1.5 gaps or sizing-driven headroom checks:

| Service | Region | Requested | Reason |
| --- | --- | --- | --- |
$(@($quotaRequests.requests | ForEach-Object { "| $(Get-ConfigValue $_ @('service', 'resource', 'name')) | $(Get-ConfigValue $_ @('region', 'location')) | $(Get-ConfigValue $_ @('requested', 'target', 'required')) | $(Get-ConfigValue $_ @('reason', 'detail')) |" }) -join "`n")
"@ | Set-Content -LiteralPath $quotaMd -Encoding utf8
    $results.Add((New-CheckResult -Id 'quota-request-artifact' -Name 'quota increase request artifact' -Status 'Pass' -Fr 'FR2.8' `
                -Detail "Wrote $quotaJson and $quotaMd." -Data @{ jsonPath = $quotaJson; markdownPath = $quotaMd; requestCount = @($quotaRequests.requests).Count }))

    $exemptions = @(
        [ordered]@{
            name = 'workspace-mrg-foundry-cognitive-services-public-access'
            policy = 'Cognitive Services accounts should disable public network access'
            scope = 'Workspace managed resource group Foundry account'
            justification = 'Temporary Discovery RP requirement; NSP enforced; remove when RP fix ships.'
            requestedDuration = 'Time-bound, non-prod first'
        },
        [ordered]@{
            name = 'workspace-mrg-log-analytics-public-access'
            policy = 'Log Analytics workspaces should disable public network access'
            scope = 'Workspace managed resource group Log Analytics workspace'
            justification = 'Managed logging dependency currently has no config-only fix in Discovery deployment.'
            requestedDuration = 'Time-bound, non-prod first'
        },
        [ordered]@{
            name = 'bookshelf-mrg-storage-public-access'
            policy = 'Storage accounts should disable public network access'
            scope = 'Bookshelf managed resource group storage account'
            justification = 'Temporary Bookshelf managed storage public-access policy conflict; NSP enforced.'
            requestedDuration = 'Time-bound, non-prod first'
        }
    )
    $policyRequests = [ordered]@{
        title = 'Discovery policy exemption requests'
        generatedUtc = (Get-Date).ToUniversalTime().ToString('o')
        subscription = $cfg.subscriptionId
        requests = $exemptions
        notes = @(
            'Do not request an NSP association exemption; resolve with ordering/retry plus the FR2.1a Perimeter Joiner custom role.',
            'Do not request a Container Apps allowInsecure exemption; the RP sets allowInsecure:false.'
        )
    }
    $policyJson = Join-Path $OutDir "policy-exemption-requests-$($cfg.names.workspace).json"
    $policyMd = Join-Path $OutDir "policy-exemption-requests-$($cfg.names.workspace).md"
    ($policyRequests | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $policyJson -Encoding utf8
    @"
# Discovery policy exemption requests

| Name | Policy | Scope | Justification | Duration |
| --- | --- | --- | --- | --- |
$(@($exemptions | ForEach-Object { "| $($_.name) | $($_.policy) | $($_.scope) | $($_.justification) | $($_.requestedDuration) |" }) -join "`n")

Not requested:

- NSP association: fix with ordering/retry plus the FR2.1a Perimeter Joiner custom role, not an exemption.
- Container Apps allowInsecure: fixed in the RP with `allowInsecure:false`, no exemption needed.
"@ | Set-Content -LiteralPath $policyMd -Encoding utf8
    $results.Add((New-CheckResult -Id 'policy-exemption-artifact' -Name 'policy exemption request artifact' -Status 'Pass' -Fr 'FR2.8' `
                -Detail "Wrote $policyJson and $policyMd." -Data @{ jsonPath = $policyJson; markdownPath = $policyMd; requestCount = @($exemptions).Count }))
}
catch {
    $results.Add((New-CheckResult -Id 'quota-exemption-artifacts' -Name 'quota and exemption artifacts' -Status 'Fail' -Fr 'FR2.8' `
                -Detail $_.Exception.Message -Remediation 'Ensure the output directory is writable and rerun.'))
}

    return $results.ToArray()
}

$cfg = Get-OnboardingConfig -Path $ConfigPath
$results = [System.Collections.Generic.List[object]]::new()
$steps = @(
    [pscustomobject]@{ ScriptName = 'rp_register.ps1'; FunctionName = 'Invoke-RpRegister' },
    [pscustomobject]@{ ScriptName = 'rbac_assign.ps1'; FunctionName = 'Invoke-RbacAssign' },
    [pscustomobject]@{ ScriptName = 'nsp_perimeter_joiner_role.ps1'; FunctionName = 'Invoke-NspPerimeterJoinerRole' },
    [pscustomobject]@{ ScriptName = 'network_provision.ps1'; FunctionName = 'Invoke-NetworkProvision' },
    [pscustomobject]@{ ScriptName = 'byo_storage.ps1'; FunctionName = 'Invoke-ByoStorage' },
    [pscustomobject]@{ ScriptName = 'firewall_request_artifact.ps1'; FunctionName = 'Invoke-FirewallRequestArtifact' },
    [pscustomobject]@{ ScriptName = 'quota_exemption_requests.ps1'; FunctionName = 'Invoke-QuotaExemptionRequests' }
)

try {
    Assert-AzLogin -SubscriptionId $cfg.subscriptionId
}
catch {
    $results.Add((New-CheckResult -Id 'stage2-login' -Name 'Azure CLI login' -Status 'Fail' -Fr 'FR2.1-FR2.9' `
                -Detail $_.Exception.Message -Remediation "Run 'az login' and ensure access to subscription $($cfg.subscriptionId)."))
}

foreach ($step in $steps) {
    $scriptName = $step.ScriptName
    if ($results | Where-Object { $_.status -eq 'Fail' }) { break }
    try {
        $functionName = $step.FunctionName
        $stepResults = & $functionName -Config $cfg -ConfigPath $ConfigPath -PassThru -JsonPath $JsonPath
        foreach ($r in @($stepResults)) { $results.Add($r) }
        $fail = @($stepResults | Where-Object { $_.status -eq 'Fail' } | Select-Object -First 1)
        if ($fail.Count -gt 0) {
            $results.Add((New-CheckResult -Id "stage2-stop-$scriptName" -Name "stopped after $scriptName" -Status 'Fail' -Fr 'FR2.9' `
                        -Detail "First hard failure: $($fail[0].name) — $($fail[0].detail)" `
                        -Remediation $fail[0].remediation))
            break
        }
    }
    catch {
        $results.Add((New-CheckResult -Id "stage2-exception-$scriptName" -Name "sub-script $scriptName" -Status 'Fail' -Fr 'FR2.9' `
                    -Detail $_.Exception.Message -Remediation "Fix the error in $scriptName and rerun Stage 2; scripts are idempotent."))
        break
    }
}

if ($PassThru) { return $results.ToArray() }
$null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 2 · landing-zone preparation (FR2.1-FR2.9)' -JsonPath $JsonPath
Complete-Stage -Results $results.ToArray()

