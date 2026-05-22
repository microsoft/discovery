param(
  [Parameter(Mandatory=$true, Position=0)]
  [string]$Command,

  [Parameter(Position=1)]
  [string]$SubCommand = '',

  [ValidateSet('Table','Markdown','Json','Plain')]
  [string]$Format = 'Table',

  [string]$Publisher = '',
  [string]$Tag = '',
  [switch]$WithToolsOnly,
  [switch]$WithoutToolsOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# =========================================================================
# Helpers
# =========================================================================

function Get-RepoRoot {
  return (git rev-parse --show-toplevel).Trim()
}

function Read-YamlField {
  param([string]$YamlPath, [string]$Field, [string]$Default = '')

  if (-not (Test-Path $YamlPath)) { return $Default }
  $lines = Get-Content $YamlPath
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^$Field\s*:\s*(.*)$") {
      $rest = $Matches[1].Trim()
      $rest = $rest -replace '^["'']|["'']$', ''
      if ($rest -eq '>' -or $rest -eq '>-' -or $rest -eq '|' -or [string]::IsNullOrWhiteSpace($rest)) {
        if (($i + 1) -lt $lines.Count) { return $lines[$i + 1].Trim() }
        return $Default
      }
      return $rest
    }
  }
  return $Default
}

function Read-YamlList {
  param([string]$YamlPath, [string]$Field)

  $items = @()
  if (-not (Test-Path $YamlPath)) { return $items }
  $lines = Get-Content $YamlPath
  $inBlock = $false
  foreach ($line in $lines) {
    if ($line -match "^$Field\s*:\s*$") { $inBlock = $true; continue }
    if ($inBlock) {
      if ($line -match '^\s*-\s*(.+)$') {
        $items += ($Matches[1].Trim() -replace '^["'']|["'']$', '')
      }
      elseif ($line -match '^\S') { $inBlock = $false }
    }
  }
  return $items
}

function Read-NestedYamlField {
  # Two-level YAML reader. Returns `parent.child` from blocks like:
  #   publisher:
  #     name: Microsoft
  #     party: 1p
  param([string]$YamlPath, [string]$Parent, [string]$Child, [string]$Default = '')

  if (-not (Test-Path $YamlPath)) { return $Default }
  $lines = Get-Content $YamlPath
  $inBlock = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match "^$Parent\s*:\s*$") { $inBlock = $true; continue }
    if ($inBlock) {
      if ($line -match "^\s+$Child\s*:\s*(.*)$") {
        $rest = $Matches[1].Trim()
        $rest = $rest -replace '^["'']|["'']$', ''
        return $rest
      }
      if ($line -match '^\S') { $inBlock = $false }
    }
  }
  return $Default
}

# =========================================================================
# Walking the flat layout
# =========================================================================

function Get-AgentDirectories {
  if (-not (Test-Path $AgentsRoot)) { return @() }
  return Get-ChildItem $AgentsRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne 'tmp' -and (Test-Path (Join-Path $_.FullName 'agent.yaml')) }
}

function Get-StarterKitDirectories {
  if (-not (Test-Path $StarterKitsRoot)) { return @() }
  return Get-ChildItem $StarterKitsRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne 'tmp' -and (Test-Path (Join-Path $_.FullName 'kit.json')) }
}

function Get-AgentTools {
  param([string]$AgentDir)

  $toolsRoot = Join-Path $AgentDir 'tools'
  $tools = @()
  if (-not (Test-Path $toolsRoot)) { return $tools }

  $toolDirs = Get-ChildItem $toolsRoot -Directory -ErrorAction SilentlyContinue
  foreach ($t in $toolDirs) {
    $toolYaml = Join-Path $t.FullName 'tool.yaml'
    if (-not (Test-Path $toolYaml)) { continue }
    $name = Read-YamlField -YamlPath $toolYaml -Field 'name'
    if (-not $name) { $name = $t.Name }
    $tools += [pscustomobject]@{
      Name          = $name
      Folder        = $t.Name
      HasDockerfile = Test-Path (Join-Path $t.FullName 'Dockerfile')
    }
  }
  return ,$tools
}

