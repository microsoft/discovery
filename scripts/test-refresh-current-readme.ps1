# Mirrors the Python regex substitutions inside .github/workflows/refresh-current.yml
# (the "Patch README.md" step). Runs against a copy of the real README so you can
# see exactly what the workflow's PR would look like — without touching the real file.
#
# Usage:
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/test-refresh-current-readme.ps1
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/test-refresh-current-readme.ps1 `
#        -NewVersion v0.15.13 -PreviousVersion v0.15.12 -PreviousDate 2026-08-28

param(
    [string] $NewVersion      = 'v0.15.13',
    [string] $PreviousVersion = 'v0.15.12',
    [string] $PreviousDate    = '2026-08-28'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$readme   = Join-Path $repoRoot 'README.md'
if (-not (Test-Path $readme)) { throw "README.md not found at $readme" }

$prevBare = $PreviousVersion.TrimStart('v')
$original = Get-Content -Raw -LiteralPath $readme

# 1. Header "Current release: <strong>vX.Y.Z</strong>"
$headerPattern = '(Current release:\s*<strong>)v\d+\.\d+\.\d+(</strong>)'
if ([regex]::Matches($original, $headerPattern).Count -ne 1) {
    throw "Header regex did not match exactly once in README.md"
}
$patched = [regex]::Replace($original, $headerPattern, "`${1}$NewVersion`${2}", 1)

# 2. Previous rows — Windows x64 and Windows Arm64
function Update-PreviousRow {
    param(
        [string] $Text,
        [string] $Arch  # 'x64' or 'Arm64'
    )
    $pat = '\|\s*v\d+\.\d+\.\d+\s*_\(previous\)_\s*\|\s*\d{4}-\d{2}-\d{2}\s*\|\s*Windows\s+' `
         + [regex]::Escape($Arch) `
         + '\s*\|\s*\[`Discovery-app-\d+\.\d+\.\d+-preview-win-([A-Za-z0-9]+)\.exe`\]' `
         + '\((https://aka\.ms/discovery/download/[^)]+)\)\s*\|'
    $rx  = [regex]::new($pat)
    $ms  = $rx.Matches($Text)
    if ($ms.Count -ne 1) {
        throw "Previous-row regex for Windows $Arch matched $($ms.Count) times (expected 1)"
    }
    return $rx.Replace($Text, {
        param($m)
        $archSuffix = $m.Groups[1].Value
        $url        = $m.Groups[2].Value
        $bt         = [char]0x60  # PowerShell escape-char is backtick; build one literally.
        "| $PreviousVersion _(previous)_ | $PreviousDate | Windows $Arch | [${bt}Discovery-app-$prevBare-preview-win-$archSuffix.exe${bt}]($url) |"
    }, 1)
}

$patched = Update-PreviousRow -Text $patched -Arch 'x64'
$patched = Update-PreviousRow -Text $patched -Arch 'Arm64'

if ($patched -eq $original) { throw "No changes produced; the inputs match the current README state." }

# Diff view.
$tempOriginal = [System.IO.Path]::GetTempFileName()
$tempPatched  = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $tempOriginal -Value $original -NoNewline
    Set-Content -LiteralPath $tempPatched  -Value $patched  -NoNewline

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $git) {
        Write-Host "----- diff (unified) -----"
        & git --no-pager diff --no-index --color=never -- $tempOriginal $tempPatched
        Write-Host "----- end diff -----"
    } else {
        Write-Host "----- old header -----"
        Select-String -InputObject $original -Pattern 'Current release.*<strong>v[^<]+</strong>' | ForEach-Object { $_.Matches[0].Value }
        Write-Host "----- new header -----"
        Select-String -InputObject $patched  -Pattern 'Current release.*<strong>v[^<]+</strong>' | ForEach-Object { $_.Matches[0].Value }
    }
} finally {
    Remove-Item $tempOriginal, $tempPatched -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "OK: patcher would rewrite README.md as shown above."
Write-Host "    NewVersion      = $NewVersion"
Write-Host "    PreviousVersion = $PreviousVersion"
Write-Host "    PreviousDate    = $PreviousDate"
