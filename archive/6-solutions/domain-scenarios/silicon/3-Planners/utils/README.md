# Utilities Directory

This directory contains utilities for the Microsoft Discovery platform, including tools for processing definition files, Docker automation, and Azure Container Registry management.

## Tools Overview

This directory contains utilities for processing Microsoft Discovery tool definitions and environment setup:

1. **`definition-content-creator.py`**: Converts individual YAML files to JSON
2. **`update-tools-definition-and-generate-json.ps1`**: Automated PowerShell script to update ACR paths and generate all JSON files
3. **`generate-docker-images-and-push-to-acr.ps1`**: Cross-platform PowerShell script to build and push Docker images to ACR
4. **`generate-agent-workflow-json.ps1`**: PowerShell script to convert agent and workflow YAML files to JSON format
5. **`docker-setup-automation.ps1`**: Cross-platform PowerShell script for Docker environment setup (Mac, Windows, Linux)
6. **`register-rp.ps1`**: Azure Resource Provider registration status checker and registration tool
7. **`role-assignments.ps1`**: Azure role assignment tool for Microsoft Discovery Platform permissions
8. **`update-agent-names.py`**: Python script to update agent names across all YAML files and maintain consistency

## Azure Resource Provider Management

### Resource Provider Registration Tool

The **`register-rp.ps1`** script provides automated checking and registration of Azure Resource Providers required for Microsoft Discovery platform:

```powershell
# Check RP status in current subscription
pwsh register-rp.ps1

# Check and register unregistered RPs (with confirmation)
pwsh register-rp.ps1 -Register

# Target specific subscription
pwsh register-rp.ps1 -SubscriptionId 'your-subscription-id'

# Enable verbose output
pwsh register-rp.ps1 -Verbose

# Show help and RP list
pwsh register-rp.ps1 -Help
```

**Features:**

- **Status Checking**: Displays registration status of all required Resource Providers
- **Batch Registration**: Registers multiple unregistered RPs with confirmation
- **Colored Output**: Easy-to-read status with color-coded results
- **Subscription Targeting**: Works with specific subscription IDs
- **Comprehensive Coverage**: Checks 23 essential RPs for Discovery platform
- **Safe Operations**: Confirmation prompts before making changes

**Resource Providers Managed:**

- Microsoft.Network, Microsoft.Compute, Microsoft.Storage
- Microsoft.ManagedIdentity, Microsoft.AlertsManagement, Microsoft.Authorization
- Microsoft.CognitiveServices, Microsoft.ContainerInstance, Microsoft.ContainerRegistry
- Microsoft.ContainerService, Microsoft.DocumentDB, Microsoft.Features
- Microsoft.KeyVault, Microsoft.MachineLearningServices, Microsoft.NetApp
- Microsoft.OperationalInsights, Microsoft.ResourceGraph, Microsoft.Search
- Microsoft.Web, Microsoft.insights, Microsoft.Resources, Microsoft.Sql, Microsoft.App

**Prerequisites:**

- **Azure CLI**: Installed and authenticated (`az login`)
- **PowerShell 5.1+**: Windows or PowerShell 7+ for cross-platform
- **Subscription Access**: Contributor or Owner role for registration

## Azure Role Assignment Management

### Role Assignment Tool for Microsoft Discovery Platform

The **`role-assignments.ps1`** script provides automated assignment of comprehensive Azure roles required for Microsoft Discovery Platform deployments:

```powershell
# Assign roles to a user (basic usage)
pwsh role-assignments.ps1 -UserPrincipalName "user@contoso.com"

# Assign roles using Object ID
pwsh role-assignments.ps1 -ObjectId "12345678-1234-1234-1234-123456789012"

# Assign roles to a service principal
pwsh role-assignments.ps1 -ServicePrincipalName "sp-discovery"

# Target specific subscription
pwsh role-assignments.ps1 -UserPrincipalName "user@contoso.com" -SubscriptionId "your-subscription-id"

# Assign roles at resource group scope
pwsh role-assignments.ps1 -UserPrincipalName "user@contoso.com" -ResourceGroupName "rg-discovery" -Scope "ResourceGroup"

# Preview assignments without making changes (dry run)
pwsh role-assignments.ps1 -UserPrincipalName "user@contoso.com" -DryRun

# Skip confirmation prompts
pwsh role-assignments.ps1 -UserPrincipalName "user@contoso.com" -Force

# Show help and role list
pwsh role-assignments.ps1 -Help
```

