# Single-threaded asynchronous DAG scheduler.
# Every remote step is a long-running operation, so one event loop can drive hundreds of
# them: nodes Start/Poll via Step functions, results are written by this thread only,
# remote operation ids are registered before polling, and in-flight work is cancelled
# on deadline or cancellation.

$script:DhQueueClasses = @('acr', 'toolRegister', 'toolRun', 'gpuToolRun', 'agentRegister', 'roundTrip')
$script:DhCapacityCodes = @('DH-RUN-006')

function Get-DhNodeId {
  param([string]$Agent, [string]$Tool, [string]$Stage)
  return ('{0}/{1}/{2}' -f $Agent, $(if ($Tool) { $Tool } else { '_agent' }), $Stage)
}

function Add-DhNode {
  param([System.Collections.IDictionary]$Graph, [string]$Agent, [string]$Tool = '', [string]$Stage, [string]$Class, [object[]]$Deps = @())
  $id = Get-DhNodeId -Agent $Agent -Tool $Tool -Stage $Stage
  $Graph.nodes[$id] = [ordered]@{
    id = $id; agent = $Agent; tool = $Tool; stage = $Stage; class = $Class; deps = @($Deps | Where-Object { $_ -and $Graph.nodes.Contains($_.id) })
    state = 'pending'; phase = 'init'; nextAt = [datetime]::MinValue; startedAt = $null; data = [ordered]@{}
    messages = [System.Collections.Generic.List[object]]::new(); evidence = [System.Collections.Generic.List[string]]::new()
    operations = [System.Collections.Generic.List[object]]::new(); result = $null; job = $null
  }
  return $Graph.nodes[$id]
}

function New-DhDep {
  param([string]$Id, [switch]$Soft)
  return @{ id = $Id; soft = [bool]$Soft }
}

function New-DhGraph {
  <#
  .SYNOPSIS Builds the per-tool / per-agent stage DAG for the selected stages.
  .NOTES Budgets are split exactly across shards (remainder to the first shards). Concurrency is split
         with a minimum of one slot per shard, so the effective global maximum is max(limit, shards).
  #>
  param([System.Collections.IDictionary]$Catalog, [string[]]$Stages, [System.Collections.IDictionary]$Config, [int]$ShardCount = 1, [int]$ShardIndex = 1)
  $graph = [ordered]@{
    nodes = [ordered]@{}; toolCtx = @{}; agentCtx = @{}; running = @{}; budgets = @{}; limits = @{}; caches = @{}
    catalog = $Catalog; config = $Config; stages = $Stages
  }
  $shards = [math]::Max(1, $ShardCount)
  $index = [math]::Min([math]::Max(1, $ShardIndex), $shards)
  foreach ($class in $script:DhQueueClasses) {
    $limit = [int](Get-DhValue $Config ('concurrency.' + $class) 4)
    $graph.limits[$class] = [math]::Max(1, [math]::Floor($limit / $shards))
    $graph.running[$class] = 0
  }
  foreach ($key in @('maxAcrBuilds', 'maxToolRuns', 'maxGpuToolRuns', 'maxRoundTrips')) {
    $budget = [int](Get-DhValue $Config ('budgets.' + $key) 100)
    $graph.budgets[$key] = [int][math]::Floor($budget / $shards) + $(if ($index -le ($budget % $shards)) { 1 } else { 0 })
  }
  $smokeSelected = ($Stages -contains 'image-smoke') -or ($Stages -contains 'build')
  foreach ($agent in $Catalog.agents.Values) {
    $graph.agentCtx[$agent.name] = [ordered]@{ agent = $agent; deployedName = ''; investigations = [System.Collections.Generic.List[string]]::new() }
    foreach ($tool in $agent.tools.Values) {
      $key = '{0}/{1}' -f $agent.name, $tool.name
      $graph.toolCtx[$key] = [ordered]@{ agent = $agent; tool = $tool; imageRef = ''; imageTag = ''; digest = ''; toolResourceId = ''; smokeResults = $null; smokeSource = '' }
      $build = $null; $smoke = $null; $register = $null
      if ($Stages -contains 'build') { $build = Add-DhNode -Graph $graph -Agent $agent.name -Tool $tool.name -Stage 'build' -Class 'acr' }
      if ($smokeSelected) {
        $smoke = Add-DhNode -Graph $graph -Agent $agent.name -Tool $tool.name -Stage 'image-smoke' -Class 'acr' -Deps @($(if ($build) { New-DhDep $build.id }))
      }
      if ($Stages -contains 'tool-register') {
        $register = Add-DhNode -Graph $graph -Agent $agent.name -Tool $tool.name -Stage 'tool-register' -Class 'toolRegister' -Deps @($(if ($build) { New-DhDep $build.id }))
      }
      if ($Stages -contains 'tool-run') {
        $class = if ($tool.gpu) { 'gpuToolRun' } else { 'toolRun' }
        $deps = @()
        if ($register) { $deps += New-DhDep $register.id }
        if ($smoke) { $deps += New-DhDep $smoke.id -Soft }
        Add-DhNode -Graph $graph -Agent $agent.name -Tool $tool.name -Stage 'tool-run' -Class $class -Deps $deps | Out-Null
      }
    }
    $bound = @(Get-DhBoundTools -Agent $agent)
    $agentReg = $null
    if ($Stages -contains 'agent-register') {
      $deps = @($bound | ForEach-Object { New-DhDep (Get-DhNodeId -Agent $agent.name -Tool $_ -Stage 'tool-register') })
      $agentReg = Add-DhNode -Graph $graph -Agent $agent.name -Stage 'agent-register' -Class 'agentRegister' -Deps $deps
    }
    if ($Stages -contains 'round-trip') {
      $deps = @()
      if ($agentReg) { $deps += New-DhDep $agentReg.id }
      foreach ($toolName in $bound) { $deps += New-DhDep (Get-DhNodeId -Agent $agent.name -Tool $toolName -Stage 'tool-run') -Soft }
      Add-DhNode -Graph $graph -Agent $agent.name -Stage 'round-trip' -Class 'roundTrip' -Deps $deps | Out-Null
    }
  }
  return $graph
}

