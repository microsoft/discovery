# Stage: agent-register. Ports the deployer's patch_agent_yaml.py / build_payload / upsertAgent
# contract, adding multi-tool binding and the mandatory discovery-github-test markers.

$script:DhAgentOpTerminal = @('Succeeded', 'Failed', 'Canceled')

function Get-DhDeployedAgentName {
  param([System.Collections.IDictionary]$Config, [System.Collections.IDictionary]$Agent)
  $name = [string](Get-DhValue $Agent.agentDoc 'name' $Agent.name)
  return ('{0}{1}' -f $Config.namePrefix, $name)
}

function Update-DhAgentDocument {
  <#
  .SYNOPSIS Port of patch_agent_yaml.py: model id, HITL and confirmations disabled, toolIds bound (multi-tool).
  #>
  param([System.Collections.IDictionary]$Doc, [string]$ChatModel, [hashtable]$ToolIdMap, [string[]]$UnboundToolIds = @())
  $model = Get-DhValue $Doc 'model' $null
  if ($null -eq $model) { $model = [ordered]@{} }
  if ($model -is [System.Collections.IDictionary]) {
    $modelId = ([string](Get-DhValue $model 'id' '')).Trim()
    if (-not $modelId -or $modelId -eq '{{CHAT-MODEL}}') { $model['id'] = $ChatModel }
  }
  $Doc['model'] = $model
  $disc = Get-DhValue $Doc 'discoveryExtensions' $null
  if ($null -eq $disc) { $disc = [ordered]@{} }
  if (-not ($disc -is [System.Collections.IDictionary])) { throw 'Invalid discoveryExtensions: expected a mapping' }
  $disc['humanInTheLoop'] = 'Disabled'
  $tools = @(Get-DhValue $disc 'tools' @())
  foreach ($item in $tools) {
    if (-not ($item -is [System.Collections.IDictionary])) { throw 'Invalid discoveryExtensions.tools entry: expected a mapping' }
    $item['confirmation'] = 'Disabled'
  }
  $deduped = [System.Collections.Generic.List[object]]::new()
  $seen = [System.Collections.Generic.HashSet[string]]::new()
  foreach ($item in $tools) {
    $current = ([string](Get-DhValue $item 'toolId' '')).Trim()
    if ($ToolIdMap.ContainsKey($current)) { $item['toolId'] = $ToolIdMap[$current] }
    $leaf = ((([string]$item['toolId']) -split '/')[-1]).ToLowerInvariant()
    if ($leaf -and -not $seen.Add($leaf)) { continue }
    $deduped.Add($item)
  }
  foreach ($toolId in $UnboundToolIds) {
    $leaf = (($toolId -split '/')[-1]).ToLowerInvariant()
    if ($seen.Add($leaf)) { $deduped.Add([ordered]@{ toolId = $toolId; confirmation = 'Disabled' }) }
  }
  $disc['tools'] = $deduped.ToArray()
  $Doc['discoveryExtensions'] = $disc
  return $Doc
}

function Resolve-DhTemplateVariables {
  <#
  .SYNOPSIS Port of resolve_variables: replaces {{word}} from the deploy config, leaving unknowns intact.
  #>
  param($Value, [hashtable]$Variables)
  if ($Value -is [string]) {
    return [regex]::Replace($Value, '\{\{(\w+)\}\}', {
        param($m)
        $key = $m.Groups[1].Value
        if ($Variables.ContainsKey($key)) { return [string]$Variables[$key] }
        return $m.Value
      })
  }
  if ($Value -is [System.Collections.IDictionary]) {
    $out = [ordered]@{}
    foreach ($key in $Value.Keys) { $out[$key] = Resolve-DhTemplateVariables -Value $Value[$key] -Variables $Variables }
    return $out
  }
  if ($Value -is [array]) {
    return , @($Value | ForEach-Object { Resolve-DhTemplateVariables -Value $_ -Variables $Variables })
  }
  return $Value
}

function New-DhPromptDefinition {
  param([System.Collections.IDictionary]$Doc)
  $out = [ordered]@{ kind = 'prompt' }
  $model = Get-DhValue $Doc 'model' $null
  if ($model -is [string]) { $out['model'] = $model }
  elseif ($model -is [System.Collections.IDictionary]) {
    $out['model'] = [string](Get-DhValue $model 'id' '')
    $options = Get-DhValue $model 'options' @{}
    if ($options -is [System.Collections.IDictionary] -and $options.Contains('temperature')) { $out['temperature'] = $options['temperature'] }
  }
  if ($Doc.Contains('instructions')) { $out['instructions'] = $Doc['instructions'] }
  $outputSchema = Get-DhValue $Doc 'outputSchema' $null
  if ($outputSchema) {
    $props = Get-DhValue $outputSchema 'properties' @{}
    $jsonProps = [ordered]@{}
    $required = [System.Collections.Generic.List[string]]::new()
    foreach ($name in $props.Keys) {
      $prop = $props[$name]
      $jsonProps[$name] = [ordered]@{ type = [string](Get-DhValue $prop 'kind' 'string'); description = [string](Get-DhValue $prop 'description' '') }
      if ([bool](Get-DhValue $prop 'required' $true)) { $required.Add($name) }
    }
    $out['text'] = [ordered]@{
      format = [ordered]@{
        type = 'json_schema'; name = ('{0}Output' -f $Doc['name']); description = [string](Get-DhValue $Doc 'description' '')
        schema = [ordered]@{ type = 'object'; properties = $jsonProps; required = $required.ToArray(); additionalProperties = $false }
        strict = [bool](Get-DhValue $outputSchema 'strict' $true)
      }
    }
  }
  return $out
}

