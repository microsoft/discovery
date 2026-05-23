
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

## Build Docker Image

### Step 1: Build and Publish Docker Image


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

## Usage

### Basic Analysis

| Prompt | Description |
|--------|-------------|
| "Calculate molecular properties for aspirin (CC(=O)Oc1ccccc1C(=O)O)" | Molecular weight, LogP, TPSA, H-bond donors/acceptors |
| "Identify all functional groups in ibuprofen" | Functional group detection using SMARTS |
| "Check this molecule for hazardous groups: C(=O)(Cl)Cl" | Safety screening for explosives, PFAS, CWC compounds |
| "Convert this SMILES to SDF format: c1ccccc1" | File format conversion |

### Advanced Analysis

| Prompt | Description |
|--------|-------------|
| "Generate a low-energy 3D conformer for caffeine and save as SDF" | Conformer generation with energy minimization |
| "Evaluate drug-likeness for these SMILES using Lipinski, Veber, and QED" | Multi-criteria drug-likeness assessment |
| "Enumerate all stereoisomers of this molecule" | Stereo enumeration |
| "Run substructure search for a benzene ring across these compounds" | Batch substructure matching |

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → MolToolkit (LLM) → MolToolkit Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** MolToolkit container for cheminformatics analysis using RDKit and open-source Python packages

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
| `molToolkit` | `tools/MolToolkit/` | MolToolkit is a comprehensive toolkit for molecular analysis and data processing, designed to handle tasks such as molecular conformer generation, ... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.