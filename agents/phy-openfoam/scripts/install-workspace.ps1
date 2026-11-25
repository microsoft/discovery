#Requires -Version 7.0
<#
.SYNOPSIS
    Copy the complete phy-openfoam skill and optional companion into an existing project.
.DESCRIPTION
    Includes supplied scripts/resources, excluding caches and Python bytecode.
    Does not install Python, build an image, register MCP, or change project-wide instructions.
    Preflights all sources/destinations before copying. Existing differing files
    cause a refusal unless the operator supplies -Force; identical files are unchanged.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$ProjectPath,
    [switch]$IncludeAgent,
    [switch]$Force,
    [string]$RuntimeExecutable
)
$ErrorActionPreference = 'Stop'
$entry = Split-Path -Parent $PSScriptRoot
$project = (Resolve-Path -LiteralPath $ProjectPath -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $project -PathType Container)) { throw 'ProjectPath must be an existing directory.' }
if ($RuntimeExecutable -and -not (Test-Path -LiteralPath $RuntimeExecutable -PathType Leaf)) {
    throw 'RuntimeExecutable must name an installed discovery-physics executable.'
}
$skillSource = Join-Path $entry 'skills/phy-openfoam'
foreach ($required in @('SKILL.md', 'scripts/render_report.py', 'scripts/project_results.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $skillSource $required) -PathType Leaf)) {
        throw "Required skill resource is missing; nothing copied: $required"
    }
}
$excludedDirectories = @(
    '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', '.git',
    '.venv', 'venv', '.tox', '.nox', 'node_modules', 'build', 'dist'
)
function Get-SuppliedSkillFiles {
    param([string]$Directory, [string]$Relative = '')
    foreach ($item in (Get-ChildItem -LiteralPath $Directory -Force | Sort-Object Name)) {
        if ($item.PSIsContainer -and ($item.Name -in $excludedDirectories -or
                $item.Name -like '*.egg-info' -or $item.Name -like '*.dist-info')) { continue }
        if (-not $item.PSIsContainer -and ($item.Extension -in @('.pyc', '.pyo') -or
                $item.Name -in @('.DS_Store', 'Thumbs.db', '.coverage'))) { continue }
        if ($item.LinkType) { throw "Linked skill resource requires review; nothing copied: $($item.FullName)" }
        $relativeItem = if ($Relative) { Join-Path $Relative $item.Name } else { $item.Name }
        if ($item.PSIsContainer) {
            Get-SuppliedSkillFiles -Directory $item.FullName -Relative $relativeItem
        } else {
            @{ Source = $item.FullName; Relative = (Join-Path '.github/skills/phy-openfoam' $relativeItem) }
        }
    }
}
$files = @(Get-SuppliedSkillFiles -Directory $skillSource)
if ($IncludeAgent) {
    $files += @{ Source = (Join-Path $entry 'integrations/phy-openfoam.agent.md'); Relative = '.github/agents/phy-openfoam.agent.md' }
}
$pending = @()
foreach ($file in $files) {
    $source = Get-Item -LiteralPath $file.Source -Force
    if ($source.PSIsContainer -or $source.LinkType) { throw "Source must be a regular file; nothing copied: $($file.Source)" }
    $sourceHash = (Get-FileHash -LiteralPath $file.Source -Algorithm SHA256).Hash
    $destination = Join-Path $project $file.Relative
    $parent = Split-Path -Parent $destination
    while ($parent -and $parent -ne $project) {
        if (Test-Path -LiteralPath $parent) {
            $directory = Get-Item -LiteralPath $parent -Force
            if (-not $directory.PSIsContainer -or $directory.LinkType) {
                throw "Destination parent must be an unlinked directory; nothing copied: $parent"
            }
        }
        $parent = Split-Path -Parent $parent
    }
    if (Test-Path -LiteralPath $destination) {
        $target = Get-Item -LiteralPath $destination -Force
        if ($target.PSIsContainer -or $target.LinkType) { throw "Destination is not a regular file; nothing copied: $destination" }
        if ($sourceHash -eq (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash) { continue }
        if (-not $Force) { throw "Existing file differs; nothing copied. Review and use -Force explicitly if appropriate: $destination" }
    }
    $pending += @{ Source = $file.Source; Destination = $destination }
}
foreach ($file in $pending) {
    if ($PSCmdlet.ShouldProcess($file.Destination, 'Install phy-openfoam workspace integration')) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file.Destination) | Out-Null
        Copy-Item -LiteralPath $file.Source -Destination $file.Destination -Force
    }
}
Write-Host 'Complete skill location: .github/skills/phy-openfoam/ (SKILL.md, reporting/results helpers, and supplied resources; skills is plural).'
Write-Host 'No runtime, credentials, operator policy, or project instructions were changed.'
if ($RuntimeExecutable) {
    Write-Host 'Set DISCOVERY_PHYSICS_CLI to the supplied executable path in the environment used to launch Discovery.'
}