#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build RetroChimera container images and push to ACR.

.DESCRIPTION
    Builds one or more of the five RetroChimera Docker images:
      deps        - Conda/pip dependencies (~3.6 GB, rebuild on version bumps)
      checkpoint  - Pistachio model checkpoint (~4 GB, build once)
      bb          - eMolecules building blocks (~200 MB, rebuild monthly)
      main        - Full runtime image (pulls deps + checkpoint + bb from ACR, uses Dockerfile.fast)
      allinone    - Standalone image (no ACR dependencies, uses default Dockerfile)

.PARAMETER Target
    Which image(s) to build. One of: deps, checkpoint, bb, main, allinone, all.
    "all" builds deps, checkpoint, bb, then main (in dependency order).

.PARAMETER AcrName
    ACR registry name (without .azurecr.io). Required.

.PARAMETER CheckpointTag
    Tag for the checkpoint image. Default: v1

.PARAMETER DepsTag
    Tag for the deps image. Default: 1.1.0

.PARAMETER BbTag
    Tag for the building blocks image. Default: 2026-04

.PARAMETER MainTag
    Tag for the main/allinone image. Default: latest

.PARAMETER BbUrl
    Override the eMolecules building blocks download URL.

.EXAMPLE
    .\build-acr.ps1 -Target all -AcrName mdqacr
    .\build-acr.ps1 -Target main -AcrName mdqacr
    .\build-acr.ps1 -Target deps -AcrName mdqacr -DepsTag 1.2.0
    .\build-acr.ps1 -Target bb -AcrName mdqacr -BbTag 2026-05
    .\build-acr.ps1 -Target allinone -AcrName mdqacr
#>
param(
    [Parameter(Mandatory)][ValidateSet("deps","checkpoint","bb","main","allinone","all")]
    [string]$Target,

    [Parameter(Mandatory)]
    [string]$AcrName,

    [string]$DepsTag = "1.1.0",
    [string]$CheckpointTag = "v1",
    [string]$BbTag = "2026-04",
    [string]$MainTag = "latest",
    [string]$BbUrl = ""
)

$ErrorActionPreference = "Stop"
$toolDir = $PSScriptRoot

function Build-Deps {
    Write-Host "`n=== Building retrochimera-deps:$DepsTag ===" -ForegroundColor Cyan
    az acr build -r $AcrName `
        -t "retrochimera-deps:$DepsTag" `
        -f "$toolDir/Dockerfile.deps" `
        $toolDir
}

function Build-Checkpoint {
    Write-Host "`n=== Building retrochimera-checkpoint:$CheckpointTag ===" -ForegroundColor Cyan
    az acr build -r $AcrName `
        -t "retrochimera-checkpoint:$CheckpointTag" `
        -f "$toolDir/Dockerfile.checkpoint" `
        $toolDir
}

function Build-Bb {
    Write-Host "`n=== Building retrochimera-bb:$BbTag ===" -ForegroundColor Cyan
    $bbArgs = @(
        "acr", "build",
        "-r", $AcrName,
        "-t", "retrochimera-bb:$BbTag",
        "-f", "$toolDir/Dockerfile.bb"
    )
    if ($BbUrl) {
        $bbArgs += "--build-arg"
        $bbArgs += "BUILDING_BLOCKS_URL=$BbUrl"
    }
    $bbArgs += $toolDir
    & az @bbArgs
}

function Build-Main {
    Write-Host "`n=== Building retrochimera:$MainTag ===" -ForegroundColor Cyan
    az acr build -r $AcrName `
        -t "retrochimera:$MainTag" `
        -f "$toolDir/Dockerfile.fast" `
        --build-arg "DEPS_IMAGE=$AcrName.azurecr.io/retrochimera-deps:$DepsTag" `
        --build-arg "CHECKPOINT_IMAGE=$AcrName.azurecr.io/retrochimera-checkpoint:$CheckpointTag" `
        --build-arg "BB_IMAGE=$AcrName.azurecr.io/retrochimera-bb:$BbTag" `
        $toolDir
}

function Build-AllInOne {
    Write-Host "`n=== Building retrochimera:$MainTag (all-in-one) ===" -ForegroundColor Cyan
    $aioArgs = @(
        "acr", "build",
        "-r", $AcrName,
        "-t", "retrochimera:$MainTag",
        "-f", "$toolDir/Dockerfile"
    )
    if ($BbUrl) {
        $aioArgs += "--build-arg"
        $aioArgs += "BUILDING_BLOCKS_URL=$BbUrl"
    }
    $aioArgs += $toolDir
    & az @aioArgs
}

switch ($Target) {
    "deps"       { Build-Deps }
    "checkpoint" { Build-Checkpoint }
    "bb"         { Build-Bb }
    "main"       { Build-Main }
    "allinone"   { Build-AllInOne }
    "all"        {
        Build-Deps
        if ($LASTEXITCODE -ne 0) { throw "Deps build failed" }
        Build-Checkpoint
        if ($LASTEXITCODE -ne 0) { throw "Checkpoint build failed" }
        Build-Bb
        if ($LASTEXITCODE -ne 0) { throw "Building blocks build failed" }
        Build-Main
        if ($LASTEXITCODE -ne 0) { throw "Main build failed" }
        Write-Host "`n=== All images built successfully ===" -ForegroundColor Green
    }
}
