# Reports and the public scorecard. Everything here is built from public result fields only.

$script:DhStageWeights = [ordered]@{ build = 20; 'image-smoke' = 10; 'tool-register' = 15; 'tool-run' = 20; 'agent-register' = 10; 'round-trip' = 25 }
$script:DhStatusRank = @{ failed = 7; blocked = 6; inconclusive = 5; untested = 4; skipped = 3; warning = 2; cached = 1; passed = 0 }
$script:DhStatusCredit = @{ passed = 1.0; cached = 1.0; warning = 0.75 }

function Add-DhMissingResults {
  <#
  .SYNOPSIS Synthesizes inconclusive results for every expected item that produced no record.
  #>
  param([object[]]$Results, [System.Collections.IDictionary]$Plan, [string]$RunId)
  $all = [System.Collections.Generic.List[object]]::new()
  foreach ($r in $Results) { $all.Add($r) }
  if (-not $Plan) { return $all.ToArray() }
  $have = @{}
  foreach ($r in $Results) { $have[('{0}|{1}|{2}' -f $r.agent, $r.tool, $r.stage)] = $true }
  foreach ($agent in $Plan.agents.Keys) {
    foreach ($item in @($Plan.agents[$agent].expected)) {
      $key = '{0}|{1}|{2}' -f $agent, $item.tool, $item.stage
      if ($have.ContainsKey($key)) { continue }
      $result = New-DhResult -Agent $agent -Tool ([string]$item.tool) -Stage $item.stage -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-RPT-001' -Messages @((New-DhMessage -Level warning -Code 'DH-RPT-001'))
      $result.runId = $RunId
      $all.Add($result)
    }
  }
  return $all.ToArray()
}

function Test-DhResultNeedsAttention {
  <#
  .SYNOPSIS True for any non-passing result or any result carrying a warning/error message.
  #>
  param($Result)
  if ($Result.status -notin @('passed', 'cached')) { return $true }
  return (@($Result.messages | Where-Object { $_.level -in @('warning', 'error') }).Count -gt 0)
}

function Get-DhWorstStatus {
  param([string[]]$Statuses)
  $worst = ''
  foreach ($s in $Statuses) { if (-not $worst -or $script:DhStatusRank[$s] -gt $script:DhStatusRank[$worst]) { $worst = $s } }
  return $worst
}

