# Microsoft Discovery - Build and Deploy Tools and Agents

## Overview

This comprehensive utility provides **end-to-end automation** for deploying Microsoft Discovery tools and agents. It handles the complete flow from container images to deployed control plane resources:

### Core Capabilities

1. **🐳 Container Image Building** (Optional)
   - **Local Build** - Uses Docker on your machine (faster, requires Docker installed)
   - **Remote Build** - Uses Azure Container Registry Tasks (no Docker needed, builds in cloud)
   - **Skip Docker entirely** - Use pre-built images already in ACR

2. **📝 YAML to ARM Template Conversion**
   - Automatically converts tool definition YAML files to ARM templates
   - Automatically converts agent definition YAML files to ARM templates
   - Generates combined templates with both tool and agent resources
   - Updates ACR image references from your YAML definitions

3. **☁️ Azure Resource Deployment**
   - Deploys Microsoft Discovery Tool control plane resources
   - Deploys Microsoft Discovery Agent control plane resources
   - Automatic deletion and recreation of existing resources
      - The script will not handle the scenario where the deletion of tool and agents could not happen due to cross dependency from project resource
      - The script will not handle if the tool or agent exists with similar name in some other region within same Resource Group
   - Smart dependency handling (agents → tools)
   - Split deployment strategy for reliability

### What This Utility Does

✅ **Builds Docker images** for your tools (local or Azure ACR)  
✅ **Converts YAML definitions** to ARM templates (JSON)  
✅ **Deploys Discovery Tool resources** to Azure control plane  
✅ **Deploys Discovery Agent resources** to Azure control plane  
✅ **Manages resource lifecycle** (create, update, delete)  
✅ **Cross-platform support** (Windows, macOS, Linux)

### What You Don't Need to Do

❌ No manual Docker image building required  
❌ No manual YAML to JSON conversion  
❌ No manual ARM template creation  
❌ No manual resource deployment  
❌ No manual dependency management

