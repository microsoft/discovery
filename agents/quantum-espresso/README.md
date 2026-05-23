
# Quantum ESPRESSO Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the Quantum ESPRESSO tool and its associated agent to the Microsoft Discovery platform.

## Overview

Quantum ESPRESSO is a leading open-source package for electronic structure calculations and materials modeling using density functional theory (DFT). This deployment includes:

- **Dockerfile**: Multi-stage build for the Quantum ESPRESSO container image
- **Tool Definition**: Configuration for the QE CPU tool
- **Agent Definition**: AI agent configuration for orchestrating DFT calculations
- **SSSP Pseudopotentials**: Pre-installed SSSP Efficiency v1.3.0 library

## Prerequisites

Before starting the deployment, ensure you have:

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally for image building
4. Azure CLI or PowerShell for resource management

## Build Docker Image

### Step 1: Build and Publish Docker Image


   ```bash
   docker build -t quantum-espresso:cpu .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag quantum-espresso:cpu mycontainerregistry.azurecr.io/quantum-espresso:cpu
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/quantum-espresso:cpu
   ```

## File Structure

```text
quantum-espresso/
├── Dockerfile                          # Multi-stage container build
├── qe_utils.py                         # Python utilities library (installed in container)
├── qe-tool-definition.yaml             # Tool configuration (YAML)
├── qe-agent-definition.yaml            # Agent configuration (YAML)
├── example-input-files/
│   └── silicon/
│       ├── si.scf.in                   # SCF calculation example
│       ├── si.nscf.in                  # NSCF for DOS
│       ├── si.bands.in                 # Band structure example
│       ├── si.dos.in                   # DOS post-processing
│       ├── si.pdos.in                  # Projected DOS
│       ├── si.relax.in                 # Atomic relaxation
│       ├── si.vc-relax.in              # Variable-cell relaxation
│       ├── si.ph.in                    # Phonon at Gamma
│       └── README.md                   # Silicon examples guide
└── README.md                           # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The Quantum ESPRESSO agent provides:

- **Electronic Structure**: SCF, NSCF, band structure, DOS calculations
- **Geometry Optimization**: Atomic relaxation, variable-cell optimization
- **Phonon Calculations**: Phonon frequencies and dispersions (via phonopy/ph.x)
- **Structure Generation**: pymatgen for crystal structure manipulation
- **K-path Generation**: Automatic high-symmetry k-paths via seekpath
- **Symmetry Analysis**: Space group detection via spglib
- **Post-processing**: DOS, bands plotting via matplotlib
- **Equation of State**: Birch-Murnaghan EOS fitting for bulk modulus
- **Elastic Constants**: Strain-stress analysis for elastic tensor (C_ij)
- **Convergence Testing**: Automated ecutwfc/k-point convergence tests
- **Band Analysis**: Band gap, VBM/CBM detection, effective mass extraction
- **Thermal Properties**: Heat capacity, entropy, free energy from phonons

### Python Package Reference

The container includes scientific Python packages for self-sufficient workflows:

| Package | Purpose |
|---------|---------|
| pymatgen | Structure manipulation, QE input/output, Materials Project |
| spglib | Symmetry detection and analysis |
| seekpath | Automatic high-symmetry k-path generation |
| phonopy | Phonon calculation post-processing |
| ase | Atomic Simulation Environment (structure I/O) |
| numpy, scipy | Scientific computing |
| matplotlib | Plotting and visualization |
| pandas | Data analysis |
| h5py | HDF5 file support for large datasets |

#### Example: Generate k-path with seekpath

```python
from pymatgen.core import Structure
import seekpath

# Load structure
struct = Structure.from_file("POSCAR")
cell = (struct.lattice.matrix,
        struct.frac_coords,
        [s.Z for s in struct.species])

# Get standardized k-path
path_data = seekpath.get_path(cell)
print("High-symmetry points:", path_data['point_coords'])
print("K-path:", path_data['path'])
```

#### Example: Create QE input with pymatgen

```python
from pymatgen.core import Structure, Lattice
from pymatgen.io.pwscf import PWInput

