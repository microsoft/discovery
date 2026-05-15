#!/bin/bash
# Validation Script for Discovery Service Onboarding

# Prevent MSYS/Git Bash from converting path-like arguments (e.g. /subscriptions/...)
export MSYS_NO_PATHCONV=1

# Wrap the real az CLI to strip \r from output (Windows az.cmd returns CRLF even in WSL/Git Bash)
# PIPESTATUS[0] preserves the real az exit code instead of tr's (always 0).
az() {
    command az "$@" | tr -d '\r'
    return ${PIPESTATUS[0]}
}

# Define color codes
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

# Initialize variables
SUBSCRIPTION_ID=""
RESOURCE_GROUP_NAME=""
LOCATION=""
SCOPE="ResourceGroup"
USER_ID=""
CHECK_SCOPE_LEVEL=""
CHECK_RESOURCE_GROUP=""

# Functions for colored output
info() {
    echo -e "${BLUE}[INFO] $1${RESET}"
}

success() {
    echo -e "${GREEN}[INFO] $1${RESET}"
}

warn() {
    echo -e "${YELLOW}[WARN] $1${RESET}"
}

error() {
    echo -e "${RED}[ERROR] $1${RESET}"
}

usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -s, --subscription-id ID       The Azure subscription ID for deployment"
    echo "  -g, --resource-group NAME      The resource group name for deployment"
    echo "  -l, --location LOCATION        The Azure region for deployment (e.g., 'eastus')"
    echo "  -c, --scope SCOPE              The scope for deployment: 'Subscription' or 'ResourceGroup'"
    echo "  -u, --user-id EMAIL            The user principal name (email) for validation"
    echo "  -h, --help                     Display this help message"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -s|--subscription-id)
            SUBSCRIPTION_ID="$2"
            shift 2
            ;;
        -g|--resource-group)
            RESOURCE_GROUP_NAME="$2"
            shift 2
            ;;
        -l|--location)
            LOCATION="$2"
            shift 2
            ;;
        -c|--scope)
            SCOPE="$2"
            if [[ "$SCOPE" != "Subscription" && "$SCOPE" != "ResourceGroup" ]]; then
                error "Invalid scope: $SCOPE. Must be either 'Subscription' or 'ResourceGroup'"
                exit 1
            fi
            shift 2
            ;;
        -u|--user-id)
            USER_ID="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            error "Unknown option: $1"
            usage
            ;;
    esac
done

declare -a issues

# Helper to record an issue (centralized in case we later add logging/JSON export)
add_issue() {
    local msg="$1"
    issues+=("$msg")
}

# Check for jq utility and print install instructions if missing
if ! command -v jq >/dev/null 2>&1; then
    OS="$(uname -s)"
    error "jq utility is not installed. You will need to install it to ensure successful completion of this script."
    case "$OS" in
        Darwin)
            info "On macOS, install jq using: brew install jq"
            ;;
        Linux)
            info "On Linux (Debian/Ubuntu), install jq using: sudo apt-get update && sudo apt-get install -y jq"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            info "On Windows, install jq using Chocolatey: sudo choco install jq -y"
            ;;
        *)
            info "Please install jq manually for your OS. See https://stedolan.github.io/jq/download/"
            ;;
    esac
    exit 1
else
    info "jq is already installed."
fi

# 1. Login and Subscription Selection
echo "********* Checking Azure login status *********"
if ! az account show > /dev/null 2>&1; then
    info "Not logged in. Logging in to Azure..."
    az login
    info "Azure login complete."
else
    info "Already logged in to Azure."
fi

# Set subscription context if provided
if [[ -n "$SUBSCRIPTION_ID" ]]; then
    info "Setting subscription context to: $SUBSCRIPTION_ID"
    az account set --subscription "$SUBSCRIPTION_ID"
    info "Subscription set."
