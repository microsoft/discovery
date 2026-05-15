# Microsoft Discovery Utilities

This directory contains a comprehensive collection of utilities for Microsoft Discovery platform operations, including validation, deployment, content creation, and VS Code extension tools. All utilities are designed to streamline the development, deployment, and management of Microsoft Discovery resources.

## Overview of Available Utilities

| Utility | Location | Purpose |
|---------|----------|---------|
| **Discovery Onboarding Validation Script** | `validation-script/` | Validates Azure subscription readiness for Discovery deployment |
| **Infrastructure Deployment Scripts** | `validate-and-deploy-infra-scripts/` | Automates validation and deployment of Discovery infrastructure |
| **Definition Content Creator** | `definition-content-creator.py` | Converts YAML definition files to JSON format |
| **Supercomputer CLI** | `supercomputer-cli/` | Toolkit provides basic access to the Discovery Supercomputer API for submitting and running jobs directly on Supercomputer |
| **Agent Workbench** | `agent-workbench/` | Web-based interface and MCP server for creating, testing, and deploying AI agents to Azure Discovery. Supports chat-based testing, job submission, and integration with VS Code/GitHub Copilot |

---

## 1. Discovery Onboarding Validation Script

**Location**: `validation-script/validate_discovery_onboarding.sh`

A comprehensive validation script that verifies your Azure subscription and user account are ready to deploy Microsoft Discovery infrastructure resources.

### Prerequisite: Microsoft Discovery Subscription Onboarding

Before running the validation script, ensure your Azure subscription is onboarded to Microsoft Discovery. Contact your Microsoft account representative or administrator to request onboarding for your Azure subscription.

### Features

- **Azure Login & Subscription Selection**: Confirms you are logged in and using the correct subscription.
- **Region & User Principal Input**: Prompts for your Azure region and user principal name (email).
- **Resource Provider Registration**: Checks if all required Azure resource providers are registered, and can register missing ones if you have permission.
- **Role Assignment Verification**: Ensures your account has all necessary roles (e.g., Microsoft Discovery Platform Administrator, Storage Account Contributor, Storage Blob Data Contributor), and can assign missing roles if allowed.
- **AI Model Quota Check**: Verifies quota for key AI models (GPT-4o, text-embedding-3-small) in your region, warning if quota is insufficient.
- **vCPU Quota Validation**: Checks available vCPU quota for Standard_D4s_v6 SKU to ensure adequate compute resources.
- **NetApp Quota Check**: Validates NetApp account pool sizes and available quota in your region, warning if below minimum requirements.
- **Issue Summary & Remediation**: Summarizes any issues found and offers to remediate (register providers, assign roles) if you have the necessary permissions.

### Usage

1. Open your terminal. For Windows users, use WSL or Git bash.
2. Navigate to the utils directory and run the script:

    ```bash
    cd discovery/utils
    ./validation-script/validate_discovery_onboarding.sh
    ```

3. Follow the prompts to complete the validation.
4. Address any issues reported before deploying Discovery resources.

**Note:** This document provides guidance on resolving issues that may require elevated permissions, such as Resource Provider (RP) registration or assigning necessary roles. If you plan to onboard new tools, ensure you have the `AcrPush` RBAC role assigned to your account. Contact your administrator if you need assistance with permissions or role assignments.

> **Tip:** Running this script before onboarding helps ensure your Azure environment is properly configured for Microsoft Discovery deployments.

---

## 2. Infrastructure Deployment Scripts

**Location**: `validate-and-deploy-infra-scripts/`

A complete solution for validating prerequisites and deploying Microsoft Discovery infrastructure using Bicep templates. The main deployment script automatically handles both validation and deployment processes.

### Key Scripts

- **`deploy_discovery_infra.sh`**: Main deployment script that handles validation and infrastructure deployment
- **`validate.sh`**: Standalone validation script (automatically called by deployment script)
- **`Deployment Templates/`**: Directory containing Bicep templates and modules

### Prerequisites

- **Azure CLI** installed and logged in
- **Azure Bicep** installed
- **jq** utility for JSON processing
- Owner or User Access Administrator role in the subscription (for automatic role assignment)

### Usage

Navigate to the validate-and-deploy-infra-scripts directory first:

```bash
cd discovery/utils/validate-and-deploy-infra-scripts
./deploy_discovery_infra.sh [options]
```

**Key Options:**

