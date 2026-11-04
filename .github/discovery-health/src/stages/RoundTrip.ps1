# Stage: round-trip. Deterministic prompt -> deployed agent -> tool calls, graded programmatically
# (port of the deployer's assess_response, extended to require every expected bound tool).

$script:DhResponseTerminal = @('completed', 'failed', 'cancelled', 'canceled', 'expired', 'incomplete')
$script:DhToolFailurePattern = 'Tool execution failed|ToolRunError|ContainerExitCode|"error"\s*:\s*(?:\{|"[^" ]+)'
$script:DhToolSuccessPattern = 'Tool execution succeeded|Tool has completed successfully|"status"\s*:\s*"(?:succeeded|completed)"'
$script:DhConfirmationPattern = '(?:please (?:confirm|approve)|confirm.{0,80}proceed|would you like|approval required)'

function Test-DhGaApi {
  param([string]$ApiVersion)
  return ([string]::CompareOrdinal($ApiVersion, '2026-06-01') -ge 0)
}

function Get-DhResponseUrl {
  param([System.Collections.IDictionary]$Config, [string]$Conversation, [string]$ResponseId = '', [string]$Suffix = '')
  $ga = Test-DhGaApi $Config.apiVersion
  $route = if ($ga) { 'openai/v1/responses' } else { 'openai/responses' }
  $url = '{0}/conversations/{1}/{2}' -f $Config.workspaceEndpoint, [Uri]::EscapeDataString($Conversation), $route
  if ($ResponseId) { $url += '/' + [Uri]::EscapeDataString($ResponseId) }
  if ($Suffix) { $url += $Suffix }
  if ($ga) { return $url }
  return ('{0}?api-version={1}' -f $url, $Config.apiVersion)
}

function Get-DhResponseText {
  param([System.Collections.IDictionary]$Body)
  $parts = foreach ($item in @(Get-DhValue $Body 'output' @())) {
    if ($item -is [System.Collections.IDictionary] -and $item.type -eq 'message') {
      foreach ($content in @(Get-DhValue $item 'content' @())) { if ($content -is [System.Collections.IDictionary] -and $content.text -is [string]) { $content.text } }
    }
  }
  return ((@($parts) -join "`n").Trim())
}

function Test-DhApprovalPending {
  param([System.Collections.IDictionary]$Body)
  $outputs = @(Get-DhValue $Body 'output' @())
  $answered = @($outputs | Where-Object { $_ -is [System.Collections.IDictionary] -and $_.type -eq 'function_call_output' } | ForEach-Object { $_.call_id })
  foreach ($confirmation in @(Get-DhValue $Body 'discoveryProperties.confirmations' @())) { if ($confirmation.status -eq 'AwaitingUserInput') { return $true } }
  if (Get-DhValue $Body 'required_action' $null) { return $true }
  if ([string](Get-DhValue $Body 'status' '') -eq 'requires_action') { return $true }
  foreach ($o in $outputs) {
    if (-not ($o -is [System.Collections.IDictionary])) { continue }
    if ($o.type -in @('mcp_approval_request', 'tool_approval_request')) { return $true }
    if ($o.type -eq 'function_call' -and $o.name -eq 'GetUserInput' -and $o.call_id -notin $answered) { return $true }
  }
  return $false
}

function Get-DhToolExecutions {
  <#
  .SYNOPSIS function_call_output items correlated to a deployed tool (function names '<tool>-<operation>').
  #>
  param([System.Collections.IDictionary]$Body, [string[]]$Prefixes)
  $outputs = @(Get-DhValue $Body 'output' @())
  $calls = @{}
  foreach ($o in $outputs) { if ($o -is [System.Collections.IDictionary] -and $o.type -eq 'function_call' -and $o.call_id) { $calls[[string]$o.call_id] = $o } }
  $found = foreach ($o in $outputs) {
    if (-not ($o -is [System.Collections.IDictionary]) -or $o.type -ne 'function_call_output') { continue }
    $call = $calls[[string]$o.call_id]
    if (-not $call) { continue }
    $name = ([string]$call.name).ToLowerInvariant()
    foreach ($prefix in $Prefixes) { if ($prefix -and $name.StartsWith($prefix.ToLowerInvariant() + '-')) { $o; break } }
  }
  return @($found)
}

