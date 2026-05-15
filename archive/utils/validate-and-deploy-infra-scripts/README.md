# Microsoft Discovery Infrastructure Deployment Scripts

This directory contains scripts and templates for validating and deploying Microsoft Discovery infrastructure resources in Azure. The scripts automate the validation of prerequisites and deployment of the necessary resources using Bicep templates.

## Overview

The deployment process is streamlined through a single script:

- **`deploy_discovery_infra.sh`**: This main script handles both validation and deployment. It automatically runs the validation script (`utils/validation-script/validate.sh`) to check prerequisites and then deploys the Bicep templates that provision the Microsoft Discovery infrastructure resources.

You don't need to run the validation script separately as the deployment script takes care of it. Additionally, the script can automatically assign required RBAC roles if you have sufficient permissions.

## Prerequisites

Before running the script, ensure you have:

- **Azure CLI** installed and logged in (the script will check and prompt you to log in if needed). Please visit a link [here](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest), in case you are looking at instructions on how to install az cli
- **Azure Bicep** Ensure you have azure bicep installed. More instructions [here](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/install#azure-cli)
- **jq** utility installed for JSON processing. More details [here](https://jqlang.org/download/)
- Owner or User Access Administrator role in the subscription (required for automatic role assignment), otherwise you may need to work with your Subscription privileged user to get user role assignments at the Resource Group level

The script will verify these prerequisites and provide installation instructions if any are missing.

## Usage

To deploy Microsoft Discovery resources, simply run the deployment script:

```bash
./deploy_discovery_infra.sh [options]
```

**Options:**

- `-s, --subscription-id ID`: The Azure subscription ID for deployment (if not provided, uses current)
- `-g, --resource-group NAME`: The resource group name for deployment (required when scope is ResourceGroup)
- `-l, --location LOCATION`: The Azure region for deployment (e.g., 'eastus')
- `-c, --scope SCOPE`: The scope for deployment: 'Subscription' or 'ResourceGroup' (default: ResourceGroup)
- `-p, --prefix TEXT`: The prefix for resource names (default: 'd' + 'Date(MMDD)'), example d0924. Must start with a lowercase letter (a-z) and be maximum 6 characters long, containing only lowercase alphanumeric characters.
- `-x, --suffix TEXT`: The suffix for resource names (default: current Hour and Minute if not specified). Must be maximum 4 characters long, containing only lowercase alphanumeric characters.
- `-u, --user-id EMAIL`: The user principal name (email) for validation
- `-d, --dry-run`: Preview commands without executing them
- `-k, --skip-validation`: Skip the validation checks and proceed directly to deployment
- `-h, --help`: Display help message

The script will:

1. Check Azure login status and prompt for login if needed
2. Verify the Azure CLI and jq utility installation
3. Create resource group if it doesn't exist
4. Verify and register required resource providers (can be skipped with `-k` flag)
5. Run validation checks for quotas and permissions (can be skipped with `-k` flag)
6. Assign any missing required roles (if you have permission) (can be skipped with `-k` flag)
7. Deploy the Bicep templates with the specified parameters
8. Clean up any temporary files created during deployment

The script will fail if the same Prefix and Suffix have been used by someone else, so try to choose unique prefix and suffix combo.

### Example Commands

**1. Basic deployment:**

```bash
./deploy_discovery_infra.sh -g "rg-discovery" -l "eastus" -p "test" -x "001" -u "user@example.com"
```

**2. Specify subscription and use custom prefix/suffix:**

```bash
./deploy_discovery_infra.sh -s "00000000-0000-0000-0000-000000000000" -g "rg-discovery" -l "eastus2" -p "test" -x "001" -u "user@example.com"
```

**3. Preview deployment without executing (dry run):**

```bash
./deploy_discovery_infra.sh -s "00000000-0000-0000-0000-000000000000" -g "rg-discovery" -l "eastus" -d
```

**4. Deploy to subscription scope:**

```bash
./deploy_discovery_infra.sh -s "00000000-0000-0000-0000-000000000000" -c "Subscription" -l "swedencentral" -u "user@example.com"
```

**5. Skip validation and proceed directly to deployment:**

```bash
./deploy_discovery_infra.sh -s "00000000-0000-0000-0000-000000000000" -g "rg-discovery" -l "eastus" -k
```

**6. Skip validation and perform a dry run:**

```bash
./deploy_discovery_infra.sh -s "00000000-0000-0000-0000-000000000000" -g "rg-discovery" -l "eastus" -k -d
```

## Deployment Templates

The Bicep templates in the `Deployment Templates` directory define the infrastructure resources to be deployed:

- `main.bicep`: The main deployment template
- `modules/`: Directory containing modular templates for specific resource types:
  - `datacontainer.bicep`: Data container resources
  - `discovery-storage.bicep`: Discovery storage resources
  - `discovery.bicep`: Core Discovery resources
  - `identity.bicep`: Managed identity resources
  - `identity_role_assignments.bicep`: Role assignments for identities
  - `storage.bicep`: Storage account resources
  - `supercomputer.bicep`: Supercomputer resources
  - `vnet.bicep`: Virtual network resources

## Notes

- **Resource Naming Constraints**:

  - **Prefix**: Must start with a lowercase letter (a-z) and be maximum 6 characters long, containing only lowercase alphanumeric characters (a-z, 0-9).
  - **Suffix**: Must be maximum 4 characters long, containing only lowercase alphanumeric characters (a-z, 0-9).
  - These constraints ensure that Azure resource names remain valid and consistent with Azure naming best practices.

- The `-k, --skip-validation` flag allows you to bypass validation checks and proceed directly to deployment. This is useful when:
  - Redeploying after a failed deployment where validation has already passed
  - Continuing deployment when validation cannot complete due to temporary issues
  - Debugging deployment issues without waiting for validation to complete
  - Saving time when redeploying to environments that have already been validated

- During deployment, you may see `BCP081` warnings about resource types not having types available. These are expected for preview resources in the Microsoft.Discovery namespace and can be safely ignored.
- Some operations like Resource Provider registration can take up to 15 minutes to complete. The script includes a retry mechanism that will wait for these operations to complete.
- The script automatically handles many common issues, including:
  - Creating the resource group if it doesn't exist
  - Registering required resource providers
  - Assigning necessary RBAC roles if you have sufficient permissions
  - Checking and prompting for Azure CLI and jq installation
- The script provides colored output for better readability of warnings, errors, and success messages
- For any issues during deployment, review the error messages and consult the Azure portal for more details.
