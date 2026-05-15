# BoltzGen — Protein Binder Design Agent for Microsoft Discovery

## Overview

BoltzGen is a Discovery platform agent for **protein binder design** using diffusion models. Based on [HannesStark/boltzgen](https://github.com/HannesStark/boltzgen), it generates, folds, scores, and ranks binder designs for proteins, peptides, antibodies, nanobodies, and small-molecule binders.

**Key capabilities:**
- Design protein binders against arbitrary protein targets
- Design cyclic peptides and stapled peptides
- Design antibody and nanobody CDR loops
- Redesign and optimize existing proteins
- Design proteins that bind small molecules
- Automated quality filtering with diversity optimization

**Pipeline:** design → inverse folding → folding → design folding → affinity → analysis → filtering

**Stack:** PyTorch (CUDA) + Boltz-2 + diffusion models + rdkit

## Security

- **Last scan date**: See SECURITY.md (created during deployment)
- **Base image**: nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04
- **Non-root user**: appuser (UID 1000)
- **No embedded secrets**

## Prerequisites

- Microsoft Discovery platform access
- Azure Container Registry (ACR) access
- Docker Desktop (for local builds)
- Azure CLI (`az login`)
- **GPU nodepool required** (H100 or A100 recommended)

## Deployment Steps

### 1. Build Docker Image

```bash
cd 6-solutions/tools-and-models/boltzgen/

# Development build (no model weights — fast, ~10 min)
docker build --platform linux/amd64 --build-arg DOWNLOAD_WEIGHTS=false -t boltzgen:test .

# Production build (with model weights — slow, ~30 min, ~15GB image)
docker build --platform linux/amd64 -t boltzgen:latest .
```

### 2. Tag and Push to ACR

```bash
az acr login --name <your-acr-name>
docker tag boltzgen:latest <your-acr-name>.azurecr.io/boltzgen:latest
docker push <your-acr-name>.azurecr.io/boltzgen:latest
```

### 3. Update Tool Definition

Edit `boltzgen-tool-definition.yaml` and replace `{name}` with your ACR name.

### 4. Deploy to Discovery

Use Discovery management tools to publish the tool and agent definitions.

## Run Investigations

### Basic Calculations

| Prompt | Input File(s) | Description |
|--------|--------------|-------------|
| Design a protein binder against the target in 1G13 chain A, 60-100 residues | 1g13.cif | Protein binder design with automatic target extraction |
| Design a 15-25 residue peptide binder against EGFR | target EGFR .cif file | Peptide binder with peptide-anything protocol |
| Check if my design spec is valid | design_spec.yaml + target.cif | Validate YAML spec without running pipeline |

### Advanced Analysis

| Prompt | Description |
|--------|-------------|
| Generate 1000 protein binder designs for PD-L1 and select the best 20 | Large-scale design campaign with diversity filtering |
| Redesign residues 50-60 on chain A of my protein to improve binding | Protein redesign protocol |
| Design a nanobody against my target protein | Nanobody CDR design protocol |
| Merge results from three previous runs and re-filter with budget=50 | Merge + refilter workflow |
| Re-run filtering with relaxed RMSD threshold and no composition bias filter | Fast refiltering (~15 sec) |

## File Structure

```
boltzgen/
├── Dockerfile                          # CUDA + boltzgen + model weights
├── boltzgen-tool-definition.yaml       # Tool compute/infra specs
├── boltzgen-agent-definition.yaml      # Agent instructions for LLM
├── boltzgen_utils.py                   # Python utilities library
├── test_boltzgen_utils.py              # Unit tests (pytest)
├── README.md                           # This file
└── example-input-files/
    ├── README.md                       # Input file documentation
    ├── protein_binder_design.yaml      # Sample protein binder spec
    └── peptide_binder_design.yaml      # Sample peptide binder spec
```

## Agent Capabilities

| Capability | Protocol | GPU Required |
|-----------|----------|-------------|
| Protein binder design | protein-anything | Yes |
| Peptide binder design | peptide-anything | Yes |
| Small molecule binder design | protein-small_molecule | Yes |
| Antibody CDR design | antibody-anything | Yes |
| Nanobody CDR design | nanobody-anything | Yes |
| Protein redesign/optimization | protein-redesign | Yes |
| Design spec validation | N/A (boltzgen check) | No |
| Filtering/re-ranking | N/A (filtering step only) | No |

## Key Configuration Details

### num_designs Guidelines

| Scenario | num_designs | budget | Estimated Time (A100) |
|----------|------------|--------|----------------------|
| Quick test | 10-50 | 2-5 | 2-10 min |
| Small campaign | 100-500 | 10-20 | 15-60 min |
| Production | 10,000-60,000 | 20-100 | 3-18 hours |

### Model Weights

BoltzGen uses ~6GB of model weights from HuggingFace:
- `boltzgen1_diverse` — Diverse design checkpoint
- `boltzgen1_adherence` — Adherence design checkpoint
- `boltzgen1_ifold` — Inverse folding checkpoint
- `boltz2_conf_final` — Boltz-2 folding checkpoint
- `boltz2_aff` — Affinity prediction checkpoint
- `mols.zip` — Small molecule dictionary

Weights are baked into the production Docker image. For development, pass `--build-arg DOWNLOAD_WEIGHTS=false`.

## Additional Resources

- [BoltzGen GitHub](https://github.com/HannesStark/boltzgen)
- [BoltzGen PyPI](https://pypi.org/project/boltzgen/)
- [Design Specification Examples](https://github.com/HannesStark/boltzgen/tree/main/example)
- [Boltz-2 Model](https://github.com/jwohlwend/boltz)