function New-AgentEntry {
  param(
    [System.IO.DirectoryInfo]$Dir,
    [bool]$IncludeTools = $false
  )

  $agentDir     = $Dir.FullName
  $agentName    = $Dir.Name
  $metadataPath = Join-Path $agentDir 'metadata.yaml'
  $hasMetadata  = Test-Path $metadataPath
  $hasTool      = Test-Path (Join-Path $agentDir 'tools')
  $hasReadme    = Test-Path (Join-Path $agentDir 'README.md')

  $description    = ''
  $version        = ''
  $party          = ''
  $publisherName  = ''
  $tags           = @()

  if ($hasMetadata) {
    $version       = Read-YamlField       -YamlPath $metadataPath -Field 'version'
    $description   = Read-YamlField       -YamlPath $metadataPath -Field 'description'
    $tags          = Read-YamlList        -YamlPath $metadataPath -Field 'tags'
    $publisherName = Read-NestedYamlField -YamlPath $metadataPath -Parent 'publisher' -Child 'name'
    $party         = Read-NestedYamlField -YamlPath $metadataPath -Parent 'publisher' -Child 'party'
  }

  $tools = @()
  if ($IncludeTools) { $tools = Get-AgentTools -AgentDir $agentDir }

  return [pscustomobject]@{
    Path        = $agentName
    Name        = $agentName
    Publisher   = $publisherName
    Party       = $party
    Description = $description
    Version     = $version
    HasTool     = $hasTool
    HasReadme   = $hasReadme
    Tags        = $tags
    Tools       = $tools
    ToolCount   = @($tools).Count
    AgentDir    = $agentDir
  }
}

function New-StarterKitEntry {
  param([System.IO.DirectoryInfo]$Dir)

  $kitDir  = $Dir.FullName
  $kitName = $Dir.Name
  $kitPath = Join-Path $kitDir 'kit.json'
  if (-not (Test-Path $kitPath)) { return $null }

  try {
    $plugin = Get-Content $kitPath -Raw | ConvertFrom-Json
  } catch {
    return $null
  }

  $agentRefs = @()
  if ($plugin.PSObject.Properties.Name -contains 'agentRefs') {
    $agentRefs = @($plugin.agentRefs | ForEach-Object { $_.ref })
  }
  $primaryRef = @($plugin.agentRefs | Where-Object { $_.role -eq 'primary' } | Select-Object -First 1)
  $entryAgent = if ($primaryRef.Count -gt 0) { [string]$primaryRef[0].ref } else { '' }

  $name        = if ($plugin.PSObject.Properties.Name -contains 'name')        { $plugin.name }        else { $kitName }
  $version     = if ($plugin.PSObject.Properties.Name -contains 'version')     { $plugin.version }     else { '' }
  $description = if ($plugin.PSObject.Properties.Name -contains 'description') { $plugin.description } else { '' }
  $category    = if ($plugin.PSObject.Properties.Name -contains 'category')    { $plugin.category }    else { '' }
  $party       = if ($plugin.PSObject.Properties.Name -contains 'party')       { $plugin.party }       else { '' }
  $keywords    = if ($plugin.PSObject.Properties.Name -contains 'keywords')    { @($plugin.keywords) } else { @() }

  $publisherName = ''
  if ($plugin.PSObject.Properties.Name -contains 'author' -and
      $plugin.author -and
      $plugin.author.PSObject.Properties.Name -contains 'name') {
    $publisherName = [string]$plugin.author.name
  }

  return [pscustomobject]@{
    Path        = $kitName
    Name        = $name
    Publisher   = $publisherName
    Party       = $party
    Version     = $version
    Description = $description
    Category    = $category
    EntryAgent  = $entryAgent
    AgentRefs   = $agentRefs
    AgentCount  = @($agentRefs).Count
    Keywords    = $keywords
    KitDir      = $kitDir
  }
}

# =========================================================================
# Command implementations
# =========================================================================

function Get-AllAgentEntries {
  param([bool]$IncludeTools = $false)
  $entries = New-Object System.Collections.Generic.List[object]
  foreach ($d in (Get-AgentDirectories)) {
    $entries.Add((New-AgentEntry -Dir $d -IncludeTools $IncludeTools))
  }
  return $entries.ToArray()
}

function Get-AllStarterKitEntries {
  $entries = New-Object System.Collections.Generic.List[object]
  foreach ($d in (Get-StarterKitDirectories)) {
    $e = New-StarterKitEntry -Dir $d
    if ($e) { $entries.Add($e) }
  }
  return $entries.ToArray()
}

