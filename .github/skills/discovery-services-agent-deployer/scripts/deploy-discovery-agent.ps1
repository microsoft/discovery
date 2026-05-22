param(
  [string[]]$AgentName,
  [string]$PublisherName,
  [ValidateSet('auto','remote','local')]
  [string]$BuildMode = 'auto',
  [string]$Resume,
  [string]$RunDir,
  [ValidateSet('init','build','deploy-tool','deploy-agent','validate','summary','stop')]
  [string]$Stage,
  [switch]$ConfirmSupercomputerNodepools,
  [string]$ValidationPrompt,
  [switch]$SkipValidation,
  [switch]$WhatIfPlan,
  [switch]$SuppressTaskPlan,
  [Parameter(Position=0, ValueFromRemainingArguments=$true)]
  [string[]]$AgentArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SkillRoot = Split-Path -Parent $PSScriptRoot
$script:DiscoveryDeploySkillRoot = $SkillRoot

# Inlined deployment implementation. Keep this file self-contained like discovery-services-starter-kit-deployer.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Suppress Azure CLI telemetry collection.  The telemetry module has a known
# bug where its cleanup phase crashes with a KeyboardInterrupt during deepcopy
# in _get_azure_subscription_id, causing az to exit non-zero even when the
# command itself succeeded (SystemExit: 0).  Disabling telemetry skips that
# entire code path and prevents the crash across all stages.
$env:AZURE_CORE_COLLECT_TELEMETRY = 'no'

function Get-RepoRoot {
  return (git rev-parse --show-toplevel).Trim()
}

function Assert-PowerShell7OrNewer {
  $Version = $PSVersionTable.PSVersion
  if ($Version.Major -lt 7) {
    throw "PowerShell 7+ is required for discovery-services-agent-deployer stages. Current version: $Version. Run with 'pwsh'."
  }
}

function Test-ConfigValuePresent {
  param($Value)

  if ($null -eq $Value) { return $false }
  $Text = ([string]$Value).Trim()
  if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
  if ($Text -like '<*>') { return $false }
  return $true
}

function Get-ConfigRawValue {
  param(
    [object]$ConfigObj,
    [string]$Field
  )

  if ($null -eq $ConfigObj) { return $null }
  if ($ConfigObj -is [System.Collections.IDictionary]) {
    if ($ConfigObj.Contains($Field)) { return $ConfigObj[$Field] }
    if (($ConfigObj -is [hashtable]) -and $ConfigObj.ContainsKey($Field)) { return $ConfigObj[$Field] }
    return $null
  }
  if ($ConfigObj.PSObject.Properties.Name -contains $Field) {
    return $ConfigObj.$Field
  }
  return $null
}

function Get-ConfigFieldMetadata {
  param([string]$Field)

  $Metadata = @{
    subscriptionId = @{ label = 'Azure subscription ID'; example = '00000000-0000-0000-0000-000000000000' }
    resourceGroup = @{ label = 'Azure resource group for Discovery tool resources'; example = 'my-discovery-rg' }
    acrName = @{ label = 'Azure Container Registry name without .azurecr.io'; example = 'myregistry' }
    acrResourceGroup = @{ label = 'Optional Azure resource group that contains ACR when different from resourceGroup'; example = 'my-acr-rg' }
    location = @{ label = 'Azure region for the Discovery tool resource; ask the user to choose a region'; example = 'uksouth'; requireUserInput = $true }
    workspaceEndpoint = @{ label = 'Discovery workspace endpoint'; example = 'https://my-workspace.workspace.discovery.azure.com' }
    project = @{ label = 'Discovery project name'; example = 'my-project' }
    tenantId = @{ label = 'Entra tenant ID'; example = '00000000-0000-0000-0000-000000000000' }
    chatModel = @{ label = 'Model deployment name for {{CHAT-MODEL}}'; example = 'gpt-4.1' }
    forceToolImageRebuild = @{ label = 'Whether to rebuild and repush the tool image even if the ACR tag already exists'; example = 'false'; requireUserInput = $true }
    runReuseWindowMinutes = @{ label = 'Recent run folder reuse window in minutes'; example = '2'; default = 2 }
    printAcrLogsOnFailure = @{ label = 'Whether to print ACR logs when a remote build fails'; example = 'false'; default = $false }
    deleteInvestigationAfterTest = @{ label = 'Whether to delete the validation investigation after the test'; example = 'false'; default = $false }
  }

  if ($Metadata.ContainsKey($Field)) { return $Metadata[$Field] }
  return @{ label = $Field; example = '' }
}

function Write-CopilotConfigInputRequest {
  param(
    [string]$ConfigPath,
    [string[]]$MissingFields
  )

  $Template = [ordered]@{}
  foreach ($Field in $MissingFields) {
    $Meta = Get-ConfigFieldMetadata -Field $Field
    $RequireUserInput = $Meta.ContainsKey('requireUserInput') -and [bool]$Meta['requireUserInput']
    if ($Meta.ContainsKey('default') -and -not $RequireUserInput) {
      $Template[$Field] = $Meta['default']
    } else {
      $Template[$Field] = ''
    }
  }
  foreach ($Field in @('runReuseWindowMinutes','printAcrLogsOnFailure','deleteInvestigationAfterTest')) {
    if (-not $Template.Contains($Field)) {
      $Meta = Get-ConfigFieldMetadata -Field $Field
      $Template[$Field] = $Meta['default']
    }
  }

  Write-Host 'CONFIG_INPUT_REQUIRED=true'
  Write-Host ("CONFIG_PATH={0}" -f $ConfigPath)
  Write-Host ("CONFIG_FIELDS_TO_COLLECT={0}" -f ($MissingFields -join ','))
  Write-Host 'CONFIG_INPUT_FORMAT=copilot'
  Write-Host '--- COPILOT CONFIG INPUT REQUEST ---'
  Write-Host 'I need these values before running the Discovery deployment. Ask the user for every listed value in chat; do not infer or choose values from examples/defaults. After the user answers, create the ignored config.json and rerun the stage.'
  foreach ($Field in $MissingFields) {
    $Meta = Get-ConfigFieldMetadata -Field $Field
    $DefaultText = if ($Meta.ContainsKey('default')) { " Default: $($Meta['default'])." } else { '' }
    $ExampleText = if ($Meta.ContainsKey('example') -and -not [string]::IsNullOrWhiteSpace($Meta['example'])) { " Example: $($Meta['example'])." } else { '' }
    Write-Host ("- {0}: {1}.{2}{3}" -f $Field, $Meta['label'], $DefaultText, $ExampleText)
  }
  Write-Host 'Suggested config.json shape:'
  Write-Host ($Template | ConvertTo-Json -Depth 10)
  Write-Host '--- END COPILOT CONFIG INPUT REQUEST ---'
}

function Write-CopilotBuildModeInputRequest {
  param([string]$AgentName)

  Write-Host 'BUILD_MODE_INPUT_REQUIRED=true'
  Write-Host 'BUILD_MODE_INPUT_FORMAT=copilot'
  Write-Host '--- COPILOT BUILD MODE INPUT REQUEST ---'
  Write-Host 'Docker is available for this run. Ask the user to choose the build mode for this deployment, then rerun the stage with -BuildMode <remote|local>. Do not infer a choice and do not write buildMode to config.json.'
  Write-Host '- remote: build and push with Azure Container Registry Tasks.'
  Write-Host '- local: build with local Docker, then push to ACR.'
  if (-not [string]::IsNullOrWhiteSpace($AgentName)) {
    Write-Host ("Suggested rerun command: pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-agent-deployer\scripts\deploy-discovery-agent.ps1 {0} -Stage init -BuildMode <remote|local>" -f $AgentName)
  }
  Write-Host '--- END COPILOT BUILD MODE INPUT REQUEST ---'
}

function Get-AcrResourceGroup {
  param([hashtable]$Config)
  if ($Config.ContainsKey('acrResourceGroup') -and -not [string]::IsNullOrWhiteSpace([string]$Config.acrResourceGroup)) {
    return [string]$Config.acrResourceGroup
  }
  return [string]$Config.resourceGroup
}

function Write-SupercomputerNodepoolPlan {
  param([hashtable]$Context)
  $SkuText = if ($Context.ContainsKey('recommendedSkus') -and @($Context.recommendedSkus).Count -gt 0) { (@($Context.recommendedSkus) -join ',') } else { '<none specified>' }
  Write-Host '=== TOOL BUILD PLAN ==='
  Write-Host ("TOOL_BUILD_PLAN tool={0} agent={1} image={2} recommendedSkus={3}" -f $Context.toolName, $Context.agentName, $Context.imageRef, $SkuText)
}

function Assert-SupercomputerNodepoolConfirmed {
  param(
    [bool]$Confirmed,
    [hashtable]$Context
  )
  if ($Confirmed) { return }
  $SkuText = if ($Context -and $Context.ContainsKey('recommendedSkus') -and @($Context.recommendedSkus).Count -gt 0) { (@($Context.recommendedSkus) -join ', ') } else { '<none specified>' }
  Write-Host 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED=true'
  Write-Host 'SUPERCOMPUTER_NODEPOOL_SKU_SEMANTICS=The recommendedSkus listed for the tool are alternative nodepool choices; confirm capacity for at least one listed SKU.'
  Write-Host 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_CHOICES=Proceed - I have Supercomputer nodepool capacity for at least one listed SKU|Stop - I do not have the required Supercomputer nodepool capacity'
  Write-Host 'SUPERCOMPUTER_NODEPOOL_INPUT_FORMAT=copilot'
  Write-Host 'SUPERCOMPUTER_NODEPOOL_PROMPT_UI=choice'
  Write-Host '--- COPILOT SUPERCOMPUTER NODEPOOL INPUT REQUEST ---'
  Write-Host 'Use the assistant choice-prompt UI to ask the customer this exact question before running any build command. Do not ask as plain text.'
  Write-Host ("Do you have Supercomputer nodepool capacity to proceed with the tool build for '{0}'? The listed SKUs are alternatives; you need capacity for at least one of: {1}." -f $Context.toolName, $SkuText)
  Write-Host 'Choices:'
  Write-Host '- Proceed - I have Supercomputer nodepool capacity for at least one listed SKU.'
  Write-Host '- Stop - I do not have the required Supercomputer nodepool capacity.'
  Write-Host 'If the customer chooses Proceed, rerun build with -ConfirmSupercomputerNodepools. Do not write confirmSupercomputerNodepools to config.json.'
  Write-Host 'If the customer chooses Stop, run -Stage stop for this RunDir and tell them: When you have Supercomputer nodepool capacity for at least one of the listed SKUs per tool, rerun the skill.'
  Write-Host '--- END COPILOT SUPERCOMPUTER NODEPOOL INPUT REQUEST ---'
  throw 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED: Ask the customer to proceed or stop based on Supercomputer nodepool capacity before building the tool.'
}

function Resolve-ConfigField {
  param(
    [object]$ConfigObj,
    [string]$Field,
    $Default = $null,
    [switch]$Required,
    [switch]$PromptForMissing,
    [string]$PromptLabel
  )

  $Raw = Get-ConfigRawValue -ConfigObj $ConfigObj -Field $Field
  if (Test-ConfigValuePresent -Value $Raw) {
    return [string]$Raw
  }

  if ($null -ne $Default) {
    return [string]$Default
  }

  if ($Required) {
    throw "config.json is missing required field '$Field'."
  }

  return $null
}

function Get-PreferredLocationValues {
  return @('eastus','uksouth','swedencentral')
}

function Convert-ConfigToBool {
  param(
    $Value,
    [bool]$Default = $false
  )

  if ($null -eq $Value) { return $Default }
  if ($Value -is [bool]) { return [bool]$Value }

  $Text = ([string]$Value).Trim().ToLowerInvariant()
  if ($Text -in @('true','1','yes','y','on')) { return $true }
  if ($Text -in @('false','0','no','n','off')) { return $false }
  return $Default
}

function Convert-ConfigToInt {
  param(
    $Value,
    [int]$Default
  )

  try {
    return [int]$Value
  } catch {
    return $Default
  }
}

function Load-BuilderConfig {
  param(
    [string]$SkillStagesDir,
    [string[]]$RequiredFields = @('subscriptionId','resourceGroup','acrName'),
    [switch]$PromptForMissing,
    [hashtable]$SeedConfig = @{},
    [switch]$Quiet
  )

  $SkillDir = $script:DiscoveryDeploySkillRoot
  $ConfigPath = Join-Path $SkillDir 'config.json'
  $Config = $null
  if (Test-Path $ConfigPath) {
    $Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
  } elseif (-not $Quiet) {
    Write-Host "[config] Missing $ConfigPath."
  }

  $Required = @{}
  foreach ($Field in $RequiredFields) { $Required[$Field] = $true }

  $WorkingConfig = [ordered]@{}
  if ($Config) {
    if ($Config -is [hashtable]) {
      foreach ($k in $Config.Keys) { $WorkingConfig[$k] = $Config[$k] }
    } else {
      foreach ($p in $Config.PSObject.Properties) { $WorkingConfig[$p.Name] = $p.Value }
    }
  }
  if ($SeedConfig) {
    foreach ($k in $SeedConfig.Keys) {
      if (Test-ConfigValuePresent -Value $SeedConfig[$k]) {
        $WorkingConfig[$k] = $SeedConfig[$k]
      }
    }
  }
  foreach ($RunScopedField in @('buildMode','confirmSupercomputerNodepools')) {
    if ($WorkingConfig.Contains($RunScopedField)) { $WorkingConfig.Remove($RunScopedField) }
  }

  if ($PromptForMissing) {
    $MissingRequired = @()
    foreach ($Field in $RequiredFields) {
      $RawValue = Get-ConfigRawValue -ConfigObj $WorkingConfig -Field $Field
      $Meta = Get-ConfigFieldMetadata -Field $Field
      if (Test-ConfigValuePresent -Value $RawValue) {
        continue
      }
      $RequireUserInput = $Meta.ContainsKey('requireUserInput') -and [bool]$Meta['requireUserInput']
      if (-not $RequireUserInput -and $Meta.ContainsKey('default') -and (Test-ConfigValuePresent -Value $Meta['default'])) { continue }
      $MissingRequired += $Field
    }
    $DockerAvailableVar = Get-Variable -Name 'DiscoveryDeployDockerAvailableForInput' -Scope script -ErrorAction SilentlyContinue
    $BuildModeVar = Get-Variable -Name 'DiscoveryDeployBuildModeForInput' -Scope script -ErrorAction SilentlyContinue
    $AgentNameVar = Get-Variable -Name 'DiscoveryDeployAgentNameForInput' -Scope script -ErrorAction SilentlyContinue
    if ($null -ne $DockerAvailableVar -and $DockerAvailableVar.Value -and $null -ne $BuildModeVar -and $BuildModeVar.Value -eq 'auto') {
      Write-CopilotBuildModeInputRequest -AgentName ($null -ne $AgentNameVar ? $AgentNameVar.Value : '')
    }
    if ($MissingRequired.Count -gt 0) {
      Write-CopilotConfigInputRequest -ConfigPath $ConfigPath -MissingFields $MissingRequired
      throw ("CONFIG_INPUT_REQUIRED: Missing required field(s): {0}. Provide these values through Copilot, write {1}, then rerun the stage." -f ($MissingRequired -join ', '), $ConfigPath)
    }
  }

  $SubscriptionId = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'subscriptionId' -Required:($Required.ContainsKey('subscriptionId')) -PromptLabel 'subscriptionId'
  $ResourceGroup = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'resourceGroup' -Required:($Required.ContainsKey('resourceGroup')) -PromptLabel 'resourceGroup'
  $AcrName = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'acrName' -Required:($Required.ContainsKey('acrName')) -PromptLabel 'acrName (without .azurecr.io)'
  $AcrResourceGroup = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'acrResourceGroup' -PromptLabel 'acrResourceGroup'
  $Location = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'location' -Default 'uksouth' -PromptLabel 'location [eastus/uksouth/swedencentral or custom]'
  if (Test-ConfigValuePresent -Value $Location) {
    $Location = ([string]$Location).Trim().ToLowerInvariant()
    $PreferredLocations = Get-PreferredLocationValues
    if ($PreferredLocations -notcontains $Location) {
      Write-Host "[config] Location '$Location' is outside the preferred list (eastus, uksouth, swedencentral). Continuing with custom value."
    }
  }
  $ApiVersion = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'apiVersion' -Default '2026-02-01-preview' -PromptLabel 'apiVersion'
  $WorkspaceEndpoint = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'workspaceEndpoint' -Required:($Required.ContainsKey('workspaceEndpoint')) -PromptLabel 'workspaceEndpoint (https://<workspace>.workspace.discovery.azure.com)'
  $Project = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'project' -Required:($Required.ContainsKey('project')) -PromptLabel 'project'
  $TenantId = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'tenantId' -Required:($Required.ContainsKey('tenantId')) -PromptLabel 'tenantId'
  $ChatModel = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'chatModel' -Required:($Required.ContainsKey('chatModel')) -PromptLabel 'chatModel deployment name'
  $TestPrompt = Resolve-ConfigField -ConfigObj $WorkingConfig -Field 'testPrompt' -PromptForMissing:$false -PromptLabel 'testPrompt'
  $RunReuseRaw = Get-ConfigRawValue -ConfigObj $WorkingConfig -Field 'runReuseWindowMinutes'
  if (-not (Test-ConfigValuePresent -Value $RunReuseRaw)) { $RunReuseRaw = 2 }
  $RunReuseWindowMinutes = Convert-ConfigToInt -Value $RunReuseRaw -Default 2

  $PrintAcrLogsRaw = Get-ConfigRawValue -ConfigObj $WorkingConfig -Field 'printAcrLogsOnFailure'
  $DeleteInvestigationRaw = Get-ConfigRawValue -ConfigObj $WorkingConfig -Field 'deleteInvestigationAfterTest'
  $ForceToolImageRebuildRaw = Get-ConfigRawValue -ConfigObj $WorkingConfig -Field 'forceToolImageRebuild'

  $PrintAcrLogsOnFailure = Convert-ConfigToBool -Value $PrintAcrLogsRaw -Default $false
  $DeleteInvestigationAfterTest = Convert-ConfigToBool -Value $DeleteInvestigationRaw -Default $false
  $ForceToolImageRebuild = Convert-ConfigToBool -Value $ForceToolImageRebuildRaw -Default $false

  if ([string]::IsNullOrWhiteSpace(([string]$ApiVersion).Trim())) {
    throw "config.json is missing a usable 'apiVersion' value."
  }

  return [ordered]@{
    configPath = $ConfigPath
    subscriptionId = [string]$SubscriptionId
    resourceGroup = [string]$ResourceGroup
    acrName = [string]$AcrName
    acrResourceGroup = if (Test-ConfigValuePresent -Value $AcrResourceGroup) { [string]$AcrResourceGroup } else { [string]$ResourceGroup }
    location = [string]$Location
    apiVersion = ([string]$ApiVersion).Trim()
    workspaceEndpoint = [string]$WorkspaceEndpoint
    project = [string]$Project
    tenantId = [string]$TenantId
    chatModel = [string]$ChatModel
    testPrompt = if (Test-ConfigValuePresent -Value $TestPrompt) { [string]$TestPrompt } else { '' }
    runReuseWindowMinutes = [int]$RunReuseWindowMinutes
    printAcrLogsOnFailure = [bool]$PrintAcrLogsOnFailure
    deleteInvestigationAfterTest = [bool]$DeleteInvestigationAfterTest
    forceToolImageRebuild = [bool]$ForceToolImageRebuild
  }
}

function Ensure-RunConfigFields {
  param(
    [string]$RunDir,
    [string]$SkillStagesDir,
    [string[]]$RequiredFields
  )

  $State = Load-RunState -RunDir $RunDir
  $PromptedConfigPath = Join-Path $RunDir 'prompted-config.json'
  $PromptedConfig = [ordered]@{}
  if (Test-Path $PromptedConfigPath) {
    try {
      $PromptedConfig = Get-Content $PromptedConfigPath -Raw | ConvertFrom-Json -AsHashtable
    } catch {
      $PromptedConfig = [ordered]@{}
    }
  }

  # DO NOT seed from $State.config - that's from a previous agent run and causes session pollution.
  # Only seed from the current run's prompted-config.json to maintain per-run isolation.
  $Seed = [ordered]@{}
  foreach ($k in $PromptedConfig.Keys) {
    $Seed[$k] = $PromptedConfig[$k]
  }

  # Config policy (post-stage-01):
  #   * Skill config.json present  -> it overrides defaults; missing required fields produce a Copilot input request.
  #   * Skill config.json missing  -> stage-01 must have collected everything; later stages NEVER request input.
  $SkillDir = $script:DiscoveryDeploySkillRoot
  $SkillConfigPath = Join-Path $SkillDir 'config.json'
  $SkillConfigExists = Test-Path $SkillConfigPath

  if ($SkillConfigExists) {
    $Loaded = Load-BuilderConfig -SkillStagesDir $SkillStagesDir -RequiredFields $RequiredFields -PromptForMissing -SeedConfig $Seed
  } else {
    # Verify stage-01 captured every field this stage needs; fail loudly if not.
    $Missing = @()
    foreach ($Field in $RequiredFields) {
      if (-not (Test-ConfigValuePresent -Value (Get-ConfigRawValue -ConfigObj $Seed -Field $Field))) {
        $Missing += $Field
      }
    }
    if ($Missing.Count -gt 0) {
      throw ("[config] prompted-config.json is missing required field(s): {0}. Re-run stage-01-init to collect inputs (skill config.json is absent so stage-01 is the single prompting point)." -f ($Missing -join ', '))
    }
    Write-Host ("[config] Using prompted-config.json from RunDir: {0}" -f $PromptedConfigPath)
    $Loaded = Load-BuilderConfig -SkillStagesDir $SkillStagesDir -RequiredFields $RequiredFields -SeedConfig $Seed -Quiet
  }

  $Merged = [ordered]@{}
  if ($State.ContainsKey('config') -and $State.config) {
    foreach ($k in $State.config.Keys) { $Merged[$k] = $State.config[$k] }
  }
  foreach ($k in $Loaded.Keys) {
    if ($Merged.Contains($k)) {
      if (Test-ConfigValuePresent -Value $Loaded[$k]) {
        $Merged[$k] = $Loaded[$k]
      }
    } else {
      $Merged[$k] = $Loaded[$k]
    }
  }
  foreach ($RunScopedField in @('buildMode','confirmSupercomputerNodepools')) {
    if ($Merged.Contains($RunScopedField)) { $Merged.Remove($RunScopedField) }
  }

  $State.config = $Merged
  $StatePath = Save-RunState -RunDir $RunDir -State $State
  ($Merged | ConvertTo-Json -Depth 50) | Set-Content $PromptedConfigPath -Encoding UTF8

  return [ordered]@{
    state = $State
    config = $Merged
    statePath = $StatePath
    promptedConfigPath = $PromptedConfigPath
  }
}

function New-DiscoveryToolUrl {
  param(
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$ToolName,
    [string]$ApiVersion
  )

  if ([string]::IsNullOrWhiteSpace($ApiVersion)) {
    throw 'API version is required to build the Discovery ARM URL.'
  }

  return ('https://management.azure.com/subscriptions/{0}/resourceGroups/{1}/providers/Microsoft.Discovery/tools/{2}?api-version={3}' -f $SubscriptionId, $ResourceGroup, $ToolName, $ApiVersion)
}

# ---------------------------------------------------------------------------
# Error logging & retry helpers
# ---------------------------------------------------------------------------

function Write-StageError {
  <#
  .SYNOPSIS Writes an error message to stderr AND appends to RunDir/error.log.
  #>
  param(
    [string]$RunDir,
    [string]$StageName,
    [string]$Message
  )

  $Timestamp = Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'
  $Line = "[$Timestamp] [$StageName] $Message"

  # Append to error.log inside the run directory
  if ($RunDir -and (Test-Path $RunDir)) {
    $LogPath = Join-Path $RunDir 'error.log'
    $Line | Out-File -FilePath $LogPath -Append -Encoding UTF8
  }

  # Emit without triggering the caller's ErrorActionPreference=Stop before
  # run-state failure details are persisted.
  Write-Error $Line -ErrorAction Continue
}

function Set-RunStateFailed {
  <#
  .SYNOPSIS Sets status=Failed and errorMessage in run-state.json for the given stage bag.
  #>
  param(
    [string]$RunDir,
    [string]$StageName,
    [string]$ErrorMessage
  )

  if (-not $RunDir -or -not (Test-Path (Join-Path $RunDir 'run-state.json'))) { return }
  try {
    $State = Load-RunState -RunDir $RunDir
    # Map stage names to the state bag they own
    switch ($StageName) {
      'stage-01' { $State.context['status'] = 'Failed'; $State.context['errorMessage'] = $ErrorMessage }
      'stage-02' { $State.build['status'] = 'Failed'; $State.build['errorMessage'] = $ErrorMessage }
      'stage-03' { $State.deploy['status'] = 'Failed'; $State.deploy['errorMessage'] = $ErrorMessage }
      'stage-04' { $State.deploy['agentStatus'] = 'Failed'; $State.deploy['agentErrorMessage'] = $ErrorMessage }
      'stage-05' {
        $State.validate['status'] = 'Failed'
        $State.validate['errorMessage'] = $ErrorMessage
        $State.validate['failedAt'] = (Get-Date).ToString('o')
      }
    }
    Save-RunState -RunDir $RunDir -State $State | Out-Null
  } catch {
    # Best-effort; don't mask the original error
    Write-Error "Warning: could not update run-state.json with failure info: $_"
  }
}

function Invoke-AzRestWithRetry {
  <#
  .SYNOPSIS Calls az rest with retry on transient failures (exit-code != 0 with 429/5xx patterns).
  .PARAMETER Method   HTTP method (get, put, post, delete, patch).
  .PARAMETER Url      Full URL for az rest.
  .PARAMETER Body     Optional body file path (prefixed with @).
  .PARAMETER MaxRetries  Number of retries after the initial attempt (default 2).
  .PARAMETER BaseDelaySec  Base delay in seconds for exponential backoff (default 5).
  .OUTPUTS  The raw stdout string from az rest on success.
  .NOTES  Throws on non-transient errors or after exhausting retries.
  #>
  param(
    [string]$Method,
    [string]$Url,
    [string]$Body,
    [int]$MaxRetries = 2,
    [int]$BaseDelaySec = 5
  )

  $TransientPattern = '(429|500|502|503|504|Timeout|timeout|ETIMEDOUT|connection reset|temporarily unavailable|ResourceNotFound)'

  for ($Attempt = 1; $Attempt -le ($MaxRetries + 1); $Attempt++) {
    $Args = @('rest', '--method', $Method, '--url', $Url, '--output', 'json', '--only-show-errors')
    if ($Body) {
      $Args += @('--body', $Body, '--headers', 'Content-Type=application/json')
    }
    $Raw = & az @Args 2>&1
    if ($LASTEXITCODE -eq 0) {
      return ($Raw | Out-String)
    }

    $ErrText = ($Raw | Out-String)
    $IsTransient = $ErrText -match $TransientPattern
    if (-not $IsTransient -or $Attempt -gt $MaxRetries) {
      throw $ErrText
    }

    $Delay = [math]::Min($BaseDelaySec * [math]::Pow(2, $Attempt - 1), 30)
    Write-Host ("[retry] Transient error on attempt $Attempt/$($MaxRetries + 1). Retrying in ${Delay}s...")
    Start-Sleep -Seconds $Delay
  }
}

function Save-RunState {
  param(
    [string]$RunDir,
    [hashtable]$State
  )

  $StatePath = Join-Path $RunDir 'run-state.json'
  $TempPath = "{0}.{1}.tmp" -f $StatePath, ([guid]::NewGuid().ToString('N'))
  try {
    ($State | ConvertTo-Json -Depth 50) | Set-Content $TempPath -Encoding UTF8
    Move-Item -Path $TempPath -Destination $StatePath -Force
  } finally {
    if (Test-Path $TempPath) { Remove-Item $TempPath -Force -ErrorAction SilentlyContinue }
  }
  return $StatePath
}

function Load-RunState {
  param([string]$RunDir)
  $StatePath = Join-Path $RunDir 'run-state.json'
  if (-not (Test-Path $StatePath)) {
    throw "Missing run state: $StatePath"
  }
  return (Get-Content $StatePath -Raw | ConvertFrom-Json -AsHashtable)
}

function Detect-DockerAvailable {
  $DockerAvailable = $false
  try {
    $null = docker --version 2>$null
    if ($LASTEXITCODE -eq 0) {
      $null = docker ps 2>$null
      if ($LASTEXITCODE -eq 0) {
        $DockerAvailable = $true
      }
    }
  } catch {
    $DockerAvailable = $false
  }
  return $DockerAvailable
}

function Resolve-AgentAndTool {
  param(
    [string]$AgentName,
    [string]$PublisherName,
    [hashtable]$Config
  )

  if ([string]::IsNullOrWhiteSpace($AgentName)) {
    throw 'AgentName input is required.'
  }

  if ($PublisherName) {
    Write-Host "[stage-01] -PublisherName is deprecated in the flat agents/ layout and is ignored."
  }

  $RepoRoot = Get-RepoRoot
  $AgentsRoot = Join-Path $RepoRoot 'agents'
  $AgentDir = Join-Path $AgentsRoot $AgentName

  if (-not (Test-Path (Join-Path $AgentDir 'agent.yaml'))) {
    throw "Agent '$AgentName' not found at '$AgentDir' (expected '$AgentsRoot/$AgentName/agent.yaml')."
  }

  $ToolsDir = Join-Path $AgentDir 'tools'
  $HasTool = $false
  $ToolDir = ''
  $DockerfilePath = ''
  $ToolYamlPath = ''
  $TempToolYaml = ''
  $ImageName = ''
  $ImageTag = ''
  $ImageRef = ''
  $ToolSkipReason = ''
  $ToolMeta = $null

  if (-not (Test-Path $ToolsDir)) {
    $ToolSkipReason = "Agent '$AgentName' does not ship a tool (no tools folder under $AgentDir)."
  } else {
    $ToolFolders = @(Get-ChildItem $ToolsDir -Directory)
    if ($ToolFolders.Count -eq 0) {
      $ToolSkipReason = "Tools directory exists but contains no sub-folders: $ToolsDir"
    } else {
      if ($ToolFolders.Count -eq 1) {
        $ToolDir = $ToolFolders[0].FullName
      } else {
        $ToolDir = ($ToolFolders | Sort-Object Name | Select-Object -First 1).FullName
      }

      $DockerfilePath = Join-Path $ToolDir 'Dockerfile'
      $ToolYamlPath = Join-Path $ToolDir 'tool.yaml'
      if (-not (Test-Path $DockerfilePath)) { throw "Missing Dockerfile at $DockerfilePath" }
      if (-not (Test-Path $ToolYamlPath)) { throw "Missing tool.yaml at $ToolYamlPath" }

      python -c "import yaml" 2>$null
      if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyyaml | Out-Null }
      $ToolMetaJson = python -c @'
import json, sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
acrs = []
skus = []
def walk(value):
    if isinstance(value, dict):
        image = value.get("image")
        if isinstance(image, dict) and image.get("acr"):
            acrs.append(str(image.get("acr")))
        if value.get("acr"):
            acrs.append(str(value.get("acr")))
        if "recommended_sku" in value:
            sku = value.get("recommended_sku")
            if isinstance(sku, list):
                skus.extend([str(x) for x in sku if x])
            elif sku:
                skus.append(str(sku))
        for child in value.values():
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)
walk(doc)
name = str(doc.get("name") or "")
print(json.dumps({"name": name, "acr": acrs[0] if acrs else "", "recommendedSkus": list(dict.fromkeys(skus))}))
'@ $ToolYamlPath
      if ($LASTEXITCODE -ne 0) { throw "Failed to parse tool.yaml metadata: $ToolYamlPath" }
      $ToolMeta = $ToolMetaJson | ConvertFrom-Json
      $AcrValue = [string]$ToolMeta.acr
      if (-not $AcrValue) { throw "tool.yaml has no image acr value at top-level or under infra[].image.acr" }
      if ($AcrValue -notmatch '/(?<image>[^:"\s]+):(?<tag>[^"\s]+)') {
        throw "Could not parse image:tag from acr value: $AcrValue"
      }

      $ImageName = $Matches['image']
      $ImageTag = $Matches['tag']
      $ImageRef = "$($Config.acrName).azurecr.io/$ImageName`:$ImageTag"
      $HasTool = $true
    }
  }

  $TempRoot = Join-Path $RepoRoot 'agents\tmp'
  if (-not (Test-Path $TempRoot)) { New-Item -ItemType Directory -Path $TempRoot | Out-Null }

  $AgentTempRoot = Join-Path $TempRoot $AgentName
  if (-not (Test-Path $AgentTempRoot)) { New-Item -ItemType Directory -Path $AgentTempRoot | Out-Null }

  $RunDir = $null
  $LatestRun = Get-ChildItem $AgentTempRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
  if ($LatestRun) {
    $Age = (New-TimeSpan -Start $LatestRun.LastWriteTime -End (Get-Date)).TotalMinutes
    if ($Age -le [int]$Config.runReuseWindowMinutes) {
      $RunDir = $LatestRun.FullName
    }
  }

  if (-not $RunDir) {
    $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $RunDir = Join-Path $AgentTempRoot $Stamp
    New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
  }

  if ($HasTool) {
    $TempToolYaml = Join-Path $RunDir 'tool.yaml'
    Copy-Item $ToolYamlPath $TempToolYaml -Force
  }

  return [ordered]@{
    repoRoot = $RepoRoot
    agentName = $AgentName
    publisherName = $PublisherName
    agentDir = $AgentDir
    hasTool = $HasTool
    toolSkipReason = $ToolSkipReason
    toolsDir = $ToolsDir
    toolDir = $ToolDir
    dockerfilePath = $DockerfilePath
    toolYamlPath = $ToolYamlPath
    tempToolYaml = $TempToolYaml
    imageName = $ImageName
    imageTag = $ImageTag
    imageRef = $ImageRef
    toolName = if ($ToolMeta -and $ToolMeta.name) { [string]$ToolMeta.name } else { $AgentName }
    recommendedSkus = if ($ToolMeta -and $ToolMeta.recommendedSkus) { @($ToolMeta.recommendedSkus) } else { @() }
    runDir = $RunDir
  }
}


