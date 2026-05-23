#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
.SYNOPSIS
    Assigns the complete set of Azure RBAC roles required for a Microsoft Discovery persona
    to one or more users.

.DESCRIPTION
    This cross-platform PowerShell script (Windows, macOS, Linux) automates role assignment
    for the Microsoft Discovery platform. It validates the executor's permissions before
    acting, supports batch assignment of multiple users, handles guest users, and produces
    a clear summary of all actions taken.

    The executor must hold one of the following roles at the target scope:
      - Owner
      - User Access Administrator
      - Role Based Access Control Administrator

    The Microsoft Discovery Platform Administrator (Preview) role alone is NOT sufficient
    because it cannot assign the Azure built-in roles (Storage, Network, Managed Identity,
    Azure AI, etc.) that each persona requires.

.PARAMETER Persona
    Optional. The Microsoft Discovery persona to configure.
    Valid values: "PlatformAdministrator" (or "1"), "Scientist" (or "2")
    If omitted, an interactive menu is displayed to select a persona.

.PARAMETER SubscriptionId
    Required. The Azure subscription ID (GUID) where Microsoft Discovery is deployed.

.PARAMETER UserIds
    Required. One or more user identifiers to assign roles to.
    Accepts UPN email addresses or Object ID GUIDs.
    Formats accepted:
      - Array:              -UserIds "user1@contoso.com","user2@contoso.com"
      - Comma-separated:    -UserIds "user1@contoso.com,user2@contoso.com"
      - Semicolon-separated: -UserIds "user1@contoso.com;user2@contoso.com"

.PARAMETER Scope
    Optional. Scope at which primary and supporting roles are assigned.
    Valid values: "Subscription", "ResourceGroup"
    Default: "ResourceGroup"
    Note: The Reader role is always assigned at Subscription scope regardless of this setting.

.PARAMETER ResourceGroupName
    Conditional. Required when -Scope is "ResourceGroup". The resource group where
    Microsoft Discovery is deployed.

.PARAMETER WorkspaceManagedRGName
    Optional. The name of the managed resource group of the Microsoft Discovery workspace.
    Required for assigning Azure AI Owner (Platform Administrator) and Azure AI User
    (Scientist) at RG scope. If omitted, those roles are skipped (PartialSuccess exit code).

.PARAMETER WorkspaceManagedRGSubscriptionId
    Optional. The subscription ID of the workspace managed resource group, if different
    from -SubscriptionId. Defaults to -SubscriptionId if not specified.

.PARAMETER AllowIncomplete
    Optional. Suppresses the PartialSuccess (exit 2) result when -WorkspaceManagedRGName
    is omitted. Use when the Azure AI Owner/User role will be assigned separately.

.PARAMETER SkipModuleInstall
    Optional. Skip automatic installation of Az.Accounts and Az.Resources modules.
    Use in environments where modules are pre-installed or outbound internet is restricted.

.PARAMETER Force
    Optional. Skip interactive confirmation prompt. Suitable for automation/CI pipelines.

.PARAMETER WhatIf
    Optional. Preview all planned role assignments without executing them.
    All validation runs normally; no changes are made.

.EXAMPLE
    # Assign Platform Administrator roles at Resource Group scope
    ./Set-DiscoveryRoleAssignments.ps1 `
        -Persona PlatformAdministrator `
        -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
        -Scope ResourceGroup `
        -ResourceGroupName "contoso-discovery-rg" `
        -WorkspaceManagedRGName "contoso-discovery-mrg" `
        -UserIds "alice@contoso.com","bob@contoso.com"

.EXAMPLE
    # Assign Scientist roles at subscription scope (dry run)
    ./Set-DiscoveryRoleAssignments.ps1 `
        -Persona Scientist `
        -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
        -Scope Subscription `
        -UserIds "alice@contoso.com;scientist1@contoso.com" `
        -WhatIf

.EXAMPLE
    # Assign roles to a guest user (already invited to tenant) by Object ID
    ./Set-DiscoveryRoleAssignments.ps1 `
        -Persona Scientist `
        -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
        -Scope ResourceGroup `
        -ResourceGroupName "contoso-discovery-rg" `
        -UserIds "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

.EXAMPLE
    # CI pipeline run (non-interactive, pre-installed modules)
    ./Set-DiscoveryRoleAssignments.ps1 `
        -Persona Scientist `
        -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
        -Scope ResourceGroup `
        -ResourceGroupName "contoso-discovery-rg" `
        -UserIds "user1@contoso.com","user2@contoso.com" `
        -SkipModuleInstall `
        -Force `
        -AllowIncomplete

.OUTPUTS
    Exit codes:
      0 - All assignments succeeded (or were already in place)
      2 - Partial success: one or more roles were skipped or failed
      3 - Aborted before any changes (permission failure, bad parameters, no resolvable users)
      4 - Unhandled exception

.NOTES
    Minimum requirements: Az.Accounts >= 3.0.0, Az.Resources >= 7.0.0
    Platform support: Windows (PS 5.1+), macOS (PS 7+), Linux (PS 7+)
    Script version: 1.0.0
    Role definitions sourced from: Microsoft Discovery concept-role-assignments documentation
#>

[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [string]$Persona,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]
    [string]$SubscriptionId,

    [Parameter()]
    [string[]]$UserIds,

    [ValidateSet("Subscription", "ResourceGroup")]
    [string]$Scope = "ResourceGroup",

    [string]$ResourceGroupName,

    [string]$WorkspaceManagedRGName,

    [ValidatePattern('^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?$')]
    [string]$WorkspaceManagedRGSubscriptionId,

    [ValidatePattern('^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?$')]
    [string]$TenantId,

    [switch]$AllowIncomplete,
    [switch]$SkipModuleInstall,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

#region ── Constants ──────────────────────────────────────────────────────────

$SCRIPT_VERSION = "1.0.0"

# Role definition IDs for valid executor roles
$FULL_RIGHTS_ROLE_IDS = @(
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",  # Owner
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",  # User Access Administrator
    "f58310d9-a9f6-439a-9e8d-f62e7b41a168"   # Role Based Access Control Administrator
)

# Microsoft Discovery Platform Administrator — blocked as sole executor role
$DISCOVERY_PLATFORM_ADMIN_ID = "7a2b6e6c-472e-4b39-8878-a26eb63d75c6"

