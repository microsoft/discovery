# Stage: tool-register (Microsoft.Discovery/tools via ARM) with test tags and hash-based reuse.

$script:DhToolInFlight = @('Accepted', 'Creating', 'Updating', 'Deleting', 'Running', 'Provisioning')
$script:DhToolTerminal = @('Succeeded', 'Failed', 'Canceled')

function Get-DhToolResourceId {
  param([System.Collections.IDictionary]$Config, [string]$ArmName)
  return ('/subscriptions/{0}/resourceGroups/{1}/providers/Microsoft.Discovery/tools/{2}' -f $Config.subscriptionId, $Config.resourceGroup, $ArmName)
}

function Get-DhToolUrl {
  param([System.Collections.IDictionary]$Config, [string]$ArmName)
  return ('https://management.azure.com{0}?api-version={1}' -f (Get-DhToolResourceId -Config $Config -ArmName $ArmName), $Config.apiVersion)
}

function New-DhToolDefinition {
  <#
  .SYNOPSIS Copy of tool.yaml with every infra image pointed at the tested ACR image.
  #>
  param([System.Collections.IDictionary]$Tool, [string]$ImageRef)
  $definition = Copy-DhObject $Tool.def
  foreach ($infra in @(Get-DhValue $definition 'infra' @())) {
    if ($infra -is [System.Collections.IDictionary] -and $infra.Contains('image') -and $infra.image -is [System.Collections.IDictionary]) {
      $infra.image['acr'] = $ImageRef
    }
  }
  return $definition
}

function New-DhToolArmBody {
  param([System.Collections.IDictionary]$Config, [System.Collections.IDictionary]$Agent, [System.Collections.IDictionary]$Definition, [string]$DefinitionHash)
  $category = [string](Get-DhValue $Definition 'category' '')
  if (-not $category) { $category = 'General' }
  $tags = [ordered]@{
    category = $category
    'dgt-run-id' = [string]$script:Dh.RunId
    'dgt-git-sha' = $(if ($script:Dh.GitSha) { [string]$script:Dh.GitSha } else { 'unknown' })
    'dgt-agent' = [string]$Agent.name
    'dgt-def-hash' = $DefinitionHash
  }
  $tags[[string]$Config.testTag] = 'true'
  return [ordered]@{
    location   = $Config.location
    tags       = $tags
    properties = [ordered]@{ version = '1.0.0'; definitionContent = $Definition }
  }
}

function Find-DhRegisteredTool {
  <#
  .SYNOPSIS Existing tagged tool resource for this tool, used when tool-register is not selected.
  #>
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Tool)
  $config = $Graph.config
  $response = Invoke-DhRest -Method GET -Uri (Get-DhToolUrl -Config $config -ArmName $Tool.armName) -Audience arm
  if ($response.status -ne 200) { return '' }
  $tags = Get-DhValue $response.body 'tags' @{}
  if ([string](Get-DhValue $tags ([string]$config.testTag) '') -ne 'true') { return '' }
  if ([string](Get-DhValue $response.body 'properties.provisioningState' '') -ne 'Succeeded') { return '' }
  return (Get-DhToolResourceId -Config $config -ArmName $Tool.armName)
}

function Step-DhToolRegister {
  param([System.Collections.IDictionary]$Graph, [System.Collections.IDictionary]$Node)
  $config = $Graph.config
  $ctx = $Graph.toolCtx['{0}/{1}' -f $Node.agent, $Node.tool]
  $tool = $ctx.tool
  $url = Get-DhToolUrl -Config $config -ArmName $tool.armName
  switch ($Node.phase) {
    'init' {
      if (-not $ctx.imageRef) {
        $existing = Find-DhImageForFingerprint -Graph $Graph -Tool $tool
        if (-not $existing) { Complete-DhNode -Graph $Graph -Node $Node -Status 'blocked' -Category 'policy' -Code 'DH-REG-005'; return }
        $ctx.imageRef = $existing.imageRef; $ctx.imageTag = $existing.tag; $ctx.digest = $existing.digest
      }
      $definition = New-DhToolDefinition -Tool $tool -ImageRef $ctx.imageRef
      $hash = (Get-DhSha256Hex ('{0}|{1}' -f (ConvertTo-DhJson $definition -Compress), $config.location)).Substring(0, 32)
      $Node.data['imageRef'] = $ctx.imageRef
      $current = Invoke-DhRest -Method GET -Uri $url -Audience arm
      if ($current.status -eq 200) {
        $state = [string](Get-DhValue $current.body 'properties.provisioningState' '')
        $existingHash = [string](Get-DhValue $current.body 'tags.dgt-def-hash' '')
        if ($state -eq 'Succeeded' -and $existingHash -eq $hash) {
          $ctx.toolResourceId = Get-DhToolResourceId -Config $config -ArmName $tool.armName
          Complete-DhNode -Graph $Graph -Node $Node -Status 'cached' -Code 'DH-REG-004'
          return
        }
        if ($state -in $script:DhToolInFlight) {
          $Node.phase = 'polling'
          Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
          return
        }
      }
      $body = New-DhToolArmBody -Config $config -Agent $ctx.agent -Definition $definition -DefinitionHash $hash
      Add-DhNodeEvidence -Node $Node -Name 'tool-arm-body.json' -Content $body | Out-Null
      $put = Invoke-DhRest -Method PUT -Uri $url -Audience arm -Body $body
      if ($put.status -notin @(200, 201, 202)) {
        Add-DhNodeEvidence -Node $Node -Name 'tool-put-response.txt' -Content ([string]$put.raw) | Out-Null
        $category = Get-DhFailureCategory -Status $put.status -Text ([string]$put.raw)
        Complete-DhNode -Graph $Graph -Node $Node -Status $(if ($category -eq 'infrastructure') { 'inconclusive' } else { 'failed' }) -Category $category -Code 'DH-REG-001' -Params @{ status = $put.status }
        return
      }
      Register-DhOperation -Node $Node -Kind 'arm-tool' -Id $tool.armName -PollUrl $url | Out-Null
      $Node.phase = 'polling'
      Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
    }
    'polling' {
      $response = Invoke-DhRest -Method GET -Uri $url -Audience arm
      $state = [string](Get-DhValue $response.body 'properties.provisioningState' '')
      if ($state -notin $script:DhToolTerminal) {
        if ((Get-DhNodeElapsedMinutes -Node $Node) -gt [int](Get-DhValue $config 'timeouts.toolRegisterMinutes' 30)) {
          Complete-DhNode -Graph $Graph -Node $Node -Status 'inconclusive' -Category 'infrastructure' -Code 'DH-REG-003' -Params @{ minutes = (Get-DhValue $config 'timeouts.toolRegisterMinutes' 30) }
          return
        }
        Set-DhNodeWait -Node $Node -Seconds ([int]$config.pollSeconds)
        return
      }
      Add-DhNodeEvidence -Node $Node -Name 'tool-resource.json' -Content $response.body | Out-Null
      if ($state -ne 'Succeeded') {
        $category = Get-DhFailureCategory -Text ([string]$response.raw)
        Complete-DhNode -Graph $Graph -Node $Node -Status 'failed' -Category $category -Code 'DH-REG-002' -Params @{ state = $state }
        return
      }
      $ctx.toolResourceId = Get-DhToolResourceId -Config $config -ArmName $tool.armName
      Complete-DhNode -Graph $Graph -Node $Node -Status 'passed' -Code 'DH-REG-006'
    }
  }
}
