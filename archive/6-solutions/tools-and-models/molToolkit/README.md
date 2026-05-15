
# MolToolkit Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the MolToolkit tool and its associated agent to the Microsoft Discovery platform.

## Overview

MolToolkit is a comprehensive molecular analysis toolkit supporting cheminformatics, molecular modeling, and data science workflows. This deployment includes:

- **Dockerfile**: Used for creation of the MolToolkit tool container image
- **Tool Definition**: Configuration for the MolToolkit tool
- **Agent Definition**: AI agent configuration for MolToolkit

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
   docker build -t moltoolkit:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag moltoolkit:latest mycontainerregistry.azurecr.io/moltoolkit:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/moltoolkit:latest
   ```

### Step 2: Update Tool Definition

1. **Edit the tool definition file** (`MolToolkit-tool-definition.yaml`)
2. **Update the ACR path** in the image section:

   ```yaml
   infra:
     - name: worker
       infra_type: container
       image:
         acr: mycontainerregistry.azurecr.io/moltoolkit:latest  # Update this line
   ```

   > Replace `mycontainerregistry` with your actual ACR name

### Step 3: Convert YAML to JSON

Use the provided utility to convert YAML definitions to JSON format required by the platform:

1. **Convert the tool definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py MolToolkit-tool-definition.yaml --output MolToolkit-tool-definition.json --json
   ```

2. **Convert the agent definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py MolToolkit-agent-definition.yaml --output MolToolkit-agent-definition.json --json
   ```

### Step 4: Deploy Platform Resources

#### 4.1 Create Tool Resource

Deploy the MolToolkit tool to the Discovery platform using the generated JSON definition. This creates the computational environment for running molecular analysis operations.

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/b--tool-deployment.md) for detailed steps

#### 4.2 Create Agent Resource

Deploy the MolToolkit agent using the agent JSON definition. This creates the AI agent that can perform molecular analysis and modeling tasks.

> **Reference**: See [Agent Deployment Guide](../../../4-how-to/6-tools-models-agents/c--agent-deployment.md) for detailed steps

#### 4.3 Create Workflow Resource

Create a workflow that utilizes the MolToolkit agent for molecular modeling and cheminformatics tasks.

#### 4.4 Create Project Resource

Set up a project to organize and manage your molecular analysis workflows.

> **Reference**: See [Project Creation Guide](../../../4-how-to/7-projects/a--creating-project.md) for detailed steps

#### 4.5 Create an Investigation

Create a project investigation that utilizes the MolToolkit agent for molecular modeling and analysis.

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/8-investigations/a--creating-investigation.md) for detailed steps

#### 4.6 Run an investigation

Run the investigation with prompts such as:

- "Analyze the functional groups in this molecule."
- "Generate a conformer for the given structure."
- "Predict hazardous groups in the compound."
- "Visualize the molecular structure and save the image."

Wait for response and check the generated outputs.

## File Structure

```text
molToolkit/
├── Dockerfile                          # Container image definition
├── MolToolkit-tool-definition.yaml     # Tool configuration (YAML)
├── MolToolkit-agent-definition.yaml    # Agent configuration (YAML)
├── app/                               # Application source code
│   ├── get_low_energy_conformer.py    # Conformer generation logic
│   ├── io_utils.py                    # I/O utilities
│   ├── mol_functional_groups.py       # Functional group analysis
│   ├── mol_hazardous_groups.py        # Hazardous group prediction
│   ├── molecular_utils.py             # General molecular utilities
└── README.md                          # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The MolToolkit agent provides:

- **Molecular Analysis**: Functional group identification, hazardous group prediction, conformer generation
- **Visualization**: Structure visualization and image generation
- **Cheminformatics**: Data processing and feature extraction
- **Flexible File Management**: Saves results and images with appropriate naming conventions

### Supported File Types

- **Molecular Data**: SDF, MOL, PDB, SMILES
- **Images**: PNG, JPEG
- **Tabular Data**: CSV, TSV
- **Custom Text Files**: Any text-based format

### Key Features

- **Smart Content Processing**: Handles molecular data formats and conversions
- **Visualization**: Generates molecular images
- **Safe File Naming**: Sanitizes file names to prevent security issues
- **Output Management**: Saves all files to `/app/outputs` directory for easy retrieval

## Additional Resources

- [Microsoft Discovery Documentation](../../)
- [Container Image Creation Guide](../../../4-how-to/5-tool-image/a--create-and-publish-container-image.md)

## Support

For platform-specific issues, refer to the [user guide documentation](../../../4-how-to/) or contact your platform administrator.
