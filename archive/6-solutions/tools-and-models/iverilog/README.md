# iverilog with Agent - Combined ARM Template Deployment Guide

This guide explains how to deploy iverilog Tool and Agent as a combined solution using a single ARM template. The deployment will create and configure both interdependent components in the correct order:

1. **iverilog Tool**: The molecular dynamics simulation package containerized for scientific computing
2. **iverilog Agent**: An agent that leverages the iverilog tool for automated workflows

## Architecture Overview

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│                  │      │                  │      │                  │      │                  │
│  iverilog        │─────▶│ iverilog Tool CP │─────▶│ iverilog Agent  │─────▶│  iverilog Agent  │
│  Docker Image    │      │ Resource creation│      │  CP Resource     │      │  deployment      │
│                  │      │                  │      │  creation        │      │                  │
└──────────────────┘      └──────────────────┘      └──────────────────┘      └──────────────────┘
     Provides              iverilog tool              iverilog agent            Generates and runs
     containerized         control plane             control plane            Python scripts based
     iverilog               resource creation         resource creation.       on scenario
     environment                                     Triggers agent           (Internal)
                                                     creation on AI 
                                                     Agent Service

Tool Resource ID ─────────────▶ Agent CP Resource
```

The architecture follows this dependency chain:

```
iverilog Tool CP Resource Deployment → iverilog Agent CP Resource Deployment
```

### Component Relationships

- **iverilog Tool**: Microsoft.Discovery/tools resource deployment for iverilog
- **iverilog Agent**: Microsoft.Discovery/agents resource deployment for iverilog tool agent which inturn results into Chat completion model powered agent that generates Python scripts for iverilog workflows

## Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- [Docker](https://www.docker.com/get-started) installed (for building the iverilog Docker image)
- Access to an Azure subscription

## Prepare for Deployment

### Step 1: Prepare the Docker Image for the iverilog Tool

```bash
# Set Azure Container Registry details
export ACR_NAME="yourAcrName"
export IMAGE_NAME="iverilog"
export IMAGE_TAG="latest"

# Navigate to the tool Docker directory
cd MicrosoftDiscovery-HowTos/iverilog/1-Tool/a-core

# Build the Docker image
docker build -t ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG} .

# Login to Azure and ACR
az login
az acr login --name ${ACR_NAME}

# Push the image to ACR
docker push ${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}
```

### Step 2: Update the Combined Template Parameters

```bash
cd MicrosoftDiscovery-HowTos/iverilog/
```

Edit the `all-in-one/src/scripts/azuredeploy.parameters.json` file to match your environment:

```json
{
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "location": {
            "value": "westus2"
        },
        "toolName": {
            "value": "iverilog-tool"
        },
        "agentName": {
            "value": "iverilog-agent"
        },
        "agentVersion": {
            "value": "2025-05-15-preview"
        },
        "modelName": {
            "value": "gpt-4o"
        },
        "version": {
            "value": "1.0.0"
        }
    }
}
```

### Step 3: Update the variables under ARM template

Update the toolDefintion and agentDefinition variables in `all-in-one/src/scripts/azuredeploy.json` file with a appropriate replacements.

For toolDefinition, run the script to get its value -

```bash
python3 ../Utils/definition-content-creator.py ./iverilog-tool-definition.yaml
```

For agentDefinition, run the script to get its value -

```bash
python3 ../Utils/definition-content-creator.py ./iverilog-agent-definition.yaml
```

## Deployment Steps

### Step 1: Configure Deployment Variables

Edit the following parameters in the deployment script located in `all-in-one/src/scripts/deploy.sh`:

```bash
# Variables
RESOURCE_GROUP="your-resource-group-name"
LOCATION="westus"
DEPLOYMENT_NAME="iverilog-combined-deployment"
```

### Step 2: Run the Deployment Script

```bash
# Navigate to the scripts directory
cd MicrosoftDiscovery-HowTos/iverilog/all-in-one/src/scripts

# Make the script executable if needed
chmod +x deploy.sh

# Run the deployment script
./deploy.sh
```

### Step 3: Verify the Deployment

```bash
# Check deployment status
az deployment group show \
    --name $DEPLOYMENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --query properties.provisioningState

# List all resources created by the deployment
az resource list \
    --resource-group $RESOURCE_GROUP \
    --output table
```

## Understanding the Combined ARM Template

The combined ARM template automates the entire deployment process, ensuring proper dependencies between components:

1. **iverilog Tool Deployment**:
   - Deploys the iverilog Control plane resource

2. **iverilog Agent Deployment**:
   - Waits for the tool deployment to complete
   - References the deployed tool ID in its configuration
   - Deploys the iverilog tool agent control plane resource
   - Configures the agent to generate and execute iverilog Python scripts

### Key Dependencies in the Template

The template uses the `dependsOn` property to manage dependencies:

- Agent depends on Tool: `"dependsOn": ["[resourceId('Microsoft.Discovery/tools', parameters('toolName'))]"]`

## Troubleshooting

If you encounter issues during deployment:

1. **Tool deployment fails**:
   - Check that the Docker image was successfully pushed to ACR
   - Ensure the ACR credentials are correct and accessible
   - Verify that the compute SKUs requested are available in your region

2. **Agent deployment fails**:
   - Verify that the tool was successfully deployed
   - Check that the agent model (eg. gpt-4o) is available in your region
   - Ensure that the tool ID reference is correct

3. **Runtime issues**:
   - Check that the protein structure files are properly formatted
   - Ensure simulation parameters are within reasonable ranges
   - Review the log output for specific error messages from iverilog

## Resources

- [iverilog Tool Documentation](/iverilog/1-Tool/Readme.md)
- [iverilog Agent Documentation](/iverilog/2-Agent/README.md)
- [iverilog Official Documentation](https://steveicarus.github.io/iverilog/usage/index.html)