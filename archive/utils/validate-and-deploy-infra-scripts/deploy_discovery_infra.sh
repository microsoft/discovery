#!/usr/bin/env bash
#
# Main wrapper script for Microsoft Discovery Platform deployment
#
# Prevent MSYS/Git Bash from converting path-like arguments (e.g. /subscriptions/...)
export MSYS_NO_PATHCONV=1

# Wrap the real az CLI to strip \r from output (Windows az.cmd returns CRLF even in WSL/Git Bash)
# PIPESTATUS[0] preserves the real az exit code instead of tr's (always 0).
az() {
    command az "$@" | tr -d '\r'
    return ${PIPESTATUS[0]}
}
#
# Description:
#   This script simplifies the deployment of Microsoft Discovery Platform resources
#   by validating prerequisites and deploying Bicep templates.
#
# Usage:
#   ./deploy_discovery_infra.sh [options]
#
# Options:
#   -s, --subscription-id ID       The Azure subscription ID for deployment (if not provided, uses current)
#   -g, --resource-group NAME      The resource group name (required for ResourceGroup scope; optional for Subscription scope to override the default name)
#   -l, --location LOCATION        The Azure region for deployment (e.g., 'eastus')
#   -c, --scope SCOPE              The scope for deployment: 'Subscription' or 'ResourceGroup' (default: ResourceGroup)
#   -p, --prefix TEXT              The prefix for resource names (default: 'disc')
#   -x, --suffix TEXT              The suffix for resource names (default: randomly generated)
#   -u, --user-id EMAIL            The user principal name (email) for validation
#   -d, --dry-run                  Preview commands without executing them
#   -k, --skip-validation          Skip the validation checks and proceed with deployment
#   -h, --help                     Display this help message
#
# Examples:
#   ./deploy_discovery_infra.sh -g rg-discovery -l eastus -p mydisc -x 001
#   ./deploy_discovery_infra.sh -s 12345678-1234-1234-1234-123456789012 -g rg-discovery -l westeurope
#   ./deploy_discovery_infra.sh -s 12345678-1234-1234-1234-123456789012 -c Subscription -l westeurope -u user@contoso.com
#
# Requirements:
#   - Azure CLI (az) must be installed and logged in
#   - User must have appropriate permissions to deploy resources
#   - Validation script must complete successfully before deployment

set -e

# Define color codes
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
RESET='\033[0m'

# Set default values
SUBSCRIPTION_ID=""
RESOURCE_GROUP_NAME=""
LOCATION=""
SCOPE="ResourceGroup"
PREFIX="d$(date +%m%d)" # Default to 'd' + current month and day
SUFFIX=$(date +%H%M)  # Default to current hour, minute
USER_ID=""
DRY_RUN=false
SKIP_VALIDATION=false
TEMP_BICEP_FILE=""
TEMP_DIR=""

# Function to clean up temporary files
cleanup() {
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        echo -e "${BLUE}Cleaning up temporary files...${RESET}"
        
        # Remove the temp directory and all its contents
        rm -rf "$TEMP_DIR"
        
        echo -e "${GREEN}Cleanup completed.${RESET}"
    fi
}

# Set trap to clean up temp files on exit
trap cleanup EXIT

# Function to print colored output
write_info() {
    echo -e "${BLUE}$1${RESET}"
}

write_success() {
    echo -e "${GREEN}$1${RESET}"
}

write_warning() {
    echo -e "${YELLOW}$1${RESET}"
}

write_error() {
    echo -e "${RED}$1${RESET}"
}

