# Agent selection, sharding and the expected-item manifest used to detect lost results.

function Get-DhChangedAgents {
  <#
  .SYNOPSIS Agents whose folder or central spec changed between two git refs.
  #>
  param([Parameter(Mandatory)][string]$CatalogRoot, [Parameter(Mandatory)][string]$BaseRef, [string]$HeadRef = 'HEAD', [string]$SpecRelPath = '.github/discovery-health/specs')
  $r = Invoke-DhGit -Root $CatalogRoot -Arguments @('diff', '--name-only', "$BaseRef...$HeadRef", '--', 'agents/', $SpecRelPath)
  if ($r.exitCode -ne 0) { throw ('git diff failed: {0}' -f ($r.lines -join ' ')) }
  $names = [System.Collections.Generic.List[string]]::new()
  foreach ($line in $r.lines) {
    $name = ''
    if ($line -match '^agents/([^/]+)/') { $name = $Matches[1] }
    elseif ($line -match ('^' + [regex]::Escape($SpecRelPath) + '/([^/]+)\.yaml$')) { $name = $Matches[1] }
    if ($name -and $name -ne 'tmp' -and -not $names.Contains($name)) { $names.Add($name) }
  }
  return $names.ToArray()
}

function Get-DhAgentWeight {
  param([System.Collections.IDictionary]$Agent, [System.Collections.IDictionary]$PreviousState)
  $previous = Get-DhValue $PreviousState ('agents.' + $Agent.name + '.lastDurationSec') 0
  if ([double]$previous -gt 0) { return [double]$previous }
  $weight = 120.0
  foreach ($tool in $Agent.tools.Values) { $weight += $(if ($tool.gpu) { 2400 } else { 900 }) }
  return $weight
}

function Split-DhShards {
  <#
  .SYNOPSIS Greedy, deterministic balancing of weighted agents across shards.
  #>
  param([object[]]$Items, [int]$Count)
  $count = [math]::Max(1, $Count)
  $shards = @(for ($i = 0; $i -lt $count; $i++) { [ordered]@{ index = $i + 1; load = 0.0; agents = [System.Collections.Generic.List[string]]::new() } })
  foreach ($item in ($Items | Sort-Object @{ Expression = { $_.weight }; Descending = $true }, @{ Expression = { $_.name } })) {
    $target = $shards | Sort-Object @{ Expression = { $_.load } }, @{ Expression = { $_.index } } | Select-Object -First 1
    $target.agents.Add($item.name)
    $target.load += $item.weight
  }
  return $shards
}

function Get-DhExpectedItems {
  <#
  .SYNOPSIS Every (tool, stage) result the run must produce for an agent, used to synthesize lost results.
  #>
  param([System.Collections.IDictionary]$Agent, [string[]]$Stages)
  $items = [System.Collections.Generic.List[object]]::new()
  $items.Add([ordered]@{ tool = ''; stage = 'discover' })
  foreach ($tool in $Agent.tools.Values) {
    $items.Add([ordered]@{ tool = $tool.name; stage = 'discover' })
    foreach ($stage in $script:DhToolStages) {
      if ($Stages -contains $stage -or ($stage -eq 'image-smoke' -and $Stages -contains 'build')) { $items.Add([ordered]@{ tool = $tool.name; stage = $stage }) }
    }
  }
  foreach ($stage in $script:DhAgentStages) { if ($Stages -contains $stage) { $items.Add([ordered]@{ tool = ''; stage = $stage }) } }
  return $items.ToArray()
}

function New-DhPlan {
  param(
    [Parameter(Mandatory)][System.Collections.IDictionary]$Catalog,
    [Parameter(Mandatory)][string[]]$Stages,
    [int]$Shards = 1,
    [System.Collections.IDictionary]$PreviousState,
    [string]$RunId,
    [hashtable]$Context = @{}
  )
  $weighted = foreach ($agent in $Catalog.agents.Values) { [ordered]@{ name = $agent.name; weight = (Get-DhAgentWeight -Agent $agent -PreviousState $PreviousState) } }
  $split = Split-DhShards -Items @($weighted) -Count $Shards
  $agents = [ordered]@{}
  foreach ($shard in $split) {
    foreach ($name in $shard.agents) {
      $agent = $Catalog.agents[$name]
      $agents[$name] = [ordered]@{
        shard = $shard.index; fingerprint = $agent.fingerprint; tools = @($agent.tools.Keys)
        gpu = [bool](@($agent.tools.Values | Where-Object { $_.gpu }).Count); expected = @(Get-DhExpectedItems -Agent $agent -Stages $Stages)
      }
    }
  }
  return [ordered]@{
    schema = 'discovery-health/plan@1'; runId = $RunId; createdAt = (ConvertTo-DhIso (Get-DhUtcNow)); gitSha = $Catalog.gitSha
    ref = $Catalog.ref; source = $Catalog.source; stages = $Stages; shards = [math]::Max(1, $Shards); unknownAgents = @($Catalog.unknown)
    context = $Context; agents = $agents
    matrix = @($split | Where-Object { $_.agents.Count -gt 0 } | ForEach-Object { [ordered]@{ shard = $_.index; agents = ($_.agents -join ','); weight = [int]$_.load } })
  }
}

function Get-DhShardAgents {
  param([System.Collections.IDictionary]$Plan, [int]$Shard)
  return @($Plan.agents.Keys | Where-Object { [int]$Plan.agents[$_].shard -eq $Shard })
}
