# Azure CLI + REST access with token caching, retries, failure classification and
# GitHub OIDC re-login for long-running jobs (federated assertions expire after minutes).

$script:DhAudiences = @{
  arm       = 'https://management.azure.com/'
  discovery = 'https://discovery.azure.com'
  storage   = 'https://storage.azure.com/'
}

function Test-DhOidcAvailable {
  return [bool]($env:ACTIONS_ID_TOKEN_REQUEST_URL -and $env:ACTIONS_ID_TOKEN_REQUEST_TOKEN -and $env:AZURE_CLIENT_ID -and $env:AZURE_TENANT_ID)
}

function Invoke-DhAzRaw {
  param([string[]]$Arguments)
  $env:AZURE_CORE_COLLECT_TELEMETRY = 'no'
  $env:AZURE_CORE_ONLY_SHOW_ERRORS = 'true'
  $errFile = [System.IO.Path]::GetTempFileName()
  try {
    $stdout = & az @Arguments 2> $errFile
    $code = $LASTEXITCODE
    $stderr = [System.IO.File]::ReadAllText($errFile)
  } finally {
    Remove-Item -LiteralPath $errFile -Force -ErrorAction SilentlyContinue
  }
  return @{ exitCode = $code; stdout = (@($stdout) -join "`n"); stderr = $stderr }
}

function Update-DhAzLogin {
  <#
  .SYNOPSIS Re-mints a GitHub OIDC assertion and logs the Azure CLI in again (CI only).
  #>
  param([switch]$Force)
  if (-not (Test-DhOidcAvailable)) { return $false }
  if (-not $Force -and $script:Dh.LastLoginUtc -and ((Get-DhUtcNow) - $script:Dh.LastLoginUtc).TotalMinutes -lt 4) { return $true }
  $uri = '{0}&audience={1}' -f $env:ACTIONS_ID_TOKEN_REQUEST_URL, [Uri]::EscapeDataString('api://AzureADTokenExchange')
  if (([Uri]$uri).Scheme -ne 'https') { throw 'ACTIONS_ID_TOKEN_REQUEST_URL must be https.' }
  $oidc = Invoke-RestMethod -Method Get -Uri $uri -Headers @{ Authorization = "Bearer $($env:ACTIONS_ID_TOKEN_REQUEST_TOKEN)" } -TimeoutSec 30
  $assertion = [string]$oidc.value
  Add-DhMask $assertion
  $login = Invoke-DhAzRaw -Arguments @('login', '--service-principal', '--username', $env:AZURE_CLIENT_ID, '--tenant', $env:AZURE_TENANT_ID, '--federated-token', $assertion, '--allow-no-subscriptions', '--output', 'none')
  if ($login.exitCode -ne 0) { throw ('az login with federated token failed: {0}' -f (Protect-DhText $login.stderr)) }
  $subscription = Get-DhValue $script:Dh.Config 'subscriptionId'
  if ($subscription) { Invoke-DhAzRaw -Arguments @('account', 'set', '--subscription', $subscription) | Out-Null }
  $script:Dh.LastLoginUtc = Get-DhUtcNow
  $script:Dh.Tokens = @{}
  Write-DhLog -Level debug -Message 'Refreshed Azure CLI login from GitHub OIDC.'
  return $true
}

function Test-DhAuthExpiredText {
  param([string]$Text)
  return ($Text -match 'AADSTS700024|AADSTS70043|AADSTS700082|expired|Please run .az login.|refresh token')
}

function Invoke-DhAz {
  <#
  .SYNOPSIS Runs az with telemetry off; re-logs in once on expired federated credentials.
  #>
  param([Parameter(Mandatory)][string[]]$Arguments, [switch]$AsJson)
  $result = Invoke-DhAzRaw -Arguments $Arguments
  if ($result.exitCode -ne 0 -and (Test-DhAuthExpiredText $result.stderr) -and (Test-DhOidcAvailable)) {
    Update-DhAzLogin -Force | Out-Null
    $result = Invoke-DhAzRaw -Arguments $Arguments
  }
  if ($AsJson -and $result.exitCode -eq 0 -and $result.stdout) {
    try { $result.json = ConvertFrom-DhJson $result.stdout } catch { $result.json = $null }
  }
  return $result
}

function Get-DhAccessToken {
  param([ValidateSet('arm', 'discovery', 'storage')][string]$Audience = 'arm', [switch]$Refresh)
  $cached = $script:Dh.Tokens[$Audience]
  if (-not $Refresh -and $cached -and $cached.expiresUtc -gt (Get-DhUtcNow).AddMinutes(5)) { return $cached.token }
  if ((Test-DhOidcAvailable) -and (-not $script:Dh.LastLoginUtc -or ((Get-DhUtcNow) - $script:Dh.LastLoginUtc).TotalMinutes -gt 45)) {
    Update-DhAzLogin -Force | Out-Null
  }
  $result = Invoke-DhAz -Arguments @('account', 'get-access-token', '--resource', $script:DhAudiences[$Audience], '--output', 'json') -AsJson
  if ($result.exitCode -ne 0 -or -not $result.json) {
    throw ('Could not acquire {0} access token: {1}' -f $Audience, (Protect-DhText $result.stderr))
  }
  $token = [string]$result.json.accessToken
  $expires = (Get-DhUtcNow).AddMinutes(30)
  if ($result.json.Contains('expires_on') -and $result.json.expires_on) {
    $expires = [DateTimeOffset]::FromUnixTimeSeconds([long]$result.json.expires_on).UtcDateTime
  }
  $script:Dh.Tokens[$Audience] = @{ token = $token; expiresUtc = $expires }
  return $token
}

