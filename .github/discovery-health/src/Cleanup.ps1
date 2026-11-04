# Cleanup of discovery-github-test resources in dependency order, behind tag guards:
# orphaned operations -> investigations -> data-plane agents -> tool LinkedAgentIds -> tools -> ACR purge.

function Add-DhCleanupRecord {
  param([System.Collections.Generic.List[object]]$Records, [string]$Step, [string]$Target, [string]$Action, [int]$Status = 0, [bool]$DryRun)
  $Records.Add([ordered]@{ step = $Step; target = $Target; action = $(if ($DryRun) { "would $Action" } else { $Action }); status = $Status })
  Write-DhLog -Level $(if ($Status -ge 400) { 'warn' } else { 'info' }) -Scope 'cleanup' -Message (Get-DhMessage -Code 'DH-CLN-001' -Params @{ action = $(if ($DryRun) { "would $Action" } else { $Action }); target = ('{0} {1}' -f $Step, $Target) })
}

function Get-DhCleanupGuard {
  <#
  .SYNOPSIS Verifies the RG (and ACR when used) carry the test tag; returns '' when safe.
  #>
  param([System.Collections.IDictionary]$Config)
  $rg = Invoke-DhRest -Uri ('https://management.azure.com/subscriptions/{0}/resourcegroups/{1}?api-version=2021-04-01' -f $Config.subscriptionId, $Config.resourceGroup)
  if ($rg.status -ne 200 -or -not (Test-DhResourceTagged -Body $rg.body -Tag $Config.testTag)) { return 'resource group' }
  if ($Config.acrName) {
    $acr = Invoke-DhRest -Uri ('{0}/providers/Microsoft.ContainerRegistry/registries/{1}?api-version=2023-07-01' -f (Get-DhArmBase -Config $Config -ResourceGroup $Config.acrResourceGroup), $Config.acrName)
    if ($acr.status -ne 200 -or -not (Test-DhResourceTagged -Body $acr.body -Tag $Config.testTag)) { return 'container registry' }
  }
  return ''
}

function Get-DhPagedValues {
  param([string]$Uri, [string]$Audience)
  $values = [System.Collections.Generic.List[object]]::new()
  $next = $Uri
  $guard = 0
  while ($next -and $guard -lt 50) {
    $guard++
    $response = Invoke-DhRest -Method GET -Uri $next -Audience $Audience
    if ($response.status -ne 200) { break }
    foreach ($item in @(Get-DhValue $response.body 'value' @())) { $values.Add($item) }
    $next = [string](Get-DhValue $response.body 'nextLink' '')
  }
  return $values.ToArray()
}

function Remove-DhDataPlaneAgent {
  param([System.Collections.IDictionary]$Config, [string]$Name, [int]$WaitSeconds = 120)
  $url = '{0}/projects/{1}/agents/{2}?api-version={3}' -f $Config.workspaceEndpoint, [Uri]::EscapeDataString([string]$Config.project), [Uri]::EscapeDataString($Name), $Config.apiVersion
  $response = Invoke-DhRest -Method DELETE -Uri $url -Audience discovery -MaxAttempts 3
  if ($response.status -notin @(200, 202, 204, 404)) { return $response.status }
  $deadline = (Get-DhUtcNow).AddSeconds($WaitSeconds)
  while ((Get-DhUtcNow) -lt $deadline) {
    $check = Invoke-DhRest -Method GET -Uri $url -Audience discovery -MaxAttempts 1
    if ($check.status -eq 404) { return 204 }
    Start-Sleep -Seconds 5
  }
  return $response.status
}

function Remove-DhToolResource {
  <#
  .SYNOPSIS Clears internalMetadata.linkedAgentIds (blocks deletion) and deletes a tagged tool.
  #>
  param([System.Collections.IDictionary]$Config, [string]$ResourceId)
  $url = 'https://management.azure.com{0}?api-version={1}' -f $ResourceId, $Config.apiVersion
  $current = Invoke-DhRest -Method GET -Uri $url -Audience arm
  if ($current.status -eq 404) { return 404 }
  if ([string](Get-DhValue $current.body ('tags.' + $Config.testTag) '') -ne 'true') { return 412 }
  $linked = @(Get-DhValue $current.body 'properties.internalMetadata.linkedAgentIds' @())
  if ($linked.Count -gt 0) {
    $patch = Invoke-DhRest -Method PATCH -Uri $url -Audience arm -Body ([ordered]@{ properties = [ordered]@{ internalMetadata = [ordered]@{ linkedAgentIds = @() } } })
    if ($patch.status -in @(200, 202)) {
      for ($i = 0; $i -lt 20; $i++) {
        $state = [string](Get-DhValue (Invoke-DhRest -Method GET -Uri $url -Audience arm).body 'properties.provisioningState' '')
        if ($state -in @('Succeeded', 'Failed', '')) { break }
        Start-Sleep -Seconds 10
      }
    }
  }
  $delete = Invoke-DhRest -Method DELETE -Uri $url -Audience arm -MaxAttempts 4
  return $delete.status
}

