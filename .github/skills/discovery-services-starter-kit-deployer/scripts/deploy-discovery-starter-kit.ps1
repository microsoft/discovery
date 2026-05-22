param(
  [string]$StarterKitName,
  [string]$PublisherName,
  [ValidateSet('auto','remote','local')]
  [string]$BuildMode = 'auto',
  [string]$RunDir,
  [string]$KnowledgeBasesJson,
  [ValidateSet('init','build-tools','deploy-tools','deploy-agent','summary','stop')]
  [string]$Stage,
  [switch]$ConfirmSupercomputerNodepools,
  [switch]$WhatIfPlan,
  [Parameter(Position=0, ValueFromRemainingArguments=$true)]
  [string[]]$StarterKitArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:AZURE_CORE_COLLECT_TELEMETRY = 'no'

$BuildModeProvided = $PSBoundParameters.ContainsKey('BuildMode') -and $BuildMode -in @('remote','local')
$SkillRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = (git rev-parse --show-toplevel).Trim()

function Get-ConfigPath { Join-Path $SkillRoot 'config.json' }
function Get-TemplateConfigPath { Join-Path $SkillRoot 'config.template.json' }
function Get-AgentDeployerConfigPath { Join-Path (Split-Path -Parent $SkillRoot) 'discovery-services-agent-deployer\config.json' }

function Test-ConfigValuePresent {
  param($Value)
  if ($null -eq $Value) { return $false }
  $text = ([string]$Value).Trim()
  if ([string]::IsNullOrWhiteSpace($text)) { return $false }
  if ($text -like '<*>') { return $false }
  return $true
}

function Load-StarterConfig {
  param([string[]]$RequiredFields = @('subscriptionId','resourceGroup','acrName','location','workspaceEndpoint','project','tenantId','chatModel'))

  $configPath = Get-ConfigPath
  $templatePath = Get-TemplateConfigPath
  $agentConfigPath = Get-AgentDeployerConfigPath
  $config = [ordered]@{}
  $providedFieldNames = @()
  $starterConfigFieldNames = @()
  if (Test-Path $templatePath) {
    $template = Get-Content $templatePath -Raw | ConvertFrom-Json
    foreach ($p in $template.PSObject.Properties) { $config[$p.Name] = $p.Value }
  }
  if (Test-Path $agentConfigPath) {
    $agentConfig = Get-Content $agentConfigPath -Raw | ConvertFrom-Json
    foreach ($p in $agentConfig.PSObject.Properties) {
      $config[$p.Name] = $p.Value
      if ($providedFieldNames -notcontains $p.Name) { $providedFieldNames += $p.Name }
    }
  }
  if (Test-Path $configPath) {
    $local = Get-Content $configPath -Raw | ConvertFrom-Json
    $starterConfigFieldNames = @($local.PSObject.Properties.Name)
    foreach ($p in $local.PSObject.Properties) {
      $config[$p.Name] = $p.Value
      if ($providedFieldNames -notcontains $p.Name) { $providedFieldNames += $p.Name }
    }
  }
  foreach ($runScopedField in @('buildMode','confirmSupercomputerNodepools')) {
    if ($config.Contains($runScopedField)) { $config.Remove($runScopedField) }
  }
  foreach ($unsupportedStarterField in @('testPrompt','runReuseWindowMinutes','printAcrLogsOnFailure','deleteInvestigationAfterTest')) {
    if ($config.Contains($unsupportedStarterField)) { $config.Remove($unsupportedStarterField) }
  }
  if ((Test-Path $configPath) -and ($starterConfigFieldNames -notcontains 'acrResourceGroup') -and $config.Contains('acrResourceGroup')) {
    $config.Remove('acrResourceGroup')
  }
  if ((Test-Path $configPath) -and ($starterConfigFieldNames -notcontains 'forceToolImageRebuild') -and $config.Contains('forceToolImageRebuild')) {
    $config.Remove('forceToolImageRebuild')
    $providedFieldNames = @($providedFieldNames | Where-Object { $_ -ne 'forceToolImageRebuild' })
  }

  $explicitLocalFields = @('forceToolImageRebuild')
  $missing = @($RequiredFields | Where-Object {
    (-not (Test-ConfigValuePresent $config[$_])) -or
    (($explicitLocalFields -contains $_) -and ($providedFieldNames -notcontains $_))
  })
  if ($missing.Count -gt 0) {
    $suggested = [ordered]@{}
    foreach ($key in $config.Keys) {
      $suggested[$key] = $config[$key]
    }
    foreach ($field in $missing) {
      $suggested[$field] = ''
    }
    Write-Host 'CONFIG_INPUT_REQUIRED=true'
    Write-Host ("CONFIG_PATH={0}" -f $configPath)
    if (Test-Path $agentConfigPath) { Write-Host ("CONFIG_FALLBACK_PATH={0}" -f $agentConfigPath) }
    Write-Host ("CONFIG_MISSING_FIELDS={0}" -f ($missing -join ','))
    Write-Host ("CONFIG_FIELDS_TO_COLLECT={0}" -f ($missing -join ','))
    if ($RequiredFields -contains 'acrResourceGroup') {
      Write-Host 'CONFIG_OPTIONAL_FIELDS=acrResourceGroup'
    }
    Write-Host 'CONFIG_LOCATION_CHOICES=eastus,swedencentral,uksouth'
    Write-Host 'Suggested config.json shape:'
    Write-Host ($suggested | ConvertTo-Json -Depth 10)
    throw ("CONFIG_INPUT_REQUIRED: Missing required field(s): {0}. Copy config.template.json to config.json, fill these values, and rerun." -f ($missing -join ', '))
  }
  return $config
}

function Write-BuildModeInputRequest {
  param([string]$StarterKitName)
  Write-Host 'BUILD_MODE_INPUT_REQUIRED=true'
  Write-Host 'BUILD_MODE_INPUT_FORMAT=copilot'
  Write-Host 'BUILD_MODE_CHOICES=remote,local'
  Write-Host '--- COPILOT BUILD MODE INPUT REQUEST ---'
  Write-Host 'Ask the user to choose the build mode for this starter-kit deployment, then rerun init with -BuildMode <remote|local>. Do not store buildMode in config.json.'
  Write-Host '- remote: build and push tool images with Azure Container Registry Tasks.'
  Write-Host '- local: build tool images with local Docker, then push to ACR.'
  if (-not [string]::IsNullOrWhiteSpace($StarterKitName)) {
    Write-Host ("Suggested rerun command: pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 {0} -Stage init -BuildMode <remote|local>" -f $StarterKitName)
  }
  Write-Host '--- END COPILOT BUILD MODE INPUT REQUEST ---'
}

function Ensure-StateConfig {
  param(
    [string]$RunDir,
    [string[]]$RequiredFields
  )

  $state = Load-State -RunDir $RunDir
  $freshConfig = Load-StarterConfig -RequiredFields $RequiredFields
  foreach ($unsupportedStarterField in @('testPrompt','runReuseWindowMinutes','printAcrLogsOnFailure','deleteInvestigationAfterTest')) {
    if ($state.config.Contains($unsupportedStarterField)) { $state.config.Remove($unsupportedStarterField) }
  }
  if ((-not $freshConfig.Contains('acrResourceGroup')) -and $state.config.Contains('acrResourceGroup')) {
    $state.config.Remove('acrResourceGroup')
  }
  foreach ($key in $freshConfig.Keys) {
    $state.config[$key] = $freshConfig[$key]
  }
  foreach ($runScopedField in @('buildMode','confirmSupercomputerNodepools')) {
    if ($state.config.Contains($runScopedField)) { $state.config.Remove($runScopedField) }
  }
  Save-State -RunDir $RunDir -State $state | Out-Null
  return $state
}

function Resolve-StarterKit {
  param([string]$Name, [string]$Publisher)
  if ([string]::IsNullOrWhiteSpace($Name)) { throw 'StarterKitName is required.' }
  if ($Publisher) {
    Write-Host "[deployer] -PublisherName is deprecated in the flat starter-kits/ layout and is ignored."
  }
  $root = Join-Path $RepoRoot 'starter-kits'
  $kitPath = Join-Path (Join-Path $root $Name) 'kit.json'
  if (-not (Test-Path $kitPath)) { throw "Starter-kit '$Name' not found at '$kitPath' (expected starter-kits/$Name/kit.json)." }
  return Get-Item $kitPath
}

function Convert-RefToAgentInfo {
  param([string]$Ref)
  $normalized = ($Ref -replace '\\','/').Trim('/')
  if ($normalized -notmatch '^agents/(?<agent>[^/]+)$') {
    throw "Unsupported agentRef '$Ref'. Expected agents/<agent-name>."
  }
  $agentDir = Join-Path $RepoRoot ($normalized -replace '/', '\')
  $agentYaml = Join-Path $agentDir 'agent.yaml'
  if (-not (Test-Path $agentYaml)) { throw "agentRef '$Ref' does not exist at $agentYaml." }
  return [ordered]@{
    ref = $normalized
    name = $Matches.agent
    agentDir = $agentDir
    agentYaml = $agentYaml
  }
}

function Get-PluginAgentRefs {
  param([string]$PluginPath)
  $plugin = Get-Content $PluginPath -Raw | ConvertFrom-Json
  $refs = @($plugin.agentRefs | ForEach-Object { $_.ref })
  if ($refs.Count -eq 0) { throw "kit.json has no agentRefs entries." }
  $agents = @()
  foreach ($ref in $refs) { $agents += Convert-RefToAgentInfo -Ref $ref }
  return [ordered]@{ plugin = $plugin; agents = $agents }
}

function Get-AgentKnowledgeBaseRequirements {
  param([object[]]$Agents)
  python -c "import yaml" 2>$null
  if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyyaml | Out-Null }
  $payload = @($Agents | ForEach-Object {
    [ordered]@{ name = $_.name; ref = $_.ref; agentYaml = $_.agentYaml }
  }) | ConvertTo-Json -Depth 10 -Compress
  $script = @'
import json, sys, yaml
agents = json.loads(sys.argv[1])
if isinstance(agents, dict):
    agents = [agents]
rows = []
for agent in agents:
    doc = yaml.safe_load(open(agent["agentYaml"], encoding="utf-8")) or {}
    kbs = ((doc.get("discoveryExtensions") or {}).get("knowledgeBases") or [])
    if not kbs:
        continue
    rows.append({
        "agent": agent["name"],
        "ref": agent["ref"],
        "agentYaml": agent["agentYaml"],
        "knowledgeBases": kbs,
    })
print(json.dumps(rows))
'@
  $json = python -c $script $payload
  if ($LASTEXITCODE -ne 0) { throw 'Failed to inspect agent knowledgeBases.' }
  return @($json | ConvertFrom-Json)
}

function Resolve-KnowledgeBaseInput {
  param([object[]]$Requirements, [string]$InputJson)
  if (@($Requirements).Count -eq 0) { return @{} }
  if ([string]::IsNullOrWhiteSpace($InputJson)) {
    $suggested = [ordered]@{}
    foreach ($row in @($Requirements)) {
      $suggested[[string]$row.agent] = @(@($row.knowledgeBases) | ForEach-Object {
        [ordered]@{ knowledgeBaseId = '/bookshelves/<bookshelf-name>/knowledgeBases/<knowledgebase-name>/versions/<version>' }
      })
    }
    Write-Host 'KNOWLEDGE_BASE_INPUT_REQUIRED=true'
    Write-Host 'KNOWLEDGE_BASE_INPUT_FORMAT=json-file-or-inline-json'
    Write-Host 'KNOWLEDGE_BASE_ID_FORMAT=/bookshelves/{bookshelf_name}/knowledgeBases/{knowledgebase_name}/versions/{version}'
    foreach ($row in @($Requirements)) {
      Write-Host ("KNOWLEDGE_BASE_REQUIRED agent={0} count={1}" -f $row.agent, @($row.knowledgeBases).Count)
    }
    Write-Host 'Suggested KnowledgeBasesJson shape:'
    Write-Host ($suggested | ConvertTo-Json -Depth 20)
    throw 'KNOWLEDGE_BASE_INPUT_REQUIRED: Provide knowledge base details for the listed agents and rerun init with -KnowledgeBasesJson <json-or-path>.'
  }

  $raw = if (Test-Path $InputJson) { Get-Content $InputJson -Raw } else { $InputJson }
  $data = $raw | ConvertFrom-Json -AsHashtable
  foreach ($row in @($Requirements)) {
    $agentName = [string]$row.agent
    if (-not $data.ContainsKey($agentName)) { throw "KnowledgeBasesJson is missing required agent '$agentName'." }
    $items = @($data[$agentName])
    if ($items.Count -eq 0) { throw "KnowledgeBasesJson agent '$agentName' must include at least one knowledgeBaseId." }
    foreach ($item in $items) {
      $kbId = if ($item -is [System.Collections.IDictionary]) { [string]$item['knowledgeBaseId'] } else { [string]$item.knowledgeBaseId }
      if ($kbId -notmatch '^/bookshelves/[^/]+/knowledgeBases/[^/]+/versions/[^/]+$') {
        throw "Invalid knowledgeBaseId for agent '$agentName': '$kbId'. Expected /bookshelves/{bookshelf_name}/knowledgeBases/{knowledgebase_name}/versions/{version}."
      }
    }
  }
  return $data
}

function New-StarterRun {
  param([string]$StarterName, [string]$PluginPath, [object]$PluginData, [object[]]$Agents, [hashtable]$Config)
  $tmpRoot = Join-Path $RepoRoot 'starter-kits\tmp'
  $starterTmp = Join-Path $tmpRoot $StarterName
  New-Item -ItemType Directory -Path $starterTmp -Force | Out-Null
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $runDir = Join-Path $starterTmp $stamp
  New-Item -ItemType Directory -Path $runDir -Force | Out-Null
  $state = [ordered]@{
    starterKitName = $StarterName
    pluginPath = $PluginPath
    runDir = $runDir
    config = $Config
    plugin = $PluginData.plugin
    agents = $Agents
    agentRuns = @{}
    tools = @()
    deploy = @{}
  }
  Save-State -RunDir $runDir -State $state | Out-Null
  return $state
}

function Save-State {
  param([string]$RunDir, [object]$State)
  $path = Join-Path $RunDir 'run-state.json'
  $State | ConvertTo-Json -Depth 80 | Set-Content $path -Encoding UTF8
  return $path
}

function Load-State {
  param([string]$RunDir)
  $path = Join-Path $RunDir 'run-state.json'
  if (-not (Test-Path $path)) { throw "Missing run state: $path" }
  return Get-Content $path -Raw | ConvertFrom-Json -AsHashtable
}

function Set-StageStatus {
  param([string]$RunDir, [string]$StageName, [string]$Status)
  if ([string]::IsNullOrWhiteSpace($RunDir) -or -not (Test-Path $RunDir)) { return }
  $path = Join-Path $RunDir 'stage-todos.json'
  $stageIds = @('init','build-tools','deploy-tools','deploy-agent','summary')
  $stages = $stageIds | ForEach-Object {
    [ordered]@{ id = $_; status = if ($_ -eq $StageName) { $Status } else { 'pending' } }
  }
  if (Test-Path $path) {
    $existing = Get-Content $path -Raw | ConvertFrom-Json
    foreach ($row in $stages) {
      $old = @($existing | Where-Object { $_.id -eq $row.id }) | Select-Object -First 1
      if ($old -and $row.id -ne $StageName) { $row.status = $old.status }
    }
  }
  $stages | ConvertTo-Json -Depth 5 | Set-Content $path -Encoding UTF8
  Write-Host ("TASK_STATUS={0}:{1}" -f $StageName, $Status)
}

function Set-AllStageStatuses {
  param([string]$RunDir, [string]$Status)
  if ([string]::IsNullOrWhiteSpace($RunDir) -or -not (Test-Path $RunDir)) { return }
  $path = Join-Path $RunDir 'stage-todos.json'
  $stageIds = @('init','build-tools','deploy-tools','deploy-agent','summary')
  $stages = $stageIds | ForEach-Object {
    [ordered]@{ id = $_; status = $Status }
  }
  $stages | ConvertTo-Json -Depth 5 | Set-Content $path -Encoding UTF8
  foreach ($stageId in $stageIds) {
    Write-Host ("TASK_STATUS={0}:{1}" -f $stageId, $Status)
  }
}

function Invoke-CheckedStage {
  param([string]$Name, [string]$RunDir, [scriptblock]$Body)
  Set-StageStatus -RunDir $RunDir -StageName $Name -Status 'in_progress'
  Write-Host ("[starter-runner] START {0}" -f $Name)
  try {
    & $Body
    Set-StageStatus -RunDir $RunDir -StageName $Name -Status 'done'
    Write-Host ("[starter-runner] DONE {0}" -f $Name)
  } catch {
    $errorMessage = $_.Exception.Message
    if ($errorMessage -match '^[A-Z_]+_(INPUT|CONFIRMATION)_REQUIRED:') {
      Set-StageStatus -RunDir $RunDir -StageName $Name -Status 'input_required'
      Write-Host ("[starter-runner] INPUT_REQUIRED {0}" -f $Name)
      return
    } else {
      Set-StageStatus -RunDir $RunDir -StageName $Name -Status 'failed'
    }
    throw
  }
}

function Test-DockerAvailable {
  try {
    docker --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { return $false }
    docker ps 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Get-AgentToolContexts {
  param([hashtable]$State)
  $contexts = @()
  foreach ($agent in @($State.agents)) {
    $toolsDir = Join-Path ([string]$agent.agentDir) 'tools'
    if (-not (Test-Path $toolsDir)) { continue }
    foreach ($toolDir in @(Get-ChildItem $toolsDir -Directory | Sort-Object Name)) {
      $toolYaml = Join-Path $toolDir.FullName 'tool.yaml'
      $dockerfile = Join-Path $toolDir.FullName 'Dockerfile'
      if (-not (Test-Path $toolYaml)) { continue }
      if (-not (Test-Path $dockerfile)) { throw "Missing Dockerfile for tool '$($toolDir.Name)' at $dockerfile." }
      $toolCopyRoot = Join-Path $State.runDir ("tools\{0}\{1}" -f $agent.name, $toolDir.Name)
      New-Item -ItemType Directory -Path $toolCopyRoot -Force | Out-Null
      $tempToolYaml = Join-Path $toolCopyRoot 'tool.yaml'
      Copy-Item $toolYaml $tempToolYaml -Force
      (Get-Content $tempToolYaml) -replace '\{name\}\.azurecr\.io', "$($State.config.acrName).azurecr.io" | Set-Content $tempToolYaml -Encoding UTF8

      python -c "import yaml" 2>$null
      if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyyaml | Out-Null }
      $parseToolPy = Join-Path $toolCopyRoot 'parse_tool.py'
      @'
import json, re, sys, yaml
d = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
acr = (d.get("image") or {}).get("acr", "")
skus = []
def add_sku(value):
    if value is None:
        return
    values = value if isinstance(value, list) else [value]
    for sku in values:
        if sku is not None:
            text = str(sku)
            if text and text not in skus:
                skus.append(text)
def walk(value):
    if isinstance(value, dict):
        if "recommended_sku" in value:
            add_sku(value.get("recommended_sku"))
        for child in value.values():
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)
for entry in (d.get("infra") or []):
    img = entry.get("image") or {}
    if not acr and img.get("acr"):
        acr = img["acr"]
walk(d)
m = re.search(r"/([^:/\s]+):([^\"'\s]+)", acr)
print(json.dumps({
    "name": d.get("name", ""),
    "category": d.get("category", "General"),
    "image": m.group(1) if m else "",
    "tag": m.group(2) if m else "",
    "recommendedSkus": skus,
}))
'@ | Set-Content $parseToolPy -Encoding UTF8
      $toolMeta = python $parseToolPy $tempToolYaml | ConvertFrom-Json
      if (-not $toolMeta.name) { throw "tool.yaml has no name: $tempToolYaml" }
      if (-not $toolMeta.image -or -not $toolMeta.tag) { throw "Could not parse image:tag from tool.yaml image.acr: $tempToolYaml" }
      $contexts += [ordered]@{
        agent = [string]$agent.name
        name = [string]$toolMeta.name
        category = [string]$toolMeta.category
        toolDir = $toolDir.FullName
        dockerfile = $dockerfile
        tempToolYaml = $tempToolYaml
        imageName = [string]$toolMeta.image
        imageTag = [string]$toolMeta.tag
        imageRef = "$($State.config.acrName).azurecr.io/$($toolMeta.image):$($toolMeta.tag)"
        recommendedSkus = @($toolMeta.recommendedSkus)
      }
    }
  }
  return $contexts
}

function Test-AcrTagExists {
  param([string]$AcrName, [string]$Repository, [string]$Tag, [string]$SubscriptionId)
  $args = @('acr','repository','show-tags','--name',$AcrName,'--repository',$Repository,'-o','tsv','--only-show-errors')
  if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) { $args += @('--subscription', $SubscriptionId) }
  $tags = az @args 2>$null
  if ($LASTEXITCODE -ne 0) { return $false }
  return (($tags -split "`r?`n") -contains $Tag)
}