- `-s, --subscription-id ID`: Azure subscription ID for deployment
- `-g, --resource-group NAME`: Resource group name for deployment
- `-l, --location LOCATION`: Azure region for deployment (e.g., 'eastus')
- `-c, --scope SCOPE`: Deployment scope: 'Subscription' or 'ResourceGroup' (default: ResourceGroup)
- `-p, --prefix TEXT`: Prefix for resource names (default: 'd' + Date(MMDD))
- `-x, --suffix TEXT`: Suffix for resource names (default: current Hour and Minute)
- `-u, --user-id EMAIL`: User principal name (email) for validation
- `-d, --dry-run`: Preview commands without executing them
- `-k, --skip-validation`: Skip validation checks and proceed directly to deployment

### Example Commands

**Basic deployment:**
```bash
cd discovery/utils/validate-and-deploy-infra-scripts
./deploy_discovery_infra.sh -g "rg-discovery" -l "eastus" -p "test" -x "001" -u "user@example.com"
```

**Deployment with custom subscription:**
```bash
cd discovery/utils/validate-and-deploy-infra-scripts
./deploy_discovery_infra.sh -s "00000000-0000-0000-0000-000000000000" -g "rg-discovery" -l "eastus2" -p "test" -x "001" -u "user@example.com"
```

**Dry run (preview only):**
```bash
cd discovery/utils/validate-and-deploy-infra-scripts
./deploy_discovery_infra.sh -g "rg-discovery" -l "eastus" -d
```

### Deployment Templates

The `Deployment Templates` directory contains modular Bicep templates:

- `main.bicep`: Main deployment template
- `modules/`: Modular templates for specific resource types
  - `datacontainer.bicep`: Data container resources
  - `discovery-storage.bicep`: Discovery storage resources
  - `discovery.bicep`: Core Discovery resources
  - `identity.bicep`: Managed identity resources
  - `identity_role_assignments.bicep`: Role assignments for identities
  - `roles.bicep`: Custom role definitions
  - `storage.bicep`: Storage account resources
  - `supercomputer.bicep`: Supercomputer resources
  - `vnet.bicep`: Virtual network resources

---

## 3. Definition Content Creator

**Location**: `definition-content-creator.py`

A Python utility that converts YAML definition files to JSON format. This tool is designed to work with Microsoft Discovery platform definition files and can output JSON in two formats:

- **ARM Template JSON String**: Escaped JSON string suitable for embedding in Azure Resource Manager (ARM) templates
- **Formatted JSON**: Properly formatted JSON for portal experiences and agent file generation

### Installation

Ensure you have Python 3.6+ installed with the required dependencies:

```bash
pip install pyyaml
```

### Usage

#### Basic Syntax

Navigate to the utils directory first:

```bash
cd discovery/utils
python definition-content-creator.py <yaml_file> [options]
```

#### Command Line Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--output` | `-o` | Output file path. If not provided, prints to stdout | stdout |
| `--json` | `-j` | Output properly formatted JSON instead of ARM-compatible JSON string | ARM string format |
| `--help` | `-h` | Show help message and exit | - |

#### Examples

**Generate ARM Template JSON String (Default):**
```bash
cd discovery/utils
python definition-content-creator.py agent-definition/GromacsAgent.yaml
```

**Generate Formatted JSON for Portal Experience:**
```bash
cd discovery/utils
python definition-content-creator.py agent-definition/GromacsAgent.yaml --json
```

**Output to File:**
```bash
cd discovery/utils
python definition-content-creator.py agent-definition/GromacsAgent.yaml --json --output gromacs-portal.json
```

### Supported Input File Types

- **Agent Definition Files**: Standard YAML to JSON conversion
- **Model Definition Files**: Standard YAML to JSON conversion  
- **Tool Definition Files**: Standard YAML to JSON conversion
- **Workflow Definition Files**: Special processing with agent name handling

### Dependencies

- Python 3.6+
- PyYAML (`pip install pyyaml`)

---

## 4. Agent Workbench

**Location**: `agent-workbench/`

A comprehensive web-based workbench for creating, testing, and deploying AI agents to Azure Discovery. The workbench provides both a browser-based interface and an MCP (Model Context Protocol) server for integration with VS Code and GitHub Copilot.

### Key Features

