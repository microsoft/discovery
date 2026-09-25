#Requires -Version 7.0
<#
.SYNOPSIS  Stage 4 / FR4.1 - orchestrate Discovery platform deployment.
.DESCRIPTION
    Gates on Stage 3 readiness when provided, asserts Azure login, runs the
    ordered Stage 4 deployer, and surfaces recovery guidance for workspace-only
    failures. Single self-contained Stage 4 script folding in deploy_order.ps1,
    error_remediation_engine.ps1, true_state_detection.ps1, and recovery_reput.ps1.
    Spec: ../../script-specs/stage4-deployment/stage4_deploy.md
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [string]$JsonPath,
    [switch]$PassThru,
    [string]$BicepPath,
    [string]$ParametersPath,
    [switch]$NoBicep,
    [string]$ReadinessReport,
    [switch]$Recovery,
    [string]$Subscription,
    [string]$ResourceGroup,
    [string]$Workspace
)
Import-Module (Join-Path $PSScriptRoot '..\lib\OnboardingCommon.psm1') -Force
$script:DiscoveryApiVersion = '2026-06-01'

function Resolve-DiscoveryError {
    [CmdletBinding()]
    param([Parameter(Mandatory)][AllowEmptyString()][string]$ErrorText)

    $text = $ErrorText
    $rules = @(
        [pscustomobject]@{
            Signature   = 'Creation not supported in region'
            RootCause   = 'the target region is not a Discovery-creatable region for this resource type (the ARM-advertised location list can be broader than what the service allows for creation)'
            Remediation = 'deploy into a Discovery-creatable region (for supercomputers/storageContainers eastus is confirmed creatable; eastus2 is rejected despite being advertised) and place the BYO VNet/subnets in that same region so the supercomputer stays co-regional with its node pool subnet'
            Match       = { param($t) $t -match '(?is)Creation of new .* resources is not supported in region|is not supported in region' }
        }
        [pscustomobject]@{
            Signature   = 'RegionMismatch on supercomputer/nodePool SubnetId'
            RootCause   = 'supercomputer location (controlPlaneRegion) differs from the BYO VNet/subnet region'
            Remediation = 'set controlPlaneRegion to the region of the managedcluster/nodepool VNet so the supercomputer is co-regional with its subnets, then delete the failed supercomputer and re-run (region is immutable)'
            Match       = { param($t) $t -match '(?is)RegionMismatch|Region mismatch for dependent resource|must be in the same region as the primary resource' }
        }
        [pscustomobject]@{
            Signature   = 'AKSCapacityHeavyUsage / InternalServerError on AKS create'
            RootCause   = 'region capacity for API Server VNet Integration'
            Remediation = 'retry, or deploy workload in a region with capacity and global-peer to the firewall'
            Match       = { param($t) $t -match '(?is)AKSCapacityHeavyUsage|((InternalServerError).*(AKS|managedClusters|api[ -]?server|apiserver))|((AKS|managedClusters|api[ -]?server|apiserver).*(InternalServerError))' }
        }
        [pscustomobject]@{
            Signature   = 'AZFWApplicationRule deny on packages.microsoft.com'
            RootCause   = 'firewall rule source scoped to wrong CIDR'
            Remediation = 'add the real spoke CIDR to firewall source addresses; allow the bootstrap FQDNs'
            Match       = { param($t) $t -match '(?is)AZFWApplicationRule|AzureFirewallApplicationRule|Action:\s*Deny' -and $t -match '(?is)packages\.microsoft\.com' }
        }
        [pscustomobject]@{
            Signature   = '409 FlagMustBeSetForRestore'
            RootCause   = 'Foundry account soft-deleted then recreated'
            Remediation = 'set Restore=true, or purge and wait before re-PUT'
            Match       = { param($t) $t -match '(?is)(409|Conflict).*FlagMustBeSetForRestore|FlagMustBeSetForRestore.*(409|Conflict)' }
        }
        [pscustomobject]@{
            Signature   = 'RequestDisallowedByPolicy on Foundry / Cognitive Services account'
            RootCause   = 'workspace-MRG Foundry account with publicNetworkAccess=Enabled'
            Remediation = 'apply the workspace-MRG exemption (RP fix planned, not yet shipped)'
            Match       = { param($t) $t -match '(?is)RequestDisallowedByPolicy' -and $t -match '(?is)Foundry|Cognitive Services|Microsoft\.CognitiveServices|cognitiveservices|accounts' }
        }
        [pscustomobject]@{
            Signature   = 'RequestDisallowedByPolicy on Log Analytics workspace'
            RootCause   = 'Log Analytics MRG public access disallowed'
            Remediation = 'apply the Log Analytics MRG public-access exemption'
            Match       = { param($t) $t -match '(?is)RequestDisallowedByPolicy' -and $t -match '(?is)Log Analytics|OperationalInsights|Microsoft\.OperationalInsights' }
        }
        [pscustomobject]@{
            Signature   = 'Storage public-access policy deny'
            RootCause   = 'Bookshelf MRG storage publicNetworkAccess=Enabled'
            Remediation = 'apply the Bookshelf MRG exemption, or move to PE architecture'
            Match       = { param($t) $t -match '(?is)RequestDisallowedByPolicy|policy|deny' -and $t -match '(?is)Microsoft\.Storage|storage account|Storage' -and $t -match '(?is)publicNetworkAccess|public access|AllowBlobPublicAccess|network access' }
        }
        [pscustomobject]@{
            Signature   = 'No CustomDnsConfigs found on PE'
            RootCause   = 'private endpoint not approved / no DNS configs'
            Remediation = 'approve PE (Pending) or recreate (Rejected/Disconnected); success = Approved, dnsCount 3'
            Match       = { param($t) $t -match '(?is)No CustomDnsConfigs found|CustomDnsConfigs.*(empty|missing|not found)|dnsCount\s*[:=]\s*0' }
        }
        [pscustomobject]@{
            Signature   = 'NSP association InternalServerError, terminal Failed'
            RootCause   = 'NSP association raced provisioning'
            Remediation = 'retry with backoff after convergence'
            Match       = { param($t) $t -match '(?is)NSP|Network Security Perimeter|networkSecurityPerimeters' -and $t -match '(?is)association' -and $t -match '(?is)InternalServerError|terminal\s+Failed|provisioningState.*Failed' }
        }
    )

    foreach ($rule in $rules) {
        if (& $rule.Match $text) {
            return [pscustomobject]@{
                matched        = $true
                errorSignature = $rule.Signature
                rootCause      = $rule.RootCause
                remediation    = $rule.Remediation
            }
        }
    }

    [pscustomobject]@{
        matched        = $false
        errorSignature = 'unrecognized signature'
        rootCause      = 'No Stage 4 remediation rule matched the ARM error payload'
        remediation    = 'Log the raw error and add a new error_remediation_engine mapping with the dependency-spec owner.'
    }
}

