# Stage: tool-run - direct, deterministic execution through the Discovery tools data plane
# (POST {workspace}/tools/projects/{project}:run, the contract used by utilities/supercomputer-cli).

$script:DhRunQueued = @('NotStarted', 'Pending', 'TaskAccepted', 'Accepted', 'Queued', 'Submitted')
$script:DhRunTerminal = @('Succeeded', 'Failed', 'Canceled', 'Cancelled')

function Select-DhNodePool {
  <#
  .SYNOPSIS First configured nodepool whose SKUs intersect the tool (or spec) SKUs; GPU tools need GPU pools.
  #>
  param([System.Collections.IDictionary]$Config, [System.Collections.IDictionary]$Agent, [System.Collections.IDictionary]$Tool)
  $wanted = @($Tool.skus)
  $specSkus = Get-DhValue $Agent.spec 'requires.skus' 'auto'
  if ($specSkus -is [array]) { $wanted = @($specSkus) }
  $wantedLower = @($wanted | ForEach-Object { ([string]$_).ToLowerInvariant() })
  $candidates = @(@($Config.nodePools) | Where-Object {
      $pool = $_
      $poolSkus = @(@($pool.skus) | ForEach-Object { ([string]$_).ToLowerInvariant() })
      (@($poolSkus | Where-Object { $_ -in $wantedLower }).Count -gt 0) -and (-not $Tool.gpu -or [bool](Get-DhValue $pool 'gpu' $false))
    })
  if ($candidates.Count -eq 0) { return $null }
  $preferred = @($candidates | Where-Object { [bool](Get-DhValue $_ 'gpu' $false) -eq [bool]$Tool.gpu })
  $pool = if ($preferred.Count -gt 0) { $preferred[0] } else { $candidates[0] }
  $sku = @(@($pool.skus) | Where-Object { ([string]$_).ToLowerInvariant() -in $wantedLower })[0]
  return @{ id = [string]$pool.id; sku = [string]$sku }
}

function Get-DhToolRunBase {
  param([System.Collections.IDictionary]$Config)
  return ('{0}/tools/projects/{1}' -f $Config.workspaceEndpoint, [Uri]::EscapeDataString([string]$Config.project))
}

function Test-DhValidationReceipt {
  <#
  .SYNOPSIS Port of the deployer's verify_receipt. Returns '' when valid, else the failure reason.
  #>
  param([string]$Text, [switch]$RequireOutputPrefix)
  $found = [regex]::Matches([string]$Text, '(?m)^DISCOVERY_VALIDATION_RESULT=(.+?)\s*$')
  if ($found.Count -eq 0) { return 'missing runtime validation receipt' }
  try { $receipt = ConvertFrom-DhJson $found[$found.Count - 1].Groups[1].Value } catch { return 'receipt is not valid JSON' }
  if (-not ($receipt -is [System.Collections.IDictionary])) { return 'receipt is not an object' }
  $checks = $receipt['checks']; $artifacts = $receipt['artifacts']
  if (-not ($checks -is [array]) -or $checks.Count -eq 0) { return 'receipt must contain measured checks' }
  foreach ($check in $checks) {
    if (-not ($check -is [System.Collections.IDictionary]) -or -not $check['name'] -or -not $check.Contains('actual') -or -not $check.Contains('expected')) { return 'malformed validation check' }
    $actual = $check['actual']; $expected = $check['expected']
    $isNum = { param($v) ($v -is [int] -or $v -is [long] -or $v -is [double] -or $v -is [decimal]) -and -not ($v -is [bool]) }
    if ((& $isNum $actual) -and (& $isNum $expected)) {
      $tolerance = if ($check.Contains('tolerance')) { $check['tolerance'] } else { 0 }
      if (-not (& $isNum $tolerance)) { return ('numerical validation failed: {0}' -f $check['name']) }
      foreach ($v in @([double]$actual, [double]$expected, [double]$tolerance)) { if ([double]::IsNaN($v) -or [double]::IsInfinity($v)) { return ('numerical validation failed: {0}' -f $check['name']) } }
      if ([double]$tolerance -lt 0 -or [math]::Abs([double]$actual - [double]$expected) -gt [double]$tolerance) { return ('numerical validation failed: {0}' -f $check['name']) }
    } elseif (-not (($actual -is [string] -or $actual -is [bool]) -and $actual.GetType() -eq $expected.GetType() -and $actual -eq $expected)) {
      return ('validation failed: {0}' -f $check['name'])
    }
  }
  if (-not ($artifacts -is [array]) -or $artifacts.Count -eq 0) { return 'receipt must contain verified artifacts' }
  foreach ($artifact in $artifacts) {
    if (-not ($artifact -is [System.Collections.IDictionary])) { return 'malformed artifact' }
    $path = $artifact['path']; $size = $artifact['bytes']
    $badPath = -not ($path -is [string]) -or -not $path.StartsWith('/') -or (@($path -split '/') -contains '..')
    if ($RequireOutputPrefix -and -not $badPath) { $badPath = -not $path.StartsWith('/output/') }
    if ($badPath -or -not ($size -is [int] -or $size -is [long]) -or $size -le 0) { return 'artifact must have an output path and measured nonzero size' }
  }
  return ''
}