**Features:**

- **Comprehensive Role Coverage**: Assigns 12 essential roles for Discovery Platform operations
- **Multiple Identity Types**: Supports users, service principals, and managed identities
- **Flexible Scoping**: Assign roles at subscription or resource group level
- **Intelligent Validation**: Verifies role definitions and availability in your tenant
- **Existing Assignment Detection**: Skips roles already assigned to avoid duplicates
- **Preview Mode**: Dry run capability to preview assignments before execution
- **Colored Output**: Easy-to-read status with color-coded results
- **Error Handling**: Graceful handling of missing roles and permission issues
- **Safe Operations**: Confirmation prompts before making changes (unless using -Force)

**Roles Assigned by the Script:**

1. **Microsoft Discovery Platform Administrator (Preview)**: Full access to Discovery Platform resources
2. **Role Based Access Control Administrator**: Manage access to Azure resources by assigning roles
3. **Managed Identity Contributor**: Create, read, update, and delete user assigned identities
4. **Managed Identity Operator**: Read and assign user assigned identities
5. **Storage Account Contributor**: Manage storage accounts
6. **Network Contributor**: Manage networks
7. **Support Request Contributor**: Create and manage support requests
8. **Microsoft Discovery Platform Contributor (Preview)**: Contribute to Discovery Platform resources
9. **Storage Blob Data Contributor**: Read, write, and delete Azure Storage containers and blobs
10. **Cognitive Services Contributor**: Create, read, update, delete and manage keys of Cognitive Services
11. **AcrPush**: Push artifacts to Azure Container Registry
12. **Resource Group Contributor**: Manage everything except access to resource groups

**Advanced Usage Examples:**

```powershell
# Assign roles to multiple users in a batch
$users = @("user1@contoso.com", "user2@contoso.com", "user3@contoso.com")
foreach ($user in $users) {
    pwsh role-assignments.ps1 -UserPrincipalName $user -Force
}

# Assign roles to a service principal with specific resource group scope
pwsh role-assignments.ps1 `
    -ServicePrincipalName "sp-discovery-dev" `
    -ResourceGroupName "rg-discovery-dev" `
    -Scope "ResourceGroup" `
    -SubscriptionId "12345678-1234-1234-1234-123456789012"

# Preview what would be assigned for a user across different scopes
pwsh role-assignments.ps1 -UserPrincipalName "admin@contoso.com" -DryRun
pwsh role-assignments.ps1 -UserPrincipalName "admin@contoso.com" -ResourceGroupName "rg-prod" -Scope "ResourceGroup" -DryRun
```

**Script Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `-UserPrincipalName` | String | No* | User email address (e.g., `user@domain.com`) |
| `-ObjectId` | String | No* | Object ID of user or service principal |
| `-ServicePrincipalName` | String | No* | Service principal name or application ID |
| `-SubscriptionId` | String | No | Target subscription ID (uses current if not specified) |
| `-ResourceGroupName` | String | No | Target resource group name for RG-scoped assignments |
| `-Scope` | String | No | Assignment scope: 'Subscription' (default) or 'ResourceGroup' |
| `-DryRun` | Switch | No | Preview assignments without making changes |
| `-Force` | Switch | No | Skip confirmation prompts |
| `-Help` | Switch | No | Show detailed help and role information |

*One of UserPrincipalName, ObjectId, or ServicePrincipalName is required.

**Prerequisites for Role Assignment:**

