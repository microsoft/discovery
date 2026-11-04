# Catalog discovery: staging from git objects, YAML parsing, fingerprints, tool bindings.

$script:DhLfsHeader = 'version https://git-lfs.github.com/spec/v1'
$script:DhKnownTemplateKeys = @('workspaceEndpoint', 'apiVersion', 'project', 'model', 'tenantId', 'resourceGroup', 'corePythonToolId', 'CHAT-MODEL')

function Invoke-DhGit {
  param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string[]]$Arguments)
  $out = & git -C $Root @Arguments 2>&1
  return @{ exitCode = $LASTEXITCODE; lines = @($out | ForEach-Object { [string]$_ }) }
}

function Test-DhGitRepo {
  param([string]$Root)
  $r = Invoke-DhGit -Root $Root -Arguments @('rev-parse', '--is-inside-work-tree')
  return ($r.exitCode -eq 0 -and $r.lines[0] -eq 'true')
}

function Get-DhCatalogAgentNames {
  param([Parameter(Mandatory)][string]$CatalogRoot, [string]$Ref = 'HEAD', [ValidateSet('git', 'worktree')][string]$Source = 'git')
  $names = @()
  if ($Source -eq 'git') {
    $r = Invoke-DhGit -Root $CatalogRoot -Arguments @('ls-tree', '-d', '--name-only', "${Ref}:agents")
    if ($r.exitCode -ne 0) { throw ('Cannot list agents at {0}: {1}' -f $Ref, ($r.lines -join ' ')) }
    $names = $r.lines
  } else {
    $names = @(Get-ChildItem -LiteralPath (Join-Path $CatalogRoot 'agents') -Directory | ForEach-Object Name)
  }
  return @($names | Where-Object { $_ -and $_ -ne 'tmp' -and -not $_.StartsWith('.') } | Sort-Object)
}

function New-DhIssue {
  param([string]$Tool = '', [ValidateSet('error', 'warning')][string]$Level = 'error', [string]$Code, [hashtable]$Params = @{}, [string]$Category = 'contribution', [string]$Detail = '')
  return [ordered]@{ tool = $Tool; level = $Level; code = $Code; params = $Params; category = $Category; detail = $Detail }
}

function Test-DhShebangOrShell {
  param([string]$Path)
  if ($Path -match '\.(sh|bash)$') { return $true }
  try {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
      $buffer = [byte[]]::new(2)
      $read = $stream.Read($buffer, 0, 2)
      return ($read -eq 2 -and $buffer[0] -eq 0x23 -and $buffer[1] -eq 0x21)
    } finally { $stream.Dispose() }
  } catch { return $false }
}

function Resolve-DhLfsPointers {
  <#
  .SYNOPSIS Replaces staged Git LFS pointer files with verified worktree content.
  #>
  param([string]$StagedAgentDir, [string]$CatalogRoot, [string]$AgentRel)
  $issues = [System.Collections.Generic.List[object]]::new()
  foreach ($file in (Get-ChildItem -LiteralPath $StagedAgentDir -Recurse -File | Where-Object { $_.Length -lt 1024 })) {
    $text = [System.IO.File]::ReadAllText($file.FullName)
    if (-not $text.StartsWith($script:DhLfsHeader)) { continue }
    $oid = if ($text -match 'oid sha256:([0-9a-f]{64})') { $Matches[1] } else { '' }
    $size = if ($text -match '(?m)^size (\d+)') { [long]$Matches[1] } else { -1 }
    $rel = [System.IO.Path]::GetRelativePath($StagedAgentDir, $file.FullName)
    $worktree = Join-Path (Join-Path $CatalogRoot $AgentRel) $rel
    $ok = $false
    if ($oid -and (Test-Path -LiteralPath $worktree)) {
      $item = Get-Item -LiteralPath $worktree
      if ($item.Length -eq $size -and (Get-DhFileSha256 -Path $worktree) -eq $oid) {
        Copy-Item -LiteralPath $worktree -Destination $file.FullName -Force
        $ok = $true
      }
    }
    if (-not $ok) {
      $toolName = if ($rel -match '^tools[\\/]([^\\/]+)') { $Matches[1] } else { '' }
      $issues.Add((New-DhIssue -Tool $toolName -Code 'DH-DSC-004' -Params @{ path = ($rel -replace '\\', '/') } -Category 'infrastructure'))
    }
  }
  return $issues.ToArray()
}