# All role definition IDs (stable built-in IDs — all roles including Bookshelf are present in every tenant)
$ROLE_IDS = @{
    "Microsoft Discovery Platform Administrator (Preview)" = "7a2b6e6c-472e-4b39-8878-a26eb63d75c6"
    "Microsoft Discovery Platform Contributor (Preview)"   = "01288891-85ee-45a7-b367-9db3b752fc65"
    "Managed Identity Contributor"                         = "e40ec5ca-96e0-45a2-b4ff-59039f2c2b59"
    "Managed Identity Operator"                            = "f1a07417-d97a-45cb-824c-7a7467783830"
    "Storage Account Contributor"                          = "17d1049b-9a84-46fb-8f53-869881c3d3ab"
    "Storage Blob Data Contributor"                        = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
    "Network Contributor"                                  = "4d97b98b-1d4f-4787-a291-c67834d212e7"
    "AcrPush"                                              = "8311e382-0749-4cb8-b61a-304f252e45ec"
    "Reader"                                               = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
    "Azure AI Owner"                                       = "c883944f-8b7b-4483-af10-35834be79c4a"
    "Azure AI User"                                        = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
    # Microsoft Discovery Bookshelf Index Data Reader (Preview) — no published stable
    # GUID; resolved at runtime via Get-AzRoleDefinition after authentication.
}

$BOOKSHELF_ROLE_NAME = "Microsoft Discovery Bookshelf Index Data Reader - Preview"
# Populated at runtime after Connect-AzAccount in Step 4.
$script:BookshelfRoleResolutionError = $null

#endregion

#region ── Helper: Output ─────────────────────────────────────────────────────

function Write-Step   { param([string]$Msg) Write-Host "`n▶ $Msg" -ForegroundColor White }
function Write-Info   { param([string]$Msg) Write-Host "  $Msg" -ForegroundColor Cyan }
function Write-Done   { param([string]$Msg) Write-Host "  ✔ $Msg" -ForegroundColor Green }
function Write-Divider { param([string]$C = "White") Write-Host ("═" * 70) -ForegroundColor $C }

function Exit-Fatal {
    param([string]$Message, [int]$Code = 3)
    Write-Host ""
    Write-Host "✖ FATAL: $Message" -ForegroundColor Red
    exit $Code
}

#endregion

#region ── Helper: Scope Comparison ──────────────────────────────────────────

# Returns $true if $ParentScope covers (is the same as or an ancestor of) $ChildScope.
# E.g. /subscriptions/X covers /subscriptions/X/resourceGroups/Y
function Test-ScopeCovers {
    param([string]$ParentScope, [string]$ChildScope)
    if ($ParentScope -eq "/") { return $true }
    $parent = $ParentScope.TrimEnd('/')
    $child  = $ChildScope.TrimEnd('/')
    return ($child -eq $parent) -or $child.StartsWith($parent + '/', [System.StringComparison]::OrdinalIgnoreCase)
}

# Returns $true if any assignment in $AllAssignments grants full role-assignment
# rights that cover $TargetScope (at that scope or a broader ancestor scope).
function Test-HasFullRightsAtScope {
    param(
        [object[]]$AllAssignments,
        [string]$TargetScope
    )
    foreach ($a in $AllAssignments) {
        if ($a.RoleDefinitionId -in $FULL_RIGHTS_ROLE_IDS) {
            if (Test-ScopeCovers -ParentScope $a.Scope -ChildScope $TargetScope) {
                return $true
            }
        }
    }
    return $false
}

#endregion

#region ── Step 1: PowerShell Version Check ───────────────────────────────────

Write-Step "Checking PowerShell version"

$psMajor = $PSVersionTable.PSVersion.Major
$psEditionLocal = if ($PSVersionTable.PSEdition) { $PSVersionTable.PSEdition } else { "Desktop" }

if ($psMajor -lt 7) {
    if ($psEditionLocal -ne "Desktop") {
        # Non-Desktop (Core) edition < 7 means PS 6.x on non-Windows — block
        Exit-Fatal "PowerShell 7 or later is required on macOS and Linux. Install from: https://aka.ms/powershell"
    }
    # Windows PowerShell 5.1 — allow with warning
    Write-Warning "Running on Windows PowerShell $($PSVersionTable.PSVersion). PowerShell 7+ is recommended for consistent behavior across platforms."
} else {
    Write-Done "PowerShell $($PSVersionTable.PSVersion) on $psEditionLocal"
}

#endregion

#region ── Step 2: Module Management ─────────────────────────────────────────

Write-Step "Checking required Az modules"

$requiredModules = @(
    @{ Name = "Az.Accounts";  MinVersion = [version]"3.0.0" }
    @{ Name = "Az.Resources"; MinVersion = [version]"7.0.0" }
)

if (-not $SkipModuleInstall) {
    Write-Info "Ensuring NuGet provider is available..."
    try {
        $null = Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser -ErrorAction SilentlyContinue
        Set-PSRepository -Name PSGallery -InstallationPolicy Trusted -ErrorAction SilentlyContinue
    } catch {
        Write-Warning "Could not pre-configure NuGet/PSGallery: $($_.Exception.Message). Proceeding..."
    }

    foreach ($mod in $requiredModules) {
        $installed = Get-Module -ListAvailable -Name $mod.Name |
            Sort-Object Version -Descending | Select-Object -First 1

        if (-not $installed -or $installed.Version -lt $mod.MinVersion) {
            Write-Info "Installing $($mod.Name) >= $($mod.MinVersion) (CurrentUser scope)..."
            try {
                Install-Module -Name $mod.Name -MinimumVersion $mod.MinVersion `
                    -Scope CurrentUser -Repository PSGallery `
                    -Force -AllowClobber -ErrorAction Stop
                Write-Done "$($mod.Name) installed"
            } catch {
                Exit-Fatal ("Failed to install $($mod.Name): $($_.Exception.Message)`n" +
                    "Network access to powershellgallery.com may be blocked. " +
                    "Install manually or re-run with -SkipModuleInstall.")
            }
        } else {
            Write-Done "$($mod.Name) $($installed.Version) (>= $($mod.MinVersion) required)"
        }
    }
} else {
    Write-Info "-SkipModuleInstall specified — skipping module installation check"
    foreach ($mod in $requiredModules) {
        $installed = Get-Module -ListAvailable -Name $mod.Name |
            Sort-Object Version -Descending | Select-Object -First 1
        if (-not $installed -or $installed.Version -lt $mod.MinVersion) {
            Exit-Fatal "$($mod.Name) >= $($mod.MinVersion) is required but not installed. Remove -SkipModuleInstall to auto-install, or install manually."
        }
        Write-Done "$($mod.Name) $($installed.Version)"
    }
}