function Get-DhAgentSummaries {
  <#
  .SYNOPSIS Per-agent state, score and coverage from a run's results.
  #>
  param([object[]]$Results, [string[]]$Stages)
  $byAgent = [ordered]@{}
  foreach ($r in ($Results | Where-Object { $_.agent -ne '_run' } | Sort-Object agent)) {
    if (-not $byAgent.Contains($r.agent)) { $byAgent[$r.agent] = [System.Collections.Generic.List[object]]::new() }
    $byAgent[$r.agent].Add($r)
  }
  $summaries = [ordered]@{}
  foreach ($agent in $byAgent.Keys) {
    $records = @($byAgent[$agent])
    $stageStatus = [ordered]@{}
    $earned = 0.0; $possible = 0.0; $tested = 0; $applicable = 0
    $hasTools = @($records | Where-Object { $_.tool }).Count -gt 0
    foreach ($stage in @('discover') + @($script:DhStageWeights.Keys)) {
      $stageRecords = @($records | Where-Object { $_.stage -eq $stage })
      if ($stageRecords.Count -eq 0) { continue }
      $stageStatus[$stage] = Get-DhWorstStatus -Statuses @($stageRecords | ForEach-Object { $_.status })
      if ($stage -eq 'discover') { continue }
      if ($script:DhToolStages -contains $stage -and -not $hasTools) { continue }
      $weight = [double]$script:DhStageWeights[$stage]
      $credit = (@($stageRecords | ForEach-Object { [double](Get-DhValue $script:DhStatusCredit $_.status 0.0) }) | Measure-Object -Average).Average
      $earned += $weight * $credit
      $possible += $weight
      foreach ($rec in $stageRecords) { $applicable++; if ($rec.status -in @('passed', 'cached', 'warning', 'failed')) { $tested++ } }
    }
    $nonDiscover = @($records | Where-Object { $_.stage -ne 'discover' })
    $contributionFailure = @($records | Where-Object { $_.status -eq 'failed' -and $_.category -eq 'contribution' }).Count -gt 0
    $state = if ($contributionFailure) { 'failing' }
    elseif (@($nonDiscover | Where-Object { $_.status -in @('inconclusive', 'blocked') -or ($_.status -eq 'failed') }).Count -gt 0) { 'inconclusive' }
    elseif (@($nonDiscover | Where-Object { $_.status -in @('untested', 'skipped') }).Count -gt 0) { 'partial' }
    elseif ($nonDiscover.Count -eq 0) { 'untested' }
    else { 'healthy' }
    $messages = @($records | Where-Object { Test-DhResultNeedsAttention $_ } | ForEach-Object {
        $rec = $_
        foreach ($m in @($rec.messages)) { if ($m.level -ne 'info') { [ordered]@{ tool = $rec.tool; stage = $rec.stage; status = $rec.status; code = $m.code; text = $m.text } } }
      })
    $duration = (@($records | ForEach-Object { [double]$_.durationSec }) | Measure-Object -Sum).Sum
    $summaries[$agent] = [ordered]@{
      state = $state; score = $(if ($possible -gt 0) { [int][math]::Round(100 * $earned / $possible) } else { 0 })
      coverage = $(if ($applicable -gt 0) { [int][math]::Round(100 * $tested / $applicable) } else { 0 })
      stages = $stageStatus; tools = @($records | Where-Object { $_.tool } | ForEach-Object { $_.tool } | Select-Object -Unique)
      specSource = [string](@($records | Where-Object { $_.stage -eq 'discover' -and -not $_.tool } | ForEach-Object { Get-DhValue $_.data 'specSource' '' }) | Select-Object -First 1)
      fingerprint = [string](@($records | Where-Object { $_.stage -eq 'discover' -and -not $_.tool } | ForEach-Object { Get-DhValue $_.data 'fingerprint' '' }) | Select-Object -First 1)
      messages = @($messages | Select-Object -First 25); durationSec = [int]$duration
    }
  }
  return $summaries
}

function ConvertTo-DhHtml {
  param([AllowEmptyString()][string]$Text)
  return [System.Net.WebUtility]::HtmlEncode([string]$Text)
}

function Get-DhStateBadge {
  param([string]$State, [int]$Score)
  $color = switch ($State) { 'healthy' { 'brightgreen' } 'partial' { 'yellowgreen' } 'inconclusive' { 'lightgrey' } 'failing' { 'red' } 'removed' { 'inactive' } default { 'lightgrey' } }
  return [ordered]@{ schemaVersion = 1; label = 'discovery health'; message = $(if ($State -in @('untested', 'removed')) { $State } else { '{0} {1}' -f $State, $Score }); color = $color }
}