function Get-DhRoundTripVerdict {
  <#
  .SYNOPSIS Programmatic verdict: @{ status; category; code; params; toolsCalled }.
  #>
  param([System.Collections.IDictionary]$Body, [System.Collections.IDictionary]$Plan, [hashtable]$ToolPrefixes)
  $text = Get-DhResponseText -Body $Body
  if (Test-DhApprovalPending -Body $Body) { return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-003'; params = @{}; toolsCalled = @() } }
  $status = [string](Get-DhValue $Body 'status' '')
  if ($status -ne 'completed') {
    $errorText = ConvertTo-DhJson (Get-DhValue $Body 'error' '') -Compress
    return @{ status = 'failed'; category = (Get-DhFailureCategory -Text $errorText); code = 'DH-RTP-001'; params = @{ reason = "response ended with status $status" }; toolsCalled = @() }
  }
  $called = [System.Collections.Generic.List[string]]::new()
  $toolOutputs = [System.Collections.Generic.List[string]]::new()
  foreach ($tool in $Plan.toolsCalled) {
    $executions = @(Get-DhToolExecutions -Body $Body -Prefixes $ToolPrefixes[$tool])
    if ($executions.Count -eq 0) {
      if (@(Get-DhToolExecutions -Body $Body -Prefixes @($ToolPrefixes.Values | ForEach-Object { $_ })).Count -eq 0 -and [regex]::IsMatch($text, $script:DhConfirmationPattern, 'IgnoreCase,Singleline')) {
        return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-003'; params = @{}; toolsCalled = $called.ToArray() }
      }
      return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-002'; params = @{ tool = $tool }; toolsCalled = $called.ToArray() }
    }
    $last = $executions[-1].output
    $output = if ($last -is [string]) { $last } else { ConvertTo-DhJson $last -Compress }
    if ([regex]::IsMatch($output, $script:DhToolFailurePattern, 'IgnoreCase')) { return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-001'; params = @{ reason = "tool $tool reported an execution error" }; toolsCalled = $called.ToArray() } }
    if (-not [regex]::IsMatch($output, $script:DhToolSuccessPattern, 'IgnoreCase')) { return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-001'; params = @{ reason = "tool $tool did not report successful execution" }; toolsCalled = $called.ToArray() } }
    if ($Plan.receipt) {
      $reason = Test-DhValidationReceipt -Text $output -RequireOutputPrefix
      if ($reason) { return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-001'; params = @{ reason = $reason }; toolsCalled = $called.ToArray() } }
      if (-not [regex]::IsMatch($output, 'discovery://\S+')) { return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-001'; params = @{ reason = 'no output resource was reported by the tool' }; toolsCalled = $called.ToArray() } }
    }
    $called.Add($tool)
    $toolOutputs.Add($output)
  }
  $combined = (@($text) + $toolOutputs.ToArray()) -join "`n"
  $check = Test-DhOutputExpectations -Text $combined -Expect ([ordered]@{ contains = $Plan.contains; matches = $Plan.matches }) -Case 'round-trip' -ContainsCode 'DH-RTP-009'
  if (-not $check.ok) { return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-009'; params = $check.params; toolsCalled = $called.ToArray() } }
  if ($Plan.toolLess) {
    if (-not $text -or [regex]::IsMatch($text, '\b(?:blocked|failed|error|exception)\b', 'IgnoreCase')) {
      return @{ status = 'failed'; category = 'contribution'; code = 'DH-RTP-001'; params = @{ reason = 'agent response was empty or reported failure' }; toolsCalled = @() }
    }
    return @{ status = 'passed'; category = ''; code = 'DH-RTP-006'; params = @{}; toolsCalled = @() }
  }
  return @{ status = 'passed'; category = ''; code = 'DH-RTP-005'; params = @{ tools = ($called -join ', ') }; toolsCalled = $called.ToArray() }
}

function New-DhInvestigationName {
  <#
  .SYNOPSIS 'dgt-<6 chars>-<hash of full agent name><time><random>' (<= 24 chars), unique across agents sharing a prefix.
  #>
  param([string]$AgentName)
  $safe = (ConvertTo-DhSafeName $AgentName 6)
  if (-not $safe) { $safe = 'agent' }
  $hash = (Get-DhSha256Hex $AgentName).Substring(0, 4)
  $stamp = [Convert]::ToString([long][DateTimeOffset]::UtcNow.ToUnixTimeSeconds(), 16)
  $random = '{0:x}' -f (Get-Random -Maximum 16)
  $name = ('dgt-{0}-{1}{2}{3}' -f $safe, $hash, $stamp, $random)
  return $name.Substring(0, [math]::Min(24, $name.Length))
}

function Remove-DhInvestigation {
  param([System.Collections.IDictionary]$Config, [string]$Name)
  $url = '{0}/projects/{1}/investigations/{2}?api-version={3}' -f $Config.workspaceEndpoint, [Uri]::EscapeDataString([string]$Config.project), [Uri]::EscapeDataString($Name), $Config.apiVersion
  return (Invoke-DhRest -Method DELETE -Uri $url -Audience discovery -MaxAttempts 2)
}

function Start-DhRoundTripAttempt {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $config = $Graph.config
  $project = [string]$config.project
  $inv = New-DhInvestigationName -AgentName $Node.agent
  $invUrl = '{0}/projects/{1}/investigations/{2}?api-version={3}' -f $config.workspaceEndpoint, [Uri]::EscapeDataString($project), [Uri]::EscapeDataString($inv), $config.apiVersion
  $create = Invoke-DhRest -Method PUT -Uri $invUrl -Audience discovery -Body ([ordered]@{ description = ('Automated health test [{0}]' -f $config.testTag); displayName = ('{0} {1}' -f $config.testTag, $Node.agent) })
  if ($create.status -notin @(200, 201)) { return @{ ok = $false; status = $create.status; raw = $create.raw } }
  $Graph.agentCtx[$Node.agent].investigations.Add($inv)
  $Node.data['investigation'] = $inv
  $conv = Invoke-DhRest -Method POST -Uri ('{0}/conversations?api-version={1}' -f $config.workspaceEndpoint, $config.apiVersion) -Audience discovery -Body ([ordered]@{
      displayName = $inv; investigationName = ('/projects/{0}/investigations/{1}' -f $project, $inv); projectName = $project
    })
  $convName = [string](Get-DhValue $conv.body 'name' '')
  if ($conv.status -notin @(200, 201) -or -not $convName) { return @{ ok = $false; status = $conv.status; raw = $conv.raw } }
  $Node.data['conversation'] = $convName
  $referenceKey = if (Test-DhGaApi $config.apiVersion) { 'agent_reference' } else { 'agent' }
  $request = [ordered]@{
    input = @([ordered]@{ type = 'message'; role = 'user'; content = @([ordered]@{ type = 'input_text'; text = [string]$Node.data.plan.prompt }) })
  }
  $request[$referenceKey] = [ordered]@{ type = 'agent_reference'; name = [string]$Node.data.agentName }
  $post = Invoke-DhRest -Method POST -Uri (Get-DhResponseUrl -Config $config -Conversation $convName) -Audience discovery -Body $request -TimeoutSec 120 -MaxAttempts 2
  $responseId = [string](Get-DhValue $post.body 'id' '')
  if ($post.status -notin @(200, 201, 202) -or -not $responseId) { return @{ ok = $false; status = $post.status; raw = $post.raw } }
  $Node.data['responseId'] = $responseId
  $Node.data['attemptStartedAt'] = Get-DhUtcNow
  $Node.data['lastBody'] = $post.body
  Register-DhOperation -Node $Node -Kind 'response' -Id $responseId -PollUrl (Get-DhResponseUrl -Config $config -Conversation $convName -ResponseId $responseId) -CancelUrl (Get-DhResponseUrl -Config $config -Conversation $convName -ResponseId $responseId -Suffix '/cancel') -Audience 'discovery' | Out-Null
  return @{ ok = $true }
}

function Step-DhRoundTrip {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $config = $Graph.config
  $actx = $Graph.agentCtx[$Node.agent]
  $agent = $actx.agent
  switch ($Node.phase) {
    'init' {
      if (-not [bool](Get-DhValue $config 'roundTrip.enabled' $true)) { Complete-DhNode -Graph $Graph -Node $Node -Status 'skipped' -Category 'policy' -Code 'DH-RTP-011'; return }
      $missing = @(Get-DhMissingVariables -Config $config -Agent $agent)
      if ($missing.Count -gt 0) { Complete-DhNode -Graph $Graph -Node $Node -Status 'untested' -Code 'DH-AGT-005' -Params @{ variables = ($missing -join ', ') }; return }
      $plan = Get-DhRoundTripPlan -Agent $agent
      if ($plan.untestedCode) { Complete-DhNode -Graph $Graph -Node $Node -Status 'untested' -Code $plan.untestedCode; return }
      if (-not (Request-DhBudget -Graph $Graph -Name 'maxRoundTrips')) { Complete-DhNode -Graph $Graph -Node $Node -Status 'skipped' -Category 'policy' -Code 'DH-DEP-002' -Params @{ class = 'round trips' }; return }
      $prefixes = @{}
      foreach ($toolName in @($plan.toolsCalled)) {
        $tool = $agent.tools[$toolName]
        $prefixes[$toolName] = @(@($tool.armName, ([string]$tool.defName).ToLowerInvariant()) | Where-Object { $_ } | Select-Object -Unique)
      }
      $Node.data['plan'] = $plan
      $Node.data['prefixes'] = $prefixes
      $Node.data['specSource'] = $plan.source
      $Node.data['agentName'] = if ($actx.deployedName) { $actx.deployedName } else { Get-DhDeployedAgentName -Config $config -Agent $agent }
      $Node.data['attempts'] = 0
      Add-DhNodeEvidence -Node $Node -Name 'round-trip-prompt.txt' -Content ([string]$plan.prompt) | Out-Null
      $Node.phase = 'start'
      Set-DhNodeWait -Node $Node -Seconds 0.5
    }
    'start' {
      $Node.data.attempts = [int]$Node.data.attempts + 1
      $started = Start-DhRoundTripAttempt -Graph $Graph -Node $Node
      if (-not $started.ok) {
        Add-DhNodeEvidence -Node $Node -Name ("attempt-$($Node.data.attempts)-start.txt") -Content ([string]$started.raw) | Out-Null
        $category = Get-DhFailureCategory -Status $started.status -Text ([string]$started.raw)
        if ($category -eq 'infrastructure' -and [int]$Node.data.attempts -lt [int](Get-DhValue $config 'roundTrip.maxAttempts' 2)) { Set-DhNodeWait -Node $Node -Seconds 30; return }
        Complete-DhNode -Graph $Graph -Node $Node -Status $(if ($category -eq 'infrastructure') { 'inconclusive' } else { 'failed' }) -Category $category -Code 'DH-RTP-010' -Params @{ status = $started.status }
        return
      }
      $Node.phase = 'poll'
      Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
    }
    'poll' {
      $op = @($Node.operations | Where-Object { $_.kind -eq 'response' })[-1]
      $body = $Node.data.lastBody
      $status = [string](Get-DhValue $body 'status' '')
      if ($status -notin $script:DhResponseTerminal -and -not (Test-DhApprovalPending -Body $body)) {
        $poll = Invoke-DhRest -Method GET -Uri $op.pollUrl -Audience discovery
        if ($poll.status -eq 200 -and $poll.body -is [System.Collections.IDictionary]) { $body = $poll.body; $Node.data.lastBody = $body; $status = [string](Get-DhValue $body 'status' '') }
      }
      $limit = if ([int]$Node.data.plan.timeoutMinutes -gt 0) { [int]$Node.data.plan.timeoutMinutes } else { [int](Get-DhValue $config 'timeouts.roundTripMinutes' 20) }
      if ($status -notin $script:DhResponseTerminal -and -not (Test-DhApprovalPending -Body $body)) {
        if ((Get-DhNodeElapsedMinutes -Node $Node -Key 'attemptStartedAt') -gt $limit) {
          Stop-DhOperation -Operation $op
          Add-DhNodeEvidence -Node $Node -Name ("attempt-$($Node.data.attempts)-timeout.json") -Content $body | Out-Null
          if ([int]$Node.data.attempts -lt [int](Get-DhValue $config 'roundTrip.maxAttempts' 2)) { $Node.phase = 'start'; Set-DhNodeWait -Node $Node -Seconds 5; return }
          Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-RTP-004' -Params @{ minutes = $limit }
          return
        }
        Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
        return
      }
      Complete-DhOperation -Operation $op -Status $status
      Add-DhNodeEvidence -Node $Node -Name ("attempt-$($Node.data.attempts)-response.json") -Content $body | Out-Null
      $verdict = Get-DhRoundTripVerdict -Body $body -Plan $Node.data.plan -ToolPrefixes $Node.data.prefixes
      if ($verdict.status -ne 'passed' -and $verdict.category -eq 'infrastructure' -and [int]$Node.data.attempts -lt [int](Get-DhValue $config 'roundTrip.maxAttempts' 2)) {
        $Node.phase = 'start'
        Set-DhNodeWait -Node $Node -Seconds 10
        return
      }
      $Node.data['toolsCalled'] = @($verdict.toolsCalled)
      $bound = @(Get-DhBoundTools -Agent $agent)
      $finalStatus = $verdict.status
      if ($finalStatus -eq 'passed' -and $bound.Count -gt 0) {
        $covered = @($bound | Where-Object { $_ -in $verdict.toolsCalled }).Count
        $Node.data['coverage'] = '{0}/{1}' -f $covered, $bound.Count
        if ($covered -lt $bound.Count) {
          Add-DhNodeMessage -Node $Node -Level warning -Code 'DH-RTP-008' -Params @{ called = $covered; total = $bound.Count }
          $finalStatus = 'warning'
        }
      }
      if ($verdict.status -eq 'passed' -and [bool](Get-DhValue $config 'roundTrip.deleteInvestigationOnPass' $true)) {
        foreach ($inv in @($actx.investigations)) { try { Remove-DhInvestigation -Config $config -Name $inv | Out-Null } catch { } }
      }
      $resultStatus = if ($finalStatus -eq 'failed' -and $verdict.category -eq 'infrastructure') { 'inconclusive' } else { $finalStatus }
      Complete-DhNode -Graph $Graph -Node $Node -Status $resultStatus -Category $verdict.category -Code $verdict.code -Params $verdict.params
    }
  }
}
