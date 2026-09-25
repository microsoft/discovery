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
        $out = & az @Args 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
    }
    if ($code -ne 0 -and -not $AllowFail) {
        throw "az $($Args -join ' ') failed (exit $code): $($out -join "`n")"
    }
    if ($code -ne 0) { return '' }
    return ($out -join "`n")
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

function Write-OnboardingReport {
    <#
    .SYNOPSIS Emit machine JSON (to -JsonPath and/or stdout) and a human table.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object[]]$Results,
        [Parameter(Mandatory)][string]$Title,
        [string]$JsonPath,
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

    $json = ([pscustomobject]$summary | ConvertTo-Json -Depth 12)
    if ($JsonPath) {
        $dir = Split-Path -Parent $JsonPath
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $json | Set-Content -LiteralPath $JsonPath -Encoding utf8
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
    return [pscustomobject]$summary
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

Export-ModuleMember -Function `
    New-CheckResult, Test-AnyFailure, Get-OnboardingConfig, Test-ConfigWaiver, `
    Invoke-Az, Get-AzJson, Assert-AzLogin, Write-OnboardingReport, Complete-Stage, `
    ConvertTo-UInt32Ip, Get-CidrInfo, Test-CidrContains, Test-CidrOverlap