function Merge-DhState {
  <#
  .SYNOPSIS Merges this run into the published state; agents not in the run keep their previous entry.
  #>
  param([System.Collections.IDictionary]$Previous, [System.Collections.IDictionary]$Summaries, [string]$RunId, [string]$GitSha, [int]$HistoryRuns, [string[]]$CatalogAgents)
  $now = ConvertTo-DhIso (Get-DhUtcNow)
  $state = [ordered]@{ schema = 'discovery-health/state@1'; updatedAt = $now; runs = @(); agents = [ordered]@{} }
  if ($Previous) {
    foreach ($name in $Previous.agents.Keys) { $state.agents[$name] = $Previous.agents[$name] }
    $state.runs = @($Previous.runs)
  }
  $runAgents = [ordered]@{}
  foreach ($name in $Summaries.Keys) {
    $s = $Summaries[$name]
    $prior = Get-DhValue $state.agents $name $null
    $history = @()
    if ($prior) { $history = @($prior.history) }
    $history = @(@([ordered]@{ runId = $RunId; at = $now; state = $s.state; score = $s.score }) + $history | Select-Object -First $HistoryRuns)
    $lastPassed = if ($s.state -eq 'healthy') { $now } elseif ($prior) { [string](Get-DhValue $prior 'lastHealthy' '') } else { '' }
    $streak = 1
    foreach ($h in @($history | Select-Object -Skip 1)) { if ($h.state -eq $s.state) { $streak++ } else { break } }
    $state.agents[$name] = [ordered]@{
      state = $s.state; score = $s.score; coverage = $s.coverage; specSource = $s.specSource; fingerprint = $s.fingerprint; testedSha = $GitSha
      lastTested = $now; lastHealthy = $lastPassed; streak = $streak; stages = $s.stages; messages = $s.messages; lastDurationSec = $s.durationSec; history = $history
    }
    $runAgents[$name] = [ordered]@{ state = $s.state; score = $s.score }
  }
  if ($CatalogAgents -and $CatalogAgents.Count -gt 0) {
    foreach ($name in @($state.agents.Keys)) {
      if ($name -notin $CatalogAgents -and $state.agents[$name].state -ne 'removed') { $state.agents[$name].state = 'removed' }
    }
  }
  $counts = [ordered]@{}
  foreach ($name in $runAgents.Keys) { $counts[$runAgents[$name].state] = 1 + [int](Get-DhValue $counts $runAgents[$name].state 0) }
  $state.runs = @(@([ordered]@{ runId = $RunId; at = $now; gitSha = $GitSha; counts = $counts; agents = $runAgents }) + @($state.runs | Where-Object { $_.runId -ne $RunId }) | Select-Object -First $HistoryRuns)
  return $state
}

function New-DhSummaryMarkdown {
  param([object[]]$Results, [System.Collections.IDictionary]$Summaries, [string]$RunId, [string]$GitSha, [string]$Title, [string]$Context = '')
  $sb = [System.Text.StringBuilder]::new()
  [void]$sb.AppendLine("## $Title")
  [void]$sb.AppendLine()
  [void]$sb.AppendLine(('Run `{0}` - tested commit `{1}`{2}' -f $RunId, $(if ($GitSha) { $GitSha.Substring(0, [math]::Min(12, $GitSha.Length)) } else { 'unknown' }), $(if ($Context) { ' - ' + $Context } else { '' })))
  [void]$sb.AppendLine()
  $states = [ordered]@{}
  foreach ($name in $Summaries.Keys) { $states[$Summaries[$name].state] = 1 + [int](Get-DhValue $states $Summaries[$name].state 0) }
  [void]$sb.AppendLine('| State | Agents |')
  [void]$sb.AppendLine('| --- | ---: |')
  foreach ($key in @('healthy', 'partial', 'inconclusive', 'failing', 'untested')) { if ($states.Contains($key)) { [void]$sb.AppendLine(('| {0} | {1} |' -f $key, $states[$key])) } }
  [void]$sb.AppendLine()
  $preflight = @($Results | Where-Object { $_.agent -eq '_run' -and $_.stage -eq 'preflight' })
  foreach ($p in $preflight) { foreach ($m in @($p.messages)) { [void]$sb.AppendLine(('> **Preflight {0}:** {1}' -f $p.status, $m.text)) } }
  [void]$sb.AppendLine('| Agent | State | Score | Coverage | build | smoke | register | run | agent | round trip |')
  [void]$sb.AppendLine('| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- |')
  foreach ($name in ($Summaries.Keys | Sort-Object)) {
    $s = $Summaries[$name]
    $cells = foreach ($stage in $script:DhStageWeights.Keys) { [string](Get-DhValue $s.stages $stage '-') }
    [void]$sb.AppendLine(('| {0} | {1} | {2} | {3}% | {4} |' -f $name, $s.state, $s.score, $s.coverage, ($cells -join ' | ')))
  }
  $issues = @($Results | Where-Object { Test-DhResultNeedsAttention $_ })
  if ($issues.Count -gt 0) {
    [void]$sb.AppendLine()
    [void]$sb.AppendLine(('### All warnings and errors ({0})' -f $issues.Count))
    [void]$sb.AppendLine()
    [void]$sb.AppendLine('| Agent | Tool | Stage | Status | Category | Details |')
    [void]$sb.AppendLine('| --- | --- | --- | --- | --- | --- |')
    foreach ($r in ($issues | Sort-Object agent, tool, stage)) {
      $details = (@($r.messages | ForEach-Object { '`{0}` {1}' -f $_.code, ($_.text -replace '\|', '/') })) -join '<br>'
      [void]$sb.AppendLine(('| {0} | {1} | {2} | {3} | {4} | {5} |' -f $r.agent, $(if ($r.tool) { $r.tool } else { '-' }), $r.stage, $r.status, $(if ($r.category) { $r.category } else { '-' }), $details))
    }
  }
  return $sb.ToString()
}