- **Azure PowerShell Module (Az)**: Installed and imported
- **Azure Authentication**: Must be authenticated (`Connect-AzAccount`)
- **Sufficient Privileges**: User Access Administrator or Owner role required
- **PowerShell 5.1+**: Windows or PowerShell 7+ for cross-platform support

## Docker Environment Setup

### Cross-Platform PowerShell Script

The **`docker-setup-automation.ps1`** script provides comprehensive Docker environment setup for Mac, Windows, and Linux:

```powershell
# Run with default settings (interactive prompts)
pwsh docker-setup-automation.ps1

# Run in test-only mode (no changes, just validation)
pwsh docker-setup-automation.ps1 -TestOnly

# Skip installation steps (only configure existing Docker)
pwsh docker-setup-automation.ps1 -SkipInstall

# Skip VS Code settings update
pwsh docker-setup-automation.ps1 -SkipVSCodeSettings

# Enable verbose output
pwsh docker-setup-automation.ps1 -Verbose
```

**Features:**

- **Cross-platform**: Works on macOS, Windows, and Linux
- **Automated installation**: Uses Homebrew (Mac), winget/Chocolatey (Windows), or apt/yum (Linux)
- **Shell profile updates**: Configures bash, zsh, and PowerShell profiles
- **VS Code integration**: Updates terminal settings for Docker PATH
- **Comprehensive testing**: Validates Docker in all environments
- **No prerequisites**: Handles PowerShell installation if needed

### What the Script Does

The Docker setup script:

1. **Check Docker Installation**: Verify Docker Desktop/Engine is installed
2. **Install Docker** (if missing): Use appropriate package manager for the OS
3. **Start Docker Desktop**: Launch and wait for daemon to be ready
4. **Update Shell Profiles**: Configure PATH in bash, zsh, and PowerShell profiles
5. **Configure VS Code**: Update terminal settings for Docker PATH
6. **Test Environments**: Validate Docker works in all terminal types
7. **Provide Summary**: Show status and next steps

### After Running Docker Setup

1. **Restart VS Code** to pick up new terminal settings
2. **Ensure Docker Desktop is running** before using Docker commands
3. **Test Docker** in VS Code terminals:
   - PowerShell: `Test-Docker`
   - Bash/Zsh: `docker --version`

## Definition Content Creator

A Python utility that converts YAML definition files to JSON format. This tool is designed to work with Microsoft Discovery platform definition files and can output JSON in two formats:

- **ARM Template JSON String**: Escaped JSON string suitable for embedding in Azure Resource Manager (ARM) templates
- **Formatted JSON**: Properly formatted JSON for portal experiences and agent file generation

## Quick Start (Recommended)

### Automated Tool Processing

The fastest way to update all tool definitions and generate JSON files:

```powershell
# Navigate to the utils directory
cd discovery-hackathon\utils

# Run the PowerShell script with your ACR name
.\update-tools-definition-and-generate-json.ps1 your-acr-name

# Example:
.\update-tools-definition-and-generate-json.ps1 discoveryacr01
```

This script will:

- **Automatically install Python3 and pip if missing** (supports macOS with Homebrew, Linux with apt/yum/dnf/pacman)
- **Automatically install PyYAML package if missing**
- Update ACR paths in all YAML files in `chemistryTools/**/1-Tool/`
- Generate corresponding JSON files
- Place them in `jsonFiles/`
- Clean up backup files automatically

**No prerequisites required** - the script handles all dependency installation automatically!

### Agent and Workflow Processing

The fastest way to convert agent and workflow YAML files to JSON format:

```powershell
# Navigate to the utils directory
cd discovery-hackathon/utils

# Run the PowerShell script to convert all agent and workflow files
./generate-agent-workflow-json.ps1

# Convert to custom output directory
./generate-agent-workflow-json.ps1 -OutputPath "./my-output"

# Force overwrite existing files
./generate-agent-workflow-json.ps1 -Force
```

This script will:

