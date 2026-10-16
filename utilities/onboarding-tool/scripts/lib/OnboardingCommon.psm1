<#
.SYNOPSIS
    Shared helpers for the Discovery customer-onboarding PowerShell tooling.

.DESCRIPTION
    Every onboarding script (Stages 1-5) dot-sources / imports this module. It provides:
      - a single check-result shape (New-CheckResult) so every script emits the same JSON;
      - config load + schema-lite validation (Get-OnboardingConfig);
      - an Azure CLI wrapper that parses JSON and surfaces errors (Invoke-Az / Get-AzJson);
      - report emission (JSON file + human table) and the pass/fail exit convention
        (Write-OnboardingReport / Complete-Stage);
      - CIDR / subnet math used by the Stage 1 planning checks.

    Conventions (mirrors ../script-specs/README.md):
      - Every script returns a set of check results; exit 0 only when no result is 'Fail'.
      - Read-only stays read-only: only Stage 2 and Stage 4 write platform resources,
        Stage 3 writes only its ephemeral test VM.
      - Every failure carries an exact remediation string, not just a red mark.
#>

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Check-result model
# ---------------------------------------------------------------------------

$script:ValidStatus = @('Pass', 'Fail', 'Warn', 'Skip', 'Waived')

function New-CheckResult {
    <#
    .SYNOPSIS Standard result object emitted by every check/action.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Id,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('Pass', 'Fail', 'Warn', 'Skip', 'Waived')][string]$Status,
        [string]$Detail = '',
        [string]$Remediation = '',
        [string]$Fr = '',
        [object]$Data = $null
    )
    [pscustomobject]@{
        id          = $Id
        name        = $Name
        status      = $Status
        detail      = $Detail
        remediation = $Remediation
        fr          = $Fr
        data        = $Data
        timestamp   = (Get-Date).ToUniversalTime().ToString('o')
    }
}

function Test-AnyFailure {
    param([Parameter(Mandatory)][object[]]$Results)
    [bool]($Results | Where-Object { $_.status -eq 'Fail' })
}

# ---------------------------------------------------------------------------
# Config load + lightweight validation
# ---------------------------------------------------------------------------

function Get-OnboardingConfig {
    <#
    .SYNOPSIS Load the Stage 1 config.json (single source of truth) as an object.
    .DESCRIPTION
        Accepts a JSON path. Performs a lightweight required-field check against the
        Stage 1 schema (schemaVersion, subscriptionId, regions, network, sizingTier,
        names, deployingIdentity, rbac). Throws on missing or invalid required fields.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Config not found: $Path"
    }
    $raw = Get-Content -LiteralPath $Path -Raw
    try {
        $cfg = $raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Config is not valid JSON ($Path): $($_.Exception.Message)"
    }

    $required = @('schemaVersion', 'subscriptionId', 'controlPlaneRegion', 'workloadRegion', 'network', 'sizingTier', 'names', 'deployingIdentity', 'rbac')
    $missing = @()
    foreach ($f in $required) {
        if (-not ($cfg.PSObject.Properties.Name -contains $f) -or $null -eq $cfg.$f) { $missing += $f }
    }
    if ($missing.Count) {
        throw "Config missing required field(s): $($missing -join ', ')"
    }

    $humanAccessMode = if ($cfg.rbac.PSObject.Properties.Name -contains 'humanAccessMode') { [string]$cfg.rbac.humanAccessMode } else { '' }
    if (@('permanent-role-assignments', 'customer-jit-managed') -notcontains $humanAccessMode) {
        throw "Config rbac.humanAccessMode must be 'permanent-role-assignments' or 'customer-jit-managed'."
    }

    $hasDuration = $cfg.rbac.PSObject.Properties.Name -contains 'jitEligibilityDurationDays'
    if ($humanAccessMode -eq 'permanent-role-assignments' -and $hasDuration -and $null -ne $cfg.rbac.jitEligibilityDurationDays) {
        throw 'Config rbac.jitEligibilityDurationDays must be omitted when rbac.humanAccessMode is permanent-role-assignments.'
    }
    if ($humanAccessMode -eq 'customer-jit-managed') {
        [int]$durationDays = 0
        if (-not $hasDuration -or
            -not [int]::TryParse([string]$cfg.rbac.jitEligibilityDurationDays, [Globalization.NumberStyles]::Integer, [Globalization.CultureInfo]::InvariantCulture, [ref]$durationDays) -or
            $durationDays -lt 7 -or $durationDays -gt 3650) {
            throw 'Config rbac.jitEligibilityDurationDays must be a whole number from 7 through 3650 when rbac.humanAccessMode is customer-jit-managed.'
        }
        $cfg.rbac.jitEligibilityDurationDays = $durationDays
    }
    return $cfg
}

function Test-CustomerJitManagedUser {
    param(
        [Parameter(Mandatory)][object]$Config,
        [string]$PrincipalType
    )
    if ($PrincipalType -notmatch '^user$') { return $false }
    if (-not ($Config.PSObject.Properties.Name -contains 'rbac') -or $null -eq $Config.rbac) { return $false }
    if (-not ($Config.rbac.PSObject.Properties.Name -contains 'humanAccessMode')) { return $false }
    return [string]$Config.rbac.humanAccessMode -eq 'customer-jit-managed'
}

function Test-ConfigWaiver {
    <#
    .SYNOPSIS Return $true when a check id has a recorded waiver in the config (FR1.8).
    #>
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$CheckId
    )
    if (-not ($Config.PSObject.Properties.Name -contains 'waivers') -or $null -eq $Config.waivers) { return $false }
    [bool]($Config.waivers | Where-Object { $_.check -eq $CheckId -and $_.justification })
}

# ---------------------------------------------------------------------------
# Azure CLI wrapper
# ---------------------------------------------------------------------------

function Invoke-Az {
    <#
    .SYNOPSIS Run 'az' with the given argument list and return the raw stdout string.
    .DESCRIPTION
        Centralises az invocation so scripts never inline raw az calls. On non-zero exit
        code, throws with the stderr text unless -AllowFail is set, in which case the
        empty string is returned. Always disables the az survey/telemetry prompt noise.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Args,
        [switch]$AllowFail
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $merged = & az @Args 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
    }
    # az writes warnings/telemetry to stderr; under 2>&1 those arrive as ErrorRecord objects.
    # Keep them out of stdout so JSON payloads parse cleanly, and surface them only on failure.
    $stdoutLines = @($merged | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] })
    $stderrLines = @($merged | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] })
    if ($code -ne 0 -and -not $AllowFail) {
        $detail = (@($stderrLines + $stdoutLines) | ForEach-Object { [string]$_ }) -join "`n"
        throw "az $($Args -join ' ') failed (exit $code): $detail"
    }
    if ($code -ne 0) { return '' }
    return (@($stdoutLines | ForEach-Object { [string]$_ }) -join "`n")
}

