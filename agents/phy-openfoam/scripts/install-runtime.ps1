#Requires -Version 7.0
<#
.SYNOPSIS
  Install the phy-openfoam host CLI and optional Linux/AMD64 worker image.
.DESCRIPTION
  Runtime only: never edits a Discovery project, installs skills, changes VM
  configuration, enables unenforced limits, or publishes an image. Windows x64
  is the qualified installer target. The operator owns all configuration.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$InstallRoot = $(if ($env:DISCOVERY_PHYSICS_HOME) { $env:DISCOVERY_PHYSICS_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'DiscoveryPhysics' } else { Join-Path $HOME 'DiscoveryPhysics' }),
    [string]$PythonExecutable = 'python',
    [ValidateSet('auto', 'podman', 'docker')][string]$Runtime = 'auto',
    [string]$Image = 'localhost/phy-openfoam:0.2.1',
    [switch]$SkipImage,
    [switch]$Development,
    [switch]$Editable
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -or [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
    throw 'This installer is qualified for Windows x64 only. See docs/installation.md for platform boundaries.'
}
if ([string]::IsNullOrWhiteSpace($Image) -or $Image.StartsWith('-')) { throw 'Image must be an image reference.' }
$entry = Split-Path -Parent $PSScriptRoot
$tool = Join-Path $entry 'tools/openfoam'
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$entryPrefix = [System.IO.Path]::GetFullPath($entry).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if ($InstallRoot -eq $entry.TrimEnd('\', '/') -or $InstallRoot.StartsWith($entryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'InstallRoot must be outside the catalog source entry.'
}
if (-not $PSCmdlet.ShouldProcess($InstallRoot, 'Install host CLI and selected image; no project changes')) { return }
Get-Command $PythonExecutable -ErrorAction Stop | Out-Null
& $PythonExecutable -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
if ($LASTEXITCODE) { throw 'Python version check failed.' }
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$venv = Join-Path $InstallRoot 'venv'
$py = Join-Path $venv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {
    & $PythonExecutable -m venv $venv
    if ($LASTEXITCODE) { throw 'Virtual environment creation failed.' }
}
$target = if ($Development) { "$tool[dev]" } else { $tool }
$pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check')
if ($Editable) { $pipArgs += '-e' }
& $py @pipArgs $target
if ($LASTEXITCODE) { throw 'Package installation failed.' }

$selected = $Runtime
if (-not $SkipImage) {
    if ($selected -eq 'auto') {
        $selected = if (Get-Command podman -ErrorAction SilentlyContinue) { 'podman' } elseif (Get-Command docker -ErrorAction SilentlyContinue) { 'docker' } else { throw 'Install and start Podman or Docker before building the image.' }
    }
    Get-Command $selected -ErrorAction Stop | Out-Null
    & $selected info | Out-Null
    if ($LASTEXITCODE) { throw 'Container runtime is not ready. An operator must start/configure it; this installer will not reconfigure the host.' }
    & $selected build --platform linux/amd64 --tag $Image --file (Join-Path $tool 'Dockerfile') $tool
    if ($LASTEXITCODE) { throw 'Worker image build failed.' }
    $imageId = (& $selected image inspect $Image --format '{{.Id}}' | Out-String).Trim()
    if ($LASTEXITCODE -or -not $imageId) { throw 'Built image identity could not be inspected.' }
} else {
    $imageId = $null
}
$cli = Join-Path $venv 'Scripts/discovery-physics.exe'
& $cli schema | Out-Null
if ($LASTEXITCODE) { throw 'Installed CLI failed its schema smoke test.' }

$configPath = if ($env:DISCOVERY_PHYSICS_CONFIG) { $env:DISCOVERY_PHYSICS_CONFIG } else { Join-Path $InstallRoot 'config.json' }
$cfg = if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -AsHashtable } else { @{} }
if ($cfg -isnot [System.Collections.IDictionary]) { throw 'Existing operator configuration must be a JSON object; it was not overwritten.' }
# Preserve operator policy, especially limit enforcement and concurrency.
$cfg['image'] = $Image
$cfg['runtime'] = $selected
$parent = Split-Path -Parent ([System.IO.Path]::GetFullPath($configPath))
New-Item -ItemType Directory -Force -Path $parent | Out-Null
[System.IO.File]::WriteAllText($configPath, (($cfg | ConvertTo-Json -Depth 20) + "`n"), [System.Text.UTF8Encoding]::new($false))
$receipt = [ordered]@{
    version = '0.2.1'; cli = $cli; image = $Image; image_id = $imageId
    runtime = $selected; config = $configPath; editable = [bool]$Editable
    image_built = -not [bool]$SkipImage; schema_smoke_test = $true
    solver_smoke_test = $false; timestamp_utc = [DateTime]::UtcNow.ToString('o')
}
[System.IO.File]::WriteAllText((Join-Path $InstallRoot 'runtime-install.json'), (($receipt | ConvertTo-Json) + "`n"), [System.Text.UTF8Encoding]::new($false))
Write-Host "Host CLI installed: $cli"
Write-Host 'Workspace integration is separate: save the skill manually or run install-workspace.ps1.'
if ($SkipImage) { Write-Warning 'Image build was skipped; schema parsing does not establish worker readiness.' }
if ($InstallRoot -ne (Join-Path $env:LOCALAPPDATA 'DiscoveryPhysics')) {
    Write-Host 'For a custom installation, set DISCOVERY_PHYSICS_HOME and DISCOVERY_PHYSICS_CLI in the Discovery process environment.'
}