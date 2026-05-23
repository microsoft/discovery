#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
.SYNOPSIS
    Registers Azure resource providers required for Microsoft Discovery.

.DESCRIPTION
    Cross-platform PowerShell script for Windows, macOS, and Linux that registers the
    Azure resource providers required by Microsoft Discovery and related dependencies.
    The script installs required Az modules unless -SkipModuleInstall is specified,
    signs in when needed, sets the requested subscription context, and prints a clear
    summary of registered, already-registered, pending, and failed providers.

.PARAMETER SubscriptionId
    Required. Azure subscription ID where the providers should be registered.

.PARAMETER TenantId
    Optional. Azure AD tenant ID. Use when the subscription is not in your default tenant.

.PARAMETER ProviderNamespaces
    Optional. Provider namespaces to register. Defaults to the Microsoft Discovery
    provider list embedded in this script.

.PARAMETER Wait
    Optional. Wait for providers to reach Registered state after registration starts.

.PARAMETER TimeoutMinutes
    Optional. Maximum number of minutes to wait when -Wait is used. Default: 20.

.PARAMETER PollSeconds
    Optional. Seconds between registration status checks when -Wait is used. Default: 15.

.PARAMETER SkipModuleInstall
    Optional. Skip automatic Az module installation.

.PARAMETER Force
    Optional. Skip confirmation prompt.

.EXAMPLE
    ./Register-DiscoveryResourceProviders.ps1 `
        -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
        -Wait

.EXAMPLE
    ./Register-DiscoveryResourceProviders.ps1 `
        -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
        -TenantId "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy" `
        -Force

.OUTPUTS
    Exit codes:
      0 - All providers are registered, or registration was successfully started
      2 - One or more providers failed or did not reach Registered state before timeout
      3 - Aborted before registration
      4 - Unhandled exception

.NOTES
    Minimum requirements: Az.Accounts >= 3.0.0, Az.Resources >= 7.0.0
    Platform support: Windows PowerShell 5.1+, PowerShell 7+ on Windows/macOS/Linux
    Script version: 1.0.0
#>

[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]
    [string]$SubscriptionId,

    [Parameter()]
    [ValidatePattern('^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?$')]
    [string]$TenantId,

    [Parameter()]
    [string[]]$ProviderNamespaces = @(
        "Microsoft.Network",
        "Microsoft.Compute",
        "Microsoft.Storage",
        "Microsoft.ManagedIdentity",
        "Microsoft.AlertsManagement",
        "Microsoft.Authorization",
        "Microsoft.CognitiveServices",
        "Microsoft.ContainerInstance",
        "Microsoft.ContainerRegistry",
        "Microsoft.ContainerService",
        "Microsoft.DocumentDB",
        "Microsoft.Features",
        "Microsoft.KeyVault",
        "Microsoft.MachineLearningServices",
        "Microsoft.OperationalInsights",
        "Microsoft.ResourceGraph",
        "Microsoft.Search",
        "Microsoft.Web",
        "Microsoft.Insights",
        "Microsoft.Resources",
        "Microsoft.Sql",
        "Microsoft.App",
        "Microsoft.Bing",
        "Microsoft.Discovery"
    ),

    [Parameter()]
    [switch]$Wait,

    [Parameter()]
    [ValidateRange(1, 180)]
    [int]$TimeoutMinutes = 20,

    [Parameter()]
    [ValidateRange(5, 300)]
    [int]$PollSeconds = 15,

    [Parameter()]
    [switch]$SkipModuleInstall,

    [Parameter()]
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param([string]$Message) Write-Host "`n> $Message" -ForegroundColor White }
function Write-Info { param([string]$Message) Write-Host "  $Message" -ForegroundColor Cyan }
function Write-Done { param([string]$Message) Write-Host "  OK: $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  WARN: $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "  FAIL: $Message" -ForegroundColor Red }

function Exit-Fatal {
    param([string]$Message, [int]$Code = 3)
    Write-Host ""
    Write-Fail $Message
    exit $Code
}

function Ensure-Module {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][version]$MinimumVersion
    )

    $module = Get-Module -ListAvailable -Name $Name |
        Where-Object { $_.Version -ge $MinimumVersion } |
        Sort-Object Version -Descending |
        Select-Object -First 1

    if ($module) {
        Import-Module $Name -MinimumVersion $MinimumVersion -ErrorAction Stop
        Write-Done "$Name $($module.Version) available"
        return
    }

    if ($SkipModuleInstall) {
        Exit-Fatal "$Name >= $MinimumVersion is required. Install it or rerun without -SkipModuleInstall."
    }

    Write-Info "Installing $Name >= $MinimumVersion for current user..."
    Install-Module -Name $Name -MinimumVersion $MinimumVersion -Scope CurrentUser -Repository PSGallery -Force -AllowClobber
    Import-Module $Name -MinimumVersion $MinimumVersion -ErrorAction Stop
    Write-Done "$Name installed"
}

