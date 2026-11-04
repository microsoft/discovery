# Stage: build (+ image-smoke) in Azure Container Registry Tasks.
# One multi-step ACR run per tool: build (OCI labels) -> push -> smoke cmd steps.

$script:DhAcrApi = '2019-06-01-preview'
$script:DhAcrTerminal = @('Succeeded', 'Failed', 'Canceled', 'Error', 'Timeout')

function Get-DhAcrLoginServer {
  param([System.Collections.IDictionary]$Config)
  return ('{0}.azurecr.io' -f ([string]$Config.acrName).ToLowerInvariant())
}

function Get-DhImageRepository {
  param([System.Collections.IDictionary]$Config, [System.Collections.IDictionary]$Tool)
  return ('{0}/{1}' -f ([string]$Config.acrRepositoryPrefix).Trim('/'), $Tool.imageName)
}

function Get-DhAcrRunUrl {
  param([System.Collections.IDictionary]$Config, [string]$RunId, [string]$Suffix = '')
  return ('{0}/providers/Microsoft.ContainerRegistry/registries/{1}/runs/{2}{3}?api-version={4}' -f (Get-DhArmBase -Config $Config -ResourceGroup $Config.acrResourceGroup), $Config.acrName, $RunId, $Suffix, $script:DhAcrApi)
}

function Find-DhImageForFingerprint {
  <#
  .SYNOPSIS Newest ACR tag for a tool fingerprint (tags are <fp12>-<yyyyMMddHHmm>, never reused).
  #>
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Tool)
  $config = $Graph.config
  $repo = Get-DhImageRepository -Config $config -Tool $Tool
  $cacheKey = 'tags:' + $repo
  if (-not $Graph.caches.Contains($cacheKey)) {
    $r = Invoke-DhAz -Arguments @('acr', 'repository', 'show-tags', '--name', $config.acrName, '--repository', $repo, '--subscription', $config.subscriptionId, '--detail', '--orderby', 'time_desc', '--output', 'json') -AsJson
    $Graph.caches[$cacheKey] = if ($r.exitCode -eq 0 -and $r.json) { @($r.json) } else { @() }
  }
  foreach ($entry in $Graph.caches[$cacheKey]) {
    $name = [string]$entry.name
    if (-not $name.StartsWith($Tool.fp12 + '-')) { continue }
    $created = [datetime]::MinValue
    $stamp = $name.Substring($Tool.fp12.Length + 1)
    if (-not [datetime]::TryParseExact($stamp, 'yyyyMMddHHmm', [Globalization.CultureInfo]::InvariantCulture, 'AssumeUniversal,AdjustToUniversal', [ref]$created)) {
      [datetime]::TryParse([string]$entry.createdTime, [ref]$created) | Out-Null
    }
    return [ordered]@{ tag = $name; createdUtc = $created; digest = [string]$entry.digest; imageRef = ('{0}/{1}:{2}' -f (Get-DhAcrLoginServer -Config $config), $repo, $name) }
  }
  return $null
}