show_usage() {
    echo -e "${CYAN}Microsoft Discovery Platform Deployment Wrapper${RESET}"
    echo -e "${CYAN}=============================================${RESET}"
    echo ""
    echo -e "${WHITE}Usage:${RESET}"
    echo -e "${WHITE}  ./deploy_discovery_infra.sh -g rg-discovery -l eastus -p mydisc -x 001${RESET}"
    echo ""
    echo -e "${YELLOW}Options:${RESET}"
    echo -e "${WHITE}  -s, --subscription-id ID       The Azure subscription ID for deployment${RESET}"
    echo -e "${WHITE}  -g, --resource-group NAME      The resource group name for deployment${RESET}"
    echo -e "${WHITE}  -l, --location LOCATION        The Azure region for deployment (e.g., 'eastus')${RESET}"
    echo -e "${WHITE}  -c, --scope SCOPE              The scope for deployment: 'Subscription' or 'ResourceGroup'${RESET}"
    echo -e "${WHITE}  -p, --prefix TEXT              The prefix for resource names (default: 'disc')${RESET}"
    echo -e "${WHITE}  -x, --suffix TEXT              The suffix for resource names (default: randomly generated)${RESET}"
    echo -e "${WHITE}  -u, --user-id EMAIL            The user principal name (email) for validation${RESET}"
    echo -e "${WHITE}  -d, --dry-run                  Preview commands without executing them${RESET}"
    echo -e "${WHITE}  -k, --skip-validation          Skip the validation checks and proceed with deployment${RESET}"
    echo -e "${WHITE}  -h, --help                     Display this help message${RESET}"
    echo ""
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
                write_error "Invalid scope: $SCOPE. Must be either 'Subscription' or 'ResourceGroup'"
                exit 1
            fi
            shift 2
            ;;
        -p|--prefix)
            PREFIX="$2"
            shift 2
            ;;
        -x|--suffix)
            SUFFIX="$2"
            shift 2
            ;;
        -u|--user-id)
            USER_ID="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -k|--skip-validation)
            SKIP_VALIDATION=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            write_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Check required parameters
if [[ "$SCOPE" == "ResourceGroup" && -z "$RESOURCE_GROUP_NAME" ]]; then
    write_error "Resource group name is required when scope is ResourceGroup. Use -g or --resource-group to specify."
    show_usage
    exit 1
fi

# Validate prefix and suffix
# Prefix should start with a-z and be max 6 chars, only alphanumeric
if ! [[ "$PREFIX" =~ ^[a-z][a-z0-9]{0,5}$ ]]; then
    write_error "Prefix must start with lowercase letter (a-z) and be maximum 6 characters long, containing only alphanumeric characters."
    show_usage
    exit 1
fi

# Suffix should be max 4 chars, only alphanumeric
if ! [[ "$SUFFIX" =~ ^[a-z0-9]{1,4}$ ]]; then
    write_error "Suffix must be maximum 4 characters long, containing only alphanumeric characters."
    show_usage
    exit 1
fi

# Check for required utilities
## Check for Azure CLI
if ! command -v az &> /dev/null; then
    write_error "Azure CLI (az) is not installed. Please install it before proceeding."
    write_info "Installation instructions: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
    
    # Provide platform-specific installation hints
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        write_info "For macOS, you can install using Homebrew: brew install azure-cli"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        write_info "For most Linux distributions, you can use the package manager or script installation."
        write_info "Example for Ubuntu: curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash"
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        # Windows
        write_info "For Windows, download the MSI installer from: https://aka.ms/installazurecliwindows"
    fi
    
    exit 1
fi

## Check for jq utility
if ! command -v jq &> /dev/null; then
    write_error "jq utility is not installed. Please install it before proceeding."
    
    # Provide platform-specific installation hints
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        write_info "For macOS, you can install using Homebrew: brew install jq"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        write_info "For most Linux distributions: sudo apt-get install jq or sudo yum install jq"
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        # Windows
        write_info "For Windows use Chocolatey or winget or scoop to install jq"
    fi
    
    exit 1
fi

if [[ -z "$LOCATION" ]]; then
    write_warning "Location not specified. Attempting to use default location."
    
    if [[ "$SCOPE" == "ResourceGroup" && -n "$RESOURCE_GROUP_NAME" ]]; then
        # Try to get location from existing resource group
        LOCATION=$(az group show --name "$RESOURCE_GROUP_NAME" --query location -o tsv 2>/dev/null || echo "")
    fi
    
    if [[ -z "$LOCATION" ]]; then
        write_error "Could not determine location. Please specify with -l or --location."
        exit 1
    else
        write_info "Using location: $LOCATION"
    fi
fi