function Request-DhBudget {
  param([System.Collections.IDictionary]$Graph, [string]$Name)
  if ([int]$Graph.budgets[$Name] -le 0) { return $false }
  $Graph.budgets[$Name] = [int]$Graph.budgets[$Name] - 1
  return $true
}

function Add-DhNodeMessage {
  param([System.Collections.IDictionary]$Node, [ValidateSet('info', 'warning', 'error')][string]$Level, [string]$Code, [hashtable]$Params = @{})
  $Node.messages.Add((New-DhMessage -Level $Level -Code $Code -Params $Params))
}

function Add-DhNodeEvidence {
  param([System.Collections.IDictionary]$Node, [string]$Name, $Content)
  $ref = Save-DhEvidence -Agent $Node.agent -Tool $Node.tool -Stage $Node.stage -Name $Name -Content $Content
  if ($ref -and -not $Node.evidence.Contains($ref)) { $Node.evidence.Add($ref) }
  return $ref
}

function Register-DhOperation {
  param([System.Collections.IDictionary]$Node, [string]$Kind, [string]$Id, [string]$PollUrl = '', [string]$CancelUrl = '', [string]$Audience = 'arm', [string]$CancelMethod = 'POST')
  $op = [ordered]@{
    schema = 'discovery-health/operation@1'; runId = $script:Dh.RunId; node = $Node.id; kind = $Kind; id = $Id; pollUrl = $PollUrl; cancelUrl = $CancelUrl
    cancelMethod = $CancelMethod; audience = $Audience; submittedAt = (ConvertTo-DhIso (Get-DhUtcNow)); status = 'running'
  }
  $Node.operations.Add($op)
  $file = Join-Path $script:Dh.OutputDir ('operations/{0}-{1}.json' -f (ConvertTo-DhSafeName ($Node.id -replace '/', '-') 120), $Node.operations.Count)
  $op['file'] = $file
  try {
    Write-DhJsonFile -Path $file -InputObject $op
    Send-DhCheckpoint -RelativePath ([System.IO.Path]::GetRelativePath($script:Dh.OutputDir, $file)) -Content (ConvertTo-DhJson $op)
  } catch { }
  return $op
}