function New-DhAgentPayload {
  <#
  .SYNOPSIS Port of build_payload for prompt agents.
  #>
  param([System.Collections.IDictionary]$Doc)
  if ([string](Get-DhValue $Doc 'kind' 'prompt') -eq 'workflow') { throw 'Workflow agents are not supported. Use prompt-agent YAML.' }
  $payload = [ordered]@{ name = $Doc['name'] }
  $extensions = Get-DhValue $Doc 'discoveryExtensions' ([ordered]@{})
  foreach ($key in @('humanInTheLoop', 'tools', 'knowledgeBases')) {
    if ($extensions.Contains($key)) { $payload[$key] = $extensions[$key] }
  }
  $remaining = [ordered]@{}
  foreach ($key in $extensions.Keys) { if ($key -notin @('humanInTheLoop', 'tools', 'knowledgeBases')) { $remaining[$key] = $extensions[$key] } }
  if ($remaining.Count -gt 0) { $payload['discoveryExtensions'] = $remaining }
  $payload['foundryDetails'] = [ordered]@{ description = [string](Get-DhValue $Doc 'description' ''); definition = (New-DhPromptDefinition -Doc $Doc) }
  return $payload
}

function Get-DhDeployVariables {
  param([System.Collections.IDictionary]$Config, [string]$FirstToolId = '')
  $vars = @{
    workspaceEndpoint = $Config.workspaceEndpoint; apiVersion = $Config.apiVersion; project = $Config.project; model = $Config.chatModel
    tenantId = $Config.tenantId; resourceGroup = ('/subscriptions/{0}/resourceGroups/{1}' -f $Config.subscriptionId, $Config.resourceGroup)
  }
  if ($FirstToolId) { $vars['corePythonToolId'] = $FirstToolId }
  if (-not $script:Dh.Untrusted) {
    foreach ($key in @($Config.templateVariables.Keys)) { $vars[$key] = [string]$Config.templateVariables[$key] }
  }
  return $vars
}

function New-DhAgentDeployment {
  <#
  .SYNOPSIS Builds the patched, marked, variable-resolved upsert payload for an agent.
  #>
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Agent)
  $config = $Graph.config
  $map = @{}
  $firstToolId = ''
  foreach ($binding in $Agent.bindings) {
    if (-not $binding.tool) { continue }
    $resourceId = [string]$Graph.toolCtx['{0}/{1}' -f $Agent.name, $binding.tool].toolResourceId
    if ($resourceId) { $map[[string]$binding.toolId] = $resourceId; if (-not $firstToolId) { $firstToolId = $resourceId } }
  }
  $unbound = @()
  if (@($Agent.bindings).Count -eq 0) {
    foreach ($tool in $Agent.tools.Values) {
      $resourceId = [string]$Graph.toolCtx['{0}/{1}' -f $Agent.name, $tool.name].toolResourceId
      if ($resourceId) { $unbound += $resourceId; if (-not $firstToolId) { $firstToolId = $resourceId } }
    }
  }
  $doc = Copy-DhObject $Agent.agentDoc
  $doc = Update-DhAgentDocument -Doc $doc -ChatModel $config.chatModel -ToolIdMap $map -UnboundToolIds $unbound
  $doc['name'] = Get-DhDeployedAgentName -Config $config -Agent $Agent
  $doc['description'] = ('{0} [{1} {2}]' -f ([string](Get-DhValue $doc 'description' '')).TrimEnd(), $config.testTag, $script:Dh.RunId).Trim()
  $doc = Resolve-DhTemplateVariables -Value $doc -Variables (Get-DhDeployVariables -Config $config -FirstToolId $firstToolId)
  return (New-DhAgentPayload -Doc $doc)
}

function Get-DhMissingVariables {
  param([System.Collections.IDictionary]$Config, [System.Collections.IDictionary]$Agent)
  $available = if ($script:Dh.Untrusted) { @() } else { @($Config.templateVariables.Keys) }
  $required = @($Agent.requiredVariables) + @(Get-DhValue $Agent.spec 'requires.variables' @())
  return @($required | Where-Object { $_ -and $_ -notin $available } | Select-Object -Unique)
}

