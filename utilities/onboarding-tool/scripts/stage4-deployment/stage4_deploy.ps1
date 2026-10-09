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
    [string[]]$ReadinessReport,
    [switch]$Recovery,
    [string]$Subscription,
    [string]$ResourceGroup,
    [string]$Workspace
)
Import-Module (Join-Path $PSScriptRoot '..\lib\OnboardingCommon.psm1') -Force
$script:DiscoveryApiVersion = '2026-06-01'

function Get-WorkspacePublicNetworkAccess {
    param([object]$Config)
    $ws = if ($Config -and $Config.PSObject.Properties.Name -contains 'workspace') { $Config.workspace } else { $null }
    $v = if ($ws -and $ws.PSObject.Properties.Name -contains 'publicNetworkAccess') { [string]$ws.publicNetworkAccess } else { '' }
    if ($v -in @('Enabled', 'Disabled')) { return $v }
    return 'Enabled'
}

function Get-WorkspaceNetworkIsolation {
    param([object]$Config)
    $ws = if ($Config -and $Config.PSObject.Properties.Name -contains 'workspace') { $Config.workspace } else { $null }
    if ($ws -and $ws.PSObject.Properties.Name -contains 'networkIsolation' -and $null -ne $ws.networkIsolation) {
        return [bool]$ws.networkIsolation
    }
    return $true
}

