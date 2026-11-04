# Configuration loading: defaults < config.json < DH_* environment < explicit overrides.

function Get-DhDefaultConfig {
  return [ordered]@{
    subscriptionId           = ''
    tenantId                 = ''
    resourceGroup            = ''
    location                 = ''
    acrName                  = ''
    acrResourceGroup         = ''
    acrAgentPool             = ''
    acrTimeoutSeconds        = 7200
    workspaceEndpoint        = ''
    project                  = ''
    projectResourceId        = ''
    apiVersion               = '2026-06-01'
    chatModel                = ''
    nodePools                = @()
    outputStorageContainerId = ''
    evidenceStorage          = [ordered]@{ account = ''; container = 'discovery-health'; resourceGroup = '' }
    scorecard                = [ordered]@{ pagesUrl = ''; historyRuns = 12 }
    testTag                  = 'discovery-github-test'
    acrRepositoryPrefix      = 'discovery-github-test'
    namePrefix               = 'dgt-'
    rebuild                  = [ordered]@{ mode = 'changed'; maxImageAgeDays = 30 }
    concurrency              = [ordered]@{ acr = 8; toolRegister = 10; toolRun = 6; gpuToolRun = 2; agentRegister = 10; roundTrip = 6 }
    budgets                  = [ordered]@{ maxAcrBuilds = 250; maxToolRuns = 250; maxGpuToolRuns = 40; maxRoundTrips = 150 }
    timeouts                 = [ordered]@{ buildMinutes = 120; toolRegisterMinutes = 30; toolRunQueueMinutes = 45; toolRunMinutes = 30; agentRegisterMinutes = 10; roundTripMinutes = 20 }
    roundTrip                = [ordered]@{ enabled = $true; maxAttempts = 2; deleteInvestigationOnPass = $true }
    deadlineMinutes          = 330
    pollSeconds              = 20
    cleanup                  = [ordered]@{ afterRun = 'none'; retentionDays = 30; retainFailedDays = 14; keepImagesPerRepo = 2; maxRunAgeHours = 8 }
    failOn                   = 'contribution'
    templateVariables        = [ordered]@{}
    staging                  = [ordered]@{ maxContextMB = 2048; maxFiles = 20000 }
    ledgerDir                = ''
    pythonCommand            = ''
  }
}

function ConvertTo-DhUpperSnake {
  param([string]$Name)
  return (($Name -creplace '([a-z0-9])([A-Z])', '$1_$2').ToUpperInvariant())
}

function Merge-DhConfig {
  <#
  .SYNOPSIS Deep-merges dictionaries; arrays and scalars in Overlay replace Base values.
  #>
  param([System.Collections.IDictionary]$Base, [System.Collections.IDictionary]$Overlay)
  $result = [ordered]@{}
  foreach ($key in $Base.Keys) { $result[$key] = $Base[$key] }
  if ($null -eq $Overlay) { return $result }
  foreach ($key in $Overlay.Keys) {
    $value = $Overlay[$key]
    if ($result.Contains($key) -and $result[$key] -is [System.Collections.IDictionary] -and $value -is [System.Collections.IDictionary]) {
      $result[$key] = Merge-DhConfig -Base $result[$key] -Overlay $value
    } else {
      $result[$key] = $value
    }
  }
  return $result
}

function Get-DhEnvConfigOverlay {
  param([System.Collections.IDictionary]$Defaults)
  $overlay = [ordered]@{}
  if ($env:DH_CONFIG_JSON) {
    $overlay = Merge-DhConfig -Base $overlay -Overlay (ConvertFrom-DhJson $env:DH_CONFIG_JSON)
  }
  foreach ($key in $Defaults.Keys) {
    $name = 'DH_' + (ConvertTo-DhUpperSnake $key)
    $raw = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrEmpty($raw)) { continue }
    $default = $Defaults[$key]
    if ($default -is [System.Collections.IDictionary] -or $default -is [array]) {
      $overlay[$key] = ConvertFrom-DhJson $raw
    } elseif ($default -is [bool]) {
      $overlay[$key] = $raw -in @('1', 'true', 'True', 'TRUE', 'yes')
    } elseif ($default -is [int]) {
      $overlay[$key] = [int]$raw
    } else {
      $overlay[$key] = $raw
    }
  }
  return $overlay
}