try {
    Import-Module Az.Accounts, Az.Resources -ErrorAction Stop
} catch {
    Exit-Fatal "Failed to import required modules: $($_.Exception.Message)"
}

#endregion

#region ── Step 3: Parameter Validation ──────────────────────────────────────

Write-Step "Validating parameters"

# ── Persona selection ──────────────────────────────────────────────────────────
# Accept numeric shortcuts (1/2), full names, or prompt interactively if omitted.
switch (([string]$Persona).Trim()) {
    "1" { $Persona = "PlatformAdministrator" }
    "2" { $Persona = "Scientist" }
}

if ($Persona -notin @("PlatformAdministrator", "Scientist")) {
    Write-Divider
    Write-Host ""
    Write-Host "  Select a persona:" -ForegroundColor White
    Write-Host ""
    Write-Host "    1  Platform Administrator" -ForegroundColor Cyan -NoNewline
    Write-Host "  —  sets up and manages the Discovery platform" -ForegroundColor Gray
    Write-Host "    2  Scientist              " -ForegroundColor Cyan -NoNewline
    Write-Host "  —  performs research using Discovery workflows" -ForegroundColor Gray
    Write-Host ""

    do {
        $choice = (Read-Host "  Enter selection (1 or 2)").Trim()
    } while ($choice -notin @("1", "2"))

    $Persona = if ($choice -eq "1") { "PlatformAdministrator" } else { "Scientist" }
    Write-Host ""
}

Write-Done "Persona: $Persona"
# ── End persona selection ──────────────────────────────────────────────────────

# ── UserIds prompt ─────────────────────────────────────────────────────────────
if (-not $UserIds -or $UserIds.Count -eq 0) {
    Write-Host ""
    Write-Host "  Enter the user ID(s) to assign roles to." -ForegroundColor White
    Write-Host "  Accepted formats: UPN (user@contoso.com) or Object ID (GUID)." -ForegroundColor Gray
    Write-Host "  Separate multiple users with semicolons." -ForegroundColor Gray
    Write-Host ""

    do {
        $rawInput = (Read-Host "  User ID(s)").Trim()
    } while ([string]::IsNullOrWhiteSpace($rawInput))

    $UserIds = @($rawInput)
    Write-Host ""
}
# ── End UserIds prompt ─────────────────────────────────────────────────────────

# ── Scope prompt ──────────────────────────────────────────────────────────────
if (-not $PSBoundParameters.ContainsKey('Scope')) {
    Write-Host ""
    Write-Host "  Select the assignment scope:" -ForegroundColor White
    Write-Host ""
    Write-Host "    1  Subscription   —  assign roles at the subscription level" -ForegroundColor Gray
    Write-Host "    2  ResourceGroup  —  assign roles at a specific resource group" -ForegroundColor Gray
    Write-Host ""

    do {
        $scopeChoice = (Read-Host "  Enter selection (1 or 2)").Trim()
    } while ($scopeChoice -notin @("1", "2"))

    $Scope = if ($scopeChoice -eq "1") { "Subscription" } else { "ResourceGroup" }
    Write-Host ""
    Write-Done "Scope: $Scope"
}
# ── End Scope prompt ──────────────────────────────────────────────────────────

# ── ResourceGroupName prompt ──────────────────────────────────────────────────
if ($Scope -eq "ResourceGroup" -and [string]::IsNullOrWhiteSpace($ResourceGroupName)) {
    Write-Host ""
    Write-Host "  Enter the resource group name where roles will be assigned." -ForegroundColor Cyan
    Write-Host "  (Required because -Scope is 'ResourceGroup'.)" -ForegroundColor DarkGray
    Write-Host ""
    $rgInput = Read-Host "  Resource Group Name"
    if ([string]::IsNullOrWhiteSpace($rgInput)) {
        Exit-Fatal "-ResourceGroupName is required when -Scope is 'ResourceGroup'."
    }
    $ResourceGroupName = $rgInput.Trim()
    Write-Host ""
}
# ── End ResourceGroupName prompt ──────────────────────────────────────────────

# ── WorkspaceManagedRGName prompt ─────────────────────────────────────────────
# The AI role (Azure AI Owner for PlatformAdministrator, Azure AI User for
# Scientist) can be assigned at the subscription level (along with all other
# roles) or scoped to the workspace's managed resource group. When -Scope is
# 'Subscription', we assign it at the subscription scope and skip the MRG
# prompt entirely. When -Scope is 'ResourceGroup', we ask whether to include
# this role and prompt for the MRG name (which only exists after the workspace
# is created).
$aiRoleForPrompts = if ($Persona -eq "PlatformAdministrator") { "Azure AI Owner" } else { "Azure AI User" }
if ($Scope -eq "ResourceGroup" -and
    [string]::IsNullOrWhiteSpace($WorkspaceManagedRGName) -and
    -not $PSBoundParameters.ContainsKey('WorkspaceManagedRGName') -and
    -not $AllowIncomplete) {
    Write-Host ""
    Write-Host "  Assign the $aiRoleForPrompts role on the workspace managed resource group?" -ForegroundColor Cyan
    Write-Host "    Y  Yes — prompt for the managed RG name and include this role" -ForegroundColor White
    Write-Host "    N  No  — skip this role (rerun later with -WorkspaceManagedRGName)" -ForegroundColor White
    Write-Host ""
    $aiRoleAnswer = Read-Host "  Include $aiRoleForPrompts role? (Y/N)"
    if ($aiRoleAnswer -match '^(?i:y|yes)$') {
        Write-Host ""
        Write-Host "  Enter the workspace managed resource group name." -ForegroundColor Cyan
        Write-Host "  (This is the MRG that backs the Discovery workspace.)" -ForegroundColor DarkGray
        Write-Host ""
        $mrgInput = Read-Host "  Workspace Managed RG Name"
        if ([string]::IsNullOrWhiteSpace($mrgInput)) {
            Write-Warning "No managed RG name provided; the $aiRoleForPrompts role will be skipped."
            $AllowIncomplete = $true
        } else {
            $WorkspaceManagedRGName = $mrgInput.Trim()
            Write-Done "Workspace Managed RG: $WorkspaceManagedRGName"
        }
    } else {
        Write-Info "Skipping $aiRoleForPrompts role assignment."
        $AllowIncomplete = $true
    }
    Write-Host ""
}
# ── End WorkspaceManagedRGName prompt ─────────────────────────────────────────

# Default MRG subscription to the primary subscription
if ([string]::IsNullOrWhiteSpace($WorkspaceManagedRGSubscriptionId)) {
    $WorkspaceManagedRGSubscriptionId = $SubscriptionId
}