else
    # If no subscription ID was provided, use the current one
    SUBSCRIPTION_ID=$(az account show --query "id" -o tsv)
    SUBSCRIPTION_NAME=$(az account show --query "name" -o tsv)
    info "Current subscription: $SUBSCRIPTION_NAME ($SUBSCRIPTION_ID)"
    # Only prompt for subscription if not passed as parameter
    read -p "Press Enter to continue with this subscription or enter a different Subscription ID: " INPUT_SUB_ID
    if [[ -n "$INPUT_SUB_ID" ]]; then
        SUBSCRIPTION_ID="$INPUT_SUB_ID"
        info "Setting subscription to $SUBSCRIPTION_ID..."
        az account set --subscription "$SUBSCRIPTION_ID"
        info "Subscription set."
    else
        info "Using current subscription."
    fi
fi

# 2. Prompt for Region and User ID if not provided
if [[ -z "$LOCATION" ]]; then
    VALID_REGIONS=("eastus" "eastus2" "swedencentral" "uksouth")
    while true; do
        read -p "Enter Azure region (eastus, eastus2, swedencentral, uksouth): " LOCATION
        if [[ " ${VALID_REGIONS[@]} " =~ " $LOCATION " ]]; then
            info "Region set to $LOCATION."
            break
        else
            warn "Invalid region. Please enter one of: eastus, eastus2, swedencentral, uksouth."
        fi
    done
else
    info "Using provided region: $LOCATION"
fi

if [[ -z "$USER_ID" ]]; then
    read -p "Enter User Principal Name (email): " USER_ID
    info "User Principal Name set to $USER_ID."
else
    info "Using provided User Principal Name: $USER_ID"
fi

# 3. Check Required Resource Providers (RPs)
echo ""
echo "********* Resource Providers registration check *********"
REQUIRED_RPS=(
    Microsoft.Discovery Microsoft.Network Microsoft.Compute Microsoft.Storage Microsoft.ManagedIdentity Microsoft.AlertsManagement
    Microsoft.Authorization Microsoft.CognitiveServices Microsoft.ContainerInstance Microsoft.ContainerRegistry
    Microsoft.ContainerService Microsoft.DocumentDB Microsoft.Features Microsoft.KeyVault Microsoft.MachineLearningServices
    Microsoft.NetApp Microsoft.OperationalInsights Microsoft.ResourceGraph Microsoft.Search Microsoft.Web
    Microsoft.Insights Microsoft.Resources Microsoft.Sql Microsoft.App
)
UNREGISTERED_RPS=()
for RP in "${REQUIRED_RPS[@]}"; do
    STATUS=$(az provider show --namespace $RP --query "registrationState" -o tsv)
    info "$RP registration status: $STATUS"
    if [[ "$STATUS" != "Registered" ]]; then
        add_issue "Resource Provider $RP is not registered."
        UNREGISTERED_RPS+=("$RP")
    fi
done
info "Resource Provider registration check complete."

# 4. Verify User Role Assignments
echo ""
echo "********* Role assignments for $USER_ID *********"
# Set scope level based on parameters if provided
if [[ -n "$SCOPE" ]]; then
    CHECK_SCOPE_LEVEL=$(echo "$SCOPE" | tr '[:upper:]' '[:lower:]')
    
    if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" && -n "$RESOURCE_GROUP_NAME" ]]; then
        CHECK_RESOURCE_GROUP="$RESOURCE_GROUP_NAME"
        info "Checking roles at resource group level: $CHECK_RESOURCE_GROUP"
    else
        info "Checking roles at subscription level"
    fi
else
    # If scope not provided as parameter, prompt for it
    read -p "Do you want to check roles at subscription level or resource group level? (subscription/resourcegroup): " CHECK_SCOPE_LEVEL
    
    if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" ]]; then
        # If resource group name provided as parameter, use it
        if [[ -n "$RESOURCE_GROUP_NAME" ]]; then
            CHECK_RESOURCE_GROUP="$RESOURCE_GROUP_NAME"
            info "Using provided resource group: $CHECK_RESOURCE_GROUP"
        else
            read -p "Enter the resource group name to check roles: " CHECK_RESOURCE_GROUP
        fi
    fi
fi

CHECK_SCOPE=""
if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" ]]; then
    # Get the full resource ID for the resource group to use as scope
    CHECK_SCOPE=$(az group show --name "$CHECK_RESOURCE_GROUP" --query id -o tsv 2>/dev/null)
    if [[ -z "$CHECK_SCOPE" ]]; then
        warn "Resource group '$CHECK_RESOURCE_GROUP' not found. Defaulting to subscription level check."
        CHECK_SCOPE_LEVEL="subscription"
    else
        info "Checking roles at resource group level: $CHECK_RESOURCE_GROUP"
    fi