function Read-DhConfig {
  param([string]$Path, [System.Collections.IDictionary]$Overrides)
  $defaults = Get-DhDefaultConfig
  $config = $defaults
  if ($Path) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Config file not found: $Path" }
    $config = Merge-DhConfig -Base $config -Overlay (Read-DhJsonFile -Path $Path)
  }
  $config = Merge-DhConfig -Base $config -Overlay (Get-DhEnvConfigOverlay -Defaults $defaults)
  if ($Overrides) { $config = Merge-DhConfig -Base $config -Overlay $Overrides }
  if (-not $config.acrResourceGroup) { $config.acrResourceGroup = $config.resourceGroup }
  if (-not (Get-DhValue $config 'evidenceStorage.resourceGroup')) { $config.evidenceStorage.resourceGroup = $config.resourceGroup }
  $config.workspaceEndpoint = ([string]$config.workspaceEndpoint).TrimEnd('/')
  $config.nodePools = @($config.nodePools)
  return $config
}

function Get-DhRequiredConfigFields {
  param([string[]]$Stages)
  $fields = [System.Collections.Generic.List[string]]::new()
  $azure = @($Stages | Where-Object { $_ -in $script:DhStages })
  if ($azure.Count -gt 0) { $fields.AddRange([string[]]@('subscriptionId', 'tenantId', 'resourceGroup')) }
  if ($Stages | Where-Object { $_ -in @('build', 'image-smoke', 'tool-register') }) { $fields.Add('acrName') }
  if ($Stages -contains 'tool-register') { $fields.Add('location') }
  if ($Stages | Where-Object { $_ -in @('tool-run', 'agent-register', 'round-trip') }) {
    $fields.AddRange([string[]]@('workspaceEndpoint', 'project', 'apiVersion'))
  }
  if ($Stages -contains 'agent-register') { $fields.Add('chatModel') }
  return @($fields | Select-Object -Unique)
}

function Test-DhConfig {
  <#
  .SYNOPSIS Returns a list of configuration problems (empty when valid).
  #>
  param([System.Collections.IDictionary]$Config, [string[]]$Stages = @())
  $problems = [System.Collections.Generic.List[string]]::new()
  $schemaPath = Join-Path $script:DhRoot 'schemas/config.schema.json'
  $json = ConvertTo-DhJson $Config
  $schemaErrors = $null
  $ok = Test-Json -Json $json -SchemaFile $schemaPath -ErrorAction SilentlyContinue -ErrorVariable schemaErrors
  if (-not $ok) {
    foreach ($err in @($schemaErrors)) { $problems.Add(('schema: {0}' -f $err.Exception.Message)) }
  }
  foreach ($field in (Get-DhRequiredConfigFields -Stages $Stages)) {
    $value = [string]$Config[$field]
    if ([string]::IsNullOrWhiteSpace($value) -or $value -match '^<.+>$') { $problems.Add("missing: $field") }
  }
  if ([string]::IsNullOrWhiteSpace([string]$Config.namePrefix)) { $problems.Add('namePrefix must be non-empty so deployed agents carry a test marker') }
  if ([string]::IsNullOrWhiteSpace([string]$Config.testTag)) { $problems.Add('testTag must be non-empty') }
  return $problems.ToArray()
}

function Register-DhConfigMasks {
  param([System.Collections.IDictionary]$Config)
  foreach ($key in @('subscriptionId', 'tenantId', 'resourceGroup', 'acrName', 'acrResourceGroup', 'project', 'chatModel', 'outputStorageContainerId')) {
    Add-DhMask ([string]$Config[$key])
  }
  if ($Config.workspaceEndpoint) {
    try { Add-DhMask ([Uri]$Config.workspaceEndpoint).Host } catch { }
  }
  Add-DhMask ([string](Get-DhValue $Config 'evidenceStorage.account'))
  foreach ($pool in @($Config.nodePools)) { if ($pool -is [System.Collections.IDictionary]) { Add-DhMask ([string]$pool.id) } }
  foreach ($key in @($Config.templateVariables.Keys)) { Add-DhMask ([string]$Config.templateVariables[$key]) }
}

function Get-DhPythonCommand {
  param([System.Collections.IDictionary]$Config)
  if ($Config -and $Config.pythonCommand) { return [string]$Config.pythonCommand }
  foreach ($candidate in @('python', 'python3')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
  }
  throw 'Python 3 is required for YAML parsing (python or python3 on PATH).'
}
