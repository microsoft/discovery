# Result records: one atomic JSON file per (agent, tool, stage). Public fields only.

function New-DhMessage {
  param([ValidateSet('info', 'warning', 'error')][string]$Level, [string]$Code, [hashtable]$Params = @{})
  return [ordered]@{ level = $Level; code = $Code; text = (Get-DhMessage -Code $Code -Params $Params) }
}

function Get-DhResultPath {
  param([string]$OutputDir, [string]$Agent, [string]$Tool, [string]$Stage)
  $toolPart = if ($Tool) { $Tool } else { '_agent' }
  return (Join-Path $OutputDir (Join-Path 'results' (Join-Path $Agent (Join-Path $toolPart ("$Stage.json")))))
}

function New-DhResult {
  param(
    [Parameter(Mandatory)][string]$Agent,
    [string]$Tool = '',
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][ValidateSet('passed', 'cached', 'warning', 'failed', 'blocked', 'skipped', 'untested', 'inconclusive')][string]$Status,
    [ValidateSet('', 'contribution', 'infrastructure', 'harness', 'policy')][string]$Category = '',
    [string]$Code = '',
    [object[]]$Messages = @(),
    [System.Collections.IDictionary]$Data = @{},
    [string[]]$Evidence = @(),
    [Nullable[datetime]]$StartedAt = $null,
    [double]$DurationSec = 0
  )
  $finished = Get-DhUtcNow
  $started = if ($StartedAt) { [datetime]$StartedAt } else { $finished }
  return [ordered]@{
    schema      = 'discovery-health/result@1'
    runId       = $script:Dh.RunId
    gitSha      = $script:Dh.GitSha
    agent       = $Agent
    tool        = $Tool
    stage       = $Stage
    status      = $Status
    category    = $Category
    code        = $Code
    messages    = @($Messages)
    data        = $Data
    evidence    = @($Evidence)
    startedAt   = (ConvertTo-DhIso $started)
    finishedAt  = (ConvertTo-DhIso $finished)
    durationSec = [math]::Round($(if ($DurationSec -gt 0) { $DurationSec } else { ($finished - $started).TotalSeconds }), 1)
  }
}

function Save-DhResult {
  <#
  .SYNOPSIS Persists a result atomically; failures are logged and kept in memory, never thrown.
  #>
  param([Parameter(Mandatory)][System.Collections.IDictionary]$Result)
  $path = Get-DhResultPath -OutputDir $script:Dh.OutputDir -Agent $Result.agent -Tool $Result.tool -Stage $Result.stage
  try {
    Write-DhJsonFile -Path $path -InputObject $Result
  } catch {
    $script:Dh.HarnessErrors.Add(('result write failed for {0}/{1}/{2}: {3}' -f $Result.agent, $Result.tool, $Result.stage, $_.Exception.Message))
    Write-DhLog -Level error -Message ('Could not write result file: {0}' -f $_.Exception.Message)
  }
  try { Send-DhCheckpoint -RelativePath ([System.IO.Path]::GetRelativePath($script:Dh.OutputDir, $path)) -Content (ConvertTo-DhJson $Result) } catch { }
  $level = switch ($Result.status) { 'failed' { 'error' } { $_ -in @('warning', 'inconclusive', 'blocked', 'untested', 'skipped') } { 'warn' } default { 'info' } }
  $summary = (@($Result.messages | ForEach-Object { $_.text }) -join ' | ')
  Write-DhLog -Level $level -Scope ('{0}{1}/{2}' -f $Result.agent, $(if ($Result.tool) { '/' + $Result.tool } else { '' }), $Result.stage) -Message ('{0}{1}' -f $Result.status.ToUpperInvariant(), $(if ($summary) { ' - ' + $summary } else { '' }))
  return $path
}

function Read-DhResults {
  <#
  .SYNOPSIS Loads every result JSON under one or more directories; later finishedAt wins on duplicates.
  #>
  param([string[]]$Directories)
  $byKey = [ordered]@{}
  foreach ($dir in $Directories) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    foreach ($file in (Get-ChildItem -LiteralPath $dir -Recurse -Filter '*.json' -File | Where-Object { $_.FullName -match '[\\/]results[\\/]' })) {
      try { $result = Read-DhJsonFile -Path $file.FullName } catch { continue }
      if (-not ($result -is [System.Collections.IDictionary]) -or $result.schema -ne 'discovery-health/result@1') { continue }
      $key = '{0}|{1}|{2}' -f $result.agent, $result.tool, $result.stage
      if (-not $byKey.Contains($key) -or [string]$byKey[$key].finishedAt -lt [string]$result.finishedAt) { $byKey[$key] = $result }
    }
  }
  return @($byKey.Values)
}
