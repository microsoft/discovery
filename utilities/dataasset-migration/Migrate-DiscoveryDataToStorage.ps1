<#
.SYNOPSIS
    Migrates Discovery v1 DataContainer + DataAssets to v2 StorageContainer + StorageAssets.

.DESCRIPTION
    Reads an existing Microsoft.Discovery/DataContainers resource (API 2025-07-01-preview)
    and creates a corresponding Microsoft.Discovery/StorageContainers plus child StorageAssets
    (API 2026-02-01-preview).

    PLATFORM SUPPORT
    ────────────────
    This script is intended to run on Windows, Linux, and macOS with PowerShell 7+
    (`pwsh`) and the Az PowerShell modules installed. It does not depend on any
    Windows-only cmdlets or file-system behavior.

    The new StorageContainer is linked to the SAME Azure Storage account already used by the
    source DataContainer — no new storage account or blobs are created. Each StorageAsset is
    created pointing to the same path that existed on the corresponding DataAsset.

    SOURCE RESOURCES ARE NOT MODIFIED
    ──────────────────────────────────
    This script is READ-ONLY with respect to all source resources. It only performs GET and
    LIST operations on the source DataContainer and its DataAssets. No DELETE, PATCH, or PUT
    is ever issued against them. The source DataContainer and DataAssets remain fully intact
    and operational after the migration.

    Migration mapping:
      DataStore kind        → StorageStore kind
      ─────────────────────────────────────────
      AzureStorageBlob      → AzureStorageBlob  (storageAccountId passes through)
      AzureStorageFile      → AzureStorageBlob  (storageAccountId used; fileShareName not migrated)
      DiscoveryStorage      → NOT SUPPORTED — script exits with an error

    REQUIRED CALLER PERMISSIONS
    ───────────────────────────
    The identity running this script must have ONE of the following on the target subscription
    or resource group (ARM enforces this for Microsoft.Discovery/* write operations):

      • "Microsoft Discovery Platform Contributor (Preview)"
          Role definition ID: 01288891-85ee-45a7-b367-9db3b752fc65
      • "Microsoft Discovery Platform Administrator (Preview)"
          Role definition ID: 7a2b6e6c-472e-4b39-8878-a26eb63d75c6
      • Standard "Contributor" role (covers Microsoft.Discovery/* via wildcard write)

    The caller's token is also forwarded to ARM when validating the target storage account
    (OBO flow), so the caller must also be able to READ the existing storage account referenced
    by the source DataContainer (i.e., have at least Reader access on that storage account or
    its subscription/resource group).

.PARAMETER DataContainerResourceId
    Full ARM resource ID of the source DataContainer.
    SubscriptionId, source resource group, and container name are all parsed from this value.
    Example: /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Discovery/DataContainers/my-dc

.PARAMETER TargetResourceGroup
    Name of the resource group where the new StorageContainer will be created.
    May be the same as or different from the source resource group.

.PARAMETER StorageContainerName
    Name for the new StorageContainer resource.

.PARAMETER Tags
    Optional hashtable of tags to apply to the StorageContainer and all StorageAssets.
    If omitted, tags are copied from the source DataContainer.

.PARAMETER WhatIf
    Dry-run mode. Shows what would be created without making any ARM API calls.

.PARAMETER OutputJsonReport
    Optional file path to write a JSON summary of the migration results.

.EXAMPLE
    .\Migrate-DiscoveryDataToStorage.ps1 `
        -DataContainerResourceId "/subscriptions/xxx/resourceGroups/src-rg/providers/Microsoft.Discovery/DataContainers/my-dc" `
        -TargetResourceGroup "dest-rg" `
        -StorageContainerName "my-sc"

.EXAMPLE
    # Linux/macOS invocation with PowerShell 7
    pwsh ./Migrate-DiscoveryDataToStorage.ps1 `
        -DataContainerResourceId "/subscriptions/xxx/resourceGroups/src-rg/providers/Microsoft.Discovery/DataContainers/my-dc" `
        -TargetResourceGroup "dest-rg" `
        -StorageContainerName "my-sc"

.EXAMPLE
    # Dry run — shows what would be created without any API calls
    .\Migrate-DiscoveryDataToStorage.ps1 `
        -DataContainerResourceId "/subscriptions/xxx/resourceGroups/src-rg/providers/Microsoft.Discovery/DataContainers/my-dc" `
        -TargetResourceGroup "dest-rg" `
        -StorageContainerName "my-sc" `
        -WhatIf -OutputJsonReport ".\migration-preview.json"

.EXAMPLE
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Discovery/[Dd]ata[Cc]ontainers/[^/]+$')]
    [string] $DataContainerResourceId,

    [Parameter(Mandatory)]
    [string] $TargetResourceGroup,

    [Parameter(Mandatory)]
    [string] $StorageContainerName,

    [Parameter()]
    [hashtable] $Tags,

    [Parameter()]
    [switch] $WhatIf,

    [Parameter()]
    [string] $OutputJsonReport
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -ne 'Core') {
    Write-Error 'This script requires PowerShell 7+ (pwsh) for cross-platform support.'
    exit 1
}

$requiredAzModules = @('Az.Accounts', 'Az.Resources')
foreach ($moduleName in $requiredAzModules) {
    if (-not (Get-Module -ListAvailable -Name $moduleName)) {
        Write-Error "Required PowerShell module '$moduleName' is not installed. Install it before running this script."
        exit 1
    }
}

# ── Constants ─────────────────────────────────────────────────────────────────
$V1_API   = '2025-07-01-preview'
$V2_API   = '2026-02-01-preview'
$ARM_BASE = 'https://management.azure.com'

# ── Console helpers ───────────────────────────────────────────────────────────
function Write-Step { param([string]$Msg) Write-Host "`n▶  $Msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Msg) Write-Host "   ✓ $Msg" -ForegroundColor Green }
function Write-Warn { param([string]$Msg) Write-Host "   ⚠ $Msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$Msg) Write-Host "   ✗ $Msg" -ForegroundColor Red; throw $Msg }

# ── ARM helpers ───────────────────────────────────────────────────────────────
function Get-ArmToken {
    $accessToken = Get-AzAccessToken -ResourceUrl $ARM_BASE -ErrorAction Stop

    if ($accessToken.Token -is [securestring]) {
        return [System.Net.NetworkCredential]::new('', $accessToken.Token).Password
    }

    return [string]$accessToken.Token
}

function Invoke-ArmGet {
    param([string]$ResourceId, [string]$ApiVersion)
    $url     = "${ARM_BASE}${ResourceId}?api-version=${ApiVersion}"
    $headers = @{ Authorization = "Bearer $(Get-ArmToken)"; 'Content-Type' = 'application/json' }
    return Invoke-RestMethod -Uri $url -Method GET -Headers $headers -ErrorAction Stop
}

function Try-Invoke-ArmGet {
    param([string]$ResourceId, [string]$ApiVersion)

    try {
        return Invoke-ArmGet -ResourceId $ResourceId -ApiVersion $ApiVersion
    }
    catch {
        $statusCode = $null

        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }

        if ($statusCode -eq 404) {
            return $null
        }

        throw
    }
}

function Invoke-ArmList {
    param([string]$CollectionPath, [string]$ApiVersion)
    $results = [System.Collections.Generic.List[object]]::new()
    $url     = "${ARM_BASE}${CollectionPath}?api-version=${ApiVersion}"
    do {
        $headers = @{ Authorization = "Bearer $(Get-ArmToken)"; 'Content-Type' = 'application/json' }
        $page    = Invoke-RestMethod -Uri $url -Method GET -Headers $headers -ErrorAction Stop
        if ($page.value) { $results.AddRange([object[]]$page.value) }

        if ($page.PSObject.Properties.Match('nextLink').Count -gt 0) {
            $url = $page.nextLink
        }
        else {
            $url = $null
        }
    } while ($url)
    return $results.ToArray()
}

function Invoke-ArmPut {
    param([string]$ResourceId, [string]$ApiVersion, [object]$Body)
    $url     = "${ARM_BASE}${ResourceId}?api-version=${ApiVersion}"
    $headers = @{ Authorization = "Bearer $(Get-ArmToken)"; 'Content-Type' = 'application/json' }
    $json    = $Body | ConvertTo-Json -Depth 20 -Compress
    return Invoke-RestMethod -Uri $url -Method PUT -Headers $headers -Body $json -ErrorAction Stop
}

function Wait-ForStorageContainerSucceeded {
    param(
        [string]$ResourceId,
        [string]$ApiVersion,
        [int]$TimeoutSeconds = 300,
        [int]$PollSeconds = 5
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

    do {
        $resource = Invoke-ArmGet -ResourceId $ResourceId -ApiVersion $ApiVersion
        $state = $resource.properties.provisioningState

        if ($state -eq 'Succeeded') {
            return $resource
        }

        if ($state -in @('Failed', 'Canceled')) {
            Write-Err "StorageContainer provisioning entered terminal state '$state'."
        }

        Write-Warn "StorageContainer provisioning state is '$state' - waiting ${PollSeconds}s before retrying."
        Start-Sleep -Seconds $PollSeconds
    } while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds)

    Write-Err "Timed out waiting for StorageContainer provisioning to reach 'Succeeded'."
}

# ── Phase 0: Parse inputs and validate Azure session ──────────────────────────
Write-Step 'Phase 0: Parsing inputs and validating Azure session'

$idPattern = '^/subscriptions/(?<sub>[^/]+)/resourceGroups/(?<rg>[^/]+)/providers/(?<ns>[^/]+)/(?<type>[^/]+)/(?<name>[^/]+)$'
if ($DataContainerResourceId -notmatch $idPattern) {
    Write-Err "Cannot parse ARM resource ID: $DataContainerResourceId"
}
$SubscriptionId    = $Matches['sub']
$SourceRG          = $Matches['rg']
$DataContainerName = $Matches['name']

Write-Ok "Subscription ID  : $SubscriptionId"
Write-Ok "Source RG        : $SourceRG"
Write-Ok "DataContainer    : $DataContainerName"
Write-Ok "Target RG        : $TargetResourceGroup"
Write-Ok "StorageContainer : $StorageContainerName"
if ($WhatIf) { Write-Warn 'WhatIf mode — no resources will be created' }

# Confirm Azure login
$ctx = Get-AzContext -ErrorAction SilentlyContinue
if (-not $ctx) { Write-Err 'Not logged in. Run Connect-AzAccount first.' }

# Switch subscription context if needed
if ($ctx.Subscription.Id -ne $SubscriptionId) {
    Write-Warn "Switching Az context from subscription $($ctx.Subscription.Id) → $SubscriptionId"
    Set-AzContext -SubscriptionId $SubscriptionId | Out-Null
    $ctx = Get-AzContext
}
Write-Ok "Authenticated as : $($ctx.Account.Id)"

# Verify target resource group exists
$rgCheck = Get-AzResourceGroup -Name $TargetResourceGroup -ErrorAction SilentlyContinue
if (-not $rgCheck) {
    Write-Err "Target resource group '$TargetResourceGroup' does not exist in subscription $SubscriptionId."
}
Write-Ok "Target RG exists : $($rgCheck.Location)"

# ── Phase 1: Read source DataContainer ───────────────────────────────────────
Write-Step 'Phase 1: Reading source DataContainer'

$dc        = Invoke-ArmGet -ResourceId $DataContainerResourceId -ApiVersion $V1_API
$dataStore = $dc.properties.dataStore
$location  = $dc.location
$sourceTags = if ($dc.tags) { $dc.tags } else { @{} }

Write-Ok "Location         : $location"
Write-Ok "DataStore kind   : $($dataStore.kind)"

# Map DataStore → StorageStore
$storageAccountId = $null
switch ($dataStore.kind) {
    'AzureStorageBlob' {
        $storageAccountId = $dataStore.storageAccountId
        Write-Ok "Storage account  : $storageAccountId"
    }
    'AzureStorageFile' {
        $storageAccountId = $dataStore.storageAccountId
        Write-Ok "Storage account  : $storageAccountId"
        Write-Warn "DataStore is AzureStorageFile — fileShareName '$($dataStore.fileShareName)' will NOT be migrated."
        Write-Warn "The new StorageContainer will reference the storage account with kind=AzureStorageBlob."
    }
    'DiscoveryStorage' {
        Write-Err "DataStore kind 'DiscoveryStorage' has no equivalent in v2 StorageContainers. Migration cannot proceed."
    }
    default {
        Write-Err "Unknown DataStore kind '$($dataStore.kind)'. Cannot determine migration path."
    }
}

# ── Phase 2: List DataAssets ──────────────────────────────────────────────────
Write-Step 'Phase 2: Listing DataAssets'

$dataAssets = Invoke-ArmList -CollectionPath "$DataContainerResourceId/DataAssets" -ApiVersion $V1_API
Write-Ok "Total DataAssets found : $($dataAssets.Count)"

# Validate each asset against v2 required-field constraints
$migratable = [System.Collections.Generic.List[PSCustomObject]]::new()
$skipped    = [System.Collections.Generic.List[PSCustomObject]]::new()

foreach ($asset in $dataAssets) {
    $assetName  = $asset.name
    $desc       = $asset.properties.description
    $path       = $asset.properties.path
    $assetTags  = if ($asset.tags) { $asset.tags } else { $null }

    # path is optional in v1 but required in v2 — skip if missing
    if ([string]::IsNullOrWhiteSpace($path)) {
        Write-Warn "  SKIP '$assetName' — 'path' is null/empty (required in StorageAsset)"
        $skipped.Add([PSCustomObject]@{ Name = $assetName; Reason = "path is null/empty (required in v2 StorageAsset)" })
        continue
    }

    if ($path.StartsWith('/')) {
        $path = $path.TrimStart('/')
        Write-Warn "  '$assetName' — path started with '/'; normalized to relative path '$path'."
    }

    # description is optional in v1 but required in v2 — fall back to asset name
    if ([string]::IsNullOrWhiteSpace($desc)) {
        $desc = $assetName
        Write-Warn "  '$assetName' — description is empty; will use asset name as fallback description."
    }

    $migratable.Add([PSCustomObject]@{
        Name        = $assetName
        Description = $desc
        Path        = $path
        Tags        = $assetTags
    })
}

Write-Ok "Assets to migrate : $($migratable.Count)"
if ($skipped.Count -gt 0) {
    Write-Warn "Assets skipped    : $($skipped.Count) (missing required 'path')"
}

# ── Phase 3: Confirm StorageContainer creation ────────────────────────────────
Write-Step 'Phase 3: Confirm StorageContainer creation'

$scResourceId = "/subscriptions/$SubscriptionId/resourceGroups/$TargetResourceGroup/providers/Microsoft.Discovery/StorageContainers/$StorageContainerName"
$existingSC   = Try-Invoke-ArmGet -ResourceId $scResourceId -ApiVersion $V2_API

Write-Host ''
Write-Host '   Plan:' -ForegroundColor White
Write-Host "     StorageContainer : $scResourceId" -ForegroundColor White
Write-Host "     StorageStore     : AzureStorageBlob → $storageAccountId" -ForegroundColor White
Write-Host "     Location         : $location" -ForegroundColor White
Write-Host "     StorageAssets    : $($migratable.Count) will be created automatically" -ForegroundColor White
if ($existingSC) {
    Write-Host "     Existing state   : $($existingSC.properties.provisioningState)" -ForegroundColor White
}
if ($skipped.Count -gt 0) {
    Write-Host "     Skipped assets   : $($skipped.Count) (missing path)" -ForegroundColor Yellow
}
Write-Host ''
Write-Host "   NOTE: Source DataContainer and DataAssets will NOT be modified or deleted." -ForegroundColor DarkGray

if ($WhatIf) {
    Write-Warn '[WhatIf] Dry-run complete — no resources created.'
    # Still write report if requested
    $report = [PSCustomObject]@{
        Timestamp           = (Get-Date -Format 'o')
        Mode                = 'WhatIf'
        SourceDataContainer = $DataContainerResourceId
        StorageContainer    = $scResourceId
        Location            = $location
        StorageAccountId    = $storageAccountId
        AssetsToMigrate     = @($migratable | Select-Object Name, Path, Description)
        AssetsToSkip        = @($skipped)
    }
    if ($OutputJsonReport) {
        $report | ConvertTo-Json -Depth 20 | Set-Content -Path $OutputJsonReport -Encoding UTF8
        Write-Ok "WhatIf report written to: $OutputJsonReport"
    }
    return
}

if ($existingSC) {
    $existingState = $existingSC.properties.provisioningState

    if ($existingState -ne 'Succeeded') {
        Write-Err "StorageContainer '$StorageContainerName' already exists but is in provisioning state '$existingState'. Fix the existing container or choose a new StorageContainerName, then rerun the script."
    }

    Write-Warn "StorageContainer '$StorageContainerName' already exists and is in Succeeded state."
    Write-Warn 'The script will reuse the existing StorageContainer and create StorageAssets under it.'
    Write-Warn 'If StorageAssets with the same names already exist, they may be overwritten.'

    $confirm = Read-Host '   Proceed with creating StorageAssets in the existing StorageContainer? [Y/N]'
    if ($confirm -notmatch '^[Yy]$') {
        Write-Host '   Aborted by user.' -ForegroundColor Yellow
        return
    }
}
else {
    $confirm = Read-Host '   Proceed with creating StorageContainer? [Y/N]'
    if ($confirm -notmatch '^[Yy]$') {
        Write-Host '   Aborted by user.' -ForegroundColor Yellow
        return
    }
}

# Resolve tags: -Tags parameter wins, then DataContainer tags, then empty
$effectiveTags = if ($Tags) { $Tags } elseif ($sourceTags) { $sourceTags } else { @{} }

# ── Phase 4: Create StorageContainer ─────────────────────────────────────────
if ($existingSC) {
    Write-Step 'Phase 4: Reusing existing StorageContainer'
    $createdSC = $existingSC
    Write-Ok "StorageContainer exists  : $($createdSC.id)"
    Write-Ok "Provisioning state       : $($createdSC.properties.provisioningState)"
}
else {
    Write-Step 'Phase 4: Creating StorageContainer'
    Write-Host "   Linking to existing storage account (no new storage, blobs, or source changes):" -ForegroundColor Gray
    Write-Host "   $storageAccountId" -ForegroundColor Gray

    $scBody = @{
        location   = $location
        tags       = $effectiveTags
        properties = @{
            storageStore = @{
                kind             = 'AzureStorageBlob'
                storageAccountId = $storageAccountId
            }
        }
    }

    try {
        $createdSC = Invoke-ArmPut -ResourceId $scResourceId -ApiVersion $V2_API -Body $scBody
        Write-Ok "StorageContainer created : $($createdSC.id)"
        Write-Ok "Provisioning state       : $($createdSC.properties.provisioningState)"

        if ($createdSC.properties.provisioningState -ne 'Succeeded') {
            Write-Step 'Phase 4a: Waiting for StorageContainer provisioning'
            $createdSC = Wait-ForStorageContainerSucceeded -ResourceId $scResourceId -ApiVersion $V2_API
            Write-Ok "Provisioning state       : $($createdSC.properties.provisioningState)"
        }
    }
    catch {
        Write-Err "Failed to create StorageContainer: $($_.Exception.Message)"
    }
}

# ── Phase 5: Create StorageAssets (automatic, no prompt) ─────────────────────
Write-Step "Phase 5: Creating $($migratable.Count) StorageAsset(s)"
Write-Host "   Each StorageAsset points to the same path as its source DataAsset." -ForegroundColor Gray
Write-Host "   No data is moved — only control-plane metadata is created." -ForegroundColor Gray
Write-Host ''

$createdAssets = [System.Collections.Generic.List[PSCustomObject]]::new()
$failedAssets  = [System.Collections.Generic.List[PSCustomObject]]::new()

foreach ($asset in $migratable) {
    $saResourceId = "$scResourceId/StorageAssets/$($asset.Name)"
    $assetTags    = if ($Tags) { $Tags } elseif ($asset.Tags) { $asset.Tags } else { @{} }

    $saBody = @{
        location   = $location
        tags       = $assetTags
        properties = @{
            description = $asset.Description
            path        = $asset.Path
        }
    }

    Write-Host "   '$($asset.Name)'  path: $($asset.Path)" -ForegroundColor Gray

    try {
        $createdSA = Invoke-ArmPut -ResourceId $saResourceId -ApiVersion $V2_API -Body $saBody
        Write-Ok "  '$($asset.Name)' created (provisioningState: $($createdSA.properties.provisioningState))"
        $createdAssets.Add([PSCustomObject]@{
            Name               = $asset.Name
            ResourceId         = $createdSA.id
            Path               = $asset.Path
            ProvisioningState  = $createdSA.properties.provisioningState
            Status             = 'Created'
        })
    }
    catch {
        $errMsg = $_.Exception.Message
        Write-Warn "  '$($asset.Name)' FAILED: $errMsg"
        $failedAssets.Add([PSCustomObject]@{ Name = $asset.Name; Path = $asset.Path; Error = $errMsg })
    }
}

# ── Phase 6: Summary ──────────────────────────────────────────────────────────
Write-Step 'Phase 6: Summary'
Write-Host ''
Write-Host "   StorageContainer : $scResourceId" -ForegroundColor White
Write-Host "   Assets created   : $($createdAssets.Count)" -ForegroundColor Green
if ($skipped.Count    -gt 0) { Write-Host "   Assets skipped   : $($skipped.Count) (missing path)" -ForegroundColor Yellow }
if ($failedAssets.Count -gt 0) { Write-Host "   Assets failed    : $($failedAssets.Count)" -ForegroundColor Red }

$report = [PSCustomObject]@{
    Timestamp           = (Get-Date -Format 'o')
    Mode                = 'Live'
    SourceDataContainer = $DataContainerResourceId
    StorageContainer    = $scResourceId
    Location            = $location
    StorageAccountId    = $storageAccountId
    AssetsCreated       = @($createdAssets)
    AssetsSkipped       = @($skipped)
    AssetsFailed        = @($failedAssets)
}

if ($OutputJsonReport) {
    $report | ConvertTo-Json -Depth 20 | Set-Content -Path $OutputJsonReport -Encoding UTF8
    Write-Ok "Report written to: $OutputJsonReport"
}

Write-Host ''
Write-Host '   Migration complete.' -ForegroundColor Cyan