function Step-DhAgentRegister {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $config = $Graph.config
  $actx = $Graph.agentCtx[$Node.agent]
  $agent = $actx.agent
  switch ($Node.phase) {
    'init' {
      $missing = @(Get-DhMissingVariables -Config $config -Agent $agent)
      if ($missing.Count -gt 0) { Complete-DhNode -Graph $Graph -Node $Node -Status 'untested' -Code 'DH-AGT-005' -Params @{ variables = ($missing -join ', ') }; return }
      if (@($agent.topLevelToolKinds).Count -gt 0) { Add-DhNodeMessage -Node $Node -Level warning -Code 'DH-AGT-004' -Params @{ kinds = (@($agent.topLevelToolKinds) -join ', ') } }
      foreach ($toolName in @(Get-DhBoundTools -Agent $agent)) {
        $toolCtx = $Graph.toolCtx['{0}/{1}' -f $agent.name, $toolName]
        if (-not $toolCtx.toolResourceId) { $toolCtx.toolResourceId = Find-DhRegisteredTool -Graph $Graph -Tool $toolCtx.tool }
        if (-not $toolCtx.toolResourceId) { Complete-DhNode -Graph $Graph -Node $Node -Status 'blocked' -Category 'policy' -Code 'DH-RUN-009'; return }
      }
      $payload = New-DhAgentDeployment -Graph $Graph -Agent $agent
      $Node.data['deployedName'] = [string]$payload.name
      Add-DhNodeEvidence -Node $Node -Name 'agent-payload.json' -Content $payload | Out-Null
      $url = '{0}/projects/{1}:upsertAgent?api-version={2}' -f $config.workspaceEndpoint, [Uri]::EscapeDataString([string]$config.project), $config.apiVersion
      $response = Invoke-DhRest -Method POST -Uri $url -Audience discovery -Body $payload -MaxAttempts 3
      if ($response.status -notin @(200, 202)) {
        Add-DhNodeEvidence -Node $Node -Name 'agent-upsert-response.txt' -Content ([string]$response.raw) | Out-Null
        $category = Get-DhFailureCategory -Status $response.status -Text ([string]$response.raw)
        Complete-DhNode -Graph $Graph -Node $Node -Status $(if ($category -eq 'infrastructure') { 'inconclusive' } else { 'failed' }) -Category $category -Code 'DH-AGT-001' -Params @{ status = $response.status }
        return
      }
      $opUrl = Get-DhHeaderValue -Headers $response.headers -Name 'operation-location'
      $actx.deployedName = [string]$payload.name
      if (-not $opUrl) { $Node.phase = 'state'; Set-DhNodeWait -Node $Node -Seconds 1; return }
      Register-DhOperation -Node $Node -Kind 'agent-upsert' -Id ([string]$payload.name) -PollUrl $opUrl -Audience 'discovery' | Out-Null
      $Node.data['opUrl'] = $opUrl
      $Node.phase = 'polling'
      Set-DhNodeWait -Node $Node -Seconds ([math]::Min(10, [int]$config.pollSeconds))
    }
    'polling' {
      $response = Invoke-DhRest -Method GET -Uri ([string]$Node.data.opUrl) -Audience discovery
      $status = [string](Get-DhValue $response.body 'status' '')
      if ($response.status -eq 200 -and $status -in $script:DhAgentOpTerminal) {
        if ($status -ne 'Succeeded') {
          Add-DhNodeEvidence -Node $Node -Name 'agent-operation.json' -Content $response.body | Out-Null
          Complete-DhNode -Graph $Graph -Node $Node -Status 'failed' -Category (Get-DhFailureCategory -Text ([string]$response.raw)) -Code 'DH-AGT-002' -Params @{ status = $status }
          return
        }
        $Node.phase = 'state'
        Set-DhNodeWait -Node $Node -Seconds 1
        return
      }
      if ((Get-DhNodeElapsedMinutes -Node $Node) -gt [int](Get-DhValue $config 'timeouts.agentRegisterMinutes' 10)) {
        Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-AGT-006' -Params @{ minutes = (Get-DhValue $config 'timeouts.agentRegisterMinutes' 10) }
        return
      }
      Set-DhNodeWait -Node $Node -Seconds ([math]::Min(15, [int]$config.pollSeconds))
    }
    'state' {
      $url = '{0}/projects/{1}/agents/{2}?api-version={3}' -f $config.workspaceEndpoint, [Uri]::EscapeDataString([string]$config.project), [Uri]::EscapeDataString([string]$actx.deployedName), $config.apiVersion
      $response = Invoke-DhRest -Method GET -Uri $url -Audience discovery
      $state = [string](Get-DhValue $response.body 'provisioningState' 'Unknown')
      Add-DhNodeEvidence -Node $Node -Name 'agent-state.json' -Content ([string]$response.raw) | Out-Null
      if ($state -in @('Failed', 'Canceled')) {
        Complete-DhNode -Graph $Graph -Node $Node -Status 'failed' -Category 'contribution' -Code 'DH-AGT-002' -Params @{ status = $state }
        return
      }
      Complete-DhNode -Graph $Graph -Node $Node -Status 'passed' -Code 'DH-AGT-003' -Params @{ name = $actx.deployedName }
    }
  }
}
