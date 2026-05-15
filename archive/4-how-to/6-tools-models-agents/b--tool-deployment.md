# Tool Deployment Guide for Microsoft Discovery

This comprehensive guide walks you through deploying computational tools in Microsoft Discovery, covering both Azure Portal experience and ARM template deployment approaches. Tools in Microsoft Discovery serve as the building blocks for creating autonomous agents that can execute specific computational tasks, scientific workflows, and data processing operations.

## Tool Deployment Overview

Microsoft Discovery tools are computational resources that provide specific capabilities for scientific research workflows. Tools can be standalone executables, containerized applications, or integrations with external services that agents can utilize to perform complex tasks.

### Tool Types Supported

Microsoft Discovery supports several categories of tools:

- **Action-based Tools**: Perform specific computational actions with defined input/output schemas
- **Code Environment Tools**: Provide execution environments for custom code and scripts
- **Hybrid Tools**: Combine action-based and code environment capabilities

> **Assumption**: This guide assumes your tool definitions are already created following the [Publisher Guide for Tools](tools-publishing/). If your tool definitions are not yet created, please follow that guide first to understand tool specification requirements.

## Prerequisites

Before deploying tools in Microsoft Discovery, ensure you have the following:

### 1. Platform Prerequisites

- **Active Azure subscription** with Microsoft Discovery resource provider registered
- **Sufficient permissions** to create and manage Microsoft Discovery resources

### 2. Tool Definition Requirements

- **Tool definition file** created in YAML format following the specification schema
- **Container images** (if applicable) published to Azure Container Registry or accessible registries
- **Input/output schemas** properly defined for tool actions
- **Compute resource requirements** specified (CPU, memory, GPU, storage)

### 3. Agent Defintion

- **Agent definition file** created in YAML format following the specification schema

### 4. Infrastructure Prerequisites

- **Container Registry Access**: For tools using custom container images
- **Network Connectivity**: Appropriate network access for tool dependencies
- **Storage Mounts**: Access to required data sources and output locations
- **Compute Quotas**: Sufficient VM SKU quotas in your target region

### 5. Resource Group Organization

Tools and related resources can be organized in resource groups following these patterns:

- **Development**: `contoso-discovery-dev-rg`
- **Testing**: `contoso-discovery-test-rg`  
- **Production**: `contoso-discovery-prod-rg`

Each resource group should contain the complete set of related resources for that environment:

```text
contoso-discovery-prod-rg/
├── contoso-chemistry-workspace-prod
├── chemistry-model-v1-prod
├── chemistry-tool-client-prod
├── chemistry-agent-prod
└── supporting-infrastructure
```

### 6. Azure Quota Requirements

Ensure sufficient quota in your target region for:

- **VM SKUs** specified in tool definitions (Standard_D4_v4, Standard_NC series, etc.)
- **Container compute resources** for tool execution
- **Storage resources** for tool data and outputs
- See [Quotas and Limits](../../5-management/resource-limits.md) for detailed requirements

## Tool Deployment via Azure Portal

### Step 1: Navigate to Tool Creation