function New-DhSmokeScript {
  param([System.Collections.IDictionary]$Case)
  return @"
#!/bin/sh
echo "DH_SMOKE_BEGIN:$($Case.name)"
$($Case.command)
rc=`$?
echo "DH_SMOKE_END:$($Case.name):`$rc"
exit 0
"@ -replace "`r`n", "`n"
}

function New-DhAcrTaskYaml {
  param([System.Collections.IDictionary]$Config, [string]$Repository, [string]$Tag, [string]$Fingerprint, [object[]]$SmokeCases, [switch]$SmokeOnly, [string]$DockerfilePath = 'Dockerfile')
  $timeout = [int]$Config.acrTimeoutSeconds
  $image = '$Registry/{0}:{1}' -f $Repository, $Tag
  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.Add('version: v1.1.0')
  $lines.Add("stepTimeout: $timeout")
  $lines.Add('steps:')
  if (-not $SmokeOnly) {
    $labels = @(
      ('{0}=true' -f $Config.testTag),
      ('dgt.fingerprint={0}' -f $Fingerprint),
      ('dgt.git-sha={0}' -f $(if ($script:Dh.GitSha) { $script:Dh.GitSha } else { 'unknown' })),
      ('dgt.run-id={0}' -f $script:Dh.RunId)
    ) | ForEach-Object { '--label ' + $_ }
    $lines.Add('  - id: build')
    $lines.Add(('    build: -t {0} {1} -f {2} .' -f $image, ($labels -join ' '), $DockerfilePath))
    $lines.Add("    timeout: $timeout")
    $lines.Add('  - id: push')
    $lines.Add('    push:')
    $lines.Add(('      - "{0}"' -f $image))
    $lines.Add('    timeout: 3600')
  }
  $index = 0
  foreach ($case in $SmokeCases) {
    $index++
    $lines.Add(('  - id: smoke-{0}' -f $index))
    $lines.Add(('    cmd: {0} /workspace/.dh/smoke-{1}.sh' -f $image, $index))
    $lines.Add('    entryPoint: sh')
    $lines.Add('    ignoreErrors: true')
    $lines.Add('    timeout: 900')
  }
  return ($lines -join "`n") + "`n"
}

function New-DhAcrContext {
  <#
  .SYNOPSIS Stages the ACR upload context: staged tool sources (build) plus generated .dh/ task files.
  #>
  param([System.Collections.IDictionary]$Node, [System.Collections.IDictionary]$Tool, [string]$TaskYaml, [object[]]$SmokeCases, [switch]$SmokeOnly)
  $dir = Join-Path $script:Dh.OutputDir ('acr/{0}/{1}/{2}' -f $Node.agent, $Node.tool, $Node.stage)
  if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
  if (-not $SmokeOnly) {
    $sourceDir = if ($Tool.buildContext -eq 'agent') { Split-Path -Parent (Split-Path -Parent $Tool.dir) } else { $Tool.dir }
    Copy-Item -Path (Join-Path $sourceDir '*') -Destination $dir -Recurse -Force
    $ignore = Join-Path $dir '.dockerignore'
    $existing = if (Test-Path -LiteralPath $ignore) { [System.IO.File]::ReadAllText($ignore) } else { '' }
    $separator = if ($existing -and -not $existing.EndsWith("`n")) { "`n" } else { '' }
    [System.IO.File]::WriteAllText($ignore, $existing + $separator + ".dh`n", [System.Text.UTF8Encoding]::new($false))
  }
  $dh = Join-Path $dir '.dh'
  New-Item -ItemType Directory -Path $dh -Force | Out-Null
  [System.IO.File]::WriteAllText((Join-Path $dh 'acr-task.yaml'), $TaskYaml, [System.Text.UTF8Encoding]::new($false))
  $index = 0
  foreach ($case in $SmokeCases) {
    $index++
    [System.IO.File]::WriteAllText((Join-Path $dh ("smoke-$index.sh")), (New-DhSmokeScript -Case $case), [System.Text.UTF8Encoding]::new($false))
  }
  return $dir
}

function Start-DhAcrRun {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node, [string]$ContextDir)
  $config = $Graph.config
  $arguments = @('acr', 'run', '--registry', $config.acrName, '--resource-group', $config.acrResourceGroup, '--subscription', $config.subscriptionId,
    '--file', '.dh/acr-task.yaml', '--timeout', [string]$config.acrTimeoutSeconds, '--no-wait', '--output', 'json')
  if ($config.acrAgentPool) { $arguments += @('--agent-pool', $config.acrAgentPool) }
  $arguments += $ContextDir
  $Node.job = Start-DhBackgroundCommand -Command 'az' -Arguments $arguments
  $Node.data['submitArgs'] = $arguments
  $Node.phase = 'submitting'
  Set-DhNodeWait -Node $Node -Seconds 3
}

function Get-DhAcrRunIdFromOutput {
  param([string]$Output)
  try {
    $start = $Output.IndexOf('{')
    if ($start -ge 0) {
      $json = ConvertFrom-DhJson $Output.Substring($start)
      if ($json -is [System.Collections.IDictionary] -and $json.Contains('runId') -and $json.runId) { return [string]$json.runId }
    }
  } catch { }
  if ($Output -match '(?i)Queued a run with ID:\s*([a-z0-9]+)') { return $Matches[1] }
  if ($Output -match '(?i)"runId"\s*:\s*"([a-z0-9]+)"') { return $Matches[1] }
  if ($Output -match '(?i)Run ID:\s*([a-z0-9]+)') { return $Matches[1] }
  return ''
}