function Export-DhAgentSource {
  <#
  .SYNOPSIS Stages agents/<agent> into <StageRoot>/agents/<agent> from git objects (canonical bytes) or the worktree.
  #>
  param(
    [Parameter(Mandatory)][string]$CatalogRoot,
    [string]$Ref = 'HEAD',
    [ValidateSet('git', 'worktree')][string]$Source = 'git',
    [Parameter(Mandatory)][string]$Agent,
    [Parameter(Mandatory)][string]$StageRoot
  )
  $issues = [System.Collections.Generic.List[object]]::new()
  $agentRel = "agents/$Agent"
  $dest = Join-Path $StageRoot (Join-Path 'agents' $Agent)
  if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
  New-Item -ItemType Directory -Path $dest -Force | Out-Null

  if ($Source -eq 'git') {
    $tree = Invoke-DhGit -Root $CatalogRoot -Arguments @('ls-tree', '-r', '--full-tree', $Ref, '--', $agentRel)
    $excludes = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $tree.lines) {
      if ($line -match '^(120000|160000) \w+ [0-9a-f]+\t(.+)$') {
        $path = $Matches[2]
        $toolName = if ($path -match '^agents/[^/]+/tools/([^/]+)/') { $Matches[1] } else { '' }
        $issues.Add((New-DhIssue -Tool $toolName -Code 'DH-DSC-003' -Params @{ path = $path }))
        $excludes.Add(":(exclude)$path")
      }
    }
    $tar = Join-Path ([System.IO.Path]::GetTempPath()) ('dh-{0}.tar' -f [guid]::NewGuid().ToString('N'))
    try {
      $archiveArgs = @('-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive', '--format=tar', '-o', $tar, $Ref, '--', $agentRel) + $excludes
      $archive = Invoke-DhGit -Root $CatalogRoot -Arguments $archiveArgs
      if ($archive.exitCode -ne 0) { throw ('git archive failed: {0}' -f ($archive.lines -join ' ')) }
      $null = & tar -xf $tar -C $StageRoot 2>&1
      if ($LASTEXITCODE -ne 0) { throw 'tar extraction failed for staged agent source.' }
    } finally {
      Remove-Item -LiteralPath $tar -Force -ErrorAction SilentlyContinue
    }
    foreach ($issue in (Resolve-DhLfsPointers -StagedAgentDir $dest -CatalogRoot $CatalogRoot -AgentRel $agentRel)) { $issues.Add($issue) }
  } else {
    $sourceDir = Join-Path $CatalogRoot $agentRel
    $files = @()
    if (Test-DhGitRepo -Root $CatalogRoot) {
      $files = (Invoke-DhGit -Root $CatalogRoot -Arguments @('ls-files', '-co', '--exclude-standard', '--', $agentRel)).lines
      $status = Invoke-DhGit -Root $CatalogRoot -Arguments @('status', '--porcelain', '--', $agentRel)
      if (@($status.lines | Where-Object { $_ }).Count -gt 0) { $issues.Add((New-DhIssue -Level warning -Code 'DH-DSC-014' -Category 'policy')) }
    } else {
      $files = @(Get-ChildItem -LiteralPath $sourceDir -Recurse -File | ForEach-Object { [System.IO.Path]::GetRelativePath($CatalogRoot, $_.FullName) -replace '\\', '/' })
    }
    $normalized = 0
    foreach ($rel in $files) {
      if (-not $rel) { continue }
      $src = Join-Path $CatalogRoot $rel
      if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }
      $target = Join-Path $StageRoot $rel
      $targetDir = Split-Path -Parent $target
      if (-not (Test-Path -LiteralPath $targetDir)) { New-Item -ItemType Directory -Path $targetDir -Force | Out-Null }
      Copy-Item -LiteralPath $src -Destination $target -Force
      if (Test-DhShebangOrShell -Path $target) {
        $bytes = [System.IO.File]::ReadAllBytes($target)
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
        if ($text.Contains("`r`n")) {
          [System.IO.File]::WriteAllText($target, $text.Replace("`r`n", "`n"), [System.Text.UTF8Encoding]::new($false))
          $normalized++
        }
      }
    }
    if ($normalized -gt 0) { $issues.Add((New-DhIssue -Level warning -Code 'DH-DSC-009' -Params @{ count = $normalized } -Category 'policy')) }
  }
  return @{ dir = $dest; issues = $issues.ToArray() }
}