# Warn if MRG subscription provided without MRG name (probably a mistake)
if (-not [string]::IsNullOrWhiteSpace($WorkspaceManagedRGSubscriptionId) -and
    $WorkspaceManagedRGSubscriptionId -ne $SubscriptionId -and
    [string]::IsNullOrWhiteSpace($WorkspaceManagedRGName)) {
    Write-Warning "-WorkspaceManagedRGSubscriptionId was provided but -WorkspaceManagedRGName is missing. The subscription ID will be ignored."
}

Write-Done "Parameters valid"

#endregion

#region ── Step 4: Authentication ─────────────────────────────────────────────

Write-Step "Authenticating to Azure"

$ctx = Get-AzContext -ErrorAction SilentlyContinue

if ($ctx) {
    $currentTenant = $ctx.Tenant.Id
    $currentAccount = $ctx.Account.Id
    Write-Info "Already signed in as: $currentAccount"
    Write-Info "Current tenant:       $currentTenant"
    Write-Host ""

    # If -TenantId was not supplied as a parameter, ask interactively
    if (-not $TenantId) {
        Write-Host "  Press ENTER to use the current tenant, or enter a different Tenant ID" -ForegroundColor Cyan
        Write-Host "  (needed when the subscription belongs to a different tenant):" -ForegroundColor Cyan
        $inputTenant = (Read-Host "  Tenant ID [$currentTenant]").Trim()
        if ($inputTenant -ne "") {
            $TenantId = $inputTenant
        }
    }
} else {
    Write-Info "No existing Azure context found."

    # If -TenantId was not supplied as a parameter, ask interactively
    if (-not $TenantId) {
        Write-Host "  Enter the Tenant ID to sign in to (press ENTER to let Azure resolve it automatically):" -ForegroundColor Cyan
        $inputTenant = (Read-Host "  Tenant ID").Trim()
        if ($inputTenant -ne "") {
            $TenantId = $inputTenant
        }
    }

    Write-Info "Initiating login..."
    if ($TenantId) {
        Connect-AzAccount -TenantId $TenantId -ErrorAction Stop | Out-Null
    } else {
        Connect-AzAccount -ErrorAction Stop | Out-Null
    }
}

# If the resolved/provided tenant differs from the current context, re-authenticate
if ($TenantId -and $ctx -and ($ctx.Tenant.Id -ne $TenantId)) {
    Write-Info "Switching to tenant '$TenantId'..."
    Connect-AzAccount -TenantId $TenantId -ErrorAction Stop | Out-Null
}

try {
    if ($TenantId) {
        Set-AzContext -SubscriptionId $SubscriptionId -TenantId $TenantId -ErrorAction Stop | Out-Null
    } else {
        Set-AzContext -SubscriptionId $SubscriptionId -ErrorAction Stop | Out-Null
    }
} catch {
    Exit-Fatal "Could not set context to subscription '$SubscriptionId': $($_.Exception.Message)"
}

$ctx = Get-AzContext
$executorAccount = $ctx.Account.Id
Write-Done "Connected as: $executorAccount (Subscription: $SubscriptionId)"

# Resolve executor object ID for permission checks
$executorObjectId = $null
try {
    $executorADObj = if ($executorAccount -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') {
        Get-AzADUser -ObjectId $executorAccount -ErrorAction SilentlyContinue
    } else {
        Get-AzADUser -UserPrincipalName $executorAccount -ErrorAction SilentlyContinue
    }
    if ($executorADObj) {
        $executorObjectId = $executorADObj.Id
        Write-Done "Executor identity resolved (ObjectId: $executorObjectId)"
    } else {
        Write-Warning "Could not resolve executor object ID from '$executorAccount'. Permission pre-check will be skipped."
    }
} catch {
    Write-Warning "Error resolving executor identity: $($_.Exception.Message). Permission pre-check will be skipped."
}

# Resolve Bookshelf Index Data Reader role ID by name (no published stable GUID).
try {
    $bookshelfRoleDef = Get-AzRoleDefinition -Name $BOOKSHELF_ROLE_NAME -ErrorAction Stop
    if ($bookshelfRoleDef -and $bookshelfRoleDef.Id) {
        $ROLE_IDS[$BOOKSHELF_ROLE_NAME] = $bookshelfRoleDef.Id
        Write-Done "Resolved '$BOOKSHELF_ROLE_NAME' (Id: $($bookshelfRoleDef.Id))"
    } else {
        $script:BookshelfRoleResolutionError = "Role '$BOOKSHELF_ROLE_NAME' not found in this tenant."
        Write-Warning $script:BookshelfRoleResolutionError
    }
} catch {
    $script:BookshelfRoleResolutionError = "Could not resolve '$BOOKSHELF_ROLE_NAME': $($_.Exception.Message)"
    Write-Warning $script:BookshelfRoleResolutionError
}

#endregion

#region ── Step 5: Build Assignment Plan ─────────────────────────────────────

Write-Step "Building role assignment plan"

# Compute scope strings
$primaryScope = if ($Scope -eq "Subscription") {
    "/subscriptions/$SubscriptionId"
} else {
    "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName"
}
$subscriptionScope = "/subscriptions/$SubscriptionId"
$workspaceMRGScope = if (-not [string]::IsNullOrWhiteSpace($WorkspaceManagedRGName)) {
    "/subscriptions/$WorkspaceManagedRGSubscriptionId/resourceGroups/$WorkspaceManagedRGName"
} else { $null }

$primaryLabel = if ($Scope -eq "Subscription") { "Sub" } else { "RG" }

$rolePlan = [System.Collections.Generic.List[object]]::new()

function Add-RoleEntry {
    param(
        [string]$RoleId,
        [string]$DisplayName,
        [string]$AssignmentScope,
        [string]$ScopeLabel,
        [string]$Status = "Pending",
        [string]$SkipReason = ""
    )
    $rolePlan.Add([ordered]@{
        RoleId      = $RoleId
        DisplayName = $DisplayName
        Scope       = $AssignmentScope
        ScopeLabel  = $ScopeLabel
        Status      = $Status
        SkipReason  = $SkipReason
    })
}

# Workspace MRG AI role helper (handles missing MRG)
function Add-AIRoleEntry {
    param([string]$RoleId, [string]$DisplayName)
    if ($workspaceMRGScope) {
        Add-RoleEntry $RoleId $DisplayName $workspaceMRGScope "WorkspaceMRG"
    } elseif ($Scope -eq "Subscription") {
        # No MRG provided, but caller chose subscription-level assignment —
        # assign the AI role at subscription scope alongside the other roles.
        Add-RoleEntry $RoleId $DisplayName $subscriptionScope "Sub"
    } else {
        Add-RoleEntry $RoleId $DisplayName "" "WorkspaceMRG" "Skipped" "-WorkspaceManagedRGName not provided; rerun with -WorkspaceManagedRGName to assign this role"
    }
}