function Step-DhAcrSubmission {
  <#
  .SYNOPSIS Advances 'submitting' -> 'polling'. Returns $false when the node was completed.
  #>
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node, [string]$FailCode)
  $result = Receive-DhBackgroundCommand -Job $Node.job
  if ($null -eq $result) { Set-DhNodeWait -Node $Node -Seconds 5; return $true }
  $Node.job = $null
  $runId = Get-DhAcrRunIdFromOutput -Output ([string]$result.output)
  if (-not $runId -and (Test-DhAuthExpiredText ([string]$result.output)) -and -not $Node.data.Contains('resubmitted') -and (Test-DhOidcAvailable)) {
    Update-DhAzLogin -Force | Out-Null
    $Node.data['resubmitted'] = $true
    $Node.job = Start-DhBackgroundCommand -Command 'az' -Arguments $Node.data.submitArgs
    Set-DhNodeWait -Node $Node -Seconds 3
    return $true
  }
  if (-not $runId) {
    Add-DhNodeEvidence -Node $Node -Name 'acr-submit.txt' -Content ([string]$result.output) | Out-Null
    Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure' -Code $FailCode
    return $false
  }
  $Node.data['acrRunId'] = $runId
  Register-DhOperation -Node $Node -Kind 'acr-run' -Id $runId -PollUrl (Get-DhAcrRunUrl -Config $Graph.config -RunId $runId) -CancelUrl (Get-DhAcrRunUrl -Config $Graph.config -RunId $runId -Suffix '/cancel') -Audience 'arm' | Out-Null
  $Node.phase = 'polling'
  Set-DhNodeWait -Node $Node -Seconds ([int]$Graph.config.pollSeconds)
  return $true
}

function Get-DhAcrRunLog {
  param([System.Collections.IDictionary]$Config, [string]$RunId)
  $response = Invoke-DhRest -Method POST -Uri (Get-DhAcrRunUrl -Config $Config -RunId $RunId -Suffix '/listLogSasUrl') -Audience arm
  if ($response.status -ne 200 -or -not ($response.body -is [System.Collections.IDictionary]) -or -not $response.body.logLink) { return '' }
  $log = Invoke-DhRest -Method GET -Uri ([string]$response.body.logLink) -Audience none -MaxAttempts 3
  if ($log.status -eq 200) { return [string]$log.raw }
  return ''
}

function Get-DhSmokeOutcomes {
  <#
  .SYNOPSIS Evaluates DH_SMOKE_BEGIN/END markers in ACR logs against case expectations.
  #>
  param([string]$Log, [object[]]$Cases)
  $outcomes = [System.Collections.Generic.List[object]]::new()
  foreach ($case in $Cases) {
    $name = [string]$case.name
    $pattern = 'DH_SMOKE_BEGIN:{0}\r?\n(?<out>.*?)DH_SMOKE_END:{0}:(?<rc>-?\d+)' -f [regex]::Escape($name)
    $m = [regex]::Match($Log, $pattern, 'Singleline')
    if (-not $m.Success) {
      $outcomes.Add([ordered]@{ name = $name; status = 'failed'; code = 'DH-SMK-002'; params = @{ name = $name } })
      continue
    }
    $rc = [int]$m.Groups['rc'].Value
    $out = $m.Groups['out'].Value
    $expectedExit = [int](Get-DhValue $case 'expect.exitCode' 0)
    if ($rc -ne $expectedExit) {
      $outcomes.Add([ordered]@{ name = $name; status = 'failed'; code = 'DH-SMK-001'; params = @{ name = $name; exit = $rc } })
      continue
    }
    $failedIndex = 0
    $index = 0
    foreach ($text in @(Get-DhValue $case 'expect.contains' @())) { $index++; if (-not $out.Contains([string]$text)) { $failedIndex = $index; break } }
    if (-not $failedIndex) {
      foreach ($regex in @(Get-DhValue $case 'expect.matches' @())) { $index++; if (-not [regex]::IsMatch($out, [string]$regex)) { $failedIndex = $index; break } }
    }
    if ($failedIndex) {
      $outcomes.Add([ordered]@{ name = $name; status = 'failed'; code = 'DH-SMK-003'; params = @{ name = $name; index = $failedIndex } })
      continue
    }
    $outcomes.Add([ordered]@{ name = $name; status = 'passed'; code = ''; params = @{} })
  }
  return $outcomes.ToArray()
}