function New-DhJUnitXml {
  param([object[]]$Results)
  $xml = [System.Text.StringBuilder]::new()
  [void]$xml.AppendLine('<?xml version="1.0" encoding="UTF-8"?>')
  $failures = @($Results | Where-Object { $_.status -eq 'failed' }).Count
  $skipped = @($Results | Where-Object { $_.status -notin @('passed', 'cached', 'warning', 'failed') }).Count
  [void]$xml.AppendLine(('<testsuites name="discovery-health" tests="{0}" failures="{1}" skipped="{2}">' -f $Results.Count, $failures, $skipped))
  foreach ($group in ($Results | Group-Object agent | Sort-Object Name)) {
    [void]$xml.AppendLine(('  <testsuite name="{0}" tests="{1}">' -f (ConvertTo-DhHtml $group.Name), $group.Count))
    foreach ($r in $group.Group) {
      $name = '{0}{1}' -f $(if ($r.tool) { $r.tool + '/' } else { '' }), $r.stage
      $text = ConvertTo-DhHtml ((@($r.messages | ForEach-Object { '{0} {1}' -f $_.code, $_.text })) -join '; ')
      [void]$xml.Append(('    <testcase classname="{0}" name="{1}" time="{2}"' -f (ConvertTo-DhHtml $r.agent), (ConvertTo-DhHtml $name), [double]$r.durationSec))
      if ($r.status -eq 'failed') { [void]$xml.AppendLine(('><failure message="{0}" type="{1}"/></testcase>' -f $text, (ConvertTo-DhHtml $r.category))) }
      elseif ($r.status -in @('passed', 'cached', 'warning')) { [void]$xml.AppendLine('/>') }
      else { [void]$xml.AppendLine(('><skipped message="{0}: {1}"/></testcase>' -f $r.status, $text)) }
    }
    [void]$xml.AppendLine('  </testsuite>')
  }
  [void]$xml.AppendLine('</testsuites>')
  return $xml.ToString()
}