function Invoke-AzRestJson {
  param([string]$Method, [string]$Url, [string]$BodyPath)
  $args = @('rest', '--method', $Method, '--url', $Url, '--output', 'json', '--only-show-errors')
  if ($BodyPath) { $args += @('--body', "@$BodyPath", '--headers', 'Content-Type=application/json') }
  $raw = az @args 2>&1
  if ($LASTEXITCODE -ne 0) { throw ($raw | Out-String) }
  return ($raw | Out-String)
}

function Get-AcrResourceGroup {
  param([hashtable]$Config)
  if ($Config.ContainsKey('acrResourceGroup') -and -not [string]::IsNullOrWhiteSpace([string]$Config.acrResourceGroup)) { return [string]$Config.acrResourceGroup }
  return [string]$Config.resourceGroup
}

function Test-ConfigFlag {
  param([hashtable]$Config, [string]$Name)
  if (-not $Config.ContainsKey($Name) -or $null -eq $Config[$Name]) { return $false }
  if ($Config[$Name] -is [bool]) { return [bool]$Config[$Name] }
  return ([string]$Config[$Name]).Trim().ToLowerInvariant() -in @('1','true','yes','y','on')
}

function Write-ToolBuildPlan {
  param([object[]]$ToolContexts)
  Write-Host '=== TOOL BUILD PLAN ==='
  foreach ($tool in $ToolContexts) {
    $skuText = if (@($tool.recommendedSkus).Count -gt 0) { (@($tool.recommendedSkus) -join ',') } else { '<none specified>' }
    Write-Host ("TOOL_BUILD_PLAN tool={0} agent={1} image={2} recommendedSkus={3}" -f $tool.name, $tool.agent, $tool.imageRef, $skuText)
  }
}

