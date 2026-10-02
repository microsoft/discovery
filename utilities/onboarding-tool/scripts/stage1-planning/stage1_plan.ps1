#Requires -Version 7.0
<#
.SYNOPSIS
    Stage 1 / FR1.0-FR1.8 — planning: parse the filled network-planning form and emit config.json.

.DESCRIPTION
    Single self-contained Stage 1 script. Reads the customer's filled planning spreadsheet
    (network-planning-form-template.xlsx, "Config" sheet) — or a .json config for testing —
    builds the in-memory config model, runs every embedded planning validation, and writes the
    machine-readable config.json (the single source of truth for Stages 2-5) only when all P0
    checks pass or carry a recorded waiver.

    Folds in the former sub-scripts:
      FR1.0 subscription prerequisites   FR1.1 field capture/normalization
      FR1.2 subnet sizing + delegation   FR1.3 address-space conflict
      FR1.4 region availability/capacity FR1.5 quota / SKU / TPM / Cosmos
      FR1.6 naming rules + availability   FR1.7 policy pre-flight
      FR1.8 validated config export gate

    Az-dependent checks (subscription enablement, SKU-in-region, workspace name availability)
    degrade to Warn/Skip when not logged in, so the parser and local validations run offline.

    Spec: ../../script-specs/stage1-planning/stage1_plan.md
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$FormPath,
    [string]$OutConfig,
    [string]$JsonPath,
    [switch]$PassThru
)

Import-Module (Join-Path $PSScriptRoot '..\lib\OnboardingCommon.psm1') -Force
Set-StrictMode -Version Latest

# ===========================================================================
# XLSX reader (dependency-free: xlsx = zip of XML parts)
# ===========================================================================
function Read-XlsxSheet {
    <#
    .SYNOPSIS Return a hashtable of cell values keyed by cell ref (e.g. 'A5') for one sheet.
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$SheetName
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $Path))
    try {
        function Get-Entry([string]$name) { $zip.Entries | Where-Object { $_.FullName -eq $name } | Select-Object -First 1 }
        function Read-Xml($entry) {
            if (-not $entry) { return $null }
            $sr = New-Object System.IO.StreamReader($entry.Open())
            try { [xml]$sr.ReadToEnd() } finally { $sr.Dispose() }
        }

        $wbXml = Read-Xml (Get-Entry 'xl/workbook.xml')
        $relXml = Read-Xml (Get-Entry 'xl/_rels/workbook.xml.rels')
        if (-not $wbXml -or -not $relXml) { throw "Not a valid xlsx: $Path" }

        $sheet = @($wbXml.workbook.sheets.sheet) | Where-Object { $_.name -eq $SheetName } | Select-Object -First 1
        if (-not $sheet) { throw "Sheet '$SheetName' not found in $Path (sheets: $(@($wbXml.workbook.sheets.sheet).name -join ', '))" }
        $rid = $sheet.id   # r:id attribute surfaces as .id
        $rel = @($relXml.Relationships.Relationship) | Where-Object { $_.Id -eq $rid } | Select-Object -First 1
        if (-not $rel) { throw "Could not resolve relationship for sheet '$SheetName'." }
        $target = $rel.Target -replace '^/xl/', '' -replace '^\.\./', ''
        if ($target -notmatch '^xl/') { $target = "xl/$target" }

        # shared strings
        $shared = @()
        $ssXml = Read-Xml (Get-Entry 'xl/sharedStrings.xml')
        if ($ssXml) {
            foreach ($si in $ssXml.sst.si) {
                if ($null -eq $si) { $shared += ''; continue }
                # concatenate all descendant <t> text (handles rich-text runs)
                $texts = $si.GetElementsByTagName('t')
                if ($texts.Count -gt 0) {
                    $sb = ''
                    foreach ($tn in $texts) { $sb += $tn.InnerText }
                    $shared += $sb
                }
                else { $shared += '' }
            }
        }

        $wsXml = Read-Xml (Get-Entry $target)
        if (-not $wsXml) { throw "Worksheet part '$target' not found." }
        $cells = @{}
        foreach ($row in $wsXml.worksheet.sheetData.row) {
            foreach ($c in $row.c) {
                if ($null -eq $c) { continue }
                $ref = $c.r
                $t = if ($c.HasAttribute('t')) { $c.GetAttribute('t') } else { '' }
                $vNode = $c['v']
                $vTxt = if ($vNode) { $vNode.InnerText } else { $null }
                $val = $null
                if ($t -eq 's') { if ($null -ne $vTxt) { $idx = [int]$vTxt; if ($idx -ge 0 -and $idx -lt $shared.Count) { $val = $shared[$idx] } } }
                elseif ($t -eq 'inlineStr') { $isn = $c['is']; if ($isn) { $val = $isn.InnerText } }
                elseif ($t -eq 'str') { $val = $vTxt }
                elseif ($t -eq 'b') { $val = ($vTxt -eq '1') ? 'true' : 'false' }
                else { $val = $vTxt }
                if ($null -ne $val) { $cells[$ref] = $val }
            }
        }
        return $cells
    }
    finally { $zip.Dispose() }
}