# Bookshelf role helper — handles tenants where the role isn't yet available.
function Add-BookshelfRoleEntry {
    param([string]$AssignmentScope, [string]$ScopeLabel)
    if ($ROLE_IDS.ContainsKey($BOOKSHELF_ROLE_NAME) -and -not [string]::IsNullOrWhiteSpace($ROLE_IDS[$BOOKSHELF_ROLE_NAME])) {
        Add-RoleEntry $ROLE_IDS[$BOOKSHELF_ROLE_NAME] $BOOKSHELF_ROLE_NAME $AssignmentScope $ScopeLabel
    } else {
        $reason = if ($script:BookshelfRoleResolutionError) { $script:BookshelfRoleResolutionError } else { "Role definition not found in tenant." }
        Add-RoleEntry "" $BOOKSHELF_ROLE_NAME $AssignmentScope $ScopeLabel "Skipped" $reason
    }
}

switch ($Persona) {
    "PlatformAdministrator" {
        Add-RoleEntry $ROLE_IDS["Microsoft Discovery Platform Administrator (Preview)"] `
            "Microsoft Discovery Platform Administrator (Preview)" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Managed Identity Contributor"] `
            "Managed Identity Contributor" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Managed Identity Operator"] `
            "Managed Identity Operator" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Storage Account Contributor"] `
            "Storage Account Contributor" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Storage Blob Data Contributor"] `
            "Storage Blob Data Contributor" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Network Contributor"] `
            "Network Contributor" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["AcrPush"] `
            "AcrPush" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Reader"] `
            "Reader" $subscriptionScope "Sub"
        Add-AIRoleEntry $ROLE_IDS["Azure AI Owner"] "Azure AI Owner"

        Add-BookshelfRoleEntry $primaryScope $primaryLabel
    }
    "Scientist" {
        Add-RoleEntry $ROLE_IDS["Microsoft Discovery Platform Contributor (Preview)"] `
            "Microsoft Discovery Platform Contributor (Preview)" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Storage Account Contributor"] `
            "Storage Account Contributor" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Storage Blob Data Contributor"] `
            "Storage Blob Data Contributor" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["AcrPush"] `
            "AcrPush" $primaryScope $primaryLabel
        Add-RoleEntry $ROLE_IDS["Reader"] `
            "Reader" $subscriptionScope "Sub"
        Add-AIRoleEntry $ROLE_IDS["Azure AI User"] "Azure AI User"

        Add-BookshelfRoleEntry $primaryScope $primaryLabel
    }
}

$totalRoles = $rolePlan.Count
$pendingCount = ($rolePlan | Where-Object { $_.Status -eq "Pending" }).Count
Write-Done "Plan: $totalRoles role(s) ($pendingCount to assign, $($totalRoles - $pendingCount) pre-skipped) for $Persona"

#endregion

#region ── Step 6: Permission Pre-Check ──────────────────────────────────────

Write-Step "Checking executor permissions"

if ($executorObjectId) {
    # Retrieve ALL role assignments for the executor (including group-inherited) in one call.
    # Do NOT pass -Scope here — incompatible with -ExpandPrincipalGroups. Filter client-side.
    Write-Info "Fetching executor role assignments (including group-inherited)..."
    try {
        $allExecutorAssignments = @(Get-AzRoleAssignment -ObjectId $executorObjectId -ExpandPrincipalGroups -ErrorAction Stop)
    } catch {
        $allExecutorAssignments = @()
        Write-Warning "Could not retrieve executor role assignments: $($_.Exception.Message). Proceeding without pre-check."
    }

    if ($allExecutorAssignments.Count -ge 0) {
        # ── Primary scope check (abort if lacking) ────────────────────────
        $hasFullRightsAtPrimary = Test-HasFullRightsAtScope -AllAssignments $allExecutorAssignments -TargetScope $primaryScope
        $hasDiscoveryAdminRole  = $allExecutorAssignments | Where-Object { $_.RoleDefinitionId -eq $DISCOVERY_PLATFORM_ADMIN_ID }

        if (-not $hasFullRightsAtPrimary) {
            if ($hasDiscoveryAdminRole) {
                Exit-Fatal (
                    "Executor holds only the Microsoft Discovery Platform Administrator (Preview) role, " +
                    "which cannot assign the Azure built-in roles required for a complete persona setup.`n`n" +
                    "To run this script, obtain one of the following at scope '$primaryScope':`n" +
                    "  - Owner                              (8e3af657-a8ff-443c-a75c-2fe8c4bcb635)`n" +
                    "  - User Access Administrator          (18d7d88d-d35e-4fb5-a5c3-7773c20a72d9)`n" +
                    "  - Role Based Access Control Admin    (f58310d9-a9f6-439a-9e8d-f62e7b41a168)"
                )
            } else {
                Exit-Fatal (
                    "Executor '$executorAccount' has no role-assignment permissions at scope '$primaryScope'.`n" +
                    "Assign Owner, User Access Administrator, or Role Based Access Control Administrator " +
                    "at that scope and rerun."
                )
            }
        }
        Write-Done "Full assignment rights confirmed at primary scope"

        # ── Subscription scope check (warn only — Reader role) ────────────
        $hasFullRightsAtSub = Test-HasFullRightsAtScope -AllAssignments $allExecutorAssignments -TargetScope $subscriptionScope
        if (-not $hasFullRightsAtSub -and $Scope -eq "ResourceGroup") {
            Write-Warning (
                "Executor lacks full rights at subscription scope '$subscriptionScope'. " +
                "The Reader role (which must be assigned at subscription scope) will be skipped."
            )
            foreach ($entry in $rolePlan) {
                if ($entry.RoleId -eq $ROLE_IDS["Reader"] -and $entry.Status -eq "Pending") {
                    $entry.Status     = "Skipped"
                    $entry.SkipReason = "Executor lacks role-assignment rights at subscription scope"
                }
            }
        } elseif ($hasFullRightsAtSub) {
            Write-Done "Full assignment rights confirmed at subscription scope"
        }
        # If -Scope Subscription, primary and subscription are the same — already covered above.

        # ── Workspace MRG scope check (warn only — AI role) ───────────────
        if ($workspaceMRGScope) {
            $mrgAssignments = $allExecutorAssignments

            # If MRG is in a different subscription, fetch assignments there separately
            if ($WorkspaceManagedRGSubscriptionId -ne $SubscriptionId) {
                Write-Info "Workspace MRG is in a different subscription ($WorkspaceManagedRGSubscriptionId) — checking permissions there..."
                try {
                    Set-AzContext -SubscriptionId $WorkspaceManagedRGSubscriptionId -ErrorAction Stop | Out-Null
                    $mrgAssignments = @(Get-AzRoleAssignment -ObjectId $executorObjectId -ExpandPrincipalGroups -ErrorAction Stop)
                    Set-AzContext -SubscriptionId $SubscriptionId -ErrorAction Stop | Out-Null
                } catch {
                    Write-Warning "Could not check permissions in MRG subscription: $($_.Exception.Message). AI role pre-check skipped."
                    $mrgAssignments = @()
                }
            }

            $hasFullRightsAtMRG = Test-HasFullRightsAtScope -AllAssignments $mrgAssignments -TargetScope $workspaceMRGScope
            if (-not $hasFullRightsAtMRG) {
                Write-Warning (
                    "Executor lacks full rights at workspace MRG scope '$workspaceMRGScope'. " +
                    "The $aiRoleForPrompts role will be skipped."
                )
                foreach ($entry in $rolePlan) {
                    if ($entry.ScopeLabel -eq "WorkspaceMRG" -and $entry.Status -eq "Pending") {
                        $entry.Status     = "Skipped"
                        $entry.SkipReason = "Executor lacks role-assignment rights at workspace MRG scope"
                    }
                }
            } else {
                Write-Done "Full assignment rights confirmed at workspace MRG scope"
            }
        }
    }
} else {
    Write-Warning "Executor object ID not available — skipping permission pre-check. Assignment may fail at runtime."
}