function Connect-Subscription {
    $context = Get-AzContext -ErrorAction SilentlyContinue
    if (-not $context) {
        Write-Info "No Azure context found. Starting sign-in..."
        if ([string]::IsNullOrWhiteSpace($TenantId)) {
            Connect-AzAccount -ErrorAction Stop | Out-Null
        }
        else {
            Connect-AzAccount -Tenant $TenantId -ErrorAction Stop | Out-Null
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace($TenantId) -and $context.Tenant.Id -ne $TenantId) {
        Write-Info "Current tenant is $($context.Tenant.Id). Signing in to requested tenant $TenantId..."
        Connect-AzAccount -Tenant $TenantId -ErrorAction Stop | Out-Null
    }
    else {
        Write-Done "Using signed-in account $($context.Account.Id)"
    }

    if ([string]::IsNullOrWhiteSpace($TenantId)) {
        Set-AzContext -SubscriptionId $SubscriptionId -ErrorAction Stop | Out-Null
    }
    else {
        Set-AzContext -SubscriptionId $SubscriptionId -Tenant $TenantId -ErrorAction Stop | Out-Null
    }
    Write-Done "Using subscription $SubscriptionId"
}

function Normalize-ProviderNamespaces {
    param([string[]]$Namespaces)

    $normalized = New-Object 'System.Collections.Generic.List[string]'
    foreach ($namespaceGroup in $Namespaces) {
        foreach ($namespace in ($namespaceGroup -split '[,;]')) {
            $trimmed = $namespace.Trim()
            if (-not [string]::IsNullOrWhiteSpace($trimmed) -and -not $normalized.Contains($trimmed)) {
                $normalized.Add($trimmed)
            }
        }
    }

    if ($normalized.Count -eq 0) {
        Exit-Fatal "At least one provider namespace is required."
    }

    return $normalized.ToArray()
}

function Get-ProviderState {
    param([string]$Namespace)

    $provider = Get-AzResourceProvider -ProviderNamespace $Namespace -ErrorAction SilentlyContinue
    if (-not $provider) {
        return "NotFound"
    }

    $states = @($provider | ForEach-Object { $_.RegistrationState } | Where-Object { $_ })
    if ($states.Count -eq 0) {
        return "Unknown"
    }

    if ($states -contains "Registered") {
        return "Registered"
    }

    return ($states | Select-Object -First 1)
}

try {
    Write-Step "Checking prerequisites"
    Ensure-Module -Name "Az.Accounts" -MinimumVersion ([version]"3.0.0")
    Ensure-Module -Name "Az.Resources" -MinimumVersion ([version]"7.0.0")

    Write-Step "Connecting to Azure"
    Connect-Subscription

    $providers = Normalize-ProviderNamespaces -Namespaces $ProviderNamespaces

    Write-Step "Registration plan"
    Write-Info "Subscription: $SubscriptionId"
    Write-Info "Provider count: $($providers.Count)"
    foreach ($provider in $providers) {
        Write-Info "- $provider"
    }

    if (-not $Force -and -not $WhatIfPreference) {
        $answer = Read-Host "`nRegister these resource providers? Type 'yes' to continue"
        if ($answer -ne "yes") {
            Exit-Fatal "Registration cancelled by user."
        }
    }

    $registered = New-Object 'System.Collections.Generic.List[string]'
    $alreadyRegistered = New-Object 'System.Collections.Generic.List[string]'
    $pending = New-Object 'System.Collections.Generic.List[string]'
    $failed = New-Object 'System.Collections.Generic.List[string]'

    Write-Step "Registering providers"
    foreach ($provider in $providers) {
        $state = Get-ProviderState -Namespace $provider
        if ($state -eq "Registered") {
            Write-Done "$provider already registered"
            $alreadyRegistered.Add($provider)
            continue
        }

        if ($state -eq "NotFound") {
            Write-Fail "$provider was not found in this cloud or subscription"
            $failed.Add($provider)
            continue
        }

        if ($PSCmdlet.ShouldProcess($provider, "Register Azure resource provider")) {
            try {
                Register-AzResourceProvider -ProviderNamespace $provider -ErrorAction Stop | Out-Null
                Write-Done "$provider registration started"
                $registered.Add($provider)
            }
            catch {
                Write-Fail "$provider registration failed: $($_.Exception.Message)"
                $failed.Add($provider)
            }
        }
        else {
            Write-Info "$provider would be registered"
            $pending.Add($provider)
        }
    }

    if ($Wait -and $failed.Count -eq 0 -and -not $WhatIfPreference) {
        Write-Step "Waiting for registration"
        $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
        do {
            $notReady = @()
            foreach ($provider in $providers) {
                $state = Get-ProviderState -Namespace $provider
                if ($state -ne "Registered") {
                    $notReady += [pscustomobject]@{ Namespace = $provider; State = $state }
                }
            }

            if ($notReady.Count -eq 0) {
                Write-Done "All providers are registered"
                break
            }

            if ((Get-Date) -ge $deadline) {
                foreach ($item in $notReady) {
                    Write-Fail "$($item.Namespace) did not register before timeout. Current state: $($item.State)"
                    $failed.Add($item.Namespace)
                }
                break
            }

            Write-Info "$($notReady.Count) provider(s) still pending. Checking again in $PollSeconds seconds..."
            Start-Sleep -Seconds $PollSeconds
        } while ($true)
    }

    Write-Step "Summary"
    Write-Done "Already registered: $($alreadyRegistered.Count)"
    Write-Done "Registration started: $($registered.Count)"
    if ($pending.Count -gt 0) { Write-Warn "Pending/previewed: $($pending.Count)" }
    if ($failed.Count -gt 0) { Write-Fail "Failed: $($failed.Count)" }

    if ($failed.Count -gt 0) {
        exit 2
    }

    exit 0
}
catch {
    Write-Host ""
    Write-Fail "Unhandled error: $($_.Exception.Message)"
    exit 4
}