function Get-DhBuildFailureCode {
  param([string]$Log)
  if ($Log -match '(?i)no space left on device') { return @{ code = 'DH-BLD-002'; category = 'infrastructure' } }
  if ($Log -match '(?i)(toomanyrequests|rate limit|503 Service Unavailable|i/o timeout|TLS handshake timeout)') { return @{ code = 'DH-BLD-001'; category = 'infrastructure' } }
  if ($Log -match '(?i)(failed to (resolve|pull)|pull access denied|manifest (for .* )?(unknown|not found))') { return @{ code = 'DH-BLD-006'; category = 'contribution' } }
  if ($Log -match '(?i)(curl: \(\d+\)|wget: .*(error|failed)|Could not fetch URL|HTTPError|ERROR: Could not find a version)') { return @{ code = 'DH-BLD-007'; category = 'contribution' } }
  if ($Log -match '(?i)step ID: push.*(failed|error)') { return @{ code = 'DH-BLD-005'; category = 'infrastructure' } }
  return @{ code = 'DH-BLD-001'; category = 'contribution' }
}

function Get-DhBaseImageDigests {
  param([string]$Log)
  $images = [System.Collections.Generic.List[object]]::new()
  $pattern = 'runtime-dependency:\s*\r?\n\s*registry:\s*(?<registry>\S+)\s*\r?\n\s*repository:\s*(?<repo>\S+)\s*\r?\n\s*tag:\s*(?<tag>\S+)\s*\r?\n\s*digest:\s*(?<digest>sha256:[0-9a-f]+)'
  foreach ($m in [regex]::Matches($Log, $pattern)) {
    $images.Add([ordered]@{ image = ('{0}/{1}:{2}' -f $m.Groups['registry'].Value, $m.Groups['repo'].Value, $m.Groups['tag'].Value); digest = $m.Groups['digest'].Value })
  }
  return $images.ToArray()
}

function Get-DhSmokeHash {
  param([object[]]$Cases)
  $basis = @($Cases | ForEach-Object { [ordered]@{ name = $_.name; command = $_.command; expect = $_.expect } })
  return (Get-DhSha256Hex (ConvertTo-DhJson $basis -Compress)).Substring(0, 16)
}