function Get-DhFailureCategory {
  <#
  .SYNOPSIS Classifies an error as infrastructure vs contribution from HTTP status and text.
  #>
  param([int]$Status = 0, [string]$Text = '')
  if ($Status -in @(401, 403, 408, 409, 423, 429) -or $Status -ge 500) { return 'infrastructure' }
  $infraPattern = '(?i)(no space left on device|quota|capacity|throttl|timed? ?out|timeout|temporarily unavailable|connection (reset|refused)|name resolution|AADSTS|authorization ?failed|forbidden|Service ?Unavailable|Internal ?Server ?Error|Too ?Many ?Requests|Bad ?Gateway|Gateway ?Time-?out|rate.?limit|server_error|context deadline exceeded|i/o timeout|TLS handshake)'
  if ($Text -match $infraPattern) { return 'infrastructure' }
  return 'contribution'
}

function Invoke-DhRest {
  <#
  .SYNOPSIS HTTP call with bearer token, retries on 429/5xx/network, and JSON parsing.
  .OUTPUTS @{ status; body; raw; headers }
  #>
  param(
    [ValidateSet('GET', 'PUT', 'POST', 'PATCH', 'DELETE', 'HEAD')][string]$Method = 'GET',
    [Parameter(Mandatory)][string]$Uri,
    [ValidateSet('arm', 'discovery', 'storage', 'none')][string]$Audience = 'arm',
    $Body = $null,
    [hashtable]$Headers = @{},
    [string]$ContentType = 'application/json; charset=utf-8',
    [int]$TimeoutSec = 60,
    [int]$MaxAttempts = 4
  )
  $attempt = 0
  $refreshed = $false
  while ($true) {
    $attempt++
    $requestHeaders = @{}
    foreach ($key in $Headers.Keys) { $requestHeaders[$key] = $Headers[$key] }
    if ($Audience -ne 'none') { $requestHeaders['Authorization'] = 'Bearer ' + (Get-DhAccessToken -Audience $Audience -Refresh:$refreshed) }
    $params = @{ Method = $Method; Uri = $Uri; Headers = $requestHeaders; TimeoutSec = $TimeoutSec; SkipHttpErrorCheck = $true; ErrorAction = 'Stop' }
    if ($null -ne $Body) {
      $bytes = if ($Body -is [byte[]]) { $Body } elseif ($Body -is [string]) { [System.Text.Encoding]::UTF8.GetBytes($Body) } else { [System.Text.Encoding]::UTF8.GetBytes((ConvertTo-DhJson $Body -Compress)) }
      $params['Body'] = $bytes
      $params['ContentType'] = $ContentType
    }
    try {
      $response = Invoke-WebRequest @params
    } catch {
      if ($attempt -lt $MaxAttempts) {
        Start-Sleep -Seconds ([math]::Min(30, [math]::Pow(2, $attempt)))
        continue
      }
      return @{ status = 0; body = $null; raw = $_.Exception.Message; headers = @{}; networkError = $true }
    }
    $status = [int]$response.StatusCode
    $raw = if ($response.Content -is [byte[]]) { [System.Text.Encoding]::UTF8.GetString($response.Content) } else { [string]$response.Content }
    if ($status -eq 401 -and -not $refreshed -and $Audience -ne 'none') {
      $refreshed = $true
      if (Test-DhOidcAvailable) { Update-DhAzLogin -Force | Out-Null }
      continue
    }
    if (($status -eq 429 -or $status -ge 500) -and $attempt -lt $MaxAttempts) {
      $delay = [math]::Min(60, [math]::Pow(2, $attempt) * 2)
      $retryAfter = $response.Headers['Retry-After']
      if ($retryAfter) { $parsedDelay = 0; if ([int]::TryParse([string]@($retryAfter)[0], [ref]$parsedDelay)) { $delay = [math]::Min(120, [math]::Max(1, $parsedDelay)) } }
      Start-Sleep -Seconds $delay
      continue
    }
    $body = $null
    if ($raw) {
      try { $body = ConvertFrom-DhJson $raw } catch { $body = $raw }
    }
    return @{ status = $status; body = $body; raw = $raw; headers = $response.Headers }
  }
}

function Get-DhHeaderValue {
  param($Headers, [string]$Name)
  if ($null -eq $Headers) { return '' }
  foreach ($key in @($Headers.Keys)) {
    if ([string]::Equals([string]$key, $Name, [StringComparison]::OrdinalIgnoreCase)) { return [string](@($Headers[$key])[0]) }
  }
  return ''
}

function Get-DhArmBase {
  param([System.Collections.IDictionary]$Config, [string]$ResourceGroup)
  $rg = if ($ResourceGroup) { $ResourceGroup } else { $Config.resourceGroup }
  return ('https://management.azure.com/subscriptions/{0}/resourceGroups/{1}' -f $Config.subscriptionId, $rg)
}