function Get-DiscoveryArmState {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ResourceId)
    $state = Invoke-Az -Args @('resource', 'show', '--ids', $ResourceId, '--api-version', $script:DiscoveryApiVersion, '--query', 'properties.provisioningState', '-o', 'tsv') -AllowFail
    if ([string]::IsNullOrWhiteSpace($state)) { return 'NotFound' }
    return $state.Trim()
}

function Get-FoundryAccountState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$AccountName
    )
    $acct = Get-AzJson -Args @('cognitiveservices', 'account', 'show', '-g', $ResourceGroup, '-n', $AccountName) -AllowFail
    if (-not $acct) { return 'NotFound' }
    if ($acct.PSObject.Properties.Name -contains 'provisioningState' -and $acct.provisioningState) { return [string]$acct.provisioningState }
    if ($acct.PSObject.Properties.Name -contains 'properties' -and $acct.properties -and $acct.properties.PSObject.Properties.Name -contains 'provisioningState') {
        return [string]$acct.properties.provisioningState
    }
    return 'Unknown'
}

function Test-DiscoveryTrueState {
    [CmdletBinding()]
    param(
        [string]$ResourceId,
        [string]$AccountName,
        [string]$ResourceGroup,
        [int]$TimeoutMinutes = 45,
        [int]$PollSeconds = 60
    )

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $transient = @('Accepted', 'Creating', 'Running', 'Updating', 'Provisioning')
    $terminal = @('Succeeded', 'Failed', 'Canceled', 'Cancelled', 'NotFound')
    $listState = if ($ResourceId) { Get-DiscoveryArmState -ResourceId $ResourceId } else { 'NotChecked' }
    $trueState = $listState
    $source = 'arm'

    while ($true) {
        if ($AccountName -and $ResourceGroup) {
            $source = 'cognitiveservices'
            $trueState = Get-FoundryAccountState -ResourceGroup $ResourceGroup -AccountName $AccountName
        }

        if ($terminal -contains $trueState -or -not ($transient -contains $trueState)) { break }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Seconds $PollSeconds
        if ($ResourceId) { $listState = Get-DiscoveryArmState -ResourceId $ResourceId }
    }

    $timedOut = ($transient -contains $trueState) -and (Get-Date) -ge $deadline
    $verdict = if ($timedOut) { 'Fail' } elseif ($trueState -eq 'Succeeded' -and ($listState -eq 'Succeeded' -or $listState -eq 'NotChecked')) { 'Pass' } elseif ($trueState -eq 'Succeeded') { 'Warn' } else { 'Fail' }
    [pscustomobject]@{
        resource   = $ResourceId
        account    = $AccountName
        listState  = $listState
        trueState  = if ($timedOut) { "TimedOut:$trueState" } else { $trueState }
        source     = $source
        verdict    = $verdict
        timedOut   = $timedOut
        timeoutMin = $TimeoutMinutes
    }
}

