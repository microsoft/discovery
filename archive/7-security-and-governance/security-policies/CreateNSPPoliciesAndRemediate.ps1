<#
.SYNOPSIS
Creates a UAMI, grants it Contributor at subscription scope, creates a policy definition from a JSON file,
and assigns the policy at the subscription scope using that UAMI.

.REQUIREMENTS
Az.Accounts, Az.Resources, Az.ManagedServiceIdentity modules.

.EXAMPLE
.\CreateNSPPoliciesAndRemediate.ps1 -SubscriptionId "00000000-0000-0000-0000-000000000000"
#>

param(
  [Parameter(Mandatory = $true)]
  [string]$SubscriptionId,
  [string[]] $ResourceGroups
)


# Define required modules
$requiredModules = @("Az.Accounts", "Az.Storage", "Az.Resources", "Az.Network", "Az.Sql", "Az.CosmosDB", "Az.KeyVault", "Az.ManagedServiceIdentity")

# Install and import modules if not already installed
foreach ($module in $requiredModules) {
    if (-not (Get-Module -ListAvailable -Name $module)) {
        Write-Host "Installing module: $module"
        Install-Module -Name $module -Scope CurrentUser -Force
    }
    Import-Module $module -Force
}

Write-Host ">>> Setting context to subscription: $SubscriptionId"
Connect-AzAccount -Subscription $SubscriptionId
Set-AzContext -Subscription $SubscriptionId | Out-Null

# ================================
# 1. Define constants
# ================================
$nspRg = "discovery-nsp-rg"                 # fixed name for NSP RG
$nspName = "discovery-nsp"                # NSP resource name
$profileName = "discovery-nsp-profile"   # NSP profile name
$location = "eastus2"              # change as per your needs
$UamiName = "nsp-MI"     # UAMI name

# Policy parameters (adjust values as needed)
$policyParams = @{
  effect                 = "DeployIfNotExists" # or "AuditIfNotExists"/"Audit"/"Disabled"
  skipTagName            = "SkipAssociateKeyVaultToNsp"
  nspName                = "discovery-nsp"
  nspProfile             = "discovery-nsp-profile"
  nspResourceGroupName   = "discovery-nsp-rg"
  centralizedNspProfileId= "/subscriptions/$subscriptionId/resourcegroups/discovery-nsp-rg/providers/microsoft.network/networksecurityperimeters/discovery-nsp/profiles/discovery-nsp-profile"                # leave empty if NSP is in same subscription
  accessMode             = "Learning"          # "Learning" or "Enforced"
}

# ================================
# 2. Ensure NSP resource group exists
# ================================
if (-not (Get-AzResourceGroup -Name $nspRg -ErrorAction SilentlyContinue)) {
    Write-Host "Creating NSP resource group: $nspRg" -ForegroundColor Cyan
    New-AzResourceGroup -Name $nspRg -Location $location
} else {
    Write-Host "NSP resource group already exists: $nspRg" -ForegroundColor Green
}

# ================================
# 3. Ensure NSP + profile + inbound rule exists
# ================================
$nsp = Get-AzNetworkSecurityPerimeter -ResourceGroupName $nspRg -Name $nspName -ErrorAction SilentlyContinue

if (-not $nsp) {
    Write-Host "Creating NSP: $nspName" -ForegroundColor Cyan
    $nsp = New-AzNetworkSecurityPerimeter -Name $nspName -ResourceGroupName $nspRg -Location $location
}

