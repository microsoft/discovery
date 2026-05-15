#!/bin/bash

# Check for jq utility and print install instructions if missing
if ! command -v jq >/dev/null 2>&1; then
    OS="$(uname -s)"
    echo "[ERROR] jq utility is not installed. You will need to install it to ensure successful completion of this script."
    case "$OS" in
        Darwin)
            echo "[INFO] On macOS, install jq using: brew install jq"
            ;;
        Linux)
            echo "[INFO] On Linux (Debian/Ubuntu), install jq using: sudo apt-get update && sudo apt-get install -y jq"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "[INFO] On Windows, install jq using Chocolatey: sudo choco install jq -y"
            ;;
        *)
            echo "[INFO] Please install jq manually for your OS. See https://stedolan.github.io/jq/download/"
            ;;
    esac
    exit 1
else
    echo "[INFO] jq is already installed."
fi

# Validation Script for Discovery Service Onboarding

declare -a issues

# Helper to record an issue consistently
add_issue() {
    local msg="$1"
    issues+=("$msg")
}

# 1. Login and Subscription Selection
echo "********* Checking Azure login status *********"
if ! az account show > /dev/null 2>&1; then
    echo "[INFO] Not logged in. Logging in to Azure..."
    az login
    echo "[INFO] Azure login complete."
else
    echo "[INFO] Already logged in to Azure."
fi

SUBSCRIPTION_ID=$(az account show --query "id" -o tsv)
SUBSCRIPTION_NAME=$(az account show --query "name" -o tsv)
LOGGED_IN_USER=$(az account show --query "user.name" -o tsv)
echo "[INFO] Current subscription: $SUBSCRIPTION_NAME ($SUBSCRIPTION_ID)"
echo "[INFO] Logged in as: $LOGGED_IN_USER"
read -p "Press Enter to continue with this subscription or enter a different Subscription ID: " INPUT_SUB_ID
if [[ -n "$INPUT_SUB_ID" ]]; then
    SUBSCRIPTION_ID="$INPUT_SUB_ID"
    echo "[INFO] Setting subscription to $SUBSCRIPTION_ID..."
    az account set --subscription "$SUBSCRIPTION_ID"
    echo "[INFO] Subscription set."
else
    echo "[INFO] Using current subscription."
fi

# 2. Prompt for Region and User ID
VALID_REGIONS=("eastus" "eastus2" "swedencentral" "uksouth")
while true; do
    read -p "Enter Azure region (eastus, eastus2, swedencentral, uksouth): " REGION
    if [[ " ${VALID_REGIONS[@]} " =~ " $REGION " ]]; then
        echo "[INFO] Region set to $REGION."
        break
    else
        echo "[WARN] Invalid region. Please enter one of: eastus, eastus2, swedencentral, uksouth."
    fi
done
read -p "Enter User Principal Name (email): " USER_ID
echo "[INFO] User Principal Name set to $USER_ID."

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
    echo "[INFO] $RP registration status: $STATUS"
    if [[ "$STATUS" != "Registered" ]]; then
        add_issue "Resource Provider $RP is not registered."
        UNREGISTERED_RPS+=("$RP")
    fi
done
echo "[INFO] Resource Provider registration check complete."

# 4. Verify User Role Assignments
echo ""
echo "********* Role assignments for $USER_ID *********"
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
    ASSIGNED=$(az role assignment list --assignee "$USER_ID" --query "[?roleDefinitionName=='$ROLE']" --scope "/subscriptions/$SUBSCRIPTION_ID" -o tsv)
    if [[ -z "$ASSIGNED" ]]; then
        echo "[WARN] $USER_ID does not have $ROLE role."
        add_issue "User $USER_ID does not have $ROLE role."
        MISSING_ROLES+=("$ROLE")
    else
        echo "[INFO] $USER_ID has $ROLE role."
    fi
done
echo "[INFO] Role assignment check complete."

# 5. Validate AI Foundry TPM Quota (REST API based)
echo ""
echo "********* AI Foundry TPM quota *********"
# Get access token
ACCESS_TOKEN=$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)