function Write-BuildPlanJson {
  param([string]$RunDir, [object[]]$ToolContexts)
  if ([string]::IsNullOrWhiteSpace($RunDir) -or -not (Test-Path $RunDir)) { return }
  $planPath = Join-Path $RunDir 'build-plan.json'
  $plan = [ordered]@{
    generatedAt = (Get-Date).ToString('o')
    semantics = 'recommendedSkus are alternative Supercomputer nodepool choices; confirm capacity for at least one listed SKU per tool before building.'
    tools = @($ToolContexts | ForEach-Object {
      [ordered]@{
        agent = [string]$_.agent
        tool = [string]$_.name
        image = [string]$_.imageRef
        imageName = [string]$_.imageName
        imageTag = [string]$_.imageTag
        toolYaml = [string]$_.tempToolYaml
        dockerfile = [string]$_.dockerfile
        recommendedSkus = @($_.recommendedSkus)
      }
    })
  }
  $plan | ConvertTo-Json -Depth 20 | Set-Content $planPath -Encoding UTF8
  Write-Host ("BUILD_PLAN_JSON={0}" -f $planPath)
}

function Assert-SupercomputerNodepoolConfirmed {
  param([bool]$Confirmed, [object[]]$ToolContexts, [string]$RunDir)
  if ($Confirmed) { return }
  Write-Host 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED=true'
  Write-Host 'SUPERCOMPUTER_NODEPOOL_SKU_SEMANTICS=The recommendedSkus listed for each tool are alternative nodepool choices; confirm capacity for at least one listed SKU per tool.'
  Write-Host 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_CHOICES=Proceed - I have Supercomputer nodepool capacity for at least one listed SKU per tool|Stop - I do not have the required Supercomputer nodepool capacity'
  Write-Host 'SUPERCOMPUTER_NODEPOOL_STOP_GUIDANCE=When you have Supercomputer nodepool capacity for at least one of the listed SKUs per tool, rerun the skill.'
  Write-Host 'If the customer chooses Proceed, rerun build-tools with -ConfirmSupercomputerNodepools. Do not write confirmSupercomputerNodepools to config.json. If the customer chooses Stop, run -Stage stop for this RunDir.'
  if (-not [string]::IsNullOrWhiteSpace($RunDir)) {
    Write-Host ("Proceed rerun command: pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 -RunDir `"{0}`" -Stage build-tools -ConfirmSupercomputerNodepools" -f $RunDir)
    Write-Host ("Stop command: pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 -RunDir `"{0}`" -Stage stop" -f $RunDir)
  }
  throw 'SUPERCOMPUTER_NODEPOOL_CONFIRMATION_REQUIRED: Ask the customer to proceed or stop based on Supercomputer nodepool capacity before building tools.'
}

function Get-AcrBuildRunStatus {
  param([string]$AcrName, [string]$RunId, [string]$SubscriptionId)
  $raw = az acr task show-run --registry $AcrName --run-id $RunId --subscription $SubscriptionId --query status -o tsv --only-show-errors 2>$null
  if ($LASTEXITCODE -ne 0) { return '' }
  return ([string]$raw).Trim()
}

function Get-AcrBuildRunId {
  param([string]$Raw)
  $text = ($Raw | Out-String).Trim()
  if ([string]::IsNullOrWhiteSpace($text)) { return '' }
  try {
    $json = $text | ConvertFrom-Json
    foreach ($name in @('runId','id','name')) {
      if ($json.PSObject.Properties.Name -contains $name -and $json.$name) { return [string]$json.$name }
    }
  } catch {
  }
  $match = [regex]::Match($text, '(?im)\b(?:Run ID|runId|id)\s*[:=]\s*([a-zA-Z0-9_-]+)')
  if ($match.Success) { return $match.Groups[1].Value }
  return ''
}

function Invoke-BuildTools {
  param([string]$RunDir)
  $state = Load-State -RunDir $RunDir
  $toolContexts = @(Get-AgentToolContexts -State $state)
  Write-ToolBuildPlan -ToolContexts $toolContexts
  Write-BuildPlanJson -RunDir $RunDir -ToolContexts $toolContexts
  $nodepoolConfirmed = [bool]$ConfirmSupercomputerNodepools -or ($state.ContainsKey('nodepoolConfirmed') -and [bool]$state.nodepoolConfirmed)
  Assert-SupercomputerNodepoolConfirmed -Confirmed $nodepoolConfirmed -ToolContexts $toolContexts -RunDir $RunDir
  if ($ConfirmSupercomputerNodepools -and (-not ($state.ContainsKey('nodepoolConfirmed') -and [bool]$state.nodepoolConfirmed))) {
    $state['nodepoolConfirmed'] = $true
    Save-State -RunDir $RunDir -State $state | Out-Null
  }
  $state = Ensure-StateConfig -RunDir $RunDir -RequiredFields @('subscriptionId','resourceGroup','acrName','location','forceToolImageRebuild')
  $acrResourceGroup = Get-AcrResourceGroup -Config $state.config
  $forceToolImageRebuild = Test-ConfigFlag -Config $state.config -Name 'forceToolImageRebuild'
  az acr show --name $state.config.acrName --resource-group $acrResourceGroup --subscription $state.config.subscriptionId --query id -o tsv --only-show-errors | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "ACR '$($state.config.acrName)' was not found in resource group '$acrResourceGroup' for subscription '$($state.config.subscriptionId)'. Set config.acrResourceGroup when the registry is not in config.resourceGroup." }
  $dockerAvailable = Test-DockerAvailable
  $mode = $BuildMode
  if ($mode -eq 'auto' -and $state.ContainsKey('buildMode') -and $state.buildMode -in @('remote','local')) { $mode = [string]$state.buildMode }
  if ($mode -eq 'auto') { $mode = if ($dockerAvailable) { 'remote' } else { 'remote' } }
  if ($mode -eq 'local' -and -not $dockerAvailable) { throw 'Local build requested but Docker daemon is not available.' }
  $buildRows = @()
  $failedBuilds = @()
  $queuedRemoteBuilds = @()
  foreach ($tool in $toolContexts) {
    Write-Host ("[build-tools] agent={0} tool={1} image={2}" -f $tool.agent, $tool.name, $tool.imageRef)
    $row = [ordered]@{
      agent = $tool.agent
      name = $tool.name
      imageRef = $tool.imageRef
      imageName = $tool.imageName
      imageTag = $tool.imageTag
      recommendedSkus = @($tool.recommendedSkus)
      status = 'pending'
      runId = ''
      message = ''
    }
    $tagExists = Test-AcrTagExists -AcrName $state.config.acrName -Repository $tool.imageName -Tag $tool.imageTag -SubscriptionId $state.config.subscriptionId
    if ($tagExists) {
      if (-not $forceToolImageRebuild) {
        Write-Host ("[build-tools] Reusing existing ACR tag {0}:{1}" -f $tool.imageName, $tool.imageTag)
        $row.status = 'reused'
        $row.message = 'Existing ACR tag reused.'
        $buildRows += $row
        continue
      }
      Write-Host ("[build-tools] forceToolImageRebuild=true; rebuilding existing ACR tag {0}:{1}" -f $tool.imageName, $tool.imageTag)
    }
    if ($mode -eq 'local') {
      docker build -t $tool.imageRef -f $tool.dockerfile $tool.toolDir
      if ($LASTEXITCODE -ne 0) { throw "Local docker build failed for $($tool.name)." }
      az acr login --name $state.config.acrName --subscription $state.config.subscriptionId | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "ACR login failed for $($state.config.acrName)." }
      docker push $tool.imageRef
      if ($LASTEXITCODE -ne 0) { throw "docker push failed for $($tool.imageRef)." }
      $row.status = 'succeeded'
      $row.message = 'Local Docker build and push completed.'
      $buildRows += $row
    } else {
      Write-Host ("[build-tools] Queueing ACR build for {0}:{1}" -f $tool.imageName, $tool.imageTag)
      $queueOutput = az acr build --registry $state.config.acrName --resource-group $acrResourceGroup --subscription $state.config.subscriptionId --image "$($tool.imageName):$($tool.imageTag)" --file $tool.dockerfile --no-wait --output json $tool.toolDir 2>&1
      if ($LASTEXITCODE -ne 0) {
        $row.status = 'failed'
        $row.message = "Failed to queue ACR build: $($queueOutput | Out-String)"
        $failedBuilds += $row
      } else {
        $row.status = 'queued'
        $row.runId = Get-AcrBuildRunId -Raw ($queueOutput | Out-String)
        $row.message = if ($row.runId) { "Queued ACR build run $($row.runId)." } else { 'Queued ACR build; run id was not returned by Azure CLI.' }
        Write-Host ("[build-tools] {0}" -f $row.message)
        $queuedRemoteBuilds += [ordered]@{ tool = $tool; row = $row; force = $forceToolImageRebuild }
      }
      $buildRows += $row
    }
  }
  if ($mode -ne 'local' -and $queuedRemoteBuilds.Count -gt 0) {
    $deadline = (Get-Date).AddHours(2)
    do {
      $pending = 0
      foreach ($item in $queuedRemoteBuilds) {
        $row = $item.row
        if ($row.status -in @('succeeded','failed')) { continue }
        $tool = $item.tool
        $status = if ($row.runId) { Get-AcrBuildRunStatus -AcrName $state.config.acrName -RunId $row.runId -SubscriptionId $state.config.subscriptionId } else { '' }
        if ($status -in @('Succeeded','succeeded')) {
          $row.status = 'succeeded'
          $row.message = "ACR build run $($row.runId) succeeded."
          Write-Host ("[build-tools] {0} {1}" -f $tool.name, $row.message)
          continue
        }
        if ($status -in @('Failed','failed','Canceled','Cancelled','canceled','cancelled','Error','error','Timeout','timeout')) {
          $row.status = 'failed'
          $row.message = "ACR build run $($row.runId) ended with status $status."
          $failedBuilds += $row
          Write-Host ("[build-tools] {0} {1}" -f $tool.name, $row.message)
          continue
        }
        if (-not $row.runId -and -not $item.force -and (Test-AcrTagExists -AcrName $state.config.acrName -Repository $tool.imageName -Tag $tool.imageTag -SubscriptionId $state.config.subscriptionId)) {
          $row.status = 'succeeded'
          $row.message = 'ACR tag appeared after queued build.'
          continue
        }
        $pending++
      }
      if ($pending -eq 0) { break }
      if ((Get-Date) -gt $deadline) {
        foreach ($item in $queuedRemoteBuilds) {
          $row = $item.row
          if ($row.status -notin @('succeeded','failed')) {
            $row.status = 'failed'
            $row.message = 'Timed out waiting for ACR build completion.'
            $failedBuilds += $row
          }
        }
        break
      }
      Start-Sleep -Seconds 20
    } while ($true)
  }
  $state['build'] = @{ tools = $toolContexts; buildStatus = $buildRows; completedAt = (Get-Date).ToString('o') }
  Save-State -RunDir $RunDir -State $state | Out-Null
  if ($failedBuilds.Count -gt 0) {
    Write-Host 'TOOL_BUILD_FAILURES='
    foreach ($failure in $failedBuilds) {
      Write-Host ("- tool={0} image={1} status={2} message={3}" -f $failure.name, $failure.imageRef, $failure.status, $failure.message)
    }
    throw ("One or more tool image builds failed: {0}" -f ((@($failedBuilds) | ForEach-Object { $_.name }) -join ', '))
  }
}