# Ensure NSP Profile exists
$profile = Get-AzNetworkSecurityPerimeter -ResourceGroupName $nspRg -Name $nspName | `
           Get-AzNetworkSecurityPerimeterProfile -Name $profileName -ErrorAction SilentlyContinue

if (-not $profile) {
    Write-Host "Creating NSP Profile: $profileName" -ForegroundColor Cyan
    $profile = New-AzNetworkSecurityPerimeterProfile -Name $profileName -NetworkSecurityPerimeterName $nspName -ResourceGroupName $nspRg
}

# ---------------------------
# 2) Create (or get) the User Assigned Managed Identity
# ---------------------------
$uami = Get-AzUserAssignedIdentity -ResourceGroupName $nspRg -Name $UamiName -ErrorAction SilentlyContinue
if (-not $uami) {
  Write-Host ">>> Creating UAMI '$UamiName' in RG '$nspRg' ($Location)"
  $uami = New-AzUserAssignedIdentity -ResourceGroupName $nspRg -Name $UamiName -Location $Location
} else {
  Write-Host ">>> Using existing UAMI: $($uami.Id)"
}

# ---------------------------
# 3) Assign Contributor RBAC to the UAMI at subscription scope
# ---------------------------
$scope = "/subscriptions/$SubscriptionId"
$existingRole = Get-AzRoleAssignment -ObjectId $uami.PrincipalId -Scope $scope -ErrorAction SilentlyContinue |
                Where-Object { $_.RoleDefinitionName -eq 'Contributor' }
if (-not $existingRole) {
  Write-Host ">>> Granting 'Contributor' to UAMI at scope $scope"
  New-AzRoleAssignment -ObjectId $uami.PrincipalId -RoleDefinitionName 'Contributor' -Scope $scope | Out-Null
} else {
  Write-Host ">>> UAMI already has 'Contributor' at scope $scope"
}

# ---------------------------
# 4) Create (or update) the Policy Definition for KV to NSP from the JSON file
#     - Supports policy rule, policy properties, or full policy object in file
# ---------------------------

$policyNameKV = "associate-kv-to-nsp"
$assignmentNameKV = "associate-kv-to-nsp-assignment"
$PolicyFilePathKV = ".\policy-definitions\associate-kv-to-nsp.policy.json"
Write-Host ">>> Creating/updating Policy Definition '$policyNameKV' from file: $PolicyFilePathKV"

$policyDefKV = New-AzPolicyDefinition -Name $policyNameKV -SubscriptionId $SubscriptionId -Policy $PolicyFilePathKV

# ---------------------------
# 5) Assign the KV Policy at subscription scope, using the UAMI
#     - For DeployIfNotExists/Modify effects, an identity AND a Location are required on the assignment.
# ---------------------------
Write-Host ">>> Creating/updating Policy Assignment '$assignmentNameKV' at scope $scope using UAMI"

$assignment = New-AzPolicyAssignment `
-Name                  $assignmentNameKV `
-Scope                 $scope `
-PolicyDefinition      $policyDefKV `
-PolicyParameterObject $policyParams `
-IdentityType          UserAssigned `
-IdentityId            $uami.Id `
-Location              $Location

# ---------------------------
# 6) Create (or update) the Policy Definition for Sql to NSP from the JSON file
#     - Supports policy rule, policy properties, or full policy object in file
# ---------------------------

$policyNameSql = "associate-sql-to-nsp"
$assignmentNameSql = "associate-sql-to-nsp-assignment"
$PolicyFilePathSql = ".\policy-definitions\associate-sql-to-nsp.policy.json"
Write-Host ">>> Creating/updating Policy Definition '$policyNameSql' from file: $PolicyFilePathSql"

$policyDefSql = New-AzPolicyDefinition -Name $policyNameSql -SubscriptionId $SubscriptionId -Policy $PolicyFilePathSql

# ---------------------------
# 7) Assign the Sql Policy at subscription scope, using the UAMI
#     - For DeployIfNotExists/Modify effects, an identity AND a Location are required on the assignment.
# ---------------------------
Write-Host ">>> Creating/updating Policy Assignment '$assignmentNameSql' at scope $scope using UAMI"

$assignment = New-AzPolicyAssignment `
-Name                  $assignmentNameSql `
-Scope                 $scope `
-PolicyDefinition      $policyDefSql `
-PolicyParameterObject $policyParams `
-IdentityType          UserAssigned `
-IdentityId            $uami.Id `
-Location              $Location

# ---------------------------
# 8) Create (or update) the Policy Definition for Storage to NSP from the JSON file
#     - Supports policy rule, policy properties, or full policy object in file
# ---------------------------

$policyNameStorage = "associate-storage-to-nsp"
$assignmentNameStorage = "associate-storage-to-nsp-assignment"
$PolicyFilePathStorage = ".\policy-definitions\associate-storage-to-nsp.policy.json"
Write-Host ">>> Creating/updating Policy Definition '$policyNameStorage' from file: $PolicyFilePathStorage"

$policyDefStorage = New-AzPolicyDefinition -Name $policyNameStorage -SubscriptionId $SubscriptionId -Policy $PolicyFilePathStorage

# ---------------------------
# 9) Assign the Storage Policy at subscription scope, using the UAMI
#     - For DeployIfNotExists/Modify effects, an identity AND a Location are required on the assignment.
# ---------------------------
Write-Host ">>> Creating/updating Policy Assignment '$assignmentNameStorage' at scope $scope using UAMI"

$assignment = New-AzPolicyAssignment `
-Name                  $assignmentNameStorage `
-Scope                 $scope `
-PolicyDefinition      $policyDefStorage `
-PolicyParameterObject $policyParams `
-IdentityType          UserAssigned `
-IdentityId            $uami.Id `
-Location              $Location