function New-DhSite {
  <#
  .SYNOPSIS Static scorecard site (no external assets) generated from the public state.
  #>
  param([System.Collections.IDictionary]$State, [string]$Destination, [string]$RepositoryUrl = '')
  if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
  New-Item -ItemType Directory -Path (Join-Path $Destination 'badges') -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $Destination 'history') -Force | Out-Null
  Write-DhJsonFile -Path (Join-Path $Destination 'state.json') -InputObject $State
  foreach ($run in @($State.runs)) { Write-DhJsonFile -Path (Join-Path $Destination ('history/{0}.json' -f $run.runId)) -InputObject $run }
  $rows = [System.Text.StringBuilder]::new()
  foreach ($name in ($State.agents.Keys | Sort-Object)) {
    $a = $State.agents[$name]
    Write-DhJsonFile -Path (Join-Path $Destination ('badges/{0}.json' -f $name)) -InputObject (Get-DhStateBadge -State $a.state -Score ([int]$a.score))
    $cells = foreach ($stage in $script:DhStageWeights.Keys) {
      $status = [string](Get-DhValue $a.stages $stage '')
      '<td class="s-{0}">{1}</td>' -f (ConvertTo-DhHtml $(if ($status) { $status } else { 'na' })), (ConvertTo-DhHtml $(if ($status) { $status } else { '-' }))
    }
    $details = (@($a.messages | Select-Object -First 8 | ForEach-Object { '<li><code>{0}</code> {1}{2}: {3}</li>' -f (ConvertTo-DhHtml $_.code), (ConvertTo-DhHtml $(if ($_.tool) { $_.tool + '/' } else { '' })), (ConvertTo-DhHtml $_.stage), (ConvertTo-DhHtml $_.text) })) -join ''
    $trend = (@($a.history | Select-Object -First 12 | ForEach-Object { '<span class="dot st-{0}" title="{1} {2}"></span>' -f (ConvertTo-DhHtml $_.state), (ConvertTo-DhHtml $_.at), (ConvertTo-DhHtml $_.state) })) -join ''
    $link = if ($RepositoryUrl) { '<a href="{0}/tree/main/agents/{1}">{1}</a>' -f (ConvertTo-DhHtml $RepositoryUrl), (ConvertTo-DhHtml $name) } else { ConvertTo-DhHtml $name }
    [void]$rows.AppendLine(('<tr data-state="{0}"><td>{1}</td><td class="st st-{0}">{0}</td><td data-v="{2}">{2}</td><td data-v="{3}">{3}%</td>{4}<td>{5}</td><td>{6}</td><td>{7}</td><td>{8}</td></tr>' -f
        (ConvertTo-DhHtml $a.state), $link, [int]$a.score, [int]$a.coverage, ($cells -join ''), (ConvertTo-DhHtml ([string]$a.lastTested)), (ConvertTo-DhHtml ([string]$a.lastHealthy)), $trend, $(if ($details) { "<details><summary>$(@($a.messages).Count)</summary><ul>$details</ul></details>" } else { '' })))
  }
  $counts = [ordered]@{}
  foreach ($name in $State.agents.Keys) { $counts[$State.agents[$name].state] = 1 + [int](Get-DhValue $counts $State.agents[$name].state 0) }
  $summary = (@($counts.Keys | Sort-Object | ForEach-Object { '<span class="pill st-{0}">{0}: {1}</span>' -f (ConvertTo-DhHtml $_), $counts[$_] })) -join ' '
  $template = [System.IO.File]::ReadAllText((Join-Path $script:DhRoot 'templates/site/index.html.tmpl'))
  $html = $template.Replace('{{GENERATED}}', (ConvertTo-DhHtml ([string]$State.updatedAt))).Replace('{{SUMMARY}}', $summary).Replace('{{ROWS}}', $rows.ToString()).Replace('{{RUNS}}', [string]@($State.runs).Count)
  [System.IO.File]::WriteAllText((Join-Path $Destination 'index.html'), $html, [System.Text.UTF8Encoding]::new($false))
  Copy-Item -LiteralPath (Join-Path $script:DhRoot 'templates/site/style.css') -Destination (Join-Path $Destination 'style.css') -Force
  [System.IO.File]::WriteAllText((Join-Path $Destination '.nojekyll'), '', [System.Text.UTF8Encoding]::new($false))
}

function Import-DhCheckpoints {
  <#
  .SYNOPSIS Downloads result/operation checkpoints for a run from private storage (shards that died before uploading).
  #>
  param([string]$RunId, [string]$Destination)
  if (-not (Get-DhEvidenceBase) -or -not $RunId) { return 0 }
  $prefix = '{0}/runs/{1}/' -f (Get-DhValue $script:Dh.Config 'testTag' 'discovery-github-test'), $RunId
  $count = 0
  foreach ($name in (Get-DhBlobList -Prefix $prefix)) {
    $relative = $name.Substring($prefix.Length)
    if ($relative -notmatch '^(results|operations)/[^\\]+\.json$' -or $relative -match '\.\.') { continue }
    $text = Get-DhBlobText -Name $name
    if ($null -eq $text) { continue }
    Write-DhTextFile -Path (Join-Path $Destination $relative) -Content $text
    $count++
  }
  return $count
}

