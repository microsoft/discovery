# OpenMM Tool & Agent Deployment Guide

## Overview

OpenMM is an open-source, GPU-accelerated molecular dynamics (MD) simulation toolkit with a rich Python API. This Discovery platform agent enables:

- **PDB preparation**: Fix missing atoms, add hydrogens, replace non-standard residues
- **System building**: Solvation, ionization, AMBER/CHARMM/OPLS force fields
- **Energy minimization**: Steepest descent with configurable tolerance
- **NVT/NPT equilibration**: Temperature ramping, barostat control
- **Production MD**: GPU-accelerated simulations with DCD trajectory output
- **Trajectory analysis**: RMSD, RMSF, radius of gyration, H-bonds, secondary structure, native contacts
- **Visualization**: Energy plots, RMSD/RMSF plots, secondary structure timelines

Supports CUDA, OpenCL, and CPU platforms with automatic selection.

## Prerequisites

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally
4. Azure CLI configured

## Quick Start

### Local Testing (Recommended First Step)

```bash
# Create virtual environment
python -m venv .venv-openmm
source .venv-openmm/bin/activate  # Linux/Mac
# or: .venv-openmm\Scripts\activate  # Windows

# Install test dependencies
pip install pytest numpy matplotlib pandas

# Run unit tests
pytest test_openmm_utils.py -v
```

### Docker Build & Test

```bash
# Build container
cd 6-solutions/tools-and-models/openmm/
docker build -t openmm:test .

# Verify installation
docker run openmm:test python3 -c "import openmm; print('OpenMM', openmm.__version__)"
docker run openmm:test python3 -c "from openmm_utils import *; print('OK')"

# Test with example files
docker run -v $(pwd)/example-input-files:/input \
           -v $(pwd)/test-output:/output \
           openmm:test python3 -c "
from openmm_utils import quick_setup, fix_pdb
quick_setup()
fixed = fix_pdb('alanine_dipeptide.pdb')
print('Fixed PDB:', fixed)
"
```

## Deployment Steps

### Step 1: Build and Push Docker Image

```bash
# Build
docker build -t openmm:latest .

# Tag for ACR
docker tag openmm:latest <your-acr>.azurecr.io/openmm:latest

# Login to ACR
az acr login --name <your-acr>

# Push
docker push <your-acr>.azurecr.io/openmm:latest
```

### Step 2: Update Tool Definition

Edit `openmm-tool-definition.yaml` and replace `{name}` with your ACR name:

```yaml
image:
  acr: "<your-acr>.azurecr.io/openmm:latest"
```

### Step 3: Deploy to Discovery Platform

```bash
# Deploy tool
discovery tool publish openmm-tool-definition.yaml

# Deploy agent
discovery agent publish openmm-agent-definition.yaml
```

### Step 4: Run Investigations

## Example Prompts

All examples use files from `example-input-files/`. Upload the specified files with your prompt.

### Energy Minimization

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Minimize the energy of alanine dipeptide" | `alanine_dipeptide.pdb` | Quick minimization test |
| "Fix and minimize this protein structure" | (your `.pdb`) | PDB repair + minimization |

### Full MD Simulation

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Run a 1 ns MD simulation of alanine dipeptide with AMBER ff14SB" | `alanine_dipeptide.pdb` | Full pipeline: minimize → NVT → NPT → production |
| "Simulate this protein for 10 ns and analyze RMSD and RMSF" | (your `.pdb`) | Production MD with trajectory analysis |

### Implicit Solvent

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Run an implicit solvent simulation of alanine dipeptide using GBn2" | `alanine_dipeptide.pdb` | Fast simulation without explicit water |

### Trajectory Analysis

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Analyze RMSD, RMSF, and hydrogen bonds from this trajectory" | `.dcd` + `.pdb` | Post-simulation analysis |
| "Compute secondary structure over the trajectory" | `.dcd` + `.pdb` | DSSP analysis |