# Create silicon structure
lattice = Lattice.cubic(5.43)
struct = Structure(lattice, ['Si', 'Si'],
                   [[0,0,0], [0.25,0.25,0.25]])

# Generate QE input
pwinput = PWInput(struct, pseudo={'Si': 'Si.pbe-n-rrkjus_psl.1.0.0.UPF'},
                  control={'calculation': 'scf'},
                  system={'ecutwfc': 30, 'ecutrho': 240})
pwinput.write_file('si.scf.in')
```

### Pre-installed Utilities Library (qe_utils)

The container includes `qe_utils.py`, a comprehensive Python library for QE workflows. Import and use these functions in your scripts:

```python
from qe_utils import (
    # Setup & I/O
    quick_setup, quick_finish, save_final_results,

    # Execution (with real-time streaming and auto MPI)
    run_command, run_qe_adaptive,

    # Parsing
    parse_qe_output, parse_scf_convergence, parse_bands, parse_dos,
    parse_phonon_output, parse_stress_tensor, parse_qe_forces,

    # Equation of State
    fit_equation_of_state, plot_equation_of_state,

    # Elastic Constants
    generate_strain_patterns, apply_strain_to_structure, compute_elastic_tensor,

    # Convergence Testing
    generate_convergence_inputs, analyze_convergence, plot_convergence,

    # Band Analysis
    find_band_extrema, extract_effective_mass,

    # Phonopy Interface
    create_phonopy_supercell, compute_phonons_from_forces,
    calculate_phonon_dispersion, calculate_phonon_dos, calculate_thermal_properties,

    # Visualization
    plot_scf_convergence, plot_bands, plot_dos, plot_phonon_dispersion, plot_phonon_dos,

    # Constants
    PSEUDO_DIR, INPUT_DIR, WORK_DIR, OUTPUT_DIR, RY_TO_EV
)
```

#### Key Function Reference

| Function | Purpose | Returns |
|----------|---------|---------|
| `fit_equation_of_state(volumes, energies)` | Birch-Murnaghan EOS fit | `{V0, E0, B0 (GPa), B0_prime}` |
| `generate_strain_patterns(crystal_system)` | Strain tensors for elastic calc | List of strain dicts |
| `compute_elastic_tensor(strains, stresses)` | Compute C_ij from stress-strain | `{C_matrix, C_dict, bulk_modulus_vrh}` |
| `generate_convergence_inputs(base, param, values)` | Create convergence test inputs | List of input file paths |
| `analyze_convergence(results, threshold)` | Find converged parameter value | `{converged_value, energy_differences}` |
| `find_band_extrema(bands_data)` | Find VBM, CBM, band gap | `{vbm, cbm, band_gap, is_direct}` |
| `extract_effective_mass(bands_data, band_idx, k_idx)` | m* from band curvature | `{effective_mass, curvature}` |
| `create_phonopy_supercell(structure, matrix)` | Generate displaced structures | `{phonopy, structure_files}` |
| `calculate_thermal_properties(phonopy)` | Cv, S, F from phonons | `{temperatures, heat_capacity, entropy}` |

## Example Script Template

Using the `qe_utils` library (recommended):

```python
#!/usr/bin/env python3
"""Quantum ESPRESSO calculation script using qe_utils."""
import os, glob, logging
from qe_utils import (
    quick_setup, quick_finish, run_qe_adaptive, parse_qe_output,
    check_pseudopotentials, save_final_results, PSEUDO_DIR
)

quick_setup()  # Sets up logging, directories, copies input files
results = {"status": "in_progress", "calculations": {}}

