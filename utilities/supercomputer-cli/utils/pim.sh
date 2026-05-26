#!/bin/bash
set -ex

# PIM (Privileged Identity Management) Role Assignment Script
# This script activates Azure PIM roles for development work

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
#SUBSCRIPTION_ID="3086b1e7-4896-4188-93b3-21cfd3a4953a"
SUBSCRIPTION_ID="fdba8b3d-edfc-4058-bb5c-f8e137727c3e"
#SUBSCRIPTION_ID="8bd6cf1f-7ca2-4b66-8ec3-3a7620027b80"
#SUBSCRIPTION_ID="af8cc5f9-240a-4a42-a8c5-7e7e239458bd"
JUSTIFICATION="Need access for dev work"
DURATION="PT8H"
API_VERSION="2020-10-01"

# Role definitions - stored as arrays for bash 3.x compatibility
ROLE_NAMES=("contributor" "owner" "discovery admin")
ROLE_DEFINITIONS=(
    "/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.Authorization/roleDefinitions/d09db21b-2578-4ba9-9f0a-105aebe22889"
    "/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
    "/providers/Microsoft.Authorization/roleDefinitions/7a2b6e6c-472e-4b39-8878-a26eb63d75c6"
)

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to get current user's principal ID
get_principal_id() {
    local principal_id
    #principal_id=$(az ad signed-in-user show --query id -o tsv)
    principal_id="e5e9d2e7-a8fb-4219-a42b-48167403f57d"
    
    if [ -z "$principal_id" ]; then
        log_error "Failed to get principal ID. Make sure you're logged in to Azure CLI."
        exit 1
    fi
    
    echo "$principal_id"
}

# Function to generate PIM request body
generate_pim_request_body() {
    local principal_id="$1"
    local role_definition_id="$2"
    local start_time="$3"
    local justification="${4:-$JUSTIFICATION}"
    local duration="${5:-$DURATION}"
    
    cat <<EOF
{
    "properties": {
        "principalId": "$principal_id",
        "roleDefinitionId": "$role_definition_id",
        "requestType": "SelfActivate",
        "justification": "$justification",
        "scheduleInfo": {
            "startDateTime": "$start_time",
            "expiration": {
                "type": "AfterDuration",
                "endDateTime": null,
                "duration": "$duration"
            }
        }
    }
}
EOF
}

# Function to activate a PIM role
activate_pim_role() {
    local role_name="$1"
    local principal_id="$2"
    local role_definition_id="$3"
    
    local request_id
    request_id=$(uuidgen | tr '[:upper:]' '[:lower:]')
    
    local start_time
    start_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    local request_body
    request_body=$(generate_pim_request_body "$principal_id" "$role_definition_id" "$start_time")
    
    local api_url="https://management.azure.com/providers/Microsoft.Subscription/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.Authorization/roleAssignmentScheduleRequests/${request_id}?api-version=${API_VERSION}"
    
    log_info "Activating PIM role: $role_name"
    log_info "Request ID: $request_id"
    log_info "Duration: $DURATION"
    
    if az rest --method put --url "$api_url" --body "$request_body" >/dev/null 2>&1; then
        log_success "Successfully activated PIM role: $role_name"
        return 0
    else
        log_error "Failed to activate PIM role: $role_name"
        return 1
    fi
}

# Function to get role definition ID by name
get_role_definition_id() {
    local role_name="$1"
    local i
    
    for i in "${!ROLE_NAMES[@]}"; do
        if [[ "${ROLE_NAMES[$i]}" == "$role_name" ]]; then
            echo "${ROLE_DEFINITIONS[$i]}"
            return 0
        fi
    done
    
    return 1
}

# Function to activate all PIM roles
activate_all_roles() {
    local principal_id="$1"
    local success_count=0
    local failure_count=0
    
    log_info "Starting PIM role activation for principal: $principal_id"
    echo ""
    
    local i
    for i in "${!ROLE_NAMES[@]}"; do
        if activate_pim_role "${ROLE_NAMES[$i]}" "$principal_id" "${ROLE_DEFINITIONS[$i]}"; then
            ((success_count++))
        else
            ((failure_count++))
        fi
        echo ""
    done
    
    log_info "PIM activation summary:"
    log_info "  Successful activations: $success_count"
    log_info "  Failed activations: $failure_count"
    log_info "  Total roles: ${#ROLE_NAMES[@]}"
    
    if [ $failure_count -eq 0 ]; then
        log_success "All PIM roles activated successfully!"
        return 0
    else
        log_warning "Some PIM role activations failed. Check the output above for details."
        return 1
    fi
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Activate Azure PIM roles for development work"
    echo ""
    echo "Options:"
    echo "  -r, --role ROLE       Activate specific role (contributor, k8s-cluster-admin, rbac-admin, keyvault-secrets-officer, keyvault-certificates-officer)"
    echo "  -j, --justification TEXT  Custom justification (default: '$JUSTIFICATION')"
    echo "  -d, --duration DURATION   Duration in ISO 8601 format (default: $DURATION)"
    echo "  -l, --list            List available roles"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                    # Activate all roles"
    echo "  $0 -r contributor     # Activate only contributor role"
    echo "  $0 -d PT4H            # Activate all roles for 4 hours"
    echo "  $0 -j 'Testing deployment' # Custom justification"
}

# Function to list available roles
list_roles() {
    echo "Available PIM roles:"
    local role_name
    for role_name in "${ROLE_NAMES[@]}"; do
        echo "  - $role_name"
    done
}

# Main function
main() {
    local specific_role=""
    local custom_justification="$JUSTIFICATION"
    local custom_duration="$DURATION"
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -r|--role)
                specific_role="$2"
                shift 2
                ;;
            -j|--justification)
                custom_justification="$2"
                shift 2
                ;;
            -d|--duration)
                custom_duration="$2"
                shift 2
                ;;
            -l|--list)
                list_roles
                exit 0
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # Update global variables with custom values
    JUSTIFICATION="$custom_justification"
    DURATION="$custom_duration"
    
    # Check if Azure CLI is available and user is logged in
    if ! command -v az &> /dev/null; then
        log_error "Azure CLI is not installed or not in PATH"
        exit 1
    fi
    
    if ! az account show &> /dev/null; then
        log_error "Not logged into Azure. Please run 'az login' first."
        exit 1
    fi
    
    # Get principal ID
    local principal_id
    principal_id=$(get_principal_id)
    
    # Activate specific role or all roles
    if [ -n "$specific_role" ]; then
        local role_definition_id
        role_definition_id=$(get_role_definition_id "$specific_role")
        
        if [ $? -eq 0 ]; then
            activate_pim_role "$specific_role" "$principal_id" "$role_definition_id"
        else
            log_error "Unknown role: $specific_role"
            log_info "Available roles:"
            local role_name
            for role_name in "${ROLE_NAMES[@]}"; do
                log_info "  - $role_name"
            done
            exit 1
        fi
    else
        activate_all_roles "$principal_id"
    fi
}

# Run main function
main "$@"
