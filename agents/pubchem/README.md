
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

## Build Docker Image

### Step 1: Build and Publish Docker Image


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

## Usage

### Basic Queries

| Prompt | Description |
|--------|-------------|
| "Look up the PubChem entry for aspirin" | Search compound by name |
| "Get all properties for CID 2244" | Retrieve compound by CID |
| "Find compounds matching SMILES CC(=O)Oc1ccccc1C(=O)O" | Search by SMILES |
| "What is the molecular formula and weight of caffeine?" | Basic property lookup |

### Advanced Queries

| Prompt | Description |
|--------|-------------|
| "Compare properties of ibuprofen, naproxen, and acetaminophen" | Multi-compound comparison |
| "Retrieve the InChI key, canonical SMILES, and XLogP for metformin" | Selective property extraction |
| "Find the PubChem CID for this InChI string and get its full data" | Cross-identifier lookup |

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → PubChem (LLM) → PubChem Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** PubChem container for chemical information retrieval via PubChem API

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{model}}` | Azure AI Foundry model deployment name | `gpt-4o` |


## Support

For issues or questions, open a GitHub issue:
<https://github.com/microsoft/discovery-catalog/issues>

Microsoft Discovery team contact: discovery-catalog@microsoft.com


## Tools

| Tool | Path | Description |
|---|---|---|
| `pubChem` | `tools/PubChem/` | PubChem is a tool for accessing chemical information from the PubChem database, providing a simple interface to download molecule data using the Pu... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.