else
    info "Checking roles at subscription level"
fi

REQUIRED_ROLES=(
    "Microsoft Discovery Platform Administrator (Preview)"
    "Storage Account Contributor"
    "Storage Blob Data Contributor"
    "AcrPush"
    "Managed Identity Operator"
    "Managed Identity Contributor"
    "Network Contributor"
    "Reader"
)
MISSING_ROLES=()
for ROLE in "${REQUIRED_ROLES[@]}"; do
    if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" && -n "$CHECK_SCOPE" ]]; then
        # Check role assignments at resource group scope
        ASSIGNED=$(az role assignment list --assignee "$USER_ID" --scope "$CHECK_SCOPE" --subscription "$SUBSCRIPTION_ID" --query "[?roleDefinitionName=='$ROLE']" -o tsv)
    else
        # Check role assignments at subscription level
        ASSIGNED=$(az role assignment list --assignee "$USER_ID" --query "[?roleDefinitionName=='$ROLE']" --scope "/subscriptions/$SUBSCRIPTION_ID" --subscription "$SUBSCRIPTION_ID" -o tsv)
    fi
    
    if [[ -z "$ASSIGNED" ]]; then
        if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" ]]; then
            warn "$USER_ID does not have $ROLE role at resource group level."
            add_issue "User $USER_ID does not have $ROLE role at resource group level."
        else
            warn "$USER_ID does not have $ROLE role at subscription level."
            add_issue "User $USER_ID does not have $ROLE role at subscription level."
        fi
        MISSING_ROLES+=("$ROLE")
    else
        if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" ]]; then
            info "$USER_ID has $ROLE role at resource group level."
        else
            info "$USER_ID has $ROLE role at subscription level."
        fi
    fi
done
info "Role assignment check complete."

# 5. Validate AI Foundry TPM Quota (REST API based)
echo ""
echo "********* AI Foundry TPM quota *********"
# Get access token
ACCESS_TOKEN=$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)