function Step-DhBuild {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $config = $Graph.config
  $ctx = $Graph.toolCtx['{0}/{1}' -f $Node.agent, $Node.tool]
  $tool = $ctx.tool
  $agent = $ctx.agent
  switch ($Node.phase) {
    'init' {
      $repo = Get-DhImageRepository -Config $config -Tool $tool
      $Node.data['fingerprint'] = $tool.fp12
      $existing = Find-DhImageForFingerprint -Graph $Graph -Tool $tool
      $maxAge = [int](Get-DhValue $config 'rebuild.maxImageAgeDays' 30)
      if ($existing -and [string](Get-DhValue $config 'rebuild.mode' 'changed') -eq 'changed') {
        $age = [math]::Floor(((Get-DhUtcNow) - $existing.createdUtc).TotalDays)
        if ($existing.createdUtc -ne [datetime]::MinValue -and $age -le $maxAge) {
          $ctx.imageRef = $existing.imageRef; $ctx.imageTag = $existing.tag; $ctx.digest = $existing.digest
          $ledger = Get-DhLedgerEntry -Key ('images/{0}/{1}' -f $repo, $existing.tag)
          $smokeHash = Get-DhSmokeHash -Cases @(Get-DhSmokeCases -Agent $agent -Tool $tool)
          if ($ledger -and $ledger.Contains('smoke') -and $ledger.smoke -and [string]$ledger['smokeHash'] -eq $smokeHash) { $ctx.smokeResults = @($ledger.smoke); $ctx.smokeSource = 'ledger' }
          $Node.data['imageTag'] = $existing.tag; $Node.data['digest'] = $existing.digest
          Complete-DhNode -Graph $Graph -Node $Node -Status 'cached' -Code 'DH-BLD-008' -Params @{ tag = $existing.tag; age = $age }
          return
        }
      }
      if (-not (Request-DhBudget -Graph $Graph -Name 'maxAcrBuilds')) {
        Complete-DhNode -Graph $Graph -Node $Node -Status 'skipped' -Category 'policy' -Code 'DH-DEP-002' -Params @{ class = 'ACR builds' }
        return
      }
      $tag = '{0}-{1}' -f $tool.fp12, (Get-DhUtcNow).ToString('yyyyMMddHHmm')
      $cases = @(Get-DhSmokeCases -Agent $agent -Tool $tool)
      $dockerfile = if ($tool.buildContext -eq 'agent') { 'tools/{0}/Dockerfile' -f $tool.name } else { 'Dockerfile' }
      $yaml = New-DhAcrTaskYaml -Config $config -Repository $repo -Tag $tag -Fingerprint $tool.fingerprint -SmokeCases $cases -DockerfilePath $dockerfile
      $dir = New-DhAcrContext -Node $Node -Tool $tool -TaskYaml $yaml -SmokeCases $cases
      $Node.data['imageTag'] = $tag
      $Node.data['repository'] = $repo
      $Node.data['smokeCases'] = $cases
      Add-DhNodeEvidence -Node $Node -Name 'acr-task.yaml' -Content $yaml | Out-Null
      Start-DhAcrRun -Graph $Graph -Node $Node -ContextDir $dir
    }
    'submitting' { Step-DhAcrSubmission -Graph $Graph -Node $Node -FailCode 'DH-BLD-004' | Out-Null }
    'polling' {
      $runId = [string]$Node.data.acrRunId
      $response = Invoke-DhRest -Method GET -Uri (Get-DhAcrRunUrl -Config $config -RunId $runId) -Audience arm
      $status = [string](Get-DhValue $response.body 'properties.status' '')
      if ($status -notin $script:DhAcrTerminal) {
        if ((Get-DhNodeElapsedMinutes -Node $Node) -gt [int](Get-DhValue $config 'timeouts.buildMinutes' 120)) {
          Stop-DhNode -Graph $Graph -Node $Node
          Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-BLD-003' -Params @{ minutes = (Get-DhValue $config 'timeouts.buildMinutes' 120) }
          return
        }
        Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
        return
      }
      $log = Get-DhAcrRunLog -Config $config -RunId $runId
      Add-DhNodeEvidence -Node $Node -Name 'acr-run.log' -Content $log | Out-Null
      Add-DhNodeEvidence -Node $Node -Name 'acr-run.json' -Content $response.body | Out-Null
      if ($status -ne 'Succeeded') {
        $failure = Get-DhBuildFailureCode -Log $log
        if ($status -in @('Timeout')) { $failure = @{ code = 'DH-BLD-003'; category = 'infrastructure' } }
        $resultStatus = if ($failure.category -eq 'infrastructure') { 'inconclusive' } else { 'failed' }
        Add-DhNodeMessage -Node $Node -Level error -Code 'DH-BLD-010' -Params @{ status = $status }
        Complete-DhNode -Graph $Graph -Node $Node -Status $resultStatus -Category $failure.category -Code $failure.code -Params @{ minutes = (Get-DhValue $config 'timeouts.buildMinutes' 120) }
        return
      }
      $repo = [string]$Node.data.repository
      $tag = [string]$Node.data.imageTag
      $digest = ''
      foreach ($image in @(Get-DhValue $response.body 'properties.outputImages' @())) { if ($image.tag -eq $tag -and $image.digest) { $digest = [string]$image.digest } }
      $smoke = $null
      $smokeHash = ''
      if ($log) {
        $smoke = @(Get-DhSmokeOutcomes -Log $log -Cases $Node.data.smokeCases)
        $smokeHash = Get-DhSmokeHash -Cases $Node.data.smokeCases
      }
      $baseImages = @(Get-DhBaseImageDigests -Log $log)
      $ctx.imageRef = '{0}/{1}:{2}' -f (Get-DhAcrLoginServer -Config $config), $repo, $tag
      $ctx.imageTag = $tag; $ctx.digest = $digest; $ctx.smokeResults = $smoke; $ctx.smokeSource = 'build'
      $Node.data['digest'] = $digest; $Node.data['baseImages'] = $baseImages
      Set-DhLedgerEntry -Key ('images/{0}/{1}' -f $repo, $tag) -Value ([ordered]@{
          repository = $repo; tag = $tag; digest = $digest; fingerprint = $tool.fingerprint; agent = $agent.name; tool = $tool.name
          builtAt = (ConvertTo-DhIso (Get-DhUtcNow)); runId = $script:Dh.RunId; gitSha = $script:Dh.GitSha; acrRunId = $runId; baseImages = $baseImages; smoke = $smoke; smokeHash = $smokeHash
        })
      Complete-DhNode -Graph $Graph -Node $Node -Status 'passed' -Code 'DH-BLD-009' -Params @{ tag = $tag }
    }
  }
}