function Get-AzJson {
    <#
    .SYNOPSIS Run an az command that returns JSON and parse it to an object.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Args,
        [switch]$AllowFail
    )
    $argList = @($Args)
    if ($argList -notcontains '-o' -and $argList -notcontains '--output') {
        $argList += @('-o', 'json')
    }
    $text = Invoke-Az -Args $argList -AllowFail:$AllowFail
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    try { return $text | ConvertFrom-Json }
    catch { return $null }
}

function Set-PimRoleEligibility {
    <#
    .SYNOPSIS Create or reuse a time-bound Azure RBAC PIM eligible assignment.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SubscriptionId,
        [Parameter(Mandatory)][string]$PrincipalId,
        [Parameter(Mandatory)][string]$RoleId,
        [Parameter(Mandatory)][string]$Scope,
        [Parameter(Mandatory)][ValidateRange(7, 3650)][int]$DurationDays,
        [string]$Justification = 'Discovery onboarding customer-managed JIT access',
        [ValidateRange(0, 300)][int]$PollingIntervalSeconds = 2,
        [ValidateRange(0, 120)][int]$MaxPollingAttempts = 30
    )

    $roleDefinitionId = if ($RoleId -match '^/') {
        $RoleId
    }
    else {
        "/subscriptions/$SubscriptionId/providers/Microsoft.Authorization/roleDefinitions/$RoleId"
    }
    $filter = [uri]::EscapeDataString("principalId eq '$PrincipalId' and roleDefinitionId eq '$roleDefinitionId'")
    $instancesUrl = "https://management.azure.com$scope/providers/Microsoft.Authorization/roleEligibilityScheduleInstances?api-version=2020-10-01&%24filter=$filter"
    $instanceResponse = Get-AzJson -Args @('rest', '--method', 'get', '--url', $instancesUrl)
    if ($null -eq $instanceResponse) {
        throw "Could not read PIM role eligibility schedule instances for $PrincipalId at $Scope."
    }

    $instances = if ($instanceResponse.PSObject.Properties.Name -contains 'value') { @($instanceResponse.value) } else { @($instanceResponse) }
    $now = [DateTimeOffset]::UtcNow
    foreach ($instance in $instances) {
        if (-not $instance) { continue }
        $properties = if ($instance.PSObject.Properties.Name -contains 'properties') { $instance.properties } else { $instance }
        if ($null -eq $properties) {
            throw "PIM returned a malformed eligibility schedule instance for $PrincipalId at $Scope."
        }
        $endValue = if ($properties.PSObject.Properties.Name -contains 'endDateTime') { [string]$properties.endDateTime } else { '' }
        if (-not $endValue) {
            return [pscustomobject]@{
                state                       = 'eligible-existing'
                roleDefinitionId            = $roleDefinitionId
                scope                       = $Scope
                eligibilityEndDateTime      = $null
                requestedEligibilityDurationDays = $DurationDays
                requiresActivation          = $true
            }
        }
        [DateTimeOffset]$endDateTime = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse($endValue, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$endDateTime)) {
            throw "PIM returned an invalid eligibility endDateTime '$endValue' for $PrincipalId at $Scope."
        }
        if ($endDateTime -gt $now) {
            return [pscustomobject]@{
                state                       = 'eligible-existing'
                roleDefinitionId            = $roleDefinitionId
                scope                       = $Scope
                eligibilityEndDateTime      = $endDateTime.ToUniversalTime().ToString('o')
                requestedEligibilityDurationDays = $DurationDays
                requiresActivation          = $true
            }
        }
    }

    $requestId = [guid]::NewGuid().ToString()
    $requestUrl = "https://management.azure.com$scope/providers/Microsoft.Authorization/roleEligibilityScheduleRequests/${requestId}?api-version=2020-10-01"
    $body = [ordered]@{
        properties = [ordered]@{
            principalId     = $PrincipalId
            roleDefinitionId = $roleDefinitionId
            requestType     = 'AdminAssign'
            justification   = $Justification
            scheduleInfo    = [ordered]@{
                startDateTime = $now.ToString('o')
                expiration    = [ordered]@{
                    type     = 'AfterDuration'
                    duration = "P${DurationDays}D"
                }
            }
        }
    } | ConvertTo-Json -Depth 8 -Compress
    $created = Get-AzJson -Args @('rest', '--method', 'put', '--url', $requestUrl, '--body', $body)
    if ($null -eq $created) {
        throw "PIM eligibility request $requestId returned no readable response for $PrincipalId at $Scope."
    }

    $createdProperties = if ($created.PSObject.Properties.Name -contains 'properties') { $created.properties } else { $created }
    if ($null -eq $createdProperties) {
        throw "PIM eligibility request $requestId returned malformed properties for $PrincipalId at $Scope."
    }
    $createdStatusProperty = $createdProperties.PSObject.Properties['status']
    $createdStatus = if ($createdStatusProperty) { [string]$createdStatusProperty.Value } else { '' }
    $pendingStatuses = @('Accepted', 'Granted', 'PendingApproval', 'PendingAdminDecision', 'PendingProvisioning', 'ProvisioningStarted')
    $failedStatuses = @('Failed', 'Denied', 'Canceled', 'Cancelled', 'Revoked', 'TimedOut', 'Invalid')
    if ($failedStatuses -contains $createdStatus) {
        throw "PIM eligibility request $requestId ended with status '$createdStatus' for $PrincipalId at $Scope."
    }
    if ([string]::IsNullOrWhiteSpace($createdStatus)) {
        throw "PIM eligibility request $requestId returned no status for $PrincipalId at $Scope."
    }
    if ($createdStatus -ne 'Provisioned' -and $createdStatus -notin $pendingStatuses) {
        throw "PIM eligibility request $requestId returned unrecognized status '$createdStatus' for $PrincipalId at $Scope."
    }
    if ($createdStatus -in $pendingStatuses) {
        for ($attempt = 1; $attempt -le $MaxPollingAttempts -and $createdStatus -in $pendingStatuses; $attempt++) {
            if ($PollingIntervalSeconds -gt 0) { Start-Sleep -Seconds $PollingIntervalSeconds }
            $request = Get-AzJson -Args @('rest', '--method', 'get', '--url', $requestUrl)
            if ($null -eq $request) {
                throw "PIM eligibility request $requestId could not be read while waiting for provisioning for $PrincipalId at $Scope."
            }
            $requestProperties = if ($request.PSObject.Properties.Name -contains 'properties') { $request.properties } else { $request }
            $requestStatusProperty = if ($null -ne $requestProperties) { $requestProperties.PSObject.Properties['status'] } else { $null }
            if (-not $requestStatusProperty) {
                throw "PIM eligibility request $requestId returned no status while waiting for provisioning for $PrincipalId at $Scope."
            }
            $createdStatus = [string]$requestStatusProperty.Value
            if ($failedStatuses -contains $createdStatus) {
                throw "PIM eligibility request $requestId ended with status '$createdStatus' for $PrincipalId at $Scope."
            }
            if ($createdStatus -ne 'Provisioned' -and $createdStatus -notin $pendingStatuses) {
                throw "PIM eligibility request $requestId returned unrecognized status '$createdStatus' for $PrincipalId at $Scope."
            }
        }
    }
    if ($createdStatus -ne 'Provisioned') {
        $displayStatus = if ([string]::IsNullOrWhiteSpace($createdStatus)) { '<missing>' } else { $createdStatus }
        throw "PIM eligibility request $requestId was not provisioned after $MaxPollingAttempts polling attempts; last status '$displayStatus' for $PrincipalId at $Scope."
    }
    return [pscustomobject]@{
        state                       = 'eligible-created'
        requestId                   = $requestId
        requestStatus               = $createdStatus
        roleDefinitionId            = $roleDefinitionId
        scope                       = $Scope
        eligibilityEndDateTime      = $now.AddDays($DurationDays).ToString('o')
        requestedEligibilityDurationDays = $DurationDays
        requiresActivation          = $true
    }
}