- **Automatically validate Python environment** and install PyYAML if missing
- **Process all agent YAML files** from chemistryTools, chemistryAgents, and genericAgents directories
- **Process all workflow YAML files** from chemistryWorkflow directory
- **Generate properly formatted JSON files** suitable for Microsoft Discovery platform
- **Use intelligent naming conventions** (e.g., `AgentName-agent-definition.json`, `WorkflowName-workflow-definition.json`)
- **Provide colored output** for easy progress tracking
- **Handle file conflicts** with overwrite protection

**Output Files Generated:**

- Agent definitions: `<AgentName>-agent-definition.json`
- Workflow definitions: `<WorkflowName>-workflow-definition.json`

### System Requirements

- **Windows 10/11** or **Windows Server 2016+**
- **PowerShell 5.1+** (comes with Windows)
- **Administrator privileges** may be required for Python installation

### Docker Image Building

To build and push Docker images for all chemistry tools to Azure Container Registry:

**Cross-Platform PowerShell Script:**

```powershell
# Navigate to the utils directory
cd discovery-hackathon/utils

# Run the PowerShell script (interactive mode)
./generate-docker-images-and-push-to-acr.ps1

# Or provide ACR name directly
./generate-docker-images-and-push-to-acr.ps1 -AcrName myregistry

# View help
./generate-docker-images-and-push-to-acr.ps1 -Help
```

The Docker script will:

- Automatically discover all chemistry tools with Dockerfiles
- Build Docker images for each tool
- Tag images appropriately for your ACR
- Push images to Azure Container Registry
- Clean up local images to save disk space
- Provide detailed progress and summary reports
- **Handle common ACR name formats** (automatically fixes `.azureacr.io` typos to `.azurecr.io`)
- **Robust authentication checking** using Azure CLI with timeout (prevents hanging)

**Prerequisites for Docker script:**