# Function to fetch and display quota for a given location
fetch_quota() {
    local LOCATION="$1"
    local API_URL="https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/providers/Microsoft.CognitiveServices/locations/$LOCATION/usages?api-version=2023-05-01"
    local RESPONSE=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "$API_URL")
    if [[ -z "$RESPONSE" || "$RESPONSE" == "{}" ]]; then
        echo "[ERROR] No quota response for location $LOCATION."
        add_issue "No quota response for location $LOCATION."
        return
    fi
    echo "[INFO] AI Foundry TPM quota details for location $LOCATION (GlobalStandard preferred):"
    echo "============================="

    local have_gpt4o_std=false have_gpt4o_global=false
    local gpt4o_std_current=0 gpt4o_std_limit=0 gpt4o_global_current=0 gpt4o_global_limit=0
    local have_embed_std=false have_embed_global=false
    local embed_std_current=0 embed_std_limit=0 embed_global_current=0 embed_global_limit=0

    while read -r item; do
        local MODEL=$(echo "$item" | jq -r '.name.value')
        local CURRENT_RAW=$(echo "$item" | jq -r '.currentValue')
        local LIMIT_RAW=$(echo "$item" | jq -r '.limit')
        [[ -z "$CURRENT_RAW" || "$CURRENT_RAW" == "null" ]] && CURRENT_RAW=0
        [[ -z "$LIMIT_RAW" || "$LIMIT_RAW" == "null" ]] && LIMIT_RAW=0
        local CURR_TPM=$((CURRENT_RAW * 1000))
        local LIMIT_TPM=$((LIMIT_RAW * 1000))
        case "$MODEL" in
            OpenAI.Standard.gpt-4o) have_gpt4o_std=true; gpt4o_std_current=$CURR_TPM; gpt4o_std_limit=$LIMIT_TPM ;;
            OpenAI.GlobalStandard.gpt-4o) have_gpt4o_global=true; gpt4o_global_current=$CURR_TPM; gpt4o_global_limit=$LIMIT_TPM ;;
            OpenAI.Standard.text-embedding-3-small) have_embed_std=true; embed_std_current=$CURR_TPM; embed_std_limit=$LIMIT_TPM ;;
            OpenAI.GlobalStandard.text-embedding-3-small) have_embed_global=true; embed_global_current=$CURR_TPM; embed_global_limit=$LIMIT_TPM ;;
        esac
    done < <(echo "$RESPONSE" | jq -c '.value[]')

    _eval_variant() {
        local family="$1"; local variant="$2"; local current_tpm=$3; local limit_tpm=$4; local threshold=$5
        local rpm_calc
        if [[ "$family" == "GPT-4o" ]]; then
            rpm_calc=$(awk "BEGIN {print ($limit_tpm) / (1000/6)}")
        else
            rpm_calc=$(awk "BEGIN {print ($limit_tpm) / 1000}")
        fi
        local available=$(awk "BEGIN {print ($limit_tpm - $current_tpm)}")
        echo "[INFO] Model Family: $family Variant: $variant ($LOCATION)"
        echo "[INFO] Current TPM Usage: $current_tpm"
        echo "[INFO] TPM Limit: $limit_tpm"
        echo "[INFO] Estimated RPM: $rpm_calc"
        echo "[INFO] Available TPM: $available"
        local label=$([[ "$family" == "GPT-4o" ]] && echo 250K || echo 600K)
        local available_int=${available%.*}
        if [[ -z "$available_int" || $available_int -lt $threshold ]]; then
            if [[ "$family" == "GPT-4o" ]]; then
                echo "[WARN] TPM quota for GPT-4o ($variant) is less than $label in $LOCATION."
                add_issue "TPM quota for GPT-4o ($variant) is less than $label in $LOCATION."
            else
                echo "[WARN] TPM quota for Text-Embedding-3-Small ($variant) is less than $label in $LOCATION."
                add_issue "TPM quota for Text-Embedding-3-Small ($variant) is less than $label in $LOCATION."
            fi
        else
            echo "[INFO] Sufficient TPM quota ($available_int) for $family ($variant) in $LOCATION."
        fi
        echo "-----------------------------"
    }

    if $have_gpt4o_global; then
        $have_gpt4o_std && echo "[INFO] GlobalStandard GPT-4o detected; skipping Standard variant."
        _eval_variant "GPT-4o" "GlobalStandard" $gpt4o_global_current $gpt4o_global_limit 250000
    elif $have_gpt4o_std; then
        _eval_variant "GPT-4o" "Standard" $gpt4o_std_current $gpt4o_std_limit 250000
    else
        echo "[WARN] No GPT-4o quota entries found in $LOCATION."; add_issue "No GPT-4o quota entries found in $LOCATION."
    fi

    if $have_embed_global; then
        $have_embed_std && echo "[INFO] GlobalStandard Text-Embedding-3-Small detected; skipping Standard variant."
        _eval_variant "Text-Embedding-3-Small" "GlobalStandard" $embed_global_current $embed_global_limit 600000
    elif $have_embed_std; then
        _eval_variant "Text-Embedding-3-Small" "Standard" $embed_std_current $embed_std_limit 600000
    else
        echo "[WARN] No Text-Embedding-3-Small quota entries found in $LOCATION."; add_issue "No Text-Embedding-3-Small quota entries found in $LOCATION."
    fi
}