function Assert-AzLogin {
    <#
    .SYNOPSIS Fail fast when az is not logged in or the target subscription is unset.
    #>
    param([string]$SubscriptionId)
    $acct = Get-AzJson -Args @('account', 'show') -AllowFail
    if (-not $acct) { throw "Not logged in to Azure CLI. Run 'az login' first." }
    if ($SubscriptionId) {
        Invoke-Az -Args @('account', 'set', '--subscription', $SubscriptionId) | Out-Null
    }
}

# ---------------------------------------------------------------------------
# Report emission + exit convention
# ---------------------------------------------------------------------------

function ConvertTo-OnboardingMarkdown {
    <#
    .SYNOPSIS Render a stage summary object as a human-readable Markdown report.
    #>
    param([Parameter(Mandatory)][object]$Summary)

    $emoji = @{ 'Pass' = '✅'; 'Fail' = '❌'; 'Warn' = '⚠️'; 'Skip' = '⏭️'; 'Waived' = '🟡' }
    $verdictLine = if ($Summary.verdict -eq 'GO') { '✅ **GO** — all checks passed (or were waived).' }
    else { '❌ **NO-GO** — resolve the failed checks below, then re-run this stage.' }

    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("# $($Summary.title)")
    [void]$sb.AppendLine()
    [void]$sb.AppendLine($verdictLine)
    [void]$sb.AppendLine()
    [void]$sb.AppendLine("_Generated $($Summary.generated)_")
    [void]$sb.AppendLine()
    [void]$sb.AppendLine('## Summary')
    [void]$sb.AppendLine()
    [void]$sb.AppendLine('| Result | Count |')
    [void]$sb.AppendLine('|---|---|')
    [void]$sb.AppendLine("| ✅ Pass | $($Summary.pass) |")
    [void]$sb.AppendLine("| ❌ Fail | $($Summary.fail) |")
    [void]$sb.AppendLine("| ⚠️ Warn | $($Summary.warn) |")
    [void]$sb.AppendLine("| ⏭️ Skip | $($Summary.skip) |")
    [void]$sb.AppendLine("| 🟡 Waived | $($Summary.waived) |")
    [void]$sb.AppendLine("| **Total** | **$($Summary.total)** |")
    [void]$sb.AppendLine()

    # Render the full analysis (reason, underlying error, fix) for one flagged check.
    $renderFlag = {
        param($item, [string]$reasonLabel, [string]$fixLabel)
        [void]$sb.AppendLine("### $($emoji[[string]$item.status]) $($item.name) ($($item.fr))")
        [void]$sb.AppendLine()
        $reason = if ($item.detail) { [string]$item.detail } else { 'No additional detail was reported by the check.' }
        [void]$sb.AppendLine("- **$reasonLabel** $reason")
        $err = $null
        if ($item.PSObject.Properties.Name -contains 'data' -and $null -ne $item.data) {
            $err = ($item.data | ConvertTo-Json -Depth 8 -Compress)
        }
        if ($err -and $err -ne '{}' -and $err -ne 'null') {
            [void]$sb.AppendLine("- **Error / evidence:**")
            [void]$sb.AppendLine()
            [void]$sb.AppendLine('  ```json')
            foreach ($line in ($err -split "`n")) { [void]$sb.AppendLine("  $line") }
            [void]$sb.AppendLine('  ```')
        }
        if ($item.remediation) { [void]$sb.AppendLine("- **$fixLabel** $($item.remediation)") }
        [void]$sb.AppendLine()
    }

    $fails = @($Summary.results | Where-Object status -eq 'Fail')
    if ($fails.Count) {
        [void]$sb.AppendLine('## ❌ What to fix next')
        [void]$sb.AppendLine()
        [void]$sb.AppendLine("These checks failed and block a GO verdict. Resolve each one, then re-run this stage.")
        [void]$sb.AppendLine()
        foreach ($f in $fails) { & $renderFlag $f 'Why it failed:' 'Fix:' }
    }

    $warns = @($Summary.results | Where-Object status -eq 'Warn')
    if ($warns.Count) {
        [void]$sb.AppendLine('## ⚠️ Warnings (review, not blocking)')
        [void]$sb.AppendLine()
        [void]$sb.AppendLine("These did not block the stage but should be reviewed — they often indicate risk or a manual follow-up.")
        [void]$sb.AppendLine()
        foreach ($w in $warns) { & $renderFlag $w 'Why it was flagged:' 'Recommended action:' }
    }

    $waived = @($Summary.results | Where-Object status -eq 'Waived')
    if ($waived.Count) {
        [void]$sb.AppendLine('## 🟡 Waived (accepted exceptions)')
        [void]$sb.AppendLine()
        [void]$sb.AppendLine("A waiver was recorded for each of these, so they do not block the stage. Confirm the waiver is still valid.")
        [void]$sb.AppendLine()
        foreach ($wv in $waived) { & $renderFlag $wv 'What was waived:' 'Waiver note:' }
    }

    [void]$sb.AppendLine('## All checks')
    [void]$sb.AppendLine()
    [void]$sb.AppendLine('| Status | FR | Check | Detail |')
    [void]$sb.AppendLine('|---|---|---|---|')
    foreach ($r in $Summary.results) {
        $g = $emoji[[string]$r.status]
        $detail = ([string]$r.detail) -replace '\r?\n', ' ' -replace '\|', '\|'
        [void]$sb.AppendLine("| $g $($r.status) | $($r.fr) | $($r.name) | $detail |")
    }
    [void]$sb.AppendLine()
    return $sb.ToString()
}