function Resolve-DiscoveryError {
    [CmdletBinding()]
    param([Parameter(Mandatory)][AllowEmptyString()][string]$ErrorText)

    $text = $ErrorText
    $rules = @(
        [pscustomobject]@{
            Signature   = 'Insufficient model TPM quota (InsufficientQuota on Cognitive Services deployment)'
            RootCause   = 'the workspace provisions its own model deployment (gpt-5.4 GlobalStandard, 250K TPM) in its managed Foundry account, and the subscription does not have that much free TPM quota in the workload region'
            Remediation = 'free or request TPM quota for the model named in the error in the workload region (Foundry portal > Quotas, or delete unused deployments), then re-run Stage 4 to re-PUT the workspace; if it stays Failed, delete the workspace and re-run with a new workspace name. Stage 1 check model-quota reports the shortfall up front'
            Match       = { param($t) $t -match '(?is)InsufficientQuota|Tokens Per Minute' }
        }
        [pscustomobject]@{
            Signature   = 'Insufficient VM quota (VmSkuQuota)'
            RootCause   = 'the subscription does not have enough vCPU quota in the region for the supercomputer system pool (3 nodes of the system SKU) that the service validates at submit time'
            Remediation = 'request a quota increase for the quota named in the error (Total Regional vCPUs and/or the VM family) in the deployment region via Subscriptions > Usage + quotas or az quota update, wait for it to be approved, then re-run Stage 4; Stage 1 check vcpu-quota reports the shortfall up front'
            Match       = { param($t) $t -match '(?is)VmSkuQuota|Insufficient quota for VM size|QuotaExceeded|OperationNotAllowed.*quota' }
        }
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
            Signature   = 'Supercomputer InternalServerError (target=internalMetadata)'
            RootCause   = 'the supercomputer failed before AKS was created (managed resource group left empty); observed when (a) the managedcluster subnet carries a Microsoft.ContainerService/managedClusters delegation or is also passed as managementSubnetId, or (b) the UAMI lacks its required roles'
            Remediation = 'confirm the FR4.1 subnet-topology check passes (managedcluster subnet undelegated; a separate delegated management subnet only for UserDefinedRouting) and the managed identity role check passes (Discovery Platform Contributor, Storage Blob Data Contributor, AcrPull on the deployment RG; Network Contributor on the supercomputer subnets or their VNet), wait 5-10 minutes for role propagation, delete the Failed supercomputer (az resource delete --ids <supercomputer id> --api-version 2026-06-01), then re-run Stage 4; if both are already correct, open a support case with the correlation id'
            Match       = { param($t) $t -match '(?is)InternalServerError.*internalMetadata|internalMetadata.*InternalServerError' }
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

function Get-FailedDeploymentError {
    <#
    .SYNOPSIS Drill into a Failed ARM deployment and return the real per-resource error(s).
    .DESCRIPTION
        'az deployment group create' surfaces only a generic "At least one resource deployment
        operation failed" wrapper. The authoritative error (code/message/target) lives in the
        per-resource deployment operations' statusMessage. This pulls those out so the user sees
        the real RP error (e.g. InternalServerError on the supercomputer) instead of the wrapper.
    #>
    param([Parameter(Mandatory)][string]$ResourceGroup, [Parameter(Mandatory)][string]$DeploymentName)
    $parts = @()
    $ops = Get-AzJson -Args @('deployment', 'operation', 'group', 'list', '-g', $ResourceGroup, '-n', $DeploymentName) -AllowFail
    foreach ($op in @($ops)) {
        $p = $op.properties
        if (-not $p -or "$($p.provisioningState)" -ne 'Failed') { continue }
        $sm = $p.statusMessage
        if (-not $sm) { continue }
        $errObj = if ($sm.PSObject.Properties.Name -contains 'error') { $sm.error } else { $sm }
        $code = "$($errObj.code)".Trim()
        $msg = "$($errObj.message)".Trim()
        if (-not $code -and -not $msg) { continue }
        $line = (@("[$code]", $msg) | Where-Object { $_ -and $_ -ne '[]' }) -join ' '
        # RP validation wrappers ("Resource payload validation failed") carry the actionable cause
        # in error.details[]; append those so the user sees e.g. the quota shortfall.
        $inner = @(@($errObj.details) | Where-Object { $_ } | ForEach-Object {
                $dc = "$($_.code)".Trim(); $dm = "$($_.message)".Trim(); $dt = "$($_.target)".Trim()
                if ($dm) { (@("[$(if ($dt) { $dt } else { $dc })]", $dm) | Where-Object { $_ -ne '[]' }) -join ' ' }
            })
        if ($inner.Count) { $line = "$($line): $($inner -join '; ')" }
        $target = "$($errObj.target)".Trim()
        if ($target) { $line = "$line (target=$target)" }
        $resId = "$($p.targetResource.id)".Trim()
        if ($resId) { $line = "$line [resource=$resId]" }
        $parts += $line
    }
    return ($parts | Select-Object -Unique) -join ' | '
}

function Get-ManagedRgFailureText {
    <#
    .SYNOPSIS Return distinct failed-operation errors from a Discovery resource's managed RG.
    .DESCRIPTION The workspace RP reports a generic InternalServerError; the actionable cause
    (e.g. InsufficientQuota on the model deployment) is only in the managed RG activity log.
    #>
    param([string]$ResourceId)
    if (-not $ResourceId) { return '' }
    $mrg = Invoke-Az -Args @('resource', 'show', '--ids', $ResourceId, '--api-version', $script:DiscoveryApiVersion, '--query', 'properties.managedResourceGroup', '-o', 'tsv') -AllowFail
    if ([string]::IsNullOrWhiteSpace($mrg)) { return '' }
    $events = Get-AzJson -Args @('monitor', 'activity-log', 'list', '-g', $mrg.Trim(), '--offset', '6h', '--status', 'Failed') -AllowFail
    $lines = foreach ($e in @($events)) {
        $msg = "$($e.properties.statusMessage)".Trim()
        if (-not $msg) { continue }
        $res = "$($e.resourceId)".Split('/')[-1]
        "[$($e.operationName.value) $res] $msg"
    }
    return (@($lines | Select-Object -Unique) -join ' | ')
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
    $failed = @('Failed', 'Canceled', 'Cancelled', 'NotFound')
    $listState = if ($ResourceId) { Get-DiscoveryArmState -ResourceId $ResourceId } else { 'NotChecked' }
    $trueState = $listState
    $source = 'arm'

    while ($true) {
        if ($AccountName -and $ResourceGroup) {
            # FR4.3: the Foundry account only tightens the gate (catches a false ARM Succeeded);
            # it never overrides a failed or still-provisioning ARM state.
            $source = 'cognitiveservices'
            $foundryState = Get-FoundryAccountState -ResourceGroup $ResourceGroup -AccountName $AccountName
            $states = @(@($listState, $foundryState) | Where-Object { $_ -ne 'NotChecked' })
            $bad = @($states | Where-Object { $failed -contains $_ })
            $busy = @($states | Where-Object { $transient -contains $_ })
            $other = @($states | Where-Object { $_ -ne 'Succeeded' })
            $trueState = 'Succeeded'
            if ($bad.Count) { $trueState = $bad[0] } elseif ($busy.Count) { $trueState = $busy[0] } elseif ($other.Count) { $trueState = $other[0] }
        }

        if (-not ($transient -contains $trueState)) { break }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Seconds $PollSeconds
        if ($ResourceId) {
            $listState = Get-DiscoveryArmState -ResourceId $ResourceId
            if (-not ($AccountName -and $ResourceGroup)) { $trueState = $listState }
        }
    }

    $timedOut = ($transient -contains $trueState) -and (Get-Date) -ge $deadline
    $verdict = if ($timedOut) { 'Fail' } elseif ($trueState -eq 'Succeeded') { 'Pass' } else { 'Fail' }
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

# Resolve the VNet name using the same precedence Stage 2 (Get-VNetName) applies, so the
# Stage 1 -> Stage 2 -> Stage 4 flow derives identical names without a config write-back:
# network.vnetName/virtualNetworkName -> names.vnet/virtualNetwork -> vnet-<workspace>.
function Get-Stage4VNetName {
    param([object]$Config)
    $network = Get-ObjProp -Object $Config -Name 'network'
    foreach ($n in 'vnetName', 'virtualNetworkName') {
        $v = Get-ObjProp -Object $network -Name $n
        if ($v) { return [string]$v }
    }
    $names = Get-ObjProp -Object $Config -Name 'names'
    foreach ($n in 'vnet', 'virtualNetwork') {
        $v = Get-ObjProp -Object $names -Name $n
        if ($v) { return [string]$v }
    }
    $workspace = Get-ObjProp -Object $names -Name 'workspace'
    if ($workspace) { return "vnet-$workspace" }
    return ''
}

function Get-SubnetIdByRole {
    param([object]$Config, [string]$Role, [string]$ResourceGroup)
    $network = Get-ObjProp -Object $Config -Name 'network'
    $subnets = @(Get-ObjProp -Object $network -Name 'subnets')
    $subnet = $subnets | Where-Object { (Resolve-SubnetRole (Get-ObjProp -Object $_ -Name 'role')) -eq $Role } | Select-Object -First 1
    if (-not $subnet) { return '' }
    $id = Get-ObjProp -Object $subnet -Name 'id'
    if ($id) { return [string]$id }
    $vnetName = Get-ObjProp -Object $subnet -Name 'vnetName'
    if (-not $vnetName) { $vnetName = Get-ObjProp -Object $network -Name 'vnetName' }
    if (-not $vnetName) { $vnetName = Get-Stage4VNetName -Config $Config }
    # Mirror Stage 2 (Get-SubnetName): explicit name/subnetName, else snet-<role>.
    $name = Get-ObjProp -Object $subnet -Name 'name'
    if (-not $name) { $name = Get-ObjProp -Object $subnet -Name 'subnetName' }
    if (-not $name) { $name = "snet-$Role" }
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
        # Mirror Stage 2's storage-RG precedence (storage.resourceGroup/resourceGroupName,
        # then the network RG). Stage 1 normally writes storage.accountId, so this is a fallback.
        $storageRg = Get-ObjProp -Object $storage -Name 'resourceGroup'
        if (-not $storageRg) { $storageRg = Get-ObjProp -Object $storage -Name 'resourceGroupName' }
        if (-not $storageRg) {
            $network = Get-ObjProp -Object $Config -Name 'network'
            foreach ($n in 'networkResourceGroup', 'resourceGroup', 'rg') {
                $v = Get-ObjProp -Object $network -Name $n
                if ($v) { $storageRg = $v; break }
            }
        }
        if (-not $storageRg) { $storageRg = $ResourceGroup }
        return "/subscriptions/$($Config.subscriptionId)/resourceGroups/$storageRg/providers/Microsoft.Storage/storageAccounts/$account"
    }
    return ''
}

function Grant-FoundryUserOnManagedRg {
    <#
    .SYNOPSIS Assign Foundry User on the workspace managed RG (Learn quickstart step 5).
    .DESCRIPTION The managed RG only exists after the workspace is created, so Stage 2 cannot
    grant this. Targets config principals with a Platform Administrator/Contributor role, else the
    deploying identity. Failures are Warn: the platform is deployed, only Foundry portal edits break.
    #>
    param([object]$Config, [string]$WorkspaceId)
    $foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
    $mrg = Invoke-Az -Args @('resource', 'show', '--ids', $WorkspaceId, '--api-version', $script:DiscoveryApiVersion, '--query', 'properties.managedResourceGroup', '-o', 'tsv') -AllowFail
    $mrg = "$mrg".Trim()
    if ($mrg -match '/resourceGroups/([^/]+)') { $mrg = $Matches[1] }
    if (-not $mrg) {
        return @(New-CheckResult -Id 'foundry-user-mrg' -Name 'Foundry User on workspace managed RG' -Status 'Warn' -Fr 'FR4.1' `
                -Detail "Could not read properties.managedResourceGroup from $WorkspaceId, so Foundry User was not assigned." `
                -Remediation 'Find the managed resource group on the workspace overview page and assign Foundry User to the users who edit agents and workflows in the Foundry portal.')
    }
    $scope = "/subscriptions/$($Config.subscriptionId)/resourceGroups/$mrg"

    $principals = @()
    $cfgPrincipals = Get-ObjProp -Object $Config -Name 'principals'
    foreach ($p in @($cfgPrincipals)) {
        if (-not $p) { continue }
        $role = [string](@((Get-ObjProp -Object $p -Name 'role'), (Get-ObjProp -Object $p -Name 'roleName'), (Get-ObjProp -Object $p -Name 'discoveryRole')) | Where-Object { $_ } | Select-Object -First 1)
        $oid = [string](@((Get-ObjProp -Object $p -Name 'objectId'), (Get-ObjProp -Object $p -Name 'principalId'), (Get-ObjProp -Object $p -Name 'id')) | Where-Object { $_ } | Select-Object -First 1)
        if ($oid -and $role -match '^Platform[ -]?(Administrator|Contributor)$') {
            $principals += [pscustomobject]@{ ObjectId = $oid; Type = [string](Get-ObjProp -Object $p -Name 'type') }
        }
    }
    if (-not $principals.Count) {
        $deployer = Get-ObjProp -Object $Config -Name 'deployingIdentity'
        $oid = Get-ObjProp -Object $deployer -Name 'objectId'
        if ($oid) { $principals += [pscustomobject]@{ ObjectId = [string]$oid; Type = [string](Get-ObjProp -Object $deployer -Name 'type') } }
    }
    if (-not $principals.Count) {
        return @(New-CheckResult -Id 'foundry-user-mrg' -Name 'Foundry User on workspace managed RG' -Status 'Warn' -Fr 'FR4.1' `
                -Detail "No principals or deployingIdentity.objectId in config, so Foundry User was not assigned on $mrg." `
                -Remediation "Assign Foundry User on $scope to the users who edit agents and workflows in the Foundry portal.")
    }

    $out = @()
    foreach ($pr in $principals) {
        $id = "foundry-user-mrg-$($pr.ObjectId)"
        $data = [pscustomobject]@{ principal = $pr.ObjectId; role = 'Foundry User'; roleDefinitionId = $foundryUserRoleId; scope = $scope }
        $exists = Get-AzJson -Args @('role', 'assignment', 'list', '--assignee', $pr.ObjectId, '--role', $foundryUserRoleId, '--scope', $scope) -AllowFail
        if ($exists -and @($exists).Count) {
            $out += New-CheckResult -Id $id -Name 'Foundry User on workspace managed RG' -Status 'Pass' -Fr 'FR4.1' -Detail "Already assigned to $($pr.ObjectId) on $mrg." -Data $data
            continue
        }
        $azArgs = @('role', 'assignment', 'create', '--assignee-object-id', $pr.ObjectId, '--role', $foundryUserRoleId, '--scope', $scope)
        $ptype = switch -Regex ($pr.Type) { '^user$' { 'User' } 'servicePrincipal|managedIdentity' { 'ServicePrincipal' } 'group' { 'Group' } default { $null } }
        if ($ptype) { $azArgs += @('--assignee-principal-type', $ptype) }
        try {
            Invoke-Az -Args $azArgs | Out-Null
            $out += New-CheckResult -Id $id -Name 'Foundry User on workspace managed RG' -Status 'Pass' -Fr 'FR4.1' -Detail "Assigned to $($pr.ObjectId) on $mrg." -Data $data
        }
        catch {
            $out += New-CheckResult -Id $id -Name 'Foundry User on workspace managed RG' -Status 'Warn' -Fr 'FR4.1' `
                -Detail "Could not assign Foundry User to $($pr.ObjectId) on ${mrg}: $($_.Exception.Message)" `
                -Remediation "Have an Owner or User Access Administrator run: az role assignment create --assignee-object-id $($pr.ObjectId) --role $foundryUserRoleId --scope $scope" `
                -Data $data
        }
    }
    return $out
}

# Discover the workspace's managed AI Foundry (CognitiveServices) account so FR4.3 can verify
# its true-state even when the config omits foundry.accountName/resourceGroup. Returns $null when
# the managed RG or account can't be located (caller then degrades the gate to Warn).
function Get-WorkspaceFoundryAccount {
    param([string]$WorkspaceId, [object]$Config)
    $ws = Get-AzJson -Args @('resource', 'show', '--ids', $WorkspaceId, '--api-version', $script:DiscoveryApiVersion) -AllowFail
    $managedRg = ''
    $wsProps = if ($ws) { Get-ObjProp -Object $ws -Name 'properties' } else { $null }
    if ($wsProps) {
        foreach ($p in 'managedResourceGroupId', 'managedResourceGroup') {
            $v = Get-ObjProp -Object $wsProps -Name $p
            if ($v) {
                if ($v -match '/resourceGroups/([^/]+)') { $managedRg = $Matches[1] } else { $managedRg = [string]$v }
                break
            }
        }
    }
    if (-not $managedRg) {
        $wsName = Get-ConfigName -Config $Config -Name 'workspace' -Default ''
        if ($wsName) {
            $groups = Get-AzJson -Args @('group', 'list', '--query', "[?starts_with(name, 'mrg-dwsp-$wsName')].name") -AllowFail
            if ($groups -and @($groups).Count) { $managedRg = [string]@($groups)[0] }
        }
    }
    if (-not $managedRg) { return $null }
    $accounts = Get-AzJson -Args @('cognitiveservices', 'account', 'list', '-g', $managedRg) -AllowFail
    if (-not $accounts) { return $null }
    $match = @($accounts | Where-Object { $_.kind -in @('AIServices', 'OpenAI', 'CognitiveServices') } | Select-Object -First 1)
    if (-not $match.Count) { $match = @($accounts | Select-Object -First 1) }
    if (-not $match.Count) { return $null }
    return [pscustomobject]@{ accountName = [string]$match[0].name; resourceGroup = $managedRg }
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
    if ([string]::IsNullOrWhiteSpace($ResourceId)) {
        $why = "Internal tool error: the resource id for '$Name' was not computed, so its provisioning state could not be checked. The Azure deployment itself may have succeeded."
        return New-CheckResult -Id $Id -Name $Name -Status 'Fail' -Fr $Fr -Detail $why `
            -Remediation 'Check the resource in the Azure portal (or az resource show), and report this tool defect with the Stage 4 console log; re-running Stage 4 resumes from existing resources.' `
            -Data ([pscustomobject]@{ resource = ''; provisioningState = 'NotChecked'; rawError = $ErrorText; extra = $Extra })
    }
    $ok = $State -eq 'Succeeded'
    $resolved = if ($ok) { $null } else { Resolve-DiscoveryError -ErrorText $ErrorText }
    $detail = "resource=$ResourceId provisioningState=$State"
    if (-not $ok -and $resolved) { $detail = "$detail remediationMatch=$($resolved.errorSignature)" }
    if (-not $ok -and $ErrorText) {
        $clean = ($ErrorText -replace '\s+', ' ').Trim()
        if ($clean.Length -gt 500) { $clean = $clean.Substring(0, 500) + '...' }
        $detail = "$detail error=$clean"
    }
    New-CheckResult -Id $Id -Name $Name -Status ($ok ? 'Pass' : 'Fail') -Fr $Fr -Detail $detail `
        -Remediation ($ok ? '' : $resolved.remediation) `
        -Data ([pscustomobject]@{ resource = $ResourceId; provisioningState = $State; remediation = $resolved; rawError = $ErrorText; extra = $Extra })
}

function Invoke-BicepDeploymentOnce {
    param([string]$ResourceGroup, [string]$TemplateFile, [string]$ParameterFile)
    if (-not $TemplateFile) { return [pscustomobject]@{ ok = $true; error = '' } }
    if (-not (Test-Path -LiteralPath $TemplateFile)) { return [pscustomobject]@{ ok = $false; error = "BicepPath not found: $TemplateFile" } }
    $deploymentName = "stage4-$(Get-Date -Format yyyyMMddHHmmss)"
    $args = @('deployment', 'group', 'create', '-g', $ResourceGroup, '--name', $deploymentName, '--template-file', $TemplateFile)
    if ($ParameterFile) {
        if (-not (Test-Path -LiteralPath $ParameterFile)) { return [pscustomobject]@{ ok = $false; error = "ParametersPath not found: $ParameterFile" } }
        $args += @('--parameters', "@$ParameterFile")
    }
    try {
        Invoke-Az -Args $args | Out-Null
        return [pscustomobject]@{ ok = $true; error = '' }
    } catch {
        $detail = Get-FailedDeploymentError -ResourceGroup $ResourceGroup -DeploymentName $deploymentName
        $msg = if ($detail) { $detail } else { $_.Exception.Message }
        return [pscustomobject]@{ ok = $false; error = $msg }
    }
}

function New-Stage4BicepParamFile {
    param([object]$Config, [string]$ResourceGroup, [string]$Location)

    $names = Get-ObjProp -Object $Config -Name 'names'
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
        publicNetworkAccess     = Get-WorkspacePublicNetworkAccess -Config $Config
        networkIsolation        = Get-WorkspaceNetworkIsolation -Config $Config
    }
    foreach ($opt in 'systemSku', 'nodePoolVmSize', 'nodePoolScaleSetPriority') {
        $v = Get-ObjProp -Object $Config -Name $opt
        if ($v) { $p[$opt] = [string]$v }
    }
    $net = Get-ObjProp -Object $Config -Name 'network'
    $outboundType = Get-ObjProp -Object $net -Name 'outboundType'
    if ($outboundType) { $p['outboundType'] = [string]$outboundType }
    if (-not $outboundType -or [string]$outboundType -eq 'UserDefinedRouting') {
        $mgmt = Get-SubnetIdByRole -Config $Config -Role 'spare' -ResourceGroup $ResourceGroup
        if ($mgmt) { $p['managementSubnetId'] = $mgmt }
    }
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
if ([string]::IsNullOrWhiteSpace($managedIdentityId)) {
    $results.Add((New-CheckResult -Id 'deploy-managed-identity' -Name 'deployment managed identity' -Status 'Fail' -Fr 'FR4.1' `
                -Detail 'Config does not include managedIdentity.id; the platform template requires a pre-existing user-assigned managed identity.' `
                -Remediation 'Pre-create a user-assigned managed identity (a prerequisite the tool does not provision) and set managedIdentity.id in the onboarding config before running Stage 4; the Bicep identity parameter is mandatory and cannot be empty.'))
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

# UAMI pre-flight: the id is set, so verify it resolves to a real identity and surface its
# role coverage. The tool does not create the UAMI or assign its roles (prerequisites), so a
# missing identity is a hard Fail while missing/unreadable roles are a Warn (deploy can submit,
# but AKS/workspace may fail at runtime without the right roles).
$uami = Get-AzJson -Args @('identity', 'show', '--ids', $managedIdentityId) -AllowFail
$uamiPrincipalId = if ($uami) { [string]$uami.principalId } else { '' }
if (-not $uami -or [string]::IsNullOrWhiteSpace($uamiPrincipalId)) {
    $results.Add((New-CheckResult -Id 'deploy-managed-identity-exists' -Name 'managed identity exists' -Status 'Fail' -Fr 'FR4.1' `
                -Detail "managedIdentity.id does not resolve to an existing user-assigned managed identity: $managedIdentityId" `
                -Remediation 'Create the user-assigned managed identity (az identity create) so the resource id in managedIdentity.id exists, or correct the id in the config. The platform identity parameter must reference an existing UAMI.' `
                -Data ([pscustomobject]@{ managedIdentityId = $managedIdentityId; resolved = $false })))
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}
$results.Add((New-CheckResult -Id 'deploy-managed-identity-exists' -Name 'managed identity exists' -Status 'Pass' -Fr 'FR4.1' `
            -Detail "UAMI resolves (principalId=$uamiPrincipalId)." `
            -Data ([pscustomobject]@{ managedIdentityId = $managedIdentityId; principalId = $uamiPrincipalId; resolved = $true })))
$uamiRolesRaw = Invoke-Az -Args @('role', 'assignment', 'list', '--assignee', $uamiPrincipalId, '--all', '-o', 'json') -AllowFail
$uamiRoles = $null
if (-not [string]::IsNullOrWhiteSpace($uamiRolesRaw)) {
    # -NoEnumerate keeps an empty '[]' as an empty array instead of collapsing to $null (= unreadable).
    try { $uamiRoles = $uamiRolesRaw | ConvertFrom-Json -NoEnumerate } catch { $uamiRoles = $null }
}
if ($null -eq $uamiRoles) {
    $results.Add((New-CheckResult -Id 'deploy-managed-identity-roles' -Name 'managed identity role assignments' -Status 'Warn' -Fr 'FR4.1' `
                -Detail 'Could not read role assignments for the UAMI (insufficient permission to list role assignments, or a transient error); UAMI role coverage was not verified.' `
                -Remediation 'Verify manually that the UAMI holds Microsoft Discovery Platform Contributor, Storage Blob Data Contributor and AcrPull on the deployment resource group, plus Network Contributor on the managedcluster and nodepool subnets (or their VNet), then proceed.' `
                -Data ([pscustomobject]@{ principalId = $uamiPrincipalId; verified = $false })))
}
else {
    # Minimum UAMI roles per "Configure managed identities for Microsoft Discovery" (Learn):
    # three core roles on the deployment RG, plus Network Contributor on the VNet that hosts the
    # supercomputer subnets (the AKS cluster identity must join them).
    $rgScope = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup"
    $scNetRoles = @('managedcluster', 'nodepool')
    $uamiOutbound = [string](Get-ObjProp -Object (Get-ObjProp -Object $cfg -Name 'network') -Name 'outboundType')
    if (-not $uamiOutbound -or $uamiOutbound -eq 'UserDefinedRouting') { $scNetRoles += 'spare' }
    $scSubnetScopes = @($scNetRoles | ForEach-Object { Get-SubnetIdByRole -Config $cfg -Role $_ -ResourceGroup $resourceGroup } | Where-Object { $_ } | Select-Object -Unique)
    $ownerId = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'; $contributorId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
    $requiredUamiRoles = @(
        [pscustomobject]@{ name = 'Microsoft Discovery Platform Contributor'; id = '01288891-85ee-45a7-b367-9db3b752fc65'; scope = $rgScope; accepts = @() }
        [pscustomobject]@{ name = 'Storage Blob Data Contributor'; id = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'; scope = $rgScope; accepts = @() }
        [pscustomobject]@{ name = 'AcrPull'; id = '7f951dda-4ed3-4680-a7ca-43fe172d538d'; scope = $rgScope; accepts = @() }
    )
    # Network Contributor is needed on each supercomputer subnet; a grant on the VNet, network RG or
    # subscription covers it. (The service self-assigns it on the managedcluster subnet only.)
    foreach ($sn in $scSubnetScopes) {
        $requiredUamiRoles += [pscustomobject]@{ name = 'Network Contributor'; id = '4d97b98b-1d4f-4787-a291-c67834d212e7'; scope = $sn; accepts = @($contributorId, $ownerId) }
    }
    $missingRoles = [System.Collections.Generic.List[object]]::new()
    foreach ($req in $requiredUamiRoles) {
        # An assignment satisfies the requirement when it is the same (or an accepted superset) role
        # at the required scope or any ancestor scope (subscription / RG / VNet).
        $ok = @($uamiRoles | Where-Object {
                $defId = ([string]$_.roleDefinitionId -split '/')[-1]
                $s = ([string]$_.scope).TrimEnd('/')
                ($defId -eq $req.id -or $req.accepts -contains $defId) -and
                ($req.scope -ieq $s -or $req.scope.StartsWith("$s/", [System.StringComparison]::OrdinalIgnoreCase))
            }).Count -gt 0
        if (-not $ok) { $missingRoles.Add($req) }
    }
    $roleSummary = @($uamiRoles | ForEach-Object { [pscustomobject]@{ role = $_.roleDefinitionName; scope = $_.scope } })
    if ($missingRoles.Count -gt 0) {
        $cmds = ($missingRoles | ForEach-Object { "az role assignment create --assignee-object-id $uamiPrincipalId --assignee-principal-type ServicePrincipal --role $($_.id) --scope $($_.scope)" }) -join ' ; '
        $results.Add((New-CheckResult -Id 'deploy-managed-identity-roles' -Name 'managed identity role assignments' -Status 'Fail' -Fr 'FR4.1' `
                    -Detail ("The UAMI is missing $($missingRoles.Count) required role(s): " + (($missingRoles | ForEach-Object { "$($_.name) on $($_.scope)" }) -join '; ') + ". The supercomputer's AKS cluster/kubelet/workload identities and the workspace all run as this UAMI; without these roles the supercomputer fails a few minutes after submit with an opaque 'InternalServerError (target=internalMetadata)' and must be deleted before retrying. Role assignments currently held: $(@($uamiRoles).Count).") `
                    -Remediation "Ask an Owner / User Access Administrator to assign the missing roles, wait 5-10 minutes for propagation, then re-run Stage 4: $cmds" `
                    -Data ([pscustomobject]@{ principalId = $uamiPrincipalId; missing = @($missingRoles | ForEach-Object { [pscustomobject]@{ role = $_.name; roleId = $_.id; scope = $_.scope } }); roleAssignments = $roleSummary })))
        # Stop before submitting: a role-less supercomputer burns minutes, then must be deleted by hand.
        if ($PassThru) { return $results.ToArray() }
        $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
        Complete-Stage -Results $results.ToArray()
    }
    else {
        $results.Add((New-CheckResult -Id 'deploy-managed-identity-roles' -Name 'managed identity role assignments' -Status 'Pass' -Fr 'FR4.1' `
                    -Detail ("UAMI holds all required roles: " + (($requiredUamiRoles | ForEach-Object { "$($_.name) on $($_.scope)" }) -join '; ') + '.') `
                    -Data ([pscustomobject]@{ principalId = $uamiPrincipalId; roleAssignments = $roleSummary })))
    }
}
$workspaceId = New-DiscoveryId -SubscriptionId $subscriptionId -ResourceGroup $resourceGroup -TypePath 'workspaces' -NamePath $workspaceName
$supercomputerId = if ($supercomputerName) { New-DiscoveryId -SubscriptionId $subscriptionId -ResourceGroup $resourceGroup -TypePath 'supercomputers' -NamePath $supercomputerName } else { '' }
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
    # Subnet-topology pre-flight. Supercomputer system nodes join the managedcluster subnet, so it must
    # carry no delegation; with UserDefinedRouting the API server needs a separate management subnet
    # ('spare' role / managementSubnet) delegated to Microsoft.ContainerService/managedClusters.
    # Either mistake surfaces only minutes later as an opaque InternalServerError (target=internalMetadata).
    $mgmtDeleg = 'Microsoft.ContainerService/managedClusters'
    $topoIssues = [System.Collections.Generic.List[string]]::new()
    $topoFixes = [System.Collections.Generic.List[string]]::new()
    if ($preflightSubnet) {
        $scSn = Get-AzJson -Args @('network', 'vnet', 'subnet', 'show', '--ids', $preflightSubnet) -AllowFail
        $scDel = @($scSn.delegations | ForEach-Object { $_.serviceName } | Where-Object { $_ })
        if ($scDel.Count) {
            $topoIssues.Add("managedcluster subnet $($scSn.name) is delegated to $($scDel -join ','); the supercomputer system nodes run in this subnet, so it must not be delegated.")
            $topoFixes.Add("az network vnet subnet update --ids $preflightSubnet --remove delegations")
        }
    }
    $preOutbound = [string](Get-ObjProp -Object (Get-ObjProp -Object $cfg -Name 'network') -Name 'outboundType')
    if (-not $preOutbound -or $preOutbound -eq 'UserDefinedRouting') {
        $mgmtId = Get-SubnetIdByRole -Config $cfg -Role 'spare' -ResourceGroup $resourceGroup
        $mgmtSn = if ($mgmtId) { Get-AzJson -Args @('network', 'vnet', 'subnet', 'show', '--ids', $mgmtId) -AllowFail } else { $null }
        if (-not $mgmtSn) {
            $topoIssues.Add("outboundType=UserDefinedRouting requires a management subnet (role 'managementSubnet'/'spare', at least /28) for the AKS API server, but none was found$(if ($mgmtId) { " at $mgmtId" }).")
            $topoFixes.Add("Add a managementSubnet row (delegation $mgmtDeleg) to the form and re-run Stages 1-3, or set network.outboundType=LoadBalancer")
        }
        elseif (@($mgmtSn.delegations | ForEach-Object { $_.serviceName }) -notcontains $mgmtDeleg) {
            $topoIssues.Add("management subnet $($mgmtSn.name) is not delegated to $mgmtDeleg (required for API-server VNet integration under UserDefinedRouting).")
            $topoFixes.Add("az network vnet subnet update --ids $mgmtId --delegations $mgmtDeleg")
        }
    }
    if ($topoIssues.Count) {
        $results.Add((New-CheckResult -Id 'deploy-subnet-topology' -Name 'supercomputer subnet topology' -Status 'Fail' -Fr 'FR4.1' `
                    -Detail (($topoIssues -join ' ') + ' Stage 4 stopped before submitting so no Failed supercomputer is left behind.') `
                    -Remediation ("Fix the subnets, then re-run Stage 3 and Stage 4: " + ($topoFixes -join ' ; ')) `
                    -Data ([pscustomobject]@{ issues = @($topoIssues); fixes = @($topoFixes) })))
        if ($PassThru) { return $results.ToArray() }
        $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
        Complete-Stage -Results $results.ToArray()
    }
    else {
        $results.Add((New-CheckResult -Id 'deploy-subnet-topology' -Name 'supercomputer subnet topology' -Status 'Pass' -Fr 'FR4.1' `
                    -Detail "managedcluster subnet has no delegation$(if (-not $preOutbound -or $preOutbound -eq 'UserDefinedRouting') { "; management subnet is delegated to $mgmtDeleg (UserDefinedRouting)" } else { "; outboundType=$preOutbound needs no management subnet" })."))
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
            # The platform template requires five subnet IDs. Stage 1 records role+CIDR only and
            # Stage 2 does not write names/IDs back to the config, so resolve each role with the
            # same deterministic convention Stage 2 uses (vnet-<workspace> / snet-<role>). Fail fast
            # with a clear prerequisite when any required subnet still cannot be derived.
            $requiredRoles = @('managedcluster', 'nodepool', 'agent-containerapp', 'workspace-containerapp', 'private-endpoints')
            $missingSubnets = @($requiredRoles | Where-Object { -not (Get-SubnetIdByRole -Config $cfg -Role $_ -ResourceGroup $resourceGroup) })
            if ($missingSubnets.Count) {
                $results.Add((New-CheckResult -Id 'deploy-subnet-ids' -Name 'deployment subnet ids' -Status 'Fail' -Fr 'FR4.1' `
                            -Detail "Could not resolve required subnet id(s) for role(s): $($missingSubnets -join ', ')." `
                            -Remediation 'Run Stage 2 to provision the landing-zone network (it names subnets vnet-<workspace>/snet-<role>), or set network.vnetName and per-subnet name/id in the config so Stage 4 can build the platform parameters.' `
                            -Data ([pscustomobject]@{ missingRoles = $missingSubnets })))
                if ($PassThru) { return $results.ToArray() }
                $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
                Complete-Stage -Results $results.ToArray()
            }
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
    $scOutbound = [string](Get-ObjProp -Object (Get-ObjProp -Object $cfg -Name 'network') -Name 'outboundType')
    $scMgmtSubnet = if (-not $scOutbound -or $scOutbound -eq 'UserDefinedRouting') { Get-SubnetIdByRole -Config $cfg -Role 'spare' -ResourceGroup $resourceGroup } else { '' }
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
        $scNet = Get-ObjProp -Object $cfg -Name 'network'
        $scOutboundType = Get-ObjProp -Object $scNet -Name 'outboundType'
        if (-not $scOutboundType) { $scOutboundType = 'UserDefinedRouting' }
        $scBody = @{
            location   = $location
            tags       = @{ version = 'v2'; 'discovery.overridemrgregion' = [string]$cfg.workloadRegion }
            properties = @{
                subnetId           = $scSubnet
                outboundType       = [string]$scOutboundType
                identities         = @{
                    clusterIdentity    = @{ id = $managedIdentityId }
                    kubeletIdentity    = @{ id = $managedIdentityId }
                    workloadIdentities = @{ $managedIdentityId = @{} }
                }
            }
        }
        $systemSku = Get-ObjProp -Object $cfg -Name 'systemSku'
        if ($scMgmtSubnet) { $scBody.properties.managementSubnetId = $scMgmtSubnet }
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
                    NetworkIsolation                             = (Get-WorkspaceNetworkIsolation -Config $cfg).ToString().ToLowerInvariant()
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
                    publicNetworkAccess    = Get-WorkspacePublicNetworkAccess -Config $cfg
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
        if (-not ($foundryAccount -and $foundryRg)) {
            $discovered = Get-WorkspaceFoundryAccount -WorkspaceId $workspaceId -Config $cfg
            if ($discovered) { $foundryAccount = $discovered.accountName; $foundryRg = $discovered.resourceGroup }
        }
        $gate = Wait-DiscoveryGate -ResourceId $workspaceId -FoundryAccountName $foundryAccount -FoundryResourceGroup $foundryRg
        $state = $gate.trueState -replace '^TimedOut:', ''
        if (-not ($foundryAccount -and $foundryRg) -and $state -eq 'Succeeded') {
            # FR4.3 managed Foundry true-state could not be verified; don't pass on workspace ARM state alone.
            $results.Add((New-CheckResult -Id 'deploy-workspace' -Name 'workspace deployment' -Status 'Warn' -Fr 'FR4.1,FR4.3' `
                        -Detail "resource=$workspaceId provisioningState=$state foundryTrueState=unverified (no foundry.accountName/resourceGroup and managed Foundry account not discoverable)" `
                        -Remediation 'Set foundry.accountName and foundry.resourceGroup (the managed AI Foundry/CognitiveServices account) so FR4.3 can verify the workspace dependency true-state.' `
                        -Data $gate))
        } else {
            $wsError = $put.error
            if ($state -ne 'Succeeded') {
                $mrgErr = Get-ManagedRgFailureText -ResourceId $workspaceId
                if ($mrgErr) { $wsError = (@("managedRG: $mrgErr", $wsError) | Where-Object { $_ }) -join ' | ' }
            }
            $results.Add((New-StepResult -Id 'deploy-workspace' -Name 'workspace deployment' -ResourceId $workspaceId -State $state -Fr 'FR4.1,FR4.3' -ErrorText $wsError -Extra $gate))
        }
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

$storageAccountId = Get-StorageAccountId -Config $cfg -ResourceGroup $resourceGroup
if ($storageAccountId) {
    $storageBody = @{ location = $location; properties = @{ storageStore = @{ kind = 'AzureStorageBlob'; storageAccountId = $storageAccountId } } }
    $storagePut = Invoke-ArmPut -ResourceId $storageContainerId -Body $storageBody
    $storageGate = Wait-DiscoveryGate -ResourceId $storageContainerId
    $storageState = $storageGate.trueState -replace '^TimedOut:', ''
    $results.Add((New-StepResult -Id 'deploy-project-storage' -Name 'project storage container' -ResourceId $storageContainerId -State $storageState -Fr 'FR4.1' -ErrorText $storagePut.error -Extra $storageGate))
}
else {
    $results.Add((New-CheckResult -Id 'deploy-project-storage' -Name 'project storage container' -Status 'Fail' -Fr 'FR4.1' `
                -Detail "resource=$storageContainerId provisioningState=NotSubmitted missing=storage.accountId or storage.account" `
                -Remediation 'Supply the storage account id/name required for every Discovery project storage container.' `
                -Data ([pscustomobject]@{ resource = $storageContainerId; provisioningState = 'NotSubmitted' })))
}

if (@($results | Where-Object { $_.id -eq 'deploy-project-storage' -and $_.status -eq 'Fail' }).Count) {
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

$projectBody = @{ location = $location; properties = @{ storageContainerIds = @($storageContainerId) } }
$projectPut = Invoke-ArmPut -ResourceId $projectId -Body $projectBody
$projectGate = Wait-DiscoveryGate -ResourceId $projectId
$projectState = $projectGate.trueState -replace '^TimedOut:', ''
$results.Add((New-StepResult -Id 'deploy-project' -Name 'Discovery project' -ResourceId $projectId -State $projectState -Fr 'FR4.1' -ErrorText $projectPut.error -Extra $projectGate))

if (@($results | Where-Object { $_.id -eq 'deploy-project' -and $_.status -eq 'Fail' }).Count) {
    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 4 · deploy order (FR4.1-FR4.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

foreach ($r in @(Grant-FoundryUserOnManagedRg -Config $cfg -WorkspaceId $workspaceId)) { $results.Add($r) }

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
    $detail = "resource=$ResourceId provisioningState=$State"
    if (-not $ok -and $resolved) { $detail = "$detail remediationMatch=$($resolved.errorSignature)" }
    if (-not $ok -and $ErrorText) {
        $clean = ($ErrorText -replace '\s+', ' ').Trim()
        if ($clean.Length -gt 500) { $clean = $clean.Substring(0, 500) + '...' }
        $detail = "$detail error=$clean"
    }
    New-CheckResult -Id $Id -Name $Name -Status ($ok ? 'Pass' : 'Fail') -Fr $Fr `
        -Detail $detail `
        -Remediation ($ok ? '' : $resolved.remediation) `
        -Data ([pscustomobject]@{ resource = $ResourceId; provisioningState = $State; remediation = $resolved; rawError = $ErrorText; extra = $Extra })
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
            $bodyProps.publicNetworkAccess = Get-WorkspacePublicNetworkAccess -Config $cfg
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
    if ($storageState -ne 'Succeeded') {
        $results.Add((New-CheckResult -Id 'recovery-project-storage' -Name 'post-recovery project storage' -Status 'Fail' -Fr 'FR4.5' `
                    -Detail "Storage container $storageContainerId is $storageState; a project cannot be recovered without storage." `
                    -Remediation 'Deploy or recover the project storage container, then rerun recovery.'))
    }
    else {
        $projectId = "$workspaceId/projects/$projectName"
        $projectBody = @{ location = [string]$workspaceObj.location; properties = @{ storageContainerIds = @($storageContainerId) } }
        $projectPut = Invoke-ArmPut -ResourceId $projectId -Body $projectBody
        $projectGate = Wait-DiscoveryGate -ResourceId $projectId
        $projectState = $projectGate.trueState -replace '^TimedOut:', ''
        $results.Add((New-StepResult -Id 'recovery-project' -Name 'post-recovery project' -ResourceId $projectId -State $projectState -Fr 'FR4.5' -ErrorText $projectPut.error -Extra ([pscustomobject]@{ trueState = $projectGate; storageContainerState = $storageState })))
    }
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
    $ReadinessReport = @($ReadinessReport | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $coveredProfiles = @()
    $multi = @($ReadinessReport).Count -gt 1
    foreach ($reportPath in @($ReadinessReport)) {
        $checkId = 'stage3-readiness-report'
        $checkName = 'Stage 3 readiness report'
        if ($multi) { $checkId += '-' + [IO.Path]::GetFileNameWithoutExtension($reportPath); $checkName += " ($([IO.Path]::GetFileName($reportPath)))" }
        if (-not (Test-Path -LiteralPath $reportPath)) {
            $readinessGateOpen = $false
            $results.Add((New-CheckResult -Id $checkId -Name $checkName -Status 'Fail' -Fr 'FR4.6' `
                        -Detail "Readiness report not found: $reportPath" `
                        -Remediation 'Run Stage 3 validation and pass the GO report before Stage 4 writes platform resources.'))
            continue
        }
        try {
            $readiness = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json -ErrorAction Stop
            $verdict = Get-ObjProp -Object $readiness -Name 'verdict'
            $reportProfile = [string](Get-ObjProp -Object (Get-ObjProp -Object $readiness -Name 'extra') -Name 'profile')
            if ($verdict -eq 'GO') {
                if ($reportProfile) { $coveredProfiles += $reportProfile }
                $results.Add((New-CheckResult -Id $checkId -Name $checkName -Status 'Pass' -Fr 'FR4.6' `
                            -Detail "verdict=GO profile=$reportProfile path=$reportPath"))
            } else {
                $readinessGateOpen = $false
                $results.Add((New-CheckResult -Id $checkId -Name $checkName -Status 'Fail' -Fr 'FR4.6' `
                            -Detail "verdict=$verdict profile=$reportProfile path=$reportPath" `
                            -Remediation 'Do not run Stage 4 until Stage 3 dependency validation is GO.'))
            }
        } catch {
            $readinessGateOpen = $false
            $results.Add((New-CheckResult -Id $checkId -Name $checkName -Status 'Fail' -Fr 'FR4.6' `
                        -Detail "Unable to parse readiness report: $($_.Exception.Message)" `
                        -Remediation 'Regenerate the Stage 3 JSON report and rerun Stage 4.'))
        }
    }
    if ($readinessGateOpen -and $coveredProfiles -and ('supercomputer' -notin $coveredProfiles)) {
        $results.Add((New-CheckResult -Id 'stage3-readiness-coverage' -Name 'Stage 3 profile coverage' -Status 'Warn' -Fr 'FR4.6' `
                    -Detail "The supplied Stage 3 report(s) cover profile(s) '$($coveredProfiles -join ', ')' but not 'supercomputer'. Stage 4 deploys a supercomputer first, so its subnets (managedcluster, nodepool, spare) were not validated by Stage 3. Stage 4's own subnet-topology pre-flight still runs, but NSG/route/DNS checks for those subnets were skipped." `
                    -Remediation 'Run Stage 3 with -Profile supercomputer too and pass both reports: -ReadinessReport ./out/stage3-supercomputer.json,./out/stage3-workspace.json'))
    }
} else {
    $results.Add((New-CheckResult -Id 'stage3-readiness-report' -Name 'Stage 3 readiness report' -Status 'Warn' -Fr 'FR4.6' `
                -Detail 'No -ReadinessReport was supplied, so Stage 4 cannot confirm that Stage 3 returned GO for this config; it proceeds without that gate. Network/DNS problems Stage 3 would have caught will instead surface as deployment failures.' `
                -Remediation 'Pass the Stage 3 report: -ReadinessReport ./out/stage3.json (Stage 4 then refuses to write unless that report is GO).'))
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