function Complete-DhSmokeFromOutcomes {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node, [object[]]$Outcomes, [string]$Source)
  $failed = @($Outcomes | Where-Object { $_.status -ne 'passed' })
  foreach ($outcome in $failed) { Add-DhNodeMessage -Node $Node -Level error -Code $outcome.code -Params $outcome.params }
  $Node.data['cases'] = @($Outcomes | ForEach-Object { [ordered]@{ name = $_.name; status = $_.status } })
  if ($Source -eq 'ledger') { Add-DhNodeMessage -Node $Node -Level info -Code 'DH-SMK-004' -Params @{ tag = $Node.data.imageTag } }
  if ($failed.Count -gt 0) {
    Complete-DhNode -Graph $Graph -Node $Node -Status 'failed' -Category 'contribution'
  } else {
    Complete-DhNode -Graph $Graph -Node $Node -Status $(if ($Source -eq 'ledger') { 'cached' } else { 'passed' }) -Code 'DH-SMK-005' -Params @{ count = @($Outcomes).Count }
  }
}

function Step-DhImageSmoke {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $config = $Graph.config
  $ctx = $Graph.toolCtx['{0}/{1}' -f $Node.agent, $Node.tool]
  $tool = $ctx.tool
  switch ($Node.phase) {
    'init' {
      if ($ctx.smokeResults) {
        $Node.data['imageTag'] = $ctx.imageTag
        Complete-DhSmokeFromOutcomes -Graph $Graph -Node $Node -Outcomes @($ctx.smokeResults) -Source $ctx.smokeSource
        return
      }
      if (-not $ctx.imageRef) {
        $existing = Find-DhImageForFingerprint -Graph $Graph -Tool $tool
        if (-not $existing) { Complete-DhNode -Graph $Graph -Node $Node -Status 'blocked' -Category 'policy' -Code 'DH-REG-005'; return }
        $ctx.imageRef = $existing.imageRef; $ctx.imageTag = $existing.tag; $ctx.digest = $existing.digest
      }
      if (-not (Request-DhBudget -Graph $Graph -Name 'maxAcrBuilds')) {
        Complete-DhNode -Graph $Graph -Node $Node -Status 'skipped' -Category 'policy' -Code 'DH-DEP-002' -Params @{ class = 'ACR runs' }
        return
      }
      $repo = Get-DhImageRepository -Config $config -Tool $tool
      $cases = @(Get-DhSmokeCases -Agent $ctx.agent -Tool $tool)
      $yaml = New-DhAcrTaskYaml -Config $config -Repository $repo -Tag $ctx.imageTag -Fingerprint $tool.fingerprint -SmokeCases $cases -SmokeOnly
      $dir = New-DhAcrContext -Node $Node -Tool $tool -TaskYaml $yaml -SmokeCases $cases -SmokeOnly
      $Node.data['imageTag'] = $ctx.imageTag
      $Node.data['smokeCases'] = $cases
      Start-DhAcrRun -Graph $Graph -Node $Node -ContextDir $dir
    }
    'submitting' { Step-DhAcrSubmission -Graph $Graph -Node $Node -FailCode 'DH-BLD-004' | Out-Null }
    'polling' {
      $runId = [string]$Node.data.acrRunId
      $response = Invoke-DhRest -Method GET -Uri (Get-DhAcrRunUrl -Config $config -RunId $runId) -Audience arm
      $status = [string](Get-DhValue $response.body 'properties.status' '')
      if ($status -notin $script:DhAcrTerminal) {
        if ((Get-DhNodeElapsedMinutes -Node $Node) -gt 60) {
          Stop-DhNode -Graph $Graph -Node $Node
          Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-BLD-003' -Params @{ minutes = 60 }
          return
        }
        Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
        return
      }
      $log = Get-DhAcrRunLog -Config $config -RunId $runId
      if (-not $log) {
        Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-SMK-006'
        return
      }
      Add-DhNodeEvidence -Node $Node -Name 'acr-smoke.log' -Content $log | Out-Null
      $outcomes = @(Get-DhSmokeOutcomes -Log $log -Cases $Node.data.smokeCases)
      Complete-DhSmokeFromOutcomes -Graph $Graph -Node $Node -Outcomes $outcomes -Source 'smoke-run'
    }
  }
}
