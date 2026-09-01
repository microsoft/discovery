# Mirrors the parsing logic in .github/workflows/probe-aka-ms.yml, using
# curl.exe (bundled with Windows 10+ / Git for Windows) so the byte-for-byte
# behaviour is comparable to the Ubuntu runner.

$ErrorActionPreference = 'Stop'

$currentUrl  = 'https://aka.ms/discovery/download/current'
$previousUrl = 'https://aka.ms/discovery/download/previous'

function Resolve-AkaTarget {
    param([Parameter(Mandatory)][string] $Url)
    $target = & curl.exe -sI -o NUL -w '%header{location}' $Url
    if ([string]::IsNullOrWhiteSpace($target)) { throw "No Location header on $Url" }
    $m = [regex]::Match($target, 'Discovery-app-(\d+\.\d+\.\d+)-preview-win-x64\.exe')
    if (-not $m.Success) { throw "No version match in redirect target: $target" }
    [pscustomobject]@{ Version = "v$($m.Groups[1].Value)"; Target = $target }
}

$current  = Resolve-AkaTarget -Url $currentUrl
$previous = Resolve-AkaTarget -Url $previousUrl

Write-Host "aka.ms current  ->" $current.Version
Write-Host "                  " $current.Target
Write-Host "aka.ms previous ->" $previous.Version
Write-Host "                  " $previous.Target

# README's current version.
$readme = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot '..\README.md')
$readmeMatch = [regex]::Match($readme, 'Current release:\s*<strong>(v\d+\.\d+\.\d+)</strong>')
if (-not $readmeMatch.Success) { throw 'Could not parse "Current release: <strong>vX.Y.Z</strong>" from README.md' }
$readmeCurrent = $readmeMatch.Groups[1].Value
Write-Host "README current  ->" $readmeCurrent

# Last-Modified on the previous blob → previous_date.
$prevLastMod = & curl.exe -sI -o NUL -w '%header{last-modified}' $previous.Target
Write-Host "previous Last-Modified header ->" $prevLastMod
if ([string]::IsNullOrWhiteSpace($prevLastMod)) {
    $prevDate = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    Write-Host "previous_date (fallback: today UTC) ->" $prevDate
} else {
    $prevDate = ([datetimeoffset]::Parse($prevLastMod)).ToUniversalTime().ToString('yyyy-MM-dd')
    Write-Host "previous_date ->" $prevDate
}

# Decision matrix identical to the workflow.
if ($current.Version -eq $readmeCurrent) {
    Write-Host ""
    Write-Host "DECISION: no-op (README already at $readmeCurrent)"
    exit 0
}
if ($current.Version -eq $previous.Version) {
    Write-Host ""
    Write-Host "DECISION: defer (aka.ms current == previous == $($current.Version))"
    exit 0
}
Write-Host ""
Write-Host "DECISION: would dispatch refresh-current.yml with:"
Write-Host "  version          = $($current.Version)"
Write-Host "  previous_version = $($previous.Version)"
Write-Host "  previous_date    = $prevDate"