**→ [See Prerequisites](#prerequisites) to get started**

---

## Tool and Agent Definition File Naming Conventions

The script uses **case-insensitive pattern matching** to discover tool and agent definition files. This means `Tool`, `TOOL`, and `tool` are all acceptable.

### 🔧 Tool Definition Files

Tool definition files support **multiple naming patterns** (any of these will work):

- **Recommended**: `*tool-definition.yaml`
  - Examples: `PubMed-tool-definition.yaml`, `rdkit-tool-definition.yaml`
- **Alternate patterns**:
  - `*tool_definition.yaml` (underscore separator)
    - Examples: `PubMed-tool_definition.yaml`, `rdkit_tool_definition.yaml`
  - `*tools.yaml` (plural form)
    - Examples: `PubMedtools.yaml`, `rdkittools.yaml`
  - `*tool.yaml` (short form)
    - Examples: `PubMedtool.yaml`, `rdkittool.yaml`, `RetroChimera-Tool.yaml`

**Case-Insensitive**: `Tool`, `TOOL`, and `tool` in filenames all work

**Location**: Place in `6-solutions/tools-and-models/<tool-name>/` directory

**Required Fields**:
```yaml
version: "1.0.0"
infra:
  - image:
      acr: "placeholder.azurecr.io/tool-name"  # Will be auto-updated
    compute:
      cpu: "1"
      memory: "2Gi"
# ... additional tool configuration
```

### 🤖 Agent Definition Files

Agent definition files support **multiple naming patterns** (any of these will work):

- **Recommended**: `*agent-definition.yaml`
  - Examples: `PubMed-agent-definition.yaml`, `rdkit-agent-definition.yaml`
- **Alternate patterns**:
  - `*agent_definition.yaml` (underscore separator)
    - Examples: `PubMed-agent_definition.yaml`, `rdkit_agent_definition.yaml`
  - `*agents.yaml` (plural form)
    - Examples: `PubMedagents.yaml`, `rdkitagents.yaml`
  - `*agent.yaml` (short form)
    - Examples: `PubMedagent.yaml`, `rdkitagent.yaml`, `RDKitAgent.yaml`, `RetroChimera-Agent.yaml`

**Case-Insensitive**: `Agent`, `AGENT`, and `agent` in filenames all work

**Location**: Place in the same directory as the tool definition: `6-solutions/tools-and-models/<tool-name>/`

**Required Structure**:
```yaml
version: "1.0.0"
agent:
  name: "Agent Name"
  description: "Agent description"
  model: "gpt-4o"
  instructions: "Detailed instructions for the agent"
  temperature: 0
  top_p: 0
  response_format: "auto"
extension:
  events: []
  inputs: []
  outputs: []
  system_prompts: []
```

**⚠️ Critical**: The agent fields **must** be nested under an `agent` property, and the `extension` property must be at the root level (not inside `agent`).

### 📂 Directory Structure Example

```
6-solutions/tools-and-models/
├── pubmed/
│   ├── Dockerfile                      # Optional: For building container image
│   ├── PubMed-tool-definition.yaml     # Tool definition (recommended pattern)
│   ├── PubMed-agent-definition.yaml    # Agent definition (recommended pattern)
│   └── [tool source code files]
├── rdkit-tool/
│   ├── Dockerfile                      # Optional
│   ├── rdkit-tool-definition.yaml      # Tool definition (recommended pattern)
│   ├── RDKitAgent.yaml                 # Agent definition (alternate pattern: *agent.yaml)
│   └── [tool source code files]
├── RetroChimera/
│   ├── Dockerfile                      # Optional
│   ├── RetroChimera-Tool.yaml          # Tool definition (alternate pattern: *tool.yaml)
│   ├── RetroChimera-Agent.yaml         # Agent definition (alternate pattern: *agent.yaml)
│   └── [tool source code files]
├── gromacs/
│   ├── Dockerfile                      # Optional
│   ├── gromacs-tool-definition.yaml    # Tool definition (recommended pattern)
│   ├── gromacsAgent.yaml               # Agent definition (alternate pattern: *agent.yaml)
│   └── [tool source code files]
└── chembl/
    ├── Dockerfile                      # Optional
    ├── ChEMBL-tool-definition.yaml     # Tool definition (case-insensitive)
    └── [tool source code files]        # No agent - tool only
```

**Key Points:**
- Tool and agent files can use **any supported naming pattern**
- **Case-insensitive** matching works for all patterns
- The `*` wildcard matches any prefix (including hyphens, underscores, etc.)
- Agent definitions are **optional** - tools can exist without agents

---

## Important: No Docker Pre-requisites Required

**You do NOT need to build Docker images before running this utility.**

The script provides **two flexible workflows**:

### Option 1: Full Build + Deploy (Recommended for New Tools)
1. Builds Docker images (local or ACR)
2. Pushes images to Azure Container Registry
3. Generates ARM templates with correct image references
4. Deploys Tool and Agent resources

```bash
python3 build_tools.py --deploy
# Select build mode, tools to build, and confirm deployment
```

### Option 2: Generate Templates Only (No Build or Deploy)
1. Convert YAML definitions to ARM templates
2. Manual deployment later

```bash
python3 build_tools.py
# Select tools
# Generate templates: yes
# Deploy templates: no
```

**Key Point**: The script is intelligent enough to:
- ✅ Detect if images already exist in ACR
- ✅ Skip building if images are already available
- ✅ Generate templates with correct ACR image references
- ✅ Deploy resources using existing container images

---

## Solution Options

### Option 1: Local Build (Docker)

- ✅ **Faster builds** - Uses your local compute resources
- ✅ **Works offline** - No Azure connection needed for building
- ✅ **Optional ACR push** - Can push to ACR or keep images local
- ✅ **ARM template generation** - Converts YAML definitions to ARM templates
- ✅ **Resource deployment** - Deploy Tool and Agent resources to Azure
- ⚠️ **Requires Docker** - Docker Desktop or Engine must be installed and running

### Option 2: Remote Build (ACR Tasks)

- ✅ **No local Docker needed** - Builds happen in Azure cloud
- ✅ **Works on any platform** - Windows, macOS, Linux
- ✅ **Automatic ACR push** - Images pushed directly to your registry
- ✅ **ARM template generation** - Converts YAML definitions to ARM templates
- ✅ **Resource deployment** - Deploy Tool and Agent resources to Azure
- ⚠️ **Requires Azure access** - Needs Azure CLI and ACR permissions

### Option 3: Template Generation Only (No Image Building)

- ✅ **Use existing images** - Works with pre-built images in ACR
- ✅ **YAML to ARM conversion** - Converts definition files to deployment templates
- ✅ **Resource deployment** - Deploy Tool and Agent resources to Azure
- ✅ **Fastest option** - Skip image building entirely
- ⚠️ **Images must exist** - Container images must already be in ACR

---

## Prerequisites

### Always Required

1. **Python 3.7 or higher**
   ```bash
   python3 --version
   ```

2. **PyYAML library** (for YAML to ARM template conversion)
   ```bash
   pip install pyyaml
   # Or install all dependencies
   pip install -r requirements.txt
   ```

### For Image Building (Optional)

**Note**: Skip this section if you're using pre-existing images in ACR or only generating templates.

2. **Docker Desktop or Docker Engine** (for local builds only)
   - **Windows**: [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)
   - **Linux**: [Docker Engine](https://docs.docker.com/engine/install/)
   - **macOS**: [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
   
   Verify installation:
   ```bash
   docker --version
   docker ps  # Should show running containers or empty list
   ```

### For Remote Builds or Resource Deployment

3. **Azure CLI** installed and authenticated
   ```bash
   # Install Azure CLI
   # macOS: brew install azure-cli
   # Windows: Download from https://aka.ms/installazurecliwindows  
   # Linux: https://docs.microsoft.com/cli/azure/install-azure-cli
   
   # Login to Azure
   az login
   ```

4. **Azure Permissions**
   
   **For Image Building (ACR operations):**

   **On the Azure Container Registry (ACR):**
   - **`AcrPush`** role (or higher: `Contributor`, `Owner`)
   - This allows the script to:
     - Trigger ACR Tasks for remote image builds (`az acr build`)
     - Push built images to the registry
     - Verify ACR exists and retrieve details (`az acr show`)
   
   **For Resource Deployment (Discovery control plane):**
   
   **On the Resource Group:**
   - **`Contributor`** role (or higher: `Owner`)
   - Required to:
     - Create/update/delete Discovery Tool resources (`Microsoft.Discovery/tools`)
     - Create/update/delete Discovery Agent resources (`Microsoft.Discovery/agents`)
     - Deploy ARM templates
     - Manage resource lifecycle
   
   **On the Subscription:**
   - Basic read access (implicit with Resource Group contributor)
   
   **To assign the required permissions:**
   ```bash
   # Assign AcrPush role to a user on the ACR (for image building)
   az role assignment create \
     --assignee <user-email-or-object-id> \
     --role "AcrPush" \
     --scope /subscriptions/<subscription-id>/resourceGroups/<rg-name>/providers/Microsoft.ContainerRegistry/registries/<acr-name>
   
   # Assign Contributor role on Resource Group (for resource deployment)
   az role assignment create \
     --assignee <user-email-or-object-id> \
     --role "Contributor" \
     --scope /subscriptions/<subscription-id>/resourceGroups/<rg-name>
   
   # Verify role assignments
   az role assignment list \
     --assignee <user-email> \
     --scope /subscriptions/<subscription-id>/resourceGroups/<rg-name>
   ```
   
   **Notes:**
   - For **template generation only** (no building or deployment), no Azure permissions are needed
   - For **local-only builds** (not pushing to ACR), no ACR permissions are needed
   - For **deployment with --deploy flag**, you need both ACR and Resource Group permissions

### Optional Environment Variables

Set these to skip interactive prompts:

```bash
export ACR_NAME=<your-acr-name>
export AZURE_RESOURCE_GROUP=<your-resource-group>
export AZURE_SUBSCRIPTION_ID=<your-subscription-id>
```

Or create a `.env` file in the `utils/tool-onboarding` directory:

```bash
cp .env.example .env
# Edit .env with your values
```

---

## Quick Start

### Basic Workflow

The typical workflow with this utility is:

1. **Prepare Tool/Agent Definitions** (one-time setup)
   - Create `*-tool-definition.yaml` in your tool directory
   - Optionally create `*-agent-definition.yaml` or `*Agent.yaml`
   - Ensure naming conventions are followed (see section above)

2. **Run the Build Script**
   ```bash
   cd utils/build-and-deploy-tool-agents
   python3 build_tools.py --deploy
   ```

3. **Follow Interactive Prompts**
   - Choose build mode (local/remote/skip)
   - Select tools to process
   - Confirm ARM template generation
   - Confirm deployment to Azure

4. **Verify Deployment**
   - Check deployed resources in Azure portal
   - Or use Azure CLI commands (see "Verifying Deployed Resources")

### Detailed Steps

### 1. Navigate to the build-and-deploy-tool-agents directory

```bash
cd utils/build-and-deploy-tool-agents
```

### 2. Run the script with --deploy flag

```bash
python3 build_tools.py --deploy
```

### 3. Follow the interactive prompts

The script will:
1. Detect your platform (macOS/Windows/Linux)
2. Check if Docker is available (for image building)
3. Let you choose build mode (Local/Remote/Skip) or generate templates only
4. Discover all available tools with definition YAML files
5. Ask you to select which tools to process
6. Request ACR details if needed for images
7. Verify prerequisites (Docker, Azure CLI, or neither)
8. Build each selected tool (if applicable)
9. **Convert YAML definitions to ARM templates (JSON)**
10. **Deploy Tool and Agent resources to Azure**
11. Display a summary of successful and failed operations

---

## Usage Examples

### Example 1: Local Build (Keep Images Local)

```bash
$ python3 build_tools.py

🚀 Microsoft Discovery - Tool Image Builder
================================================================================

Platform: Darwin

🔍 Checking Docker availability...
✅ Docker is available and running
   Platform: Darwin

🔧 Build Mode Selection
================================================================================

Choose build mode:
  1. Local build (using Docker on this machine)
  2. Remote build (using Azure Container Registry Tasks)
  q. Quit

Your choice (1/2/q): 1
✅ Selected: Local build

📦 Discovered Tools with Dockerfiles
[... tools list ...]

Your selection: 13

📤 Push to Azure Container Registry?
================================================================================

Push images to ACR after building? (yes/no): no

📋 Build Summary:
   Tools to build: 1
   Build mode: Local (Docker)
   Images will be stored locally only

Proceed with builds? (yes/no): yes

[1/1]
================================================================================
🏗️  Building: rdkit-tool
================================================================================
Context: 6-solutions/tools-and-models/rdkit-tool
Dockerfile: 6-solutions/tools-and-models/rdkit-tool/Dockerfile
Image: rdkit-tool:latest
Build mode: Local Docker

🚀 Starting local build...
[Docker build output...]
✅ Successfully built: rdkit-tool:latest
```

### Example 2: Local Build with ACR Push

```bash
Your choice (1/2/q): 1
✅ Selected: Local build

[... tool selection ...]

Push images to ACR after building? (yes/no): yes

🔍 Verifying Azure CLI...
✅ Authenticated as: user@company.com

🔧 Azure Container Registry Configuration
ACR Name: mydiscoveryacr (from environment)
Resource Group: discovery-rg (from environment)

🔍 Verifying access to ACR: mydiscoveryacr...
✅ ACR found: mydiscoveryacr.azurecr.io

📋 Build Summary:
   Tools to build: 1
   Build mode: Local (Docker)
   Target ACR: mydiscoveryacr

[Build happens locally, then pushes to ACR...]
✅ Successfully built: mydiscoveryacr.azurecr.io/rdkit-tool:latest
📤 Pushing image to ACR...
✅ Successfully pushed: mydiscoveryacr.azurecr.io/rdkit-tool:latest
```

### Example 3: Remote Build (No Docker Required)

```bash
$ python3 build_tools.py

🚀 Microsoft Discovery - Tool Image Builder
================================================================================

🔍 Verifying Azure CLI...
✅ Authenticated as: user@company.com
✅ Subscription: My Subscription

📦 Discovered Tools with Dockerfiles
================================================================================

1. bindingdb
   Path: 6-solutions/tools-and-models/bindingdb
   Dockerfile: 6-solutions/tools-and-models/bindingdb/Dockerfile

2. chembl
   Path: 6-solutions/tools-and-models/chembl
   Dockerfile: 6-solutions/tools-and-models/chembl/Dockerfile

[... more tools ...]

Select tools to build:
  - Enter tool numbers separated by commas (e.g., 1,3,5)
  - Enter 'all' to build all tools
  - Enter 'q' to quit

Your selection: all
```

### Example 2: Build Specific Tools

```bash
Your selection: 1,5,13

✅ Selected 3 tool(s)

🔧 Azure Container Registry Configuration
================================================================================

Enter ACR name: mydiscoveryacr
Enter Resource Group: discovery-rg
Enter Subscription ID (optional, press Enter to use default): 

🔍 Verifying access to ACR: mydiscoveryacr...
✅ ACR found: mydiscoveryacr.azurecr.io
✅ Location: eastus

Proceed with remote builds? (yes/no): yes
```

### Example 3: Remote Build (No Docker Required)

```bash
$ python3 build_tools.py

Platform: Darwin

🔍 Checking Docker availability...
❌ Docker not found

🔧 Build Mode Selection
⚠️  Docker is not available on this machine.
✅ Will use remote build mode (Azure Container Registry Tasks)

🔍 Verifying Azure CLI...
✅ Authenticated as: user@company.com
✅ Subscription: My Subscription

📦 Discovered Tools with Dockerfiles
[... all 13 tools listed ...]

Your selection: all
✅ Selected all 13 tools

🔧 Azure Container Registry Configuration
Enter ACR name: mydiscoveryacr
Enter Resource Group: discovery-rg

🔍 Verifying access to ACR: mydiscoveryacr...
✅ ACR found: mydiscoveryacr.azurecr.io
✅ Location: eastus

📋 Build Summary:
   Tools to build: 13
   Build mode: Remote (ACR Tasks)
   Target ACR: mydiscoveryacr

Proceed with builds? (yes/no): yes

[1/13]
🏗️  Building: bindingdb
🚀 Starting remote build (this may take several minutes)...
[Azure ACR build output...]
✅ Successfully built and pushed: mydiscoveryacr.azurecr.io/bindingdb:latest

[... continues for all tools ...]
```

### Example 4: Using Environment Variables (Any Mode)

```bash
export ACR_NAME="mydiscoveryacr"
export AZURE_RESOURCE_GROUP="discovery-rg"
export AZURE_SUBSCRIPTION_ID="12345678-1234-1234-1234-123456789012"

python3 build_tools.py
# Script will use the environment variables automatically
```

### Example 5: Complete End-to-End Deployment (Recommended)

This example shows the complete workflow: building images, converting YAML to ARM templates, and deploying Discovery control plane resources.

**Prerequisites:**
- PyYAML installed: `pip install pyyaml`
- Tool and Agent definition YAML files in tool directories (see naming conventions above)
- Azure CLI authenticated with Contributor role on resource group
- ACR accessible with AcrPush role (for pushing images)

```bash
# Build images, generate ARM templates, and deploy resources
python3 build_tools.py --deploy

# After image building completes successfully:

📄 Generating ARM Templates and Deploying Resources
================================================================================

Generate ARM templates for successful builds? (yes/no): yes
Deploy templates to Azure? (yes/no): yes
Enter Azure location for resources (default: eastus): uksouth

🔄 Converting YAML Definitions to ARM Templates
================================================================================

Generating template for pubmed...
  ℹ Found tool definition: PubMed-tool-definition.yaml
  ℹ Found agent definition: PubMed-agent-definition.yaml
  ℹ Converting YAML to JSON ARM template format
  ✓ Combined template (tool + agent) saved: arm-templates/pubmed-template.json

Generating template for rdkit-tool...
  ℹ Found tool definition: rdkit-tool-definition.yaml
  ℹ Found agent definition: RDKitAgent.yaml
  ℹ Converting YAML to JSON ARM template format
  ✓ Combined template (tool + agent) saved: arm-templates/rdkit-tool-template.json

================================================================================
ARM Template Generation Summary
================================================================================
Total tools processed: 2
Templates generated: 2
  - Tools with agents: 2
  - Tools without agents: 0

Templates saved to: arm-templates
================================================================================

☁️ Deploying Discovery Control Plane Resources
================================================================================

Deploying pubmed-template.json...
  → Checking for existing agent: PubMed
  → Agent exists, deleting: PubMed
  ✓ Agent deleted successfully
  → Checking for existing tool: pubmed
  → Tool exists, deleting: pubmed
  ✓ Tool deleted successfully
  → Detected combined template with tool and agent
  → Deploying Microsoft.Discovery/tools resource first...
  ✓ Tool resource deployed successfully (provisioningState: Succeeded)
  → Deploying Microsoft.Discovery/agents resource...
  ✓ Agent resource deployed successfully (provisioningState: Succeeded)
  ✓ Combined deployment successful: pubmed-template

Deploying rdkit-tool-template.json...
  → Checking for existing agent: RDKit
  → Checking for existing tool: rdkit-tool
  → Detected combined template with tool and agent
  → Deploying Microsoft.Discovery/tools resource first...
  ✓ Tool resource deployed successfully (provisioningState: Succeeded)
  → Deploying Microsoft.Discovery/agents resource...
  ✓ Agent resource deployed successfully (provisioningState: Succeeded)
  ✓ Combined deployment successful: rdkit-tool-template

================================================================================
Deployment Summary
================================================================================
Total templates: 2
Successful deployments: 2
Failed deployments: 0
Tool resources created: 2
Agent resources created: 2
================================================================================

✅ Complete workflow finished successfully!
   - Docker images built and pushed to ACR
   - YAML definitions converted to ARM templates
   - Discovery Tool resources deployed to Azure
   - Discovery Agent resources deployed to Azure
```

**What the script does automatically:**

1. **YAML to ARM Conversion**:
   - Reads `*-tool-definition.yaml` files
   - Reads `*-agent-definition.yaml` or `*Agent.yaml` files
   - Converts YAML structure to ARM template JSON format
   - Updates ACR image references from your registry
   - Creates combined templates with both resources

2. **Control Plane Resource Deployment**:
   - Deploys `Microsoft.Discovery/tools` resources
   - Deploys `Microsoft.Discovery/agents` resources
   - Links agents to their tool dependencies
   - Configures model settings, instructions, and extensions

3. **Resource Lifecycle Management**:
   - Detects existing resources
   - Deletes old versions before deploying
   - Handles dependencies (agent → tool order)
   - Provides detailed status and error reporting

**Manual Template Deployment (Alternative):**

If you want more control, generate templates without deploying:

```bash
# Generate templates only (no deployment)
python3 build_tools.py
# When prompted: Generate ARM templates? yes
# When prompted: Deploy templates? no

# Navigate to the generated templates
cd arm-templates

# Review the generated ARM template
cat pubmed-template.json

# Deploy manually when ready
az deployment group create \
  --resource-group discovery-rg \
  --template-file pubmed-template.json \
  --parameters location=uksouth
```

---

## Output

### Build Progress

Each tool build shows real-time progress:

```
[1/3]
================================================================================
🏗️  Building: rdkit-tool
================================================================================
Context: 6-solutions/tools-and-models/rdkit-tool
Dockerfile: 6-solutions/tools-and-models/rdkit-tool/Dockerfile
Image: rdkit-tool:latest
Registry: mydiscoveryacr

🚀 Starting remote build (this may take several minutes)...

[Azure ACR build output...]

✅ Successfully built and pushed: mydiscoveryacr.azurecr.io/rdkit-tool:latest
```

### Final Summary

```
📊 Build Summary
================================================================================

✅ Successfully built (3):
   - rdkit-tool
   - chembl
   - pubMed

================================================================================
Total: 3/3 successful
================================================================================
```

---

## Verifying Built Images

### For Local Builds

Check locally built images:

```bash
# List local Docker images
docker images | grep -E "(rdkit-tool|chembl|pubmed)"

# Test run an image locally
docker run --rm rdkit-tool:latest --help

# If you pushed to ACR, verify in the registry
az acr repository list --name <your-acr-name> --output table
```

### For Remote Builds (or after pushing to ACR)

Verify images in your ACR:

```bash
# List all repositories
az acr repository list --name <your-acr-name> --output table

# Show tags for a specific tool
az acr repository show-tags --name <your-acr-name> --repository rdkit-tool --output table

# Pull an image to test locally (if you have Docker)
docker pull <your-acr-name>.azurecr.io/rdkit-tool:latest
```

---

## Troubleshooting

### Azure CLI Issues (Remote Build Mode)

**Azure CLI Not Found:**

```bash
# Install Azure CLI based on your OS
# macOS
brew install azure-cli

# Windows
# Download from: https://aka.ms/installazurecliwindows

# Linux (Ubuntu/Debian)
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

**Not Authenticated:**

```bash
az login
# Follow browser authentication flow
```

**No Access to ACR:**

Ensure you have the correct permissions:

```bash
# Check your role assignments on the ACR
az role assignment list --assignee <your-email> --scope /subscriptions/<subscription-id>/resourceGroups/<rg-name>/providers/Microsoft.ContainerRegistry/registries/<acr-name>

# You need at least "AcrPush" role
```

**No Access to ACR:**

Ensure you have the correct permissions:

```bash
# Check your role assignments on the ACR
az role assignment list --assignee <your-email> --scope /subscriptions/<subscription-id>/resourceGroups/<rg-name>/providers/Microsoft.ContainerRegistry/registries/<acr-name>

# You need at least "AcrPush" role
```

### Build Failures

**Local Build Failures:**
- Check Docker daemon is running: `docker ps`
- Verify sufficient disk space: `docker system df`
- Check build logs for missing dependencies or network issues
- Try building with more verbose output: Add `--progress=plain` flag manually

**Remote Build Failures:**
- Check that the Dockerfile in the tool directory is valid
- Ensure all required files are present in the tool directory  
- Review the Azure ACR build logs (displayed during build)
- Some tools may have large dependencies and take 30-40 minutes to build
- Verify network connectivity to Azure

### Platform-Specific Issues

**Windows:**
- Ensure WSL2 is installed for Docker Desktop
- Azure CLI commands are automatically handled with proper shell compatibility
- Path separators are handled automatically
- Use PowerShell, Command Prompt, or WSL terminal to run the script

**macOS:**
- Docker Desktop requires macOS 10.15 or newer
- Apple Silicon (M1/M2) Macs: Ensure Rosetta 2 is installed if needed

**Linux:**
- Ensure Docker service is running: `sudo systemctl status docker`
- Add user to docker group to avoid sudo: `sudo usermod -aG docker $USER`

### Deployment Issues

**Resource Already Exists:**
- The script automatically detects and deletes existing resources before deployment
- If automatic deletion fails, you can manually delete resources:
  ```bash
  # Delete an agent
  az resource delete \
    --resource-group <resource-group> \
    --name <agent-name> \
    --resource-type Microsoft.Discovery/agents
  
  # Delete a tool
  az resource delete \
    --resource-group <resource-group> \
    --name <tool-name> \
    --resource-type Microsoft.Discovery/tools
  ```

**Agent Deployment Validation Errors:**
- Ensure the agent definition includes all required fields
- Check that the tool resource is successfully deployed first
- Verify the agent definition has the correct structure with `agent` property
- Review deployment logs for specific validation error messages

**Template Generation Issues:**
- Ensure tool and agent definition YAML files exist in the tool directory
- Verify YAML files are properly formatted (use a YAML validator)
- Check that ACR image references are correct
- Tool definition files must match: `*-tool-definition.yaml`
- Agent definition files can use patterns: `*-agent-definition.yaml`, `*Agent.yaml`, `*-agent.yaml`, `*_agent.yaml`
- Verify agent definition has proper structure with `agent` property at root level
- Ensure `extension` property is at root level (not inside `agent`)

**YAML Structure Errors:**
- **Missing `agent` property**: Agent fields must be nested under `agent:` in YAML
- **Wrong property nesting**: `extension` should be at root level, not inside `agent`
- **Invalid YAML syntax**: Use a YAML linter to check syntax
- **Missing required fields**: Ensure all required fields are present (name, description, model, etc.)

Example correct agent structure:
```yaml
version: "1.0.0"
agent:                    # Required: nest agent fields here
  name: "Agent Name"
  description: "..."
  model: "gpt-4o"
  instructions: "..."
  temperature: 0
extension:                # Required: at root level, not inside agent
  events: []
  inputs: []
```

---

## Decision Guide: Local vs Remote?

### Choose **Local Build** when:
- ✅ You have Docker installed and running
- ✅ You want faster builds (uses your local CPU/memory)
- ✅ You're testing/developing and don't need ACR yet
- ✅ You have good hardware and want to iterate quickly
- ✅ You're building just a few images

### Choose **Remote Build** when:
- ✅ You don't have Docker installed
- ✅ Your machine has limited resources
- ✅ You're building many images in parallel
- ✅ You want builds to happen in Azure (closer to deployment)
- ✅ Your network connection is good but machine is slow
- ✅ You need images in ACR anyway

---

## Advanced Usage

### Building Specific Tools with Custom Tags

For local builds, you can manually tag images:

```bash
# After building locally
docker tag rdkit-tool:latest mydiscoveryacr.azurecr.io/rdkit-tool:v1.0.0
docker push mydiscoveryacr.azurecr.io/rdkit-tool:v1.0.0
```

To modify the script for custom tags, edit `build_tools.py`:

```python
# Change this line in build_tool_locally() or build_tool_with_acr_tasks()
image_name = f"{tool_name.lower()}:latest"
# To:
image_name = f"{tool_name.lower()}:v1.0.0"
```

### Custom Dockerfile Locations

The script automatically discovers Dockerfiles. If you add new tools:
1. Place tool code in `6-solutions/tools-and-models/<tool-name>/`
2. Add a `Dockerfile` in that directory
3. Run the script - it will auto-discover the new tool

### Verifying Deployed Resources

After deployment, verify the resources in Azure:

```bash
# List all Discovery tools
az resource list \
  --resource-group <resource-group> \
  --resource-type Microsoft.Discovery/tools \
  --query "[].{name:name, type:type, location:location}" \
  -o table

# List all Discovery agents
az resource list \
  --resource-group <resource-group> \
  --resource-type Microsoft.Discovery/agents \
  --query "[].{name:name, type:type, location:location}" \
  -o table

# Get detailed information about a specific tool
az resource show \
  --resource-group <resource-group> \
  --name <tool-name> \
  --resource-type Microsoft.Discovery/tools

# Get detailed information about a specific agent
az resource show \
  --resource-group <resource-group> \
  --name <agent-name> \
  --resource-type Microsoft.Discovery/agents
```

---

## Next Steps

After building and deploying tool images:

1. **Verify Deployed Resources**
   - Check Discovery tools and agents in Azure portal or via Azure CLI
   - See "Verifying Deployed Resources" in Advanced Usage section

2. **Use Tools in Investigations**
   - See [Running Investigations](../../4-how-to/8-investigations/b--running-a-sample-scenario.md)

3. **Additional Tool or Agent Configuration**
   - Update tool definitions: See [Updating Tool/Agent Resources](../../4-how-to/6-tools-models-agents/d--updating-tool-model-agent-resource.md)
   - Deploy additional models: See [Model Deployment Guide](../../4-how-to/6-tools-models-agents/a--model-deployment.md)

---

## Key Features

### End-to-End Automation
- **Complete Workflow**: From source code to deployed Azure resources in one command
- **No Manual Steps**: Handles Docker building, YAML conversion, and deployment automatically
- **Flexible Entry Points**: Start from any stage (build, convert, or deploy)

### YAML to ARM Template Conversion
- **Automatic Conversion**: Transforms YAML definitions to ARM template JSON format
- **Intelligent Parsing**: Extracts and structures tool and agent properties correctly
- **Image Reference Updates**: Automatically updates ACR image paths from your registry
- **Combined Templates**: Creates single template with both tool and agent resources
- **Validation**: Ensures proper structure with required `agent` property nesting

### Automatic Resource Management
- **Intelligent Deletion**: Automatically detects and removes existing resources before deployment
- **Dependency Handling**: Deletes agents before tools to respect resource dependencies
- **Failure Resilience**: Continues deployment even if deletion fails, with detailed tracking
- **Lifecycle Management**: Create, update, and delete Discovery control plane resources

### Combined Template Generation
- **Single File Deployment**: Tool and agent resources in one ARM template
- **Split Deployment Strategy**: Deploys tool first, then agent for reliability
- **Flexible Agent Detection**: Supports multiple agent file naming patterns
- **Proper Resource Links**: Correctly links agents to their tool dependencies

### Control Plane Resource Deployment
- **Microsoft.Discovery/tools**: Deploys tool resources with container specs, compute, and environment
- **Microsoft.Discovery/agents**: Deploys agent resources with model config, instructions, and tools
- **API Version**: Uses `2025-07-01-preview` API for latest features
- **Resource Properties**: Includes definitionContent, version, model name, tools array, etc.

### Cross-Platform Support
- **Windows**: Full support with proper shell command handling
- **macOS**: Native support with Docker Desktop or remote builds
- **Linux**: Full Docker and ACR support
- **Shell Compatibility**: Automatic command adaptation for each platform

---

## Reference Links

- [Azure Container Registry Tasks Documentation](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-tasks-overview)
- [ACR Tasks Quickstart](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-tasks-quickstart)
- [Azure CLI Installation](https://docs.microsoft.com/cli/azure/install-azure-cli)
- [ARM Template Reference](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/)
- [Microsoft Discovery Documentation](../../README.md)
- [Discovery API Reference](https://learn.microsoft.com/en-us/rest/api/discovery/)

---

## Files in This Directory

- **`build_tools.py`** - Main orchestration script
  - Discovers tools with definition files
  - Manages Docker image building (local or remote)
  - Orchestrates ARM template generation
  - Coordinates deployment workflow
  
- **`generate_arm_templates.py`** - ARM template generation and deployment engine
  - Converts YAML definitions to ARM template JSON format
  - Generates combined templates with tool and agent resources
  - Deploys Microsoft.Discovery/tools resources
  - Deploys Microsoft.Discovery/agents resources
  - Manages resource lifecycle (create, update, delete)
  
- **`requirements.txt`** - Python dependencies
  - PyYAML: Required for YAML to JSON conversion
  - Install with: `pip install -r requirements.txt`
  
- **`.env.example`** - Example environment variable configuration
  - Template for ACR name, resource group, subscription ID
  - Copy to `.env` and customize for your environment
  
- **`README.md`** - This comprehensive documentation file

- **`arm-templates/`** - Generated ARM templates directory (auto-created)
  - Contains JSON ARM templates generated from YAML definitions
  - Combined templates with both tool and agent resources
  - Ready for deployment to Azure

---

## Understanding the Conversion Process

### YAML to ARM Template Conversion

This utility automatically converts your YAML definition files into Azure Resource Manager (ARM) templates:

**Input**: Tool and Agent YAML definitions
```yaml
# PubMed-tool-definition.yaml
version: "1.0.0"
infra:
  - image:
      acr: "placeholder.azurecr.io/pubmed"
    compute:
      cpu: "1"
      memory: "2Gi"
# ... more configuration

# PubMed-agent-definition.yaml
version: "1.0.0"
agent:
  name: "PubMed"
  model: "gpt-4o"
  instructions: "..."
extension:
  system_prompts: [...]
```

**Output**: ARM Template JSON
```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
  "contentVersion": "1.0.0.0",
  "resources": [
    {
      "type": "Microsoft.Discovery/tools",
      "apiVersion": "2025-07-01-preview",
      "name": "pubmed",
      "properties": {
        "version": "1.0.0",
        "definitionContent": { /* tool config */ }
      }
    },
    {
      "type": "Microsoft.Discovery/agents",
      "apiVersion": "2025-07-01-preview",
      "name": "PubMed",
      "properties": {
        "modelName": "gpt-4o",
        "definitionContent": {
          "agent": { /* agent config */ },
          "extension": { /* extension config */ }
        }
      }
    }
  ]
}
```

**Key Transformations**:
1. YAML structure → JSON ARM template format
2. Tool config → `Microsoft.Discovery/tools` resource
3. Agent config → `Microsoft.Discovery/agents` resource  
4. ACR placeholder → Actual ACR registry path
5. Separate files → Combined template with dependencies
6. YAML properties → ARM resource properties