#### Browser Interface (Web App)
- **Agent Development**: Create and configure tool agents, knowledge base agents, and entry/workflow agents
- **Chat-Based Testing**: Test agents interactively with a chat interface powered by Azure OpenAI
- **Job Submission**: Submit computational jobs to the Discovery Supercomputer directly from the browser
- **Results Viewer**: View and download job outputs with specialized viewers for molecular structures (3Dmol, NGL), trajectories, and images
- **Agent Publishing**: Deploy agents and tools to Azure Discovery workspaces

#### MCP Server Integration
- **VS Code Integration**: Drive Discovery workflows directly from VS Code or GitHub Copilot chat
- **Investigation Management**: Create and organize computational workflows with structured file organization
- **Complete Job Lifecycle**: Upload inputs, submit jobs, stream logs, retrieve results, and clean up storage
- **Profile Management**: Switch between different Discovery configurations and environments
- **Agent Discovery**: List and explore available computational agents and their capabilities

### Installation

#### Prerequisites

| Requirement | Purpose |
|-------------|---------|
| **Python 3.9+** | Core runtime (3.12+ recommended for MCP server) |
| **Docker Desktop** | Container runtime for agent testing |
| **Azure OpenAI endpoint** | AI-powered agent generation and chat |
| **Discovery workspace** | Publishing agents and running Supercomputer jobs |

#### Required Azure RBAC Roles

| Role | Purpose |
|------|---------|
| **Microsoft Discovery Platform Contributor (Preview)** | Manage Discovery resources |
| **Contributor** | General Azure resource management |
| **AcrPush** | Push container images to Azure Container Registry |
| **Cognitive Services OpenAI User** | Call Azure OpenAI APIs (if using Entra ID auth) |

### Quick Start

#### Web Application

```bash
# Windows
cd discovery/utils/agent-workbench
start_web_app.bat

# Linux / macOS
cd discovery/utils/agent-workbench
./start_web_app.sh
```

Open **http://localhost:8050** and configure your Azure settings.

#### MCP Server (VS Code / GitHub Copilot)

```bash
cd discovery/utils/agent-workbench/mcp-server
python setup_github_copilot.py
```

The setup script will auto-detect your environment (local, Codespaces, remote SSH) and configure the appropriate transport mechanism.

### Configuration

Configure the workbench through the **Settings Dialog** in the web interface or by editing `discovery_config.json` directly.

Key configuration sections:
- **Azure Settings**: Tenant ID, Subscription ID, Resource Group, Location, ACR Name
- **Azure OpenAI**: Endpoint URL, Deployment Name, API Version, Authentication method
- **Supercomputer**: Discovery Supercomputer name, Workspace, Project, Data Container, Storage accounts
- **Conversation Settings**: Max Tokens, Temperature, Max Retries

### Usage Examples

#### Web Interface
1. Launch the web app and configure Azure settings
2. Browse available agents or create new ones
3. Test agents via the chat interface
4. Submit jobs to the Discovery Supercomputer
5. View and download results

#### MCP Server (via GitHub Copilot)
```
"What agents are available?"
"List the available computational tools"
"Calculate molecular weight of CCO and generate an optimized conformer"
"Check the status of my last job"
```

### File Organization

```
agent-workbench/
├── doc/                    # Documentation and setup guides
├── extensions/             # Result viewer extensions (3Dmol, NGL, trajectory)
├── mcp-server/            # MCP server for VS Code/Copilot integration
├── prompts/               # System prompts for agent behavior
├── start_web_app.bat      # Windows startup script
├── start_web_app.sh       # Linux/macOS startup script
└── discovery_config.json  # Configuration file
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| **Port 8050 in use** | Kill the existing process or change the port |
| **Docker not found** | Install Docker Desktop and ensure it's running |
| **Authentication fails** | Verify RBAC roles are assigned (allow 1-5 min for propagation) |
| **MCP server not appearing** | Reload VS Code and re-run `setup_github_copilot.py` |

For detailed setup instructions, see [Setup Guide](agent-workbench/doc/README_SetupGuide.md).

---

## Getting Started

To begin using the Microsoft Discovery utilities:

1. **For Initial Setup**: Start with the Discovery Onboarding Validation Script to verify your Azure environment
2. **For Infrastructure Deployment**: Use the Infrastructure Deployment Scripts to deploy Discovery resources
3. **For Content Creation**: Use the Definition Content Creator to convert YAML definitions to JSON
4. **For Agent Development & Testing**: Use the Agent Workbench for interactive agent creation, chat-based testing, and job submission to the Discovery Supercomputer

Each utility is designed to work independently or as part of a complete Discovery development and deployment workflow.