function Get-DhTreeFingerprint {
  param([string]$CatalogRoot, [string]$Ref, [string]$Source, [string]$RelPath, [string]$StagedDir, [string]$Extra = '')
  $basis = ''
  if ($Source -eq 'git') {
    $r = Invoke-DhGit -Root $CatalogRoot -Arguments @('rev-parse', "${Ref}:$RelPath")
    if ($r.exitCode -eq 0) { $basis = $r.lines[0] }
  }
  if (-not $basis) {
    $parts = foreach ($file in (Get-ChildItem -LiteralPath $StagedDir -Recurse -File | Sort-Object FullName)) {
      '{0}:{1}' -f ([System.IO.Path]::GetRelativePath($StagedDir, $file.FullName) -replace '\\', '/'), (Get-DhFileSha256 -Path $file.FullName)
    }
    $basis = Get-DhSha256Hex ($parts -join "`n")
  }
  return (Get-DhSha256Hex ('{0}|tpl{1}|{2}' -f $basis, $script:DhTemplateVersion, $Extra))
}

function Get-DhImageRefs {
  param($Definition)
  $refs = [System.Collections.Generic.List[string]]::new()
  foreach ($infra in @(Get-DhValue $Definition 'infra' @())) {
    $acr = Get-DhValue $infra 'image.acr'
    if ($acr) { $refs.Add([string]$acr) }
  }
  return @($refs | Select-Object -Unique)
}

function Get-DhToolSkus {
  param($Definition)
  $skus = [System.Collections.Generic.List[string]]::new()
  $gpu = $false
  foreach ($infra in @(Get-DhValue $Definition 'infra' @())) {
    foreach ($sku in @(Get-DhValue $infra 'compute.recommended_sku' @())) { if ($sku) { $skus.Add([string]$sku) } }
    $minGpu = Get-DhValue $infra 'compute.min_resources.gpu' 0
    try { if ([int]$minGpu -gt 0) { $gpu = $true } } catch { }
  }
  return @{ skus = @($skus | Select-Object -Unique); gpu = $gpu }
}

function Resolve-DhToolBindings {
  <#
  .SYNOPSIS Maps agent.yaml discoveryExtensions.tools[].toolId values to tool folders.
  #>
  param([System.Collections.IDictionary]$Agent)
  $bindings = [System.Collections.Generic.List[object]]::new()
  $issues = [System.Collections.Generic.List[object]]::new()
  $toolIds = @(@(Get-DhValue $Agent.agentDoc 'discoveryExtensions.tools' @()) | Where-Object { $_ -is [System.Collections.IDictionary] } | ForEach-Object { [string]$_.toolId })
  $toolNames = @($Agent.tools.Keys)
  $overrides = Get-DhValue $Agent.spec 'toolIdPlaceholders' @{}
  $placeholderCount = @($toolIds | Where-Object { $_ -match '^\{\{\w+\}\}$' }).Count
  foreach ($toolId in $toolIds) {
    $target = $null
    $kind = 'resourceId'
    if ($overrides -is [System.Collections.IDictionary] -and $overrides.Contains($toolId)) {
      $target = [string]$overrides[$toolId]
      $kind = if ($toolId -match '^\{\{\w+\}\}$') { 'placeholder' } else { 'resourceId' }
    } elseif ($toolId -match '^\{\{(\w+)\}\}$') {
      $kind = 'placeholder'
      $key = ConvertTo-DhAlnum ($Matches[1] -replace 'ToolId$', '')
      $hits = @($toolNames | Where-Object {
          $tool = $Agent.tools[$_]
          $candidates = @((ConvertTo-DhAlnum $_), (ConvertTo-DhAlnum $tool.defName)) | ForEach-Object { $_; ($_ -replace 'tool$', '') }
          $candidates -contains $key
        })
      if ($hits.Count -eq 1) { $target = $hits[0] }
      elseif ($toolNames.Count -eq 1 -and $placeholderCount -eq 1) { $target = $toolNames[0] }
    } else {
      $leaf = ConvertTo-DhAlnum (($toolId -split '/')[-1])
      $hits = @($toolNames | Where-Object { (ConvertTo-DhAlnum $_) -eq $leaf -or $Agent.tools[$_].armName -eq $leaf })
      if ($hits.Count -eq 1) { $target = $hits[0] }
    }
    if ($target -and -not $Agent.tools.Contains($target)) { $target = $null }
    if (-not $target) {
      $issues.Add((New-DhIssue -Code 'DH-DSC-010' -Params @{ placeholder = $(if ($kind -eq 'placeholder') { $toolId } else { 'resource id' }) }))
    }
    $bindings.Add([ordered]@{ toolId = $toolId; kind = $kind; tool = $target })
  }
  foreach ($name in $toolNames) {
    if (-not ($bindings | Where-Object { $_.tool -eq $name })) {
      $issues.Add((New-DhIssue -Tool $name -Level warning -Code 'DH-DSC-011' -Params @{ tool = $name } -Category 'contribution'))
    }
  }
  return @{ bindings = $bindings.ToArray(); issues = $issues.ToArray() }
}

