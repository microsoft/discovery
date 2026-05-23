
# LAMMPS Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the LAMMPS (Large-scale Atomic/Molecular Massively Parallel Simulator) tool and its associated agent to the Microsoft Discovery platform.

## Overview

LAMMPS is a high-performance molecular dynamics simulation tool supporting a wide range of materials modeling capabilities. This deployment includes:

- **Dockerfile**: Used for creation of the LAMMPS tool container image
- **Tool Definition**: Configuration for the LAMMPS CPU tool
- **Agent Definition**: AI agent configuration for orchestrating LAMMPS simulations
- **lammps_utils Library**: Python utilities for running simulations and analyzing results

## Prerequisites

Before starting the deployment, ensure you have:

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally for image building
4. Azure CLI or PowerShell for resource management

## Build Docker Image

### Step 1: Build and Publish Docker Image


   ```bash
   docker build -t lammps-cpu:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag lammps-cpu:latest mycontainerregistry.azurecr.io/lammps-cpu:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/lammps-cpu:latest
   ```

## File Structure

```text
lammps/
├── Dockerfile                          # Container image definition
├── lammps-cpu-tool-definition.yaml     # Tool configuration (YAML)
├── lammps-cpu-agent-definition.yaml    # Agent configuration (YAML)
├── lammps_utils.py                     # Python utilities library
├── test_lammps_utils.py                # Unit tests for utilities
├── sample-questions.md                 # Example prompts for the agent
└── README.md                           # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The LAMMPS agent provides:

- **Simulation Orchestration**: Automatically runs LAMMPS simulations with optimal parallelization
- **Thermal Conductivity Analysis**: NEMD (enhanced heat exchange) and Green-Kubo methods
- **Transport Properties**: Diffusion coefficient from MSD, viscosity calculations
- **Structural Analysis**: RDF, density profiles, radius of gyration
- **Mechanical Properties**: Stress-strain analysis, elastic modulus calculation
- **Parameter Sweeps**: Automated generation of input files for parametric studies
- **Statistical Analysis**: Block averaging, autocorrelation functions with proper error estimation

### lammps_utils Library Reference

The container includes a pre-installed `lammps_utils` library with the following functions:

#### Setup & File Operations
| Function | Description |
|----------|-------------|
| `quick_setup()` | Initialize logging, create directories, copy input files |
| `quick_finish()` | Copy output files to /output directory |
| `save_final_results(results, output_files, file_descriptions, status)` | **MANDATORY**: Save results to `/output/final_results.json` |
| `copy_input_files(patterns)` | Copy specific file patterns from /input |
| `copy_outputs(patterns)` | Copy specific output patterns to /output |
| `NUM_CORES` | Number of available CPU cores |

#### Execution
| Function | Description |
|----------|-------------|
| `run_lammps(input_file, log_file, num_atoms, auto_detect)` | Run LAMMPS with optimal parallelization |
| `auto_detect_atom_count(input_file)` | Detect atom count from input/data files |
| `run_command(command_list)` | Execute any subprocess command |

#### Simulation Parameter Extraction
| Function | Description |
|----------|-------------|
| `get_simulation_parameters_from_input(input_file, data_file)` | Extract units, timestep, temperature, heat flux, box dimensions |
| `get_box_dimensions_from_data_file(data_file)` | Get Lx, Ly, Lz, volume from data file |
| `get_heat_flux_from_input(input_file)` | Parse heat flux from fix ehex/heat commands |
| `get_atom_count_from_data_file(data_file)` | Get atom count from data file header |
| `get_data_file_from_input(input_file)` | Find data file path from read_data command |

#### Thermal Conductivity Analysis
| Function | Description |
|----------|-------------|
| `parse_temperature_profile(filename)` | Parse out.T* files -> array[z, T] |
| `compute_thermal_conductivity_nemd(T_profile, heat_flux, area)` | Compute κ from NEMD |
| `parse_hfacf(filename, use_final_block)` | Parse Green-Kubo HFACF output |
| `compute_thermal_conductivity_gk(hfacf_data, volume, temp, timestep)` | Compute κ from Green-Kubo |
| `analyze_energy_drift(energy_file)` | Analyze energy conservation |

#### Trajectory & Structural Analysis
| Function | Description |
|----------|-------------|
| `parse_dump_file(filename, frame)` | Parse LAMMPS dump files |
| `parse_rdf_file(filename)` | Parse RDF output -> {r, g_r, coord} |
| `parse_msd_file(filename)` | Parse MSD output -> {time, msd, msd_components} |
| `parse_density_profile(filename)` | Parse density profiles |
| `parse_gyration_file(filename)` | Parse radius of gyration |

#### Transport Properties
| Function | Description |
|----------|-------------|
| `compute_diffusion_coefficient(msd_data, timestep, dimensions)` | Compute D from MSD via Einstein relation |

#### Mechanical Properties
| Function | Description |
|----------|-------------|
| `parse_stress_strain(log_file, strain_component, stress_component)` | Extract stress-strain data |
| `compute_elastic_modulus(stress_strain_data, strain_range)` | Compute Young's modulus and yield stress |
| `compute_surface_tension(log_file, box_normal)` | Compute γ from pressure tensor anisotropy |

#### Statistical Analysis
| Function | Description |
|----------|-------------|
| `block_average(data, num_blocks)` | Block averaging with proper error estimation |
| `autocorrelation_function(data, max_lag)` | Compute ACF and correlation time |
| `parse_log_file(log_file, columns)` | Extract thermo data from log |

#### Visualization
| Function | Description |
|----------|-------------|
| `plot_temperature_profile(T_profile, output_file)` | Plot NEMD temperature profile |
| `plot_rdf(rdf_data, output_file)` | Plot radial distribution function |
| `plot_msd(msd_data, timestep, output_file, fit_result)` | Plot MSD with diffusion fit |
| `plot_stress_strain(data, output_file, modulus_result)` | Plot stress-strain curve |
| `plot_acf(acf_data, output_file)` | Plot autocorrelation function |

## Example Script Template

```python
from lammps_utils import (
    quick_setup, quick_finish, run_lammps, save_final_results,
    parse_temperature_profile, compute_thermal_conductivity_nemd,
    get_simulation_parameters_from_input
)
import logging