try:
    logging.info("******* STEP 1: SETUP *******")
    logging.info(f"Files: {os.listdir('.')}")
    logging.info(f"Pseudopotentials: {len(glob.glob(os.path.join(PSEUDO_DIR, '*.UPF')))}")

    logging.info("******* STEP 2: CALCULATIONS *******")
    for inp_file in glob.glob('*.in'):
        output_file = inp_file.replace('.in', '.out')
        run_qe_adaptive('pw.x', inp_file, output_file)  # Auto MPI + real-time streaming
        calc = parse_qe_output(output_file)
        results['calculations'][inp_file] = calc
        if calc['converged']:
            logging.info(f"Energy: {calc['total_energy_eV']:.6f} eV")
            if calc.get('band_gap_eV'):
                logging.info(f"Band gap: {calc['band_gap_eV']:.3f} eV")

    logging.info("******* STEP 3: FINALIZE *******")
    results['status'] = 'completed'

except Exception as e:
    logging.error(f"Error: {e}")
    results['status'] = 'failed'
    results['error'] = str(e)

finally:
    quick_finish()  # Copy outputs to /output
    save_final_results(results)  # Save final_results.json
```

### Advanced Workflow Example: Bulk Modulus

```python
from qe_utils import fit_equation_of_state, plot_equation_of_state

# After running vc-relax at different volumes (or pressures)
volumes = [148.5, 152.3, 156.2, 160.1, 164.0]  # Å³
energies = [-310.52, -310.68, -310.75, -310.71, -310.58]  # eV

eos = fit_equation_of_state(volumes, energies, eos_type='birchmurnaghan')
print(f"Equilibrium volume: {eos['V0']:.2f} Å³")
print(f"Bulk modulus: {eos['B0']:.1f} GPa")
plot_equation_of_state(eos, 'eos_fit.png')
```

### Advanced Workflow Example: Phonon Calculation

```python
from qe_utils import (
    create_phonopy_supercell, parse_qe_forces, compute_phonons_from_forces,
    calculate_phonon_dispersion, calculate_thermal_properties, plot_phonon_dispersion
)

# 1. Create displaced supercells
ph = create_phonopy_supercell('relaxed.cif', supercell_matrix=[2,2,2])
print(f"Generated {ph['n_displacements']} displaced structures")

# 2. Run QE SCF on each displaced structure (loop)
# ... run pw.x on each POSCAR file ...

# 3. Collect forces and compute phonons
forces = [parse_qe_forces(f'disp-{i:03d}.out') for i in range(1, ph['n_displacements']+1)]
phonons = compute_phonons_from_forces(ph['phonopy'], forces)

# 4. Calculate dispersion and thermal properties
disp = calculate_phonon_dispersion(phonons['phonopy'])
thermal = calculate_thermal_properties(phonons['phonopy'], t_max=500)
plot_phonon_dispersion(disp, 'phonon_bands.png')
```

## Usage

### Basic Calculations

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Run a self-consistent calculation on silicon" | si.scf.in | SCF ground-state energy |
| "Relax the atomic positions of silicon" | si.relax.in | Geometry optimization (fixed cell) |
| "Compute the band structure of silicon along high-symmetry paths" | si.scf.in | Electronic band structure |
| "Calculate the density of states for silicon" | si.dos.in | Total and projected DOS |

### Advanced Analysis

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Run a variable-cell relaxation of silicon and report the equilibrium lattice parameter" | si.vc-relax.in | Full cell + atomic relaxation |
| "Compute phonon frequencies at Gamma for silicon" | si.ph.in | Phonon calculation via DFPT |
| "Perform a convergence study on silicon — test ecutwfc from 30 to 80 Ry and k-points 4×4×4 to 8×8×8" | si.scf.in | Cutoff and k-grid convergence |
| "Calculate the equation of state for silicon by varying the lattice constant ±5%" | si.scf.in | Energy-volume curve fitting |

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → Quantum ESPRESSO (LLM) → Quantum ESPRESSO Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** Quantum ESPRESSO container for first-principles electronic structure calculations with pymatgen, phonopy, seekpath, and ASE

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
| `quantumEspresso` | `tools/qe/` | Quantum ESPRESSO is an integrated suite of open-source computer codes for electronic-structure calculations and materials modeling at the nanoscale... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.