function Invoke-DiscoveryDeployInit {
param(
  [Parameter(Mandatory = $true)][string]$AgentName,
  [string]$PublisherName,
  [ValidateSet('auto','remote','local')][string]$BuildMode = 'auto',
  [switch]$ConfirmSupercomputerNodepools
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Assert-PowerShell7OrNewer

$_RunDir = $null  # Will be set once we know the run directory

try {

Write-Host "[stage-01] Prerequisites"
foreach ($cmd in @('git','python','az')) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    throw "Missing required tool '$cmd'. Install it and retry stage-01-init."
  }
}

python -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "Python is installed but pip is unavailable. Install/repair pip and retry stage-01-init."
}

az version | Out-Null
$AccountShowRaw = az account show --query "{name:name, id:id}" -o table 2>&1
if ($LASTEXITCODE -ne 0) {
  throw ("[stage-01] Azure authentication check failed.`n" +
    "Action required: run 'az login' (and if needed 'az login --tenant <tenant-id>'), verify access to the target subscription, then rerun stage-01-init.`n" +
    "Command error: $($AccountShowRaw | Out-String)")
}

$DockerAvailable = Detect-DockerAvailable
Write-Host ("[stage-01] DockerAvailable={0}" -f $DockerAvailable)
$script:DiscoveryDeployDockerAvailableForInput = $DockerAvailable
$script:DiscoveryDeployBuildModeForInput = $BuildMode
$script:DiscoveryDeployAgentNameForInput = $AgentName
$SelectedBuildMode = ''