# Function to fetch and display quota for a given location
fetch_quota() {
    local LOC="$1"
    local API_URL="https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/providers/Microsoft.CognitiveServices/locations/$LOC/usages?api-version=2023-05-01"
    local RESPONSE=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "$API_URL")
    if [[ -z "$RESPONSE" || "$RESPONSE" == "{}" ]]; then
        error "No quota response for location $LOC."
    add_issue "No quota response for location $LOC."
        return
    fi
    info "AI Foundry TPM quota details for location $LOC (GlobalStandard preferred):"
    echo "============================="

    # Track presence of standard and global variants for each model family.
    local have_gpt4o_std=false have_gpt4o_global=false
    local gpt4o_std_current=0 gpt4o_std_limit=0 gpt4o_global_current=0 gpt4o_global_limit=0
    local have_embed_std=false have_embed_global=false
    local embed_std_current=0 embed_std_limit=0 embed_global_current=0 embed_global_limit=0

    # Parse all entries first (no subshell).
    while read -r item; do
        local MODEL=$(echo "$item" | jq -r '.name.value')
        local CURRENT_RAW=$(echo "$item" | jq -r '.currentValue')
        local LIMIT_RAW=$(echo "$item" | jq -r '.limit')
        # Normalize numeric safety (default 0 if blank)
        [[ -z "$CURRENT_RAW" || "$CURRENT_RAW" == "null" ]] && CURRENT_RAW=0
        [[ -z "$LIMIT_RAW" || "$LIMIT_RAW" == "null" ]] && LIMIT_RAW=0
        local CURR_TPM=$((CURRENT_RAW * 1000))
        local LIMIT_TPM=$((LIMIT_RAW * 1000))

        case "$MODEL" in
            OpenAI.Standard.gpt-4o)
                have_gpt4o_std=true; gpt4o_std_current=$CURR_TPM; gpt4o_std_limit=$LIMIT_TPM ;;
            OpenAI.GlobalStandard.gpt-4o)
                have_gpt4o_global=true; gpt4o_global_current=$CURR_TPM; gpt4o_global_limit=$LIMIT_TPM ;;
            OpenAI.Standard.text-embedding-3-small)
                have_embed_std=true; embed_std_current=$CURR_TPM; embed_std_limit=$LIMIT_TPM ;;
            OpenAI.GlobalStandard.text-embedding-3-small)
                have_embed_global=true; embed_global_current=$CURR_TPM; embed_global_limit=$LIMIT_TPM ;;
        esac
    done < <(echo "$RESPONSE" | jq -c '.value[]')

    # Helper to evaluate a single variant
    _evaluate_variant() {
        local family="$1" # GPT-4o or Text-Embedding-3-Small
        local variant="$2" # Standard or GlobalStandard
        local current_tpm=$3
        local limit_tpm=$4
        local threshold=$5
        local rpm_calc
        if [[ "$family" == "GPT-4o" ]]; then
            # Original calculation: TPM_LIMIT / (1000/6) (because 1000 tokens per ~6 RPM segments?)
            rpm_calc=$(awk "BEGIN {print ($limit_tpm) / (1000/6)}")
        else
            rpm_calc=$(awk "BEGIN {print ($limit_tpm) / 1000}")
        fi
        local available=$(awk "BEGIN {print ($limit_tpm - $current_tpm)}")
        info "Model Family: $family Variant: $variant ($LOC)"
        info "Current TPM Usage: $current_tpm"
        info "TPM Limit: $limit_tpm"
        info "Estimated RPM: $rpm_calc"
        info "Available TPM: $available"
        local thresh_label
        if [[ "$family" == "GPT-4o" ]]; then
            thresh_label="250K"
        else
            thresh_label="600K"
        fi
        # Numeric compare: cast available to int (floor) for threshold test.
        local available_int=${available%.*}
        if [[ -z "$available_int" || $available_int -lt $threshold ]]; then
            if [[ "$family" == "GPT-4o" ]]; then
                warn "TPM quota for GPT-4o ($variant) is less than $thresh_label in $LOC."
                add_issue "TPM quota for GPT-4o ($variant) is less than $thresh_label in $LOC."
            else
                warn "TPM quota for Text-Embedding-3-Small ($variant) is less than $thresh_label in $LOC."
                add_issue "TPM quota for Text-Embedding-3-Small ($variant) is less than $thresh_label in $LOC."
            fi
        else
            info "Sufficient TPM quota ($available_int) for $family ($variant) in $LOC."
        fi
        echo "-----------------------------"
    }

    # GPT-4o evaluation: prefer GlobalStandard
    if $have_gpt4o_global; then
        if $have_gpt4o_std; then
            info "GlobalStandard GPT-4o detected; skipping Standard variant quota enforcement."
        fi
        _evaluate_variant "GPT-4o" "GlobalStandard" $gpt4o_global_current $gpt4o_global_limit 250000
    elif $have_gpt4o_std; then
        _evaluate_variant "GPT-4o" "Standard" $gpt4o_std_current $gpt4o_std_limit 250000
    else
        warn "No GPT-4o quota entries found in $LOC."
        add_issue "No GPT-4o quota entries found in $LOC."
    fi

    # Embedding model evaluation: prefer GlobalStandard
    if $have_embed_global; then
        if $have_embed_std; then
            info "GlobalStandard Text-Embedding-3-Small detected; skipping Standard variant quota enforcement."
        fi
        _evaluate_variant "Text-Embedding-3-Small" "GlobalStandard" $embed_global_current $embed_global_limit 600000
    elif $have_embed_std; then
        _evaluate_variant "Text-Embedding-3-Small" "Standard" $embed_std_current $embed_std_limit 600000
    else
        warn "No Text-Embedding-3-Small quota entries found in $LOC."
        add_issue "No Text-Embedding-3-Small quota entries found in $LOC."
    fi
}

# Check both standard and globalStandard locations
fetch_quota "$LOCATION"
info "AI Foundry TPM quota check (REST API) complete."