#endregion

#region ── Step 7: User Resolution ───────────────────────────────────────────

Write-Step "Resolving user identities"

# Normalize input: split on semicolons, trim whitespace, deduplicate, drop empty segments
$normalizedIds = @($UserIds |
    ForEach-Object { $_ -split "[;,]" } |
    ForEach-Object { $_.Trim() } |
    Where-Object   { $_ -ne "" } |
    Sort-Object -Unique)

if ($normalizedIds.Count -eq 0) {
    Exit-Fatal "No user IDs provided. Enter at least one UPN or Object ID."
}

$resolvedUsers = [System.Collections.Generic.List[hashtable]]::new()

foreach ($entry in $normalizedIds) {

    $adUser = $null

    # ── GUID → lookup by Object ID ────────────────────────────────────────
    if ($entry -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') {
        try {
            $adUser = Get-AzADUser -ObjectId $entry -ErrorAction Stop
            if (-not $adUser) {
                Write-Error "Object ID '$entry' not found in the directory. Skipping."
                continue
            }
        } catch {
            Write-Error "Failed to look up Object ID '$entry': $($_.Exception.Message). Skipping."
            continue
        }

    # ── UPN (contains @) ─────────────────────────────────────────────────
    } elseif ($entry -match '@') {
        # OData-escape single quotes (e.g. O'Brien@contoso.com → O''Brien@contoso.com)
        $escapedEntry = $entry -replace "'", "''"

        # Try UPN lookup first
        try {
            $adUser = Get-AzADUser -UserPrincipalName $entry -ErrorAction Stop
        } catch {
            $adUser = $null
        }

        # Fallback: mail attribute filter (handles external/guest email addresses)
        if (-not $adUser) {
            try {
                $mailMatches = @(Get-AzADUser -Filter "mail eq '$escapedEntry'" -ErrorAction Stop)
                switch ($mailMatches.Count) {
                    0 {
                        Write-Error (
                            "User '$entry' was not found in the directory. " +
                            "If this is a guest user, ensure they have accepted a B2B invitation " +
                            "before running this script. Skipping."
                        )
                        continue
                    }
                    1 { $adUser = $mailMatches[0] }
                    default {
                        Write-Error (
                            "Ambiguous: '$entry' matches $($mailMatches.Count) directory users. " +
                            "Provide the Object ID (GUID) to uniquely identify the user. Skipping."
                        )
                        continue
                    }
                }
            } catch {
                Write-Error "Failed to look up '$entry': $($_.Exception.Message). Skipping."
                continue
            }
        }

    # ── Unrecognised format ───────────────────────────────────────────────
    } else {
        Write-Error "Invalid format: '$entry'. Provide a UPN (user@domain.com) or Object ID (GUID). Skipping."
        continue
    }

    # Confirm user was found
    if (-not $adUser) {
        Write-Error "Could not resolve '$entry'. Skipping."
        continue
    }

    $isGuest = ($adUser.UserType -eq "Guest") -or ($adUser.UserPrincipalName -like "*#EXT#*")
    $guestTag = if ($isGuest) { " [Guest]" } else { "" }
    Write-Done "Resolved: $($adUser.UserPrincipalName)$guestTag (ObjectId: $($adUser.Id))"

    $resolvedUsers.Add(@{
        ObjectId = $adUser.Id
        UPN      = $adUser.UserPrincipalName
        Display  = $adUser.DisplayName
        IsGuest  = $isGuest
    })
}

if ($resolvedUsers.Count -eq 0) {
    Exit-Fatal "No users could be resolved. No changes were made."
}

Write-Info "$($resolvedUsers.Count) user(s) ready for role assignment"

#endregion

#region ── Step 8: Confirmation ──────────────────────────────────────────────

$pendingEntries = @($rolePlan | Where-Object { $_.Status -eq "Pending" })
$skippedEntries = @($rolePlan | Where-Object { $_.Status -eq "Skipped" })

if ($WhatIfPreference) {
    Write-Host ""
    Write-Divider "Cyan"
    Write-Host "  [DRY RUN — no changes will be made]" -ForegroundColor Cyan
    Write-Divider "Cyan"
}

