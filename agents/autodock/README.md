# AutoDock Vina Tool & Agent Deployment Guide

## Overview

AutoDock Vina is a molecular docking program widely used for structure-based drug design and virtual screening. This Discovery platform agent enables:

- **Protein-ligand docking**: Predict binding poses and affinities
- **Virtual screening**: Screen compound libraries against targets
- **Binding site analysis**: Identify and characterize binding sites
- **Structure-based drug design**: Optimize lead compounds

## Prerequisites

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally
4. Azure CLI configured

## Quick Start

### Local Testing (Recommended First Step)

```bash
# Create virtual environment
python -m venv .venv-autodock
source .venv-autodock/bin/activate  # Linux/Mac
# or: .venv-autodock\Scripts\activate  # Windows

# Install test dependencies
pip install pytest numpy matplotlib pandas

# Run unit tests
pytest test_autodock_utils.py -v
```

### Docker Build & Test

```bash
# Build container
cd 6-solutions/tools-and-models/autodock/
docker build -t autodock:test .

# Verify installation
docker run autodock:test vina --version
docker run autodock:test python3 -c "from autodock_utils import *; print('OK')"

# Test with example files
docker run -v $(pwd)/example-input-files/1hsg-indinavir:/input \
           -v $(pwd)/test-output:/output \
           autodock:test python3 -c "
from autodock_utils import quick_setup, list_input_files
quick_setup()
print('Input files:', list_input_files())
"
```

## Build Docker Image


```bash
# Build
docker build -t autodock:latest .

# Tag for ACR
docker tag autodock:latest <your-acr>.azurecr.io/autodock:latest

# Login to ACR
az acr login --name <your-acr>

# Push
docker push <your-acr>.azurecr.io/autodock:latest
```

## Usage

All examples use files from `example-input-files/1hsg-indinavir/`. Upload the specified files with your prompt.

### Basic Docking

| Prompt | Input Files |
|--------|-------------|
| "Dock indinavir to HIV protease" | `1hsg_protein.pdb`, `indinavir.sdf`, `reference_ligand.pdb` |
| "Predict the binding affinity of indinavir" | `1hsg_protein.pdb`, `indinavir.sdf`, `reference_ligand.pdb` |
| "Find the best binding pose for saquinavir" | `1hsg_protein.pdb`, `saquinavir.sdf`, `reference_ligand.pdb` |

### Virtual Screening

| Prompt | Input Files |
|--------|-------------|
| "Screen all ligands against HIV protease and rank by affinity" | `1hsg_protein.pdb`, `indinavir.sdf`, `ritonavir.sdf`, `saquinavir.sdf`, `nelfinavir.sdf`, `reference_ligand.pdb` |
| "Find the best HIV protease inhibitor from these compounds" | `1hsg_protein.pdb`, `indinavir.sdf`, `ritonavir.sdf`, `saquinavir.sdf`, `nelfinavir.sdf`, `reference_ligand.pdb` |

### Binding Site Definition

| Prompt | Input Files |
|--------|-------------|
| "Dock indinavir using active site residues ASP25, ILE50, VAL82" | `1hsg_protein.pdb`, `indinavir.sdf` |
| "Dock using the co-crystallized ligand position for the grid box" | `1hsg_protein.pdb`, `indinavir.sdf`, `reference_ligand.pdb` |

## Example Input Files

All example files are in `example-input-files/1hsg-indinavir/`. See the [example README](example-input-files/1hsg-indinavir/README.md) for detailed file descriptions.

## File Structure

```
autodock/
├── Dockerfile                           # Container definition
├── autodock-tool-definition.yaml        # Tool infrastructure config
├── autodock-agent-definition.yaml       # Agent AI config
├── autodock_utils.py                    # Utilities library
├── test_autodock_utils.py               # Unit tests
├── README.md                            # This file
└── example-input-files/
    └── 1hsg-indinavir/
        ├── README.md                    # Example documentation
        ├── 1hsg.pdb                     # Full crystal structure from RCSB
        ├── 1hsg_protein.pdb             # Protein only (no waters/ligands)
        ├── mk1_ligand.pdb               # Co-crystallized ligand from PDB
        ├── reference_ligand.pdb         # Grid box reference (same as mk1_ligand)
        ├── indinavir.sdf                # Indinavir ligand for docking
        ├── ritonavir.sdf                # Ritonavir ligand for screening
        ├── saquinavir.sdf               # Saquinavir ligand for screening
        ├── nelfinavir.sdf               # Nelfinavir ligand for screening
        └── config.txt                   # Sample Vina config
```

## Agent Capabilities

### File Preparation
- PDB to PDBQT receptor conversion
- Ligand preparation from SDF, MOL2, SMILES
- Automatic hydrogen addition and protonation

### Grid Box Configuration
- Automatic calculation from reference ligand
- Residue-based binding site definition
- Manual center/size specification

### Docking Operations
- Single ligand docking with AutoDock Vina
- Batch docking for virtual screening
- Configurable exhaustiveness and pose count

### Analysis & Visualization
- Binding affinity ranking
- Ligand efficiency calculation
- Pose comparison plots
- Interaction analysis

## Key Configuration Details

### autodock_utils Library Reference

| Category | Functions |
|----------|-----------|
| Setup | `quick_setup()`, `quick_finish()`, `save_final_results()` |
| Preparation | `pdb_to_pdbqt_receptor()`, `prepare_ligand()`, `smiles_to_pdbqt()` |
| Grid Box | `calculate_grid_box_from_ligand()`, `calculate_grid_box_from_residues()`, `create_grid_box()` |
| Docking | `run_vina()`, `batch_dock()`, `write_vina_config()` |
| Analysis | `rank_docking_results()`, `calculate_ligand_efficiency()`, `calculate_binding_site_contacts()` |
| Output | `split_pdbqt_models()`, `extract_pose()`, `pdbqt_to_pdb()`, `pdbqt_to_sdf()` |
| Visualization | `plot_docking_scores()`, `plot_pose_comparison()`, `create_results_summary_table()` |

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "No poses generated" | Grid box too small/misplaced | Increase box size or check center |
| "Search space too large" | Box > 126 Å | Focus on specific binding site |
| "PDBQT parse error" | Invalid file format | Validate with `validate_pdbqt()` |
| "Ligand outside box" | Wrong grid center | Use reference ligand for box |

### Performance Optimization

- Use `exhaustiveness=16` for screening (faster)
- Use `exhaustiveness=64` for final poses (more thorough)
- Limit `num_modes=5` for virtual screening
- Pre-filter ligands by drug-likeness before screening

## Citation

If you use AutoDock Vina in your research, please cite:

> Eberhardt, J., Santos-Martins, D., Tillack, A.F., Forli, S. (2021).
> AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings.
> *Journal of Chemical Information and Modeling*.

## License

- AutoDock Vina: Apache-2.0
- This agent package: Apache-2.0

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → AutoDock Vina (LLM) → AutoDock Vina Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** AutoDock Vina container for protein-ligand molecular docking

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
| `autoDock` | `tools/autodock/` | AutoDock Vina molecular docking tool for protein-ligand binding affinity prediction, virtual screening, and drug discovery workflows |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.