function Invoke-Stage4DeployOrder {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$BicepPath,
        [string]$ParametersPath,
        [int]$TimeoutMinutes = 120,
        [int]$PollSeconds = 60
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()
    $script:DiscoveryApiVersion = '2026-06-01'

function Get-ObjProp {
    param([object]$Object, [string]$Name)
    if ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

function Get-DeploymentResourceGroup {
    param([object]$Config)
    $direct = Get-ObjProp -Object $Config -Name 'resourceGroup'
    if ($direct) { return [string]$direct }
    $deployment = Get-ObjProp -Object $Config -Name 'deployment'
    $fromDeployment = Get-ObjProp -Object $deployment -Name 'resourceGroup'
    if ($fromDeployment) { return [string]$fromDeployment }
    return ''
}

function Get-ConfigName {
    param([object]$Config, [string]$Name, [string]$Default)
    $names = Get-ObjProp -Object $Config -Name 'names'
    $value = Get-ObjProp -Object $names -Name $Name
    if ($value) { return [string]$value }
    return $Default
}

function New-DiscoveryId {
    param([string]$SubscriptionId, [string]$ResourceGroup, [string]$TypePath, [string]$NamePath)
    return "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/$TypePath/$NamePath"
}

function Get-SubnetIdByRole {
    param([object]$Config, [string]$Role, [string]$ResourceGroup)
    $network = Get-ObjProp -Object $Config -Name 'network'
    $subnets = @(Get-ObjProp -Object $network -Name 'subnets')
    $subnet = $subnets | Where-Object { (Get-ObjProp -Object $_ -Name 'role') -eq $Role } | Select-Object -First 1
    if (-not $subnet) { return '' }
    $id = Get-ObjProp -Object $subnet -Name 'id'
    if ($id) { return [string]$id }
    $vnetName = Get-ObjProp -Object $subnet -Name 'vnetName'
    if (-not $vnetName) { $vnetName = Get-ObjProp -Object $network -Name 'vnetName' }
    $name = Get-ObjProp -Object $subnet -Name 'name'
    if ($vnetName -and $name) {
        $subRg = Get-ObjProp -Object $subnet -Name 'resourceGroup'
        if (-not $subRg) { $subRg = Get-ObjProp -Object $network -Name 'networkResourceGroup' }
        if (-not $subRg) { $subRg = $ResourceGroup }
        return "/subscriptions/$($Config.subscriptionId)/resourceGroups/$subRg/providers/Microsoft.Network/virtualNetworks/$vnetName/subnets/$name"
    }
    return ''
}

function Get-VNetRegionFromSubnetId {
    param([string]$SubnetId)
    if ([string]::IsNullOrWhiteSpace($SubnetId)) { return '' }
    $vnetId = $SubnetId -replace '/subnets/[^/]+$', ''
    if ($vnetId -eq $SubnetId) { return '' }
    $loc = Invoke-Az -Args @('resource', 'show', '--ids', $vnetId, '--query', 'location', '-o', 'tsv') -AllowFail
    if ([string]::IsNullOrWhiteSpace($loc)) { return '' }
    return $loc.Trim()
}

function Get-ManagedIdentityId {
    param([object]$Config, [string]$ResourceGroup)
    foreach ($containerName in @('managedIdentity', 'workspaceIdentity', 'identity')) {
        $container = Get-ObjProp -Object $Config -Name $containerName
        $id = Get-ObjProp -Object $container -Name 'id'
        if ($id) { return [string]$id }
    }
    $direct = Get-ObjProp -Object $Config -Name 'managedIdentityId'
    if ($direct) { return [string]$direct }
    $identityName = Get-ConfigName -Config $Config -Name 'managedIdentity' -Default ''
    if ($identityName) {
        return "/subscriptions/$($Config.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$identityName"
    }
    return ''
}

function Get-StorageAccountId {
    param([object]$Config, [string]$ResourceGroup)
    $storage = Get-ObjProp -Object $Config -Name 'storage'
    $id = Get-ObjProp -Object $storage -Name 'accountId'
    if ($id) { return [string]$id }
    $account = Get-ObjProp -Object $storage -Name 'account'
    if ($account) {
        return "/subscriptions/$($Config.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts/$account"
    }
    return ''
}

function ConvertTo-JsonBodyFile {
    param([Parameter(Mandatory)][object]$Body)
    $file = New-TemporaryFile
    $Body | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $file.FullName -Encoding utf8
    return $file.FullName
}

function Invoke-ArmPut {
    param([string]$ResourceId, [object]$Body)
    $bodyFile = ConvertTo-JsonBodyFile -Body $Body
    try {
        $url = "https://management.azure.com$ResourceId`?api-version=$script:DiscoveryApiVersion"
        Invoke-Az -Args @('rest', '--method', 'put', '--url', $url, '--body', "@$bodyFile", '--headers', 'Content-Type=application/json') | Out-Null
        return [pscustomobject]@{ ok = $true; error = '' }
    } catch {
        return [pscustomobject]@{ ok = $false; error = $_.Exception.Message }
    } finally {
        Remove-Item -LiteralPath $bodyFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-ArmState {
    param([string]$ResourceId)
    $state = Invoke-Az -Args @('resource', 'show', '--ids', $ResourceId, '--api-version', $script:DiscoveryApiVersion, '--query', 'properties.provisioningState', '-o', 'tsv') -AllowFail
    if ([string]::IsNullOrWhiteSpace($state)) { return 'NotFound' }
    return $state.Trim()
}

function Wait-DiscoveryGate {
    param(
        [string]$ResourceId,
        [string]$FoundryAccountName,
        [string]$FoundryResourceGroup
    )
    if ($FoundryAccountName -and $FoundryResourceGroup) {
        return Test-DiscoveryTrueState -ResourceId $ResourceId -AccountName $FoundryAccountName -ResourceGroup $FoundryResourceGroup -TimeoutMinutes $TimeoutMinutes -PollSeconds $PollSeconds
    }
    return Test-DiscoveryTrueState -ResourceId $ResourceId -TimeoutMinutes $TimeoutMinutes -PollSeconds $PollSeconds
}

function New-StepResult {
    param(
        [string]$Id,
        [string]$Name,
        [string]$ResourceId,
        [string]$State,
        [string]$Fr,
        [string]$ErrorText = '',
        [object]$Extra = $null
    )
    $ok = $State -eq 'Succeeded'
    $resolved = if ($ok) { $null } else { Resolve-DiscoveryError -ErrorText $ErrorText }
    $detail = "resource=$ResourceId provisioningState=$State"
    if (-not $ok -and $resolved) { $detail = "$detail remediationMatch=$($resolved.errorSignature)" }
    New-CheckResult -Id $Id -Name $Name -Status ($ok ? 'Pass' : 'Fail') -Fr $Fr -Detail $detail `
        -Remediation ($ok ? '' : $resolved.remediation) `
        -Data ([pscustomobject]@{ resource = $ResourceId; provisioningState = $State; remediation = $resolved; extra = $Extra })
}

function Invoke-BicepDeploymentOnce {
    param([string]$ResourceGroup, [string]$TemplateFile, [string]$ParameterFile)
    if (-not $TemplateFile) { return [pscustomobject]@{ ok = $true; error = '' } }
    if (-not (Test-Path -LiteralPath $TemplateFile)) { return [pscustomobject]@{ ok = $false; error = "BicepPath not found: $TemplateFile" } }
    $args = @('deployment', 'group', 'create', '-g', $ResourceGroup, '--name', "stage4-$(Get-Date -Format yyyyMMddHHmmss)", '--template-file', $TemplateFile)
    if ($ParameterFile) {
        if (-not (Test-Path -LiteralPath $ParameterFile)) { return [pscustomobject]@{ ok = $false; error = "ParametersPath not found: $ParameterFile" } }
        $args += @('--parameters', "@$ParameterFile")
    }
    try {
        Invoke-Az -Args $args | Out-Null
        return [pscustomobject]@{ ok = $true; error = '' }
    } catch {
        return [pscustomobject]@{ ok = $false; error = $_.Exception.Message }
    }
}

function New-Stage4BicepParamFile {
    param([object]$Config, [string]$ResourceGroup, [string]$Location)

    $names = Get-ObjProp -Object $Config -Name 'names'
    $bookshelf = Get-ObjProp -Object $Config -Name 'bookshelf'
    $inScope = Get-ObjProp -Object $bookshelf -Name 'inScope'
    $bookshelfInScope = if ($null -ne $inScope) { [bool]$inScope } else { $true }

    $p = [ordered]@{
        location                = $Location
        workloadRegion          = [string]$Config.workloadRegion
        supercomputerName       = [string](Get-ObjProp -Object $names -Name 'supercomputer')
        workspaceName           = [string](Get-ObjProp -Object $names -Name 'workspace')
        projectName             = [string](Get-ObjProp -Object $names -Name 'project')
        nodePoolName            = [string](Get-ObjProp -Object $names -Name 'nodePool')
        storageContainerName    = [string](Get-ObjProp -Object $names -Name 'storageContainer')
        chatModelDeploymentName = 'gpt-5-4'
        chatModelName           = 'gpt-5.4'
        managedIdentityId       = Get-ManagedIdentityId -Config $Config -ResourceGroup $ResourceGroup
        managedClusterSubnetId  = Get-SubnetIdByRole -Config $Config -Role 'managedcluster' -ResourceGroup $ResourceGroup
        nodePoolSubnetId        = Get-SubnetIdByRole -Config $Config -Role 'nodepool' -ResourceGroup $ResourceGroup
        agentSubnetId           = Get-SubnetIdByRole -Config $Config -Role 'agent-containerapp' -ResourceGroup $ResourceGroup
        workspaceSubnetId       = Get-SubnetIdByRole -Config $Config -Role 'workspace-containerapp' -ResourceGroup $ResourceGroup
        privateEndpointSubnetId = Get-SubnetIdByRole -Config $Config -Role 'private-endpoints' -ResourceGroup $ResourceGroup
        storageAccountId        = Get-StorageAccountId -Config $Config -ResourceGroup $ResourceGroup
        bookshelfInScope        = $bookshelfInScope
    }
    foreach ($opt in 'systemSku', 'nodePoolVmSize', 'nodePoolScaleSetPriority') {
        $v = Get-ObjProp -Object $Config -Name $opt
        if ($v) { $p[$opt] = [string]$v }
    }
    $net = Get-ObjProp -Object $Config -Name 'network'
    $outboundType = Get-ObjProp -Object $net -Name 'outboundType'
    if ($outboundType) { $p['outboundType'] = [string]$outboundType }
    foreach ($opt in 'nodePoolMinNodeCount', 'nodePoolMaxNodeCount') {
        $v = Get-ObjProp -Object $Config -Name $opt
        if ($null -ne $v) { $p[$opt] = [int]$v }
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


$subscriptionId = [string]$cfg.subscriptionId
$resourceGroup = Get-DeploymentResourceGroup -Config $cfg
if ([string]::IsNullOrWhiteSpace($resourceGroup)) {
    $results.Add((New-CheckResult -Id 'deploy-config-resource-group' -Name 'deployment resource group' -Status 'Fail' -Fr 'FR4.1' `
                -Detail 'Config does not include resourceGroup or deployment.resourceGroup.' `
                -Remediation 'Add the target deployment resource group to the onboarding config; Stage 4 writes platform resources and will not guess the scope.'))
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

Invoke-Az -Args @('account', 'set', '--subscription', $subscriptionId) | Out-Null

$location = [string]$cfg.controlPlaneRegion
$workspaceName = Get-ConfigName -Config $cfg -Name 'workspace' -Default ''
$projectName = Get-ConfigName -Config $cfg -Name 'project' -Default "$workspaceName-project"
$supercomputerName = Get-ConfigName -Config $cfg -Name 'supercomputer' -Default ''
$nodePoolName = Get-ConfigName -Config $cfg -Name 'nodePool' -Default ''
$storageContainerName = Get-ConfigName -Config $cfg -Name 'storageContainer' -Default "$workspaceName-bookshelf"
$managedIdentityId = Get-ManagedIdentityId -Config $cfg -ResourceGroup $resourceGroup

$supercomputerId = New-DiscoveryId -SubscriptionId $subscriptionId -ResourceGroup $resourceGroup -TypePath 'supercomputers' -NamePath $supercomputerName
$workspaceId = New-DiscoveryId -SubscriptionId $subscriptionId -ResourceGroup $resourceGroup -TypePath 'workspaces' -NamePath $workspaceName
$chatModelId = "$workspaceId/chatModelDeployments/gpt-5-4"
$storageContainerId = New-DiscoveryId -SubscriptionId $subscriptionId -ResourceGroup $resourceGroup -TypePath 'storageContainers' -NamePath $storageContainerName
$projectId = "$workspaceId/projects/$projectName"

# Region co-location pre-flight (applies to both Bicep and ARM paths). The supercomputer must be
# co-regional with its managedcluster/nodepool subnets; discovery.overridemrgregion does not relax it.
if (-not $Recovery -and $location) {
    $preflightSubnet = Get-SubnetIdByRole -Config $cfg -Role 'managedcluster' -ResourceGroup $resourceGroup
    if ($preflightSubnet) {
        $preflightRegion = Get-VNetRegionFromSubnetId -SubnetId $preflightSubnet
        if ($preflightRegion -and $preflightRegion -ne $location) {
            $results.Add((New-CheckResult -Id 'deploy-supercomputer' -Name 'supercomputer deployment' -Status 'Fail' -Fr 'FR4.1' `
                        -Detail "resource=$supercomputerId provisioningState=NotSubmitted RegionMismatch expected=$location actual=$preflightRegion subnet=$preflightSubnet" `
                        -Remediation "controlPlaneRegion ($location) must match the managedcluster/nodepool VNet region ($preflightRegion); the supercomputer and its node pool subnet must be co-regional. Set controlPlaneRegion=$preflightRegion, delete the failed supercomputer, and re-run (region is immutable)." `
                        -Data ([pscustomobject]@{ expected = $location; actual = $preflightRegion; subnetId = $preflightSubnet })))
            if ($PassThru) { return $results.ToArray() }
            $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
            Complete-Stage -Results $results.ToArray()
        }
    }
}

# Bicep is the default deploy path: template the whole platform in one RG deployment, driven by
# parameters generated from the Stage 1 config. Pass -NoBicep to use per-resource ARM PUTs instead,
# or -BicepPath to supply a custom template.
$generatedParamFile = $null
if (-not $NoBicep -and -not $Recovery -and -not $BicepPath) {
    $defaultBicep = Join-Path $PSScriptRoot 'discovery-platform.bicep'
    if (Test-Path -LiteralPath $defaultBicep) {
        $BicepPath = $defaultBicep
        if (-not $ParametersPath) {
            $generatedParamFile = New-Stage4BicepParamFile -Config $cfg -ResourceGroup $resourceGroup -Location $location
            $ParametersPath = $generatedParamFile
        }
    }
}

$bicepAttempt = Invoke-BicepDeploymentOnce -ResourceGroup $resourceGroup -TemplateFile $BicepPath -ParameterFile $ParametersPath
if ($generatedParamFile) { Remove-Item -LiteralPath $generatedParamFile -Force -ErrorAction SilentlyContinue }


if (-not $BicepPath) {
    $scMissing = @()
    $scSubnet = Get-SubnetIdByRole -Config $cfg -Role 'managedcluster' -ResourceGroup $resourceGroup
    $scMgmtSubnet = Get-SubnetIdByRole -Config $cfg -Role 'managedcluster' -ResourceGroup $resourceGroup
    $nodeSubnet = Get-SubnetIdByRole -Config $cfg -Role 'nodepool' -ResourceGroup $resourceGroup
    if (-not $supercomputerName) { $scMissing += 'names.supercomputer' }
    if (-not $location) { $scMissing += 'controlPlaneRegion' }
    if (-not $managedIdentityId) { $scMissing += 'managedIdentity.id or names.managedIdentity' }
    if (-not $scSubnet) { $scMissing += 'managedcluster subnet id/name' }
    $regionMismatch = $null
    if ($location -and $scSubnet) {
        $subnetRegion = Get-VNetRegionFromSubnetId -SubnetId $scSubnet
        if ($subnetRegion -and $subnetRegion -ne $location) {
            $regionMismatch = [pscustomobject]@{ expected = $location; actual = $subnetRegion; subnetId = $scSubnet }
        }
    }
    if ($scMissing.Count) {
        $results.Add((New-CheckResult -Id 'deploy-supercomputer' -Name 'supercomputer deployment' -Status 'Fail' -Fr 'FR4.1' `
                    -Detail "resource=$supercomputerId provisioningState=NotSubmitted missing=$($scMissing -join ',')" `
                    -Remediation 'Supply the missing config values or provide -BicepPath/-ParametersPath for the platform template.' `
                    -Data ([pscustomobject]@{ resource = $supercomputerId; provisioningState = 'NotSubmitted'; missing = $scMissing })))
    } elseif ($regionMismatch) {
        $results.Add((New-CheckResult -Id 'deploy-supercomputer' -Name 'supercomputer deployment' -Status 'Fail' -Fr 'FR4.1' `
                    -Detail "resource=$supercomputerId provisioningState=NotSubmitted RegionMismatch expected=$($regionMismatch.expected) actual=$($regionMismatch.actual) subnet=$($regionMismatch.subnetId)" `
                    -Remediation "controlPlaneRegion ($($regionMismatch.expected)) must match the managedcluster/nodepool VNet region ($($regionMismatch.actual)); the supercomputer and its node pool subnet must be co-regional. Set controlPlaneRegion=$($regionMismatch.actual), delete the failed supercomputer, and re-run (region is immutable)." `
                    -Data $regionMismatch))
    } else {
        $scBody = @{
            location   = $location
            tags       = @{ version = 'v2'; 'discovery.overridemrgregion' = [string]$cfg.workloadRegion }
            properties = @{
                subnetId           = $scSubnet
                managementSubnetId = $scMgmtSubnet
                outboundType       = 'UserDefinedRouting'
                identities         = @{
                    clusterIdentity    = @{ id = $managedIdentityId }
                    kubeletIdentity    = @{ id = $managedIdentityId }
                    workloadIdentities = @{ $managedIdentityId = @{} }
                }
            }
        }
        $systemSku = Get-ObjProp -Object $cfg -Name 'systemSku'
        if ($systemSku) { $scBody.properties.systemSku = [string]$systemSku }
        $put = Invoke-ArmPut -ResourceId $supercomputerId -Body $scBody
        if ($put.ok -and $nodePoolName -and $nodeSubnet) {
            $npBody = @{
                location   = $location
                properties = @{
                    subnetId             = $nodeSubnet
                    vmSize               = [string]((Get-ObjProp -Object $cfg -Name 'nodePoolVmSize') ?? 'Standard_D4ds_v6')
                    maxNodeCount         = [int]((Get-ObjProp -Object $cfg -Name 'nodePoolMaxNodeCount') ?? 3)
                    minNodeCount         = [int]((Get-ObjProp -Object $cfg -Name 'nodePoolMinNodeCount') ?? 0)
                    scaleSetPriority     = [string]((Get-ObjProp -Object $cfg -Name 'nodePoolScaleSetPriority') ?? 'Regular')
                }
            }
            $null = Invoke-ArmPut -ResourceId "$supercomputerId/nodePools/$nodePoolName" -Body $npBody
        }
        $gate = Wait-DiscoveryGate -ResourceId $supercomputerId
        $state = $gate.trueState -replace '^TimedOut:', ''
        $results.Add((New-StepResult -Id 'deploy-supercomputer' -Name 'supercomputer deployment' -ResourceId $supercomputerId -State $state -Fr 'FR4.1' -ErrorText $put.error -Extra $gate))
    }
} else {
    $gate = Wait-DiscoveryGate -ResourceId $supercomputerId
    $state = $gate.trueState -replace '^TimedOut:', ''
    $results.Add((New-StepResult -Id 'deploy-supercomputer' -Name 'supercomputer deployment' -ResourceId $supercomputerId -State $state -Fr 'FR4.1' -ErrorText $bicepAttempt.error -Extra $gate))
}

if (@($results | Where-Object { $_.id -eq 'deploy-supercomputer' -and $_.status -eq 'Fail' }).Count) {
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

$scStateBeforeWorkspace = Get-ArmState -ResourceId $supercomputerId
if ($scStateBeforeWorkspace -eq 'Failed') {
    $results.Add((New-CheckResult -Id 'deploy-workspace' -Name 'workspace deployment' -Status 'Fail' -Fr 'FR4.1' `
                -Detail "resource=$workspaceId provisioningState=NotSubmitted supercomputerState=Failed" `
                -Remediation 'Fix the supercomputer first; do not touch the workspace while the supercomputer is Failed.' `
                -Data ([pscustomobject]@{ resource = $workspaceId; provisioningState = 'NotSubmitted'; supercomputer = $supercomputerId; supercomputerState = 'Failed' })))
} else {
    if (-not $BicepPath) {
        $wsMissing = @()
        $agentSubnet = Get-SubnetIdByRole -Config $cfg -Role 'agent-containerapp' -ResourceGroup $resourceGroup
        $workspaceSubnet = Get-SubnetIdByRole -Config $cfg -Role 'workspace-containerapp' -ResourceGroup $resourceGroup
        $peSubnet = Get-SubnetIdByRole -Config $cfg -Role 'private-endpoints' -ResourceGroup $resourceGroup
        if (-not $workspaceName) { $wsMissing += 'names.workspace' }
        if (-not $managedIdentityId) { $wsMissing += 'managedIdentity.id or names.managedIdentity' }
        if (-not $agentSubnet) { $wsMissing += 'agent-containerapp subnet id/name' }
        if (-not $workspaceSubnet) { $wsMissing += 'workspace-containerapp subnet id/name' }
        if (-not $peSubnet) { $wsMissing += 'private-endpoints subnet id/name' }
        if ($wsMissing.Count) {
            $results.Add((New-CheckResult -Id 'deploy-workspace' -Name 'workspace deployment' -Status 'Fail' -Fr 'FR4.1' `
                        -Detail "resource=$workspaceId provisioningState=NotSubmitted missing=$($wsMissing -join ',')" `
                        -Remediation 'Supply the missing workspace config values or provide -BicepPath/-ParametersPath for the platform template.' `
                        -Data ([pscustomobject]@{ resource = $workspaceId; provisioningState = 'NotSubmitted'; missing = $wsMissing })))
        } else {
            $wsBody = @{
                location   = $location
                tags       = @{
                    version                                      = 'v2'
                    'discovery.workbench.enableGhcpAiFeatures'   = 'true'
                    'discovery.workbench.enableExtensions'       = 'true'
                    'discovery.overridemrgregion'                = [string]$cfg.workloadRegion
                    NetworkIsolation                             = 'true'
                    SkipAssociateKeyVaultToNsp                  = 'true'
                    SkipAssociateCosmosDBToNsp                  = 'true'
                    SkipAssociateStorageAccountsToNsp           = 'true'
                }
                properties = @{
                    workspaceIdentity      = @{ id = $managedIdentityId }
                    supercomputerIds       = @($supercomputerId)
                    agentSubnetId          = $agentSubnet
                    privateEndpointSubnetId = $peSubnet
                    workspaceSubnetId      = $workspaceSubnet
                    publicNetworkAccess    = 'Disabled'
                }
            }
            $put = Invoke-ArmPut -ResourceId $workspaceId -Body $wsBody
        }
    } else {
        $put = $bicepAttempt
    }
    if (-not @($results | Where-Object { $_.id -eq 'deploy-workspace' }).Count) {
        $foundry = Get-ObjProp -Object $cfg -Name 'foundry'
        $foundryAccount = Get-ObjProp -Object $foundry -Name 'accountName'
        $foundryRg = Get-ObjProp -Object $foundry -Name 'resourceGroup'
        $gate = Wait-DiscoveryGate -ResourceId $workspaceId -FoundryAccountName $foundryAccount -FoundryResourceGroup $foundryRg
        $state = $gate.trueState -replace '^TimedOut:', ''
        $results.Add((New-StepResult -Id 'deploy-workspace' -Name 'workspace deployment' -ResourceId $workspaceId -State $state -Fr 'FR4.1,FR4.3' -ErrorText $put.error -Extra $gate))
    }
}

if (@($results | Where-Object { $_.id -eq 'deploy-workspace' -and $_.status -eq 'Fail' }).Count) {
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

$chatBody = @{ location = $location; properties = @{ modelFormat = 'OpenAI'; modelName = 'gpt-5.4' } }
$chatPut = Invoke-ArmPut -ResourceId $chatModelId -Body $chatBody
$chatGate = Wait-DiscoveryGate -ResourceId $chatModelId
$chatState = $chatGate.trueState -replace '^TimedOut:', ''
$results.Add((New-StepResult -Id 'deploy-chat-model-gpt-5-4' -Name 'validation chat model gpt-5-4' -ResourceId $chatModelId -State $chatState -Fr 'FR4.1,FR4.2' -ErrorText $chatPut.error -Extra $chatGate))

if (@($results | Where-Object { $_.id -eq 'deploy-chat-model-gpt-5-4' -and $_.status -eq 'Fail' }).Count) {
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

$bookshelfInScope = $true
$bookshelf = Get-ObjProp -Object $cfg -Name 'bookshelf'
$configuredInScope = Get-ObjProp -Object $bookshelf -Name 'inScope'
if ($null -ne $configuredInScope) { $bookshelfInScope = [bool]$configuredInScope }
$storageAccountId = Get-StorageAccountId -Config $cfg -ResourceGroup $resourceGroup
$projectProps = @{}
$preExistingStorageState = if ($bookshelfInScope) { Get-ArmState -ResourceId $storageContainerId } else { 'Skipped' }
if ($bookshelfInScope -and $preExistingStorageState -eq 'Succeeded') { $projectProps.storageContainerIds = @($storageContainerId) }
$projectBody = @{ location = $location; properties = $projectProps }
$projectPut = Invoke-ArmPut -ResourceId $projectId -Body $projectBody
$projectGate = Wait-DiscoveryGate -ResourceId $projectId
$projectState = $projectGate.trueState -replace '^TimedOut:', ''
$results.Add((New-StepResult -Id 'deploy-project' -Name 'Discovery project' -ResourceId $projectId -State $projectState -Fr 'FR4.1' -ErrorText $projectPut.error -Extra $projectGate))

if (@($results | Where-Object { $_.id -eq 'deploy-project' -and $_.status -eq 'Fail' }).Count) {
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

if ($bookshelfInScope -and $storageAccountId) {
    $storageBody = @{ location = $location; properties = @{ storageStore = @{ kind = 'AzureStorageBlob'; storageAccountId = $storageAccountId } } }
    $storagePut = Invoke-ArmPut -ResourceId $storageContainerId -Body $storageBody
    $storageGate = Wait-DiscoveryGate -ResourceId $storageContainerId
    $storageState = $storageGate.trueState -replace '^TimedOut:', ''
    $results.Add((New-StepResult -Id 'deploy-bookshelf' -Name 'bookshelf storage container' -ResourceId $storageContainerId -State $storageState -Fr 'FR4.1' -ErrorText $storagePut.error -Extra $storageGate))
} elseif ($bookshelfInScope) {
    $results.Add((New-CheckResult -Id 'deploy-bookshelf' -Name 'bookshelf storage container' -Status 'Fail' -Fr 'FR4.1' `
                -Detail "resource=$storageContainerId provisioningState=NotSubmitted missing=storage.accountId or storage.account" `
                -Remediation 'Supply the storage account id/name used by the Discovery storage container.' `
                -Data ([pscustomobject]@{ resource = $storageContainerId; provisioningState = 'NotSubmitted' })))
} else {
    $results.Add((New-CheckResult -Id 'deploy-bookshelf' -Name 'bookshelf storage container' -Status 'Skip' -Fr 'FR4.1' `
                -Detail 'bookshelf.inScope=false' -Data ([pscustomobject]@{ resource = $storageContainerId; provisioningState = 'Skipped' })))
}

if ($PassThru) { return $results.ToArray() }
$null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
Complete-Stage -Results $results.ToArray()
}

function Invoke-Stage4RecoveryReput {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [Parameter(Mandatory)][string]$Subscription,
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$Workspace,
        [int]$TimeoutMinutes = 120,
        [int]$PollSeconds = 120
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()
    $script:DiscoveryApiVersion = '2026-06-01'

function Get-ObjProp {
    param([object]$Object, [string]$Name)
    if ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

function Get-ConfigName {
    param([object]$Config, [string]$Name, [string]$Default)
    $names = Get-ObjProp -Object $Config -Name 'names'
    $value = Get-ObjProp -Object $names -Name $Name
    if ($value) { return [string]$value }
    return $Default
}

function Remove-ReadOnlyIdentityFields {
    param([object]$Value)
    $readOnly = @('resourceGroup', 'clientId', 'objectId', 'principalId', 'tenantId', 'subscriptionId')
    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Array]) {
        return @($Value | ForEach-Object { Remove-ReadOnlyIdentityFields -Value $_ })
    }
    if ($Value -is [hashtable] -or $Value -is [pscustomobject]) {
        $clean = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            if ($readOnly -contains $property.Name) { continue }
            $clean[$property.Name] = Remove-ReadOnlyIdentityFields -Value $property.Value
        }
        return $clean
    }
    return $Value
}

function ConvertTo-JsonBodyFile {
    param([Parameter(Mandatory)][object]$Body)
    $file = New-TemporaryFile
    $Body | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $file.FullName -Encoding utf8
    return $file.FullName
}

function Invoke-ArmPut {
    param([string]$ResourceId, [object]$Body)
    $bodyFile = ConvertTo-JsonBodyFile -Body $Body
    try {
        $url = "https://management.azure.com$ResourceId`?api-version=$script:DiscoveryApiVersion"
        Invoke-Az -Args @('rest', '--method', 'put', '--url', $url, '--body', "@$bodyFile", '--headers', 'Content-Type=application/json') | Out-Null
        return [pscustomobject]@{ ok = $true; error = '' }
    } catch {
        return [pscustomobject]@{ ok = $false; error = $_.Exception.Message }
    } finally {
        Remove-Item -LiteralPath $bodyFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-ArmState {
    param([string]$ResourceId)
    $state = Invoke-Az -Args @('resource', 'show', '--ids', $ResourceId, '--api-version', $script:DiscoveryApiVersion, '--query', 'properties.provisioningState', '-o', 'tsv') -AllowFail
    if ([string]::IsNullOrWhiteSpace($state)) { return 'NotFound' }
    return $state.Trim()
}

function Wait-DiscoveryGate {
    param([string]$ResourceId)
    Test-DiscoveryTrueState -ResourceId $ResourceId -TimeoutMinutes $TimeoutMinutes -PollSeconds $PollSeconds
}

function New-StepResult {
    param(
        [string]$Id,
        [string]$Name,
        [string]$ResourceId,
        [string]$State,
        [string]$Fr,
        [string]$ErrorText = '',
        [object]$Extra = $null
    )
    $ok = $State -eq 'Succeeded'
    $resolved = if ($ok) { $null } else { Resolve-DiscoveryError -ErrorText $ErrorText }
    New-CheckResult -Id $Id -Name $Name -Status ($ok ? 'Pass' : 'Fail') -Fr $Fr `
        -Detail "resource=$ResourceId provisioningState=$State$($ok ? '' : " remediationMatch=$($resolved.errorSignature)")" `
        -Remediation ($ok ? '' : $resolved.remediation) `
        -Data ([pscustomobject]@{ resource = $ResourceId; provisioningState = $State; remediation = $resolved; extra = $Extra })
}

Assert-AzLogin -SubscriptionId $Subscription
$workspaceId = "/subscriptions/$Subscription/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/workspaces/$Workspace"
$workspaceObj = Get-AzJson -Args @('resource', 'show', '--ids', $workspaceId, '--api-version', $script:DiscoveryApiVersion) -AllowFail
if (-not $workspaceObj) {
    $results.Add((New-CheckResult -Id 'reput-workspace-read' -Name 'read workspace for re-PUT' -Status 'Fail' -Fr 'FR4.5' `
                -Detail "Workspace not found: $workspaceId" `
                -Remediation 'Verify -Subscription, -ResourceGroup, and -Workspace.'))
} else {
    $props = $workspaceObj.properties
    $scIds = @($props.supercomputerIds | Where-Object { $_ })
    if (-not $scIds.Count) {
        $results.Add((New-CheckResult -Id 'reput-supercomputer-link' -Name 'workspace supercomputer link' -Status 'Fail' -Fr 'FR4.5' `
                    -Detail "resource=$workspaceId supercomputerIds is empty" `
                    -Remediation 'Re-PUT requires an existing Succeeded supercomputer link; recreate or repair the workspace with the correct supercomputerIds.'))
    } else {
        $badSc = @()
        foreach ($sc in $scIds) {
            $state = Get-ArmState -ResourceId $sc
            if ($state -ne 'Succeeded') { $badSc += "$sc=$state" }
        }
        if ($badSc.Count) {
            $results.Add((New-CheckResult -Id 'reput-supercomputer-state' -Name 'supercomputer state before workspace re-PUT' -Status 'Fail' -Fr 'FR4.5' `
                        -Detail "Unhealthy supercomputer(s): $($badSc -join '; ')" `
                        -Remediation 'Re-PUT still fails unless the supercomputer is Succeeded; fix it first and confirm FR2.1a NSP role assignment.'))
        } else {
            $bodyProps = [ordered]@{}
            $bodyProps.workspaceIdentity = Remove-ReadOnlyIdentityFields -Value $props.workspaceIdentity
            $bodyProps.supercomputerIds = $scIds
            foreach ($key in @('agentSubnetId', 'privateEndpointSubnetId', 'workspaceSubnetId')) {
                $value = Get-ObjProp -Object $props -Name $key
                if ($value) { $bodyProps[$key] = $value }
            }
            $bodyProps.publicNetworkAccess = 'Disabled'
            $body = [ordered]@{
                location   = $workspaceObj.location
                tags       = $workspaceObj.tags
                properties = $bodyProps
            }
            $put = Invoke-ArmPut -ResourceId $workspaceId -Body $body
            $gate = Wait-DiscoveryGate -ResourceId $workspaceId
            $state = $gate.trueState -replace '^TimedOut:', ''
            $results.Add((New-StepResult -Id 'reput-workspace' -Name 'workspace re-PUT' -ResourceId $workspaceId -State $state -Fr 'FR4.5' -ErrorText $put.error -Extra $gate))
        }
    }
}

if (-not @($results | Where-Object { $_.status -eq 'Fail' }).Count) {
    $location = if ($workspaceObj.location) { [string]$workspaceObj.location } else { [string]$cfg.controlPlaneRegion }
    $chatId = "$workspaceId/chatModelDeployments/gpt-5-4"
    $chatBody = @{ location = $location; properties = @{ modelFormat = 'OpenAI'; modelName = 'gpt-5.4' } }
    $chatPut = Invoke-ArmPut -ResourceId $chatId -Body $chatBody
    $chatGate = Wait-DiscoveryGate -ResourceId $chatId
    $chatState = $chatGate.trueState -replace '^TimedOut:', ''
    $results.Add((New-StepResult -Id 'recovery-chat-model-gpt-5-4' -Name 'post-recovery chat model gpt-5-4' -ResourceId $chatId -State $chatState -Fr 'FR4.5' -ErrorText $chatPut.error -Extra $chatGate))
}

if (-not @($results | Where-Object { $_.status -eq 'Fail' }).Count) {
    $projectName = Get-ConfigName -Config $cfg -Name 'project' -Default "$Workspace-project"
    $storageContainerName = Get-ConfigName -Config $cfg -Name 'storageContainer' -Default "$Workspace-bookshelf"
    $storageContainerId = "/subscriptions/$Subscription/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/storageContainers/$storageContainerName"
    $storageState = Get-ArmState -ResourceId $storageContainerId
    $projectProps = @{}
    if ($storageState -eq 'Succeeded') { $projectProps.storageContainerIds = @($storageContainerId) }
    $projectId = "$workspaceId/projects/$projectName"
    $projectBody = @{ location = [string]$workspaceObj.location; properties = $projectProps }
    $projectPut = Invoke-ArmPut -ResourceId $projectId -Body $projectBody
    $projectGate = Wait-DiscoveryGate -ResourceId $projectId
    $projectState = $projectGate.trueState -replace '^TimedOut:', ''
    $results.Add((New-StepResult -Id 'recovery-project' -Name 'post-recovery project' -ResourceId $projectId -State $projectState -Fr 'FR4.5' -ErrorText $projectPut.error -Extra ([pscustomobject]@{ trueState = $projectGate; storageContainerState = $storageState })))
}

if ($PassThru) { return $results.ToArray() }
$null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · workspace re-PUT recovery (FR4.5)' -JsonPath $JsonPath
Complete-Stage -Results $results.ToArray()
}

function Get-ObjProp {
    param([object]$Object, [string]$Name)
    if ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

function Get-DeploymentResourceGroup {
    param([object]$Config)
    $direct = Get-ObjProp -Object $Config -Name 'resourceGroup'
    if ($direct) { return [string]$direct }
    $deployment = Get-ObjProp -Object $Config -Name 'deployment'
    $fromDeployment = Get-ObjProp -Object $deployment -Name 'resourceGroup'
    if ($fromDeployment) { return [string]$fromDeployment }
    return ''
}

function Get-ConfigName {
    param([object]$Config, [string]$Name, [string]$Default)
    $names = Get-ObjProp -Object $Config -Name 'names'
    $value = Get-ObjProp -Object $names -Name $Name
    if ($value) { return [string]$value }
    return $Default
}

if ($Recovery) {
    $recoveryResults = Invoke-Stage4RecoveryReput -ConfigPath $ConfigPath -JsonPath $JsonPath -PassThru:$true -Subscription $Subscription -ResourceGroup $ResourceGroup -Workspace $Workspace
    if ($PassThru) { return $recoveryResults }
    $null = Write-OnboardingReport -Results $recoveryResults -Title 'Stage 4 · workspace re-PUT recovery (FR4.5)' -JsonPath $JsonPath
    Complete-Stage -Results $recoveryResults
}

$cfg = Get-OnboardingConfig -Path $ConfigPath
$results = [System.Collections.Generic.List[object]]::new()

Assert-AzLogin -SubscriptionId ([string]$cfg.subscriptionId)

$readinessGateOpen = $true
if ($ReadinessReport) {
    if (-not (Test-Path -LiteralPath $ReadinessReport)) {
        $readinessGateOpen = $false
        $results.Add((New-CheckResult -Id 'stage3-readiness-report' -Name 'Stage 3 readiness report' -Status 'Fail' -Fr 'FR4.6' `
                    -Detail "Readiness report not found: $ReadinessReport" `
                    -Remediation 'Run Stage 3 validation and pass the GO report before Stage 4 writes platform resources.'))
    } else {
        try {
            $readiness = Get-Content -LiteralPath $ReadinessReport -Raw | ConvertFrom-Json -ErrorAction Stop
            $verdict = Get-ObjProp -Object $readiness -Name 'verdict'
            if ($verdict -eq 'GO') {
                $results.Add((New-CheckResult -Id 'stage3-readiness-report' -Name 'Stage 3 readiness report' -Status 'Pass' -Fr 'FR4.6' `
                            -Detail "verdict=GO path=$ReadinessReport"))
            } else {
                $readinessGateOpen = $false
                $results.Add((New-CheckResult -Id 'stage3-readiness-report' -Name 'Stage 3 readiness report' -Status 'Fail' -Fr 'FR4.6' `
                            -Detail "verdict=$verdict path=$ReadinessReport" `
                            -Remediation 'Do not run Stage 4 until Stage 3 dependency validation is GO.'))
            }
        } catch {
            $readinessGateOpen = $false
            $results.Add((New-CheckResult -Id 'stage3-readiness-report' -Name 'Stage 3 readiness report' -Status 'Fail' -Fr 'FR4.6' `
                        -Detail "Unable to parse readiness report: $($_.Exception.Message)" `
                        -Remediation 'Regenerate the Stage 3 JSON report and rerun Stage 4.'))
        }
    }
} else {
    $results.Add((New-CheckResult -Id 'stage3-readiness-report' -Name 'Stage 3 readiness report' -Status 'Warn' -Fr 'FR4.6' `
                -Detail 'No -ReadinessReport was supplied; proceeding because the parameter is optional.' `
                -Remediation 'For production runs, pass the Stage 3 GO report to gate Stage 4 writes.'))
}

if ($readinessGateOpen) {
    $deployArgs = @{
        ConfigPath = $ConfigPath
        PassThru   = $true
    }
    if ($BicepPath) { $deployArgs.BicepPath = $BicepPath }
    if ($ParametersPath) { $deployArgs.ParametersPath = $ParametersPath }
    $deployResults = Invoke-Stage4DeployOrder @deployArgs
    foreach ($result in @($deployResults)) { $results.Add($result) }
}

$workspaceFailure = @($results | Where-Object { $_.id -eq 'deploy-workspace' -and $_.status -eq 'Fail' }).Count -gt 0
$supercomputerFailure = @($results | Where-Object { $_.id -eq 'deploy-supercomputer' -and $_.status -eq 'Fail' }).Count -gt 0
$recoveryCommand = ''
if ($workspaceFailure -and -not $supercomputerFailure) {
    $resourceGroup = Get-DeploymentResourceGroup -Config $cfg
    $workspace = Get-ConfigName -Config $cfg -Name 'workspace' -Default ''
    if ($resourceGroup -and $workspace) {
        $recoveryCommand = "pwsh -NoProfile -File `"$PSCommandPath`" -ConfigPath `"$ConfigPath`" -Recovery -Subscription `"$($cfg.subscriptionId)`" -ResourceGroup `"$resourceGroup`" -Workspace `"$workspace`""
        $results.Add((New-CheckResult -Id 'workspace-recovery-offer' -Name 'workspace-only failure recovery' -Status 'Warn' -Fr 'FR4.5' `
                    -Detail "Workspace-only failure detected. Recovery command: $recoveryCommand" `
                    -Remediation 'Run the targeted stage4_deploy.ps1 -Recovery command after confirming the supercomputer is Succeeded.'))
    }
}

$extra = [pscustomobject]@{
    apiVersion      = '2026-06-01'
    bicepPath       = $BicepPath
    parametersPath  = $ParametersPath
    readinessReport = $ReadinessReport
    recoveryCommand = $recoveryCommand
}

if ($PassThru) { return $results.ToArray() }
$null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · Discovery deployment (FR4.1-FR4.6)' -JsonPath $JsonPath -Extra $extra
Complete-Stage -Results $results.ToArray()