function Invoke-PublishersCommand {
  $agents = Get-AllAgentEntries
  $kits   = Get-AllStarterKitEntries

  $byName = @{}
  foreach ($a in $agents) {
    $key = if ($a.Publisher) { $a.Publisher } else { '(unspecified)' }
    if (-not $byName.ContainsKey($key)) {
      $byName[$key] = [pscustomobject]@{
        Publisher    = $key
        Party        = $a.Party
        AgentCount   = 0
        StarterKits  = 0
      }
    }
    $byName[$key].AgentCount++
    if (-not $byName[$key].Party -and $a.Party) { $byName[$key].Party = $a.Party }
  }
  foreach ($k in $kits) {
    $key = if ($k.Publisher) { $k.Publisher } else { '(unspecified)' }
    if (-not $byName.ContainsKey($key)) {
      $byName[$key] = [pscustomobject]@{
        Publisher    = $key
        Party        = $k.Party
        AgentCount   = 0
        StarterKits  = 0
      }
    }
    $byName[$key].StarterKits++
    if (-not $byName[$key].Party -and $k.Party) { $byName[$key].Party = $k.Party }
  }

  $rows = $byName.Values | Sort-Object Publisher

  switch ($Format) {
    'Table' {
      Write-Host ("PUBLISHER_COUNT={0}" -f @($rows).Count)
      Write-Host ''
      $rows | Select-Object Publisher, Party, AgentCount, StarterKits | Format-Table -AutoSize
    }
    'Plain' {
      foreach ($r in $rows) { Write-Host $r.Publisher }
    }
    'Markdown' {
      Write-Host ("PUBLISHER_COUNT={0}" -f @($rows).Count)
      Write-Host ''
      Write-Host '| Publisher | Party | Agents | Starter kits |'
      Write-Host '|---|---|---|---|'
      foreach ($r in $rows) {
        Write-Host ("| {0} | {1} | {2} | {3} |" -f $r.Publisher, $r.Party, $r.AgentCount, $r.StarterKits)
      }
    }
    'Json' {
      $rows | ConvertTo-Json -Depth 4
    }
  }
}

function Invoke-AgentsCommand {
  param([bool]$IncludeTools)

  $rows = Get-AllAgentEntries -IncludeTools $IncludeTools
  if ($Publisher)        { $rows = $rows | Where-Object { $_.Publisher -ieq $Publisher } }
  if ($Tag)              { $rows = $rows | Where-Object { $_.Tags -contains $Tag } }
  if ($WithToolsOnly)    { $rows = $rows | Where-Object { $_.HasTool } }
  if ($WithoutToolsOnly) { $rows = $rows | Where-Object { -not $_.HasTool } }
  $rows = $rows | Sort-Object Name

  switch ($Format) {
    'Table' {
      Write-Host ("AGENT_COUNT={0}" -f @($rows).Count)
      Write-Host ''
      if ($IncludeTools) {
        $proj = $rows | Select-Object @{n='Agent';e={$_.Name}}, @{n='Publisher';e={$_.Publisher}}, @{n='Tools';e={ if (@($_.Tools).Count -eq 0) { '(no tools)' } else { ($_.Tools | ForEach-Object { "tools/$($_.Folder)" }) -join ', ' } }}
        $proj | Format-Table -AutoSize
      } else {
        $rows | Select-Object @{n='Agent';e={$_.Name}}, @{n='Publisher';e={$_.Publisher}}, @{n='Party';e={$_.Party}} | Format-Table -AutoSize
      }
    }
    'Plain' {
      foreach ($a in $rows) {
        Write-Host $a.Name
        if ($IncludeTools) {
          if (@($a.Tools).Count -eq 0) {
            Write-Host '  (no tools)'
          } else {
            foreach ($t in $a.Tools) {
              Write-Host ("  + tools/{0}" -f $t.Folder)
            }
          }
        }
      }
    }
    'Markdown' {
      Write-Host ("AGENT_COUNT={0}" -f @($rows).Count)
      Write-Host ''
      if ($IncludeTools) {
        Write-Host '| Agent | Publisher | Tools |'
        Write-Host '|---|---|---|'
        foreach ($a in $rows) {
          $toolsCol = if (@($a.Tools).Count -eq 0) { '(no tools)' } else { (($a.Tools | ForEach-Object { "tools/$($_.Folder)" }) -join ', ') }
          Write-Host ("| {0} | {1} | {2} |" -f $a.Name, $a.Publisher, $toolsCol)
        }
      } else {
        Write-Host '| Agent | Publisher | Party |'
        Write-Host '|---|---|---|'
        foreach ($a in $rows) {
          Write-Host ("| {0} | {1} | {2} |" -f $a.Name, $a.Publisher, $a.Party)
        }
      }
    }
    'Json' {
      if ($IncludeTools) {
        $rows | Select-Object Name, Publisher, Party, Description, Version, HasTool, ToolCount, Tools, HasReadme, Tags | ConvertTo-Json -Depth 6
      } else {
        $rows | Select-Object Name, Publisher, Party, Description, Version, HasTool, HasReadme, Tags | ConvertTo-Json -Depth 4
      }
    }
  }
}