function Write-OnboardingReport {
    <#
    .SYNOPSIS Emit machine JSON (-JsonPath), a Markdown report, and a human console table.
    .DESCRIPTION Writes JSON to -JsonPath, a sibling .md report (or -ReportPath), and prints a
    console table with a clear verdict and an actionable "Next steps" footer for any failures.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object[]]$Results,
        [Parameter(Mandatory)][string]$Title,
        [string]$JsonPath,
        [string]$ReportPath,
        [object]$Extra
    )
    $summary = [ordered]@{
        title     = $Title
        generated = (Get-Date).ToUniversalTime().ToString('o')
        total     = @($Results).Count
        pass      = @($Results | Where-Object status -eq 'Pass').Count
        fail      = @($Results | Where-Object status -eq 'Fail').Count
        warn      = @($Results | Where-Object status -eq 'Warn').Count
        skip      = @($Results | Where-Object status -eq 'Skip').Count
        waived    = @($Results | Where-Object status -eq 'Waived').Count
        verdict   = if (Test-AnyFailure $Results) { 'NO-GO' } else { 'GO' }
        results   = $Results
    }
    if ($Extra) { $summary['extra'] = $Extra }
    $summaryObj = [pscustomobject]$summary

    $json = ($summaryObj | ConvertTo-Json -Depth 12)
    if ($JsonPath) {
        $dir = Split-Path -Parent $JsonPath
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $json | Set-Content -LiteralPath $JsonPath -Encoding utf8
    }

    # Human-readable Markdown report: sibling of the JSON unless -ReportPath is given.
    if (-not $ReportPath -and $JsonPath) {
        $ReportPath = [System.IO.Path]::ChangeExtension($JsonPath, '.md')
    }
    if ($ReportPath) {
        $dir = Split-Path -Parent $ReportPath
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        (ConvertTo-OnboardingMarkdown -Summary $summaryObj) | Set-Content -LiteralPath $ReportPath -Encoding utf8
    }

    Write-Host ''
    Write-Host "== $Title =="
    $Results | ForEach-Object {
        $glyph = switch ($_.status) {
            'Pass' { '[PASS]' }; 'Fail' { '[FAIL]' }; 'Warn' { '[WARN]' }
            'Skip' { '[SKIP]' }; 'Waived' { '[WAIVED]' }
        }
        Write-Host ("{0,-9} {1,-8} {2}" -f $glyph, $_.fr, $_.name)
        if ($_.detail) { Write-Host ("           {0}" -f $_.detail) }
        if ($_.status -eq 'Fail' -and $_.remediation) { Write-Host ("           -> {0}" -f $_.remediation) }
    }
    Write-Host ''
    Write-Host ("Verdict: {0}  (pass={1} fail={2} warn={3} skip={4} waived={5})" -f `
            $summary.verdict, $summary.pass, $summary.fail, $summary.warn, $summary.skip, $summary.waived)

    # Actionable footer so a human operator knows exactly what to do next.
    $fails = @($Results | Where-Object status -eq 'Fail')
    if ($fails.Count) {
        Write-Host ''
        Write-Host 'Next steps — resolve these before re-running:'
        $i = 1
        foreach ($f in $fails) {
            $fix = if ($f.remediation) { $f.remediation } else { 'See detail above.' }
            Write-Host ("  {0}. {1} -> {2}" -f $i, $f.name, $fix)
            $i++
        }
    }
    if ($ReportPath) { Write-Host ''; Write-Host ("Report: {0}" -f $ReportPath) }
    return $summaryObj
}

function Complete-Stage {
    <#
    .SYNOPSIS Exit the process 0 when no failures, 1 otherwise (pipeline gate).
    #>
    param([Parameter(Mandatory)][object[]]$Results)
    if (Test-AnyFailure $Results) { exit 1 } else { exit 0 }
}

# ---------------------------------------------------------------------------
# CIDR / subnet math (Stage 1 planning)
# ---------------------------------------------------------------------------

function ConvertTo-UInt32Ip {
    param([Parameter(Mandatory)][string]$Ip)
    $bytes = ([System.Net.IPAddress]::Parse($Ip)).GetAddressBytes()
    [Array]::Reverse($bytes)
    return [System.BitConverter]::ToUInt32($bytes, 0)
}

function Get-CidrInfo {
    <#
    .SYNOPSIS Parse 'a.b.c.d/n' into network/broadcast/prefix and host count.
    #>
    param([Parameter(Mandatory)][string]$Cidr)
    $parts = $Cidr -split '/'
    if ($parts.Count -ne 2) { throw "Invalid CIDR: $Cidr" }
    $prefix = [int]$parts[1]
    if ($prefix -lt 0 -or $prefix -gt 32) { throw "Invalid prefix in CIDR: $Cidr" }
    $ipUint = [uint64](ConvertTo-UInt32Ip $parts[0])
    $all = [uint64]4294967295
    $hostMask = [uint64][math]::Pow(2, (32 - $prefix)) - 1
    $mask = $all - $hostMask
    $network = $ipUint -band $mask
    $broadcast = $network + $hostMask
    [pscustomobject]@{
        Cidr      = $Cidr
        Prefix    = $prefix
        Network   = $network
        Broadcast = $broadcast
        Count     = [uint64]$broadcast - [uint64]$network + 1
    }
}

function Test-CidrContains {
    <#
    .SYNOPSIS $true when $Inner is fully inside $Outer.
    #>
    param([Parameter(Mandatory)][string]$Outer, [Parameter(Mandatory)][string]$Inner)
    $o = Get-CidrInfo $Outer
    $i = Get-CidrInfo $Inner
    return ($i.Network -ge $o.Network -and $i.Broadcast -le $o.Broadcast)
}

function Test-CidrOverlap {
    <#
    .SYNOPSIS $true when two CIDR ranges overlap at all.
    #>
    param([Parameter(Mandatory)][string]$A, [Parameter(Mandatory)][string]$B)
    $x = Get-CidrInfo $A
    $y = Get-CidrInfo $B
    return ($x.Network -le $y.Broadcast -and $y.Network -le $x.Broadcast)
}

# ---------------------------------------------------------------------------
# Subnet role vocabulary (friendly planning-form names -> canonical roles)
# ---------------------------------------------------------------------------
# The planning-form template uses human-friendly subnet role names, while the
# code, Bicep templates and deployment payloads key off canonical roles. This
# single map is the source of truth so Stage 1 validation, Stage 2 provisioning
# and Stage 4 resolution all agree on the same vocabulary. Canonical roles map
# to themselves; friendly aliases map to their canonical equivalent.
$script:CanonicalSubnetRoles = @(
    'managedcluster', 'nodepool', 'agent-containerapp', 'workspace-containerapp',
    'search-containerapp', 'private-endpoints', 'spare'
)
$script:SubnetRoleAliases = @{
    'akssubnet'                   = 'managedcluster'
    'managedclustersubnet'        = 'managedcluster'
    'supercomputernodepoolsubnet' = 'nodepool'
    'nodepoolsubnet'              = 'nodepool'
    'agentsubnet'                 = 'agent-containerapp'
    'workspacesubnet'             = 'workspace-containerapp'
    'searchsubnet'                = 'search-containerapp'
    'privateendpointsubnet'       = 'private-endpoints'
    'privateendpointssubnet'      = 'private-endpoints'
    'managementsubnet'            = 'spare'
    'sparesubnet'                 = 'spare'
}

function Resolve-SubnetRole {
    <#
    .SYNOPSIS Normalise a planning-form subnet role to its canonical role name.
    .DESCRIPTION
        Canonical roles pass through unchanged. Known friendly aliases
        (e.g. 'aksSubnet' -> 'managedcluster') are mapped. Unknown roles are
        returned trimmed and lower-cased so callers can detect them.
    #>
    param([string]$Role)
    if ([string]::IsNullOrWhiteSpace($Role)) { return '' }
    $key = $Role.Trim().ToLowerInvariant()
    if ($script:CanonicalSubnetRoles -contains $key) { return $key }
    if ($script:SubnetRoleAliases.ContainsKey($key)) { return $script:SubnetRoleAliases[$key] }
    return $key
}

function Test-CanonicalSubnetRole {
    <#
    .SYNOPSIS $true when the (resolved) role is a recognised canonical role.
    #>
    param([string]$Role)
    $script:CanonicalSubnetRoles -contains (Resolve-SubnetRole $Role)
}

function Get-VcpuQuotaResult {
    <#
    .SYNOPSIS Check compute quota for the supercomputer pools Stage 4 deploys (check id vcpu-quota).
    .DESCRIPTION The configured system pool is validated at submit time, so a shortfall rejects the
    deployment ("Insufficient quota ... Total Regional vCPUs"). The configured node pool only needs
    headroom when it autoscales. Quota is shared across the subscription, so Stage 1 checks it at
    planning time and Stage 3 re-checks it before deploy.
    #>
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$Fr,
        [string]$RerunStage = 'this stage',
        [object[]]$SkuCatalog
    )
    $region = [string]$Config.workloadRegion
    $subscriptionId = [string]$Config.subscriptionId
    $systemSku = if ($Config.PSObject.Properties.Name -contains 'systemSku' -and $Config.systemSku) { [string]$Config.systemSku } else { 'Standard_D4s_v6' }
    $nodePoolSku = if ($Config.PSObject.Properties.Name -contains 'nodePoolVmSize' -and $Config.nodePoolVmSize) { [string]$Config.nodePoolVmSize } else { 'Standard_D4ds_v6' }
    $nodePoolMax = if ($Config.PSObject.Properties.Name -contains 'nodePoolMaxNodeCount' -and $null -ne $Config.nodePoolMaxNodeCount) { [int]$Config.nodePoolMaxNodeCount } else { 3 }
    if ($nodePoolMax -lt 0) {
        return New-CheckResult -Id 'vcpu-quota' -Name 'Compute vCPU quota' -Status 'Fail' -Fr $Fr `
            -Detail "nodePoolMaxNodeCount=$nodePoolMax is invalid; it must be zero or greater." `
            -Remediation 'Correct nodePoolMaxNodeCount and re-run Stage 1.'
    }

    if (-not $SkuCatalog) {
        $SkuCatalog = @(Get-AzJson -Args @('vm', 'list-skus', '--location', $region, '--resource-type', 'virtualMachines', '--subscription', $subscriptionId) -AllowFail)
    }
    $requirements = @(
        [pscustomobject]@{ sku = $systemSku; count = 3; purpose = 'system pool'; blocking = $true }
    )
    if ($nodePoolMax -gt 0) {
        $requirements += [pscustomobject]@{ sku = $nodePoolSku; count = $nodePoolMax; purpose = 'node-pool autoscale'; blocking = $false }
    }
    $resolved = @()
    foreach ($requirement in $requirements) {
        $record = @($SkuCatalog | Where-Object { $_.name -eq $requirement.sku } | Select-Object -First 1)
        $restrictions = @(if ($record.Count -and $record[0].PSObject.Properties.Name -contains 'restrictions') {
                $record[0].restrictions | Where-Object { $null -ne $_ }
            })
        if (-not $record.Count -or $restrictions.Count) {
            $reason = if (-not $record.Count) { 'not offered' } else { 'restricted for this subscription' }
            return New-CheckResult -Id 'vcpu-quota' -Name 'Compute vCPU quota' -Status 'Fail' -Fr $Fr `
                -Detail "$($requirement.sku) required for the $($requirement.purpose) is $reason in $region." `
                -Remediation "Choose an available SKU or region, resolve the subscription restriction, and re-run $RerunStage."
        }
        $family = [string]$record[0].family
        $vcpuCapability = @($record[0].capabilities | Where-Object { $_.name -eq 'vCPUs' } | Select-Object -First 1)
        $vcpuPerNode = 0
        if ([string]::IsNullOrWhiteSpace($family) -or -not $vcpuCapability.Count -or
            -not [int]::TryParse([string]$vcpuCapability[0].value, [ref]$vcpuPerNode) -or $vcpuPerNode -le 0) {
            return New-CheckResult -Id 'vcpu-quota' -Name 'Compute vCPU quota' -Status 'Fail' -Fr $Fr `
                -Detail "$($requirement.sku) returned incomplete family/vCPU metadata in $region; quota requirements cannot be calculated." `
                -Remediation "Confirm the VM SKU metadata and re-run $RerunStage."
        }
        $resolved += [pscustomobject]@{
            sku      = $requirement.sku
            family   = $family
            count    = $requirement.count
            purpose  = $requirement.purpose
            blocking = $requirement.blocking
            vcpus    = $vcpuPerNode * $requirement.count
        }
    }

    $sysNeed = [int]($resolved | Where-Object purpose -eq 'system pool' | Select-Object -ExpandProperty vcpus -First 1)
    $npNeed = 0
    foreach ($requirement in @($resolved | Where-Object purpose -eq 'node-pool autoscale')) {
        $npNeed += [int]$requirement.vcpus
    }
    $usage = Get-AzJson -Args @('vm', 'list-usage', '--location', $region, '--subscription', $subscriptionId) -AllowFail
    if (-not $usage) {
        return New-CheckResult -Id 'vcpu-quota' -Name 'Compute vCPU quota' -Status 'Warn' -Fr $Fr `
            -Detail "Could not read compute usage/quota for $region (az vm list-usage failed), so the supercomputer's $sysNeed-vCPU system pool requirement was not verified." `
            -Remediation "Confirm in the portal (Subscriptions > Usage + quotas) that subscription $subscriptionId has enough Total Regional and VM-family vCPUs for the configured SKUs, then re-run $RerunStage."
    }
    $quotaValues = @{}
    foreach ($u in @($usage)) {
        $current = [int]$u.currentValue
        $limit = [int]$u.limit
        $quotaValues[[string]$u.name.value] = [pscustomobject]@{
            current   = $current
            limit     = $limit
            available = $limit - $current
        }
    }
    $needs = [System.Collections.Generic.List[object]]::new()
    $needs.Add([pscustomobject]@{ quota = 'cores'; label = 'Total Regional vCPUs'; hard = $sysNeed; soft = $sysNeed + $npNeed })
    foreach ($familyGroup in @($resolved | Group-Object family)) {
        $systemVcpus = 0
        $allVcpus = 0
        foreach ($requirement in @($familyGroup.Group)) {
            $allVcpus += [int]$requirement.vcpus
            if ($requirement.blocking) { $systemVcpus += [int]$requirement.vcpus }
        }
        $purposes = ($familyGroup.Group | ForEach-Object { "$($_.sku) $($_.purpose)" }) -join ', '
        $needs.Add([pscustomobject]@{
                quota = $familyGroup.Name
                label = "$($familyGroup.Name) vCPUs ($purposes)"
                hard  = $systemVcpus
                soft  = $allVcpus
            })
    }
    $short = @(foreach ($n in $needs) {
            $a = if ($quotaValues.ContainsKey($n.quota)) { $quotaValues[$n.quota].available } else { 0 }
            if ($a -lt $n.soft) {
                [pscustomobject]@{ service = "Microsoft.Compute/$($n.quota)"; label = $n.label; region = $region; available = $a; required = $n.soft; blocking = ($a -lt $n.hard) }
            }
        })
    $summary = ($short | ForEach-Object { "$($_.label): available $($_.available), need $($_.required)" }) -join '; '
    $fix = "Request a quota increase for $region (Subscriptions > Usage + quotas, or: az quota update --resource-name <quota> --scope /subscriptions/$subscriptionId/providers/Microsoft.Compute/locations/$region --limit-object value=<new-limit> --resource-type dedicated), then re-run $RerunStage."
    if (@($short | Where-Object blocking).Count) {
        return New-CheckResult -Id 'vcpu-quota' -Name 'Compute vCPU quota' -Status 'Fail' -Fr $Fr `
            -Detail "Not enough compute quota for the supercomputer system pool (3 x $systemSku = $sysNeed vCPUs). Stage 4 would be rejected with 'Insufficient quota'. $summary." `
            -Remediation "$fix Or record a WAIVER row (check=vcpu-quota + justification) if the increase is already in flight." -Data $short
    }
    if ($short.Count) {
        return New-CheckResult -Id 'vcpu-quota' -Name 'Compute vCPU quota' -Status 'Warn' -Fr $Fr `
            -Detail "Enough quota to deploy the supercomputer system pool ($sysNeed vCPUs), but not for the node pool to autoscale to $nodePoolMax x $nodePoolSku ($npNeed vCPUs); jobs that need the node pool to scale out will stay pending. $summary." `
            -Remediation $fix -Data $short
    }
    $quotaData = @($needs | ForEach-Object {
            $value = $quotaValues[$_.quota]
            [pscustomobject]@{
                quota     = $_.quota
                label     = $_.label
                current   = $value.current
                limit     = $value.limit
                available = $value.available
                required  = $_.soft
            }
        })
    $detailParts = @($quotaData | ForEach-Object {
            "$($_.label) $($_.available) available ($($_.limit) limit - $($_.current) used; need $($_.required))"
        })
    New-CheckResult -Id 'vcpu-quota' -Name 'Compute vCPU quota' -Status 'Pass' -Fr $Fr `
        -Detail "$region quota headroom for the effective Stage 4 configuration: $($detailParts -join '; ')." `
        -Data ([pscustomobject]@{ requirements = $resolved; quotas = $quotaData })
}

function Get-AzJsonResult {
    param([Parameter(Mandatory)][string[]]$Args)

    $argList = @($Args)
    if ($argList -notcontains '-o' -and $argList -notcontains '--output') {
        $argList += @('-o', 'json')
    }
    try {
        $text = Invoke-Az -Args $argList
    }
    catch {
        return [pscustomobject]@{ succeeded = $false; data = $null; error = $_.Exception.Message }
    }
    if ([string]::IsNullOrWhiteSpace($text)) {
        return [pscustomobject]@{ succeeded = $false; data = $null; error = "az $($argList -join ' ') returned no output." }
    }
    try {
        return [pscustomobject]@{ succeeded = $true; data = ($text | ConvertFrom-Json -ErrorAction Stop); error = '' }
    }
    catch {
        return [pscustomobject]@{ succeeded = $false; data = $null; error = "az $($argList -join ' ') returned invalid JSON: $($_.Exception.Message)" }
    }
}

function Get-OptionalPropertyValue {
    param([object]$Object, [string]$Name)

    if ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name) {
        return $Object.$Name
    }
    return $null
}

function Get-DiscoveryResourceStateForQuota {
    param([string]$ResourceId, [string]$SubscriptionId)

    if ([string]::IsNullOrWhiteSpace($ResourceId)) { return 'NotConfigured' }
    $result = Get-AzJsonResult -Args @(
        'resource', 'show', '--ids', $ResourceId, '--api-version', '2026-06-01',
        '--subscription', $SubscriptionId
    )
    if (-not $result.succeeded) {
        if ($result.error -match '(?i)ResourceNotFound|could not be found|was not found') { return 'NotFound' }
        return 'Unknown'
    }
    $properties = Get-OptionalPropertyValue -Object $result.data -Name 'properties'
    $state = Get-OptionalPropertyValue -Object $properties -Name 'provisioningState'
    if ($state) {
        return [string]$state
    }
    return 'Unknown'
}

function Get-ModelQuotaResult {
    <#
    .SYNOPSIS Check gpt-5.4 GlobalStandard TPM quota for the workspace (check id model-quota).
    .DESCRIPTION The workspace creates gpt-5.4 (250K TPM) in its managed Foundry account and Stage 4
    adds chat model gpt-5-4 (200K TPM). A shortfall fails the workspace ~20 min into Stage 4 with a
    generic InternalServerError. A usage row alone does not prove deployability, so this check also
    confirms that gpt-5.4 exposes the GlobalStandard SKU in the workload region. Soft-deleted
    Foundry accounts keep their regional quota until purged.
    #>
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$Fr,
        [string]$RerunStage = 'this stage'
    )
    $region = [string]$Config.workloadRegion
    $subscriptionId = [string]$Config.subscriptionId
    $unverifiedStatus = if ($Fr -eq 'FR3.6e') { 'Fail' } else { 'Warn' }
    $workspaceNeed = 250
    $chatModelNeed = 200
    $workspaceState = 'NotConfigured'
    $chatModelState = 'NotConfigured'
    if ($Config.PSObject.Properties.Name -contains 'resourceGroup' -and $Config.resourceGroup -and
        $Config.PSObject.Properties.Name -contains 'names' -and $Config.names -and
        $Config.names.PSObject.Properties.Name -contains 'workspace' -and $Config.names.workspace) {
        $workspaceId = "/subscriptions/$subscriptionId/resourceGroups/$($Config.resourceGroup)/providers/Microsoft.Discovery/workspaces/$($Config.names.workspace)"
        $workspaceState = Get-DiscoveryResourceStateForQuota -ResourceId $workspaceId -SubscriptionId $subscriptionId
        $chatModelState = Get-DiscoveryResourceStateForQuota -ResourceId "$workspaceId/chatModelDeployments/gpt-5-4" -SubscriptionId $subscriptionId
        if ($workspaceState -eq 'Succeeded') { $workspaceNeed = 0 }
        if ($chatModelState -eq 'Succeeded') { $chatModelNeed = 0 }
    }
    $tpmNeed = $workspaceNeed + $chatModelNeed
    if ($tpmNeed -eq 0) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status 'Skip' -Fr $Fr `
            -Detail 'Workspace and validation chat model already exist in Succeeded state; the resumed deployment needs no additional GPT-5.4 TPM allocation.' `
            -Data ([pscustomobject]@{ region = $region; workspaceState = $workspaceState; chatModelState = $chatModelState; required = 0 })
    }

    $quotaName = 'OpenAI.GlobalStandard.gpt-5.4'
    $usageResult = Get-AzJsonResult -Args @(
        'cognitiveservices', 'usage', 'list', '-l', $region, '--subscription', $subscriptionId
    )
    if (-not $usageResult.succeeded) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail "Could not read $quotaName usage in $region for subscription $subscriptionId. $($usageResult.error)" `
            -Remediation "Confirm Azure sign-in and Cognitive Services Usages Reader (or Reader) at subscription scope, then re-run $RerunStage. An unverified Stage 3 quota check must be resolved or explicitly waived before deployment."
    }
    $usage = @($usageResult.data)
    $q = @($usage | Where-Object {
            $name = Get-OptionalPropertyValue -Object $_ -Name 'name'
            (Get-OptionalPropertyValue -Object $name -Name 'value') -eq $quotaName
        }) | Select-Object -First 1
    if (-not $q) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status 'Fail' -Fr $Fr `
            -Detail "Azure returned Cognitive Services usage for $region, but it did not contain the required metric $quotaName." `
            -Remediation "Verify that gpt-5.4 GlobalStandard quota is enabled for subscription $subscriptionId in $region, then re-run $RerunStage."
    }

    $modelsResult = Get-AzJsonResult -Args @(
        'cognitiveservices', 'model', 'list', '-l', $region, '--subscription', $subscriptionId
    )
    if (-not $modelsResult.succeeded) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail "$quotaName reports quota in $region, but regional model availability could not be verified for subscription $subscriptionId. $($modelsResult.error)" `
            -Remediation "Resolve the Azure CLI, authorization, network, or API error and re-run $RerunStage. An unverified Stage 3 quota check must be resolved or explicitly waived before deployment."
    }
    $models = @($modelsResult.data)

    $compatibleModels = @(foreach ($record in $models) {
            $kind = [string](Get-OptionalPropertyValue -Object $record -Name 'kind')
            $model = Get-OptionalPropertyValue -Object $record -Name 'model'
            $modelName = [string](Get-OptionalPropertyValue -Object $model -Name 'name')
            if ($kind -ne 'OpenAI' -or $modelName -ne 'gpt-5.4') { continue }
            $compatibleSku = @(Get-OptionalPropertyValue -Object $model -Name 'skus' | Where-Object {
                    (Get-OptionalPropertyValue -Object $_ -Name 'name') -eq 'GlobalStandard' -and
                    (Get-OptionalPropertyValue -Object $_ -Name 'usageName') -eq $quotaName
                }) | Select-Object -First 1
            if ($compatibleSku) {
                [pscustomobject]@{ record = $record; model = $model; sku = $compatibleSku }
            }
        })
    if (-not $compatibleModels.Count) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status 'Fail' -Fr $Fr `
            -Detail "$quotaName reports quota in $region, but the regional catalog contains no OpenAI gpt-5.4 version with a matching GlobalStandard SKU." `
            -Remediation "Choose a region with an OpenAI gpt-5.4 GlobalStandard version whose usageName is '$quotaName', or have the subscription/model enabled there, then re-run $RerunStage."
    }
    $defaultModels = @($compatibleModels | Where-Object {
            (Get-OptionalPropertyValue -Object $_.model -Name 'isDefaultVersion') -eq $true
        })
    $selectionPool = if ($defaultModels.Count) { $defaultModels } else { $compatibleModels }
    $selectedModel = $selectionPool | Sort-Object {
        [string](Get-OptionalPropertyValue -Object $_.model -Name 'version')
    } -Descending | Select-Object -First 1
    $modelRecord = $selectedModel.record
    $model = $selectedModel.model
    $sku = $selectedModel.sku
    $modelVersion = [string](Get-OptionalPropertyValue -Object $model -Name 'version')
    if ([string]::IsNullOrWhiteSpace($modelVersion)) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail 'The resolver-compatible OpenAI gpt-5.4 GlobalStandard catalog record did not report a version; deployment support is unverified.' `
            -Remediation "Resolve the incomplete regional model metadata, then re-run $RerunStage."
    }

    $lifecycleStatus = [string](Get-OptionalPropertyValue -Object $model -Name 'lifecycleStatus')
    if ([string]::IsNullOrWhiteSpace($lifecycleStatus)) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail "Resolver-compatible OpenAI gpt-5.4 version $modelVersion in $region did not report lifecycleStatus, so deployment support is unverified." `
            -Remediation "Confirm the target version is supported by Discovery, then re-run $RerunStage."
    }
    if ($lifecycleStatus -ne 'GenerallyAvailable') {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status 'Fail' -Fr $Fr `
            -Detail "Resolver-compatible OpenAI gpt-5.4 version $modelVersion is present in $region, but lifecycleStatus is '$lifecycleStatus'. This onboarding flow supports GenerallyAvailable versions only." `
            -Remediation "Use a GenerallyAvailable version supported by Discovery, then re-run $RerunStage."
    }

    $quotaStatus = [string](Get-OptionalPropertyValue -Object $q -Name 'status')
    if ($quotaStatus -in @('Blocked', 'InOverage')) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status 'Fail' -Fr $Fr `
            -Detail "$quotaName in $region has blocking quota status '$quotaStatus'; its numeric limit is not usable evidence that Stage 4 can allocate TPM." `
            -Remediation "Resolve the $quotaStatus quota status for gpt-5.4 GlobalStandard in $region, then re-run $RerunStage."
    }
    if ($quotaStatus -and $quotaStatus -notin @('Included', 'Blocked', 'InOverage')) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail "$quotaName in $region returned unrecognized quota status '$quotaStatus'; deployment readiness is unverified." `
            -Remediation "Confirm the meaning of quota status '$quotaStatus' and that allocation is allowed, then re-run $RerunStage."
    }

    $numberStyle = [Globalization.NumberStyles]::Float
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $tokenRate = $null
    $tokenRateCount = 0.0
    $malformedTokenRate = $null
    foreach ($rate in @(Get-OptionalPropertyValue -Object $sku -Name 'rateLimits')) {
        $rateKey = [string](Get-OptionalPropertyValue -Object $rate -Name 'key')
        $rules = @(Get-OptionalPropertyValue -Object $rate -Name 'rules')
        $tokenRule = @($rules | Where-Object {
                (Get-OptionalPropertyValue -Object $_ -Name 'key') -eq 'token'
            } | Select-Object -First 1)
        if ($rateKey -ne 'token' -and -not $tokenRule.Count) { continue }
        $rawRenewalPeriod = Get-OptionalPropertyValue -Object $rate -Name 'renewalPeriod'
        $rawTokenRateCount = Get-OptionalPropertyValue -Object $rate -Name 'count'
        $renewalPeriod = 0.0
        $parsedTokenRateCount = 0.0
        $hasRenewalPeriod = $null -ne $rawRenewalPeriod -and
            [double]::TryParse([string]$rawRenewalPeriod, $numberStyle, $culture, [ref]$renewalPeriod)
        $hasTokenRateCount = $null -ne $rawTokenRateCount -and
            [double]::TryParse([string]$rawTokenRateCount, $numberStyle, $culture, [ref]$parsedTokenRateCount)
        if (-not $hasRenewalPeriod -or -not $hasTokenRateCount) {
            $malformedTokenRate = [pscustomobject]@{ renewalPeriod = $rawRenewalPeriod; count = $rawTokenRateCount }
            continue
        }
        if ($renewalPeriod -eq 60) {
            $tokenRate = $rate
            $tokenRateCount = $parsedTokenRateCount
            break
        }
    }
    if (-not $tokenRate -and $malformedTokenRate) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail "$quotaName returned malformed token rate-limit metadata (renewalPeriod='$($malformedTokenRate.renewalPeriod)', count='$($malformedTokenRate.count)'); quota-unit conversion is unverified." `
            -Remediation "Resolve the malformed regional model metadata, then re-run $RerunStage."
    }
    if (-not $tokenRate -or $tokenRateCount -ne 1000) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail "$quotaName did not expose the expected conversion of one capacity unit to 1,000 tokens per minute; numeric quota values cannot be safely interpreted as K TPM." `
            -Remediation "Confirm the current GlobalStandard gpt-5.4 quota-unit conversion in the regional model metadata, then re-run $RerunStage."
    }

    $currentValue = 0.0
    $limit = 0.0
    $rawCurrentValue = Get-OptionalPropertyValue -Object $q -Name 'currentValue'
    $rawLimit = Get-OptionalPropertyValue -Object $q -Name 'limit'
    $hasCurrent = $null -ne $rawCurrentValue -and
        [double]::TryParse([string]$rawCurrentValue, $numberStyle, $culture, [ref]$currentValue)
    $hasLimit = $null -ne $rawLimit -and
        [double]::TryParse([string]$rawLimit, $numberStyle, $culture, [ref]$limit)
    if (-not $hasCurrent -or -not $hasLimit -or $currentValue -lt 0 -or $limit -lt 0 -or $currentValue -gt $limit) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status $unverifiedStatus -Fr $Fr `
            -Detail "$quotaName returned invalid usage values (currentValue='$rawCurrentValue', limit='$rawLimit'); deployment readiness is unverified." `
            -Remediation "Resolve the malformed or inconsistent Cognitive Services usage response, then re-run $RerunStage."
    }

    $free = $limit - $currentValue
    $data = [pscustomobject]@{
        quota          = $quotaName
        quotaStatus    = $quotaStatus
        quotaUnit      = '1K TPM'
        region         = $region
        modelVersion   = $modelVersion
        lifecycleStatus = $lifecycleStatus
        workspaceState = $workspaceState
        chatModelState = $chatModelState
        used           = $currentValue
        limit          = $limit
        available      = $free
        required       = $tpmNeed
    }
    if ($free -lt $tpmNeed) {
        return New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status 'Fail' -Fr $Fr `
            -Detail "$quotaName in ${region}: ${free}K TPM free ($currentValue/$limit used), need ${tpmNeed}K (workspace remaining=${workspaceNeed}K, chat model remaining=${chatModelNeed}K). Stage 4 would fail with InsufficientQuota." `
            -Remediation "GlobalStandard quota is scoped by subscription, region, model, and deployment type. Identify unused gpt-5.4 allocations in $region or request more quota in Foundry > Manage > Quota, then re-run $RerunStage. Soft-deleted accounts can retain quota; purge one only after its owner confirms it is unrecoverable and accepts permanent data loss. Or record a WAIVER row (check=model-quota + justification) if the increase is already in flight." -Data $data
    }
    New-CheckResult -Id 'model-quota' -Name 'Model TPM quota' -Status 'Pass' -Fr $Fr `
        -Detail "Catalog and quota prerequisites satisfied at check time for resolver-compatible OpenAI gpt-5.4 version $modelVersion GlobalStandard in ${region}: ${free}K TPM free, need ${tpmNeed}K. The additional chat deployment resolves a compatible default version, or the latest compatible version when no default exists; the workspace may use a service-pinned version. This does not prove live capacity, deployment permission, policy compliance, or successful inference; recheck immediately before allocation." -Data $data
}

Export-ModuleMember -Function `
    New-CheckResult, Test-AnyFailure, Get-OnboardingConfig, Test-CustomerJitManagedUser, Test-ConfigWaiver, `
    Invoke-Az, Get-AzJson, Set-PimRoleEligibility, Assert-AzLogin, Write-OnboardingReport, Complete-Stage, `
    ConvertTo-UInt32Ip, Get-CidrInfo, Test-CidrContains, Test-CidrOverlap, `
    Resolve-SubnetRole, Test-CanonicalSubnetRole, Get-VcpuQuotaResult, Get-ModelQuotaResult
