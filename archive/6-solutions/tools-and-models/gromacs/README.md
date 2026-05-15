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

## Deployment Steps

### Step 1: Build and Publish Docker Image

1. **Build the Docker image** from the provided Dockerfile in this folder:

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

### Step 2: Update Tool Definition

1. Edit the tool definition file (e.g., `gromacs-tool-definition.yaml`) and update the image path:

   ```yaml
   infra:
     - name: worker
       infra_type: container
       image:
         acr: mycontainerregistry.azurecr.io/gromacs:latest
   ```

2. If the tool requires GPUs or MPI, ensure the infra section and resource requests reflect those requirements.

### Step 3: Convert YAML to JSON

Use the provided utility to convert YAML tool and agent definitions to JSON (the platform expects JSON payloads):

```bash
python3 ../../utils/definition-content-creator.py gromacs-tool-definition.yaml --output gromacs-tool-definition.json --json

python3 ../../utils/definition-content-creator.py gromacs-agent-definition.yaml --output gromacsAgent.json --json
```

### Step 4: Deploy Platform Resources

Follow the same sequence used for other tools on the platform:

- Create the Tool resource using the generated JSON
- Create the Agent resource using the generated agent JSON
- Create a Workflow that uses the agent for MD investigations
- Create a Project to organize runs and investigations
- Create Data Assets (folder-type) for example inputs
- Create an Investigation and run sample prompts

See the platform guides for detailed steps:

- Tool Deployment Guide: ../../../4-how-to/6-tools-models-agents/b--tool-deployment.md
- Agent Deployment Guide: ../../../4-how-to/6-tools-models-agents/c--agent-deployment.md
- Project Creation Guide: ../../../4-how-to/7-projects/a--creating-project.md

## Example Investigations

- **Protein in Water (small)**: Attach a data asset named `protein-in-water-inputs` with prepared topology/coordinate files. Prompt: "Run short production MD and report radius of gyration over time." Expected runtime: ~10–20 minutes depending on infra.

- **Enzyme Simulation (longer)**: Attach `enzyme-inputs` and prompt: "Run production MD for X ns and compute RMSD relative to the crystal structure." Expected runtime: varies with simulation length and resources.

## File Structure

```text
gromacs/
├── Dockerfile
├── gromacs-tool-definition.yaml  # Tool configuration (YAML)
├── gromacs-agent-definition.yaml # Agent configuration (YAML)
├── example-input-files/          # Sample input files for testing (if present)
└── README.md
```

## Test prompts

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

## Additional Resources

- Microsoft Discovery Documentation: ../../
- Container Image Creation Guide: ../../../4-how-to/5-tool-image/a--create-and-publish-container-image.md
- Gromacs Official Documentation: http://manual.gromacs.org/

## Support

For platform-specific issues, consult the user guide or contact your platform administrator.

File: [6-solutions/tools-and-models/gromacs/README.md](6-solutions/tools-and-models/gromacs/README.md)

````