function Invoke-StarterKitsCommand {
  $rows = Get-AllStarterKitEntries
  if ($Publisher) { $rows = $rows | Where-Object { $_.Publisher -ieq $Publisher } }
  $rows = $rows | Sort-Object Name

  switch ($Format) {
    'Table' {
      Write-Host ("STARTER_KIT_COUNT={0}" -f @($rows).Count)
      Write-Host ''
      $rows | Select-Object @{n='Starter-Kit';e={$_.Name}}, @{n='Publisher';e={$_.Publisher}}, @{n='Category';e={$_.Category}} | Format-Table -AutoSize
    }
    'Plain' {
      foreach ($r in $rows) { Write-Host $r.Name }
    }
    'Markdown' {
      Write-Host ("STARTER_KIT_COUNT={0}" -f @($rows).Count)
      Write-Host ''
      Write-Host '| Starter-Kit | Publisher | Category |'
      Write-Host '|---|---|---|'
      foreach ($r in $rows) {
        Write-Host ("| {0} | {1} | {2} |" -f $r.Name, $r.Publisher, $r.Category)
      }
    }
    'Json' {
      $rows | Select-Object Name, Publisher, Party, Version, Description, Category, EntryAgent, AgentRefs, AgentCount, Keywords | ConvertTo-Json -Depth 6
    }
  }
}

function Resolve-AgentEntry {
  param(
    [string]$AgentKey,
    [bool]$IncludeTools = $false
  )
  $key = $AgentKey.Trim()
  if (-not $key) { return $null }
  $rows = Get-AllAgentEntries -IncludeTools $IncludeTools
  return $rows | Where-Object { $_.Name -ieq $key } | Select-Object -First 1
}

function Resolve-StarterKitEntry {
  param([string]$StarterKitKey)
  $key = $StarterKitKey.Trim()
  if (-not $key) { return $null }
  $rows = Get-AllStarterKitEntries
  return $rows | Where-Object { $_.Name -ieq $key -or $_.Path -ieq $key } | Select-Object -First 1
}

function Invoke-AgentDescribeCommand {
  param([string]$AgentKey)

  $entry = Resolve-AgentEntry -AgentKey $AgentKey -IncludeTools $false
  if (-not $entry) {
    Write-Error "Unknown agent '$AgentKey'. Use the agent's folder name (e.g. 'aizynthfinder')."
    exit 2
  }

  switch ($Format) {
    'Table' {
      $entry | Select-Object Name, Publisher, Version, HasTool, Description | Format-Table -AutoSize -Wrap
    }
    'Plain' {
      Write-Host $entry.Name
    }
    'Markdown' {
      Write-Host '| Agent | Publisher | Version | HasTool | Description |'
      Write-Host '|---|---|---|---|---|'
      $desc = ($entry.Description -replace '\|','\|')
      Write-Host ("| {0} | {1} | {2} | {3} | {4} |" -f $entry.Name, $entry.Publisher, $entry.Version, $entry.HasTool, $desc)
    }
    'Json' {
      $entry | Select-Object Name, Publisher, Party, Version, HasTool, Description, Tags, HasReadme | ConvertTo-Json -Depth 4
    }
  }
}

