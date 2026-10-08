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
        names, deployingIdentity). Throws on missing required fields.
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

    $required = @('schemaVersion', 'subscriptionId', 'controlPlaneRegion', 'workloadRegion', 'network', 'sizingTier', 'names', 'deployingIdentity')
    $missing = @()
    foreach ($f in $required) {
        if (-not ($cfg.PSObject.Properties.Name -contains $f) -or $null -eq $cfg.$f) { $missing += $f }
    }
    if ($missing.Count) {
        throw "Config missing required field(s): $($missing -join ', ')"
    }
    return $cfg
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

Export-ModuleMember -Function `
    New-CheckResult, Test-AnyFailure, Get-OnboardingConfig, Test-ConfigWaiver, `
    Invoke-Az, Get-AzJson, Assert-AzLogin, Write-OnboardingReport, Complete-Stage, `
    ConvertTo-UInt32Ip, Get-CidrInfo, Test-CidrContains, Test-CidrOverlap, `
    Resolve-SubnetRole, Test-CanonicalSubnetRole