function Split-CellRef {
    param([string]$Ref)
    if ($Ref -match '^([A-Z]+)(\d+)$') {
        $col = 0
        foreach ($ch in $Matches[1].ToCharArray()) { $col = $col * 26 + ([int][char]$ch - 64) }
        return [pscustomobject]@{ Col = $col; Row = [int]$Matches[2] }
    }
    return $null
}

function ConvertFrom-ConfigSheet {
    <#
    .SYNOPSIS Turn the row-tagged 'Config' sheet cells into the config model.
    #>
    param([Parameter(Mandatory)][hashtable]$Cells)

    # group cells by row -> @{col=value}
    $rows = @{}
    foreach ($ref in $Cells.Keys) {
        $rc = Split-CellRef $ref
        if (-not $rc) { continue }
        if (-not $rows.ContainsKey($rc.Row)) { $rows[$rc.Row] = @{} }
        $rows[$rc.Row][$rc.Col] = $Cells[$ref]
    }

    $scalars = @{}
    $subnets = [System.Collections.Generic.List[object]]::new()
    $policies = [System.Collections.Generic.List[string]]::new()
    $waivers = [System.Collections.Generic.List[object]]::new()

    foreach ($rowNum in ($rows.Keys | Sort-Object)) {
        $r = $rows[$rowNum]
        $a = if ($r.ContainsKey(1)) { [string]$r[1] } else { '' }
        $b = if ($r.ContainsKey(2)) { [string]$r[2] } else { '' }
        $c = if ($r.ContainsKey(3)) { [string]$r[3] } else { '' }
        $d = if ($r.ContainsKey(4)) { [string]$r[4] } else { '' }
        $e = if ($r.ContainsKey(5)) { [string]$r[5] } else { '' }
        $a = $a.Trim()
        if (-not $a) { continue }
        switch ($a) {
            'SUBNET' {
                if ($b.Trim()) { $subnets.Add([pscustomobject]@{ role = $b.Trim(); cidr = $c.Trim(); requiredPrefix = $d.Trim(); delegation = ($e.Trim() ? $e.Trim() : 'none') }) }
            }
            'POLICY' { if ($b.Trim()) { $policies.Add($b.Trim()) } }
            'WAIVER' { if ($b.Trim()) { $waivers.Add([pscustomobject]@{ check = $b.Trim(); justification = $c.Trim(); approvedBy = $d.Trim() }) } }
            default {
                if ($a -match '\.' -or $a -match '^[a-z]') { if ($b -ne '') { $scalars[$a] = $b.Trim() } }
            }
        }
    }
    return [pscustomobject]@{ Scalars = $scalars; Subnets = $subnets; Policies = $policies; Waivers = $waivers }
}

function Get-DottedList { param([hashtable]$Map, [string]$Prefix)
    $Map.Keys | Where-Object { $_ -like "$Prefix*" }
}

