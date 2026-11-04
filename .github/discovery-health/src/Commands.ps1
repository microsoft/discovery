# Commands: plan, run.

function Initialize-DhRun {
  param([System.Collections.IDictionary]$Config, [string]$OutputDir, [string]$RunId, [string]$GitSha = '', [switch]$Untrusted)
  $script:Dh.Config = $Config
  $script:Dh.RunId = if ($RunId) { $RunId } else { New-DhRunId }
  if (-not (Test-Path -LiteralPath $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }
  $script:Dh.OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
  $script:Dh.GitSha = $GitSha
  $script:Dh.Untrusted = [bool]$Untrusted
  $script:Dh.CancelRequested = $false
  $script:Dh.HarnessErrors.Clear()
  $script:DhEvidenceEnabled = $true
  Initialize-DhLog -OutputDir $script:Dh.OutputDir
  Register-DhConfigMasks -Config $Config
}

function Resolve-DhStages {
  param([string[]]$Stages)
  $list = @($Stages | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
  if ($list.Count -eq 0 -or $list -contains 'all') { return $script:DhStages }
  $unknown = @($list | Where-Object { $_ -notin $script:DhStages })
  if ($unknown.Count -gt 0) { throw ('Unknown stage(s): {0}. Valid: {1}' -f ($unknown -join ', '), ($script:DhStages -join ', ')) }
  if ($list -contains 'build' -and $list -notcontains 'image-smoke') { $list += 'image-smoke' }
  return @($script:DhStages | Where-Object { $_ -in $list })
}

function Resolve-DhAgentList {
  param([string[]]$Agents)
  return @($Agents | ForEach-Object { $_ -split '[,\s]+' } | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique)
}

function Write-DhGitHubOutput {
  param([string]$Name, [string]$Value)
  if ($env:GITHUB_OUTPUT) { [System.IO.File]::AppendAllText($env:GITHUB_OUTPUT, ('{0}={1}{2}' -f $Name, $Value, [Environment]::NewLine)) }
}

function Get-DhPreviousState {
  <#
  .SYNOPSIS Loads the previously published scorecard state from a file or URL (retries + cache busting).
  #>
  param([string]$Path, [string]$Url)
  if ($Path -and (Test-Path -LiteralPath $Path)) {
    $state = Read-DhJsonFile -Path $Path
    if ($state.schema -eq 'discovery-health/state@1') { return $state }
    throw "Previous state at $Path has an unexpected schema."
  }
  if ($Url) {
    for ($attempt = 1; $attempt -le 4; $attempt++) {
      $uri = '{0}{1}t={2}' -f $Url, $(if ($Url.Contains('?')) { '&' } else { '?' }), [DateTime]::UtcNow.Ticks
      $response = Invoke-DhRest -Method GET -Uri $uri -Audience none -MaxAttempts 1 -TimeoutSec 30
      if ($response.status -eq 200 -and $response.body -is [System.Collections.IDictionary] -and $response.body.schema -eq 'discovery-health/state@1') { return $response.body }
      Start-Sleep -Seconds ([math]::Pow(2, $attempt))
    }
  }
  return $null
}

function Invoke-DhPlanCommand {
  param(
    [System.Collections.IDictionary]$Config, [string]$CatalogRoot, [string]$Ref = 'HEAD', [string]$Source = 'git', [string[]]$Agents = @(), [string]$ChangedFrom,
    [string[]]$Stages, [int]$Shards, [string]$SpecRoot, [string]$OutputDir, [string]$PreviousStatePath, [string]$PreviousStateUrl, [string]$RunId, [hashtable]$Context = @{}
  )
  Initialize-DhRun -Config $Config -OutputDir $OutputDir -RunId $RunId
  $stageList = Resolve-DhStages -Stages $Stages
  $agentList = Resolve-DhAgentList -Agents $Agents
  if ($ChangedFrom) {
    $changed = @(Get-DhChangedAgents -CatalogRoot $CatalogRoot -BaseRef $ChangedFrom -HeadRef $Ref)
    $agentList = if ($agentList.Count -gt 0) { @($agentList | Where-Object { $_ -in $changed }) } else { $changed }
    Write-DhLog -Message ('Changed agents since {0}: {1}' -f $ChangedFrom, $(if ($changed.Count) { $changed -join ', ' } else { '(none)' }))
    if ($agentList.Count -eq 0) { $agentList = @('__none__') }
  }
  $requested = @($agentList | Where-Object { $_ -ne '__none__' })
  $catalog = if ($agentList -contains '__none__') {
    [ordered]@{ root = $CatalogRoot; ref = $Ref; source = $Source; gitSha = ''; allAgents = @(); unknown = @(); agents = [ordered]@{} }
  } else {
    Read-DhCatalog -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -Agents $requested -SpecRoot $SpecRoot -OutputDir $script:Dh.OutputDir -Config $Config
  }
  $previous = $null
  try { $previous = Get-DhPreviousState -Path $PreviousStatePath -Url $PreviousStateUrl } catch { Write-DhLog -Level warn -Message $_.Exception.Message }
  $plan = New-DhPlan -Catalog $catalog -Stages $stageList -Shards $Shards -PreviousState $previous -RunId $script:Dh.RunId -Context $Context
  $plan['allAgents'] = @($catalog.allAgents)
  $minLimit = (@($script:DhQueueClasses | ForEach-Object { [int](Get-DhValue $Config ('concurrency.' + $_) 4) }) | Measure-Object -Minimum).Minimum
  if ($Shards -gt $minLimit) {
    Write-DhLog -Level warn -Message ('{0} shards exceed the smallest concurrency limit ({1}); each shard gets at least one slot per class, so effective global concurrency can reach {0}.' -f $Shards, $minLimit)
  }
  Write-DhJsonFile -Path (Join-Path $script:Dh.OutputDir 'plan.json') -InputObject $plan
  Write-DhJsonFile -Path (Join-Path $script:Dh.OutputDir 'matrix.json') -InputObject @{ include = @($plan.matrix) }
  Write-DhGitHubOutput -Name 'run_id' -Value $script:Dh.RunId
  Write-DhGitHubOutput -Name 'matrix' -Value (ConvertTo-DhJson @{ include = @($plan.matrix) } -Compress)
  Write-DhGitHubOutput -Name 'agent_count' -Value ([string]$plan.agents.Count)
  Write-DhLog -Message ('Plan {0}: {1} agent(s), {2} tool(s), stages [{3}], {4} shard(s).' -f $script:Dh.RunId, $plan.agents.Count, (@($catalog.agents.Values | ForEach-Object { $_.tools.Count }) | Measure-Object -Sum).Sum, ($stageList -join ', '), @($plan.matrix).Count)
  foreach ($name in $plan.agents.Keys) {
    $entry = $plan.agents[$name]
    $agent = $catalog.agents[$name]
    $issues = @($agent.issues | Where-Object { $_.level -eq 'error' } | ForEach-Object { $_.code })
    Write-DhLog -Message ('  shard {0}  {1,-36} tools={2,-2} gpu={3,-5} spec={4,-5} issues={5}' -f $entry.shard, $name, $agent.tools.Count, $entry.gpu, [bool]$agent.spec, $(if ($issues) { $issues -join ',' } else { '-' }))
  }
  foreach ($unknown in $catalog.unknown) { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-DSC-012' -Params @{ agent = $unknown }) }
  return $plan
}

function Save-DhDiscoverResults {
  param([System.Collections.IDictionary]$Catalog)
  foreach ($unknown in $Catalog.unknown) {
    Save-DhResult -Result (New-DhResult -Agent ([string]$unknown) -Stage 'discover' -Status 'failed' -Category 'policy' -Code 'DH-DSC-012' -Messages @() -Data @{} ) | Out-Null
  }
  foreach ($agent in $Catalog.agents.Values) {
    $scopes = @('') + @($agent.tools.Keys)
    foreach ($scope in $scopes) {
      $issues = @($agent.issues | Where-Object { [string]$_.tool -eq $scope })
      $messages = @($issues | ForEach-Object { New-DhMessage -Level $(if ($_.level -eq 'error') { 'error' } else { 'warning' }) -Code $_.code -Params $_.params })
      foreach ($issue in $issues) {
        if ($issue.detail) { Save-DhEvidence -Agent $agent.name -Tool $scope -Stage 'discover' -Name ('{0}.txt' -f $issue.code) -Content ([string]$issue.detail) | Out-Null }
      }
      $errors = @($issues | Where-Object { $_.level -eq 'error' })
      $status = if ($errors.Count -gt 0) { 'failed' } elseif ($issues.Count -gt 0) { 'warning' } else { 'passed' }
      $category = if ($errors.Count -gt 0) { [string]$errors[0].category } else { '' }
      $data = [ordered]@{ fingerprint = $(if ($scope) { $agent.tools[$scope].fp12 } else { $agent.fingerprint.Substring(0, 12) }); specSource = $(if ($agent.spec) { 'spec' } else { 'default' }) }
      Save-DhResult -Result (New-DhResult -Agent $agent.name -Tool $scope -Stage 'discover' -Status $status -Category $category -Messages $messages -Data $data) | Out-Null
    }
  }
}

function Set-DhDiscoverGating {
  <#
  .SYNOPSIS Pre-completes nodes whose agent/tool failed discovery (or all nodes when preflight failed).
  #>
  param([System.Collections.IDictionary]$Graph, [bool]$PreflightOk)
  foreach ($node in @($Graph.nodes.Values)) {
    if (-not $PreflightOk) {
      Complete-DhNode -Graph $Graph -Node $node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-DEP-005'
      continue
    }
    $agent = $Graph.catalog.agents[$node.agent]
    $scope = if ($node.tool) { $node.tool } else { '' }
    $errors = @($agent.issues | Where-Object { $_.level -eq 'error' -and [string]$_.tool -eq $scope })
    if ($errors.Count -gt 0) {
      $category = [string]$errors[0].category
      $status = if ($category -eq 'infrastructure') { 'inconclusive' } else { 'blocked' }
      Complete-DhNode -Graph $Graph -Node $node -Status $status -Category $category -Code 'DH-DEP-001' -Params @{ dependency = 'discover'; status = 'failed' }
    }
  }
}

function Invoke-DhRunCommand {
  param(
    [System.Collections.IDictionary]$Config, [string]$CatalogRoot, [string]$Ref = 'HEAD', [string]$Source = 'git', [string[]]$Agents = @(), [string[]]$Stages = @(),
    [string]$SpecRoot, [string]$OutputDir, [string]$PlanPath, [int]$Shard, [string]$RunId, [switch]$Untrusted, [switch]$DryRun
  )
  $plan = $null
  if ($PlanPath) {
    $plan = Read-DhJsonFile -Path $PlanPath
    if (-not $RunId) { $RunId = [string]$plan.runId }
  }
  Initialize-DhRun -Config $Config -OutputDir $OutputDir -RunId $RunId -Untrusted:$Untrusted
  $stageList = if ($plan -and -not $Stages) { @($plan.stages) } else { Resolve-DhStages -Stages $Stages }
  $shardCount = 1
  $agentList = Resolve-DhAgentList -Agents $Agents
  if ($plan -and $Shard -gt 0) {
    $agentList = @(Get-DhShardAgents -Plan $plan -Shard $Shard)
    $shardCount = [int]$plan.shards
  } elseif ($plan) {
    $agentList = @($plan.agents.Keys)
  }
  if ($plan -and $agentList.Count -eq 0) {
    Write-DhLog -Message 'No agents assigned to this shard.'
    return @{ exitCode = 0 }
  }
  $started = Get-DhUtcNow
  $catalog = Read-DhCatalog -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -Agents $agentList -SpecRoot $SpecRoot -OutputDir $script:Dh.OutputDir -Config $Config
  $script:Dh.GitSha = $catalog.gitSha
  Write-DhLog -Message ('Run {0}: {1} agent(s), stages [{2}], shard {3}/{4}, source {5}@{6}.' -f $script:Dh.RunId, $catalog.agents.Count, ($stageList -join ', '), $(if ($Shard) { $Shard } else { 1 }), $shardCount, $Source, $(if ($catalog.gitSha) { $catalog.gitSha.Substring(0, 12) } else { $Ref }))
  if ($Untrusted -and $SpecRoot) { Write-DhLog -Message 'Untrusted (PR) run: specs and template variables come from the trusted base only.' }
  Save-DhDiscoverResults -Catalog $catalog
  $graph = New-DhGraph -Catalog $catalog -Stages $stageList -Config $Config -ShardCount $shardCount -ShardIndex $(if ($Shard -gt 0) { $Shard } else { 1 })
  if ($DryRun) {
    foreach ($node in $graph.nodes.Values) { Write-DhLog -Message ('[dry-run] {0} (class {1}) deps: {2}' -f $node.id, $node.class, $(if ($node.deps.Count) { ($node.deps | ForEach-Object { $_.id }) -join ', ' } else { '-' })) }
    return @{ exitCode = 0; graph = $graph }
  }
  $preflight = @{ ok = $true }
  if ($graph.nodes.Count -gt 0) { $preflight = Invoke-DhPreflight -Config $Config -Stages $stageList }
  Set-DhDiscoverGating -Graph $graph -PreflightOk $preflight.ok
  $deadline = $started.AddMinutes([int](Get-DhValue $Config 'deadlineMinutes' 330))
  $stopReason = Invoke-DhScheduler -Graph $graph -DeadlineUtc $deadline
  if ([string](Get-DhValue $Config 'cleanup.afterRun' 'none') -eq 'all' -and $preflight.ok) {
    try { Invoke-DhAgentTeardown -Graph $graph } catch { Write-DhLog -Level warn -Message ('After-run cleanup failed: {0}' -f $_.Exception.Message) }
  }
  $results = Read-DhResults -Directories @($script:Dh.OutputDir)
  $counts = [ordered]@{}
  foreach ($r in $results) { $counts[$r.status] = 1 + [int](Get-DhValue $counts $r.status 0) }
  $summary = [ordered]@{
    schema = 'discovery-health/run@1'; runId = $script:Dh.RunId; shard = $Shard; shards = $shardCount; gitSha = $script:Dh.GitSha; stages = $stageList
    startedAt = (ConvertTo-DhIso $started); finishedAt = (ConvertTo-DhIso (Get-DhUtcNow)); stopReason = $stopReason; counts = $counts
    harnessErrors = @($script:Dh.HarnessErrors | ForEach-Object { Protect-DhText $_ })
  }
  Write-DhJsonFile -Path (Join-Path $script:Dh.OutputDir 'run.json') -InputObject $summary
  Write-DhLog -Message ('Run {0} finished: {1}' -f $script:Dh.RunId, (($counts.Keys | ForEach-Object { '{0}={1}' -f $_, $counts[$_] }) -join ' '))
  return @{ exitCode = 0; results = $results; summary = $summary }
}
