# Shared state and low-level helpers for the DiscoveryHealth module.

$script:DhTemplateVersion = '1'
$script:DhStages = @('build', 'image-smoke', 'tool-register', 'tool-run', 'agent-register', 'round-trip')
$script:DhToolStages = @('build', 'image-smoke', 'tool-register', 'tool-run')
$script:DhAgentStages = @('agent-register', 'round-trip')
$script:DhOkStatuses = @('passed', 'cached', 'warning')
$script:DhHasDateKind = (Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind') -and $env:DH_FORCE_JSON_FALLBACK -ne '1'

$script:Dh = @{
  Config          = $null
  RunId           = $null
  OutputDir       = $null
  GitSha          = $null
  Untrusted       = $false
  Masks           = [System.Collections.Generic.List[string]]::new()
  Tokens          = @{}
  LastLoginUtc    = $null
  LogPath         = $null
  HarnessErrors   = [System.Collections.Generic.List[string]]::new()
  CancelRequested = $false
}

function Get-DhState { return $script:Dh }

function Get-DhRepoRoot {
  param([string]$StartPath = $script:DhRoot)
  $root = (& git -C $StartPath rev-parse --show-toplevel 2>$null)
  if ($LASTEXITCODE -eq 0 -and $root) { return ([string]$root).Trim() }
  return (Resolve-Path (Join-Path $script:DhRoot '..\..')).Path
}

function Get-DhUtcNow { return [DateTime]::UtcNow }

function ConvertTo-DhIso {
  param([datetime]$Value)
  return $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

function New-DhRunId {
  $suffix = -join ((1..6) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
  return ('{0}-{1}' -f (Get-DhUtcNow).ToString('yyyyMMddHHmmss'), $suffix)
}

function Get-DhSha256Hex {
  param([AllowEmptyString()][string]$Text)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes([string]$Text)
  $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
  return ([System.Convert]::ToHexString($hash)).ToLowerInvariant()
}

function Get-DhFileSha256 {
  param([Parameter(Mandatory)][string]$Path)
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function ConvertTo-DhSafeName {
  param([string]$Value, [int]$MaxLength = 64)
  $safe = ([string]$Value).ToLowerInvariant() -replace '[^a-z0-9-]', '-' -replace '-{2,}', '-'
  $safe = $safe.Trim('-')
  if ($safe.Length -gt $MaxLength) { $safe = $safe.Substring(0, $MaxLength).Trim('-') }
  return $safe
}

function ConvertTo-DhAlnum {
  param([string]$Value)
  return (([string]$Value).ToLowerInvariant() -replace '[^a-z0-9]', '')
}

function ConvertFrom-DhJToken {
  # PowerShell adapts JObject as a dictionary (so .Type would read a key); dispatch on CLR type instead.
  param($Token)
  if ($Token -is [Newtonsoft.Json.Linq.JObject]) {
    $map = [ordered]@{}
    foreach ($property in $Token.Properties()) { $map[$property.Name] = ConvertFrom-DhJToken $property.Value }
    return $map
  }
  if ($Token -is [Newtonsoft.Json.Linq.JArray]) {
    $items = [System.Collections.Generic.List[object]]::new()
    foreach ($child in $Token.Children()) { $items.Add((ConvertFrom-DhJToken $child)) }
    return , $items.ToArray()
  }
  if ($Token -is [Newtonsoft.Json.Linq.JValue]) {
    if ($Token.Type -eq [Newtonsoft.Json.Linq.JTokenType]::Null -or $Token.Type -eq [Newtonsoft.Json.Linq.JTokenType]::Undefined) { return $null }
    return $Token.Value
  }
  return $null
}

function ConvertFrom-DhJson {
  <#
  .SYNOPSIS Parses JSON into ordered hashtables without converting date-like strings.
  #>
  param([Parameter(ValueFromPipeline)][AllowEmptyString()][string]$Json)
  if ([string]::IsNullOrWhiteSpace($Json)) { return $null }
  if ($script:DhHasDateKind) {
    return ($Json | ConvertFrom-Json -AsHashtable -Depth 200 -DateKind String)
  }
  $reader = [Newtonsoft.Json.JsonTextReader]::new([System.IO.StringReader]::new($Json))
  $reader.DateParseHandling = [Newtonsoft.Json.DateParseHandling]::None
  $reader.MaxDepth = 256
  $token = [Newtonsoft.Json.Linq.JToken]::ReadFrom($reader)
  return (ConvertFrom-DhJToken $token)
}

function ConvertTo-DhJson {
  param($InputObject, [switch]$Compress)
  if ($Compress) { return (ConvertTo-Json -InputObject $InputObject -Depth 100 -Compress) }
  return (ConvertTo-Json -InputObject $InputObject -Depth 100)
}

function Copy-DhObject {
  param($InputObject)
  if ($null -eq $InputObject) { return $null }
  return (ConvertFrom-DhJson (ConvertTo-DhJson $InputObject -Compress))
}

function Write-DhTextFile {
  <#
  .SYNOPSIS Atomically writes UTF-8 text (temp file + rename) so readers never see partial content.
  #>
  param([Parameter(Mandatory)][string]$Path, [AllowEmptyString()][string]$Content)
  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  $temp = '{0}.{1}.tmp' -f $Path, [guid]::NewGuid().ToString('N')
  try {
    [System.IO.File]::WriteAllText($temp, [string]$Content, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $Path -Force
  } finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
  }
}

function Write-DhJsonFile {
  param([Parameter(Mandatory)][string]$Path, $InputObject)
  Write-DhTextFile -Path $Path -Content (ConvertTo-DhJson $InputObject)
}

function Read-DhJsonFile {
  param([Parameter(Mandatory)][string]$Path)
  return (ConvertFrom-DhJson ([System.IO.File]::ReadAllText($Path)))
}

function Get-DhValue {
  <#
  .SYNOPSIS Safe nested lookup on dictionaries: Get-DhValue $h 'a.b.c' $default.
  #>
  param($Object, [string]$Path, $Default = $null)
  $current = $Object
  foreach ($segment in $Path.Split('.')) {
    if ($null -eq $current) { return $Default }
    if ($current -is [System.Collections.IDictionary]) {
      if (-not $current.Contains($segment)) { return $Default }
      $current = $current[$segment]
    } else {
      return $Default
    }
  }
  if ($null -eq $current) { return $Default }
  return $current
}

function Test-DhTruthy {
  param($Value)
  if ($null -eq $Value) { return $false }
  if ($Value -is [bool]) { return $Value }
  if ($Value -is [string]) { return -not [string]::IsNullOrWhiteSpace($Value) -and $Value -notin @('false', '0') }
  if ($Value -is [System.Collections.ICollection]) { return $Value.Count -gt 0 }
  if ($Value -is [int] -or $Value -is [long] -or $Value -is [double]) { return $Value -ne 0 }
  return $true
}

function Format-DhDuration {
  param([double]$Seconds)
  $span = [TimeSpan]::FromSeconds([math]::Max(0, $Seconds))
  if ($span.TotalHours -ge 1) { return ('{0}h{1:00}m' -f [int][math]::Floor($span.TotalHours), $span.Minutes) }
  if ($span.TotalMinutes -ge 1) { return ('{0}m{1:00}s' -f [int][math]::Floor($span.TotalMinutes), $span.Seconds) }
  return ('{0}s' -f [int]$span.TotalSeconds)
}