function Invoke-DeployTools {
  param([string]$RunDir)
  $state = Ensure-StateConfig -RunDir $RunDir -RequiredFields @('subscriptionId','resourceGroup','acrName','location')
  foreach ($tool in @($state.build.tools)) {
    $toolJson = Join-Path (Split-Path -Parent $tool.tempToolYaml) 'tool.json'
    python -c "import yaml,json,sys; json.dump(yaml.safe_load(open(sys.argv[1], encoding='utf-8')), open(sys.argv[2], 'w', encoding='utf-8'), indent=2)" $tool.tempToolYaml $toolJson
  }
  $deployPlanPath = Join-Path $RunDir 'deploy-tools-plan.json'
  @{
    config = @{
      subscriptionId = $state.config.subscriptionId
      resourceGroup = $state.config.resourceGroup
      location = $state.config.location
      apiVersion = $state.config.apiVersion
    }
    tools = @($state.build.tools | ForEach-Object {
      [ordered]@{
        agent = $_.agent
        name = $_.name
        category = $_.category
        toolJson = (Join-Path (Split-Path -Parent $_.tempToolYaml) 'tool.json')
      }
    })
  } | ConvertTo-Json -Depth 50 | Set-Content $deployPlanPath -Encoding UTF8
  $deployPy = Join-Path $RunDir 'deploy_tools_parallel.py'
  @'
import concurrent.futures, json, re, shutil, subprocess, sys, time

plan = json.load(open(sys.argv[1], encoding="utf-8"))
cfg = plan["config"]

def az_rest(method, url, body_path=None):
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        raise RuntimeError("Azure CLI executable not found in PATH")
    args = [az, "rest", "--method", method, "--url", url, "--output", "json", "--only-show-errors"]
    if body_path:
        args += ["--body", f"@{body_path}", "--headers", "Content-Type=application/json"]
    res = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip())
    return res.stdout.strip()