# 6. Check vCPU Quota for Standard_D4s_v6 SKU
echo ""
echo "********* vCPU quota for Standard_D4s_v6 SKU *********"
VCPU_QUOTA=$(az vm list-usage --location "$LOCATION" --query "[?contains(name.value, 'Dsv6')].limit" -o tsv)
VCPU_USAGE=$(az vm list-usage --location "$LOCATION" --query "[?contains(name.value, 'Dsv6')].CurrentValue" -o tsv)
if [[ -z "$VCPU_QUOTA" ]]; then
    warn "No vCPU quota found for any 'Dsv6' family in $LOCATION. Listing available VM quota names:"
    az vm list-usage --location "$LOCATION" -o table
fi
info "vCPU quota for Standard_D4s_v6 SKU: ${VCPU_QUOTA:-none}"
AVAILABLE_VCPU=$((VCPU_QUOTA - VCPU_USAGE))
if [[ -z "$VCPU_QUOTA" || "$AVAILABLE_VCPU" -lt 12 ]]; then
    # NOTE: This section avoids pipelines that would create a subshell; adding issues via add_issue is safe.
    warn "Insufficient available vCPU quota for Standard_D4s_v6 SKU (need at least 12) in $LOCATION."
    add_issue "Insufficient available vCPU quota for Standard_D4s_v6 SKU (need at least 12) in $LOCATION."
else
    info "Available vCPU quota for Standard_D4s_v6 SKU: $AVAILABLE_VCPU"
fi
info "vCPU quota check complete."

# 7. Verify NetApp Quota Availability
echo ""
echo "********* NetApp quota *********"
NETAPP_ACCOUNTS=$(az netappfiles account list --query "[].{name:name,resourceGroup:resourceGroup,location:location}" -o tsv)

NETAPP_FOUND=0
USED_QUOTA=0
POOL_SIZES_GB=""

while IFS=$'\t' read -r ACCOUNT_NAME ACCOUNT_RG ACCOUNT_LOC; do
    if [[ "$ACCOUNT_LOC" == "$LOCATION" ]]; then
        NETAPP_FOUND=1
        POOL_SIZES=$(az netappfiles pool list --resource-group "$ACCOUNT_RG" --account-name "$ACCOUNT_NAME" --query "[].size" -o tsv)
        # Convert pool sizes from bytes to GB (rounded down) and sum for all accounts in region
        for SIZE_BYTES in $POOL_SIZES; do
            SIZE_GB=$((SIZE_BYTES / 1024 / 1024 / 1024))
            USED_QUOTA=$((USED_QUOTA + SIZE_GB))
            POOL_SIZES_GB="$POOL_SIZES_GB $SIZE_GB"
        done
        info "NetApp Account: $ACCOUNT_NAME (Resource Group: $ACCOUNT_RG)"
        info "Pool sizes (GB):$POOL_SIZES_GB"
    fi
done <<< "$NETAPP_ACCOUNTS"
AVAILABLE_QUOTA=$((25600 - USED_QUOTA)) # 25TB = 25600 GB
info "Used quota: $USED_QUOTA GB"
info "Available quota: $AVAILABLE_QUOTA GB"
if [[ "$AVAILABLE_QUOTA" -lt 4096 ]]; then
    # NOTE: NetApp quota loop uses here-string (<<<) which does not spawn a subshell; still using add_issue for consistency.
    warn "NetApp available quota less than 4TB (4096GB) in $LOCATION for account $ACCOUNT_NAME."
    add_issue "NetApp available quota less than 4TB in $LOCATION for account $ACCOUNT_NAME."
fi
info "NetApp quota check complete."

# 8. Emit issues
echo ""
echo "**********************************"
info "Validation checks complete."
echo "**********************************"

ALL_ISSUES_RESOLVED=true

