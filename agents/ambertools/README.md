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

## Build Docker Image


```bash
cd 6-solutions/tools-and-models/ambertools/
docker build --platform linux/amd64 -t ambertools:latest .
docker tag ambertools:latest <your-acr>.azurecr.io/ambertools:latest
az acr login --name <your-acr>
docker push <your-acr>.azurecr.io/ambertools:latest
```

## Usage

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

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → AmberTools (LLM) → AmberTools Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** AmberTools container (sander, tleap, cpptraj, antechamber) for biomolecular simulations

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
| `amberTools` | `tools/ambertools/` | AmberTools is a comprehensive suite of programs for biomolecular simulation. |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.