if (-not $Force -and -not $WhatIfPreference) {
    Write-Host ""
    Write-Divider "Yellow"
    Write-Host "  PLANNED ROLE ASSIGNMENTS" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Persona : $Persona" -ForegroundColor Yellow
    $scopeDesc = if ($Scope -eq "ResourceGroup") { "ResourceGroup ($ResourceGroupName)" } else { "Subscription ($SubscriptionId)" }
    Write-Host "  Scope   : $scopeDesc" -ForegroundColor Yellow
    $userList = ($resolvedUsers | ForEach-Object { $_.UPN }) -join ', '
    Write-Host "  Users   : $userList" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Roles to assign ($($pendingEntries.Count)):" -ForegroundColor White
    foreach ($r in $pendingEntries) {
        Write-Host "    + $($r.DisplayName)  [$($r.ScopeLabel)]" -ForegroundColor Green
    }
    if ($skippedEntries.Count -gt 0) {
        Write-Host ""
        Write-Host "  Roles to skip ($($skippedEntries.Count)):" -ForegroundColor DarkYellow
        foreach ($r in $skippedEntries) {
            Write-Host "    - $($r.DisplayName)  [$($r.SkipReason)]" -ForegroundColor DarkYellow
        }
    }
    Write-Divider "Yellow"
    Write-Host ""

    $confirm = Read-Host "Assign $($pendingEntries.Count) role(s) to $($resolvedUsers.Count) user(s)? [Y/N]"
    if ($confirm -notmatch '^[Yy]$') {
        Write-Host "Aborted by user. No changes made." -ForegroundColor Yellow
        exit 0
    }
}

#endregion

#region ── Step 9: Role Assignment Loop ──────────────────────────────────────

Write-Step "$(if ($WhatIfPreference) { "Evaluating" } else { "Assigning" }) roles"

$results = [System.Collections.Generic.List[psobject]]::new()
$mrgSubDiffers = ($workspaceMRGScope -and $WorkspaceManagedRGSubscriptionId -ne $SubscriptionId)

foreach ($user in $resolvedUsers) {
    Write-Info "Processing user: $($user.UPN)$(if ($user.IsGuest) { ' [Guest]' })"

    foreach ($entry in $rolePlan) {

        $resultRow = [PSCustomObject]@{
            User       = $user.UPN
            Role       = $entry.DisplayName
            ScopeLabel = $entry.ScopeLabel
            FullScope  = $entry.Scope
            Status     = ""
            Reason     = ""
        }

        # ── Pre-skipped entries ────────────────────────────────────────────
        if ($entry.Status -eq "Skipped") {
            $resultRow.Status = if ($WhatIfPreference) { "WouldSkip" } else { "Skipped" }
            $resultRow.Reason = $entry.SkipReason
            $results.Add($resultRow)
            continue
        }

        # ── Switch context to MRG subscription if needed ──────────────────
        if ($mrgSubDiffers -and $entry.ScopeLabel -eq "WorkspaceMRG") {
            try {
                Set-AzContext -SubscriptionId $WorkspaceManagedRGSubscriptionId -ErrorAction Stop | Out-Null
            } catch {
                $resultRow.Status = "Failed"
                $resultRow.Reason = "Failed to switch to MRG subscription '$WorkspaceManagedRGSubscriptionId': $($_.Exception.Message)"
                $results.Add($resultRow)
                Write-Error $resultRow.Reason
                continue
            }
        }

        # ── Idempotency check ─────────────────────────────────────────────
        # Use -AtScope to check only direct assignments at the target scope,
        # not inherited ones from parent management groups.
        $existing = $null
        try {
            $existing = Get-AzRoleAssignment `
                -ObjectId         $user.ObjectId `
                -RoleDefinitionId $entry.RoleId `
                -Scope            $entry.Scope `
                -AtScope `
                -ErrorAction Stop
        } catch {
            # Non-fatal: treat as not yet assigned
            $existing = $null
        }

        if ($existing) {
            $resultRow.Status = "AlreadyAssigned"
        } elseif ($WhatIfPreference) {
            $resultRow.Status = "WouldAssign"
        } else {
            try {
                New-AzRoleAssignment `
                    -ObjectId         $user.ObjectId `
                    -RoleDefinitionId $entry.RoleId `
                    -Scope            $entry.Scope `
                    -ObjectType       "User" `
                    -ErrorAction Stop | Out-Null
                $resultRow.Status = "Assigned"
            } catch {
                $resultRow.Status = "Failed"
                $resultRow.Reason = $_.Exception.Message
                Write-Error "  ✖ '$($entry.DisplayName)' → '$($user.UPN)': $($_.Exception.Message)"
            }
        }

        $results.Add($resultRow)

        # ── Restore primary subscription context after MRG assignment ─────
        if ($mrgSubDiffers -and $entry.ScopeLabel -eq "WorkspaceMRG") {
            try {
                Set-AzContext -SubscriptionId $SubscriptionId -ErrorAction Stop | Out-Null
            } catch {
                Write-Warning "Failed to restore primary subscription context: $($_.Exception.Message)"
            }
        }
    }
}

#endregion

#region ── Step 10: Summary Report ───────────────────────────────────────────

Write-Host ""
Write-Divider "White"
Write-Host "  MICROSOFT DISCOVERY ROLE ASSIGNMENT SUMMARY" -ForegroundColor White
Write-Host "  Running as  : $executorAccount" -ForegroundColor White
Write-Host "  Persona     : $Persona" -ForegroundColor White
$scopeDisplay = if ($Scope -eq "ResourceGroup") { "ResourceGroup ($ResourceGroupName)" } else { "Subscription ($SubscriptionId)" }
Write-Host "  Scope       : $scopeDisplay" -ForegroundColor White
Write-Host "  WhatIf      : $($WhatIfPreference -eq $true)" -ForegroundColor White
Write-Host "  Script ver  : $SCRIPT_VERSION" -ForegroundColor White
Write-Divider "White"
Write-Host ""

# Detailed results table
# Build a short, stable display name per user so the Role column has room to render in full.
$userDisplayMap = @{}
$idx = 0
foreach ($u in $resolvedUsers) {
    $idx++
    $short = if ($u.UPN -like "*#EXT#*") {
        # Guest UPN: collapse "alias_domain.com#EXT#@tenant.onmicrosoft.com" → "alias@domain.com [Guest]"
        $localPart = ($u.UPN -split '#EXT#')[0]
        $lastUnderscore = $localPart.LastIndexOf('_')
        if ($lastUnderscore -gt 0) {
            "{0}@{1} [Guest]" -f $localPart.Substring(0, $lastUnderscore), $localPart.Substring($lastUnderscore + 1)
        } else { "$localPart [Guest]" }
    } else { $u.UPN }
    $userDisplayMap[$u.UPN] = "U$idx`: $short"
}

# Segregate results into three sections: Assigned, Failed, Skipped.
$assignedStatuses = @("Assigned", "AlreadyAssigned", "WouldAssign")
$failedStatuses   = @("Failed")
$skippedStatuses  = @("Skipped", "WouldSkip")

$assignedRows = @($results | Where-Object { $_.Status -in $assignedStatuses })
$failedRows   = @($results | Where-Object { $_.Status -in $failedStatuses })
$skippedRows  = @($results | Where-Object { $_.Status -in $skippedStatuses })