echo ""
if [[ ${#issues[@]} -eq 0 ]]; then
    echo "✅  All validations passed."
    echo ""
else
    echo "⚠️  Issues found during validation:"
    for issue in "${issues[@]}"; do
        echo "- $issue"
    done
    echo ""
    echo "Note: Ensure these issues are addressed before you start Discovery resource deployment."
    echo ""
    
    ISSUES_REMAINING=false
    
    # Show unregistered RPs summary
    if [[ ${#UNREGISTERED_RPS[@]} -gt 0 ]]; then
        echo "The following Resource Providers are not registered:"
        for RP in "${UNREGISTERED_RPS[@]}"; do
            echo "- $RP"
        done
        az role assignment list --assignee "$USER_ID" --scope "/subscriptions/$SUBSCRIPTION_ID" --subscription "$SUBSCRIPTION_ID" --query "[?roleDefinitionName=='Owner' || roleDefinitionName=='User Access Administrator' || roleDefinitionName=='Contributor']" -o tsv | grep -E 'Owner|User Access Administrator|Contributor' > /dev/null
        if [[ $? -eq 0 ]]; then
            read -p "Do you want to register ALL missing Resource Providers now? (y/n): " REG_ALL
            if [[ "$REG_ALL" == "y" ]]; then
                for RP in "${UNREGISTERED_RPS[@]}"; do
                    info "Registering $RP..."
                    az provider register --namespace $RP
                done
                info "All missing Resource Providers have been registered."
                info "Note: Registration may take several minutes to complete. Re-run validation to confirm."
                ISSUES_REMAINING=true
            else
                info "Resource Provider registration skipped."
                ALL_ISSUES_RESOLVED=false
            fi
        else
            error "You do not have Owner role permissions to register Resource Providers."
            ALL_ISSUES_RESOLVED=false
        fi
        echo ""
    fi
    
    # Show missing roles summary and offer to assign
    if [[ ${#MISSING_ROLES[@]} -gt 0 ]]; then
        echo "The following roles are missing for $USER_ID:"
        for ROLE in "${MISSING_ROLES[@]}"; do
            echo "- $ROLE"
        done
        # Determine if user has privilege to assign roles at the checked scope OR at subscription scope (fallback)
        HAS_ASSIGN_PERMISSION=0
        if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" && -n "$CHECK_SCOPE" ]]; then
            # First check at resource group scope
            if az role assignment list --assignee "$USER_ID" --scope "$CHECK_SCOPE" --subscription "$SUBSCRIPTION_ID" \
                --query "[?roleDefinitionName=='Owner' || roleDefinitionName=='User Access Administrator' || roleDefinitionName=='Role Based Access Control Administrator']" -o tsv \
                | grep -E 'Owner|User Access Administrator|Role Based Access Control Administrator' > /dev/null; then
                HAS_ASSIGN_PERMISSION=1
            else
                # Fallback: user may have assignment privilege at subscription scope (Owner / UAA / RBAC Admin)
                if az role assignment list --assignee "$USER_ID" --scope "/subscriptions/$SUBSCRIPTION_ID" --subscription "$SUBSCRIPTION_ID" \
                    --query "[?roleDefinitionName=='Owner' || roleDefinitionName=='User Access Administrator' || roleDefinitionName=='Role Based Access Control Administrator']" -o tsv \
                    | grep -E 'Owner|User Access Administrator|Role Based Access Control Administrator' > /dev/null; then
                    HAS_ASSIGN_PERMISSION=1
                    info "User has required role-assignment permissions at subscription scope (will allow assigning missing roles at resource group scope)."
                fi
            fi
        else
            # Subscription level validation – check directly
            if az role assignment list --assignee "$USER_ID" --scope "/subscriptions/$SUBSCRIPTION_ID" --subscription "$SUBSCRIPTION_ID" \
                --query "[?roleDefinitionName=='Owner' || roleDefinitionName=='User Access Administrator' || roleDefinitionName=='Role Based Access Control Administrator']" -o tsv \
                | grep -E 'Owner|User Access Administrator|Role Based Access Control Administrator' > /dev/null; then
                HAS_ASSIGN_PERMISSION=1
            fi
        fi

        if [[ $HAS_ASSIGN_PERMISSION -eq 1 ]]; then
            read -p "Do you want to assign ALL missing roles now? (y/n): " ASSIGN_ALL
            if [[ "$ASSIGN_ALL" == "y" ]]; then
                # Use the same scope level that was used for checking
                if [[ "$CHECK_SCOPE_LEVEL" == "resourcegroup" && -n "$CHECK_SCOPE" ]]; then
                    info "Roles will be assigned at resource group level: $CHECK_RESOURCE_GROUP"
                    for ROLE in "${MISSING_ROLES[@]}"; do
                        info "Assigning $ROLE to $USER_ID at resource group scope..."
                        if ! az role assignment create --assignee "$USER_ID" --role "$ROLE" --scope "$CHECK_SCOPE" --subscription "$SUBSCRIPTION_ID" 2>&1; then
                            warn "Failed to assign $ROLE. Trying with assignee object ID..."
                            ASSIGNEE_OID=$(az ad user show --id "$USER_ID" --query id -o tsv 2>/dev/null)
                            if [[ -n "$ASSIGNEE_OID" ]]; then
                                az role assignment create --assignee-object-id "$ASSIGNEE_OID" --assignee-principal-type User --role "$ROLE" --scope "$CHECK_SCOPE" --subscription "$SUBSCRIPTION_ID" 2>&1 || warn "Failed to assign $ROLE even with object ID."
                            fi
                        fi
                    done
                    info "All missing roles have been assigned at resource group level."
                else
                    info "Roles will be assigned at subscription level"
                    for ROLE in "${MISSING_ROLES[@]}"; do
                        info "Assigning $ROLE to $USER_ID at subscription scope..."
                        if ! az role assignment create --assignee "$USER_ID" --role "$ROLE" --scope "/subscriptions/$SUBSCRIPTION_ID" --subscription "$SUBSCRIPTION_ID" 2>&1; then
                            warn "Failed to assign $ROLE. Trying with assignee object ID..."
                            ASSIGNEE_OID=$(az ad user show --id "$USER_ID" --query id -o tsv 2>/dev/null)
                            if [[ -n "$ASSIGNEE_OID" ]]; then
                                az role assignment create --assignee-object-id "$ASSIGNEE_OID" --assignee-principal-type User --role "$ROLE" --scope "/subscriptions/$SUBSCRIPTION_ID" --subscription "$SUBSCRIPTION_ID" 2>&1 || warn "Failed to assign $ROLE even with object ID."
                            fi
                        fi
                    done
                    info "All missing roles have been assigned at subscription level."
                fi
                info "Role assignments complete. No need to re-run validation for this issue."
            else
                info "Role assignments skipped."
                ALL_ISSUES_RESOLVED=false
            fi
        else
            error "You do not have permissions to assign missing roles (no Owner / User Access Administrator / RBAC Admin role at resource group or subscription scope)."
            info "If you DO have Owner at subscription scope but still see this, re-run with an explicit subscription ID: -s <subscriptionId>."
            ALL_ISSUES_RESOLVED=false
        fi
        echo ""
    fi
    
    # Detect manual (non-auto-remediated) blocking capacity / quota issues.
    # These should force ALL_ISSUES_RESOLVED=false so the script exits with code 1
    # instead of incorrectly reporting success.
    MANUAL_BLOCKING_FOUND=false
    for issue in "${issues[@]}"; do
        case "$issue" in
            *"TPM quota"*|*"vCPU quota"*|*"NetApp available quota"*|*"No quota response"*)
                MANUAL_BLOCKING_FOUND=true
                break
                ;;
        esac
    done

    if [[ "$MANUAL_BLOCKING_FOUND" == "true" ]]; then
        info "Detected blocking quota / capacity issues that require manual remediation (e.g., quota increase or resource cleanup)."
        info "These must be resolved before deployment will succeed."
        ALL_ISSUES_RESOLVED=false
    fi

    # Emit summary
    if [[ "$ALL_ISSUES_RESOLVED" == "true" ]]; then
        if [[ "$ISSUES_REMAINING" == "true" ]]; then
            echo "⚠️  Some operations are still in progress (e.g., Resource Provider registration)."
            echo "    Re-run this validation script to verify all issues are resolved."
            exit 2  # Exit with code 2 to indicate operations in progress
        else
            echo "✅  All validations now pass."
            exit 0  # Success
        fi
    else
        echo "⚠️  Some issues remain unresolved. Please address them before proceeding."
        exit 1  # Exit with code 1 to indicate unresolved issues
    fi
fi

# If we get here, all validations passed from the beginning
exit 0