# ============= SETUP =============
quick_setup()

# ============= GET SIMULATION PARAMETERS =============
params = get_simulation_parameters_from_input("in.lj.ehex")
area = params['box']['Lx'] * params['box']['Ly']
heat_flux = params['heat_flux']

# ============= RUN SIMULATION =============
run_lammps("in.lj.ehex", "simulation.log")

# ============= ANALYSIS =============
T_profile = parse_temperature_profile("out.Tlj_ehex")
result = compute_thermal_conductivity_nemd(T_profile, heat_flux, area)
logging.info(f"Thermal conductivity: {result['kappa']:.4f}")

# ============= SAVE RESULTS (MANDATORY) =============
save_final_results(
    results={
        "thermal_conductivity": result['kappa'],
        "thermal_conductivity_std_err": result['kappa_std_err'],
        "method": "NEMD-eHEX"
    },
    output_files={"log": "/output/simulation.log"},
    file_descriptions={"log": "LAMMPS simulation log"}
)

# ============= FINISH =============
quick_finish()
```

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → LAMMPS CPU (LLM) → LAMMPS CPU Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** LAMMPS CPU container for molecular simulations with MDAnalysis, ASE, and freud

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{model}}` | Azure AI Foundry model deployment name | `gpt-4o` |

## Usage

### Basic Simulations

| Prompt | Description |
|--------|-------------|
| "Run the LJ eHEX thermal conductivity simulation and report the computed thermal conductivity" | Basic NEMD thermal conductivity calculation |
| "Run energy minimization on the provided data file and report the final potential energy" | Simple energy minimization |
| "Run a short equilibration of the SPC/E water system and report temperature and density over time" | NVT/NPT equilibration |

### Analysis & Transport Properties

| Prompt | Description |
|--------|-------------|
| "Compute the radial distribution function for the LJ system and plot g(r)" | Structural analysis with RDF |
| "Calculate the diffusion coefficient from the MSD output of my simulation" | Transport property from mean squared displacement |
| "Analyze the stress-strain data from my tensile test and compute the elastic modulus" | Mechanical property extraction |

### Advanced Investigations

| Prompt | Description |
|--------|-------------|
| "For both LJ and SPC/E, quantify how HEX and eHEX differ in energy drift, steady-state temperature profile, and computed thermal conductivity" | Algorithmic comparison across force fields |
| "How does the computed thermal conductivity change with system length in the gradient direction?" | Finite-size effect analysis |
| "What is the statistical uncertainty in the measured thermal conductivity, and how does it scale with simulation time?" | Convergence and error estimation |

> For additional advanced prompts with detailed input file requirements, see `tools/lammps-cpu/sample-questions.md`.

## Support

For issues or questions, open a GitHub issue:
<https://github.com/microsoft/discovery-catalog/issues>

Microsoft Discovery team contact: discovery-catalog@microsoft.com


## Tools

| Tool | Path | Description |
|---|---|---|
| `lammpsCpu` | `tools/lammps-cpu/` | LAMMPS is a molecular simulation tool. |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.