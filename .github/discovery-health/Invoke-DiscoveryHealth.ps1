#Requires -Version 7.2
<#
.SYNOPSIS
  Discovery Health: programmatic live tests for Discovery catalog agents and tools.

.DESCRIPTION
  Runs identically on Windows 11 and GitHub-hosted Linux runners (PowerShell 7, Azure CLI,
  Python 3 + PyYAML, Git). No Docker is required: images build remotely in Azure Container
  Registry. No AI is used by the harness; prompts and checks come from deterministic specs.

  Commands:
    plan           Discover + select agents, write plan.json/matrix.json. No Azure calls.
    run            Execute stages (build, image-smoke, tool-register, tool-run, agent-register, round-trip).
    report         Merge results, synthesize missing ones, write summary/JUnit, build the scorecard site.
    cleanup        Delete discovery-github-test resources in dependency order (tag-guarded).
    evidence       Download private evidence for a run from the evidence storage account.
    scaffold-spec  Write deterministic spec skeletons for agents that have none.
    validate-specs Validate every spec against its schema and the catalog.

.EXAMPLE
  pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 plan -Agents chembl,aizynthfinder
.EXAMPLE
  pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 run -Agents chembl -Stages build,tool-register
.EXAMPLE
  pwsh -File .github/discovery-health/Invoke-DiscoveryHealth.ps1 cleanup -DryRun
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('plan', 'run', 'report', 'cleanup', 'evidence', 'scaffold-spec', 'validate-specs')]
  [string]$Command = 'plan',
  [string]$ConfigPath,
  [string[]]$Agents = @(),
  [string[]]$Stages = @(),
  [string]$CatalogRoot,
  [string]$Ref = 'HEAD',
  [ValidateSet('git', 'worktree')][string]$Source = 'git',
  [string]$SpecRoot,
  [string]$OutputDir,
  [string]$ChangedFrom,
  [int]$Shards = 1,
  [int]$Shard = 0,
  [string]$PlanPath,
  [string]$RunId,
  [string[]]$ResultsDir = @(),
  [string]$PreviousStatePath,
  [string]$PreviousStateUrl,
  [switch]$Site,
  [switch]$Bootstrap,
  [ValidateSet('', 'contribution', 'any', 'none')][string]$FailOn = '',
  [ValidateSet('', 'changed', 'always')][string]$Rebuild = '',
  [switch]$Untrusted,
  [switch]$DryRun,
  [switch]$All,
  [switch]$FromCheckpoints,
  [switch]$ReapOrphans,
  [string]$Title = 'Discovery Health',
  [string]$Context = '',
  [string]$RepositoryUrl = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'DiscoveryHealth.psd1') -Force
$repoRoot = Get-DhRepoRoot -StartPath $PSScriptRoot
if (-not $CatalogRoot) { $CatalogRoot = $repoRoot }
$CatalogRoot = (Resolve-Path -LiteralPath $CatalogRoot).Path
if (-not $SpecRoot) { $SpecRoot = Join-Path $PSScriptRoot 'specs' }
if (-not $ConfigPath) {
  $localConfig = Join-Path $PSScriptRoot 'config.json'
  if (Test-Path -LiteralPath $localConfig) { $ConfigPath = $localConfig }
}
if (-not $OutputDir) {
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
  $OutputDir = Join-Path $repoRoot (Join-Path '.discovery-health' ('{0}-{1}' -f $Command, $stamp))
}

$overrides = [ordered]@{}
if ($Rebuild) { $overrides['rebuild'] = [ordered]@{ mode = $Rebuild } }
if ($FailOn) { $overrides['failOn'] = $FailOn }
$config = Read-DhConfig -Path $ConfigPath -Overrides $overrides