function Invoke-AgentSingleListToolsCommand {
  param([string]$AgentKey)

  $entry = Resolve-AgentEntry -AgentKey $AgentKey -IncludeTools $true
  if (-not $entry) {
    Write-Error "Unknown agent '$AgentKey'. Use the agent's folder name (e.g. 'aizynthfinder')."
    exit 2
  }

  $row = [pscustomobject]@{
    Agent       = $entry.Name
    Publisher   = $entry.Publisher
    Version     = $entry.Version
    ToolCount   = @($entry.Tools).Count
    Tools       = if (@($entry.Tools).Count -eq 0) { '' } else { ($entry.Tools | ForEach-Object { $_.Name }) -join ', ' }
    Description = $entry.Description
  }

  switch ($Format) {
    'Table' {
      $row | Format-Table -AutoSize -Wrap
    }
    'Plain' {
      Write-Host $row.Agent
      if (@($entry.Tools).Count -eq 0) {
        Write-Host '  (no tools)'
      } else {
        foreach ($tool in $entry.Tools) {
          Write-Host ("  + {0}" -f $tool.Name)
        }
      }
    }
    'Markdown' {
      Write-Host '| Agent | Publisher | Version | ToolCount | Tools | Description |'
      Write-Host '|---|---|---|---|---|---|'
      $desc = ($row.Description -replace '\|','\|')
      Write-Host ("| {0} | {1} | {2} | {3} | {4} | {5} |" -f $row.Agent, $row.Publisher, $row.Version, $row.ToolCount, $row.Tools, $desc)
    }
    'Json' {
      $row | ConvertTo-Json -Depth 4
    }
  }
}

function Invoke-StarterKitDescribeCommand {
  param([string]$StarterKitKey)

  $entry = Resolve-StarterKitEntry -StarterKitKey $StarterKitKey
  if (-not $entry) {
    Write-Error "Unknown starter kit '$StarterKitKey'. Use the kit's folder name (e.g. 'drug-discovery')."
    exit 2
  }

  switch ($Format) {
    'Table' {
      $entry | Select-Object Name, Publisher, Version, Category, AgentCount, Description | Format-Table -AutoSize -Wrap
    }
    'Plain' {
      Write-Host $entry.Name
    }
    'Markdown' {
      Write-Host '| Starter-Kit | Publisher | Version | Category | AgentCount | Description |'
      Write-Host '|---|---|---|---|---|---|'
      $desc = ($entry.Description -replace '\|','\|')
      Write-Host ("| {0} | {1} | {2} | {3} | {4} | {5} |" -f $entry.Name, $entry.Publisher, $entry.Version, $entry.Category, $entry.AgentCount, $desc)
    }
    'Json' {
      $entry | Select-Object Name, Publisher, Party, Version, Category, AgentCount, Description, EntryAgent, AgentRefs, Keywords | ConvertTo-Json -Depth 6
    }
  }
}

# =========================================================================
# Dispatch
# =========================================================================

$RepoRoot        = Get-RepoRoot
$AgentsRoot      = Join-Path $RepoRoot 'agents'
$StarterKitsRoot = Join-Path $RepoRoot 'starter-kits'

switch ($Command) {
  'publishers' {
    if ($SubCommand) { Write-Error "'publishers' takes no subcommand (got '$SubCommand')."; exit 2 }
    Invoke-PublishersCommand
  }
  'agents' {
    $includeTools = $false
    if ($SubCommand) {
      if ($SubCommand -eq 'list-tools') { $includeTools = $true }
      else { Write-Error "Unknown subcommand for 'agents': '$SubCommand'. Did you mean 'list-tools'?"; exit 2 }
    }
    Invoke-AgentsCommand -IncludeTools $includeTools
  }
  'starter-kits' {
    if ($SubCommand) { Write-Error "'starter-kits' takes no subcommand (got '$SubCommand')."; exit 2 }
    Invoke-StarterKitsCommand
  }
  default {
    if (-not $SubCommand) {
      Write-Error "Unknown command '$Command'. Expected one of: publishers, agents, starter-kits, <agent-name> describe, <agent-name> list-tools, <starterkit-name> describe."
      exit 2
    }

    switch ($SubCommand) {
      'describe' {
        $agentEntry = Resolve-AgentEntry -AgentKey $Command -IncludeTools $false
        if ($agentEntry) {
          Invoke-AgentDescribeCommand -AgentKey $Command
          break
        }

        $starterKitEntry = Resolve-StarterKitEntry -StarterKitKey $Command
        if ($starterKitEntry) {
          Invoke-StarterKitDescribeCommand -StarterKitKey $Command
          break
        }

        Write-Error "'$Command' did not match an agent or starter kit. Use the folder name (e.g. 'aizynthfinder' or 'drug-discovery')."
        exit 2
      }
      'list-tools' {
        Invoke-AgentSingleListToolsCommand -AgentKey $Command
      }
      default {
        Write-Error "Unknown subcommand '$SubCommand' for '$Command'. Supported: describe, list-tools."
        exit 2
      }
    }
  }
}