function Invoke-DhOrphanReaper {
  <#
  .SYNOPSIS Cancels remote operations a lost shard left in the 'running' state.
  #>
  param([string[]]$Directories, [string]$RunId)
  $cancelled = 0
  $seen = @{}
  foreach ($dir in $Directories) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    foreach ($file in (Get-ChildItem -LiteralPath $dir -Recurse -Filter '*.json' -File | Where-Object { $_.FullName -match '[\\/]operations[\\/]' })) {
      try { $op = Read-DhJsonFile -Path $file.FullName } catch { continue }
      if ($op.schema -ne 'discovery-health/operation@1' -or $op.status -ne 'running' -or ($RunId -and $op.runId -ne $RunId)) { continue }
      $key = '{0}|{1}' -f $op.kind, $op.id
      if ($seen.ContainsKey($key) -or -not $op.cancelUrl) { continue }
      $seen[$key] = $true
      if (-not ([string]$op.cancelUrl).StartsWith('https://')) { continue }
      try {
        $response = Invoke-DhRest -Method ([string]$op.cancelMethod) -Uri ([string]$op.cancelUrl) -Audience ([string]$op.audience) -Body @{} -MaxAttempts 2 -TimeoutSec 30
        Write-DhLog -Level warn -Message ('Reaped orphaned {0} operation from {1} (HTTP {2}).' -f $op.kind, $op.node, $response.status)
        $cancelled++
      } catch { }
    }
  }
  return $cancelled
}