function Get-DhRequiredTemplateVariables {
  param([System.Collections.IDictionary]$AgentDoc, [string[]]$ToolIdPlaceholders)
  $scan = [ordered]@{ discoveryExtensions = (Get-DhValue $AgentDoc 'discoveryExtensions' @{}); tools = (Get-DhValue $AgentDoc 'tools' @()) }
  $text = ConvertTo-DhJson $scan -Compress
  $names = [System.Collections.Generic.List[string]]::new()
  foreach ($m in [regex]::Matches($text, '\{\{([A-Za-z0-9_\-]+)\}\}')) {
    $name = $m.Groups[1].Value
    if ("{{$name}}" -in $ToolIdPlaceholders) { continue }
    if ($name -in $script:DhKnownTemplateKeys) { continue }
    if (-not $names.Contains($name)) { $names.Add($name) }
  }
  return $names.ToArray()
}

function Read-DhCatalog {
  <#
  .SYNOPSIS Stages and parses the selected agents; never throws for per-agent problems (recorded as issues).
  #>
  param(
    [Parameter(Mandatory)][string]$CatalogRoot,
    [string]$Ref = 'HEAD',
    [ValidateSet('git', 'worktree')][string]$Source = 'git',
    [string[]]$Agents = @(),
    [string]$SpecRoot,
    [Parameter(Mandatory)][string]$OutputDir,
    [System.Collections.IDictionary]$Config
  )
  $stageRoot = Join-Path $OutputDir 'catalog'
  if (-not (Test-Path -LiteralPath $stageRoot)) { New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null }
  $all = @(Get-DhCatalogAgentNames -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source)
  $requested = @($Agents | Where-Object { $_ })
  $selected = if ($requested.Count -gt 0) { @($requested | Where-Object { $_ -in $all }) } else { $all }
  $gitSha = ''
  if (Test-DhGitRepo -Root $CatalogRoot) {
    $rev = Invoke-DhGit -Root $CatalogRoot -Arguments @('rev-parse', $Ref)
    if ($rev.exitCode -eq 0) { $gitSha = $rev.lines[0] }
  }
  $catalog = [ordered]@{
    root = $CatalogRoot; ref = $Ref; source = $Source; gitSha = $gitSha
    allAgents = $all; unknown = @($requested | Where-Object { $_ -notin $all }); agents = [ordered]@{}
  }
  $maxBytes = [long](Get-DhValue $Config 'staging.maxContextMB' 2048) * 1MB
  $maxFiles = [int](Get-DhValue $Config 'staging.maxFiles' 20000)

  $yamlPaths = [System.Collections.Generic.List[string]]::new()
  foreach ($name in $selected) {
    $agent = [ordered]@{
      name = $name; dir = ''; fingerprint = ''; agentDoc = $null; metadataDoc = $null; spec = $null; specPath = ''; specHash = ''
      tools = [ordered]@{}; bindings = @(); topLevelToolKinds = @(); requiredVariables = @(); issues = [System.Collections.Generic.List[object]]::new()
    }
    try {
      $staged = Export-DhAgentSource -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -Agent $name -StageRoot $stageRoot
      $agent.dir = $staged.dir
      foreach ($issue in $staged.issues) { $agent.issues.Add($issue) }
    } catch {
      $agent.issues.Add((New-DhIssue -Code 'DH-GEN-001' -Params @{ stage = 'discover' } -Category 'harness' -Detail $_.Exception.Message))
      $catalog.agents[$name] = $agent
      continue
    }
    foreach ($file in @('agent.yaml', 'metadata.yaml', 'README.md')) {
      $path = Join-Path $agent.dir $file
      if (-not (Test-Path -LiteralPath $path)) { $agent.issues.Add((New-DhIssue -Code 'DH-DSC-001' -Params @{ file = $file })) }
      elseif ($file -like '*.yaml') { $yamlPaths.Add($path) }
    }
    $toolsDir = Join-Path $agent.dir 'tools'
    if (Test-Path -LiteralPath $toolsDir) {
      foreach ($toolDir in (Get-ChildItem -LiteralPath $toolsDir -Directory | Sort-Object Name)) {
        $tool = [ordered]@{
          name = $toolDir.Name; agent = $name; dir = $toolDir.FullName; defPath = (Join-Path $toolDir.FullName 'tool.yaml'); def = $null; defName = ''; armName = ''
          imageName = ''; imageTagOriginal = ''; fingerprint = ''; fp12 = ''; gpu = $false; skus = @(); codeEnvironments = @(); actions = @(); buildContext = 'tool'
          hasDockerfile = (Test-Path -LiteralPath (Join-Path $toolDir.FullName 'Dockerfile')); contextBytes = 0; contextFiles = 0
        }
        if (Test-Path -LiteralPath $tool.defPath) { $yamlPaths.Add($tool.defPath) } else { $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-001' -Params @{ file = "tools/$($tool.name)/tool.yaml" })) }
        if (-not $tool.hasDockerfile) { $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-008')) }
        $files = @(Get-ChildItem -LiteralPath $toolDir.FullName -Recurse -File)
        $tool.contextFiles = $files.Count
        $tool.contextBytes = [long](($files | Measure-Object -Property Length -Sum).Sum)
        if ($tool.contextBytes -gt $maxBytes -or $tool.contextFiles -gt $maxFiles) {
          $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-005' -Params @{ size = [math]::Round($tool.contextBytes / 1MB, 1); limit = [math]::Round($maxBytes / 1MB) }))
        }
        $agent.tools[$tool.name] = $tool
      }
    }
    if ($SpecRoot) {
      $specPath = Join-Path $SpecRoot "$name.yaml"
      if (Test-Path -LiteralPath $specPath) { $agent.specPath = $specPath; $agent.specHash = Get-DhFileSha256 -Path $specPath; $yamlPaths.Add($specPath) }
    }
    $catalog.agents[$name] = $agent
  }

  $parsed = ConvertFrom-DhYamlFiles -Paths $yamlPaths.ToArray() -Config $Config
  foreach ($agent in $catalog.agents.Values) {
    if (-not $agent.dir) { continue }
    $agentYaml = Join-Path $agent.dir 'agent.yaml'
    $metaYaml = Join-Path $agent.dir 'metadata.yaml'
    foreach ($pair in @(@('agentDoc', $agentYaml, 'agent.yaml'), @('metadataDoc', $metaYaml, 'metadata.yaml'))) {
      $entry = $parsed[$pair[1]]
      if ($entry) {
        if ($entry.ok -and $entry.doc -is [System.Collections.IDictionary]) { $agent[$pair[0]] = $entry.doc }
        else { $agent.issues.Add((New-DhIssue -Code 'DH-DSC-002' -Params @{ file = $pair[2] } -Detail ([string]$entry.error))) }
      }
    }
    if ($agent.agentDoc -and ([string](Get-DhValue $agent.agentDoc 'kind' 'prompt')) -ne 'prompt') {
      $agent.issues.Add((New-DhIssue -Code 'DH-DSC-015' -Params @{ kind = (Get-DhValue $agent.agentDoc 'kind') }))
    }
    if ($agent.specPath) {
      $entry = $parsed[$agent.specPath]
      if ($entry -and $entry.ok -and $entry.doc -is [System.Collections.IDictionary]) { $agent.spec = $entry.doc }
      else { $agent.issues.Add((New-DhIssue -Code 'DH-SPC-001' -Params @{ reason = 'YAML parse error' } -Category 'policy' -Detail ([string]$entry.error))) }
    }
    foreach ($tool in $agent.tools.Values) {
      $entry = $parsed[$tool.defPath]
      if (-not $entry) { continue }
      if (-not $entry.ok -or -not ($entry.doc -is [System.Collections.IDictionary])) {
        $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-002' -Params @{ file = "tools/$($tool.name)/tool.yaml" } -Detail ([string]$entry.error)))
        continue
      }
      $tool.def = $entry.doc
      $tool.defName = [string](Get-DhValue $tool.def 'name' '')
      $tool.armName = ConvertTo-DhAlnum $tool.defName
      if (-not $tool.armName) { $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-007')) }
      $refs = @(Get-DhImageRefs -Definition $tool.def)
      if ($refs.Count -eq 0) { $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-006')) }
      elseif (@($refs | ForEach-Object { ($_ -split ':')[0] } | Select-Object -Unique).Count -gt 1) { $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-013')) }
      if ($refs.Count -gt 0) {
        if ($refs[0] -match '/(?<image>[^:"\s]+):(?<tag>[^"\s]+)$') {
          $tool.imageName = ($Matches['image'] -split '/')[-1].ToLowerInvariant()
          $tool.imageTagOriginal = $Matches['tag']
        } else {
          $agent.issues.Add((New-DhIssue -Tool $tool.name -Code 'DH-DSC-006'))
        }
      }
      $skuInfo = Get-DhToolSkus -Definition $tool.def
      $tool.skus = $skuInfo.skus
      $tool.gpu = $skuInfo.gpu
      $tool.codeEnvironments = @(Get-DhValue $tool.def 'code_environments' @())
      $tool.actions = @(Get-DhValue $tool.def 'actions' @())
      $specContext = [string](Get-DhValue $agent.spec ('tools.' + $tool.name + '.buildContext') '')
      $tool.buildContext = if ($specContext) { $specContext } else { Get-DhBuildContextKind -DockerfilePath (Join-Path $tool.dir 'Dockerfile') -ToolName $tool.name }
      $fingerprintRel = if ($tool.buildContext -eq 'agent') { "agents/$($agent.name)" } else { "agents/$($agent.name)/tools/$($tool.name)" }
      $fingerprintDir = if ($tool.buildContext -eq 'agent') { $agent.dir } else { $tool.dir }
      $tool.fingerprint = Get-DhTreeFingerprint -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -RelPath $fingerprintRel -StagedDir $fingerprintDir -Extra ('context=' + $tool.buildContext)
      $tool.fp12 = $tool.fingerprint.Substring(0, 12)
    }
    if ($agent.agentDoc) {
      $resolved = Resolve-DhToolBindings -Agent $agent
      $agent.bindings = $resolved.bindings
      foreach ($issue in $resolved.issues) { $agent.issues.Add($issue) }
      $agent.topLevelToolKinds = @(@(Get-DhValue $agent.agentDoc 'tools' @()) | Where-Object { $_ -is [System.Collections.IDictionary] } | ForEach-Object { [string]$_.kind } | Where-Object { $_ } | Select-Object -Unique)
      $placeholders = @($agent.bindings | Where-Object { $_.kind -eq 'placeholder' } | ForEach-Object { $_.toolId })
      $agent.requiredVariables = @(Get-DhRequiredTemplateVariables -AgentDoc $agent.agentDoc -ToolIdPlaceholders $placeholders)
    }
    $agent.fingerprint = Get-DhTreeFingerprint -CatalogRoot $CatalogRoot -Ref $Ref -Source $Source -RelPath "agents/$($agent.name)" -StagedDir $agent.dir -Extra $agent.specHash
    if ($agent.spec) {
      foreach ($problem in (Test-DhSpec -Spec $agent.spec -Agent $agent)) {
        $agent.issues.Add((New-DhIssue -Code 'DH-SPC-001' -Params @{ reason = $problem } -Category 'policy'))
      }
    }
  }
  return $catalog
}

function Get-DhBuildContextKind {
  <#
  .SYNOPSIS 'agent' when the Dockerfile copies agent-root paths (tools/<tool>/..., agent.yaml); otherwise 'tool'.
  #>
  param([string]$DockerfilePath, [string]$ToolName)
  if (-not (Test-Path -LiteralPath $DockerfilePath)) { return 'tool' }
  $text = [System.IO.File]::ReadAllText($DockerfilePath) -replace '\\\r?\n', ' '
  foreach ($line in ($text -split '\r?\n')) {
    if ($line -notmatch '^\s*(COPY|ADD)\s+(.*)$') { continue }
    $parts = @($Matches[2] -split '\s+' | Where-Object { $_ })
    if (@($parts | Where-Object { $_ -like '--from=*' }).Count -gt 0) { continue }
    $sources = @($parts | Where-Object { -not $_.StartsWith('--') })
    if ($sources.Count -lt 2) { continue }
    foreach ($source in $sources[0..($sources.Count - 2)]) {
      $s = $source.TrimStart('.', '/')
      if ($s.StartsWith("tools/$ToolName/") -or $s -eq "tools/$ToolName" -or $s -eq 'agent.yaml' -or $s -eq 'metadata.yaml') { return 'agent' }
    }
  }
  return 'tool'
}

function Get-DhBoundTools {
  param([System.Collections.IDictionary]$Agent)
  return @($Agent.bindings | Where-Object { $_.tool } | ForEach-Object { $_.tool } | Select-Object -Unique)
}