function Test-DhOutputExpectations {
  <#
  .SYNOPSIS Returns @{ ok; code; params } for contains/matches/receipt expectations over output text.
  #>
  param([string]$Text, [System.Collections.IDictionary]$Expect, [string]$Case, [switch]$RequireOutputPrefix, [string]$ContainsCode = 'DH-RUN-002', [string]$ReceiptCode = 'DH-RUN-003')
  $index = 0
  foreach ($needle in @(Get-DhValue $Expect 'contains' @())) {
    $index++
    if (-not ([string]$Text).Contains([string]$needle)) { return @{ ok = $false; code = $ContainsCode; params = @{ case = $Case; index = $index } } }
  }
  foreach ($regex in @(Get-DhValue $Expect 'matches' @())) {
    $index++
    if (-not [regex]::IsMatch([string]$Text, [string]$regex)) { return @{ ok = $false; code = $ContainsCode; params = @{ case = $Case; index = $index } } }
  }
  if ([bool](Get-DhValue $Expect 'receipt' $false)) {
    $reason = Test-DhValidationReceipt -Text $Text -RequireOutputPrefix:$RequireOutputPrefix
    if ($reason) { return @{ ok = $false; code = $ReceiptCode; params = @{ case = $Case; reason = $reason } } }
  }
  return @{ ok = $true }
}

function New-DhToolRunPayload {
  param([System.Collections.IDictionary]$Config, [string]$ToolResourceId, [string]$NodePoolId, [System.Collections.IDictionary]$Case)
  $inline = @(@($Case.inlineFiles) | Where-Object { $_ } | ForEach-Object {
      [ordered]@{ mountPath = [string]$_.mountPath; encodedFile = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes(((([string]$_.content) -replace "`r`n", "`n")))) }
    })
  $payload = [ordered]@{ toolId = $ToolResourceId; command = [string]$Case.command; inlineFiles = $inline; inputData = @(); outputData = @(); nodePoolIds = @($NodePoolId) }
  if ($Config.outputStorageContainerId) {
    $payload.outputData = @([ordered]@{ mountPath = '/dh/output'; storageUri = ('discovery://storageassets{0}/storageassets/{1}' -f $Config.outputStorageContainerId, $Config.testTag) })
  }
  return $payload
}