function Complete-DhOperation {
  param([System.Collections.IDictionary]$Operation, [string]$Status)
  if (-not $Operation -or $Operation.status -ne 'running') { return }
  $Operation.status = $Status
  $Operation['finishedAt'] = ConvertTo-DhIso (Get-DhUtcNow)
  try {
    Write-DhJsonFile -Path $Operation.file -InputObject $Operation
    Send-DhCheckpoint -RelativePath ([System.IO.Path]::GetRelativePath($script:Dh.OutputDir, $Operation.file)) -Content (ConvertTo-DhJson $Operation)
  } catch { }
}

function Stop-DhOperation {
  <#
  .SYNOPSIS Best-effort cancellation of a registered remote operation.
  #>
  param([System.Collections.IDictionary]$Operation)
  if (-not $Operation -or $Operation.status -ne 'running') { return }
  if ($Operation.cancelUrl) {
    try {
      $response = Invoke-DhRest -Method $Operation.cancelMethod -Uri $Operation.cancelUrl -Audience $Operation.audience -Body @{} -MaxAttempts 2 -TimeoutSec 30
      Write-DhLog -Level warn -Message ('Cancelled {0} operation for {1} (HTTP {2}).' -f $Operation.kind, $Operation.node, $response.status)
    } catch {
      Write-DhLog -Level warn -Message ('Could not cancel {0} operation for {1}.' -f $Operation.kind, $Operation.node)
    }
  }
  Complete-DhOperation -Operation $Operation -Status 'cancelled'
}

function Complete-DhNode {
  <#
  .SYNOPSIS Finalizes a node: records the result atomically and releases its queue slot.
  #>
  param(
    [System.Collections.IDictionary]$Graph,
    [System.Collections.IDictionary]$Node,
    [string]$Status,
    [string]$Category = '',
    [string]$Code = '',
    [hashtable]$Params = @{},
    [System.Collections.IDictionary]$Data = $null
  )
  if ($Node.state -eq 'done') { return }
  if ($Status -in @('passed', 'cached') -and @($Node.messages | Where-Object { $_.level -in @('warning', 'error') }).Count -gt 0) { $Status = 'warning' }
  $level = switch ($Status) { 'failed' { 'error' } { $_ -in @('passed', 'cached') } { 'info' } default { 'warning' } }
  $messages = [System.Collections.Generic.List[object]]::new()
  if ($Code) { $messages.Add((New-DhMessage -Level $level -Code $Code -Params $Params)) }
  foreach ($m in $Node.messages) { $messages.Add($m) }
  if ($Node.job) { try { Remove-Job -Job $Node.job -Force -ErrorAction SilentlyContinue } catch { }; $Node.job = $null }
  foreach ($op in $Node.operations) { if ($op.status -eq 'running') { Complete-DhOperation -Operation $op -Status $Status } }
  $data = if ($Data) { $Data } else { $Node.data }
  $publicData = [ordered]@{}
  foreach ($key in @($data.Keys)) {
    if ($key -in @('imageTag', 'digest', 'baseImages', 'cases', 'coverage', 'toolsCalled', 'nodepoolSku', 'deployedName', 'attempts', 'specSource', 'fingerprint', 'sizeBytes', 'queueSec', 'runSec')) {
      $publicData[$key] = $data[$key]
    }
  }
  $started = if ($Node.startedAt) { [datetime]$Node.startedAt } else { $null }
  $result = New-DhResult -Agent $Node.agent -Tool $Node.tool -Stage $Node.stage -Status $Status -Category $Category -Code $Code -Messages $messages.ToArray() -Data $publicData -Evidence $Node.evidence.ToArray() -StartedAt $started
  Save-DhResult -Result $result | Out-Null
  if ($Node.state -eq 'running') { $Graph.running[$Node.class] = [math]::Max(0, [int]$Graph.running[$Node.class] - 1) }
  $Node.state = 'done'
  $Node.result = $result
  if ($Status -in @('failed')) {
    Write-DhAnnotation -Level error -Title ('{0} {1}' -f $Node.agent, $Node.stage) -Message ((@($messages | ForEach-Object { $_.text })) -join ' ')
  }
}

