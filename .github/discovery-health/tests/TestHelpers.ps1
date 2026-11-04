# Minimal, dependency-free test harness (no Pester) so tests run the same on Windows and GitHub runners.

$script:DhTestResults = [System.Collections.Generic.List[object]]::new()

function Test-Case {
  param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Body)
  try {
    & $Body
    $script:DhTestResults.Add([pscustomobject]@{ name = $Name; ok = $true; error = '' })
    Write-Host "PASS $Name"
  } catch {
    $script:DhTestResults.Add([pscustomobject]@{ name = $Name; ok = $false; error = $_.Exception.Message })
    Write-Host "FAIL $Name :: $($_.Exception.Message)"
    Write-Host ($_.ScriptStackTrace -split "`n" | Select-Object -First 4 | Out-String)
  }
}

function Assert-True { param($Condition, [string]$Message = 'expected true') if (-not $Condition) { throw $Message } }
function Assert-False { param($Condition, [string]$Message = 'expected false') if ($Condition) { throw $Message } }
function Assert-Equal {
  param($Expected, $Actual, [string]$Message = '')
  if ($Expected -is [array] -or $Actual -is [array]) {
    $e = (@($Expected) | ConvertTo-Json -Compress -Depth 20); $a = (@($Actual) | ConvertTo-Json -Compress -Depth 20)
    if ($e -ne $a) { throw "expected $e but got $a. $Message" }
    return
  }
  if ($Expected -ne $Actual) { throw "expected '$Expected' but got '$Actual'. $Message" }
}
function Assert-Match { param([string]$Text, [string]$Pattern, [string]$Message = '') if ($Text -notmatch $Pattern) { throw "'$Text' does not match /$Pattern/. $Message" } }
function Assert-NotMatch { param([string]$Text, [string]$Pattern, [string]$Message = '') if ($Text -match $Pattern) { throw "'$Text' unexpectedly matches /$Pattern/. $Message" } }
function Assert-Throws { param([scriptblock]$Body, [string]$Message = 'expected an exception') $threw = $false; try { & $Body } catch { $threw = $true }; if (-not $threw) { throw $Message } }

function Complete-DhTestFile {
  $failed = @($script:DhTestResults | Where-Object { -not $_.ok })
  Write-Host ('SUMMARY {0} passed, {1} failed' -f ($script:DhTestResults.Count - $failed.Count), $failed.Count)
  if ($failed.Count -gt 0) { exit 1 }
  exit 0
}

function Get-DhTestModule {
  $root = Split-Path -Parent $PSScriptRoot
  Import-Module (Join-Path $root 'DiscoveryHealth.psd1') -Force
  return (Get-Module DiscoveryHealth)
}

function New-DhTestConfig {
  param([hashtable]$Overrides = @{})
  $module = Get-Module DiscoveryHealth
  $base = [ordered]@{
    subscriptionId = '00000000-1111-2222-3333-444444444444'; tenantId = '55555555-6666-7777-8888-999999999999'; resourceGroup = 'rg-dgt-test'; location = 'eastus'
    acrName = 'dgttestacr'; workspaceEndpoint = 'https://fakews.workspace.discovery.azure.com'; project = 'dgt-project'; chatModel = 'gpt-test'
    nodePools = @([ordered]@{ id = '/subscriptions/00000000-1111-2222-3333-444444444444/resourceGroups/rg/providers/Microsoft.Discovery/supercomputers/sc/nodepools/cpu'; skus = @('Standard_D4s_v6', 'Standard_D2s_v6', 'Standard_E4as_v6'); gpu = $false })
    pollSeconds = 2; deadlineMinutes = 30
  }
  foreach ($key in $Overrides.Keys) { $base[$key] = $Overrides[$key] }
  return (& $module { param($o) Read-DhConfig -Overrides $o } $base)
}