function Format-ResultSection {
    param(
        [string]$Title,
        [object[]]$Rows,
        [string]$Color,
        [switch]$IncludeReason
    )
    Write-Host ""
    Write-Host ("  {0} ({1})" -f $Title, $Rows.Count) -ForegroundColor $Color
    Write-Host ("  " + ("─" * 68)) -ForegroundColor $Color
    if ($Rows.Count -eq 0) {
        Write-Host "    (none)" -ForegroundColor DarkGray
        return
    }
    $cols = @(
        @{ N = "User";   E = { $userDisplayMap[$_.User] } },
        @{ N = "Role";   E = { $_.Role } },
        @{ N = "Scope";  E = { $_.ScopeLabel } },
        @{ N = "Status"; E = { $_.Status } }
    )
    if ($IncludeReason) {
        $cols += @{ N = "Reason/Error"; E = { $_.Reason } }
    }
    $Rows | Select-Object $cols | Format-Table -AutoSize -Wrap |
        Out-String -Width 4096 | Write-Host
}

Format-ResultSection -Title "ASSIGNED ROLES"           -Rows $assignedRows -Color "Green"
Format-ResultSection -Title "ROLES THAT COULD NOT BE ASSIGNED (FAILED)" -Rows $failedRows -Color "Red"   -IncludeReason
Format-ResultSection -Title "SKIPPED ROLES"            -Rows $skippedRows -Color "Yellow" -IncludeReason

# User legend (short alias → full UPN) for readability.
if ($userDisplayMap.Count -gt 0) {
    Write-Host "  User legend:" -ForegroundColor DarkGray
    foreach ($u in $resolvedUsers) {
        Write-Host ("    {0}  →  {1}" -f $userDisplayMap[$u.UPN], $u.UPN) -ForegroundColor DarkGray
    }
    Write-Host ""
}

# Per-user result summary
Write-Host "PER-USER RESULT" -ForegroundColor White
foreach ($user in $resolvedUsers) {
    $userRows   = @($results | Where-Object { $_.User -eq $user.UPN })
    $failedRows = @($userRows | Where-Object { $_.Status -eq "Failed" })
    $skippedRows= @($userRows | Where-Object { $_.Status -in @("Skipped", "WouldSkip") })

    $userResult = if     ($failedRows.Count -gt 0 -and $skippedRows.Count -gt 0) { "PartialSuccess ($($failedRows.Count) Failed, $($skippedRows.Count) Skipped)" }
                  elseif ($failedRows.Count -gt 0)                                { "PartialSuccess ($($failedRows.Count) Failed)" }
                  elseif ($skippedRows.Count -gt 0)                               { "PartialSuccess ($($skippedRows.Count) Skipped)" }
                  else                                                             { "Success" }

    $color = if ($userResult -like "PartialSuccess*") { "Yellow" } else { "Green" }
    Write-Host ("  {0,-50} → {1}" -f $user.UPN, $userResult) -ForegroundColor $color
}
Write-Host ""

# Overall exit code determination
$anyFailed  = @($results | Where-Object { $_.Status -eq "Failed" })
$anySkipped = @($results | Where-Object { $_.Status -in @("Skipped", "WouldSkip") })

$exitCode = if ($anyFailed.Count -eq 0 -and $anySkipped.Count -eq 0) {
    0
} elseif ($anyFailed.Count -eq 0 -and $anySkipped.Count -gt 0 -and $AllowIncomplete) {
    0   # Caller suppressed partial-success exit
} else {
    2
}

$overallLabel = if ($anyFailed.Count -eq 0 -and $anySkipped.Count -eq 0) { "Success" }
               elseif ($anyFailed.Count -gt 0 -and $anySkipped.Count -gt 0) { "PartialSuccess (Failed + Skipped)" }
               elseif ($anyFailed.Count -gt 0)  { "PartialSuccess ($($anyFailed.Count) Failed)" }
               else                              { "PartialSuccess ($($anySkipped.Count) Skipped)" }

if ($WhatIfPreference) { $overallLabel = "[DRY RUN] $overallLabel" }

$overallColor = if ($exitCode -eq 0) { "Green" } else { "Yellow" }
Write-Host "Overall result : $overallLabel  (exit code $exitCode)" -ForegroundColor $overallColor

# Actionable hints
$aiRoleSkipped = @($anySkipped | Where-Object { $_.Role -like "*AI Owner*" -or $_.Role -like "*AI User*" })
if ($aiRoleSkipped.Count -gt 0) {
    $aiRoleName = $aiRoleSkipped[0].Role
    Write-Host ""
    Write-Host "  ⚠  ACTION REQUIRED: '$aiRoleName' was not assigned." -ForegroundColor Yellow
    Write-Host "     This role is scoped to the Discovery workspace's managed resource group (MRG)," -ForegroundColor Yellow
    Write-Host "     which only exists after the workspace is created." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "     → Please come back AFTER the workspace is created, then rerun this script with" -ForegroundColor Cyan
    Write-Host "       the workspace managed RG name to assign the remaining permission(s):" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "         ./Set-DiscoveryRoleAssignments.ps1 ``" -ForegroundColor White
    Write-Host "             -Persona $Persona ``" -ForegroundColor White
    Write-Host "             -SubscriptionId $SubscriptionId ``" -ForegroundColor White
    $scopeArgs = if ($Scope -eq "ResourceGroup") { "-Scope ResourceGroup -ResourceGroupName $ResourceGroupName ``" } else { "-Scope Subscription ``" }
    Write-Host "             $scopeArgs" -ForegroundColor White
    Write-Host "             -UserIds `"$(($resolvedUsers | ForEach-Object { $_.UPN }) -join ';')`" ``" -ForegroundColor White
    Write-Host "             -WorkspaceManagedRGName <workspace-managed-rg-name>" -ForegroundColor White
}
if ($anySkipped | Where-Object { $_.Role -eq "Reader" }) {
    Write-Host ""
    Write-Host "  → Reader role was skipped (executor lacks rights at subscription scope)." -ForegroundColor Cyan
    Write-Host "    Rerun as Owner / User Access Administrator / RBAC Admin at subscription scope." -ForegroundColor Cyan
}
if ($anyFailed.Count -gt 0) {
    Write-Host ""
    Write-Host "  → $($anyFailed.Count) assignment(s) failed. Review the Reason/Error column above for details." -ForegroundColor Red
}

Write-Divider "White"
Write-Host ""

exit $exitCode

#endregion
