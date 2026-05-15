
# PubChem Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the PubChem tool and its associated agent to the Microsoft Discovery platform.

## Overview

PubChem provides access to chemical information and bioactivity data from the PubChem database, supporting compound search and data integration workflows. This deployment includes:

- **Dockerfile**: Used for creation of the PubChem tool container image
- **Tool Definition**: Configuration for the PubChem tool
- **Agent Definition**: AI agent configuration for PubChem

## Prerequisites

Before starting the deployment, ensure you have:

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally for image building
4. Azure CLI or PowerShell for resource management
5. Completed platform onboarding (see [user guide](../../../4-how-to/))

## Deployment Steps

### Step 1: Build and Publish Docker Image

1. **Build the Docker image** from the provided Dockerfile:

   ```bash
   docker build -t pubchem:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag pubchem:latest mycontainerregistry.azurecr.io/pubchem:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/pubchem:latest
   ```

### Step 2: Update Tool Definition

1. **Edit the tool definition file** (`PubChem-tool-definition.yaml`)
2. **Update the ACR path** in the image section:

   ```yaml
   infra:
     - name: worker
       infra_type: container
       image:
         acr: mycontainerregistry.azurecr.io/pubchem:latest  # Update this line
   ```

   > Replace `mycontainerregistry` with your actual ACR name

### Step 3: Convert YAML to JSON

Use the provided utility to convert YAML definitions to JSON format required by the platform:

1. **Convert the tool definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py PubChem-tool-definition.yaml --output PubChem-tool-definition.json --json
   ```

2. **Convert the agent definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py PubChem-agent-definition.yaml --output PubChem-agent-definition.json --json
   ```

### Step 4: Deploy Platform Resources

#### 4.1 Create Tool Resource

Deploy the PubChem tool to the Discovery platform using the generated JSON definition. This creates the computational environment for running chemical information retrieval operations.

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/b--tool-deployment.md) for detailed steps

#### 4.2 Create Agent Resource

Deploy the PubChem agent using the agent JSON definition. This creates the AI agent that can perform compound search and data integration tasks.

> **Reference**: See [Agent Deployment Guide](../../../4-how-to/6-tools-models-agents/c--agent-deployment.md) for detailed steps

#### 4.3 Create Workflow Resource

Create a workflow that utilizes the PubChem agent for compound search and chemical data retrieval tasks.

#### 4.4 Create Project Resource

Set up a project to organize and manage your chemical information workflows.

> **Reference**: See [Project Creation Guide](../../../4-how-to/7-projects/a--creating-project.md) for detailed steps

#### 4.5 Create an Investigation

Create a project investigation that utilizes the PubChem agent for compound search and analysis.

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/8-investigations/a--creating-investigation.md) for detailed steps

#### 4.6 Run an investigation

Run the investigation with prompts such as:

- "Search for compounds with bioactivity against a target."
- "Retrieve compound information for CID 2244."
- "Analyze the chemical properties of the selected compound."

Wait for response and check the generated outputs.

## File Structure

```text
pubChem/
├── Dockerfile                          # Container image definition
├── PubChem-tool-definition.yaml        # Tool configuration (YAML)
├── PubChem-agent-definition.yaml       # Agent configuration (YAML)
├── app/                               # Application source code
│   ├── basic-description.txt          # Tool description
│   ├── PubChem-api-documentation.md   # API documentation
└── README.md                          # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The PubChem agent provides:

- **Compound Search**: Search by name, CID, bioactivity, and more
- **Data Integration**: Retrieve and process chemical information
- **Flexible File Management**: Saves results and compound data with appropriate naming conventions

### Supported File Types

- **Chemical Data**: SDF, MOL, SMILES
- **Tabular Data**: CSV, TSV
- **Custom Text Files**: Any text-based format

### Key Features

- **Smart Content Processing**: Handles chemical data formats and conversions
- **Safe File Naming**: Sanitizes file names to prevent security issues
- **Output Management**: Saves all files to `/app/outputs` directory for easy retrieval

## Additional Resources

- [Microsoft Discovery Documentation](../../)
- [Container Image Creation Guide](../../../4-how-to/5-tool-image/a--create-and-publish-container-image.md)

## Support

For platform-specific issues, refer to the [user guide documentation](../../../4-how-to/) or contact your platform administrator.