# ---------------------------
# 10) Create (or update) the Policy Definition for Cosmos to NSP from the JSON file
#     - Supports policy rule, policy properties, or full policy object in file
# ---------------------------

$policyNameCosmos = "associate-cosmos-to-nsp"
$assignmentNameCosmos = "associate-cosmos-to-nsp-assignment"
$PolicyFilePathCosmos = ".\policy-definitions\associate-cosmos-to-nsp.policy.json"
Write-Host ">>> Creating/updating Policy Definition '$policyNameCosmos' from file: $PolicyFilePathCosmos"

$policyDefCosmos = New-AzPolicyDefinition -Name $policyNameCosmos -SubscriptionId $SubscriptionId -Policy $PolicyFilePathCosmos

# ---------------------------
# 11) Assign the Sql Policy at subscription scope, using the UAMI
#     - For DeployIfNotExists/Modify effects, an identity AND a Location are required on the assignment.
# ---------------------------
Write-Host ">>> Creating/updating Policy Assignment '$assignmentNameCosmos' at scope $scope using UAMI"

$assignment = New-AzPolicyAssignment `
-Name                  $assignmentNameCosmos `
-Scope                 $scope `
-PolicyDefinition      $policyDefCosmos `
-PolicyParameterObject $policyParams `
-IdentityType          UserAssigned `
-IdentityId            $uami.Id `
-Location              $Location


Write-Host ""
Write-Host "===== Summary ====="
Write-Host ("UAMI PrincipalId : {0}" -f $uami.PrincipalId)
Write-Host ("UAMI ResourceId  : {0}" -f $uami.Id)
Write-Host ("RBAC             : Contributor @ {0}" -f $scope)

# Refresh profile object
$profile = Get-AzNetworkSecurityPerimeter -ResourceGroupName $nspRg -Name $nspName | `
           Get-AzNetworkSecurityPerimeterProfile -Name $profileName

$profileId = $profile.Id

# ================================
# 4. Discover resources from input RGs
# ================================
$targetResources = @()

foreach ($rg in $ResourceGroups) {
    Write-Host "Scanning resource group: $rg" -ForegroundColor Cyan

    # Cosmos DB
    $targetResources += Get-AzCosmosDBAccount -ResourceGroupName $rg | ForEach-Object {
        [PSCustomObject]@{
            ResourceType = "CosmosDB"
            Name         = $_.Name
            ResourceId   = $_.Id
        }
    }

    # SQL Server
    $targetResources += Get-AzSqlServer -ResourceGroupName $rg | ForEach-Object {
        [PSCustomObject]@{
            ResourceType = "SqlServer"
            Name         = $_.ServerName
            ResourceId   = $_.ResourceId
        }
    }

    # Key Vault
    $targetResources += Get-AzKeyVault -ResourceGroupName $rg | ForEach-Object {
        [PSCustomObject]@{
            ResourceType = "KeyVault"
            Name         = $_.VaultName
            ResourceId   = $_.ResourceId
        }
    }

    # Storage Account
    $targetResources += Get-AzStorageAccount -ResourceGroupName $rg | ForEach-Object {
        [PSCustomObject]@{
            ResourceType = "Storage"
            Name         = $_.StorageAccountName
            ResourceId   = $_.Id
        }
    }
}

Write-Host "`nDiscovered resources:" -ForegroundColor Green
$targetResources | Select-Object ResourceType, Name, ResourceId

# ================================
# 5. Associate resources into NSP
# ================================
foreach ($res in $targetResources) {
    if (-not $res.ResourceId) {
        Write-Host "Skipping $($res.Name) — missing ResourceId" -ForegroundColor Red
        continue
    }
	
	switch ($res.ResourceType) {
        "SqlServer" { $prefix = "sql" }
        "CosmosDB"  { $prefix = "cdb" }
        "Storage"   { $prefix = "st" }
        "KeyVault"  { $prefix = "kv" }
        default     { $prefix = "res" } # fallback
    }

    $assocName = "$prefix-$($res.Name)-assoc"

    Write-Host "Associating $($res.ResourceId)..." -ForegroundColor Yellow
    try {
		
        New-AzNetworkSecurityPerimeterAssociation `
            -Name $assocName `
            -ResourceGroupName $nspRg `
            -SecurityPerimeterName $nspName `
            -ProfileId $profileId `
            -PrivateLinkResourceId $res.ResourceId `
            -AccessMode Learning
		
        Write-Host "✅ Associated $($res.Name)" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Failed to associate $($res.Name): $_" -ForegroundColor Red
    }
}

Write-Host "`nScript Completed!" -ForegroundColor Green