$SkillConfigPath = Join-Path $script:DiscoveryDeploySkillRoot 'config.json'
$SkillConfigExists = Test-Path $SkillConfigPath

# Stage-01 is the single config-input request point for the entire deployment.
# Collect every field used by stages 2-5 up front so later stages run non-interactively
# from run-local prompted-config.json (Mode B), while still letting skill config.json
# override defaults when present (Mode A).
$Stage01RequiredFields = @('subscriptionId','resourceGroup','acrName','location','workspaceEndpoint','project','tenantId','chatModel','forceToolImageRebuild')
if ($SkillConfigExists) {
  Write-Host ("[stage-01] Using skill config.json as overrides: {0}" -f $SkillConfigPath)
} else {
  Write-Host '[stage-01] skill config.json is missing; collecting all required values once for this run.'
}

$Config = Load-BuilderConfig -SkillStagesDir $PSScriptRoot -RequiredFields $Stage01RequiredFields -PromptForMissing

if ($DockerAvailable) {
  if ($BuildMode -in @('local','remote')) {
    Write-Host ("[stage-01] Using selected build mode: {0}" -f $BuildMode)
    $SelectedBuildMode = $BuildMode
  } else {
    Write-CopilotBuildModeInputRequest -AgentName $AgentName
    Write-Host '[stage-01] STATUS=InputRequired (build mode)'
    return
  }
} else {
  Write-Host '[stage-01] Docker is unavailable; using remote build mode for this run.'
  $SelectedBuildMode = 'remote'
}

$AccountSetRaw = az account set --subscription $Config.subscriptionId 2>&1
if ($LASTEXITCODE -ne 0) {
  throw ("[stage-01] Failed to select subscription '$($Config.subscriptionId)'.`n" +
    "Action required: ensure the subscription exists and your account has access (Reader+), then rerun stage-01-init.`n" +
    "Command error: $($AccountSetRaw | Out-String)")
}
Write-Host ("[stage-01] Loaded config: {0}" -f $Config.configPath)

$Resolved = Resolve-AgentAndTool -AgentName $AgentName -PublisherName $PublisherName -Config $Config
$_RunDir = $Resolved.runDir

$State = [ordered]@{
  config = $Config
  context = $Resolved
  dockerAvailable = $DockerAvailable
  buildMode = $SelectedBuildMode
  nodepoolConfirmed = [bool]$ConfirmSupercomputerNodepools
  build = @{}
  deploy = @{}
  validate = @{}
}

$StatePath = Save-RunState -RunDir $Resolved.runDir -State $State
$PromptedConfigPath = Join-Path $Resolved.runDir 'prompted-config.json'
($State.config | ConvertTo-Json -Depth 50) | Set-Content $PromptedConfigPath -Encoding UTF8
Write-Host ("RUN_DIR={0}" -f $Resolved.runDir)
Write-Host ("RUN_STATE={0}" -f $StatePath)
Write-Host ("PROMPTED_CONFIG={0}" -f $PromptedConfigPath)
if ($Resolved.hasTool) {
  Write-Host ("IMAGE_REF={0}" -f $Resolved.imageRef)
} else {
  Write-Host "[runner] Stage 2 and stage 3 skipped as the agent doesn't have any tool."
}
Write-Host '[stage-01] STATUS=Succeeded (1/5 init complete)'

} catch {
  $ErrMsg = $_.Exception.Message
  if ($ErrMsg -like 'CONFIG_INPUT_REQUIRED:*' -or $ErrMsg -like 'BUILD_MODE_INPUT_REQUIRED:*') {
    Write-Host ("[stage-01] STATUS=InputRequired ({0})" -f ($ErrMsg -replace '^(CONFIG_INPUT_REQUIRED|BUILD_MODE_INPUT_REQUIRED):\s*',''))
    throw
  }
  Write-StageError -RunDir $_RunDir -StageName 'stage-01' -Message $ErrMsg
  Set-RunStateFailed -RunDir $_RunDir -StageName 'stage-01' -ErrorMessage $ErrMsg
  Write-Host '[stage-01] STATUS=Failed'
  throw
}

}


function Invoke-DiscoveryDeployBuild {
param(
  [Parameter(Mandatory = $true)][string]$RunDir,
  [ValidateSet('auto','remote','local')][string]$BuildMode = 'auto',
  [switch]$ConfirmSupercomputerNodepools
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Assert-PowerShell7OrNewer

try {

$State = Load-RunState -RunDir $RunDir
$Config = $State.config
$Ctx = $State.context
$DockerAvailable = [bool]$State.dockerAvailable

if ($Ctx.ContainsKey('hasTool') -and -not [bool]$Ctx.hasTool) {
  $State.build['status'] = 'Skipped'
  $State.build['skipReason'] = 'agent has no tool'
  $State.build['completedAt'] = (Get-Date).ToString('o')
  $StatePath = Save-RunState -RunDir $RunDir -State $State
  Write-Host ("RUN_STATE={0}" -f $StatePath)
  Write-Host '[stage-02] STATUS=Skipped (agent has no tool)'
  return
}

function Test-AcrTagExists {
  param(
    [string]$AcrName,
    [string]$Repository,
    [string]$Tag
  )

  $TagsRaw = az acr repository show-tags --name $AcrName --repository $Repository --subscription $Config.subscriptionId -o tsv --only-show-errors 2>&1
  if ($LASTEXITCODE -ne 0) { return $false }
  return (($TagsRaw -split "`r?`n") -contains $Tag)
}

Write-SupercomputerNodepoolPlan -Context $Ctx
$NodepoolConfirmed = [bool]$ConfirmSupercomputerNodepools -or ($State.ContainsKey('nodepoolConfirmed') -and [bool]$State.nodepoolConfirmed)
Assert-SupercomputerNodepoolConfirmed -Confirmed $NodepoolConfirmed -Context $Ctx
if ($ConfirmSupercomputerNodepools -and (-not ($State.ContainsKey('nodepoolConfirmed') -and [bool]$State.nodepoolConfirmed))) {
  $State['nodepoolConfirmed'] = $true
  $StatePath = Save-RunState -RunDir $RunDir -State $State
  Write-Host ("RUN_STATE={0}" -f $StatePath)
}

$Mode = $BuildMode
  if ($Mode -eq 'auto') {
    $ConfiguredMode = ''
    if ($State.ContainsKey('buildMode') -and $State.buildMode) {
      $ConfiguredMode = ([string]$State.buildMode).Trim().ToLowerInvariant()
    }

    if ($ConfiguredMode -in @('local','remote')) {
      $Mode = $ConfiguredMode
    }

    if ($DockerAvailable) {
      if ($Mode -eq 'auto') {
        Write-CopilotBuildModeInputRequest -AgentName $Ctx.agentName
        Write-Host '[stage-02] STATUS=InputRequired (build mode)'
        return
      }
    }
    elseif ($Mode -eq 'auto') { $Mode = 'remote' }
  }

if ($Mode -eq 'local' -and -not $DockerAvailable) {
  throw 'Local build requested but Docker daemon is not available.'
}

Write-Host ("[stage-02] BuildMode={0}" -f $Mode)
$AcrResourceGroup = Get-AcrResourceGroup -Config $Config
az acr show --name $Config.acrName --resource-group $AcrResourceGroup --subscription $Config.subscriptionId --query id -o tsv --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) { throw "ACR '$($Config.acrName)' was not found in resource group '$AcrResourceGroup' for subscription '$($Config.subscriptionId)'. Set config.acrResourceGroup when the registry is not in config.resourceGroup." }
$ForceToolImageRebuild = [bool]$Config.forceToolImageRebuild

  if ((-not $ForceToolImageRebuild) -and (Test-AcrTagExists -AcrName $Config.acrName -Repository $Ctx.imageName -Tag $Ctx.imageTag)) {
  if (-not ($State.build.ContainsKey('completedAt') -and $State.build.completedAt)) {
    $State.build['completedAt'] = (Get-Date).ToString('o')
  }
  $State.build['mode'] = if ($Mode -ne 'auto') { $Mode } elseif ($State.build.ContainsKey('mode') -and $State.build.mode) { $State.build.mode } else { 'remote' }
  $State.build['status'] = 'Succeeded'
  Write-Host ("[stage-02] Existing build already completed; tag '{0}' is present in ACR. Skipping rebuild." -f $Ctx.imageTag)
  $StatePath = Save-RunState -RunDir $RunDir -State $State
  Write-Host ("RUN_STATE={0}" -f $StatePath)
  Write-Host ("IMAGE_REF={0}" -f $Ctx.imageRef)
  Write-Host '[stage-02] STATUS=Succeeded (2/5 build complete; reused existing image)'
  return
}

if ($Mode -eq 'local') {
  Write-Host ("[stage-02] Building image locally: {0}" -f $Ctx.imageRef)
  docker build -t $Ctx.imageRef -f $Ctx.dockerfilePath $Ctx.toolDir
  if ($LASTEXITCODE -ne 0) { throw 'Local docker build failed.' }

  $AcrLoginRaw = az acr login --name $Config.acrName 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw ("[stage-02] Failed to login to ACR '$($Config.acrName)'.`n" +
      "Action required: ensure Azure login is valid and your identity has permission on this registry (typically AcrPush). Then rerun stage-02-build.`n" +
      "Command error: $($AcrLoginRaw | Out-String)")
  }

  Write-Host ("[stage-02] Pushing image to ACR: {0}" -f $Ctx.imageRef)
  docker push $Ctx.imageRef
  if ($LASTEXITCODE -ne 0) {
    throw ("[stage-02] docker push failed for '$($Ctx.imageRef)'.`n" +
      "Action required: ensure your identity has AcrPush on registry '$($Config.acrName)' and retry stage-02-build.`n" +
      "If credentials expired, run 'az login' and retry.")
  }
} else {
  Write-Host ("[stage-02] Queueing remote ACR build for {0}..." -f $Ctx.imageRef)
  # Run az acr build with lowered ErrorActionPreference so that a CLI
  # telemetry crash (non-zero exit despite the build being queued) doesn't
  # terminate the script before we can check for the run ID.
  $SavedEAP = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $BuildRaw = (az acr build --registry $Config.acrName --resource-group $AcrResourceGroup --subscription $Config.subscriptionId --image "$($Ctx.imageName):$($Ctx.imageTag)" --file $Ctx.dockerfilePath --no-wait --output json $Ctx.toolDir 2>$null)
  $BuildExitCode = $LASTEXITCODE
  $ErrorActionPreference = $SavedEAP

  $RunId = ''
  try {
    $BuildObj = $BuildRaw | ConvertFrom-Json
    if ($BuildObj -and $BuildObj.runId) { $RunId = ([string]$BuildObj.runId).Trim() }
  } catch {}

  # Fallback: query ACR for the most recent run even if the CLI crashed.
  if (-not $RunId) {
    $SavedEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $FallbackRaw = (az acr task list-runs --registry $Config.acrName --subscription $Config.subscriptionId --top 1 --query "[0].runId" -o tsv --only-show-errors 2>$null)
    $ErrorActionPreference = $SavedEAP
    if ($LASTEXITCODE -eq 0 -and $FallbackRaw) { $RunId = ([string]$FallbackRaw).Trim() }
  }

  if (-not $RunId) {
    throw ("[stage-02] Failed to queue ACR remote build (exit code $BuildExitCode).`n" +
      "Action required: confirm Azure connectivity and permissions on ACR/resource group (AcrPush/AcrBuild or Contributor as required), then rerun stage-02-build.")
  }

  if ($BuildExitCode -ne 0) {
    Write-Host ("[stage-02] CLI exited with code {0} but run {1} was queued — continuing (likely telemetry crash)." -f $BuildExitCode, $RunId)
  }
  Write-Host ("[stage-02] Remote run queued: runId={0}" -f $RunId)
  $State.build.runId = $RunId
  $State.build.mode = $Mode
  $State.build.startedAt = (Get-Date).ToString('o')
  $State.build.status = 'Running'
  $StatePath = Save-RunState -RunDir $RunDir -State $State
  Write-Host ("RUN_STATE={0}" -f $StatePath)
  $Terminal = @('Succeeded','Failed','Canceled','Error','Timeout')
  $Deadline = (Get-Date).AddHours(2)
  $ConsecutivePollFailures = 0
  $MaxConsecutivePollFailures = 5
  while ($true) {
    if ((Get-Date) -gt $Deadline) { throw "Timed out waiting for ACR run $RunId." }
    Start-Sleep -Seconds 15
    $Status = $null
    try {
      # Temporarily lower ErrorActionPreference so a CLI process crash
      # (non-zero exit / stderr) doesn't become a terminating error that
      # bypasses this catch block and hits the outer catch.
      $SavedEAP = $ErrorActionPreference
      $ErrorActionPreference = 'Continue'
      $StatusRaw = (az acr task show-run --registry $Config.acrName --subscription $Config.subscriptionId --run-id $RunId --query status -o tsv --only-show-errors 2>$null)
      $ErrorActionPreference = $SavedEAP
      if ($LASTEXITCODE -eq 0 -and $StatusRaw) {
        $Status = ([string]$StatusRaw).Trim()
        $ConsecutivePollFailures = 0
      }
    } catch {
      $ErrorActionPreference = $SavedEAP
    }

    if (-not $Status) {
      $ConsecutivePollFailures++
      Write-Host ("[stage-02] Poll attempt failed ({0}/{1}) — CLI may have crashed" -f $ConsecutivePollFailures, $MaxConsecutivePollFailures)
      if ($ConsecutivePollFailures -ge $MaxConsecutivePollFailures) {
        Write-Host '[stage-02] Polling failed repeatedly; checking ACR directly for image tag...'
        if (Test-AcrTagExists -AcrName $Config.acrName -Repository $Ctx.imageName -Tag $Ctx.imageTag) {
          Write-Host '[stage-02] Image tag found in ACR — treating build as Succeeded despite CLI polling failures.'
          $Status = 'Succeeded'
          break
        } else {
          throw "ACR build polling failed $MaxConsecutivePollFailures consecutive times and image tag is not present in ACR."
        }
      }
      continue
    }
    Write-Host ("[stage-02] BuildStatus={0}" -f $Status)
    $State.build.status = $Status
    $StatePath = Save-RunState -RunDir $RunDir -State $State
    if ($Terminal -contains $Status) { break }
  }

  if ($Status -ne 'Succeeded') {
    if ($Config.printAcrLogsOnFailure) {
      $SavedEAP = $ErrorActionPreference
      $ErrorActionPreference = 'Continue'
      $LogRaw = az acr task logs --registry $Config.acrName --subscription $Config.subscriptionId --run-id $RunId --only-show-errors 2>&1
      $LogExitCode = $LASTEXITCODE
      $ErrorActionPreference = $SavedEAP
      if ($LogExitCode -eq 0) {
        $LogRaw | ForEach-Object { Write-Host $_ }
      } else {
        Write-Host ("[stage-02] Unable to stream ACR logs; continuing with failure handling. Error: {0}" -f (($LogRaw | Out-String).Trim()))
      }
    }
    throw "ACR build failed with status=$Status"
  }

  $State.build.runId = $RunId
}

if (-not (Test-AcrTagExists -AcrName $Config.acrName -Repository $Ctx.imageName -Tag $Ctx.imageTag)) {
  throw "Tag '$($Ctx.imageTag)' not visible in ACR repository '$($Ctx.imageName)'."
}

$State.build['mode'] = $Mode
$State.build['status'] = 'Succeeded'
$State.build['completedAt'] = (Get-Date).ToString('o')
$StatePath = Save-RunState -RunDir $RunDir -State $State
Write-Host ("RUN_STATE={0}" -f $StatePath)
Write-Host ("IMAGE_REF={0}" -f $Ctx.imageRef)
Write-Host '[stage-02] STATUS=Succeeded (2/5 build complete)'

} catch {
  $ErrMsg = $_.Exception.Message
  if ($ErrMsg -like 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED:*' -or $ErrMsg -like 'BUILD_MODE_INPUT_REQUIRED:*' -or $ErrMsg -like 'CONFIG_INPUT_REQUIRED:*') {
    Write-Host ("[stage-02] STATUS=InputRequired ({0})" -f ($ErrMsg -replace '^(SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED|BUILD_MODE_INPUT_REQUIRED|CONFIG_INPUT_REQUIRED):\s*',''))
    throw
  }
  Write-Host ("[stage-02] ERROR: {0}" -f $ErrMsg)
  Write-StageError -RunDir $RunDir -StageName 'stage-02' -Message $ErrMsg
  Set-RunStateFailed -RunDir $RunDir -StageName 'stage-02' -ErrorMessage $ErrMsg
  Write-Host '[stage-02] STATUS=Failed'
  throw
}

}