# Check both standard and globalStandard locations
fetch_quota "$REGION"
echo "[INFO] AI Foundry TPM quota check (REST API) complete."

# 6. Check vCPU Quota for Standard_D4s_v6 SKU
echo ""
echo "********* vCPU quota for Standard_D4s_v6 SKU *********"
VCPU_QUOTA=$(az vm list-usage --location "$REGION" --query "[?contains(name.value, 'Dsv6')].limit" -o tsv)
VCPU_USAGE=$(az vm list-usage --location "$REGION" --query "[?contains(name.value, 'Dsv6')].CurrentValue" -o tsv)
if [[ -z "$VCPU_QUOTA" ]]; then
    echo "[WARN] No vCPU quota found for any 'Dsv6' family in $REGION. Listing available VM quota names:"
    az vm list-usage --location "$REGION" -o table
fi
echo "[INFO] vCPU quota for Standard_D4s_v6 SKU: ${VCPU_QUOTA:-none}"
AVAILABLE_VCPU=$((VCPU_QUOTA - VCPU_USAGE))
if [[ -z "$VCPU_QUOTA" || "$AVAILABLE_VCPU" -lt 12 ]]; then
    echo "[WARN] Insufficient available vCPU quota for Standard_D4s_v6 SKU (need at least 12) in $REGION."
    add_issue "Insufficient available vCPU quota for Standard_D4s_v6 SKU (need at least 12) in $REGION."
else
    echo "[INFO] Available vCPU quota for Standard_D4s_v6 SKU: $AVAILABLE_VCPU"
fi
echo "[INFO] vCPU quota check complete."

# 7. Verify NetApp Quota Availability
echo ""
echo "********* NetApp quota *********"
NETAPP_ACCOUNTS=$(az netappfiles account list --query "[].{name:name,resourceGroup:resourceGroup,location:location}" -o tsv)

NETAPP_FOUND=0
USED_QUOTA=0
POOL_SIZES_GB=""

while IFS=$'\t' read -r ACCOUNT_NAME ACCOUNT_RG ACCOUNT_LOC; do
    if [[ "$ACCOUNT_LOC" == "$REGION" ]]; then
        NETAPP_FOUND=1
        POOL_SIZES=$(az netappfiles pool list --resource-group "$ACCOUNT_RG" --account-name "$ACCOUNT_NAME" --query "[].size" -o tsv)
        # Convert pool sizes from bytes to GB (rounded down) and sum for all accounts in region
        for SIZE_BYTES in $POOL_SIZES; do
            SIZE_GB=$((SIZE_BYTES / 1024 / 1024 / 1024))
            USED_QUOTA=$((USED_QUOTA + SIZE_GB))
            POOL_SIZES_GB="$POOL_SIZES_GB $SIZE_GB"
        done
        echo "[INFO] NetApp Account: $ACCOUNT_NAME (Resource Group: $ACCOUNT_RG)"
        echo "[INFO] Pool sizes (GB):$POOL_SIZES_GB"
    fi
