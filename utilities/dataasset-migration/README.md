# Migrate-DiscoveryDataToStorage.ps1

This script migrates a Discovery v1 `DataContainer` and its child `DataAssets` to a v2 `StorageContainer` and `StorageAssets`.

It reads an existing source resource of type `Microsoft.Discovery/DataContainers` using API version `2025-07-01-preview` and creates the corresponding target resources of type `Microsoft.Discovery/StorageContainers` and `Microsoft.Discovery/StorageContainers/StorageAssets` using API version `2026-02-01-preview`.

The script does not move data. It reuses the same Azure Storage account already referenced by the source `DataContainer` and creates new control-plane metadata resources that point at the same paths.

## What The Script Does

- Reads the source `DataContainer`
- Determines the backing storage account from the source `dataStore`
- Lists all source `DataAssets`
- Validates or normalizes source asset metadata needed by v2
- Creates or reuses the target `StorageContainer`
- Creates child `StorageAssets` for each migratable source asset
- Optionally writes a JSON migration report

## What The Script Does Not Do

- It does not delete the source `DataContainer`
- It does not delete the source `DataAssets`
- It does not move, copy, or rewrite blobs/files in storage
- It does not create a new Azure Storage account

## Platform Support

The script is designed to run on:

- Windows
- Linux
- macOS

Requirements:

- PowerShell 7 or later (`pwsh`)
- `Az.Accounts` PowerShell module
- `Az.Resources` PowerShell module
- Azure sign-in with access to the target subscription and source storage account

The script does not rely on Windows-only cmdlets or Windows-specific path behavior.

## Required Permissions

The caller must have one of the following roles on the target subscription or resource group:

- `Microsoft Discovery Platform Contributor (Preview)`
- `Microsoft Discovery Platform Administrator (Preview)`
- `Contributor`

The caller must also be able to read the existing Azure Storage account referenced by the source `DataContainer`.

## Supported Source DataStore Kinds

- `AzureStorageBlob` -> migrated to `AzureStorageBlob`
- `AzureStorageFile` -> migrated to `AzureStorageBlob`
- `DiscoveryStorage` -> not supported

When the source kind is `AzureStorageFile`, the script preserves the `storageAccountId` but does not migrate `fileShareName`.

## Parameters

### `DataContainerResourceId`

Full ARM resource ID of the source `DataContainer`.

Example:

```text
/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Discovery/DataContainers/<container-name>
```

### `TargetResourceGroup`

Resource group where the target `StorageContainer` will be created or reused.

### `StorageContainerName`

Name of the target `StorageContainer`.

### `Tags`

Optional hashtable of tags to apply to the target `StorageContainer` and `StorageAssets`.

If omitted:

- `StorageContainer` tags default to source `DataContainer` tags
- `StorageAsset` tags default to source `DataAsset` tags

### `WhatIf`

Runs a dry-run and prints the migration plan without creating resources.

### `OutputJsonReport`

Optional path to write a JSON summary of the migration.

## Basic Usage

### Windows PowerShell 7 / pwsh

```powershell
.\Migrate-DiscoveryDataToStorage.ps1 `
  -DataContainerResourceId "/subscriptions/<sub>/resourceGroups/<source-rg>/providers/Microsoft.Discovery/DataContainers/<data-container-name>" `
  -TargetResourceGroup "<target-rg>" `
  -StorageContainerName "<storage-container-name>"
```

### Linux or macOS

```powershell
pwsh ./Migrate-DiscoveryDataToStorage.ps1 `
  -DataContainerResourceId "/subscriptions/<sub>/resourceGroups/<source-rg>/providers/Microsoft.Discovery/DataContainers/<data-container-name>" `
  -TargetResourceGroup "<target-rg>" `
  -StorageContainerName "<storage-container-name>"
```

### Dry Run

```powershell
.\Migrate-DiscoveryDataToStorage.ps1 `
  -DataContainerResourceId "/subscriptions/<sub>/resourceGroups/<source-rg>/providers/Microsoft.Discovery/DataContainers/<data-container-name>" `
  -TargetResourceGroup "<target-rg>" `
  -StorageContainerName "<storage-container-name>" `
  -WhatIf `
  -OutputJsonReport ".\migration-preview.json"
```

## Authentication

Before running the script, sign in to Azure with PowerShell:

```powershell
Connect-AzAccount
```

If the source `DataContainer` is in a different tenant, sign in explicitly to that tenant and subscription:

```powershell
Connect-AzAccount -TenantId "<tenant-id>" -Subscription "<subscription-id>"
```

If needed, device-code sign-in also works:

```powershell
Connect-AzAccount -TenantId "<tenant-id>" -Subscription "<subscription-id>" -UseDeviceAuthentication
```

## Existing StorageContainer Behavior

The script checks whether the target `StorageContainer` already exists before trying to create it.

### If the target `StorageContainer` does not exist

The script:

- creates it
- waits until its provisioning state becomes `Succeeded`
- then creates child `StorageAssets`

### If the target `StorageContainer` already exists and is `Succeeded`

The script:

- does not recreate it
- warns that it will reuse the existing `StorageContainer`
- warns that `StorageAssets` with the same names may be overwritten
- asks for confirmation before creating `StorageAssets`

### If the target `StorageContainer` already exists and is not `Succeeded`

The script exits with an error and instructs the user to either:

- fix the existing `StorageContainer`, or
- choose a different `StorageContainerName`

## StorageAsset Creation Behavior

The script waits for a newly created `StorageContainer` to reach `Succeeded` before creating child `StorageAssets`.

This is required because the service rejects child resource creation while the parent is still in `Accepted`.

For source asset paths:

- empty or missing paths are skipped
- paths that begin with `/` are normalized to relative paths by trimming the leading slash

This is needed because blob-backed `StorageAsset` paths must be relative.

## Output And Reports

At the end of a run, the script prints:

- target `StorageContainer` resource ID
- number of assets created
- number of assets skipped
- number of assets failed

If `OutputJsonReport` is specified, the script writes a JSON report containing:

- source `DataContainer`
- target `StorageContainer`
- storage account ID
- created assets
- skipped assets
- failed assets

## Common Failure Cases

### Invalid authentication token

Cause:

- PowerShell `Az` context is not logged into the right tenant/subscription

Fix:

- run `Connect-AzAccount` again for the correct tenant/subscription

### Target resource group does not exist

Cause:

- `TargetResourceGroup` is wrong or in a different subscription

Fix:

- use the correct resource group name

### Storage account does not exist

Cause:

- source `DataContainer` references a storage account resource ID that ARM cannot resolve

Fix:

- verify the source `DataContainer` metadata and the referenced storage account

### StorageAsset returns `400 Bad Request`

Common causes:

- parent `StorageContainer` not yet in `Succeeded`
- source path begins with `/`
- source path is empty or invalid for blob-backed storage

The current script handles the first two automatically.

## Example End-To-End Flow

1. Run a dry-run first.
2. Confirm the target resource group, storage account, and asset count look correct.
3. Run the script without `WhatIf`.
4. If the target `StorageContainer` already exists, confirm reuse when prompted.
5. Review the summary or JSON report.

## Notes

- The script is interactive by design and prompts before creating or reusing the target `StorageContainer`.
- Existing `StorageAssets` with the same names may be updated or overwritten by the service when using the same `StorageContainerName`.
- Using `WhatIf` is recommended before every live run.