function Invoke-DiscoveryDeployTool {
param(
  [Parameter(Mandatory = $true)][string]$RunDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Assert-PowerShell7OrNewer

try {

Write-Host '[stage-03] Starting tool deployment...'

$ConfigResult = Ensure-RunConfigFields -RunDir $RunDir -SkillStagesDir $PSScriptRoot -RequiredFields @('subscriptionId','resourceGroup','acrName','location')
$State = $ConfigResult.state
$Config = $ConfigResult.config
$Ctx = $State.context

if ($Ctx.ContainsKey('hasTool') -and -not [bool]$Ctx.hasTool) {
  $State.deploy['toolStatus'] = 'Skipped'
  $State.deploy['toolSkipReason'] = 'agent has no tool'
  $State.deploy['completedAt'] = (Get-Date).ToString('o')
  $StatePath = Save-RunState -RunDir $RunDir -State $State
  Write-Host ("RUN_STATE={0}" -f $StatePath)
  Write-Host '[stage-03] STATUS=Skipped (agent has no tool)'
  return
}

(Get-Content $Ctx.tempToolYaml) -replace '\{name\}\.azurecr\.io', "$($Config.acrName).azurecr.io" | Set-Content $Ctx.tempToolYaml -Encoding UTF8

python -c "import yaml" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyyaml | Out-Null }

$TempToolJson = Join-Path $RunDir 'tool.json'
python -c "import yaml,json,sys; json.dump(yaml.safe_load(open(sys.argv[1], encoding='utf-8')), open(sys.argv[2], 'w', encoding='utf-8'), indent=2)" $Ctx.tempToolYaml $TempToolJson

$ToolName = (python -c "import yaml,sys,re; n=yaml.safe_load(open(sys.argv[1], encoding='utf-8')).get('name',''); print(re.sub(r'[^a-z0-9]','',n.lower()))" $Ctx.tempToolYaml).Trim()
if (-not $ToolName) { throw 'tool.yaml has no usable name field.' }

$Category = (python -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1], encoding='utf-8')).get('category','') or '')" $Ctx.tempToolYaml).Trim()
if (-not $Category) { $Category = 'General' }

$DefinitionContent = Get-Content $TempToolJson -Raw | ConvertFrom-Json
$ArmBody = @{
  location = $Config.location
  tags = @{ category = $Category }
  properties = @{
    version = '1.0.0'
    definitionContent = $DefinitionContent
  }
} | ConvertTo-Json -Depth 30

$ArmBodyPath = Join-Path $RunDir 'arm-body.json'
$ArmBody | Set-Content $ArmBodyPath -Encoding UTF8

$Url = New-DiscoveryToolUrl -SubscriptionId $Config.subscriptionId -ResourceGroup $Config.resourceGroup -ToolName $ToolName -ApiVersion $Config.apiVersion

# Pre-check: if tool already exists and is in a non-terminal (in-flight) state, skip the PUT
# and let the polling loop below wait for it to finish.
$InFlightStates = @('Accepted', 'Creating', 'Updating', 'Deleting', 'Running')
$SkipPut = $false
try {
  $PreCheckRaw = Invoke-AzRestWithRetry -Method get -Url $Url
  $PreCheckResult = $PreCheckRaw | ConvertFrom-Json
  $ExistingState = [string]$PreCheckResult.properties.provisioningState
  if ($InFlightStates -contains $ExistingState) {
    Write-Host ("[stage-03] Tool is already in state '{0}' — skipping PUT and waiting for it to complete." -f $ExistingState)
    $SkipPut = $true
  }
} catch {
  # Tool does not exist yet (404) or GET failed transiently — proceed with PUT
}

if (-not $SkipPut) {
  try {
    $PutRaw = Invoke-AzRestWithRetry -Method put -Url $Url -Body "@$ArmBodyPath"
  } catch {
    $PutText = $_.Exception.Message
    throw ("[stage-03] Tool ARM deployment request failed.`n" +
      "Action required: ensure Azure login is valid and your identity has permissions on resource group '$($Config.resourceGroup)' (typically Contributor to create Microsoft.Discovery/tools). Then rerun stage-03-deploy-tool.`n" +
      "Command error: $PutText")
  }
}

$Terminal = @('Succeeded','Failed','Canceled')
$Deadline = (Get-Date).AddMinutes(30)
$WaitStarted = Get-Date
$PollIteration = 0
Write-Host '[stage-03] Polling tool provisioning (interval=15s; maxWait=30m)'
while ($true) {
  if ((Get-Date) -gt $Deadline) { throw 'Timed out waiting for tool provisioning (timeout: 30 minutes).' }
  try {
    $GetRaw = Invoke-AzRestWithRetry -Method get -Url $Url
  } catch {
    throw ("[stage-03] Failed while polling tool provisioning state.`n" +
      "Action required: verify Azure connectivity and access to resource group '$($Config.resourceGroup)', then rerun stage-03-deploy-tool.`n" +
      "Command error: $($_.Exception.Message)")
  }
  $Result = $GetRaw | ConvertFrom-Json
  $StateNow = [string]$Result.properties.provisioningState
  $PollIteration++
  $ElapsedSec = [int]((Get-Date) - $WaitStarted).TotalSeconds
  Write-Host ("[stage-03] [{0}] ToolState={1} (poll #{2}, elapsed={3}s)" -f (Get-Date -Format 'HH:mm:ss'), $StateNow, $PollIteration, $ElapsedSec)
  if ($Terminal -contains $StateNow) {
    if ($StateNow -ne 'Succeeded') { throw "Tool provisioning ended in state '$StateNow'." }
    break
  }
  
  Start-Sleep -Seconds 15
}

$ToolResourceId = "/subscriptions/$($Config.subscriptionId)/resourceGroups/$($Config.resourceGroup)/providers/Microsoft.Discovery/tools/$ToolName"

$State.deploy.toolName = $ToolName
$State.deploy.category = $Category
$State.deploy.toolResourceId = $ToolResourceId
$State.deploy.toolProvisioningState = 'Succeeded'
$State.deploy.completedAt = (Get-Date).ToString('o')
$State.deploy.status = 'Succeeded'
$StatePath = Save-RunState -RunDir $RunDir -State $State

Write-Host ("RUN_STATE={0}" -f $StatePath)
Write-Host '[stage-03] STATUS=Succeeded (3/5 deploy-tool complete)'
Write-Host ("TOOL_RESOURCE_ID={0}" -f $ToolResourceId)

} catch {
  $ErrMsg = $_.Exception.Message
  Write-Host ("[stage-03] ERROR: {0}" -f $ErrMsg)
  Write-StageError -RunDir $RunDir -StageName 'stage-03' -Message $ErrMsg
  Set-RunStateFailed -RunDir $RunDir -StageName 'stage-03' -ErrorMessage $ErrMsg
  Write-Host '[stage-03] STATUS=Failed'
  throw
}

}


