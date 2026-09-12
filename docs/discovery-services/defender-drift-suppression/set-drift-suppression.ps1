<#
.SYNOPSIS
  Create/update the Microsoft Discovery interactive-debug (VS Code tunnel) binary-drift
  suppression rules in Microsoft Defender for Cloud. Idempotent (safe to re-run).

.EXAMPLE
  ./set-drift-suppression.ps1
  ./set-drift-suppression.ps1 -SubscriptionId <sub-guid> -State Enabled

.NOTES
  Requires: Azure CLI, and Security Admin (or Owner) on the subscription.
#>
[CmdletBinding()]
param(
  [string]$SubscriptionId = (az account show --query id -o tsv),
  [ValidateSet('Enabled','Disabled')]
  [string]$State = 'Enabled'
)

$ErrorActionPreference = 'Stop'
$api = '2019-01-01-preview'

function Set-DriftRule {
  param([string]$Name, [string]$Value, [string]$Comment)

  $body = @{
    properties = @{
      alertType = 'K8S.NODE_DriftDetection'
      reason    = 'SpecificEntityFalsePositive'
      state     = $State
      comment   = $Comment
      suppressionAlertsScope = @{
        allOf = @( @{ field = 'entities.process.commandline'; contains = $Value } )
      }
    }
  } | ConvertTo-Json -Depth 8

  # Write without BOM: az rest --body @file rejects a UTF-8 BOM.
  $tmp = New-TemporaryFile
  [System.IO.File]::WriteAllText($tmp, $body)

  Write-Host "==> $Name  (commandline contains '$Value')"
  # The Defender alertsSuppressionRules API occasionally returns a transient 500;
  # retry a few times. Suppress native stderr so it doesn't trip $ErrorActionPreference.
  $url = "https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.Security/alertsSuppressionRules/$Name`?api-version=$api"
  $query = '{name:name, state:properties.state, field:properties.suppressionAlertsScope.allOf[0].field, contains:properties.suppressionAlertsScope.allOf[0].contains}'
  $attempt = 0
  while ($true) {
    $attempt++
    $out = & { $ErrorActionPreference = 'Continue'; az rest --method put --url $url --headers 'Content-Type=application/json' --body "@$tmp" --query $query -o table 2>$null }
    if ($LASTEXITCODE -eq 0) { $out; break }
    if ($attempt -ge 5) { Remove-Item $tmp -Force; throw "Failed to set $Name after $attempt attempts (last exit code $LASTEXITCODE)." }
    Write-Host "   transient error (attempt $attempt), retrying in 5s..."
    Start-Sleep -Seconds 5
  }
  Remove-Item $tmp -Force
}

Write-Host "Subscription: $SubscriptionId"
Write-Host "State:        $State`n"

Set-DriftRule -Name 'Binary-drift-vscode-cli-download' -Value 'vscode-cli.tar.gz' `
  -Comment 'Discovery interactive debug (VS Code tunnel): CLI download + tar extract of vscode-cli.tar.gz. Runtime tools are not in the image.'

Set-DriftRule -Name 'Binary-drift-vscode-cli-tunnel' -Value '/tmp/_debug_c' `
  -Comment 'Discovery interactive debug (VS Code tunnel): CLI/server exec from /tmp/_debug_*. Runtime-fetched binaries are not in the image.'

Write-Host "`nDone. Both rules are now present on subscription $SubscriptionId."
