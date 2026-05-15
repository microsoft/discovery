# AmberTools Agent Deployment Guide

## Overview

AmberTools is a freely available suite of programs for biomolecular simulation, distributed as part of the AMBER software package. This Discovery platform agent provides access to:

- **sander**: Molecular dynamics engine (CPU, MPI parallel)
- **tleap**: System preparation (topology building, solvation, ion addition)
- **cpptraj**: Trajectory analysis (RMSD, RMSF, hydrogen bonds, secondary structure, RDF)
- **antechamber**: Small molecule parameterization (AM1-BCC charges, GAFF2 atom types)
- **parmchk2**: Missing force field parameter detection
- **pdb4amber**: PDB file cleanup and standardization
- **parmed/pytraj**: Python interfaces for topology and trajectory manipulation

## Prerequisites

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) access
3. Docker installed locally
4. Azure CLI configured

## Deployment Steps

### Step 1: Build and Publish Docker Image

```bash
cd 6-solutions/tools-and-models/ambertools/
docker build --platform linux/amd64 -t ambertools:latest .
docker tag ambertools:latest <your-acr>.azurecr.io/ambertools:latest
az acr login --name <your-acr>
docker push <your-acr>.azurecr.io/ambertools:latest
```

### Step 2: Update Tool Definition

Edit `ambertools-tool-definition.yaml` and set the ACR path:
```yaml
image:
  acr: "<your-acr>.azurecr.io/ambertools:latest"
```

### Step 3: Deploy Platform Resources

Use the Discovery workbench to publish the tool and agent definitions.

## Run Investigations

### System Preparation

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Prepare this protein for MD simulation with ff14SB and TIP3P water" | protein.pdb | Full prep: pdb4amber + tleap (solvate, neutralize) + minimize |
| "Parameterize this small molecule with GAFF2 and AM1-BCC charges" | molecule.sdf | antechamber + parmchk2 + tleap topology |
| "Set up a protein-ligand complex for simulation" | protein.pdb, ligand.mol2 | Ligand parameterization + complex assembly |

### Molecular Dynamics

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Run a short MD simulation and analyze the trajectory" | protein.pdb | Full workflow: prep + min + heat + equil + prod + analysis |
| "Run 1 ns of MD and compute RMSD, RMSF, and hydrogen bonds" | protein.pdb | Production MD with comprehensive cpptraj analysis |
| "Minimize this protein structure and report the final energy" | protein.pdb | System prep + energy minimization only |

### Analysis Only

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Compute RMSD and RMSF for this trajectory" | system.prmtop, traj.nc | cpptraj-based structural analysis |
| "Analyze hydrogen bonding patterns" | system.prmtop, traj.nc | H-bond statistics and time series |
| "Calculate radius of gyration over time" | system.prmtop, traj.nc | Compactness analysis |

## File Structure

```
ambertools/
├── Dockerfile                         # Container image (micromamba + AmberTools)
├── ambertools-tool-definition.yaml    # Tool compute specs
├── ambertools-agent-definition.yaml   # Agent instructions (<30KB)
├── ambertools_utils.py                # Python utilities library
├── test_ambertools_utils.py           # Unit tests (57 tests)
├── README.md                          # This file
└── example-input-files/
    ├── alanine-dipeptide.pdb          # Minimal peptide (22 atoms)
    ├── 1l2y.pdb                       # Trp-cage miniprotein (20 residues)
    ├── aspirin.sdf                    # Small molecule for parameterization
    └── README.md                      # File descriptions
```

## Agent Capabilities

- System preparation with automatic force field and water model selection
- Full MD workflow: minimization, NVT heating, NPT equilibration, production
- MPI-parallel sander for multi-core execution
- Small molecule parameterization with GAFF2 and AM1-BCC charges
- Comprehensive trajectory analysis via cpptraj wrappers
- Publication-quality matplotlib visualizations
- Automatic output in final_results.json format

## Force Fields

| Force Field | Use Case |
|-------------|----------|
| ff14SB | Proteins (recommended default) |
| ff19SB | Proteins (newer, CMAP terms) |
| GAFF2 | Small molecules, drug-like compounds |
| OL15 | DNA |
| RNA.OL3 | RNA |
| Lipid21 | Lipid membranes |

## Additional Resources

- [AmberTools Manual](https://ambermd.org/AmberTools.php)
- [AMBER Tutorials](https://ambermd.org/tutorials/)
- [AMBER Force Fields](https://ambermd.org/AmberModels.php)
- [cpptraj Documentation](https://amberhub.chpc.utah.edu/cpptraj/)