done <<< "$NETAPP_ACCOUNTS"
AVAILABLE_QUOTA=$((25600 - USED_QUOTA)) # 25TB = 25600 GB
echo "[INFO] Used quota: $USED_QUOTA GB"
echo "[INFO] Available quota: $AVAILABLE_QUOTA GB"
if [[ "$AVAILABLE_QUOTA" -lt 4096 ]]; then
    echo "[WARN] NetApp available quota less than 4TB (4096GB) in $REGION for account $ACCOUNT_NAME."
    add_issue "NetApp available quota less than 4TB in $REGION for account $ACCOUNT_NAME."
fi
echo "[INFO] NetApp quota check complete."

# 8. Emit issues
echo ""
echo "**********************************"
echo "[INFO] Validation checks complete."
echo "**********************************"

echo ""
ALL_ISSUES_RESOLVED=true
ISSUES_REMAINING=false

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
    # Show unregistered RPs summary
    if [[ ${#UNREGISTERED_RPS[@]} -gt 0 ]]; then
        echo "The following Resource Providers are not registered:"
        for RP in "${UNREGISTERED_RPS[@]}"; do
            echo "- $RP"
        done
        az role assignment list --assignee "$LOGGED_IN_USER" --scope "/subscriptions/$SUBSCRIPTION_ID" --query "[?roleDefinitionName=='Owner' || roleDefinitionName=='User Access Administrator' || roleDefinitionName=='Contributor']" -o tsv | grep -E 'Owner|User Access Administrator|Contributor' > /dev/null
        if [[ $? -eq 0 ]]; then
            read -p "Do you want to register ALL missing Resource Providers now? (y/n): " REG_ALL
            if [[ "$REG_ALL" == "y" ]]; then
                for RP in "${UNREGISTERED_RPS[@]}"; do
                    echo "[INFO] Registering $RP..."
                    az provider register --namespace $RP
                done
                echo "[INFO] All missing Resource Providers have been registered."
                ISSUES_REMAINING=true
            fi
        else
            echo "⚠️  You do not have Owner role permissions to register Resource Providers."
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
        az role assignment list --assignee "$LOGGED_IN_USER" --scope "/subscriptions/$SUBSCRIPTION_ID" --query "[?roleDefinitionName=='Owner' || roleDefinitionName=='User Access Administrator' || roleDefinitionName=='Role Based Access Control Administrator']" -o tsv | grep -E 'Owner|User Access Administrator|Role Based Access Control Administrator' > /dev/null
        if [[ $? -eq 0 ]]; then
            read -p "Do you want to assign ALL missing roles now? (y/n): " ASSIGN_ALL
            if [[ "$ASSIGN_ALL" == "y" ]]; then
                for ROLE in "${MISSING_ROLES[@]}"; do
                    echo "[INFO] Assigning $ROLE to $USER_ID..."
                    az role assignment create --assignee "$USER_ID" --role "$ROLE" --scope "/subscriptions/$SUBSCRIPTION_ID"
                done
                echo "[INFO] All missing roles have been assigned."
            fi
        else
            echo "⚠️  You do not have permissions to assign missing roles."
            ALL_ISSUES_RESOLVED=false
        fi
        echo ""
    fi

    # Mark manual blocking capacity/quota issues
    MANUAL_BLOCKING_FOUND=false
    for issue in "${issues[@]}"; do
        case "$issue" in
            *"TPM quota"*|*"vCPU quota"*|*"NetApp available quota"*|*"No quota response"*)
                MANUAL_BLOCKING_FOUND=true; break ;;
        esac
    done
    if [[ "$MANUAL_BLOCKING_FOUND" == true ]]; then
        echo "[INFO] Detected blocking quota / capacity issues requiring manual remediation."
        ALL_ISSUES_RESOLVED=false
    fi

    if [[ "$ALL_ISSUES_RESOLVED" == true ]]; then
        if [[ "$ISSUES_REMAINING" == true ]]; then
            echo "⚠️  Some operations are still in progress. Re-run this validation script after they complete."
            exit 2
        else
            echo "✅  All validations now pass (after remediation)."
            exit 0
        fi
    else
        echo "⚠️  Some issues remain unresolved. Please address them before proceeding." 
        exit 1
    fi
fi

exit 0