function Step-DhToolRun {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $config = $Graph.config
  $ctx = $Graph.toolCtx['{0}/{1}' -f $Node.agent, $Node.tool]
  $tool = $ctx.tool
  $base = Get-DhToolRunBase -Config $config
  switch ($Node.phase) {
    'init' {
      if (-not $ctx.toolResourceId) { $ctx.toolResourceId = Find-DhRegisteredTool -Graph $Graph -Tool $tool }
      if (-not $ctx.toolResourceId) { Complete-DhNode -Graph $Graph -Node $Node -Status 'blocked' -Category 'policy' -Code 'DH-RUN-009'; return }
      $outputDir = if ($config.outputStorageContainerId) { '/dh/output' } else { '/tmp/dh/output' }
      $plan = Get-DhToolRunCases -Agent $ctx.agent -Tool $tool -OutputDir $outputDir
      if ($plan.untestedCode) { Complete-DhNode -Graph $Graph -Node $Node -Status 'untested' -Code $plan.untestedCode; return }
      $pool = Select-DhNodePool -Config $config -Agent $ctx.agent -Tool $tool
      if (-not $pool) { Complete-DhNode -Graph $Graph -Node $Node -Status 'untested' -Code 'DH-RUN-006'; return }
      if (-not (Request-DhBudget -Graph $Graph -Name 'maxToolRuns') -or ($tool.gpu -and -not (Request-DhBudget -Graph $Graph -Name 'maxGpuToolRuns'))) {
        Complete-DhNode -Graph $Graph -Node $Node -Status 'skipped' -Category 'policy' -Code 'DH-DEP-002' -Params @{ class = $(if ($tool.gpu) { 'GPU tool runs' } else { 'tool runs' }) }
        return
      }
      $Node.data['nodepoolSku'] = $pool.sku
      $Node.data['pool'] = $pool.id
      $Node.data['planCases'] = @($plan.cases)
      $Node.data['caseIndex'] = 0
      $Node.data['caseResults'] = [System.Collections.Generic.List[object]]::new()
      $Node.data['specSource'] = [string]@($plan.cases)[0].source
      $Node.phase = 'submit'
      Set-DhNodeWait -Node $Node -Seconds 0.5
    }
    'submit' {
      $cases = @($Node.data.planCases)
      $index = [int]$Node.data.caseIndex
      if ($index -ge $cases.Count) { $Node.phase = 'finish'; Set-DhNodeWait -Node $Node -Seconds 0.5; return }
      $case = $cases[$index]
      if ($case.Contains('error')) {
        $Node.data.caseResults.Add([ordered]@{ name = $case.name; status = 'failed'; category = 'contribution'; code = $case.error; params = @{ case = $case.name; action = $case.action } })
        $Node.data.caseIndex = $index + 1
        return
      }
      $payload = New-DhToolRunPayload -Config $config -ToolResourceId $ctx.toolResourceId -NodePoolId $Node.data.pool -Case $case
      Add-DhNodeEvidence -Node $Node -Name ("run-$($case.name)-request.json") -Content $payload | Out-Null
      $response = Invoke-DhRest -Method POST -Uri ('{0}:run?api-version={1}' -f $base, $config.apiVersion) -Audience discovery -Body $payload
      if ($response.status -notin @(200, 201, 202) -or -not (Get-DhValue $response.body 'id' '')) {
        Add-DhNodeEvidence -Node $Node -Name ("run-$($case.name)-submit.txt") -Content ([string]$response.raw) | Out-Null
        $category = Get-DhFailureCategory -Status $response.status -Text ([string]$response.raw)
        $Node.data.caseResults.Add([ordered]@{ name = $case.name; status = $(if ($category -eq 'infrastructure') { 'inconclusive' } else { 'failed' }); category = $category; code = 'DH-RUN-008'; params = @{ status = $response.status } })
        $Node.data.caseIndex = $index + 1
        return
      }
      $operationId = [string]$response.body.id
      $op = Register-DhOperation -Node $Node -Kind 'tool-run' -Id $operationId -PollUrl ('{0}/operations/{1}?api-version={2}' -f $base, $operationId, $config.apiVersion) -CancelUrl ('{0}/operations/{1}:cancel?api-version={2}' -f $base, $operationId, $config.apiVersion) -Audience 'discovery'
      $Node.data['currentOp'] = $op
      $Node.data['caseSubmittedAt'] = Get-DhUtcNow
      $Node.data.Remove('caseRunningAt')
      $Node.phase = 'poll'
      Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
    }
    'poll' {
      $cases = @($Node.data.planCases)
      $case = $cases[[int]$Node.data.caseIndex]
      $op = $Node.data.currentOp
      $response = Invoke-DhRest -Method GET -Uri $op.pollUrl -Audience discovery
      $status = [string](Get-DhValue $response.body 'result.status' (Get-DhValue $response.body 'status' ''))
      $queueLimit = [int](Get-DhValue $config 'timeouts.toolRunQueueMinutes' 45)
      $runLimit = if ([int]$case.timeoutMinutes -gt 0) { [int]$case.timeoutMinutes } else { [int](Get-DhValue $config 'timeouts.toolRunMinutes' 30) }
      $outcome = $null
      if ($status -in $script:DhRunQueued -or -not $status) {
        if ((Get-DhNodeElapsedMinutes -Node $Node -Key 'caseSubmittedAt') -gt $queueLimit) {
          Stop-DhOperation -Operation $op
          $outcome = [ordered]@{ name = $case.name; status = 'inconclusive'; category = 'infrastructure'; code = 'DH-RUN-004'; params = @{ case = $case.name; minutes = $queueLimit } }
        }
      } elseif ($status -notin $script:DhRunTerminal) {
        if (-not $Node.data.Contains('caseRunningAt')) { $Node.data['caseRunningAt'] = Get-DhUtcNow }
        if ((Get-DhNodeElapsedMinutes -Node $Node -Key 'caseRunningAt') -gt $runLimit) {
          Stop-DhOperation -Operation $op
          $outcome = [ordered]@{ name = $case.name; status = 'failed'; category = 'contribution'; code = 'DH-RUN-005'; params = @{ case = $case.name; minutes = $runLimit } }
        }
      } else {
        Complete-DhOperation -Operation $op -Status $status
        Add-DhNodeEvidence -Node $Node -Name ("run-$($case.name)-response.json") -Content $response.body | Out-Null
        $logs = [string](Get-DhValue $response.body 'result.toolReport.logs' '')
        Add-DhNodeEvidence -Node $Node -Name ("run-$($case.name)-logs.txt") -Content $logs | Out-Null
        $expectedStatus = [string](Get-DhValue $case 'expect.status' 'Succeeded')
        $exitMatches = [regex]::Matches($logs, 'DH_RUN_EXIT:(-?\d+)')
        $exitCode = if ($exitMatches.Count -gt 0) { [int]$exitMatches[$exitMatches.Count - 1].Groups[1].Value } else { $null }
        $expectedExit = [int](Get-DhValue $case 'expect.exitCode' 0)
        if ($status -ne $expectedStatus -or ($null -ne $exitCode -and $exitCode -ne $expectedExit)) {
          $errorText = '{0} {1}' -f (ConvertTo-DhJson (Get-DhValue $response.body 'error' '') -Compress), (Get-DhValue $response.body 'result.runtimeDetails' '')
          $category = if ($status -eq 'Failed' -and (Get-DhFailureCategory -Text $errorText) -eq 'infrastructure' -and $null -eq $exitCode) { 'infrastructure' } else { 'contribution' }
          $outcome = [ordered]@{ name = $case.name; status = $(if ($category -eq 'infrastructure') { 'inconclusive' } else { 'failed' }); category = $category; code = 'DH-RUN-001'; params = @{ case = $case.name; status = $(if ($null -ne $exitCode) { "$status (exit $exitCode)" } else { $status }) } }
        } else {
          $check = Test-DhOutputExpectations -Text $logs -Expect $case.expect -Case $case.name
          $outcome = if ($check.ok) { [ordered]@{ name = $case.name; status = 'passed'; category = ''; code = ''; params = @{} } } else { [ordered]@{ name = $case.name; status = 'failed'; category = 'contribution'; code = $check.code; params = $check.params } }
        }
      }
      if ($outcome) {
        $Node.data.caseResults.Add($outcome)
        $Node.data.caseIndex = [int]$Node.data.caseIndex + 1
        $Node.phase = 'submit'
        Set-DhNodeWait -Node $Node -Seconds 0.5
        return
      }
      Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
    }
    'finish' {
      $results = @($Node.data.caseResults)
      $Node.data['cases'] = @($results | ForEach-Object { [ordered]@{ name = $_.name; status = $_.status } })
      foreach ($r in @($results | Where-Object { $_.status -ne 'passed' })) { Add-DhNodeMessage -Node $Node -Level $(if ($r.status -eq 'failed') { 'error' } else { 'warning' }) -Code $r.code -Params $r.params }
      $failed = @($results | Where-Object { $_.status -eq 'failed' })
      $inconclusive = @($results | Where-Object { $_.status -eq 'inconclusive' })
      if ($failed.Count -gt 0) { Complete-DhNode -Graph $Graph -Node $Node -Status 'failed' -Category $(if (@($failed | Where-Object { $_.category -eq 'contribution' }).Count) { 'contribution' } else { 'infrastructure' }); return }
      if ($inconclusive.Count -gt 0) { Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure'; return }
      Complete-DhNode -Graph $Graph -Node $Node -Status 'passed' -Code 'DH-RUN-010' -Params @{ count = $results.Count }
    }
  }
}