function Invoke-DiscoveryDeployAgent {
param(
  [Parameter(Mandatory = $true)][string]$RunDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Assert-PowerShell7OrNewer

try {

$ConfigResult = Ensure-RunConfigFields -RunDir $RunDir -SkillStagesDir $PSScriptRoot -RequiredFields @('subscriptionId','resourceGroup','workspaceEndpoint','project','tenantId','chatModel')
$State = $ConfigResult.state
$Config = $ConfigResult.config
$Ctx = $State.context

$HasTool = $Ctx.ContainsKey('hasTool') -and [bool]$Ctx.hasTool
if ($HasTool) {
  if (-not $State.deploy.toolResourceId) {
    throw 'ToolResourceId missing in run-state.json. Run stage-03-deploy-tool first.'
  }

  $ToolProvisioningState = [string]''
  if ($State.deploy.ContainsKey('toolProvisioningState') -and $State.deploy.toolProvisioningState) {
    $ToolProvisioningState = [string]$State.deploy.toolProvisioningState
  }

  if ($ToolProvisioningState -ne 'Succeeded') {
    throw ("Tool provisioning is not complete (current state: '{0}'). Run stage-03-deploy-tool until it reaches Succeeded before running stage-04-deploy-agent." -f $ToolProvisioningState)
  }
} else {
  Write-Host "[runner] Stage 2 and stage 3 skipped as the agent doesn't have any tool."
}

$AgentYamlSource = Join-Path $Ctx.agentDir 'agent.yaml'
if (-not (Test-Path $AgentYamlSource)) { throw "Missing agent.yaml at $AgentYamlSource" }

$TempAgentYaml = Join-Path $RunDir 'agent.yaml'
Copy-Item $AgentYamlSource $TempAgentYaml -Force

$PatchPy = Join-Path $RunDir 'patch_agent_yaml.py'
@'
import sys, yaml
path, chat_model = sys.argv[1], sys.argv[2]
tool_id = sys.argv[3] if len(sys.argv) > 3 else ''
doc = yaml.safe_load(open(path, encoding='utf-8'))
if not isinstance(doc, dict):
  raise SystemExit(f"Invalid YAML payload: {path}")

model = doc.get('model') or {}
if isinstance(model, dict):
  model_id = str(model.get('id', '')).strip()
  if (not model_id) or model_id == '{{CHAT-MODEL}}':
    model['id'] = chat_model
  doc['model'] = model

if tool_id:
  disc = doc.get('discoveryExtensions') or {}
  tools = disc.get('tools') or []
  if not isinstance(tools, list):
    tools = []

  tool_leaf = tool_id.rsplit('/', 1)[-1].lower()
  replaced_any = False
  deduped = []
  seen_leaves = set()
  for item in tools:
    if not isinstance(item, dict):
      continue
    current = str(item.get('toolId', '')).strip()
    current_leaf = current.rsplit('/', 1)[-1].lower() if current else ''
    is_placeholder = current.startswith('{{') and current.endswith('}}')
    # Replace placeholders OR any toolId whose leaf name matches the newly deployed tool
    # (handles hard-coded foreign-subscription toolIds in source agent.yaml)
    if is_placeholder or current_leaf == tool_leaf:
      if tool_leaf in seen_leaves:
        continue
      item['toolId'] = tool_id
      if 'confirmation' not in item:
        item['confirmation'] = 'Disabled'
      deduped.append(item)
      seen_leaves.add(tool_leaf)
      replaced_any = True
    else:
      if current_leaf and current_leaf in seen_leaves:
        continue
      deduped.append(item)
      if current_leaf:
        seen_leaves.add(current_leaf)

  if not replaced_any:
    deduped.append({'toolId': tool_id, 'confirmation': 'Disabled'})

  disc['tools'] = deduped
  doc['discoveryExtensions'] = disc

with open(path, 'w', encoding='utf-8') as f:
  yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=False)
'@ | Set-Content $PatchPy -Encoding UTF8

python -c "import yaml, requests" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyyaml requests | Out-Null }

$PatchArgs = @($PatchPy, $TempAgentYaml, $Config.chatModel)
if ($HasTool) { $PatchArgs += $State.deploy.toolResourceId }
python @PatchArgs
if ($LASTEXITCODE -ne 0) { throw 'Failed to patch temp agent.yaml' }

$CurrentTenant = (az account show --query tenantId -o tsv --only-show-errors).Trim()
if ($CurrentTenant -ne $Config.tenantId) {
  az login --tenant $Config.tenantId | Out-Null
  az account set --subscription $Config.subscriptionId | Out-Null
}

$DeployConfigPath = Join-Path $RunDir 'agent-deploy-config.json'
$DeployConfig = @{
  workspaceEndpoint = $Config.workspaceEndpoint
  apiVersion = $Config.apiVersion
  project = $Config.project
  model = $Config.chatModel
  tenantId = $Config.tenantId
  resourceGroup = "/subscriptions/$($Config.subscriptionId)/resourceGroups/$($Config.resourceGroup)"
}
if ($HasTool) { $DeployConfig.corePythonToolId = $State.deploy.toolResourceId }
$DeployConfig | ConvertTo-Json -Depth 8 | Set-Content $DeployConfigPath -Encoding UTF8

$DeployScript = Join-Path $RunDir 'stage-04a-deploy-agent.py'
@'
#!/usr/bin/env python3
"""Internal helper for Stage 4: deploy one Discovery agent YAML and optionally verify."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

try:
    import requests
    import yaml
except ImportError:
    print("ERROR: Missing dependencies. Install with: pip install pyyaml requests")
    sys.exit(1)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise RuntimeError(f"Invalid YAML payload: {path}")
    return doc


def resolve_variables(obj, config: dict):
    if isinstance(obj, str):
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(config.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, dict):
        return {k: resolve_variables(v, config) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_variables(v, config) for v in obj]
    return obj


def get_token(config: dict) -> str:
    az_exe = shutil.which("az") or shutil.which("az.cmd")
    if not az_exe:
        raise RuntimeError("Azure CLI executable not found in PATH")

    cmd = [
        az_exe,
        "account",
        "get-access-token",
        "--resource",
        "https://discovery.azure.com",
        "--query",
        "accessToken",
        "-o",
        "tsv",
        "--only-show-errors",
    ]
    env = os.environ.copy()
    env["AZURE_CORE_COLLECT_TELEMETRY"] = "no"

    last_error = ""
    for attempt in range(1, 4):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=90,
                env=env,
            )
            token = result.stdout.strip()
            if token:
                return token
            last_error = "token command returned empty token"
        except subprocess.TimeoutExpired:
            last_error = "az account get-access-token timed out"
        except subprocess.CalledProcessError as exc:
            last_error = (exc.stderr or exc.stdout or str(exc)).strip()
        except KeyboardInterrupt:
            # Defensive guard for rare subprocess/thread interrupt surfacing.
            last_error = "token command interrupted"

        if attempt < 3:
            time.sleep(2 * attempt)

    raise RuntimeError(f"failed to get access token after retries: {last_error}")


def build_prompt_definition(doc: dict) -> dict:
    out = {"kind": "prompt"}

    model = doc.get("model", {})
    if isinstance(model, str):
        out["model"] = model
    elif isinstance(model, dict):
        out["model"] = model.get("id", "")
        options = model.get("options", {})
        if "temperature" in options:
            out["temperature"] = options["temperature"]

    if "instructions" in doc:
        out["instructions"] = doc["instructions"]

    output_schema = doc.get("outputSchema")
    if output_schema:
        props = output_schema.get("properties", {})
        json_props = {}
        required = []
        for name, prop in props.items():
            json_props[name] = {
                "type": prop.get("kind", "string"),
                "description": prop.get("description", ""),
            }
            if prop.get("required", True):
                required.append(name)

        out["text"] = {
            "format": {
                "type": "json_schema",
                "name": f"{doc['name']}Output",
                "description": doc.get("description", ""),
                "schema": {
                    "type": "object",
                    "properties": json_props,
                    "required": required,
                    "additionalProperties": False,
                },
                "strict": output_schema.get("strict", True),
            }
        }

    return out


def build_payload(doc: dict) -> dict:
    payload = {"name": doc["name"]}

    extensions = doc.get("discoveryExtensions", {})
    kind = doc.get("kind", "prompt")

    if kind == "workflow":
        raise RuntimeError("Workflow agents are not supported by this deploy helper. Use prompt-agent YAML.")

    if "humanInTheLoop" in extensions:
        payload["humanInTheLoop"] = extensions["humanInTheLoop"]
    if "tools" in extensions:
        payload["tools"] = extensions["tools"]
    if "knowledgeBases" in extensions:
        payload["knowledgeBases"] = extensions["knowledgeBases"]

    remaining = {
        k: v
        for k, v in extensions.items()
        if k not in {"humanInTheLoop", "tools", "knowledgeBases"}
    }
    if remaining:
        payload["discoveryExtensions"] = remaining

    foundry = {"description": doc.get("description", "")}
    foundry["definition"] = build_prompt_definition(doc)
    payload["foundryDetails"] = foundry

    return payload


def upsert_agent(payload: dict, config: dict, token: str) -> dict:
    url = f"{config['workspaceEndpoint']}/projects/{config['project']}:upsertAgent?api-version={config['apiVersion']}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # Retry logic for transient errors (timeout, connection issues, 5xx)
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            body = resp.json() if "application/json" in resp.headers.get("content-type", "") else resp.text
            
            # Retry on 5xx server errors and specific transient conditions
            if resp.status_code >= 500 and attempt < max_attempts:
                time.sleep(min(2 * attempt, 8))
                continue
            
            return {"status_code": resp.status_code, "body": body, "headers": dict(resp.headers)}
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as ex:
            if attempt < max_attempts:
                time.sleep(min(2 * attempt, 8))
                continue
            raise
    
    return {"status_code": 0, "body": {}, "headers": {}}


def poll_operation(op_url: str, config: dict, attempts: int = 20, interval_seconds: int = 15) -> str:
    import datetime
    start = time.time()
    print(
        f"  Polling agent operation (interval={interval_seconds}s, max={attempts} attempts / {attempts * interval_seconds}s)",
        flush=True,
    )
    for i in range(1, attempts + 1):
        time.sleep(interval_seconds)
        elapsed = int(time.time() - start)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            token = get_token(config)
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            resp = requests.get(op_url, headers=headers, timeout=60)
            if resp.status_code != 200:
                print(f"  [{ts}] poll #{i} HTTP {resp.status_code} (elapsed={elapsed}s)", flush=True)
                continue
            status = resp.json().get("status")
            print(f"  [{ts}] poll #{i} status={status} (elapsed={elapsed}s)", flush=True)
            if status in ("Succeeded", "Failed", "Canceled"):
                return status
        except requests.exceptions.RequestException as ex:
            print(f"  [{ts}] poll #{i} request error: {ex} (elapsed={elapsed}s)", flush=True)
            continue
    return "Timeout"


def get_agent_state(name: str, config: dict, token: str) -> str:
    url = f"{config['workspaceEndpoint']}/projects/{config['project']}/agents/{name}?api-version={config['apiVersion']}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return "Unknown"
    body = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
    if isinstance(body, dict):
        return body.get("provisioningState", "Unknown")
    return "Unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal helper to deploy one Discovery agent YAML")
    parser.add_argument("path", help="YAML file to deploy")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--verify", action="store_true", help="Poll async operation and print agent state")
    args = parser.parse_args()

    config = load_json(args.config)
    print(f"Config: endpoint={config['workspaceEndpoint']}, project={config['project']}")

    doc = resolve_variables(load_yaml(args.path), config)
    payload = build_payload(doc)
    name = payload["name"]

    print("Found 1 file(s) to deploy:")
    print(f"  - {args.path}")

    print(f"\nDeploying {name}...", end=" ", flush=True)
    token = get_token(config)
    result = upsert_agent(payload, config, token)

    if result["status_code"] not in (200, 202):
        print(f"FAILED (HTTP {result['status_code']})")
        return 1

    body = result["body"] if isinstance(result["body"], dict) else {}
    print(f"ACCEPTED (HTTP {result['status_code']}) id={body.get('id', '')}")

    if args.verify:
        op_url = result["headers"].get("operation-location", "")
        if op_url:
            op_status = poll_operation(op_url, config)
            print(f"  Final operation status: {op_status}")
            if op_status != "Succeeded":
                return 1

        agent_state = get_agent_state(name, config, get_token(config))
        print(f"  Agent state: {agent_state}")

    print("\nDone: 1 succeeded, 0 failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

'@ | Set-Content $DeployScript -Encoding UTF8
python $DeployScript --config $DeployConfigPath --verify $TempAgentYaml
if ($LASTEXITCODE -ne 0) { throw 'Agent deployment failed.' }

$State.deploy.tempAgentYaml = $TempAgentYaml
$State.deploy.deployConfigPath = $DeployConfigPath
$State.deploy.agentCompletedAt = (Get-Date).ToString('o')
$StatePath = Save-RunState -RunDir $RunDir -State $State

Write-Host ("RUN_STATE={0}" -f $StatePath)
Write-Host '[stage-04] STATUS=Succeeded (4/5 deploy-agent complete)'
Write-Host ("TEMP_AGENT_YAML={0}" -f $TempAgentYaml)

} catch {
  $ErrMsg = $_.Exception.Message
  Write-StageError -RunDir $RunDir -StageName 'stage-04' -Message $ErrMsg
  Set-RunStateFailed -RunDir $RunDir -StageName 'stage-04' -ErrorMessage $ErrMsg
  Write-Host '[stage-04] STATUS=Failed'
  throw
}

}


function Invoke-DiscoveryDeployValidation {
param(
  [Parameter(Mandatory = $true)][string]$RunDir,
  [string]$Prompt
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Assert-PowerShell7OrNewer

try {

$ConfigResult = Ensure-RunConfigFields -RunDir $RunDir -SkillStagesDir $PSScriptRoot -RequiredFields @()
$State = $ConfigResult.state
$Config = $ConfigResult.config

if (-not $State.deploy.deployConfigPath) {
  throw 'deployConfigPath missing in run-state.json. Run stage-04-deploy-agent first.'
}
if (-not $State.deploy.tempAgentYaml) {
  throw 'tempAgentYaml missing in run-state.json. Run stage-04-deploy-agent first.'
}

$EffectivePrompt = $Prompt
if ([string]::IsNullOrWhiteSpace($EffectivePrompt)) {
  if ($State.context.ContainsKey('hasTool') -and -not [bool]$State.context.hasTool) {
    $EffectivePrompt = 'What can you do?'
    Write-Host 'VALIDATION_PROMPT=What can you do?'
  } else {
    $ConfigTestPrompt = Get-ConfigRawValue -ConfigObj $Config -Field 'testPrompt'
    if (Test-ConfigValuePresent -Value $ConfigTestPrompt) {
      $EffectivePrompt = [string]$ConfigTestPrompt
      Write-Host 'VALIDATION_PROMPT_SOURCE=config.testPrompt'
    } else {
      $toolName = if ($State.context.ContainsKey('toolName') -and $State.context.toolName) { [string]$State.context.toolName } else { [string]$State.context.agentName }
      $toolDir = if ($State.context.ContainsKey('toolDir') -and $State.context.toolDir) { [string]$State.context.toolDir } else { '' }
      Write-Host 'VALIDATION_PROMPT_INPUT_REQUIRED=true'
      Write-Host 'VALIDATION_PROMPT_INPUT_FORMAT=copilot'
      Write-Host '--- COPILOT VALIDATION PROMPT REQUEST ---'
      Write-Host 'Generate a short, concrete validation prompt for this deployed Discovery agent and rerun validate with -ValidationPrompt "<prompt>". Do not ask the user for this prompt and do not store it in config.json.'
      Write-Host ("Agent: {0}" -f ([string]$State.context.agentName))
      Write-Host ("Tool: {0}" -f $toolName)
      if ($toolDir) { Write-Host ("Tool directory: {0}" -f $toolDir) }
      Write-Host 'Prompt requirements: exercise the deployed agent/tool lightly, require a concise answer, avoid long-running analysis, and include enough domain-specific detail to prove the correct tool container is reachable.'
      Write-Host ("Suggested rerun command: pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-agent-deployer\scripts\deploy-discovery-agent.ps1 -RunDir `"{0}`" -Stage validate -ValidationPrompt `"<generated prompt>`"" -f $RunDir)
      Write-Host '--- END COPILOT VALIDATION PROMPT REQUEST ---'
      throw 'VALIDATION_PROMPT_INPUT_REQUIRED: Generate a validation prompt from the deployed agent/tool context and rerun validate with -ValidationPrompt.'
    }
  }
}

python -c "import yaml, requests" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyyaml requests | Out-Null }

$TempAgentName = (python -c "import yaml,sys; d=yaml.safe_load(open(sys.argv[1], encoding='utf-8')); print((d.get('name') or '').strip())" $State.deploy.tempAgentYaml).Trim()
if (-not $TempAgentName) { throw 'Could not resolve agent name from temp agent.yaml' }

$ValidatePy = Join-Path $RunDir 'validation_test.py'
@'
import atexit, json, os, random, re, signal, subprocess, sys, time
import requests

if hasattr(sys.stdout, "reconfigure"):
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
  sys.stderr.reconfigure(encoding="utf-8", errors="replace")

cfg_path, agent_name, prompt, delete_after, result_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
cfg = json.load(open(cfg_path, encoding='utf-8'))

# Track all investigation URLs created during this run for cleanup on interruption
_created_inv_urls = []
_cleanup_done = False

def _cleanup_investigations():
  global _cleanup_done
  if _cleanup_done or str(delete_after).lower() != "true":
    return
  _cleanup_done = True
  for url in _created_inv_urls:
    try:
      t = token()
      requests.delete(url, headers=headers(t), timeout=15)
      print(f"[cleanup] Deleted investigation: {url.split('/investigations/')[1].split('?')[0]}", flush=True)
    except Exception as ex:
      print(f"[cleanup] Warning: could not delete investigation: {ex}", flush=True)

_interrupted = False

def _signal_handler(signum, frame):
  global _interrupted
  if _interrupted:
    # Second signal — force exit
    print(f"\n[cleanup] Forced exit on second signal {signum}", flush=True)
    _cleanup_investigations()
    sys.exit(1)
  _interrupted = True
  print(f"\n[cleanup] Received signal {signum} — will finish current poll cycle then clean up.", flush=True)

atexit.register(_cleanup_investigations)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def token():
  token_cmd = cfg.get("tokenCommand", "az account get-access-token --resource https://discovery.azure.com --query accessToken -o tsv")
  res = subprocess.run(token_cmd, shell=True, capture_output=True, text=True, check=True)
  t = res.stdout.strip()
  if not t:
    raise RuntimeError("token command returned empty token")
  return t

def headers(t):
  return {"Authorization": f"Bearer {t}", "Content-Type": "application/json", "Accept": "application/json"}

http_timeout = int(os.getenv("VALIDATION_HTTP_TIMEOUT_SECONDS", "45"))
http_retries = int(os.getenv("VALIDATION_HTTP_RETRIES", "4"))

def call_with_retries(method, url, **kwargs):
  last = None
  for attempt in range(1, http_retries + 1):
    try:
      return requests.request(method, url, timeout=http_timeout, **kwargs)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as ex:
      last = ex
      if attempt == http_retries:
        raise
      time.sleep(min(2 * attempt, 8))
  if last:
    raise last

base = cfg["workspaceEndpoint"].rstrip("/")
api = cfg["apiVersion"]
project = cfg["project"]
safe = re.sub(r"[^a-z0-9-]", "-", agent_name.lower())[:8].strip("-") or "agent"

# Use deterministic investigation naming (timestamp-based, not random)
# This allows retries to reuse the same investigation instead of creating duplicates.
# Investigation names must be 3-24 chars: "test-" (5) + safe (<=8) + "-" (1) + suffix (10) = 24 max.
timestamp_suffix = int(time.time())
inv = f"test-{safe}-{timestamp_suffix}"[:24].rstrip("-")

t = token()
inv_url = f"{base}/projects/{project}/investigations/{inv}?api-version={api}"
call_with_retries("DELETE", inv_url, headers=headers(t))
create = call_with_retries("PUT", inv_url, headers=headers(t), json={"description": "Post-deploy validation", "displayName": f"Validation Test {agent_name}"})
if create.status_code not in (200, 201):
  raise RuntimeError(f"investigation create failed: HTTP {create.status_code} {create.text[:300]}")
_created_inv_urls.append(inv_url)

conv = call_with_retries("POST", f"{base}/conversations?api-version={api}", headers=headers(t), json={
  "displayName": f"validation-{agent_name}",
  "investigationName": f"/projects/{project}/investigations/{inv}",
  "projectName": project,
})
conv.raise_for_status()
conv_name = conv.json().get("name")
if not conv_name:
  raise RuntimeError("conversation create returned no name")

def wait_for_completion(conversation_name, text_prompt, wait_seconds):
  t_local = token()
  resp = call_with_retries("POST", f"{base}/conversations/{conversation_name}/openai/responses?api-version={api}", headers=headers(t_local), json={
    "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": text_prompt}]}],
    "agent": {"type": "agent_reference", "name": agent_name},
  })
  resp.raise_for_status()
  body_local = resp.json()
  rid_local = body_local.get("id")
  status_local = body_local.get("status", "")

  terminal = {"completed", "failed", "cancelled", "expired"}
  deadline = time.time() + wait_seconds
  poll_count = 0
  start_time = time.time()
  while status_local not in terminal:
    if _interrupted:
      print("[validation] Interrupted — stopping poll loop.", flush=True)
      break
    if time.time() > deadline:
      raise TimeoutError(f"Timed out waiting {wait_seconds} seconds for response completion")
    time.sleep(30)
    poll_count += 1
    elapsed = int(time.time() - start_time)
    print(f"[validation] Polling attempt {poll_count}, elapsed {elapsed}s, status={status_local}...", flush=True)
    t_local = token()
    poll = call_with_retries("GET", f"{base}/conversations/{conversation_name}/openai/responses/{rid_local}?api-version={api}", headers=headers(t_local))
    poll.raise_for_status()
    body_local = poll.json()
    status_local = body_local.get("status", "")

  return body_local, status_local

wait_seconds = int(os.getenv("VALIDATION_WAIT_SECONDS", "900"))
fallback_prompt = os.getenv("VALIDATION_FALLBACK_PROMPT", "Reply with exactly OK")
max_retries = int(os.getenv("VALIDATION_MAX_RETRIES", "3"))

def write_result(status_value, investigation, response_status, text, semantic_failure=False):
  with open(result_path, "w", encoding="utf-8") as f:
    json.dump({
      "status": status_value,
      "investigation": investigation,
      "responseStatus": response_status,
      "semanticFailure": semantic_failure,
      "outputText": text or "",
    }, f, indent=2)

# Retry logic: if timeout or incomplete response, delete investigation and retry
body = None
status = None
for attempt in range(1, max_retries + 1):
  try:
    body, status = wait_for_completion(conv_name, prompt if attempt == 1 else fallback_prompt, wait_seconds)
    texts = []
    for item in body.get("output", []):
      if isinstance(item, dict) and item.get("type") == "message":
        for c in item.get("content", []):
          if isinstance(c, dict) and c.get("text"):
            texts.append(c["text"])
    joined = "\n".join(texts).strip()
    
    blocked_patterns = [
      r"\bblocked\b",
      r"\bfailed\b",
      r"\berror\b",
      r"\bexception\b",
      r"modulenotfounderror",
      r"no module named",
      r"cannot execute",
      r"can't execute",
      r"unable to proceed",
      r"what i need to proceed",
      r"tool connectivity check attempted but failed",
      r"execution result:\s*\*\*400 bad request\*\*",
      r"invalidnodepool",
      r"nodepoolcapabilityerror",
      r"bad request",
      r"job submission",
    ]
    reported_failure = any(re.search(pattern, joined, flags=re.IGNORECASE) for pattern in blocked_patterns)

    if status == "completed" and joined and reported_failure:
      write_result("failed", inv, status, joined, True)
      print(f"VALIDATION_INVESTIGATION={inv}", flush=True)
      print("VALIDATION_STATUS=failed", flush=True)
      print(f"VALIDATION_OUTPUT_PREVIEW={joined[:300]}", flush=True)
      raise RuntimeError("Validation response completed but indicates the investigation is blocked or failed. Read validation-result.json for the final state.")

    # Success criteria: completed status, non-empty output, and no explicit failure report
    if status == "completed" and joined:
      write_result("passed", inv, status, joined, False)
      print(f"VALIDATION_INVESTIGATION={inv}", flush=True)
      print(f"VALIDATION_STATUS={status}", flush=True)
      print(f"VALIDATION_OUTPUT_PREVIEW={joined[:300]}", flush=True)
      break
    elif attempt < max_retries:
      print(f"[validation] Attempt {attempt}: status={status}, output_len={len(joined)} - deleting investigation and retrying...", flush=True)
      # Delete investigation before retry to clean up state
      try:
        t = token()
        call_with_retries("DELETE", inv_url, headers=headers(t))
        print(f"[validation] Investigation deleted: {inv}", flush=True)
      except Exception as ex:
        print(f"[validation] Warning: could not delete investigation: {ex}", flush=True)
      # Create new investigation for retry
      time.sleep(1)
      t = token()
      call_with_retries("DELETE", inv_url, headers=headers(t))
      inv_new = f"test-{safe}-{int(time.time())}"[:24].rstrip("-")
      inv_url_new = f"{base}/projects/{project}/investigations/{inv_new}?api-version={api}"
      create = call_with_retries("PUT", inv_url_new, headers=headers(t), json={"description": "Post-deploy validation", "displayName": f"Validation Test {agent_name}"})
      if create.status_code not in (200, 201):
        raise RuntimeError(f"investigation create failed on retry: HTTP {create.status_code} {create.text[:300]}")
      inv = inv_new
      inv_url = inv_url_new
      _created_inv_urls.append(inv_url)
      # Create new conversation with new investigation
      conv = call_with_retries("POST", f"{base}/conversations?api-version={api}", headers=headers(t), json={
        "displayName": f"validation-{agent_name}",
        "investigationName": f"/projects/{project}/investigations/{inv}",
        "projectName": project,
      })
      conv.raise_for_status()
      conv_name = conv.json().get("name")
      if not conv_name:
        raise RuntimeError("conversation create failed on retry")
      time.sleep(2)  # Wait before retry
    else:
      write_result("failed", inv, status, joined if "joined" in locals() else "", False)
      print(f"VALIDATION_INVESTIGATION={inv}", flush=True)
      print(f"VALIDATION_STATUS={status}", flush=True)
      print(f"VALIDATION_OUTPUT_PREVIEW={joined[:300] if joined else ''}", flush=True)
      raise SystemExit(2)
  except TimeoutError as ex:
    if attempt < max_retries:
      print(f"[validation] Attempt {attempt}: Timeout - deleting investigation and retrying...", flush=True)
      # Delete timed-out investigation
      try:
        t = token()
        call_with_retries("DELETE", inv_url, headers=headers(t))
        print(f"[validation] Timed-out investigation deleted: {inv}", flush=True)
      except Exception as ex:
        print(f"[validation] Warning: could not delete timed-out investigation: {ex}", flush=True)
      # Create new investigation for retry
      time.sleep(1)
      t = token()
      inv_new = f"test-{safe}-{int(time.time())}"[:24].rstrip("-")
      inv_url_new = f"{base}/projects/{project}/investigations/{inv_new}?api-version={api}"
      create = call_with_retries("PUT", inv_url_new, headers=headers(t), json={"description": "Post-deploy validation", "displayName": f"Validation Test {agent_name}"})
      if create.status_code not in (200, 201):
        raise RuntimeError(f"investigation create failed on retry after timeout: HTTP {create.status_code} {create.text[:300]}")
      inv = inv_new
      inv_url = inv_url_new
      _created_inv_urls.append(inv_url)
      # Create new conversation with new investigation
      conv = call_with_retries("POST", f"{base}/conversations?api-version={api}", headers=headers(t), json={
        "displayName": f"validation-{agent_name}",
        "investigationName": f"/projects/{project}/investigations/{inv}",
        "projectName": project,
      })
      conv.raise_for_status()
      conv_name = conv.json().get("name")
      if not conv_name:
        raise RuntimeError("conversation create failed on retry after timeout")
      time.sleep(2)
    else:
      write_result("timeout", inv, "timeout", "", False)
      print(f"VALIDATION_INVESTIGATION={inv}", flush=True)
      print(f"VALIDATION_STATUS=timeout", flush=True)
      print(f"VALIDATION_OUTPUT_PREVIEW=", flush=True)
      raise SystemExit(2)

if str(delete_after).lower() == "true":
  try:
    t = token()
    call_with_retries("DELETE", inv_url, headers=headers(t))
    print(f"VALIDATION_INVESTIGATION_DELETED={inv}", flush=True)
    _cleanup_done = True  # Prevent atexit from double-deleting
  except Exception as ex:
    print(f"VALIDATION_INVESTIGATION_DELETE_WARNING={ex}", flush=True)
else:
  _cleanup_done = True  # Skip atexit cleanup when delete_after is false
'@ | Set-Content $ValidatePy -Encoding UTF8

$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
$ValidationResultPath = Join-Path $RunDir 'validation-result.json'
python $ValidatePy $State.deploy.deployConfigPath $TempAgentName $EffectivePrompt $Config.deleteInvestigationAfterTest $ValidationResultPath
if ($LASTEXITCODE -ne 0) { throw 'Validation test failed.' }
if (-not (Test-Path $ValidationResultPath)) { throw "Validation result file was not written: $ValidationResultPath" }
$ValidationResult = Get-Content $ValidationResultPath -Raw | ConvertFrom-Json
if ([string]$ValidationResult.status -ne 'passed') {
  throw ("Validation completed with status '{0}'. Read validation-result.json for details." -f ([string]$ValidationResult.status))
}

$State.validate.completedAt = (Get-Date).ToString('o')
$State.validate.status = 'Succeeded'
$State.validate.resultPath = $ValidationResultPath
$StatePath = Save-RunState -RunDir $RunDir -State $State
$PromptedConfigPath = Join-Path $RunDir 'prompted-config.json'
if (Test-Path $PromptedConfigPath) {
  Remove-Item $PromptedConfigPath -Force
  Write-Host ("PROMPTED_CONFIG_DELETED={0}" -f $PromptedConfigPath)
}
Write-Host ("RUN_STATE={0}" -f $StatePath)
Write-Host 'VALIDATION_STATUS=passed'
Write-Host '[stage-05] STATUS=Succeeded (5/5 validate complete)'

} catch {
  $ErrMsg = $_.Exception.Message
  if ($ErrMsg -like 'VALIDATION_PROMPT_INPUT_REQUIRED:*') {
    Write-Host ("[stage-05] STATUS=InputRequired ({0})" -f ($ErrMsg -replace '^VALIDATION_PROMPT_INPUT_REQUIRED:\s*',''))
    throw
  }
  Write-Host ("[stage-05] ERROR: {0}" -f $ErrMsg)
  Write-StageError -RunDir $RunDir -StageName 'stage-05' -Message $ErrMsg
  Set-RunStateFailed -RunDir $RunDir -StageName 'stage-05' -ErrorMessage $ErrMsg
  Write-Host '[stage-05] STATUS=Failed'
  throw
}

}


function Invoke-DiscoveryDeploySummary {
param(
  [Parameter(Mandatory = $true)][string]$RunDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Assert-PowerShell7OrNewer

try {

$State = Load-RunState -RunDir $RunDir

function Has-StateValue {
  param(
    [hashtable]$Bag,
    [string]$Key
  )

  if (-not $Bag) { return $false }
  if (-not $Bag.ContainsKey($Key)) { return $false }
  $Value = $Bag[$Key]
  if ($null -eq $Value) { return $false }
  return -not [string]::IsNullOrWhiteSpace(([string]$Value))
}

function Get-StageStatus {
  param(
    [hashtable]$RunState,
    [int]$StageNumber
  )

  switch ($StageNumber) {
    1 {
      if ((Has-StateValue -Bag $RunState.context -Key 'runDir') -and
          (Has-StateValue -Bag $RunState.context -Key 'agentDir')) { return 'Succeeded' }
      return 'Pending'
    }
    2 {
      if ((Has-StateValue -Bag $RunState.build -Key 'status') -and ([string]$RunState.build.status -eq 'Skipped')) { return 'Skipped' }
      if ((Has-StateValue -Bag $RunState.build -Key 'status') -and ([string]$RunState.build.status -eq 'Succeeded')) { return 'Succeeded' }
      if (Has-StateValue -Bag $RunState.build -Key 'completedAt') { return 'Succeeded' }
      if (Has-StateValue -Bag $RunState.build -Key 'runId') { return 'Running' }
      return 'Pending'
    }
    3 {
      if ((Has-StateValue -Bag $RunState.deploy -Key 'toolStatus') -and ([string]$RunState.deploy.toolStatus -eq 'Skipped')) { return 'Skipped' }
      if ((Has-StateValue -Bag $RunState.deploy -Key 'status') -and
          ([string]$RunState.deploy.status -eq 'Succeeded') -and
          (Has-StateValue -Bag $RunState.deploy -Key 'toolResourceId')) { return 'Succeeded' }
      if ((Has-StateValue -Bag $RunState.deploy -Key 'completedAt') -and
          (Has-StateValue -Bag $RunState.deploy -Key 'toolResourceId')) { return 'Succeeded' }
      return 'Pending'
    }
    4 {
      if ((Has-StateValue -Bag $RunState.deploy -Key 'agentCompletedAt') -and
          (Has-StateValue -Bag $RunState.deploy -Key 'tempAgentYaml')) { return 'Succeeded' }
      return 'Pending'
    }
    5 {
      if ((Has-StateValue -Bag $RunState.validate -Key 'status') -and ([string]$RunState.validate.status -eq 'Failed')) { return 'Failed' }
      if (Has-StateValue -Bag $RunState.validate -Key 'failedAt') { return 'Failed' }
      if (Has-StateValue -Bag $RunState.validate -Key 'completedAt') { return 'Succeeded' }
      return 'Pending'
    }
    default { return 'Unknown' }
  }
}

$Rows = @(
  [pscustomobject]@{ Stage = 1; Name = 'init'; Status = (Get-StageStatus -RunState $State -StageNumber 1) }
  [pscustomobject]@{ Stage = 2; Name = 'build'; Status = (Get-StageStatus -RunState $State -StageNumber 2) }
  [pscustomobject]@{ Stage = 3; Name = 'deploy-tool'; Status = (Get-StageStatus -RunState $State -StageNumber 3) }
  [pscustomobject]@{ Stage = 4; Name = 'deploy-agent'; Status = (Get-StageStatus -RunState $State -StageNumber 4) }
  [pscustomobject]@{ Stage = 5; Name = 'validate'; Status = (Get-StageStatus -RunState $State -StageNumber 5) }
)

Write-Output '=== discovery-services-agent-deployer SUMMARY ==='
Write-Output ("RUN_DIR={0}" -f $RunDir)
if (Has-StateValue -Bag $State.context -Key 'imageRef') {
  Write-Output ("IMAGE_REF={0}" -f ([string]$State.context.imageRef))
}
if (Has-StateValue -Bag $State.deploy -Key 'toolResourceId') {
  Write-Output ("TOOL_RESOURCE_ID={0}" -f ([string]$State.deploy.toolResourceId))
}
Write-Output '---'
Write-Output 'Stage Name Status'
foreach ($r in $Rows) {
  Write-Output ("{0} {1} {2}" -f $r.Stage, $r.Name, $r.Status)
}
Write-Output '---'

foreach ($r in $Rows) {
  Write-Output ("SUMMARY_STAGE_{0}_NAME={1}" -f $r.Stage, $r.Name)
  Write-Output ("SUMMARY_STAGE_{0}_STATUS={1}" -f $r.Stage, $r.Status)
}

if ((Has-StateValue -Bag $State.build -Key 'runId')) {
  Write-Output ("SUMMARY_BUILD_RUN_ID={0}" -f ([string]$State.build.runId))
}
if ((Has-StateValue -Bag $State.build -Key 'mode')) {
  Write-Output ("SUMMARY_BUILD_MODE={0}" -f ([string]$State.build.mode))
}
if (Has-StateValue -Bag $State.validate -Key 'completedAt') {
  Write-Output ("SUMMARY_VALIDATION_STATUS=passed")
} elseif (Has-StateValue -Bag $State.validate -Key 'failedAt') {
  Write-Output ("SUMMARY_VALIDATION_STATUS=failed")
} elseif (Test-Path (Join-Path $RunDir 'validation-result.json')) {
  try {
    $ValidationResult = Get-Content (Join-Path $RunDir 'validation-result.json') -Raw | ConvertFrom-Json
    Write-Output ("SUMMARY_VALIDATION_STATUS={0}" -f ([string]$ValidationResult.status))
  } catch {
    Write-Output ("SUMMARY_VALIDATION_STATUS=failed")
  }
} elseif ($Rows[4].Status -eq 'Pending') {
  Write-Output ("SUMMARY_VALIDATION_STATUS=pending")
}

} catch {
  $ErrMsg = $_.Exception.Message
  Write-StageError -RunDir $RunDir -StageName 'stage-summary' -Message $ErrMsg
  Write-Host '[stage-summary] STATUS=Failed'
  throw
}

}






[object[]]$RawAgentArgs = @()
if ($null -ne $AgentArgs) { $RawAgentArgs = @($AgentArgs) }
$PositionalAgentNames = @()
for ($i = 0; $i -lt $RawAgentArgs.Count; $i++) {
  $arg = [string]$RawAgentArgs[$i]
  switch ($arg) {
    '-WhatIfPlan' { $WhatIfPlan = $true; continue }
    '-SkipValidation' { $SkipValidation = $true; continue }
    '-ConfirmSupercomputerNodepools' { $ConfirmSupercomputerNodepools = $true; continue }
    '-SuppressTaskPlan' { $SuppressTaskPlan = $true; continue }
    '-ValidationPrompt' {
      if ($i + 1 -ge $RawAgentArgs.Count) { throw '-ValidationPrompt requires a value.' }
      $i++
      $ValidationPrompt = [string]$RawAgentArgs[$i]
      continue
    }
    '-PublisherName' {
      if ($i + 1 -ge $RawAgentArgs.Count) { throw '-PublisherName requires a value.' }
      $i++
      $PublisherName = [string]$RawAgentArgs[$i]
      continue
    }
    '-BuildMode' {
      if ($i + 1 -ge $RawAgentArgs.Count) { throw '-BuildMode requires a value.' }
      $i++
      $candidateBuildMode = [string]$RawAgentArgs[$i]
      if ($candidateBuildMode -notin @('auto','remote','local')) { throw "Invalid -BuildMode '$candidateBuildMode'. Expected auto, remote, or local." }
      $BuildMode = $candidateBuildMode
      continue
    }
    '-Resume' {
      if ($i + 1 -ge $RawAgentArgs.Count) { throw '-Resume requires a value.' }
      $i++
      $Resume = [string]$RawAgentArgs[$i]
      continue
    }
    '-RunDir' {
      if ($i + 1 -ge $RawAgentArgs.Count) { throw '-RunDir requires a value.' }
      $i++
      $RunDir = [string]$RawAgentArgs[$i]
      continue
    }
    '-Stage' {
      if ($i + 1 -ge $RawAgentArgs.Count) { throw '-Stage requires a value.' }
      $i++
      $candidateStage = [string]$RawAgentArgs[$i]
      if ($candidateStage -notin @('init','build','deploy-tool','deploy-agent','validate','summary','stop')) { throw "Invalid -Stage '$candidateStage'." }
      $Stage = $candidateStage
      continue
    }
    default {
      $PositionalAgentNames += $arg
    }
  }
}

$script:StageTodos = @(
  [ordered]@{ Id = 'init'; Name = 'Discover agent and initialize run'; Status = 'pending' },
  [ordered]@{ Id = 'build'; Name = 'Build and push tool image'; Status = 'pending' },
  [ordered]@{ Id = 'deploy-tool'; Name = 'Create or update Discovery tool'; Status = 'pending' },
  [ordered]@{ Id = 'deploy-agent'; Name = 'Patch and deploy agent'; Status = 'pending' },
  [ordered]@{ Id = 'validate'; Name = 'Run deployment validation'; Status = 'pending' },
  [ordered]@{ Id = 'summary'; Name = 'Print final deployment summary'; Status = 'pending' }
)

function Set-StageTodoStatus {
  param(
    [string]$Id,
    [ValidateSet('pending','in_progress','done','skipped','failed','input_required','stopped')]
    [string]$Status
  )

  foreach ($todo in $script:StageTodos) {
    if ($todo.Id -eq $Id) {
      $todo.Status = $Status
      return
    }
  }
  throw "Unknown stage TODO id '$Id'."
}

function Save-StageTodoStatus {
  param([string]$RunDir)

  if ([string]::IsNullOrWhiteSpace($RunDir) -or -not (Test-Path $RunDir)) { return }
  $path = Join-Path $RunDir 'stage-todos.json'
  @($script:StageTodos | ForEach-Object { [pscustomobject]$_ }) |
    ConvertTo-Json -Depth 4 |
    Set-Content -Path $path -Encoding utf8
}

function Set-AllStageTodoStatuses {
  param([string]$RunDir, [string]$Status)
  foreach ($todo in $script:StageTodos) { $todo.Status = $Status }
  Save-StageTodoStatus -RunDir $RunDir
  foreach ($todo in $script:StageTodos) {
    Write-Host ("TASK_STATUS={0}:{1}" -f $todo.Id, $Status)
  }
}

function Invoke-Stage {
  param(
    [string]$Name,
    [string]$TodoId,
    [scriptblock]$ScriptBlock,
    [hashtable]$Arguments = @{},
    [string]$RunDir = ''
  )

  Set-StageTodoStatus -Id $TodoId -Status 'in_progress'
  Save-StageTodoStatus -RunDir $RunDir
  Write-Host ("TASK_STATUS={0}:in_progress" -f $TodoId)
  Write-Host ("[runner] START {0}" -f $Name)
  $outputLines = [System.Collections.Generic.List[string]]::new()
  try {
    & $ScriptBlock $Arguments *>&1 | ForEach-Object {
      $line = [string]$_
      $outputLines.Add($line)
      Write-Host $line
    }
    $stageExitCode = 0
    $lastExitCodeVariable = Get-Variable -Name LASTEXITCODE -ErrorAction SilentlyContinue
    if ($lastExitCodeVariable) { $stageExitCode = [int]$lastExitCodeVariable.Value }
    if ($stageExitCode -ne 0) {
      throw "Stage '$Name' failed with exit code $stageExitCode."
    }
  } catch {
    $isConfigInputRequired = $false
    if ($_.Exception.Message -like 'CONFIG_INPUT_REQUIRED:*' -or $_.Exception.Message -like 'BUILD_MODE_INPUT_REQUIRED:*' -or $_.Exception.Message -like 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED:*') { $isConfigInputRequired = $true }
    if ($_.Exception.Message -like 'VALIDATION_PROMPT_INPUT_REQUIRED:*') { $isConfigInputRequired = $true }
    foreach ($line in $outputLines) {
      if ($line -eq 'CONFIG_INPUT_REQUIRED=true' -or $line -eq 'BUILD_MODE_INPUT_REQUIRED=true' -or $line -eq 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED=true' -or $line -eq 'VALIDATION_PROMPT_INPUT_REQUIRED=true' -or $line.StartsWith('[stage-01] STATUS=InputRequired')) {
        $isConfigInputRequired = $true
        break
      }
    }
    if ($isConfigInputRequired) {
      Set-StageTodoStatus -Id $TodoId -Status 'input_required'
      Save-StageTodoStatus -RunDir $RunDir
      Write-Host ("TASK_STATUS={0}:input_required" -f $TodoId)
      Write-Host ("[runner] INPUT_REQUIRED {0}" -f $Name)
      exit 2
    }
    Set-StageTodoStatus -Id $TodoId -Status 'failed'
    if ($TodoId -eq 'validate') {
      Set-StageTodoStatus -Id 'summary' -Status 'stopped'
    }
    Save-StageTodoStatus -RunDir $RunDir
    Write-Host ("TASK_STATUS={0}:failed" -f $TodoId)
    throw
  }

  $inputRequiredOutput = $false
  foreach ($line in $outputLines) {
    if ($line -eq 'CONFIG_INPUT_REQUIRED=true' -or $line -eq 'BUILD_MODE_INPUT_REQUIRED=true' -or $line -eq 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED=true' -or $line -eq 'VALIDATION_PROMPT_INPUT_REQUIRED=true' -or $line -match 'STATUS=InputRequired') {
      $inputRequiredOutput = $true
      break
    }
  }
  if ($inputRequiredOutput) {
    Set-StageTodoStatus -Id $TodoId -Status 'input_required'
    Save-StageTodoStatus -RunDir $RunDir
    Write-Host ("TASK_STATUS={0}:input_required" -f $TodoId)
    Write-Host ("[runner] INPUT_REQUIRED {0}" -f $Name)
    return @($outputLines)
  }

  Set-StageTodoStatus -Id $TodoId -Status 'done'
  Write-Host ("TASK_STATUS={0}:done" -f $TodoId)
  Write-Host ("[runner] DONE {0}" -f $Name)
  Save-StageTodoStatus -RunDir $RunDir
  return @($outputLines)
}

function Get-RunDirFromOutput {
  param([string[]]$Output)
  foreach ($line in $Output) {
    if ($line -match '^RUN_DIR=(.+)$') {
      return $Matches[1].Trim()
    }
  }
  return ''
}

function Load-RunnerRunState {
  param([string]$RunDir)
  $path = Join-Path $RunDir 'run-state.json'
  if (-not (Test-Path $path)) { return $null }
  return (Get-Content $path -Raw | ConvertFrom-Json -AsHashtable)
}

function Test-StageComplete {
  param(
    [hashtable]$State,
    [int]$Stage
  )

  if (-not $State) { return $false }
  switch ($Stage) {
    2 {
      if ($State.build.ContainsKey('status') -and $State.build.status -eq 'Skipped') { return $true }
      return (($State.build.ContainsKey('completedAt') -and $State.build.completedAt) -or
        ($State.build.ContainsKey('status') -and $State.build.status -eq 'Succeeded'))
    }
    3 {
      if ($State.deploy.ContainsKey('toolStatus') -and $State.deploy.toolStatus -eq 'Skipped') { return $true }
      return (($State.deploy.ContainsKey('completedAt') -and $State.deploy.completedAt -and $State.deploy.ContainsKey('toolResourceId') -and $State.deploy.toolResourceId) -or
        ($State.deploy.ContainsKey('status') -and $State.deploy.status -eq 'Succeeded' -and $State.deploy.ContainsKey('toolResourceId') -and $State.deploy.toolResourceId))
    }
    4 { return ($State.deploy.ContainsKey('agentCompletedAt') -and $State.deploy.agentCompletedAt) }
    5 { return ($State.validate.ContainsKey('completedAt') -and $State.validate.completedAt) }
    default { return $false }
  }
}

function Test-RunHasTool {
  param([string]$RunDir)

  $state = Load-RunnerRunState -RunDir $RunDir
  return ($state -and $state.context -and $state.context.ContainsKey('hasTool') -and [bool]$state.context.hasTool)
}

function Resolve-DeployableAgent {
  param(
    [string]$AgentName,
    [string]$PublisherName
  )

  if ([string]::IsNullOrWhiteSpace($AgentName)) { throw 'Agent name cannot be empty.' }

  if ($PublisherName) {
    Write-Host "[deployer] -PublisherName is deprecated in the flat agents/ layout and is ignored."
  }

  $repoRoot   = Get-RepoRoot
  $agentsRoot = Join-Path $repoRoot 'agents'
  $agentDir   = Join-Path $agentsRoot $AgentName

  if (-not (Test-Path (Join-Path $agentDir 'agent.yaml'))) {
    throw "Agent '$AgentName' not found at '$agentDir' (expected agents/$AgentName/agent.yaml)."
  }

  return Get-Item $agentDir
}

function Resolve-AgentToolInfo {
  param(
    [string]$AgentName,
    [string]$PublisherName
  )

  $agentDir = (Resolve-DeployableAgent -AgentName $AgentName -PublisherName $PublisherName).FullName
  $toolsDir = Join-Path $agentDir 'tools'
  if (-not (Test-Path $toolsDir)) {
    return [pscustomobject]@{
      AgentDir = $agentDir
      HasTool = $false
      SkipReason = "Agent '$AgentName' does not ship a tool (no tools folder under $agentDir)."
    }
  }

  [array]$toolDirs = @(Get-ChildItem $toolsDir -Directory | Sort-Object Name)
  if ($toolDirs.Count -eq 0) {
    return [pscustomobject]@{
      AgentDir = $agentDir
      ToolsDir = $toolsDir
      HasTool = $false
      SkipReason = "Tools directory exists but contains no sub-folders: $toolsDir"
    }
  }

  $toolDir = $toolDirs[0].FullName
  $dockerfile = Join-Path $toolDir 'Dockerfile'
  $toolYaml = Join-Path $toolDir 'tool.yaml'
  if (-not (Test-Path $dockerfile)) { throw "Missing Dockerfile at $dockerfile" }
  if (-not (Test-Path $toolYaml)) { throw "Missing tool.yaml at $toolYaml" }

  return [pscustomobject]@{
    AgentDir = $agentDir
    HasTool = $true
    ToolsDir = $toolsDir
    ToolDir = $toolDir
    Dockerfile = $dockerfile
    ToolYaml = $toolYaml
  }
}

function Assert-RequestedAgentsExist {
  param(
    [string[]]$AgentNames,
    [string]$PublisherName
  )

  $missingOrInvalid = @()
  foreach ($name in $AgentNames) {
    try {
      Resolve-DeployableAgent -AgentName $name -PublisherName $PublisherName | Out-Null
    } catch {
      $missingOrInvalid += ("{0}: {1}" -f $name, $_.Exception.Message)
    }
  }

  if ($missingOrInvalid.Count -gt 0) {
    throw ("Requested agent validation failed before task creation. Fix the agent name and retry. Each agent must live at agents/<agent-name>/ with an agent.yaml.`n{0}" -f ($missingOrInvalid -join "`n"))
  }
}

function Set-SkippedStage {
  param(
    [string]$RunDir,
    [string]$TodoId,
    [string]$StageName,
    [string]$Reason
  )

  Set-StageTodoStatus -Id $TodoId -Status 'skipped'
  $state = Load-RunnerRunState -RunDir $RunDir
  if ($state) {
    if ($TodoId -eq 'build') {
      $state.build['status'] = 'Skipped'
      $state.build['skipReason'] = $Reason
    } elseif ($TodoId -eq 'deploy-tool') {
      $state.deploy['toolStatus'] = 'Skipped'
      $state.deploy['toolSkipReason'] = $Reason
    }
    $statePath = Join-Path $RunDir 'run-state.json'
    ($state | ConvertTo-Json -Depth 50) | Set-Content -Path $statePath -Encoding utf8
  }
  Write-Host ("TASK_STATUS={0}:skipped" -f $TodoId)
  Write-Host ("[runner] SKIP {0} ({1})" -f $StageName, $Reason)
  Save-StageTodoStatus -RunDir $RunDir
}

function Get-PlannedStagesForAgent {
  param(
    [string]$AgentName,
    [string]$PublisherName
  )

  $tool = Resolve-AgentToolInfo -AgentName $AgentName -PublisherName $PublisherName
  if ($tool.HasTool) {
    return @('init','build','deploy-tool','deploy-agent','validate','summary')
  }

  return @('init','deploy-agent','validate','summary')
}

function Invoke-AgentChildRun {
  param(
    [string]$ChildAgentName
  )

  Write-Host ("[multi-agent] START agent={0}" -f $ChildAgentName)
  $childArgs = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', $PSCommandPath,
    '-AgentName', $ChildAgentName,
    '-BuildMode', $BuildMode
  )
  if ($PublisherName) { $childArgs += @('-PublisherName', $PublisherName) }
  if ($SkipValidation) { $childArgs += '-SkipValidation' }
  if ($WhatIfPlan) { $childArgs += '-WhatIfPlan' }
  if ($ConfirmSupercomputerNodepools) { $childArgs += '-ConfirmSupercomputerNodepools' }
  if (-not [string]::IsNullOrWhiteSpace($ValidationPrompt)) { $childArgs += @('-ValidationPrompt', $ValidationPrompt) }
  $childArgs += '-SuppressTaskPlan'

  & pwsh @childArgs *>&1 | ForEach-Object {
    $line = [string]$_
    if ($line -match '^TASK_STATUS=(.+)$') {
      Write-Host ("TASK_STATUS={0}/{1}" -f $ChildAgentName, $Matches[1])
    } else {
      Write-Host ("[agent:{0}] {1}" -f $ChildAgentName, $line)
    }
  }
  $exitCode = $LASTEXITCODE

  if ($exitCode -eq 0) {
    Write-Host ("[multi-agent] DONE agent={0}" -f $ChildAgentName)
  } else {
    Write-Host ("[multi-agent] FAILED agent={0} exitCode={1}" -f $ChildAgentName, $exitCode)
  }
  return $exitCode
}

function Show-WhatIfPlan {
  param(
    [string]$AgentName,
    [string]$PublisherName
  )

  if ([string]::IsNullOrWhiteSpace($AgentName)) {
    throw '-AgentName is required when using -WhatIfPlan.'
  }

  $repoRoot = Get-RepoRoot
  $tool = Resolve-AgentToolInfo -AgentName $AgentName -PublisherName $PublisherName

  Write-Host '=== discovery-services-agent-deployer PLAN ==='
  Write-Host ("REPO_ROOT={0}" -f $repoRoot)
  Write-Host ("AGENT_DIR={0}" -f $tool.AgentDir)
  if ($tool.HasTool) {
    Write-Host ("TOOL_DIR={0}" -f $tool.ToolDir)
    Write-Host ("DOCKERFILE={0}" -f $tool.Dockerfile)
    Write-Host ("TOOL_YAML={0}" -f $tool.ToolYaml)
  } else {
    Write-Host 'TOOL_DIR=(none)'
    Write-Host ("PLAN_TOOL_STAGES=skipped ({0})" -f $tool.SkipReason)
  }
  Write-Host ("BUILD_MODE={0}" -f $BuildMode)
  Write-Host ("CONFIRM_SUPERCOMPUTER_NODEPOOLS={0}" -f ([bool]$ConfirmSupercomputerNodepools))
  Write-Host ("SKIP_VALIDATION={0}" -f ([bool]$SkipValidation))
  if ($tool.HasTool) {
    Write-Host 'PLAN_STAGES=init -> build -> deploy-tool -> deploy-agent'
  } else {
    Write-Host 'PLAN_STAGES=init -> deploy-agent'
  }
  if (-not $SkipValidation) { Write-Host 'PLAN_VALIDATION=create temporary investigation and send Copilot-generated validation prompt' }
  else { Write-Host 'PLAN_VALIDATION=skipped by request' }
  if ($SkipValidation) { Set-StageTodoStatus -Id 'validate' -Status 'skipped' }
}

[object[]]$AgentNames = @(
  @($AgentName) + @($PositionalAgentNames) |
    ForEach-Object { ([string]$_).Split(',', [System.StringSplitOptions]::RemoveEmptyEntries) } |
    ForEach-Object { $_.Trim() } |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
if (-not $Resume -and $AgentNames.Count -gt 0) {
  Assert-RequestedAgentsExist -AgentNames $AgentNames -PublisherName $PublisherName
  if (-not $SuppressTaskPlan -and -not $Stage -and -not $WhatIfPlan) {
    foreach ($agent in $AgentNames) {
      foreach ($stage in (Get-PlannedStagesForAgent -AgentName $agent -PublisherName $PublisherName)) {
        Write-Host ("TASK_PLAN={0}/{1}" -f $agent, $stage)
      }
    }
  }
}
if (-not $Resume -and $AgentNames.Count -gt 1) {
  Write-Host ("[multi-agent] COUNT={0}" -f $AgentNames.Count)
  Write-Host ("[multi-agent] AGENTS={0}" -f ($AgentNames -join ','))
  $failedAgents = @()
  foreach ($childAgent in $AgentNames) {
    $exitCode = Invoke-AgentChildRun -ChildAgentName $childAgent
    if ($exitCode -ne 0) { $failedAgents += $childAgent }
  }
  if ($failedAgents.Count -gt 0) {
    throw ("One or more agent deployments failed: {0}" -f ($failedAgents -join ', '))
  }
  Write-Host '[multi-agent] STATUS=Succeeded'
  return
}

[string]$ResolvedAgentName = ''
if (-not $Resume -and $AgentNames.Count -eq 1) {
  $ResolvedAgentName = [string]$AgentNames[0]
}

if ($WhatIfPlan) {
  Show-WhatIfPlan -AgentName $ResolvedAgentName -PublisherName $PublisherName
  return
}

if ($Stage) {
  switch ($Stage) {
    'init' {
      if ([string]::IsNullOrWhiteSpace($ResolvedAgentName)) { throw 'AgentName is required for -Stage init.' }
      $stageArgs = @{ AgentName = $ResolvedAgentName }
      if ($PublisherName) { $stageArgs.PublisherName = $PublisherName }
      if ($BuildMode) { $stageArgs.BuildMode = $BuildMode }
      if ($ConfirmSupercomputerNodepools) { $stageArgs.ConfirmSupercomputerNodepools = $true }
      $initOutput = Invoke-Stage -Name 'stage-01-init' -TodoId 'init' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployInit @StageArgs } -Arguments $stageArgs
      if ($initOutput -contains 'BUILD_MODE_INPUT_REQUIRED=true' -or $initOutput -contains 'CONFIG_INPUT_REQUIRED=true') { return }
      $createdRunDir = Get-RunDirFromOutput -Output $initOutput
      if (-not $createdRunDir) { throw 'Stage init did not emit RUN_DIR.' }
      Save-StageTodoStatus -RunDir $createdRunDir
      return
    }
    'build' {
      if ([string]::IsNullOrWhiteSpace($RunDir)) { throw '-RunDir is required for -Stage build.' }
      $resolvedRunDir = (Resolve-Path $RunDir).Path
      if (-not (Test-RunHasTool -RunDir $resolvedRunDir)) {
        Set-SkippedStage -RunDir $resolvedRunDir -TodoId 'build' -StageName 'stage-02-build' -Reason 'agent has no tool'
        return
      }
      Invoke-Stage -Name 'stage-02-build' -TodoId 'build' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployBuild @StageArgs } -Arguments @{ RunDir = $resolvedRunDir; BuildMode = $BuildMode; ConfirmSupercomputerNodepools = [bool]$ConfirmSupercomputerNodepools } -RunDir $resolvedRunDir | Out-Null
      return
    }
    'deploy-tool' {
      if ([string]::IsNullOrWhiteSpace($RunDir)) { throw '-RunDir is required for -Stage deploy-tool.' }
      $resolvedRunDir = (Resolve-Path $RunDir).Path
      if (-not (Test-RunHasTool -RunDir $resolvedRunDir)) {
        Set-SkippedStage -RunDir $resolvedRunDir -TodoId 'deploy-tool' -StageName 'stage-03-deploy-tool' -Reason 'agent has no tool'
        return
      }
      Invoke-Stage -Name 'stage-03-deploy-tool' -TodoId 'deploy-tool' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployTool @StageArgs } -Arguments @{ RunDir = $resolvedRunDir } -RunDir $resolvedRunDir | Out-Null
      return
    }
    'deploy-agent' {
      if ([string]::IsNullOrWhiteSpace($RunDir)) { throw '-RunDir is required for -Stage deploy-agent.' }
      $resolvedRunDir = (Resolve-Path $RunDir).Path
      Invoke-Stage -Name 'stage-04-deploy-agent' -TodoId 'deploy-agent' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployAgent @StageArgs } -Arguments @{ RunDir = $resolvedRunDir } -RunDir $resolvedRunDir | Out-Null
      return
    }
    'validate' {
      if ([string]::IsNullOrWhiteSpace($RunDir)) { throw '-RunDir is required for -Stage validate.' }
      $resolvedRunDir = (Resolve-Path $RunDir).Path
      if ($SkipValidation) {
        Set-StageTodoStatus -Id 'validate' -Status 'skipped'
        Write-Host 'TASK_STATUS=validate:skipped'
        Write-Host '[runner] SKIP stage-05-validate (-SkipValidation)'
        Save-StageTodoStatus -RunDir $resolvedRunDir
      } else {
        Invoke-Stage -Name 'stage-05-validate' -TodoId 'validate' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployValidation @StageArgs } -Arguments @{ RunDir = $resolvedRunDir; Prompt = $ValidationPrompt } -RunDir $resolvedRunDir | Out-Null
      }
      return
    }
    'summary' {
      if ([string]::IsNullOrWhiteSpace($RunDir)) { throw '-RunDir is required for -Stage summary.' }
      $resolvedRunDir = (Resolve-Path $RunDir).Path
      Invoke-Stage -Name 'stage-summary' -TodoId 'summary' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeploySummary @StageArgs } -Arguments @{ RunDir = $resolvedRunDir } -RunDir $resolvedRunDir | Out-Null
      Write-Host '[runner] STATUS=Succeeded'
      return
    }
    'stop' {
      if ([string]::IsNullOrWhiteSpace($RunDir)) { throw '-RunDir is required for -Stage stop.' }
      $resolvedRunDir = (Resolve-Path $RunDir).Path
      Set-AllStageTodoStatuses -RunDir $resolvedRunDir -Status 'stopped'
      Write-Host 'DEPLOYMENT_STOPPED=true'
      Write-Host 'DEPLOYMENT_STOPPED_REASON=Supercomputer nodepool capacity was not confirmed.'
      Write-Host 'No tool build was submitted, and no Azure resources were created or modified by build/deploy stages.'
      return
    }
  }
}

if ($Resume) {
  $RunDir = (Resolve-Path $Resume).Path
  Write-Host ("[runner] Resuming run: {0}" -f $RunDir)
} else {
  if ([string]::IsNullOrWhiteSpace($ResolvedAgentName)) {
    throw 'AgentName is required unless -Resume is provided.'
  }
  $stageArgs = @{ AgentName = $ResolvedAgentName }
  if ($PublisherName) { $stageArgs.PublisherName = $PublisherName }
  if ($BuildMode) { $stageArgs.BuildMode = $BuildMode }
  if ($ConfirmSupercomputerNodepools) { $stageArgs.ConfirmSupercomputerNodepools = $true }
  $initOutput = Invoke-Stage -Name 'stage-01-init' -TodoId 'init' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployInit @StageArgs } -Arguments $stageArgs
  if ($initOutput -contains 'BUILD_MODE_INPUT_REQUIRED=true' -or $initOutput -contains 'CONFIG_INPUT_REQUIRED=true') { return }
  $RunDir = Get-RunDirFromOutput -Output $initOutput
  if (-not $RunDir) { throw 'Stage 1 did not emit RUN_DIR; cannot continue.' }
  Save-StageTodoStatus -RunDir $RunDir
}

$State = Load-RunnerRunState -RunDir $RunDir
if ($Resume) {
  Set-StageTodoStatus -Id 'init' -Status 'done'
  Write-Host 'TASK_STATUS=init:done'
  Save-StageTodoStatus -RunDir $RunDir
}
if (-not (Test-RunHasTool -RunDir $RunDir)) {
  Set-SkippedStage -RunDir $RunDir -TodoId 'build' -StageName 'stage-02-build' -Reason 'agent has no tool'
} elseif (-not (Test-StageComplete -State $State -Stage 2)) {
  Invoke-Stage -Name 'stage-02-build' -TodoId 'build' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployBuild @StageArgs } -Arguments @{ RunDir = $RunDir; BuildMode = $BuildMode; ConfirmSupercomputerNodepools = [bool]$ConfirmSupercomputerNodepools } -RunDir $RunDir | Out-Null
} else {
  Set-StageTodoStatus -Id 'build' -Status 'done'
  Write-Host 'TASK_STATUS=build:done'
  Write-Host '[runner] SKIP stage-02-build (already completed)'
  Save-StageTodoStatus -RunDir $RunDir
}

$State = Load-RunnerRunState -RunDir $RunDir
if (-not (Test-RunHasTool -RunDir $RunDir)) {
  Set-SkippedStage -RunDir $RunDir -TodoId 'deploy-tool' -StageName 'stage-03-deploy-tool' -Reason 'agent has no tool'
} elseif (-not (Test-StageComplete -State $State -Stage 3)) {
  Invoke-Stage -Name 'stage-03-deploy-tool' -TodoId 'deploy-tool' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployTool @StageArgs } -Arguments @{ RunDir = $RunDir } -RunDir $RunDir | Out-Null
} else {
  Set-StageTodoStatus -Id 'deploy-tool' -Status 'done'
  Write-Host 'TASK_STATUS=deploy-tool:done'
  Write-Host '[runner] SKIP stage-03-deploy-tool (already completed)'
  Save-StageTodoStatus -RunDir $RunDir
}

$State = Load-RunnerRunState -RunDir $RunDir
if (-not (Test-StageComplete -State $State -Stage 4)) {
  Invoke-Stage -Name 'stage-04-deploy-agent' -TodoId 'deploy-agent' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployAgent @StageArgs } -Arguments @{ RunDir = $RunDir } -RunDir $RunDir | Out-Null
} else {
  Set-StageTodoStatus -Id 'deploy-agent' -Status 'done'
  Write-Host 'TASK_STATUS=deploy-agent:done'
  Write-Host '[runner] SKIP stage-04-deploy-agent (already completed)'
  Save-StageTodoStatus -RunDir $RunDir
}

if ($SkipValidation) {
  Set-StageTodoStatus -Id 'validate' -Status 'skipped'
  Write-Host 'TASK_STATUS=validate:skipped'
  Write-Host '[runner] SKIP stage-05-validate (-SkipValidation)'
  Save-StageTodoStatus -RunDir $RunDir
} else {
  $State = Load-RunnerRunState -RunDir $RunDir
  if (-not (Test-StageComplete -State $State -Stage 5)) {
    Invoke-Stage -Name 'stage-05-validate' -TodoId 'validate' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeployValidation @StageArgs } -Arguments @{ RunDir = $RunDir; Prompt = $ValidationPrompt } -RunDir $RunDir | Out-Null
  } else {
    Set-StageTodoStatus -Id 'validate' -Status 'done'
    Write-Host 'TASK_STATUS=validate:done'
    Write-Host '[runner] SKIP stage-05-validate (already completed)'
    Save-StageTodoStatus -RunDir $RunDir
  }
}

Invoke-Stage -Name 'stage-summary' -TodoId 'summary' -ScriptBlock { param($StageArgs) Invoke-DiscoveryDeploySummary @StageArgs } -Arguments @{ RunDir = $RunDir } -RunDir $RunDir | Out-Null
Write-Host '[runner] STATUS=Succeeded'


