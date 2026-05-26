````markdown
# Gromacs Tool & Agent Deployment Guide

This guide provides instructions for deploying the Gromacs molecular dynamics (MD) tool and its agent to the Microsoft Discovery platform. It's modeled after the `gromacs` deployment guide but tailored to the Gromacs container image and definitions in this folder.

## Overview

Gromacs is a production-grade build of Gromacs tuned for high-performance workflows (MPI/GPU-enabled options may be included depending on the provided Dockerfile). This deployment includes:

- **Dockerfile**: Container image definition for Gromacs
- **Tool Definition**: configuration for the Gromacs tool
- **Agent Definition**: AI agent configuration for Gromacs
## Prerequisites

Before deploying, ensure you have:

1. Access to the Microsoft Discovery platform
2. An Azure Container Registry (ACR) with push permissions
3. Docker installed locally for image builds (or a CI pipeline that builds images)
4. Azure CLI or PowerShell for resource management
5. Platform onboarding completed (see the user guide)

## Build Docker Image

1. **Build the image**:

   ```bash
   docker build -t gromacs:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag gromacs:latest mycontainerregistry.azurecr.io/gromacs:latest
   ```

   Replace `mycontainerregistry` with your ACR name.

3. **Login to ACR**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to ACR:

   ```bash
   docker push mycontainerregistry.azurecr.io/gromacs:latest
   ```

## Usage

- **Protein in Water (small)**: Attach a data asset named `protein-in-water-inputs` with prepared topology/coordinate files. Prompt: "Run short production MD and report radius of gyration over time." Expected runtime: ~10–20 minutes depending on infra.

- **Enzyme Simulation (longer)**: Attach `enzyme-inputs` and prompt: "Run production MD for X ns and compute RMSD relative to the crystal structure." Expected runtime: varies with simulation length and resources.

## File Structure

```text
gromacs/
├── Dockerfile
├── gromacs-tool-definition.yaml  # Tool configuration (YAML)
├── gromacs-agent-definition.yaml # Agent configuration (YAML)
├── example-input-files/          # Sample input files for testing (if present)
├── THIRD_PARTY_NOTICES.md        # Bundled OSS components and force-field licenses
└── README.md
```

## Force fields shipped

The container image installs the following protein/biomolecule force fields in
addition to the GROMACS-bundled set (`charmm27`, `oplsaa`, `gromos54a7`,
`amber99sb-ildn`, etc.):

| `-ff` name | Origin | Notes |
|---|---|---|
| `amber14sb` / `amber14sb_parmbsc1` | https://github.com/intbio/gromacs_ff | AMBER ff14SB protein parameters with parmbsc1 DNA corrections. Same files installed under both names; `amber14sb` is the protein-only display alias. |
| `charmm36m` | http://mackerell.umaryland.edu/charmm_ff.shtml (February 2026 release, CGenFF v5.0) | Modern CHARMM protein FF (C36m, Huang et al. 2017). `define = -DUSE_OLD_C36` in the MDP reverts to plain C36. |

See [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md) for licensing details —
notably that **commercial use of CHARMM/CGenFF parameters may require a separate
license** beyond the academic-free terms.

### Test Prompts

Attach the corresponding data asset (folder of input files) noted in each prompt.

- Run the SDS micellization simulation and calculate the diffusion coefficient: Use input files from the data asset attached here.
- Run energy minimization and short equilibration for the SDS system, then report potential energy and box dimensions after NPT equilibration.  
(use `example-input-files/sds/`)
- Run production MD for the SDS system, compute and report radial distribution function (RDF) between SDS headgroups and water oxygens, and estimate micelle aggregation number.
(use `example-input-files/sds/`)
- Prepare and run a full minimization → NVT → NPT → production workflow, then compute RMSD and radius of gyration over the trajectory.  
 (use `example-input-files/lysozyme/`)
- Run an ions-neutralization and equilibration sequence, then compute backbone RMSF and a short MM energy decomposition.  
 (use `example-input-files/factorXa/`)

These prompts are intentionally concise and actionable so the Gromacs agent and tool can assemble pipelines (preprocessing, `grompp`, `mdrun`, and postprocessing) using the supplied input files.


## Key Configuration Details

### Agent Capabilities

The Gromacs agent is expected to provide similar capabilities to the Gromacs agent:

- **Workflow planning**: assemble simulation pipelines (prep → minimization → equilibration → production)
- **Script generation**: create job scripts or helper scripts to run inside the container
- **Analysis**: compute common MD analyses (RMSD, RMSF, radius of gyration, energetic summaries)

### Resource Notes

- If using GPUs, ensure the cluster infra supports GPU scheduling and the container image includes CUDA/cuDNN compatible binaries.
- For MPI-enabled runs, use an MPI-capable base image and ensure the cluster infra supports multi-node MPI jobs.

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → GROMACS (LLM) → GROMACS Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** GROMACS container for high-performance molecular dynamics simulations

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
| `gromacs` | `tools/gromacs/` | Gromacs is designed for high-performance molecular dynamics (MD) simulations. It is primarily used to simulate the behavior of biomolecular systems... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.