def deploy_tool(item):
    tool_name = re.sub(r"[^a-z0-9]", "", item["name"].lower())
    definition = json.load(open(item["toolJson"], encoding="utf-8"))
    body_path = item["toolJson"].replace("tool.json", "arm-body.json")
    with open(body_path, "w", encoding="utf-8") as f:
        json.dump({
            "location": cfg["location"],
            "tags": {"category": item.get("category") or "General"},
            "properties": {"version": "1.0.0", "definitionContent": definition},
        }, f, indent=2)
    url = f"https://management.azure.com/subscriptions/{cfg['subscriptionId']}/resourceGroups/{cfg['resourceGroup']}/providers/Microsoft.Discovery/tools/{tool_name}?api-version={cfg['apiVersion']}"
    az_rest("put", url, body_path)
    deadline = time.time() + 1800
    while True:
        time.sleep(15)
        result = json.loads(az_rest("get", url))
        state = str((result.get("properties") or {}).get("provisioningState") or "")
        print(f"[deploy-tools] tool={tool_name} state={state}", flush=True)
        if state in ("Failed", "Canceled"):
            raise RuntimeError(f"Tool '{tool_name}' provisioning ended in {state}.")
        if state == "Succeeded":
            rid = f"/subscriptions/{cfg['subscriptionId']}/resourceGroups/{cfg['resourceGroup']}/providers/Microsoft.Discovery/tools/{tool_name}"
            return {"agent": item["agent"], "tool": tool_name, "toolResourceId": rid}
        if time.time() > deadline:
            raise TimeoutError(f"Timed out waiting for tool '{tool_name}' provisioning.")

