# CP2K Agent for Microsoft Discovery

## Overview

CP2K is an open-source atomistic simulation package for DFT (GPW/GAPW), ab initio molecular dynamics, geometry optimization, vibrational analysis, band structure, NEB, and semi-empirical methods. This agent provides a Python code environment with CP2K and scientific analysis tools.

## Capabilities

| Feature               | Method                                 | Status          |
| --------------------- | -------------------------------------- | ---------       |
| DFT Energy            | PBE, BLYP, BP86, PADE (+ D3/D4)        | Supported       |
| Hybrid DFT            | B3LYP, PBE0, HSE06                     | Disabled        |
| Geometry Optimization | BFGS, CG, L-BFGS                       | Supported       |
| Ab Initio MD          | NVT, NPT, NVE                          | Supported       |
| Vibrational Analysis  | Finite differences                     | Supported       |
| Band Structure        | k-point path sampling                  | Supported       |
| Cell Optimization     | Variable cell                          | Supported       |
| Nudged Elastic Band   | CI-NEB                                 | Supported       |
| Semi-empirical        | DFTB, xTB                              | Supported       |

## Docker Image

- **Registry**: `{name}.azurecr.io/cp2k:v19`
- **Compressed size**: ~803 MB
- **Base**: `mambaorg/micromamba:1.5-jammy` (2-stage build)
- **CP2K**: Source-built with DFT-D4 support (`cp2k.psmp` MPI+OMP, `cp2k.ssmp` OMP-only fallback)
- **Hybrid DFT**: still blocked in `cp2k_utils.py` pending stable libint/HFX validation
- **Python**: 3.11 with numpy, scipy, matplotlib, pandas, ASE, pymatgen, cp2k-input-tools, MDAnalysis

## Key Files

| File                         | Purpose                                                           |
| ---------------------------- | ----------------------------------------------------------------- |
| `Dockerfile`                 | 2-stage multi-stage build                                         |
| `cp2k_utils.py`              | 56 functions: setup, input gen, execution, parsing, molecule prep, trajectory analysis, visualization |
| `test_cp2k_utils.py`         | 72 unit tests (including molecule prep and trajectory analysis coverage) |
| `cp2k-tool-definition.yaml`  | Tool compute/infra specs                                          |
| `cp2k-agent-definition.yaml` | Agent instructions (22.5 KB, under 30 KB limit)                   |

## MPI/OMP Parallelization

`cp2k_utils._get_mpi_omp_split()` auto-computes the optimal MPI rank x OMP thread split:

- Targets 4 OMP threads per rank (sweet spot for CP2K's DBCSR library)
- Reserves 1 core for system overhead
- No artificial rank cap -- scales to large HPC nodes (e.g. HBv4 176 cores -> 43 ranks x 4 threads)
- CMA bus errors in containers are handled via `OMPI_MCA_btl_vader_single_copy_mechanism=none`

## Usage

1. "Calculate the DFT energy of a water molecule using PBE/DZVP"
2. "Optimize the geometry of ethanol at the PBE-D3 level"
3. "Run a 1 ps NVT molecular dynamics simulation of liquid water at 300 K"
4. "Calculate the band structure of silicon along G-X-W-L-G path"
5. "Perform a vibrational frequency analysis of CO2"

## Validation Results

All tests passed on the Discovery supercomputer (nodepool01, Standard_D4s_v6):

| Test           | Result | Detail                                            |
| -------------- | ------ | ------------------------------------------------- |
| Import         | PASS   | All 56 cp2k_utils functions                       |
| Data files     | PASS   | 54 files in CP2K data directory                   |
| Basis sets     | PASS   | 421 basis sets, 162 pseudopotentials              |
| Structure I/O  | PASS   | XYZ read/write                                    |
| DFT Energy     | PASS   | Water PBE/DZVP = -17.2196 Ha, 15 SCF cycles, 7.6s |
| Output Parsing | PASS   | Energy, convergence, SCF data                     |
| Visualization  | PASS   | SCF convergence plot (40 KB PNG)                  |
| Geometry Opt   | PASS   | Water converged at -17.2201 Ha, 32s               |

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → CP2K (LLM) → CP2K Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** CP2K container for atomistic simulations, DFT calculations, and materials modeling

## Prerequisites

- Azure subscription with Contributor role
- Azure AI Foundry project with a model deployment (e.g. GPT-4o)
- Docker for building the tool container image
- Azure Container Registry (ACR) for hosting the tool image

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
| `cp2k` | `tools/cp2k/` | CP2K atomistic simulation tool for DFT (GPW/GAPW), ab initio molecular dynamics, |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.