function Get-DhDependencyOutcome {
  <#
  .SYNOPSIS 'wait', 'ready', or a derived terminal outcome for a pending node.
  #>
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  foreach ($dep in $Node.deps) {
    $depNode = $Graph.nodes[$dep.id]
    if ($depNode.state -ne 'done') { return 'wait' }
  }
  foreach ($dep in $Node.deps) {
    $r = $Graph.nodes[$dep.id].result
    if ($r.status -in $script:DhOkStatuses) { continue }
    if ($dep.soft -and $r.status -in @('untested', 'skipped') -and $r.code -notin $script:DhCapacityCodes) { continue }
    $depName = '{0}{1}' -f $(if ($Graph.nodes[$dep.id].tool) { $Graph.nodes[$dep.id].tool + '/' } else { '' }), $Graph.nodes[$dep.id].stage
    switch ($r.status) {
      'untested' { return @{ status = 'untested'; category = ''; code = $r.code; params = @{} } }
      'inconclusive' { return @{ status = 'inconclusive'; category = 'infrastructure'; code = 'DH-DEP-001'; params = @{ dependency = $depName; status = $r.status } } }
      'skipped' { return @{ status = 'skipped'; category = ''; code = 'DH-DEP-001'; params = @{ dependency = $depName; status = $r.status } } }
      default { return @{ status = 'blocked'; category = $r.category; code = 'DH-DEP-001'; params = @{ dependency = $depName; status = $r.status } } }
    }
  }
  return 'ready'
}

function Invoke-DhNodeStep {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  switch ($Node.stage) {
    'build' { Step-DhBuild -Graph $Graph -Node $Node }
    'image-smoke' { Step-DhImageSmoke -Graph $Graph -Node $Node }
    'tool-register' { Step-DhToolRegister -Graph $Graph -Node $Node }
    'tool-run' { Step-DhToolRun -Graph $Graph -Node $Node }
    'agent-register' { Step-DhAgentRegister -Graph $Graph -Node $Node }
    'round-trip' { Step-DhRoundTrip -Graph $Graph -Node $Node }
    default { throw "Unknown stage $($Node.stage)" }
  }
}

function Test-DhSpecSkipForNode {
  <#
  .SYNOPSIS Applies expiring spec skips; returns $true when the node was completed as skipped.
  #>
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $agent = $Graph.catalog.agents[$Node.agent]
  $skip = Get-DhSpecSkip -Agent $agent -Stage $Node.stage -Tool $Node.tool
  foreach ($expired in $skip.expired) { Add-DhNodeMessage -Node $Node -Level warning -Code 'DH-SPC-002' -Params @{ stage = $Node.stage; until = $expired.until } }
  if ($skip.active) {
    Complete-DhNode -Graph $Graph -Node $Node -Status 'skipped' -Category 'policy' -Code 'DH-SPC-003' -Params @{ until = $skip.active.until }
    return $true
  }
  return $false
}

function Stop-DhNode {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  if ($Node.job) { try { Stop-Job -Job $Node.job -ErrorAction SilentlyContinue } catch { } }
  foreach ($op in @($Node.operations)) { Stop-DhOperation -Operation $op }
}