1. **Sign in to the Azure Portal**
   - Navigate to [Azure Portal](https://portal.azure.com)
   - Authenticate with your Azure credentials

2. **Access Microsoft Discovery Tools**
   - In the Azure Portal search bar, type "Microsoft Discovery Tools"
   - Select **Microsoft Discovery Tools** from the search results
   - Click **"Create"** to start the tool deployment process

### Step 2: Configure Basic Tool Settings

Configure the fundamental tool properties:

- **Subscription**: Select the Azure subscription containing your Discovery workspace
- **Resource Group**: Choose the resource group for organizing your tool resources
  - **Recommended**: Use environment-specific resource groups (dev, test, prod)
- **Tool Name**: Enter a descriptive name for your tool resource
  - **Format**: `{purpose}-{tool-type}-{version}` (e.g., `chemistry-analyzer-v1`)
- **Region**: Select the Azure region where your workspace is deployed
  - **Important**: Must match your workspace region for optimal performance

### Step 3: Upload Tool Definition

1. **Prepare Tool Definition File**
   - Create a YAML file defining your tool configuration
   - Refer to details on [how to create tool definition](tools-publishing/e--create-tool-definition.md)

2. **Convert YAML to JSON**

   Use the utility for [definition content creator](../../utils/README.md) to generate a JSON file from your YAML definition.

3. **Upload Definition**
   - **Definition Content File**: Upload your tool definition JSON file (converted from YAML)
   - **Definition Content Version**: Enter any valid string (Example: "1.0.0")

### Step 4: Configure Tool Settings

1. **Environment Variables** (Optional)
   - Add any environment variables required by your tool.
   - The environment content should be json formatted.
   - Common examples:
     - Configuration parameters
     - Model Endpoint - referring to the Model Resource ID
   - Sample JSON content:
     {
        "TEST_CAPTION": "this is a sample test caption",
        "ENDPOINT": "https://api.github.com"
     }

2. **Resource Configuration**
   - Verify compute resource allocation matches your tool requirements
   - Confirm VM SKU compatibility with your workspace supercomputer

### Step 5: Review and Create

1. **Review Configuration**
   - Verify all tool settings are correct
   - Confirm workspace and region alignment
   - Check container image accessibility and compute requirements

2. **Create Tool Resource**
   - Click **"Review + create"**
   - Review the terms and conditions
   - Click **"Create"** to deploy the tool resource

### Step 6: Create Associated Agent

After the tool resource is created, you'll typically want to create an associated agent resource that can utilize this tool in workflows.

#### Create Tool Agent

Follow the instructions on [how to deploy an Agent resource](./c--agent-deployment.md) to create an agent that references your tool.

## Tool Deployment via ARM Templates

For automated deployments and infrastructure-as-code scenarios, use the Microsoft Discovery ARM templates.

### ARM Template Overview

The tools ARM template creates both tool and agent resources in a single deployment with proper dependencies.

The ARM template deployment process creates two interconnected resources:

```text
1. Tool Resource (Microsoft.Discovery/tools)
   └── Defines the computational tool configuration and capabilities
   
2. Agent Resource (Microsoft.Discovery/agents)
   ├── Depends on: Tool Resource
   ├── Tools Array: References Tool Resource
   └── Provides intelligent workflow orchestration using the tool
```

### Infrastructure Deployment

For comprehensive infrastructure deployment instructions, use the Azure CLI or create custom ARM templates based on your requirements.

This guide covers:

- Interactive deployment script usage with YAML to JSON conversion
- Manual deployment with custom parameters
- Template parameters and configuration options
- Prerequisites and dependency management
- Resource outputs and integration workflows

## Post-Deployment Configuration

### 1. Verify Resource Creation

After deployment, verify all resources are created successfully:

```bash
# List tool resources
az resource list --resource-type "Microsoft.Discovery/tools" --output table

# List agent resources (if created via ARM template)
az resource list --resource-type "Microsoft.Discovery/agents" --output table
```

## Key Notes: Environment variables

When running container‑based tools with Microsoft Discovery agents, environment variables are reliably applied only to commands that are explicitly started by the agent. Containers that rely on Docker ENTRYPOINT to start the workload automatically may not receive environment variables as expected.
 
### Recommended pattern (best practice)

Do not rely on Docker ENTRYPOINT to start your application. Instead, let the Discovery agent explicitly run your workload.

### Recommended approaches

- Define the full command in the tool definition (preferred), or
- Use Docker CMD instead of ENTRYPOINT, so the agent controls execution.

This ensures environment variables configured in Discovery are available to your application at runtime.

### What to avoid

- Avoid containers where the main workload starts automatically via ENTRYPOINT and expects environment variables to already be present.
- Avoid assuming that arguments passed by the agent will be interpreted correctly by an existing ENTRYPOINT.

## Next Steps

After successfully deploying your tool:

1. **[Create Projects](../7-projects/)** - Organize research using your deployed tool
2. **[Run Investigations](../8-investigations/)** - Test tool functionality in research workflows
3. **[Create Workflows](./c--agent-deployment.md)** - Build complex multi-tool workflows using your deployed tools

## Related Documentation

- [Microsoft Discovery Tools Overview](../../3-concepts/tools.md)
- [Publisher Guide for Tools](tools-publishing/)