rows = []
workers = max(1, min(8, len(plan.get("tools") or [])))
with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
    futures = [executor.submit(deploy_tool, item) for item in plan.get("tools") or []]
    for future in concurrent.futures.as_completed(futures):
        row = future.result()
        print(f"TOOL_RESOURCE_ID={row['toolResourceId']}", flush=True)
        rows.append(row)

json.dump(rows, open(sys.argv[2], "w", encoding="utf-8"), indent=2)
'@ | Set-Content $deployPy -Encoding UTF8
  $toolRowsPath = Join-Path $RunDir 'deployed-tools.json'
  python $deployPy $deployPlanPath $toolRowsPath
  if ($LASTEXITCODE -ne 0) { throw 'One or more tool deployments failed.' }
  $toolRows = Get-Content $toolRowsPath -Raw | ConvertFrom-Json
  $state.tools = $toolRows
  Save-State -RunDir $RunDir -State $state | Out-Null
}

function Invoke-DeployReferencedAgents {
  param([string]$RunDir)
  $state = Ensure-StateConfig -RunDir $RunDir -RequiredFields @('subscriptionId','resourceGroup','workspaceEndpoint','project','tenantId','chatModel')
  $agentDeployRoot = Join-Path $RunDir 'agents'
  New-Item -ItemType Directory -Path $agentDeployRoot -Force | Out-Null
  $deployConfigPath = Join-Path $RunDir 'agents-deploy-config.json'
  $config = $state.config
  @{
    workspaceEndpoint = $config.workspaceEndpoint
    apiVersion = $config.apiVersion
    project = $config.project
    model = $config.chatModel
    tenantId = $config.tenantId
    resourceGroup = "/subscriptions/$($config.subscriptionId)/resourceGroups/$($config.resourceGroup)"
  } | ConvertTo-Json -Depth 8 | Set-Content $deployConfigPath -Encoding UTF8
  python -c "import yaml, requests" 2>$null
  if ($LASTEXITCODE -ne 0) { python -m pip install --quiet pyyaml requests | Out-Null }
  $deployPlanPath = Join-Path $RunDir 'deploy-agents-plan.json'
  @{
    agents = @($state.agents | ForEach-Object {
      [ordered]@{
        name = $_.name
        ref = $_.ref
        agentYaml = $_.agentYaml
      }
    })
    tools = @($state.tools)
    knowledgeBases = if ($state.ContainsKey('knowledgeBases')) { $state.knowledgeBases } else { @{} }
    outputDir = $agentDeployRoot
  } | ConvertTo-Json -Depth 30 | Set-Content $deployPlanPath -Encoding UTF8
  $deployPy = Join-Path $RunDir 'deploy_agents_parallel.py'
  @'
import concurrent.futures, copy, json, os, re, shutil, subprocess, sys, time, yaml, requests

cfg = json.load(open(sys.argv[1], encoding="utf-8"))
plan = json.load(open(sys.argv[2], encoding="utf-8"))

def token():
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        raise RuntimeError("Azure CLI executable not found in PATH")
    res = subprocess.run(
        [az, "account", "get-access-token", "--resource", "https://discovery.azure.com", "--query", "accessToken", "-o", "tsv", "--only-show-errors"],
        capture_output=True, text=True, check=True, timeout=90)
    return res.stdout.strip()

def prompt_definition(agent):
    out = {"kind": "prompt"}
    model = agent.get("model") or {}
    if isinstance(model, dict):
        out["model"] = model.get("id", cfg.get("model", ""))
        options = model.get("options") or {}
        if "temperature" in options:
            out["temperature"] = options["temperature"]
    if "instructions" in agent:
        out["instructions"] = agent["instructions"]
    return out

def tool_leaf(tool_id):
    return str(tool_id or "").rstrip("/").split("/")[-1].lower()

def is_arm_tool_id(tool_id):
    return bool(re.match(r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/[^/]+/[^/]+/[^/]+$", str(tool_id or ""), flags=re.IGNORECASE))

def patch_agent_doc(agent_item):
    doc = yaml.safe_load(open(agent_item["agentYaml"], encoding="utf-8")) or {}
    doc["model"] = {"id": cfg.get("model", ""), "options": (doc.get("model") or {}).get("options") or {"temperature": 0}}
    ext = copy.deepcopy(doc.get("discoveryExtensions") or {})
    ext["humanInTheLoop"] = "Disabled"
    deployed_for_agent = [t for t in plan.get("tools") or [] if str(t.get("agent")) == str(agent_item["name"])]
    deployed_by_leaf = {tool_leaf(t.get("toolResourceId")): t.get("toolResourceId") for t in deployed_for_agent}
    patched_tools = []
    seen = set()
    for item in ext.get("tools") or []:
        candidate = copy.deepcopy(item) if isinstance(item, dict) else {"toolId": str(item)}
        current = str(candidate.get("toolId") or "")
        leaf = tool_leaf(current)
        if leaf in deployed_by_leaf:
            candidate["toolId"] = deployed_by_leaf[leaf]
        elif ("{{" in current and "}}" in current) or not is_arm_tool_id(current):
            if len(deployed_for_agent) == 1 and deployed_for_agent[0].get("toolResourceId"):
                candidate["toolId"] = deployed_for_agent[0]["toolResourceId"]
            else:
                raise RuntimeError(f"{agent_item['name']} has unresolved or invalid toolId '{current}' and {len(deployed_for_agent)} deployed tools; cannot patch unambiguously.")
        if candidate.get("toolId") and candidate["toolId"] not in seen:
            seen.add(candidate["toolId"])
            candidate["confirmation"] = "Disabled"
            patched_tools.append(candidate)
    if not patched_tools:
        patched_tools = [{"toolId": t["toolResourceId"], "confirmation": "Disabled"} for t in deployed_for_agent if t.get("toolResourceId")]
    ext["tools"] = patched_tools
    provided_kbs = (plan.get("knowledgeBases") or {}).get(agent_item["name"])
    if provided_kbs is not None:
        ext["knowledgeBases"] = provided_kbs
    elif ext.get("knowledgeBases"):
        unresolved = [kb for kb in ext.get("knowledgeBases") or [] if "{{" in str(kb.get("knowledgeBaseId", "")) or not re.match(r"^/bookshelves/[^/]+/knowledgeBases/[^/]+/versions/[^/]+$", str(kb.get("knowledgeBaseId", "")))]
        if unresolved:
            raise RuntimeError(f"{agent_item['name']} has unresolved knowledgeBases but no values were provided in KnowledgeBasesJson.")
    doc["discoveryExtensions"] = ext
    return doc

def write_agent_yaml(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=False)

def response_details(resp, body):
    interesting_headers = {
        key: value for key, value in resp.headers.items()
        if key.lower() in {
            "x-ms-request-id",
            "x-ms-correlation-request-id",
            "x-ms-error-code",
            "request-id",
            "operation-location",
            "www-authenticate",
        }
    }
    return {
        "statusCode": resp.status_code,
        "reason": resp.reason,
        "headers": interesting_headers,
        "body": body,
        "bodyPreview": str(body)[:2000],
    }

def deploy_agent(agent_item):
    doc = patch_agent_doc(agent_item)
    os.makedirs(plan["outputDir"], exist_ok=True)
    out_path = os.path.join(plan["outputDir"], f"{agent_item['name']}.agent.yaml")
    write_agent_yaml(out_path, doc)
    payload = {
        "name": doc["name"],
        "humanInTheLoop": (doc.get("discoveryExtensions") or {}).get("humanInTheLoop", "Disabled"),
        "tools": (doc.get("discoveryExtensions") or {}).get("tools", []),
        "foundryDetails": {
            "description": doc.get("description", ""),
            "definition": prompt_definition(doc),
        },
    }
    remaining = {k: v for k, v in (doc.get("discoveryExtensions") or {}).items() if k not in {"humanInTheLoop", "tools", "knowledgeBases"}}
    if remaining:
        payload["discoveryExtensions"] = remaining
    if (doc.get("discoveryExtensions") or {}).get("knowledgeBases"):
        payload["knowledgeBases"] = doc["discoveryExtensions"]["knowledgeBases"]
    payload_path = os.path.join(plan["outputDir"], f"{agent_item['name']}.payload.json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    url = f"{cfg['workspaceEndpoint'].rstrip('/')}/projects/{cfg['project']}:upsertAgent?api-version={cfg['apiVersion']}"
    headers = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json", "Accept": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    body = resp.json() if "application/json" in resp.headers.get("content-type", "") else resp.text
    if resp.status_code >= 400:
        details = response_details(resp, body)
        error_path = os.path.join(plan["outputDir"], f"{agent_item['name']}.upsert-error.json")
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump({
                "agent": agent_item["name"],
                "url": url,
                "payloadPath": payload_path,
                "response": details,
            }, f, indent=2)
        raise RuntimeError(f"{agent_item['name']} upsertAgent failed: HTTP {resp.status_code} {resp.reason}; details={error_path}; requestHeaders={details['headers']}; bodyPreview={details['bodyPreview']}")
    op = resp.headers.get("operation-location") or resp.headers.get("Operation-Location") or (body.get("operationLocation") if isinstance(body, dict) else "")
    if op:
        for _ in range(40):
            time.sleep(15)
            poll = requests.get(op, headers={"Authorization": f"Bearer {token()}", "Accept": "application/json"}, timeout=60)
            if poll.status_code != 200:
                continue
            status = poll.json().get("status")
            print(f"[deploy-agent] agent={agent_item['name']} operation={status}", flush=True)
            if status in ("Succeeded", "Failed", "Canceled"):
                if status != "Succeeded":
                    raise RuntimeError(f"{agent_item['name']} agent operation ended in {status}")
                break
    return {"agent": agent_item["name"], "ref": agent_item.get("ref", ""), "name": doc["name"], "agentYaml": out_path, "payloadPath": payload_path, "tools": (doc.get("discoveryExtensions") or {}).get("tools", [])}

rows = []
failures = []
workers = max(1, min(6, len(plan.get("agents") or [])))
with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
    futures = {executor.submit(deploy_agent, item): item for item in plan.get("agents") or []}
    for future in concurrent.futures.as_completed(futures):
        item = futures[future]
        try:
            row = future.result()
            print(f"AGENT_DEPLOYED={row['name']}", flush=True)
            print(f"AGENT_YAML={row['agentYaml']}", flush=True)
            rows.append(row)
        except Exception as ex:
            failure = {"agent": item.get("name", ""), "error": str(ex)}
            failures.append(failure)
            print(f"AGENT_DEPLOY_FAILED={failure['agent']} error={failure['error']}", flush=True)

result = {"succeeded": rows, "failed": failures}
json.dump(result, open(sys.argv[3], "w", encoding="utf-8"), indent=2)
if failures:
    raise SystemExit("One or more agents failed to deploy. See deployed-agents.json and any *.upsert-error.json files in the run agents directory.")
'@ | Set-Content $deployPy -Encoding UTF8
  $deployedAgentsPath = Join-Path $RunDir 'deployed-agents.json'
  python $deployPy $deployConfigPath $deployPlanPath $deployedAgentsPath
  if ($LASTEXITCODE -ne 0) { throw 'One or more starter-kit agent deployments failed.' }
  $state.deploy['deployConfigPath'] = $deployConfigPath
  $deployResult = Get-Content $deployedAgentsPath -Raw | ConvertFrom-Json
  $state.deploy['agents'] = @($deployResult.succeeded)
  $state.deploy['failedAgents'] = @($deployResult.failed)
  $state.deploy['deployedAgentsPath'] = $deployedAgentsPath
  $state.deploy['completedAt'] = (Get-Date).ToString('o')
  Save-State -RunDir $RunDir -State $state | Out-Null
}

function Invoke-Summary {
  param([string]$RunDir)
  $state = Load-State -RunDir $RunDir
  Write-Host '=== discovery-services-starter-kit-deployer SUMMARY ==='
  Write-Host ("RUN_DIR={0}" -f $state.runDir)
  Write-Host ("STARTER_KIT={0}" -f $state.starterKitName)
  Write-Host ("AGENTS={0}" -f ((@($state.agents) | ForEach-Object { $_.name }) -join ','))
  foreach ($agent in @($state.deploy.agents)) {
    Write-Host ("AGENT_DEPLOYED={0}" -f $agent.name)
    if ($agent.agentYaml) { Write-Host ("AGENT_YAML={0}" -f $agent.agentYaml) }
  }
  foreach ($tool in @($state.tools)) {
    Write-Host ("TOOL_DEPLOYED agent={0} tool={1} resourceId={2}" -f $tool.agent, $tool.tool, $tool.toolResourceId)
  }
  $samplePrompts = @($state.plugin.samplePrompts)
  if ($samplePrompts.Count -gt 0) {
    Write-Host '=== AVAILABLE SAMPLE PROMPTS ==='
    Write-Host 'You can now use any of the following prompts to test the deployment:'
    for ($i = 0; $i -lt $samplePrompts.Count; $i++) {
      $prompt = $samplePrompts[$i]
      $title = if ($prompt.title) { [string]$prompt.title } elseif ($prompt.id) { [string]$prompt.id } else { 'Starter-kit prompt' }
      $text = if ($prompt.prompt) { ([string]$prompt.prompt).Trim() } else { '' }
      Write-Host ("{0}.) {1}" -f ($i + 1), $title)
      if (-not [string]::IsNullOrWhiteSpace($text)) {
        Write-Host ("    {0}" -f $text)
      }
    }
  } else {
    Write-Host 'AVAILABLE SAMPLE PROMPTS: none'
  }
  if ($state.deploy.completedAt) { Write-Host 'SUMMARY_STAGE_DEPLOY_AGENT=Succeeded' }
}

[object[]]$rawArgs = @()
if ($null -ne $StarterKitArgs) { $rawArgs = @($StarterKitArgs) }
foreach ($arg in $rawArgs) {
  if (-not $StarterKitName -and -not ([string]$arg).StartsWith('-')) { $StarterKitName = [string]$arg }
}

if ($WhatIfPlan) {
  $pluginPath = (Resolve-StarterKit -Name $StarterKitName -Publisher $PublisherName).FullName
  $pluginData = Get-PluginAgentRefs -PluginPath $pluginPath
  $kbRequirements = @(Get-AgentKnowledgeBaseRequirements -Agents @($pluginData.agents))
  Write-Host '=== discovery-services-starter-kit-deployer PLAN ==='
  Write-Host ("KIT_JSON={0}" -f $pluginPath)
  Write-Host ("AGENT_REFS={0}" -f ((@($pluginData.agents) | ForEach-Object { $_.ref }) -join ','))
  if ($kbRequirements.Count -gt 0) {
    foreach ($row in $kbRequirements) {
      Write-Host ("KNOWLEDGE_BASE_REQUIRED agent={0} count={1}" -f $row.agent, @($row.knowledgeBases).Count)
    }
  } else {
    Write-Host 'KNOWLEDGE_BASE_REQUIRED=<none>'
  }
  Write-Host 'PLAN_STAGES=init -> build-tools -> deploy-tools -> deploy-agent -> summary'
  return
}

if (-not $Stage) { $Stage = 'init' }

switch ($Stage) {
  'init' {
    $pluginPath = (Resolve-StarterKit -Name $StarterKitName -Publisher $PublisherName).FullName
    $pluginData = Get-PluginAgentRefs -PluginPath $pluginPath
    try {
      $config = Load-StarterConfig -RequiredFields @('subscriptionId','resourceGroup','acrName','location','workspaceEndpoint','project','tenantId','chatModel','forceToolImageRebuild')
    } catch {
      if ([string]$_.Exception.Message -like 'CONFIG_INPUT_REQUIRED:*') {
        Write-Host 'TASK_STATUS=init:input_required'
        Write-Host 'INPUT_REQUIRED=CONFIG'
        Write-Host 'INPUT_REQUIRED_MESSAGE=Ask the user for the missing config fields, create config.json, then rerun init.'
        return
      }
      throw
    }
    if (-not $BuildModeProvided) {
      Write-BuildModeInputRequest -StarterKitName (Split-Path -Leaf (Split-Path -Parent $pluginPath))
      Write-Host 'TASK_STATUS=init:input_required'
      Write-Host 'INPUT_REQUIRED=BUILD_MODE'
      Write-Host 'INPUT_REQUIRED_MESSAGE=Ask the user to choose remote or local, then rerun init with -BuildMode <remote|local>.'
      return
    }
    $kbRequirements = @(Get-AgentKnowledgeBaseRequirements -Agents @($pluginData.agents))
    try {
      $knowledgeBases = Resolve-KnowledgeBaseInput -Requirements $kbRequirements -InputJson $KnowledgeBasesJson
    } catch {
      if ([string]$_.Exception.Message -like 'KNOWLEDGE_BASE_INPUT_REQUIRED:*') {
        Write-Host 'TASK_STATUS=init:input_required'
        Write-Host 'INPUT_REQUIRED=KNOWLEDGE_BASES'
        Write-Host 'INPUT_REQUIRED_MESSAGE=Ask the user for knowledgeBaseId values for the listed agents, save/provide JSON, then rerun init with -KnowledgeBasesJson <json-or-path>.'
        return
      }
      throw
    }
    $state = New-StarterRun -StarterName (Split-Path -Leaf (Split-Path -Parent $pluginPath)) -PluginPath $pluginPath -PluginData $pluginData -Agents @($pluginData.agents) -Config $config
    $state['buildMode'] = $BuildMode
    $state['nodepoolConfirmed'] = [bool]$ConfirmSupercomputerNodepools
    $state['knowledgeBaseRequirements'] = $kbRequirements
    $state['knowledgeBases'] = $knowledgeBases
    Save-State -RunDir $state.runDir -State $state | Out-Null
    Set-StageStatus -RunDir $state.runDir -StageName 'init' -Status 'done'
    Write-Host ("RUN_DIR={0}" -f $state.runDir)
    Write-Host ("AGENTS={0}" -f ((@($pluginData.agents) | ForEach-Object { $_.name }) -join ','))
    return
  }
  'build-tools' { Invoke-CheckedStage -Name 'build-tools' -RunDir $RunDir -Body { Invoke-BuildTools -RunDir $RunDir }; return }
  'deploy-tools' { Invoke-CheckedStage -Name 'deploy-tools' -RunDir $RunDir -Body { Invoke-DeployTools -RunDir $RunDir }; return }
  'deploy-agent' { Invoke-CheckedStage -Name 'deploy-agent' -RunDir $RunDir -Body { Invoke-DeployReferencedAgents -RunDir $RunDir }; return }
  'summary' { Invoke-CheckedStage -Name 'summary' -RunDir $RunDir -Body { Invoke-Summary -RunDir $RunDir }; return }
  'stop' {
    Set-AllStageStatuses -RunDir $RunDir -Status 'stopped'
    Write-Host 'DEPLOYMENT_STOPPED=true'
    Write-Host 'DEPLOYMENT_STOPPED_REASON=Supercomputer nodepool capacity was not confirmed.'
    Write-Host 'No tool builds were submitted, and no Azure resources were created or modified by build/deploy stages.'
    Write-Host 'When you have Supercomputer nodepool capacity for at least one of the listed SKUs per tool, rerun the skill.'
    return
  }
}


