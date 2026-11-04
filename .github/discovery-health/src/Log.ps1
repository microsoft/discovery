# Logging, redaction, public messages and GitHub annotations.

$script:DhMessages = $null

function Initialize-DhLog {
  param([Parameter(Mandatory)][string]$OutputDir)
  if (-not (Test-Path -LiteralPath $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }
  $script:Dh.LogPath = Join-Path $OutputDir 'harness.log'
}

function Test-DhGitHubActions { return ($env:GITHUB_ACTIONS -eq 'true') }

function Add-DhMask {
  <#
  .SYNOPSIS Registers a sensitive literal for redaction (and ::add-mask:: on GitHub).
  #>
  param([AllowEmptyString()][string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value) -or $Value.Length -lt 4) { return }
  if ($script:Dh.Masks.Contains($Value)) { return }
  $script:Dh.Masks.Add($Value)
  if (Test-DhGitHubActions) { [Console]::Out.WriteLine("::add-mask::$Value") }
}

function Protect-DhText {
  <#
  .SYNOPSIS Best-effort redaction for free text that may reach public output.
  .NOTES Public reports are generated from templated messages; this is defense in depth.
  #>
  param([AllowEmptyString()][AllowNull()][string]$Text)
  if ([string]::IsNullOrEmpty($Text)) { return [string]$Text }
  $out = $Text
  foreach ($mask in ($script:Dh.Masks | Sort-Object Length -Descending)) {
    $out = [regex]::Replace($out, [regex]::Escape($mask), '***', 'IgnoreCase')
  }
  $out = [regex]::Replace($out, '(?i)\bbearer\s+[A-Za-z0-9\-\._~\+/]+=*', 'Bearer ***')
  $out = [regex]::Replace($out, 'eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*', '<jwt>')
  $out = [regex]::Replace($out, '(?i)((?:^|[?&\s;"''(])(?:sig|se|st|sp|sv|sr|spr|skoid|sktid|skt|ske|sks|skv|sdd)=)[^&\s"''<>)]+', '$1***')
  $out = [regex]::Replace($out, '(?i)\b(api[-_]?key|access[-_]?key|account[-_]?key|password|passwd|secret|client[-_]?secret|token|connectionstring)(["'']?\s*[:=]\s*["'']?)[^\s"'',;]+', '$1$2***')
  $out = [regex]::Replace($out, '(?i)AccountKey=[^;\s]+', 'AccountKey=***')
  $out = [regex]::Replace($out, 'https?://[^\s"''<>()\]]+', '<url>')
  $out = [regex]::Replace($out, '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', '<guid>')
  $out = [regex]::Replace($out, '(?i)/subscriptions/[^/\s"'']+(/resourceGroups/[^/\s"'']+)?', '/subscriptions/***')
  return $out
}

function ConvertTo-DhPublicParam {
  param($Value)
  if ($null -eq $Value) { return '' }
  $text = Protect-DhText ([string]$Value)
  if ($text.Length -gt 160) { $text = $text.Substring(0, 157) + '...' }
  if ($text -match '^[\w .:/\-+#,()=\[\]*<>@]*$') { return $text }
  return '<redacted>'
}

function Get-DhMessage {
  <#
  .SYNOPSIS Renders a public message from the catalog with sanitized parameters.
  #>
  param([Parameter(Mandatory)][string]$Code, [hashtable]$Params = @{})
  if ($null -eq $script:DhMessages) {
    $script:DhMessages = Import-PowerShellDataFile -Path (Join-Path $script:DhRoot 'templates/messages.psd1')
  }
  $template = $script:DhMessages[$Code]
  if (-not $template) { $template = "Unknown message code $Code." }
  return [regex]::Replace($template, '\{(\w+)\}', {
      param($m)
      $key = $m.Groups[1].Value
      if ($Params.ContainsKey($key)) { return (ConvertTo-DhPublicParam $Params[$key]) }
      return ''
    })
}

function Test-DhMessageCode {
  param([string]$Code)
  if ($null -eq $script:DhMessages) {
    $script:DhMessages = Import-PowerShellDataFile -Path (Join-Path $script:DhRoot 'templates/messages.psd1')
  }
  return $script:DhMessages.ContainsKey($Code)
}

function Write-DhLog {
  param(
    [ValidateSet('debug', 'info', 'warn', 'error')][string]$Level = 'info',
    [Parameter(Mandatory)][AllowEmptyString()][string]$Message,
    [string]$Scope = ''
  )
  if ($Level -eq 'debug' -and $env:DH_DEBUG -ne '1') { return }
  $prefix = if ($Scope) { "[$Scope] " } else { '' }
  $line = '[{0}] [{1}] {2}{3}' -f (Get-DhUtcNow).ToString('HH:mm:ss'), $Level.ToUpperInvariant(), $prefix, (Protect-DhText $Message)
  [Console]::Out.WriteLine($line)
  if ($script:Dh.LogPath) {
    try { [System.IO.File]::AppendAllText($script:Dh.LogPath, $line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false)) } catch { }
  }
}

function ConvertTo-DhAnnotationText {
  param([string]$Text)
  return ($Text -replace '%', '%25' -replace "`r", '%0D' -replace "`n", '%0A')
}

function Write-DhAnnotation {
  param([ValidateSet('notice', 'warning', 'error')][string]$Level, [string]$Title, [string]$Message)
  if (-not (Test-DhGitHubActions)) { return }
  $safeTitle = ConvertTo-DhAnnotationText (Protect-DhText $Title) -replace ',', ';' -replace '::', ':'
  [Console]::Out.WriteLine(('::{0} title={1}::{2}' -f $Level, $safeTitle, (ConvertTo-DhAnnotationText (Protect-DhText $Message))))
}