$exitCode = 0
try {
  switch ($Command) {
    'plan' {
      Invoke-DhPlanCommand -Config $config -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -Agents $Agents -ChangedFrom $ChangedFrom -Stages $Stages -Shards $Shards `
        -SpecRoot $SpecRoot -OutputDir $OutputDir -PreviousStatePath $PreviousStatePath -PreviousStateUrl $PreviousStateUrl -RunId $RunId -Context @{ context = $Context } | Out-Null
    }
    'run' {
      $result = Invoke-DhRunCommand -Config $config -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -Agents $Agents -Stages $Stages -SpecRoot $SpecRoot `
        -OutputDir $OutputDir -PlanPath $PlanPath -Shard $Shard -RunId $RunId -Untrusted:$Untrusted -DryRun:$DryRun
      $exitCode = [int]$result.exitCode
      if ($FailOn -and -not $DryRun) {
        $report = Invoke-DhReportCommand -Config $config -ResultsDir @($OutputDir) -PlanPath '' -OutputDir (Join-Path $OutputDir 'report') -FailOn $FailOn -Title $Title -Context $Context
        $exitCode = [int]$report.exitCode
      }
    }
    'report' {
      $dirs = if ($ResultsDir.Count -gt 0) { $ResultsDir } else { @($OutputDir) }
      $report = Invoke-DhReportCommand -Config $config -ResultsDir $dirs -PlanPath $PlanPath -OutputDir $OutputDir -PreviousStatePath $PreviousStatePath -PreviousStateUrl $PreviousStateUrl `
        -Site:$Site -Bootstrap:$Bootstrap -FailOn $FailOn -Title $Title -Context $Context -RepositoryUrl $RepositoryUrl -FromCheckpoints:$FromCheckpoints -ReapOrphans:$ReapOrphans
      $exitCode = [int]$report.exitCode
    }
    'cleanup' {
      $result = Invoke-DhCleanupCommand -Config $config -OutputDir $OutputDir -CatalogRoot $CatalogRoot -Ref $Ref -DryRun:$DryRun -All:$All
      $exitCode = [int]$result.exitCode
    }
    'evidence' {
      if (-not $RunId) { throw '-RunId is required for the evidence command.' }
      Initialize-DhRun -Config $config -OutputDir $OutputDir -RunId $RunId
      $count = Save-DhRunEvidenceCopy -RunId $RunId -Destination (Join-Path $OutputDir 'evidence-download')
      Write-DhLog -Message ('Downloaded {0} evidence file(s) to {1}' -f $count, (Join-Path $OutputDir 'evidence-download'))
    }
    'scaffold-spec' {
      Initialize-DhRun -Config $config -OutputDir $OutputDir -RunId 'scaffold'
      $catalog = Read-DhCatalog -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -Agents $Agents -SpecRoot $SpecRoot -OutputDir $OutputDir -Config $config
      foreach ($agent in $catalog.agents.Values) {
        $path = Join-Path $SpecRoot ('{0}.yaml' -f $agent.name)
        if (Test-Path -LiteralPath $path) { Write-DhLog -Message ('Spec exists, not overwritten: {0}' -f $path); continue }
        Write-DhTextFile -Path $path -Content (New-DhSpecSkeleton -Agent $agent)
        Write-DhLog -Message ('Wrote spec skeleton {0}' -f $path)
      }
    }
    'validate-specs' {
      Initialize-DhRun -Config $config -OutputDir $OutputDir -RunId 'validate-specs'
      $names = @(Get-ChildItem -LiteralPath $SpecRoot -Filter '*.yaml' -File | Where-Object { -not $_.Name.StartsWith('_') } | ForEach-Object { $_.BaseName })
      $catalog = Read-DhCatalog -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -Agents $names -SpecRoot $SpecRoot -OutputDir $OutputDir -Config $config
      $bad = 0
      foreach ($unknown in $catalog.unknown) { Write-DhLog -Level error -Message ('Spec for unknown agent: {0}' -f $unknown); $bad++ }
      foreach ($agent in $catalog.agents.Values) {
        $specIssues = @($agent.issues | Where-Object { $_.code -eq 'DH-SPC-001' })
        foreach ($issue in $specIssues) { Write-DhLog -Level error -Message ('{0}: {1} {2}' -f $agent.name, (Get-DhMessage -Code $issue.code -Params $issue.params), $issue.detail); $bad++ }
      }
      Write-DhLog -Message ('Validated {0} spec(s); {1} problem(s).' -f $names.Count, $bad)
      if ($bad -gt 0) { $exitCode = 1 }
    }
  }
} catch {
  Write-Host ('[discovery-health] FATAL: {0}' -f (Protect-DhText $_.Exception.Message))
  Write-Host (Protect-DhText $_.ScriptStackTrace)
  $exitCode = 4
}
Write-Host ('[discovery-health] OUTPUT_DIR={0}' -f $OutputDir)
exit $exitCode
