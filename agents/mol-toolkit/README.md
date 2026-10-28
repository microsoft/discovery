
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

## UMAP dependency and verification

The `molenv` environment includes `umap-learn` (imported as `from umap import
UMAP`). The Dockerfile runs `app/smoke_umap.py` during the build: it computes real
UMAP coordinates from a ten-row fingerprint Tanimoto-distance matrix and rejects
non-finite coordinates or an output shape other than `(10, 2)`. This is an
embedding execution check, not just an import check or an MDS/PCA substitute.

In the matching tool environment, the check can also be run without rebuilding:

```bash
python /app/smoke_umap.py
```

Success prints `UMAP_SMOKE_OK`, the installed package version, and `(10, 2)`.
The check requires the image's Python dependencies; compiling the script alone
does not validate UMAP execution. It does not validate scientific cluster quality.

| Prompt behavior before | Prompt behavior after |
|---|---|
| UMAP was not in the agent's available-package list | The agent explicitly uses `umap-learn` |
| Missing UMAP could lead to an MDS fallback | MDS, PCA, and t-SNE cannot be reported as UMAP |
| Precomputed similarities could be confused with distances | Tanimoto similarities are validated and converted to distances before UMAP |

For example, "visualize ten candidate fingerprints using UMAP" now requires a
real two-dimensional UMAP embedding, a plot, saved coordinates, package version,
and parameters. A failed import or embedding must be reported as a failure with
diagnostics, not as a completed substitute visualization.

These are source changes, not an update to any existing image or deployed agent.
Obtain approval before building, publishing, retagging, or replacing an image.
After approval, build and scan the matching image first, verify the smoke check,
then update the deployed tool and agent together before rerunning affected tasks.
Changing agent instructions alone cannot add the missing dependency to an image.

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