function Invoke-DhAgentTeardown {
  <#
  .SYNOPSIS After-run cleanup for the agents and tools deployed by this run (agents first, then tools).
  #>
  param([System.Collections.IDictionary]$Graph)
  $config = $Graph.config
  foreach ($name in $Graph.agentCtx.Keys) {
    $deployed = [string]$Graph.agentCtx[$name].deployedName
    if ($deployed -and $deployed.StartsWith([string]$config.namePrefix)) {
      $status = Remove-DhDataPlaneAgent -Config $config -Name $deployed
      Write-DhLog -Scope 'cleanup' -Message ('Deleted agent {0} (HTTP {1}).' -f $deployed, $status)
    }
  }
  foreach ($key in $Graph.toolCtx.Keys) {
    $resourceId = [string]$Graph.toolCtx[$key].toolResourceId
    if ($resourceId) {
      $status = Remove-DhToolResource -Config $config -ResourceId $resourceId
      Write-DhLog -Scope 'cleanup' -Message ('Deleted tool {0} (HTTP {1}).' -f (($resourceId -split '/')[-1]), $status)
    }
  }
}

function Invoke-DhCleanupCommand {
  param([System.Collections.IDictionary]$Config, [string]$OutputDir, [string]$CatalogRoot, [string]$Ref = 'HEAD', [switch]$DryRun, [switch]$All)
  Initialize-DhRun -Config $Config -OutputDir $OutputDir -RunId ('cleanup-' + (New-DhRunId))
  $problems = @(Test-DhConfig -Config $Config -Stages @('tool-register', 'agent-register') | Where-Object { $_ -notmatch 'chatModel|location' })
  if ($problems.Count -gt 0) { throw ('Cleanup configuration invalid: {0}' -f ($problems -join '; ')) }
  if (Test-DhOidcAvailable) { Update-DhAzLogin -Force | Out-Null }
  Invoke-DhAz -Arguments @('account', 'set', '--subscription', [string]$Config.subscriptionId) | Out-Null
  $guard = Get-DhCleanupGuard -Config $Config
  if ($guard) {
    Write-DhLog -Level error -Message (Get-DhMessage -Code 'DH-PRE-002' -Params @{ resource = $guard; tag = $Config.testTag })
    return @{ exitCode = 2 }
  }
  $records = [System.Collections.Generic.List[object]]::new()
  $catalogAgents = @()
  $catalogDeployedNames = @()
  if (-not $All -and $CatalogRoot) {
    $catalogAgents = @(Get-DhCatalogAgentNames -CatalogRoot $CatalogRoot -Ref $Ref -Source 'worktree')
    $yamlPaths = @($catalogAgents | ForEach-Object { Join-Path $CatalogRoot ('agents/{0}/agent.yaml' -f $_) } | Where-Object { Test-Path -LiteralPath $_ })
    $parsed = ConvertFrom-DhYamlFiles -Paths $yamlPaths -Config $Config
    $catalogDeployedNames = @($parsed.Values | Where-Object { $_.ok -and $_.doc -is [System.Collections.IDictionary] } | ForEach-Object { '{0}{1}' -f $Config.namePrefix, [string]$_.doc['name'] })
    if ($catalogDeployedNames.Count -eq 0) { throw 'Could not read any agent.yaml names from the catalog; refusing to clean up agents.' }
  }
  $now = Get-DhUtcNow
  $maxRunAge = [int](Get-DhValue $Config 'cleanup.maxRunAgeHours' 8)
  $retainFailed = [int](Get-DhValue $Config 'cleanup.retainFailedDays' 14)
  $retention = [int](Get-DhValue $Config 'cleanup.retentionDays' 30)
  $prefix = [string]$Config.namePrefix
  $project = [Uri]::EscapeDataString([string]$Config.project)

  try {
    if ($Config.acrName) {
      $runs = Invoke-DhAz -Arguments @('acr', 'task', 'list-runs', '--registry', $Config.acrName, '--subscription', $Config.subscriptionId, '--run-status', 'Running', '--output', 'json') -AsJson
      foreach ($run in @($runs.json)) {
        $created = [datetime]::MinValue
        if ([datetime]::TryParse([string]$run.createTime, [ref]$created) -and ($now - $created.ToUniversalTime()).TotalHours -gt $maxRunAge) {
          $status = 0
          if (-not $DryRun) { $status = (Invoke-DhRest -Method POST -Uri (Get-DhAcrRunUrl -Config $Config -RunId ([string]$run.runId) -Suffix '/cancel') -Audience arm).status }
          Add-DhCleanupRecord -Records $records -Step 'acr-run' -Target ([string]$run.runId) -Action 'cancel' -Status $status -DryRun $DryRun
        }
      }
    }
  } catch { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-CLN-002' -Params @{ step = 'acr-runs'; status = 0 }) }

  $taggedTools = @()
  try {
    $taggedTools = @(Get-DhPagedValues -Uri ('{0}/providers/Microsoft.Discovery/tools?api-version={1}' -f (Get-DhArmBase -Config $Config), $Config.apiVersion) -Audience arm |
        Where-Object { [string](Get-DhValue $_ ('tags.' + $Config.testTag) '') -eq 'true' })
  } catch { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-CLN-002' -Params @{ step = 'list-tools'; status = 0 }) }
  $taggedToolIds = @($taggedTools | ForEach-Object { ([string]$_.id).ToLowerInvariant() })
  $agentMarker = '[{0} ' -f $Config.testTag
  $guardFailed = $false
  $dataPlane = [bool]($Config.workspaceEndpoint -and $Config.project)
  if ($dataPlane -and $Config.projectResourceId) {
    $projectResource = Invoke-DhRest -Uri ('https://management.azure.com{0}?api-version={1}' -f $Config.projectResourceId, $Config.apiVersion)
    if ($projectResource.status -ne 200 -or -not (Test-DhResourceTagged -Body $projectResource.body -Tag $Config.testTag)) {
      Write-DhLog -Level error -Message (Get-DhMessage -Code 'DH-PRE-002' -Params @{ resource = 'Discovery project'; tag = $Config.testTag })
      $dataPlane = $false
      $guardFailed = $true
    }
  } elseif ($dataPlane) {
    Write-DhLog -Level warn -Message 'projectResourceId is not configured; data-plane cleanup relies on the dgt- name prefix and discovery-github-test markers only.'
  }

  if ($dataPlane) {
    try {
      $ops = Get-DhPagedValues -Uri ('{0}/tools/projects/{1}/operations?api-version={2}&reverse=true&maxpagesize=100' -f $Config.workspaceEndpoint, $project, $Config.apiVersion) -Audience discovery
      foreach ($op in $ops) {
        $status = [string](Get-DhValue $op 'result.status' (Get-DhValue $op 'status' ''))
        if ($status -in $script:DhRunTerminal) { continue }
        $toolId = [string](Get-DhValue $op 'toolId' (Get-DhValue $op 'request.toolId' (Get-DhValue $op 'result.toolId' '')))
        if (-not $toolId -or $toolId.ToLowerInvariant() -notin $taggedToolIds) { continue }
        $created = [datetime]::MinValue
        if (-not [datetime]::TryParse([string](Get-DhValue $op 'result.createdAt' (Get-DhValue $op 'createdAt' '')), [ref]$created)) { continue }
        if (($now - $created.ToUniversalTime()).TotalHours -le $maxRunAge) { continue }
        $code = 0
        if (-not $DryRun) { $code = (Invoke-DhRest -Method POST -Uri ('{0}/tools/projects/{1}/operations/{2}:cancel?api-version={3}' -f $Config.workspaceEndpoint, $project, $op.id, $Config.apiVersion) -Audience discovery -Body @{}).status }
        Add-DhCleanupRecord -Records $records -Step 'tool-run' -Target ([string]$op.id) -Action 'cancel' -Status $code -DryRun $DryRun
      }
    } catch { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-CLN-002' -Params @{ step = 'tool-runs'; status = 0 }) }

    try {
      $investigations = Get-DhPagedValues -Uri ('{0}/projects/{1}/investigations?api-version={2}' -f $Config.workspaceEndpoint, $project, $Config.apiVersion) -Audience discovery
      foreach ($inv in $investigations) {
        $name = [string](Get-DhValue $inv 'name' '')
        if (-not $name.StartsWith('dgt-')) { continue }
        $label = '{0} {1}' -f (Get-DhValue $inv 'displayName' (Get-DhValue $inv 'properties.displayName' '')), (Get-DhValue $inv 'description' (Get-DhValue $inv 'properties.description' ''))
        if ($label -notmatch [regex]::Escape([string]$Config.testTag)) { continue }
        if (-not $All) {
          $created = [datetime]::MinValue
          $stamp = [string](Get-DhValue $inv 'createdAt' (Get-DhValue $inv 'systemData.createdAt' (Get-DhValue $inv 'properties.createdAt' '')))
          if (-not [datetime]::TryParse($stamp, [ref]$created)) { continue }
          if (($now - $created.ToUniversalTime()).TotalDays -le $retainFailed) { continue }
        }
        $code = 0
        if (-not $DryRun) { $code = (Remove-DhInvestigation -Config $Config -Name $name).status }
        Add-DhCleanupRecord -Records $records -Step 'investigation' -Target $name -Action 'delete' -Status $code -DryRun $DryRun
      }
    } catch { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-CLN-002' -Params @{ step = 'investigations'; status = 0 }) }

    try {
      $agents = Get-DhPagedValues -Uri ('{0}/projects/{1}/agents?api-version={2}' -f $Config.workspaceEndpoint, $project, $Config.apiVersion) -Audience discovery
      foreach ($agent in $agents) {
        $name = [string](Get-DhValue $agent 'name' '')
        if (-not $prefix -or -not $name.StartsWith($prefix)) { continue }
        $description = [string](Get-DhValue $agent 'description' (Get-DhValue $agent 'foundryDetails.description' (Get-DhValue $agent 'properties.description' '')))
        if (-not $description.Contains($agentMarker)) { continue }
        if (-not $All -and $name -in $catalogDeployedNames) { continue }
        $code = 0
        if (-not $DryRun) { $code = Remove-DhDataPlaneAgent -Config $Config -Name $name }
        Add-DhCleanupRecord -Records $records -Step 'agent' -Target $name -Action 'delete' -Status $code -DryRun $DryRun
      }
    } catch { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-CLN-002' -Params @{ step = 'agents'; status = 0 }) }
  }

  try {
    foreach ($tool in $taggedTools) {
      $owner = [string](Get-DhValue $tool 'tags.dgt-agent' '')
      if (-not $All -and $owner -in $catalogAgents) { continue }
      $code = 0
      if (-not $DryRun) { $code = Remove-DhToolResource -Config $Config -ResourceId ([string]$tool.id) }
      Add-DhCleanupRecord -Records $records -Step 'tool' -Target ([string]$tool.name) -Action 'delete' -Status $code -DryRun $DryRun
    }
  } catch { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-CLN-002' -Params @{ step = 'tools'; status = 0 }) }

  if ($Config.acrName) {
    try {
      $filter = '{0}/.*:.*' -f ([regex]::Escape(([string]$Config.acrRepositoryPrefix).Trim('/')))
      $ago = if ($All) { '0d' } else { '{0}d' -f $retention }
      $keep = if ($All) { 0 } else { [int](Get-DhValue $Config 'cleanup.keepImagesPerRepo' 2) }
      $purge = "acr purge --filter '$filter' --ago $ago --keep $keep --untagged" + $(if ($DryRun) { ' --dry-run' } else { '' })
      $empty = Join-Path $script:Dh.OutputDir 'empty-context'
      New-Item -ItemType Directory -Path $empty -Force | Out-Null
      $result = Invoke-DhAz -Arguments @('acr', 'run', '--registry', $Config.acrName, '--subscription', $Config.subscriptionId, '--cmd', $purge, $empty)
      Save-DhEvidence -Agent '_cleanup' -Stage 'cleanup' -Name 'acr-purge.log' -Content ($result.stdout + "`n" + $result.stderr) | Out-Null
      Add-DhCleanupRecord -Records $records -Step 'acr' -Target $filter -Action 'purge' -Status $(if ($result.exitCode -eq 0) { 200 } else { 500 }) -DryRun $DryRun
    } catch { Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-CLN-002' -Params @{ step = 'acr-purge'; status = 0 }) }
  }

  Write-DhJsonFile -Path (Join-Path $script:Dh.OutputDir 'cleanup.json') -InputObject ([ordered]@{ schema = 'discovery-health/cleanup@1'; runId = $script:Dh.RunId; dryRun = [bool]$DryRun; all = [bool]$All; actions = $records.ToArray() })
  $failed = @($records | Where-Object { $_.status -ge 400 -and $_.status -ne 404 }).Count
  Write-DhLog -Message ('Cleanup finished: {0} action(s), {1} failed{2}.' -f $records.Count, $failed, $(if ($DryRun) { ' (dry run)' } else { '' }))
  return @{ exitCode = $(if ($guardFailed) { 2 } elseif ($failed -gt 0) { 1 } else { 0 }); records = $records.ToArray() }
}
