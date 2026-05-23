
# PDBSearch Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the PDBSearch tool and its associated agent to the Microsoft Discovery platform.

## Overview

PDBSearch enables advanced search and retrieval of biomolecular structures from the RCSB Protein Data Bank (PDB). This deployment includes:

- **Dockerfile**: Used for creation of the PDBSearch tool container image
- **Tool Definition**: Configuration for the PDBSearch tool
- **Agent Definition**: AI agent configuration for PDBSearch

## Prerequisites

Before starting the deployment, ensure you have:

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally for image building
4. Azure CLI or PowerShell for resource management

## Build Docker Image

### Step 1: Build and Publish Docker Image


   ```bash
   docker build -t pdbsearch:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag pdbsearch:latest mycontainerregistry.azurecr.io/pdbsearch:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/pdbsearch:latest
   ```

## File Structure

```text
pdbSearch/
├── Dockerfile                          # Container image definition
├── PDBSearch-tool-definition.yaml      # Tool configuration (YAML)
├── PDBSearch-agent-definition.yaml     # Agent configuration (YAML)
├── app/                               # Application source code
│   ├── io_utils.py                    # I/O utilities
│   ├── pdb_search.py                  # Main search logic
│   ├── pdb_utils.py                   # Structure retrieval utilities
│   ├── search_utils.py                # Search utilities
└── README.md                          # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The PDBSearch agent provides:

- **Advanced Structure Search**: Search by resolution, organism, ligand, and more
- **Structure Retrieval**: Download and analyze PDB entries
- **Flexible File Management**: Saves results and structures with appropriate naming conventions

## Usage

### Basic Queries

| Prompt | Description |
|--------|-------------|
| "Search for human insulin structures with resolution better than 2.0 Å" | Multi-criteria protein search |
| "Download the PDB file for entry 1UBQ" | Single structure retrieval |
| "What ligands are bound in PDB entry 4HHB?" | Ligand information lookup |
| "Find all structures deposited in the last week" | Weekly release monitoring |

### Advanced Analysis

| Prompt | Description |
|--------|-------------|
| "Find X-ray structures of EGFR from Homo sapiens with resolution < 2.5 Å and list their ligands" | Advanced multi-criteria search with ligand extraction |
| "Download all structures for UniProt P00918 and compare their resolutions" | Batch download with quality comparison |
| "Search for structures containing ATP and generate a resolution distribution plot" | Search with visualization |
| "Generate an HTML report for the top 10 highest-resolution kinase structures" | Automated reporting |

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → PDB Search (LLM) → PDB Search Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** PDB Search container for managing and analyzing protein structure data from RCSB PDB

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
| `pdbSearch` | `tools/PDBSearch/` | PDBSearch is a tool designed for managing and analyzing protein structure data from the RCSB Protein Data Bank (PDB). It facilitates searching, dow... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.