function Invoke-DhScheduler {
  <#
  .SYNOPSIS Runs the graph to completion, the deadline, or cancellation. Never throws for node failures.
  #>
  param([System.Collections.IDictionary]$Graph, [datetime]$DeadlineUtc)
  $pollSeconds = [int](Get-DhValue $Graph.config 'pollSeconds' 20)
  $stopReason = ''
  try {
    while ($true) {
      $pending = @($Graph.nodes.Values | Where-Object { $_.state -eq 'pending' })
      $running = @($Graph.nodes.Values | Where-Object { $_.state -eq 'running' })
      if ($pending.Count -eq 0 -and $running.Count -eq 0) { break }
      $now = Get-DhUtcNow
      if ($script:Dh.CancelRequested) { $stopReason = 'cancelled'; break }
      if ($now -gt $DeadlineUtc) { $stopReason = 'deadline'; break }
      $progress = $false
      foreach ($node in $pending) {
        $outcome = Get-DhDependencyOutcome -Graph $Graph -Node $node
        if ($outcome -is [string] -and $outcome -eq 'wait') { continue }
        if ($outcome -is [hashtable]) {
          Complete-DhNode -Graph $Graph -Node $node -Status $outcome.status -Category $outcome.category -Code $outcome.code -Params $outcome.params
          $progress = $true
          continue
        }
        if ([int]$Graph.running[$node.class] -ge [int]$Graph.limits[$node.class]) { continue }
        $node.state = 'running'
        $node.startedAt = Get-DhUtcNow
        $node.nextAt = [datetime]::MinValue
        $Graph.running[$node.class] = [int]$Graph.running[$node.class] + 1
        $progress = $true
      }
      foreach ($node in @($Graph.nodes.Values | Where-Object { $_.state -eq 'running' -and $_.nextAt -le (Get-DhUtcNow) })) {
        try {
          if ($node.phase -eq 'init' -and (Test-DhSpecSkipForNode -Graph $Graph -Node $node)) { $progress = $true; continue }
          Invoke-DhNodeStep -Graph $Graph -Node $node
        } catch {
          $text = $_.Exception.Message
          Add-DhNodeEvidence -Node $node -Name 'harness-error.txt' -Content ("{0}`n{1}" -f $text, $_.ScriptStackTrace) | Out-Null
          $category = if ((Get-DhFailureCategory -Text $text) -eq 'infrastructure') { 'infrastructure' } else { 'harness' }
          $status = if ($category -eq 'infrastructure') { 'inconclusive' } else { 'failed' }
          Stop-DhNode -Graph $Graph -Node $node
          Complete-DhNode -Graph $Graph -Node $node -Status $status -Category $category -Code 'DH-GEN-001' -Params @{ stage = $node.stage }
        }
        $progress = $true
      }
      $running = @($Graph.nodes.Values | Where-Object { $_.state -eq 'running' })
      if (-not $progress -and $running.Count -eq 0) {
        foreach ($node in @($Graph.nodes.Values | Where-Object { $_.state -eq 'pending' })) {
          Complete-DhNode -Graph $Graph -Node $node -Status 'blocked' -Category 'harness' -Code 'DH-GEN-001' -Params @{ stage = $node.stage }
        }
        break
      }
      if ($progress) { Start-Sleep -Milliseconds 100; continue }
      $next = ($running | ForEach-Object { $_.nextAt } | Measure-Object -Minimum).Minimum
      $sleep = [math]::Min($pollSeconds, [math]::Max(0.2, ([datetime]$next - (Get-DhUtcNow)).TotalSeconds))
      Start-Sleep -Milliseconds ([int]($sleep * 1000))
    }
  } finally {
    foreach ($node in @($Graph.nodes.Values | Where-Object { $_.state -eq 'running' })) {
      Stop-DhNode -Graph $Graph -Node $node
      Complete-DhNode -Graph $Graph -Node $node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-DEP-004'
    }
    foreach ($node in @($Graph.nodes.Values | Where-Object { $_.state -eq 'pending' })) {
      Complete-DhNode -Graph $Graph -Node $node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-DEP-003'
    }
  }
  return $stopReason
}

function Set-DhNodeWait {
  param([System.Collections.IDictionary]$Node, [double]$Seconds)
  $Node.nextAt = (Get-DhUtcNow).AddSeconds([math]::Max(0.5, $Seconds))
}

function Get-DhNodeElapsedMinutes {
  param([System.Collections.IDictionary]$Node, [string]$Key = '')
  $start = if ($Key -and $Node.data.Contains($Key)) { [datetime]$Node.data[$Key] } else { [datetime]$Node.startedAt }
  return ((Get-DhUtcNow) - $start).TotalMinutes
}

function Start-DhBackgroundCommand {
  <#
  .SYNOPSIS Runs a slow external command (e.g., az acr run upload) on a thread job.
  #>
  param([string]$Command, [string[]]$Arguments)
  return (Start-ThreadJob -ScriptBlock {
      param($cmd, $argList)
      $env:AZURE_CORE_COLLECT_TELEMETRY = 'no'
      $output = & $cmd @argList 2>&1 | ForEach-Object { [string]$_ }
      [pscustomobject]@{ exitCode = $LASTEXITCODE; output = ($output -join "`n") }
    } -ArgumentList $Command, $Arguments)
}

function Receive-DhBackgroundCommand {
  param($Job)
  if ($Job.State -in @('NotStarted', 'Running')) { return $null }
  $result = Receive-Job -Job $Job -ErrorAction SilentlyContinue | Select-Object -Last 1
  Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
  if (-not $result) { return [pscustomobject]@{ exitCode = -1; output = ('background job ended in state ' + $Job.State) } }
  return $result
}
