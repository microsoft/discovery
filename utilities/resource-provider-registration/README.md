# Register-DiscoveryResourceProviders.ps1

Cross-platform PowerShell script that registers Azure resource providers required for Microsoft Discovery and related dependencies.

## Prerequisites

| Requirement | Details |
|---|---|
| PowerShell | 5.1+ on Windows, 7.x on macOS/Linux |
| Az modules | `Az.Accounts >= 3.0.0`, `Az.Resources >= 7.0.0` auto-installed unless `-SkipModuleInstall` |
| Azure permissions | Contributor or Owner on the target subscription, or another role allowed to register resource providers |
| Sign-in | The script signs in with `Connect-AzAccount` when needed |

## Default providers

The script registers these providers by default:

```text
Microsoft.Network
Microsoft.Compute
Microsoft.Storage
Microsoft.ManagedIdentity
Microsoft.AlertsManagement
Microsoft.Authorization
Microsoft.CognitiveServices
Microsoft.ContainerInstance
Microsoft.ContainerRegistry
Microsoft.ContainerService
Microsoft.DocumentDB
Microsoft.Features
Microsoft.KeyVault
Microsoft.MachineLearningServices
Microsoft.OperationalInsights
Microsoft.ResourceGraph
Microsoft.Search
Microsoft.Web
Microsoft.Insights
Microsoft.Resources
Microsoft.Sql
Microsoft.App
Microsoft.Bing
Microsoft.Discovery
```

## Usage

### Interactive

```powershell
./Register-DiscoveryResourceProviders.ps1 `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

### Register and wait for completion

```powershell
./Register-DiscoveryResourceProviders.ps1 `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -Wait
```

### Cross-tenant subscription

```powershell
./Register-DiscoveryResourceProviders.ps1 `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -TenantId "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy" `
    -Wait
```

### CI / automation

```powershell
./Register-DiscoveryResourceProviders.ps1 `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -SkipModuleInstall `
    -Force
```

### Register a custom provider list

```powershell
./Register-DiscoveryResourceProviders.ps1 `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -ProviderNamespaces "Microsoft.Network","Microsoft.Compute","Microsoft.Storage"
```

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `-SubscriptionId` | Yes | Azure subscription GUID where providers are registered |
| `-TenantId` | Optional | Tenant GUID for cross-tenant subscriptions |
| `-ProviderNamespaces` | Optional | Provider namespaces to register; defaults to the Discovery provider list |
| `-Wait` | Optional | Wait until all providers reach `Registered` |
| `-TimeoutMinutes` | Optional | Maximum wait time when `-Wait` is used; default `20` |
| `-PollSeconds` | Optional | Seconds between status checks when `-Wait` is used; default `15` |
| `-SkipModuleInstall` | Optional | Skip auto-installing Az modules |
| `-Force` | Optional | Skip confirmation prompt |
| `-WhatIf` | Optional | Preview registrations without making changes |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All providers are registered, or registration was successfully started |
| 2 | One or more providers failed or did not reach `Registered` before timeout |
| 3 | Aborted before registration |
| 4 | Unhandled exception |