function ConvertTo-ConfigModel {
    <#
    .SYNOPSIS Assemble the config.schema.json-shaped object from parsed sheet parts.
    #>
    param([Parameter(Mandatory)][object]$Parsed)
    $s = $Parsed.Scalars
    function Val([string]$k, $default = $null) { if ($s.ContainsKey($k) -and $s[$k] -ne '') { $s[$k] } else { $default } }
    function Bool([string]$k, $default) { $v = Val $k; if ($null -eq $v) { return $default }; return ($v -match '^(true|yes|1)$') }
    function CsvList([string]$k) { $v = Val $k; if (-not $v) { return @() }; return @($v -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }

    $subnets = @($Parsed.Subnets | ForEach-Object {
            [ordered]@{ role = $_.role; cidr = $_.cidr; requiredPrefix = $_.requiredPrefix; delegation = $_.delegation }
        })

    $model = [ordered]@{
        schemaVersion     = (Val 'schemaVersion' '1.0')
        subscriptionId    = (Val 'subscriptionId')
        environment       = (Val 'environment')
        controlPlaneRegion = (Val 'controlPlaneRegion')
        workloadRegion    = (Val 'workloadRegion')
        deployingIdentity = [ordered]@{
            objectId            = (Val 'deployingIdentity.objectId')
            type                = (Val 'deployingIdentity.type' 'user')
            canRegisterProviders = (Bool 'deployingIdentity.canRegisterProviders' $false)
        }
        network           = [ordered]@{
            model                = (Val 'network.model' 'byo')
            networkResourceGroup = (Val 'network.networkResourceGroup')
            vnetCidr             = (Val 'network.vnetCidr')
            corpDns              = (CsvList 'network.corpDns')
            nvaNextHop           = (Val 'network.nvaNextHop')
            outboundType         = (Val 'network.outboundType' 'UserDefinedRouting')
            spokeCidr            = (Val 'network.spokeCidr')
            existingSubnets      = (CsvList 'network.existingSubnets')
            subnets              = $subnets
        }
        storage           = [ordered]@{
            model  = (Val 'storage.model' 'managed')
            account = (Val 'storage.account')
            access = (Val 'storage.access' 'privateEndpoint')
        }
        sizingTier        = (Val 'sizingTier' 'Small')
        bookshelf         = [ordered]@{
            inScope   = (Bool 'bookshelf.inScope' $false)
            instances = [int](Val 'bookshelf.instances' '0')
        }
        projects          = [int](Val 'projects' '1')
        deployMode        = (Val 'deployMode' 'GlobalStandard')
        names             = [ordered]@{
            workspace        = (Val 'names.workspace')
            project          = (Val 'names.project')
            supercomputer    = (Val 'names.supercomputer')
            nodePool         = (Val 'names.nodePool')
            tool             = (Val 'names.tool')
            agent            = (Val 'names.agent')
            storageContainer = (Val 'names.storageContainer')
            storageAsset     = (Val 'names.storageAsset')
            investigation    = (Val 'names.investigation')
        }
        policySet         = @($Parsed.Policies)
        waivers           = @($Parsed.Waivers | ForEach-Object { [ordered]@{ check = $_.check; justification = $_.justification; approvedBy = $_.approvedBy } })
    }
    # prune empty-string leaf values so downstream required checks catch true blanks
    return $model
}

# ===========================================================================
# Reference data (from Onboarding-Tooling-Requirements.md)
# ===========================================================================
$script:RequiredPrefixByRole = @{
    'agent-containerapp'     = 26
    'workspace-containerapp' = 26
    'search-containerapp'    = 27
    'managedcluster'         = 26
    'nodepool'               = 26
    'private-endpoints'      = 27
    'spare'                  = 27
}
$script:DelegationByRole = @{
    'agent-containerapp'     = 'Microsoft.App/environments'
    'workspace-containerapp' = 'Microsoft.App/environments'
    'search-containerapp'    = 'Microsoft.App/environments'
    'managedcluster'         = 'Microsoft.ContainerService/managedClusters'
    'nodepool'               = 'none'
    'private-endpoints'      = 'none'
    'spare'                  = 'none'
}
$script:NameRules = @{
    workspace        = @{ Min = 3; Max = 24 }
    project          = @{ Min = 3; Max = 12 }
    supercomputer    = @{ Min = 3; Max = 24 }
    nodePool         = @{ Min = 3; Max = 12 }
    tool             = @{ Min = 3; Max = 24 }
    agent            = @{ Min = 3; Max = 63 }
    storageContainer = @{ Min = 3; Max = 24 }
    storageAsset     = @{ Min = 3; Max = 24 }
    investigation    = @{ Min = 1; Max = 20 }
}
$script:KnownDenyPolicies = @(
    @{ Match = 'Cognitive Services'; Handling = 'exemption'; Note = 'Cognitive Services public network access deny blocks Foundry provisioning.' }
    @{ Match = 'Log Analytics';      Handling = 'exemption'; Note = 'Log Analytics public access deny blocks workspace diagnostics.' }
    @{ Match = 'Storage account';    Handling = 'configuration'; Note = 'Storage public access deny requires private-endpoint config.' }
    @{ Match = 'network security perimeter'; Handling = 'exemption'; Note = 'NSP association policy must allow the Discovery perimeter.' }
)
$script:CapacityLimitedRegions = @('eastus2')  # AKSCapacityHeavyUsage observed

# ===========================================================================
# Validation checks (FR1.0 - FR1.7)
# ===========================================================================
function Test-Field { param($v) ($null -ne $v) -and ("$v".Trim() -ne '') }

function Get-LivePolicyAssignments {
    <#
    .SYNOPSIS Collect the policy assignments effective at the target subscription (including
      inherited management-group assignments) and resolve each one's policyType and effect.
    .OUTPUTS Array of assignment objects, or $null when az could not read the assignments.
    #>
    param([Parameter(Mandatory)][string]$SubscriptionId)
    $scope = "/subscriptions/$SubscriptionId"
    $assignments = Get-AzJson -Args @('policy', 'assignment', 'list', '--scope', $scope, '--disable-scope-strict-match') -AllowFail
    if ($null -eq $assignments) { return $null }
    $defCache = @{}
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($a in @($assignments)) {
        $defId = [string]$a.policyDefinitionId
        $effect = $null
        if ($a.parameters -and ($a.parameters.PSObject.Properties.Name -contains 'effect') -and $a.parameters.effect.value) {
            $effect = [string]$a.parameters.effect.value
        }
        $policyType = 'Unknown'
        if ($defId) {
            if (-not $defCache.ContainsKey($defId)) {
                $isSet = $defId -match '/policySetDefinitions/'
                $defName = ($defId -split '/')[-1]
                $defSub = if ($defId -match '/subscriptions/([^/]+)/') { $Matches[1] } else { $SubscriptionId }
                $showArgs = if ($isSet) { @('policy', 'set-definition', 'show', '--name', $defName, '--subscription', $defSub) }
                else { @('policy', 'definition', 'show', '--name', $defName, '--subscription', $defSub) }
                $defCache[$defId] = Get-AzJson -Args $showArgs -AllowFail
            }
            $def = $defCache[$defId]
            if ($def) {
                $policyType = [string]$def.policyType
                if (-not $effect) {
                    if (($def.PSObject.Properties.Name -contains 'policyRule') -and $def.policyRule.then) {
                        $rawEffect = [string]$def.policyRule.then.effect
                        if ($rawEffect -and $rawEffect -notmatch '^\[') { $effect = $rawEffect }
                    }
                    elseif ($defId -match '/policySetDefinitions/') { $effect = 'initiative' }
                }
            }
        }
        if (-not $effect) { $effect = 'unknown' }
        $out.Add([pscustomobject]@{
                name         = [string]$a.name
                displayName  = [string]$a.displayName
                policyType   = $policyType
                effect       = $effect
                scope        = [string]$a.scope
                definitionId = $defId
            })
    }
    return $out.ToArray()
}

function Invoke-Stage1Checks {
    param([Parameter(Mandatory)][object]$Cfg)
    $R = [System.Collections.Generic.List[object]]::new()

    # ---- FR1.1 capture/normalization -------------------------------------
    $missing = @()
    foreach ($f in @('subscriptionId', 'controlPlaneRegion', 'workloadRegion', 'sizingTier')) { if (-not (Test-Field $Cfg.$f)) { $missing += $f } }
    if (-not (Test-Field $Cfg.network.vnetCidr)) { $missing += 'network.vnetCidr' }
    if (-not (Test-Field $Cfg.deployingIdentity.objectId)) { $missing += 'deployingIdentity.objectId' }
    if (@($Cfg.network.subnets).Count -eq 0) { $missing += 'network.subnets' }
    if ($missing.Count) {
        $R.Add((New-CheckResult -Id 'capture' -Name 'Required fields captured' -Status 'Fail' -Fr 'FR1.1' `
                    -Detail "Missing: $($missing -join ', ')" -Remediation 'Complete the corresponding cell(s) in the Config sheet.' -Data @{ missing = $missing }))
    }
    else {
        $R.Add((New-CheckResult -Id 'capture' -Name 'Required fields captured' -Status 'Pass' -Fr 'FR1.1' -Detail 'All core planning fields present.'))
    }

    # ---- FR1.0 subscription prerequisites --------------------------------
    $loggedIn = [bool](Get-AzJson -Args @('account', 'show') -AllowFail)
    if (-not $loggedIn) {
        $R.Add((New-CheckResult -Id 'sub-prereq' -Name 'Subscription enabled for Discovery' -Status 'Skip' -Fr 'FR1.0' `
                    -Detail 'az not logged in; enablement + RP state not checked.' -Remediation "Run 'az login' and re-run to verify Discovery enablement and RP registration."))
    }
    else {
        $prov = Get-AzJson -Args @('provider', 'show', '--namespace', 'Microsoft.Discovery', '--subscription', $Cfg.subscriptionId) -AllowFail
        $regState = if ($prov) { [string]$prov.registrationState } else { 'Unknown' }
        if ($prov) {
            $R.Add((New-CheckResult -Id 'sub-prereq' -Name 'Discovery RP visible on subscription' -Status 'Pass' -Fr 'FR1.0' `
                        -Detail "Microsoft.Discovery registrationState=$regState (Stage 2 performs registration)." -Data @{ registrationState = $regState }))
        }
        else {
            $R.Add((New-CheckResult -Id 'sub-prereq' -Name 'Subscription enabled for Discovery' -Status 'Warn' -Fr 'FR1.0' `
                        -Detail 'Could not read Microsoft.Discovery provider (may be allowlist-gated or access-limited).' `
                        -Remediation 'Confirm the subscription is allowlisted for Discovery by the Microsoft Discovery team.'))
        }
    }
    if (-not $Cfg.deployingIdentity.canRegisterProviders) {
        $R.Add((New-CheckResult -Id 'identity-register' -Name 'Deploying identity can register providers' -Status 'Warn' -Fr 'FR1.0' `
                    -Detail 'Config marks the deploying identity as unable to register providers.' `
                    -Remediation 'Grant Contributor/Owner or a role with Microsoft.Discovery/register/action before Stage 2.'))
    }
    else {
        $R.Add((New-CheckResult -Id 'identity-register' -Name 'Deploying identity can register providers' -Status 'Pass' -Fr 'FR1.0'))
    }

    # ---- FR1.2 subnet sizing + delegation --------------------------------
    foreach ($sn in $Cfg.network.subnets) {
        $role = [string]$sn.role
        $issues = @()
        try { $info = Get-CidrInfo $sn.cidr } catch { $info = $null; $issues += "invalid CIDR '$($sn.cidr)'" }
        $reqPrefix = if ($script:RequiredPrefixByRole.ContainsKey($role)) { $script:RequiredPrefixByRole[$role] } else { $null }
        if ($info -and $reqPrefix -and $info.Prefix -gt $reqPrefix) { $issues += "prefix /$($info.Prefix) smaller than required /$reqPrefix" }
        $expDel = if ($script:DelegationByRole.ContainsKey($role)) { $script:DelegationByRole[$role] } else { $null }
        if ($expDel -and ([string]$sn.delegation) -ne $expDel) { $issues += "delegation '$($sn.delegation)' should be '$expDel'" }
        if ($issues.Count) {
            $R.Add((New-CheckResult -Id "subnet-$role" -Name "Subnet $role sizing/delegation" -Status 'Fail' -Fr 'FR1.2' `
                        -Detail ($issues -join '; ') -Remediation 'Resize to the required prefix and set the correct delegation in the Config sheet.'))
        }
        else {
            $R.Add((New-CheckResult -Id "subnet-$role" -Name "Subnet $role sizing/delegation" -Status 'Pass' -Fr 'FR1.2' -Detail "$($sn.cidr) delegation=$($sn.delegation)"))
        }
    }

    # ---- FR1.2 egress model (forced tunneling vs managed) ----------------
    $outbound = [string]$Cfg.network.outboundType
    if ([string]::IsNullOrWhiteSpace($outbound)) { $outbound = 'UserDefinedRouting' }
    if ($outbound -notin @('UserDefinedRouting', 'LoadBalancer')) {
        $R.Add((New-CheckResult -Id 'egress-model' -Name 'Egress model (network.outboundType)' -Status 'Fail' -Fr 'FR1.2' `
                    -Detail "network.outboundType='$outbound' is not valid." -Remediation "Set network.outboundType to 'UserDefinedRouting' (forced tunneling) or 'LoadBalancer' (Azure-managed egress)."))
    }
    elseif ($outbound -eq 'UserDefinedRouting' -and -not (Test-Field $Cfg.network.nvaNextHop)) {
        $R.Add((New-CheckResult -Id 'egress-model' -Name 'Egress model (network.outboundType)' -Status 'Warn' -Fr 'FR1.2' `
                    -Detail 'UserDefinedRouting (forced tunneling) selected but network.nvaNextHop is blank.' `
                    -Remediation 'Provide the firewall/NVA next-hop IP (network.nvaNextHop) so Stage 2/3 can build and validate the egress route.'))
    }
    else {
        $R.Add((New-CheckResult -Id 'egress-model' -Name 'Egress model (network.outboundType)' -Status 'Pass' -Fr 'FR1.2' -Detail "outboundType=$outbound"))
    }

    # ---- FR1.2 network model intent --------------------------------------
    $netModel = [string]$Cfg.network.model
    if ([string]::IsNullOrWhiteSpace($netModel)) { $netModel = 'byo-spoke' }
    $allowedModels = @('byo', 'byo-spoke', 'byo-existing', 'greenfield', 'managed')
    $buildModels = @('byo', 'byo-spoke', 'greenfield')
    if ($netModel -notin $allowedModels) {
        $R.Add((New-CheckResult -Id 'network-model' -Name 'Network model (network.model)' -Status 'Fail' -Fr 'FR1.2' `
                    -Detail "network.model='$netModel' is not valid." `
                    -Remediation "Set network.model to one of: byo/byo-spoke (tool provisions into the customer VNet), byo-existing (validate only), greenfield (tool builds a self-contained VNet), managed (RP-managed)."))
    }
    elseif ($netModel -in $buildModels -and $outbound -eq 'UserDefinedRouting' -and -not (Test-Field $Cfg.network.nvaNextHop)) {
        $R.Add((New-CheckResult -Id 'network-model' -Name 'Network model (network.model)' -Status 'Warn' -Fr 'FR1.2' `
                    -Detail "network.model='$netModel' with UserDefinedRouting but network.nvaNextHop is blank; Stage 2 network.bicep cannot build the NVA route table." `
                    -Remediation 'Provide network.nvaNextHop, or set network.outboundType=LoadBalancer for greenfield/dev.'))
    }
    else {
        $R.Add((New-CheckResult -Id 'network-model' -Name 'Network model (network.model)' -Status 'Pass' -Fr 'FR1.2' -Detail "model=$netModel"))
    }

    # ---- FR1.3 address-space conflict ------------------------------------
    if (Test-Field $Cfg.network.vnetCidr) {
        $overlaps = @()
        $fitFail = @()
        foreach ($sn in $Cfg.network.subnets) {
            try {
                if (-not (Test-CidrContains -Outer $Cfg.network.vnetCidr -Inner $sn.cidr)) { $fitFail += "$($sn.role) ($($sn.cidr)) not inside VNet $($Cfg.network.vnetCidr)" }
            }
            catch {}
            foreach ($ex in $Cfg.network.existingSubnets) {
                try { if (Test-CidrOverlap -A $sn.cidr -B $ex) { $overlaps += "$($sn.role) ($($sn.cidr)) overlaps existing $ex" } } catch {}
            }
        }
        # pairwise overlap among Discovery subnets
        $arr = @($Cfg.network.subnets)
        for ($i = 0; $i -lt $arr.Count; $i++) {
            for ($j = $i + 1; $j -lt $arr.Count; $j++) {
                try { if (Test-CidrOverlap -A $arr[$i].cidr -B $arr[$j].cidr) { $overlaps += "$($arr[$i].role) overlaps $($arr[$j].role)" } } catch {}
            }
        }
        if ($overlaps.Count -or $fitFail.Count) {
            $R.Add((New-CheckResult -Id 'address-space' -Name 'Address-space conflict / fit' -Status 'Fail' -Fr 'FR1.3' `
                        -Detail (@($overlaps + $fitFail) -join '; ') -Remediation 'Relocate the conflicting subnet or widen the VNet so the full Discovery layout fits without overlap.' `
                        -Data @{ overlaps = $overlaps; fit = $fitFail }))
        }
        else {
            $R.Add((New-CheckResult -Id 'address-space' -Name 'Address-space conflict / fit' -Status 'Pass' -Fr 'FR1.3' -Detail 'No overlaps; all subnets fit inside the VNet.'))
        }
    }

    # ---- FR1.4 region availability / capacity ----------------------------
    $capFlag = $Cfg.workloadRegion -in $script:CapacityLimitedRegions
    if ($capFlag) {
        $split = ($Cfg.workloadRegion -eq $Cfg.controlPlaneRegion)
        $R.Add((New-CheckResult -Id 'region-capacity' -Name 'Region capacity' -Status 'Warn' -Fr 'FR1.4' `
                    -Detail "Workload region '$($Cfg.workloadRegion)' has known AKS API Server VNet Integration capacity pressure (AKSCapacityHeavyUsage) and AI Search capacity limits." `
                    -Remediation ($split ? 'Split control-plane and workload regions, or choose a region with capacity.' : 'Split already configured; confirm AI Search capacity in the workload region.')))
    }
    else {
        $R.Add((New-CheckResult -Id 'region-capacity' -Name 'Region capacity' -Status 'Pass' -Fr 'FR1.4' -Detail "No known capacity flag for '$($Cfg.workloadRegion)'."))
    }

    # ---- FR1.5 quota / SKU / TPM / Cosmos --------------------------------
    $cosmosRu = 2400 + 400 * [int]$Cfg.projects
    $R.Add((New-CheckResult -Id 'cosmos-ru' -Name 'Cosmos RU/s sizing' -Status 'Pass' -Fr 'FR1.5' `
                -Detail "Projects=$($Cfg.projects) -> required autoscale $cosmosRu RU/s (2400 + 400 x projects)." -Data @{ requiredRuPerSec = $cosmosRu }))
    if ($loggedIn) {
        $skus = Get-AzJson -Args @('vm', 'list-skus', '--location', $Cfg.workloadRegion, '--resource-type', 'virtualMachines') -AllowFail
        if ($skus) {
            $offered = @($skus | ForEach-Object { $_.name })
            if ($offered -contains 'Standard_D4s_v6' -and $offered -notcontains 'Standard_D4ds_v6') {
                # informational only
            }
            $R.Add((New-CheckResult -Id 'sku-region' -Name 'VM SKU availability' -Status 'Pass' -Fr 'FR1.5' -Detail "$($offered.Count) VM SKUs offered in $($Cfg.workloadRegion)."))
        }
        else {
            $R.Add((New-CheckResult -Id 'sku-region' -Name 'VM SKU availability' -Status 'Warn' -Fr 'FR1.5' -Detail 'Could not enumerate VM SKUs.' -Remediation 'Verify vm list-skus access for the workload region.'))
        }
    }
    else {
        $R.Add((New-CheckResult -Id 'sku-region' -Name 'VM SKU availability' -Status 'Skip' -Fr 'FR1.5' -Detail 'az not logged in; SKU-in-region not checked. Note: Standard_D4s_v6 is not offered in eastus/eastus2 (use Standard_D4ds_v6).'))
    }
    if ($Cfg.deployMode -eq 'DataZoneStandard') {
        $R.Add((New-CheckResult -Id 'deploy-mode' -Name 'Deploy mode' -Status 'Warn' -Fr 'FR1.5' -Detail 'DataZoneStandard selected for data residency; confirm model availability in the data zone.'))
    }

    # ---- FR1.6 naming rules ----------------------------------------------
    $namePattern = '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'
    foreach ($k in $script:NameRules.Keys) {
        $name = [string]$Cfg.names.$k
        $rule = $script:NameRules[$k]
        $issues = @()
        if (-not (Test-Field $name)) {
            $R.Add((New-CheckResult -Id "name-$k" -Name "Name '$k'" -Status 'Warn' -Fr 'FR1.6' -Detail 'Not provided.' -Remediation "Provide names.$k (length $($rule.Min)-$($rule.Max))."))
            continue
        }
        if ($name.Length -lt $rule.Min -or $name.Length -gt $rule.Max) { $issues += "length $($name.Length) outside $($rule.Min)-$($rule.Max)" }
        if ($name -cnotmatch $namePattern) { $issues += 'must be lowercase alphanumeric + single hyphens, start with a letter' }
        if ($issues.Count) {
            $R.Add((New-CheckResult -Id "name-$k" -Name "Name '$k'" -Status 'Fail' -Fr 'FR1.6' -Detail ($issues -join '; ') -Remediation 'Rename per the per-type rule.'))
        }
        else {
            $R.Add((New-CheckResult -Id "name-$k" -Name "Name '$k'" -Status 'Pass' -Fr 'FR1.6' -Detail $name))
        }
    }
    if ($loggedIn -and (Test-Field $Cfg.names.workspace)) {
        $body = @{ name = $Cfg.names.workspace; type = 'Microsoft.Discovery/workspaces' } | ConvertTo-Json -Compress
        $avail = Get-AzJson -Args @('rest', '--method', 'post', '--url', "https://management.azure.com/subscriptions/$($Cfg.subscriptionId)/providers/Microsoft.Discovery/checkNameAvailability?api-version=2026-06-01", '--body', $body) -AllowFail
        if ($avail -and ($avail.PSObject.Properties.Name -contains 'nameAvailable')) {
            $st = if ($avail.nameAvailable) { 'Pass' } else { 'Fail' }
            $R.Add((New-CheckResult -Id 'workspace-availability' -Name 'Workspace name available' -Status $st -Fr 'FR1.6' `
                        -Detail ($avail.nameAvailable ? "'$($Cfg.names.workspace)' is available." : "'$($Cfg.names.workspace)' is taken.") -Remediation 'Choose another workspace name (it is the public subdomain).'))
        }
    }

    # ---- FR1.7 policy pre-flight -----------------------------------------
    # Collect live policy assignments from Azure (subscription + inherited MG scope).
    $live = $null
    if ($loggedIn -and (Test-Field $Cfg.subscriptionId)) {
        $live = Get-LivePolicyAssignments -SubscriptionId $Cfg.subscriptionId
    }
    $liveNames = if ($live) { @($live | ForEach-Object { $_.displayName; $_.name }) } else { @() }

    # Cross-check declared (form) + live assignment names against the known Discovery blockers.
    $candidateNames = @(@($Cfg.policySet) + $liveNames | Where-Object { $_ } | Select-Object -Unique)
    $conflicts = @()
    foreach ($p in $candidateNames) {
        foreach ($known in $script:KnownDenyPolicies) {
            if ($p -match [regex]::Escape($known.Match)) { $conflicts += [pscustomobject]@{ policy = $p; handling = $known.Handling; note = $known.Note } }
        }
    }
    $conflicts = @($conflicts | Sort-Object policy -Unique)
    if ($conflicts.Count) {
        $R.Add((New-CheckResult -Id 'policy-preflight' -Name 'Deny-policy pre-flight' -Status 'Warn' -Fr 'FR1.7' `
                    -Detail (($conflicts | ForEach-Object { "$($_.policy) [$($_.handling)]" }) -join '; ') `
                    -Remediation 'Plan the exemption or configuration change now (feeds Stage 2 quota_exemption_requests).' -Data $conflicts))
    }
    else {
        $R.Add((New-CheckResult -Id 'policy-preflight' -Name 'Deny-policy pre-flight' -Status 'Pass' -Fr 'FR1.7' -Detail 'No known blocking deny policies in the declared or live assignment set.'))
    }

    # Collect + inspect custom, restrictive policies beyond the known set.
    if (-not $loggedIn) {
        $R.Add((New-CheckResult -Id 'policy-collect' -Name 'Custom policy collection' -Status 'Skip' -Fr 'FR1.7' `
                    -Detail 'az not logged in; live policy assignments not collected.' -Remediation "Run 'az login' and re-run to collect and inspect the effective policy set."))
    }
    elseif ($null -eq $live) {
        $R.Add((New-CheckResult -Id 'policy-collect' -Name 'Custom policy collection' -Status 'Warn' -Fr 'FR1.7' `
                    -Detail 'Could not read policy assignments at subscription scope.' `
                    -Remediation 'Grant the deploying identity Reader (or Resource Policy Reader) at the subscription and re-run.'))
    }
    else {
        $restrictiveEffects = @('deny', 'denyAction', 'modify', 'deployIfNotExists', 'append')
        $restrictive = @($live | Where-Object { $restrictiveEffects -contains $_.effect })
        $customRestrictive = @($restrictive | Where-Object { $_.policyType -eq 'Custom' })
        if ($customRestrictive.Count) {
            $R.Add((New-CheckResult -Id 'policy-collect' -Name 'Custom policy collection' -Status 'Warn' -Fr 'FR1.7' `
                        -Detail "Collected $(@($live).Count) assignment(s); $($customRestrictive.Count) custom restrictive policy(ies): $((@($customRestrictive | ForEach-Object { "$($_.displayName) [$($_.effect)]" }) | Select-Object -First 10) -join '; ')." `
                        -Remediation 'Review each custom deny/altering policy against the Stage 2 subnet/NSG/route/DNS/storage plan; plan an exemption or config change before Stage 2.' `
                        -Data @{ collected = @($live).Count; customRestrictive = $customRestrictive; restrictive = $restrictive }))
        }
        else {
            $R.Add((New-CheckResult -Id 'policy-collect' -Name 'Custom policy collection' -Status 'Pass' -Fr 'FR1.7' `
                        -Detail "Collected $(@($live).Count) assignment(s); no custom deny/altering policies beyond the known set." `
                        -Data @{ collected = @($live).Count; restrictive = $restrictive }))
        }
    }

    return $R.ToArray()
}

# ===========================================================================
# FR1.8 — export gate
# ===========================================================================
function Get-ContentHash {
    param([Parameter(Mandatory)][object]$Object)
    $json = ($Object | ConvertTo-Json -Depth 20)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLower()
    }
    finally { $sha.Dispose() }
}

# ===========================================================================
# Main
# ===========================================================================
if (-not (Test-Path -LiteralPath $FormPath)) { throw "Form not found: $FormPath" }
$ext = [System.IO.Path]::GetExtension($FormPath).ToLowerInvariant()

if ($ext -eq '.json') {
    $cfgModel = Get-Content -LiteralPath $FormPath -Raw | ConvertFrom-Json
    Write-Host "Loaded config model from JSON: $FormPath"
}
elseif ($ext -eq '.xlsx') {
    $cells = Read-XlsxSheet -Path $FormPath -SheetName 'Config'
    $parsed = ConvertFrom-ConfigSheet -Cells $cells
    $cfgModel = ConvertTo-ConfigModel -Parsed $parsed
    Write-Host "Parsed planning form: $FormPath  (subnets=$(@($parsed.Subnets).Count), policies=$(@($parsed.Policies).Count), waivers=$(@($parsed.Waivers).Count))"
}
else { throw "Unsupported form type '$ext'. Provide a .xlsx planning form or a .json config." }

$results = Invoke-Stage1Checks -Cfg $cfgModel

# apply waivers: downgrade waived failing P0 checks
$waiverChecks = @($cfgModel.waivers | ForEach-Object { $_.check })
$results = @($results | ForEach-Object {
        if ($_.status -eq 'Fail' -and ($waiverChecks -contains $_.id)) {
            New-CheckResult -Id $_.id -Name $_.name -Status 'Waived' -Fr $_.fr -Detail "$($_.detail) [waived]" -Data $_.data
        }
        else { $_ }
    })

$blocked = @($results | Where-Object { $_.status -eq 'Fail' })

# default export path
if (-not $OutConfig) { $OutConfig = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $FormPath)) 'config.json' }

if ($blocked.Count -eq 0) {
    $cfgModel.schemaVersion = '1.0'
    if ($cfgModel.PSObject.Properties.Name -contains 'contentHash') { $cfgModel.PSObject.Properties.Remove('contentHash') }
    $hash = Get-ContentHash -Object $cfgModel
    $ordered = [ordered]@{ schemaVersion = '1.0'; contentHash = $hash }
    foreach ($p in $cfgModel.PSObject.Properties) { if ($p.Name -ne 'schemaVersion') { $ordered[$p.Name] = $p.Value } }
    ($ordered | ConvertTo-Json -Depth 20) | Set-Content -LiteralPath $OutConfig -Encoding utf8
    $exportResult = New-CheckResult -Id 'config-export' -Name 'Config exported' -Status 'Pass' -Fr 'FR1.8' -Detail "Wrote $OutConfig (contentHash=$($hash.Substring(0,12))...)."
}
else {
    $exportResult = New-CheckResult -Id 'config-export' -Name 'Config export blocked' -Status 'Fail' -Fr 'FR1.8' `
        -Detail "Blocked by $($blocked.Count) failing check(s): $((@($blocked).id) -join ', ')." `
        -Remediation 'Resolve the named red check(s) or add a WAIVER row (checkId + justification) in the Config sheet, then re-run.'
}
$results = @($results) + $exportResult

if ($PassThru) { return $results }
$null = Write-OnboardingReport -Results $results -Title 'Stage 1 — Planning' -JsonPath $JsonPath -Extra @{ outConfig = ($blocked.Count -eq 0 ? $OutConfig : $null) }
Complete-Stage -Results $results
