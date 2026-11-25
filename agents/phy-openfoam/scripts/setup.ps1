#Requires -Version 7.0
<# Compatibility entry point: runtime installation only. #>
[CmdletBinding()]
param(
    [string]$Image = 'localhost/phy-openfoam:0.2.1',
    [switch]$SkipImage,
    [string]$InstallRoot,
    [string]$PythonExecutable,
    [ValidateSet('auto', 'podman', 'docker')][string]$Runtime,
    [switch]$Development,
    [switch]$Editable
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'install-runtime.ps1') @PSBoundParameters
if (-not $?) { throw 'Runtime installation failed.' }