function Invoke-DhReportCommand {
  param(
    [System.Collections.IDictionary]$Config, [string[]]$ResultsDir, [string]$PlanPath, [string]$OutputDir, [string]$PreviousStatePath, [string]$PreviousStateUrl,
    [switch]$Site, [switch]$Bootstrap, [string]$FailOn, [string]$Title = 'Discovery Health', [string]$Context = '', [string]$RepositoryUrl = '',
    [switch]$FromCheckpoints, [switch]$ReapOrphans
  )
  $plan = if ($PlanPath -and (Test-Path -LiteralPath $PlanPath)) { Read-DhJsonFile -Path $PlanPath } else { $null }
  $runId = if ($plan) { [string]$plan.runId } else { '' }
  Initialize-DhRun -Config $Config -OutputDir $OutputDir -RunId $runId
  $dirs = @($ResultsDir)
  if ($FromCheckpoints -and $runId) {
    $checkpoints = Join-Path $script:Dh.OutputDir 'checkpoints'
    $imported = Import-DhCheckpoints -RunId $runId -Destination $checkpoints
    if ($imported -gt 0) { $dirs += $checkpoints; Write-DhLog -Message ('Imported {0} checkpoint file(s) from private storage.' -f $imported) }
  }
  if ($ReapOrphans) {
    $reaped = Invoke-DhOrphanReaper -Directories $dirs -RunId $runId
    if ($reaped -gt 0) { Write-DhAnnotation -Level warning -Title 'Discovery Health' -Message ('Cancelled {0} orphaned remote operation(s) left by lost shards.' -f $reaped) }
  }
  $results = @(Read-DhResults -Directories $dirs)
  if (-not $runId -and $results.Count -gt 0) { $script:Dh.RunId = [string]$results[0].runId }
  $results = @(Add-DhMissingResults -Results $results -Plan $plan -RunId $script:Dh.RunId)
  $gitSha = if ($plan -and $plan.gitSha) { [string]$plan.gitSha } else { [string](@($results | Where-Object { $_.gitSha } | Select-Object -First 1).gitSha) }
  $stages = if ($plan) { @($plan.stages) } else { $script:DhStages }
  $summaries = Get-DhAgentSummaries -Results $results -Stages $stages
  Write-DhJsonFile -Path (Join-Path $script:Dh.OutputDir 'results.json') -InputObject ([ordered]@{ schema = 'discovery-health/results@1'; runId = $script:Dh.RunId; gitSha = $gitSha; results = $results; agents = $summaries })
  $markdown = New-DhSummaryMarkdown -Results $results -Summaries $summaries -RunId $script:Dh.RunId -GitSha $gitSha -Title $Title -Context $Context
  Write-DhTextFile -Path (Join-Path $script:Dh.OutputDir 'summary.md') -Content $markdown
  Write-DhTextFile -Path (Join-Path $script:Dh.OutputDir 'junit.xml') -Content (New-DhJUnitXml -Results $results)
  if ($env:GITHUB_STEP_SUMMARY) {
    $limit = 900KB
    $text = if ($markdown.Length -gt $limit) { $markdown.Substring(0, $limit) + "`n`n_Truncated; see the discovery-health-report artifact for the full list._`n" } else { $markdown }
    [System.IO.File]::AppendAllText($env:GITHUB_STEP_SUMMARY, $text)
  }
  $errors = @($results | Where-Object { $_.status -eq 'failed' })
  $warnings = @($results | Where-Object { $_.status -in @('inconclusive', 'blocked', 'warning', 'untested') })
  foreach ($r in ($errors | Select-Object -First 10)) { Write-DhAnnotation -Level error -Title ('{0} {1}' -f $r.agent, $r.stage) -Message ((@($r.messages | ForEach-Object { $_.text })) -join ' ') }
  foreach ($r in ($warnings | Select-Object -First 10)) { Write-DhAnnotation -Level warning -Title ('{0} {1}' -f $r.agent, $r.stage) -Message ((@($r.messages | ForEach-Object { $_.text })) -join ' ') }
  if ($errors.Count + $warnings.Count -gt 20) { Write-DhAnnotation -Level notice -Title 'Discovery Health' -Message ('{0} errors and {1} warnings in total; all are listed in the job summary and report artifact.' -f $errors.Count, $warnings.Count) }
  $publishOk = $true
  if ($Site) {
    $previous = $null
    try { $previous = Get-DhPreviousState -Path $PreviousStatePath -Url $PreviousStateUrl } catch { Write-DhLog -Level warn -Message $_.Exception.Message }
    if (-not $previous -and (Get-DhEvidenceBase)) {
      $mirror = Get-DhBlobText -Name ('{0}/scorecard/state.json' -f $Config.testTag)
      if ($mirror) {
        try { $candidate = ConvertFrom-DhJson $mirror; if ($candidate.schema -eq 'discovery-health/state@1') { $previous = $candidate; Write-DhLog -Message 'Loaded previous scorecard state from the private mirror.' } } catch { }
      }
    }
    if (-not $previous -and -not $Bootstrap) {
      Write-DhLog -Level error -Message 'Previous scorecard state could not be loaded (Pages URL or private mirror); refusing to publish a reset history. Use -Bootstrap only for the first deployment.'
      $publishOk = $false
    } else {
      $catalogAgents = if ($plan -and $plan.Contains('allAgents')) { @($plan.allAgents) } else { @() }
      $state = Merge-DhState -Previous $previous -Summaries $summaries -RunId $script:Dh.RunId -GitSha $gitSha -HistoryRuns ([int](Get-DhValue $Config 'scorecard.historyRuns' 12)) -CatalogAgents $catalogAgents
      New-DhSite -State $state -Destination (Join-Path $script:Dh.OutputDir 'site') -RepositoryUrl $RepositoryUrl
      if (Get-DhEvidenceBase) { Send-DhBlob -Name ('{0}/scorecard/state.json' -f $Config.testTag) -Content (ConvertTo-DhJson $state) -ContentType 'application/json' | Out-Null }
      Write-DhLog -Message ('Scorecard site written to {0}' -f (Join-Path $script:Dh.OutputDir 'site'))
    }
  }
  $policy = if ($FailOn) { $FailOn } else { [string](Get-DhValue $Config 'failOn' 'contribution') }
  $exit = 0
  if ($policy -eq 'any' -and ($errors.Count + @($results | Where-Object { $_.status -eq 'inconclusive' }).Count) -gt 0) { $exit = 1 }
  if ($policy -eq 'contribution' -and @($summaries.Values | Where-Object { $_.state -eq 'failing' }).Count -gt 0) { $exit = 1 }
  if (-not $publishOk) { $exit = 3 }
  Write-DhLog -Message ('Report: {0} agent(s); {1} failed result(s); {2} warning-level result(s); exit {3}.' -f $summaries.Count, $errors.Count, $warnings.Count, $exit)
  return @{ exitCode = $exit; summaries = $summaries; results = $results }
}