### AMBER File Support

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Run MD from these AMBER topology and coordinate files" | `.prmtop` + `.inpcrd` | Pre-parameterized system |

## File Structure

```
openmm/
├── Dockerfile                       # Container definition
├── openmm-tool-definition.yaml      # Tool infrastructure config
├── openmm-agent-definition.yaml     # Agent AI config
├── openmm_utils.py                  # Utilities library
├── test_openmm_utils.py             # Unit tests
├── README.md                        # This file
└── example-input-files/
    ├── alanine_dipeptide.pdb         # Small test system (22 atoms)
    └── README.md                    # Example files documentation
```

## Agent Capabilities

### PDB Preparation
- Missing atom/residue repair via PDBFixer
- Non-standard residue replacement
- Protonation at user-specified pH
- Heterogen removal with optional water retention

### System Building
- AMBER (ff14SB), CHARMM (36/36m), OPLS force fields
- Explicit solvation with configurable box padding
- Implicit solvent (GBn2, OBC2)
- Ion addition to target ionic strength
- AMBER prmtop/inpcrd file support

### Simulation Execution
- Energy minimization with force tolerance control
- NVT equilibration with temperature ramping
- NPT equilibration with Monte Carlo barostat
- Production MD with DCD/checkpoint output
- Automatic GPU (CUDA/OpenCL) or CPU platform selection

### Trajectory Analysis (MDTraj)
- RMSD (Cα, backbone, all-atom, custom selections)
- Per-residue RMSF
- Radius of gyration
- Hydrogen bond analysis (Baker-Hubbard)
- DSSP secondary structure assignment
- Native contact fraction (Q-value)

### Visualization
- Energy/temperature/volume time series
- RMSD vs time plots
- Per-residue RMSF bar plots
- Secondary structure stacked area plots

## Key Configuration Details

### openmm_utils Library Reference

| Category | Functions |
|----------|-----------|
| Setup | `quick_setup()`, `quick_finish()`, `save_final_results()`, `copy_input_files()`, `copy_outputs()` |
| PDB Prep | `fix_pdb()` |
| System Building | `create_system()`, `create_system_from_amber()` |
| Simulation Setup | `select_platform()`, `setup_simulation()`, `add_barostat()`, `add_reporters()` |
| Simulation Run | `run_minimization()`, `run_nvt()`, `run_npt()`, `run_production()`, `save_positions_pdb()` |
| Parsing | `parse_log()` |
| Analysis | `compute_rmsd()`, `compute_rmsf()`, `compute_radius_of_gyration()`, `compute_hbonds()`, `compute_secondary_structure()`, `compute_contacts()` |
| Visualization | `plot_energy()`, `plot_rmsd()`, `plot_rmsf()`, `plot_secondary_structure()` |
| Cleanup | `openmm_cleanup()` |

### Force Fields

| Force Field | XML File | Best For |
|-------------|----------|----------|
| AMBER ff14SB | `amber14-all.xml` | Proteins, DNA, RNA |
| CHARMM36 | `charmm36.xml` | Proteins, lipids, nucleic acids |
| GBn2 (implicit) | `implicit/gbn2.xml` | Fast protein dynamics |
| OBC2 (implicit) | `implicit/obc2.xml` | Alternative implicit solvent |

### Compute Platforms

| Platform | Speed | Auto-detection |
|----------|-------|----------------|
| CUDA | Fastest | Preferred on GPU nodes |
| OpenCL | Fast | GPU fallback |
| CPU | Moderate | CPU-only nodes |
| Reference | Slow | Debugging only |

### Recommended SKUs

| SKU | GPUs | Best For |
|-----|------|----------|
| Standard_NC40ads_H100_v5 | 1x H100 | Production MD |
| Standard_D4s_v6 | 0 | Minimization, small systems |
| Standard_D8s_v6 | 0 | Medium CPU workloads |
| Standard_D16s_v6 | 0 | Large CPU workloads |