# Check Azure CLI and authentication
if ! command -v az &> /dev/null; then
    write_error "Azure CLI is not installed. Please install it: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi

write_info "********* Checking Azure login status *********"
LOGIN_REQUIRED=false

if ! az account show &> /dev/null; then
    LOGIN_REQUIRED=true
    write_info "Not logged in. Logging in to Azure..."
    if [[ "$DRY_RUN" == "true" ]]; then
        write_info "[DRY RUN] Would run: az login"
    else
        az login
    fi
    write_info "Azure login complete."
else
    write_info "Already logged in to Azure."
fi

# Set subscription context if provided
if [[ -n "$SUBSCRIPTION_ID" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
        write_info "[DRY RUN] Would set subscription context to: $SUBSCRIPTION_ID"
        # In dry run mode, we don't actually change the subscription
        # But we'll use the provided subscription ID for the rest of the script
    else
        write_info "Setting subscription context to: $SUBSCRIPTION_ID"
        az account set --subscription "$SUBSCRIPTION_ID"
        write_info "Subscription set."
    fi
else
    # If no subscription ID was provided, use the current one
    if [[ "$DRY_RUN" == "true" && "$LOGIN_REQUIRED" == "true" ]]; then
        # If in dry run mode and login would be required, we can't get the current subscription
        write_info "[DRY RUN] Would determine current subscription."
        # Use a placeholder subscription ID for dry run
        SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"
    else
        # Get current subscription details
        CURRENT_SUBSCRIPTION_ID=$(az account show --query "id" -o tsv)
        CURRENT_SUBSCRIPTION_NAME=$(az account show --query "name" -o tsv)
        write_info "Current subscription: $CURRENT_SUBSCRIPTION_NAME ($CURRENT_SUBSCRIPTION_ID)"
        
        # Only prompt for subscription if not in dry run mode
        if [[ "$DRY_RUN" != "true" ]]; then
            read -p "Press Enter to continue with this subscription or enter a different Subscription ID: " INPUT_SUB_ID
            if [[ -n "$INPUT_SUB_ID" ]]; then
                SUBSCRIPTION_ID="$INPUT_SUB_ID"
                write_info "Setting subscription to $SUBSCRIPTION_ID..."
                az account set --subscription "$SUBSCRIPTION_ID"
                write_info "Subscription set."
            else
                write_info "Using current subscription."
                SUBSCRIPTION_ID="$CURRENT_SUBSCRIPTION_ID"
            fi
        else
            SUBSCRIPTION_ID="$CURRENT_SUBSCRIPTION_ID"
            write_info "[DRY RUN] Would prompt for subscription change, using current subscription for now."
        fi
    fi
fi

if [[ "$DRY_RUN" == "true" && "$LOGIN_REQUIRED" == "true" ]]; then
    write_info "[DRY RUN] Using subscription ID: $SUBSCRIPTION_ID for the rest of the script."
else
    # Store current subscription ID for validation script
    CURRENT_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
    write_info "Using subscription: $CURRENT_SUBSCRIPTION_ID"
fi

# Check if resource group exists when scope is ResourceGroup
if [[ "$SCOPE" == "ResourceGroup" ]]; then
    if [[ "$DRY_RUN" == "true" && "$LOGIN_REQUIRED" == "true" ]]; then
        write_info "[DRY RUN] Would check if resource group '$RESOURCE_GROUP_NAME' exists."
        write_info "[DRY RUN] Would create resource group if it doesn't exist: $RESOURCE_GROUP_NAME in location: $LOCATION"
    elif ! az group show --name "$RESOURCE_GROUP_NAME" &> /dev/null; then
        write_warning "Resource group '$RESOURCE_GROUP_NAME' does not exist."
        
        if [[ "$DRY_RUN" == "true" ]]; then
            write_info "[DRY RUN] Would create resource group: $RESOURCE_GROUP_NAME in location: $LOCATION"
        else
            write_info "Creating resource group: $RESOURCE_GROUP_NAME in location: $LOCATION"
            az group create --name "$RESOURCE_GROUP_NAME" --location "$LOCATION"
        fi
    else
        write_info "Using existing resource group: $RESOURCE_GROUP_NAME"
    fi
fi

# For Subscription scope, inform the user which resource group will be created
if [[ "$SCOPE" == "Subscription" ]]; then
    if [[ -n "$RESOURCE_GROUP_NAME" ]]; then
        write_info "Subscription scope deployment: resource group '$RESOURCE_GROUP_NAME' will be created/used."
    else
        write_info "Subscription scope deployment: resource group '${PREFIX}rg${SUFFIX}' will be created (default from prefix+suffix). Use -g to override."
    fi
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# For MINGW/MSYS, convert to Windows-style C:/ path.
# This format works for both bash file operations and the Windows-native az CLI.
# NOTE: Do NOT convert here for WSL — WSL bash needs native /mnt/c/... paths for
# file operations (mkdir, cp, sed, -f checks).  WSL paths are converted to Windows
# format only when passed to the az CLI (see AZ_TEMPLATE_FILE below).
if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; then
    SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd -W)"
fi

VALIDATION_SCRIPT_PATH="$SCRIPT_DIR/validate.sh"
BICEP_TEMPLATE_PATH="$SCRIPT_DIR/Deployment Templates/main.bicep"

if [[ "$SCOPE" == "Subscription" ]]; then
    BICEP_TEMPLATE_PATH="$SCRIPT_DIR/Deployment Templates/main.sub.bicep"
fi

# Check if validation script exists
if [[ ! -f "$VALIDATION_SCRIPT_PATH" ]]; then
    write_error "Validation script not found at: $VALIDATION_SCRIPT_PATH"
    exit 1
fi

# Check if Bicep template exists
if [[ ! -f "$BICEP_TEMPLATE_PATH" ]]; then
    write_error "Bicep template not found at: $BICEP_TEMPLATE_PATH"
    exit 1
fi

# Run validation script to check prerequisites
write_info "Checking prerequisites..."

if [[ "$SKIP_VALIDATION" == "true" ]]; then
    write_warning "Validation checks are being skipped as requested."
    write_warning "This may lead to deployment failures if prerequisites are not met."
    write_info "Proceeding directly to deployment..."
else
    write_info "Running validation script to check prerequisites..."
    VALIDATION_CMD="bash \"$VALIDATION_SCRIPT_PATH\""

    # Add parameters for the validation script
    if [[ -n "$SUBSCRIPTION_ID" ]]; then
        VALIDATION_CMD="$VALIDATION_CMD -s \"$SUBSCRIPTION_ID\""
    else
        # This should not happen anymore since we ensure SUBSCRIPTION_ID is set above
        if [[ "$DRY_RUN" == "true" && "$LOGIN_REQUIRED" == "true" ]]; then
            VALIDATION_CMD="$VALIDATION_CMD -s \"$SUBSCRIPTION_ID\""
        else
            VALIDATION_CMD="$VALIDATION_CMD -s \"$CURRENT_SUBSCRIPTION_ID\""
        fi
    fi

    if [[ "$SCOPE" == "ResourceGroup" && -n "$RESOURCE_GROUP_NAME" ]]; then
        VALIDATION_CMD="$VALIDATION_CMD -g \"$RESOURCE_GROUP_NAME\""
    fi

    VALIDATION_CMD="$VALIDATION_CMD -c \"$SCOPE\" -l \"$LOCATION\""

    # Add user ID parameter if provided
    if [[ -n "$USER_ID" ]]; then
        VALIDATION_CMD="$VALIDATION_CMD -u \"$USER_ID\""
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        write_info "[DRY RUN] Would run: $VALIDATION_CMD"

        write_info "${YELLOW}Checking resource provider registration..."
        write_info "${YELLOW}Checking user role assignments..."
        write_info "${YELLOW}Checking available vCPU quota..."
        write_info "${YELLOW}Checking AI TPM quota..."
        write_info "${YELLOW}Checking NetApp quota..."
    else
        write_info "Running: $VALIDATION_CMD"
        # Execute validation script directly to see output in real-time
        eval "$VALIDATION_CMD"
        validation_exit_code=$?
        
        # Check validation exit code
        if [[ $validation_exit_code -eq 0 ]]; then
            write_success "Validation passed. Proceeding with deployment."
        elif [[ $validation_exit_code -eq 2 ]]; then
            write_warning "Some operations (like Resource Provider registration) are still in progress."
            
            # Set retry parameters
            MAX_RETRIES=5
            RETRY_COUNT=0
            RETRY_DELAY=30  # seconds
            
            # Retry loop for operations in progress
            while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
                RETRY_COUNT=$((RETRY_COUNT + 1))
                write_info "Waiting for operations to complete (attempt $RETRY_COUNT of $MAX_RETRIES)..."
                write_info "Waiting $RETRY_DELAY seconds before retrying validation..."
                sleep $RETRY_DELAY
                
                # Re-run validation
                write_info "Re-running validation script..."
                # Execute validation script directly to see output in real-time
                eval "$VALIDATION_CMD"
                validation_exit_code=$?
                
                if [[ $validation_exit_code -eq 0 ]]; then
                    write_success "Re-validation passed. Proceeding with deployment."
                    break
                elif [[ $validation_exit_code -ne 2 ]]; then
                    # If we got a different error (not "in progress"), break and handle it
                    break
                fi
                
                # Increase delay for next attempt
                RETRY_DELAY=$((RETRY_DELAY + 15))
            done
            
            # Check final status
            if [[ $validation_exit_code -ne 0 ]]; then
                if [[ $validation_exit_code -eq 2 ]]; then
                    write_error "Operations are still in progress after $MAX_RETRIES attempts."
                    write_info "Some operations like Resource Provider registration can take up to 15 minutes."
                    write_info "Please wait and then re-run this script manually."
                else
                    write_error "Validation failed with unresolved issues. Please address them manually and re-run this script."
                fi
                exit 1
            fi
        else
            write_error "Validation failed. Please fix the identified issues before proceeding with deployment."
            write_info "Re-run this script after addressing all validation issues."
            exit 1
        fi
    fi
fi

# Update Bicep template with prefix and suffix
# Create a temporary Bicep file in the same directory for better tracking
TEMP_DIR="$SCRIPT_DIR/temp"
mkdir -p "$TEMP_DIR"
TEMP_BICEP_FILE="$TEMP_DIR/main_${PREFIX}_${SUFFIX}.bicep"

# Clean up any existing file with the same name
if [[ -f "$TEMP_BICEP_FILE" ]]; then
    rm -f "$TEMP_BICEP_FILE"
fi

# Create the modules directory in the temp directory
mkdir -p "$TEMP_DIR/modules"

if [[ "$DRY_RUN" == "true" ]]; then
    write_info "[DRY RUN] Would update Bicep template with prefix: $PREFIX and suffix: $SUFFIX"
    write_info "[DRY RUN] Would use temporary file: $TEMP_BICEP_FILE"
    # Create a copy of the original bicep file even in dry run mode
    # This ensures we have a consistent directory structure for cleanup
    cp "$BICEP_TEMPLATE_PATH" "$TEMP_BICEP_FILE"
else
    write_info "Updating Bicep template with prefix: $PREFIX and suffix: $SUFFIX"
    write_info "Using temporary file: $TEMP_BICEP_FILE"
    
    # Copy the modules directory from the original location
    cp -R "$SCRIPT_DIR/Deployment Templates/modules/"* "$TEMP_DIR/modules/"
    
    # Create a copy of the original bicep file
    cp "$BICEP_TEMPLATE_PATH" "$TEMP_BICEP_FILE"
    
    # On macOS, sed requires a slightly different syntax for the -i option
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS version
        sed -i '' "s/param prefix string = 'test'/param prefix string = '$PREFIX'/g" "$TEMP_BICEP_FILE"
        sed -i '' "s/param suffix string = '001'/param suffix string = '$SUFFIX'/g" "$TEMP_BICEP_FILE"
    else
        # Linux version
        sed -i "s/param prefix string = 'test'/param prefix string = '$PREFIX'/g" "$TEMP_BICEP_FILE"
        sed -i "s/param suffix string = '001'/param suffix string = '$SUFFIX'/g" "$TEMP_BICEP_FILE"
    fi
    
    write_success "Bicep template updated successfully."
fi

# Deploy Bicep template
write_info "Preparing to deploy Bicep template..."

# Check if Azure CLI has Bicep extension installed
if [[ "$DRY_RUN" == "true" && "$LOGIN_REQUIRED" == "true" ]]; then
    write_info "[DRY RUN] Would check if Azure CLI Bicep extension is installed."
fi

if ! az bicep version &>/dev/null; then
    write_error "Azure CLI Bicep extension is not installed. This is required for deployment."
    write_info "Please install the Bicep extension using the following command:"
    write_info ""
    write_info "For more details: https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/install"
    write_info ""
    
    # Ask user if they want to continue without Bicep
    if [[ "$DRY_RUN" != "true" ]]; then
        write_info "Do you want to continue without Bicep? [y/N]"
        read -r continue_without_bicep
        
        if [[ ! "$continue_without_bicep" =~ ^[Yy]$ ]]; then
            write_info "Deployment aborted. Please install the Bicep extension and try again."
            exit 1
        else
            write_warning "Continuing without the Bicep extension. Deployment will likely fail."
        fi
    else
        write_warning "Install the bicep extension and re-run this script."
        exit 1
    fi
else
    # Bicep extension is installed
    write_info "Azure CLI Bicep extension is installed. Continuing with deployment."
fi

# Construct deployment command with deterministic name for easier troubleshooting
DEPLOYMENT_NAME="disc-${PREFIX}-${SUFFIX}-$(date +%s)"

# Convert the template file path for the Windows-native az CLI when running in WSL.
# WSL bash uses /mnt/c/... paths, but az.cmd needs C:\... paths.
AZ_TEMPLATE_FILE="$TEMP_BICEP_FILE"
if [[ -n "$WSL_DISTRO_NAME" || "$(uname -r)" == *microsoft* ]]; then
    AZ_TEMPLATE_FILE="$(wslpath -w "$TEMP_BICEP_FILE")"
fi

if [[ "$SCOPE" == "ResourceGroup" ]]; then
    DEPLOY_CMD="az deployment group create --resource-group \"$RESOURCE_GROUP_NAME\" --name \"$DEPLOYMENT_NAME\" --template-file \"$AZ_TEMPLATE_FILE\" --parameters location=\"$LOCATION\" prefix=\"$PREFIX\" suffix=\"$SUFFIX\" --no-prompt"
else
    SUB_PARAMS="prefix=\"$PREFIX\" suffix=\"$SUFFIX\""
    if [[ -n "$RESOURCE_GROUP_NAME" ]]; then
        SUB_PARAMS="$SUB_PARAMS resourceGroupName=\"$RESOURCE_GROUP_NAME\""
    fi
    DEPLOY_CMD="az deployment sub create --location \"$LOCATION\" --name \"$DEPLOYMENT_NAME\" --template-file \"$AZ_TEMPLATE_FILE\" --parameters $SUB_PARAMS --no-prompt"
fi

# Set environment variable to suppress Bicep warnings
export BICEP_CLI_WARNING_LEVEL=0
# Add additional suppression for preview resource warnings
export AZURE_BICEP_SUPPRESS_PREVIEW_WARNINGS=true

if [[ "$DRY_RUN" == "true" ]]; then
    write_info "[DRY RUN] Would deploy Bicep template:"
    write_info "$DEPLOY_CMD"
else
    write_info "Deploying Bicep template (deployment name: $DEPLOYMENT_NAME)"
    write_info "$DEPLOY_CMD"
    eval "$DEPLOY_CMD"
    write_success "Bicep template deployment completed successfully."
fi

write_info ""
write_success "**Microsoft Discovery Platform deployment process completed!**"

# Show note about BCP081 warnings if they might still appear
write_info ""
write_info "${YELLOW}Note: If you see BCP081 warnings about resource types not having types available,"
write_info "${YELLOW}these are expected for preview resources like Microsoft.Discovery namespace."
write_info "${YELLOW}These warnings do not affect the deployment functionality and can be safely ignored."
write_info ""

exit 0