- **PowerShell 7+** (cross-platform): [Install PowerShell](https://docs.microsoft.com/en-us/powershell/scripting/install/installing-powershell)
- Docker installed and running
- Azure CLI installed and authenticated (`az login`)
- ACR access configured (`az acr login --name <your-acr>`)

## Manual Processing

## Installation

Ensure you have Python 3.6+ installed with the required dependencies:

```bash
pip install pyyaml
```

## Usage

### Basic Syntax

```bash
python definition-content-creator.py <yaml_file> [options]
```

### Command Line Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--output` | `-o` | Output file path. If not provided, prints to stdout | stdout |
| `--json` | `-j` | Output properly formatted JSON instead of ARM-compatible JSON string | ARM string format |
| `--help` | `-h` | Show help message and exit | - |

### Examples

#### 1. Generate ARM Template JSON String (Default)

Convert a YAML file to ARM-compatible JSON string format:

```bash
python definition-content-creator.py agent-definition/GromacsAgent.yaml
```

Output to a file:

```bash
python definition-content-creator.py agent-definition/GromacsAgent.yaml --output gromacs-arm.txt
```

#### 2. Generate Formatted JSON for Portal Experience

Convert a YAML file to properly formatted JSON for portal use:

```bash
python definition-content-creator.py agent-definition/GromacsAgent.yaml --json
```

Output to a file:

```bash
python definition-content-creator.py agent-definition/GromacsAgent.yaml --json --output gromacs-portal.json
```

#### 3. Process Workflow Files

For workflow definition files with special handling:

```bash
python definition-content-creator.py workflow-definition/ScienceWorkflow.yaml --json --output workflow.json
```

## Agent and Workflow JSON Generation

### Quick Start for Agents and Workflows

The `generate-agent-workflow-json.ps1` script provides an automated way to convert all agent and workflow YAML definition files to JSON format suitable for Microsoft Discovery platform deployment.

```powershell
# Navigate to the utils directory
cd discovery-hackathon/utils

# Convert all agent and workflow files (basic usage)
./generate-agent-workflow-json.ps1

# Advanced usage with custom output directory
./generate-agent-workflow-json.ps1 -OutputPath "../my-json-files"

# Force overwrite existing files without prompting
./generate-agent-workflow-json.ps1 -Force
```

### Supported Files

The script automatically processes these file types:

**Agent Files:**

- No agent files currently listed.

**Workflow Files:**

- No workflow files currently listed.

### Features

- **Automatic Environment Setup**: Validates Python installation and PyYAML dependency
- **Intelligent File Discovery**: Automatically finds all agent and workflow YAML files
- **Smart Naming**: Extracts actual agent/workflow names from YAML content for proper file naming
- **Special Workflow Processing**: Leverages the existing Python utility's workflow-specific logic
- **Overwrite Protection**: Prompts before overwriting existing files (unless using `-Force`)
- **Colored Output**: Easy-to-read progress indicators and status messages
- **Error Handling**: Comprehensive error reporting and recovery suggestions

### Output Structure

Generated JSON files follow Microsoft Discovery naming conventions:

```text
jsonFiles/
├── ADFTAgent-agent-definition.json
├── CorePythonAgent-agent-definition.json
├── MolPredictorAgent-agent-definition.json
├── ChemistryPlannerAgent-agent-definition.json
├── ChemistryRouterAgent-agent-definition.json
├── SummarizerAgent-agent-definition.json
└── MolecularScienceWorkflow-workflow-definition.json
```

### Prerequisites

- **PowerShell 5.1+** (Windows) or **PowerShell 7+** (cross-platform)
- **Python 3.6+** (automatically validated and PyYAML installed if needed)
- Access to the discovery-hackathon repository structure

## Agent Name Management

### Agent Name Updater Tool

The `update-agent-names.py` script allows you to systematically update agent names across all YAML files while maintaining consistency between agent definitions and workflow references.

#### Prerequisites

Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

**Important**: The script should be run from the project root directory (`discovery-hackathon/`) to properly discover all YAML files, or use the `--base-path` option to specify the correct path.

#### Usage Examples

**Interactive Mode** (Recommended for first-time users):

```bash
# Run from the project root directory
cd discovery-hackathon
python utils/update-agent-names.py --interactive
```

**Using Command Line Mappings**:

```bash
# Run from the project root directory
cd discovery-hackathon
python utils/update-agent-names.py --mapping "CorePythonAgent:CorePythonAgent01,ADFTAgent:ADFTAgent01"
```

**Using Configuration File**:

```bash
# Run from the project root directory (recommended)
cd discovery-hackathon
python utils/update-agent-names.py --config utils/agent_name_mappings.json

# Or specify the base path explicitly if running from utils directory
python update-agent-names.py --config agent_name_mappings.json --base-path ..
```

**Create Sample Configuration**:

```bash
# Run from the project root directory
cd discovery-hackathon
python utils/update-agent-names.py --create-sample-config
```

**Dry Run (Preview Changes)**:

```bash
# Run from the project root directory
cd discovery-hackathon
python utils/update-agent-names.py --config utils/agent_name_mappings.json --dry-run
```

#### What Gets Updated

The script updates:

- Agent names in agent definition files (`agent.name` field)
- Agent references in workflow files (e.g., `agent: AgentName`)
- Text references in instructions and descriptions
- Any other contextual references to agent names

#### Configuration File Format

The `agent_name_mappings.json` file uses simple key-value pairs:

```json
{
  "CorePythonAgent": "CorePythonAgent01",
  "ADFTAgent": "ADFTAgent01",
  "MolPredictorAgent": "MolPredictorAgent01",
  "ChemistryPlannerAgent": "ChemistryPlannerAgent01",
  "ChemistryRouterAgent": "ChemistryRouterAgent01",
  "SummarizerAgent": "SummarizerAgent01"
}
```

#### Safety Features

- **Automatic Backups**: Creates timestamped backups before changes
- **Validation**: Checks for conflicts and invalid mappings
- **Dry Run Mode**: Preview changes before applying
- **Logging**: Detailed logging of all operations
