
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
5. Completed platform onboarding (see [user guide](../../../4-how-to/))

## Deployment Steps

### Step 1: Build and Publish Docker Image

1. **Build the Docker image** from the provided Dockerfile:

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

### Step 2: Update Tool Definition

1. **Edit the tool definition file** (`lammps-cpu-tool-definition.yaml`)
2. **Update the ACR path** in the image section:

   ```yaml
   infra:
     - name: worker
       infra_type: container
       image:
         acr: mycontainerregistry.azurecr.io/lammps-cpu:latest  # Update this line
   ```

   > Replace `mycontainerregistry` with your actual ACR name

### Step 3: Convert YAML to JSON

Use the provided utility to convert YAML definitions to JSON format required by the platform:

1. **Convert the tool definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py lammps-cpu-tool-definition.yaml --output lammps-cpu-tool-definition.json --json
   ```

2. **Convert the agent definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py lammps-cpu-agent-definition.yaml --output lammps-cpu-agent-definition.json --json
   ```

### Step 4: Deploy Platform Resources

#### 4.1 Create Tool Resource

Deploy the LAMMPS tool to the Discovery platform using the generated JSON definition. This creates the computational environment for running molecular dynamics simulations.

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/b--tool-deployment.md) for detailed steps

#### 4.2 Create Agent Resource

Deploy the LAMMPS agent using the agent JSON definition. This creates the AI agent that can orchestrate LAMMPS simulations and analysis workflows.

> **Reference**: See [Agent Deployment Guide](../../../4-how-to/6-tools-models-agents/c--agent-deployment.md) for detailed steps

#### 4.3 Create Workflow Resource

Create a workflow that utilizes the LAMMPS agent for molecular dynamics simulations.

#### 4.4 Create Project Resource

Set up a project to organize and manage your molecular simulation workflows.

> **Reference**: See [Project Creation Guide](../../../4-how-to/7-projects/a--creating-project.md) for detailed steps

#### 4.5 Create an Investigation

Create a project investigation that utilizes the LAMMPS agent for molecular simulations.

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/8-investigations/a--creating-investigation.md) for detailed steps

#### 4.6 Run an investigation

Run the investigation with prompts such as:

- "Run a thermal conductivity simulation using the NEMD method with the provided LJ fluid data."
  (requires: `in.lj.ehex` + `data.lj`, or `in.spce.ehex` + `data.spce` for water)

- "Calculate the diffusion coefficient from an MSD simulation."
  (requires: `data.lj` or `data.spce` - agent generates input script with `compute msd`)

- "Compute the radial distribution function (RDF) for this molecular system."
  (requires: `data.lj` or `data.spce` - agent generates input script with `compute rdf`)

- "Perform a Green-Kubo calculation for thermal conductivity."
  (requires: `in.lj.gk` + `data.lj` for equilibrium heat flux autocorrelation)

- "Run a parameter sweep varying the timestep to study energy conservation."
  (requires: `in.lj.ehex` + `data.lj` - agent modifies timestep parameter)

- "Compare HEX vs eHEX algorithms for thermal conductivity."
  (requires: `in.lj.hex` + `in.lj.ehex` + `data.lj`)

**File extensions:**
- `in.*` - LAMMPS input/control files (e.g., `in.lj.ehex`, `in.lj.gk`)
- `data.*` - LAMMPS data files with atom positions, topology, box dimensions (e.g., `data.lj`, `data.spce`)

Wait for response and check the generated outputs.

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

### Supported File Types

- **LAMMPS Input Files**: in.*, *.lmp, *.in
- **LAMMPS Data Files**: data.*, *.data
- **Force Field Files**: *.params, *.ff
- **Output Files**: *.log, *.lammpstrj, *.restart, out.*, *.dat
- **Visualization**: PNG

### Force Fields Available

| Force Field | Applications |
|-------------|--------------|
| LJ/cut | Lennard-Jones (simple fluids) |
| EAM | Metals and alloys |
| Tersoff | Semiconductors, carbon |
| ReaxFF | Reactive chemistry |
| CHARMM/AMBER | Biomolecules |
| OPLS-AA | Organic molecules |

### Parallelization Guidelines

The agent automatically selects optimal parallelization:

| System Size | Strategy | Notes |
|-------------|----------|-------|
| < 5,000 atoms | OpenMP | Lower communication overhead |
| ≥ 5,000 atoms | MPI | Better scaling for large systems |

### Directory Structure (Container)

- **Input files**: `/input/` (read-only)
- **Working directory**: `/workdir/`
- **Output files**: `/output/`

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

## Additional Resources

- [Microsoft Discovery Documentation](../../)
- [Container Image Creation Guide](../../../4-how-to/5-tool-image/a--create-and-publish-container-image.md)
- [LAMMPS Official Documentation](https://docs.lammps.org/)

## Support

For platform-specific issues, refer to the [user guide documentation](../../../4-how-to/) or contact your platform administrator.
