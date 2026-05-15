
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
5. Completed platform onboarding (see [user guide](../../../4-how-to/))

## Deployment Steps

### Step 1: Build and Publish Docker Image

1. **Build the Docker image** from the provided Dockerfile:

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

### Step 2: Update Tool Definition

1. **Edit the tool definition file** (`qe-tool-definition.yaml`)
2. **Update the ACR path** in the image section:

   ```yaml
   infra:
     - name: worker
       infra_type: container
       image:
         acr: mycontainerregistry.azurecr.io/quantum-espresso:cpu  # Update this line
   ```

   > Replace `mycontainerregistry` with your actual ACR name

### Step 3: Convert YAML to JSON

Use the provided utility to convert YAML definitions to JSON format required by the platform:

1. **Convert the tool definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py qe-tool-definition.yaml --output qe-tool-definition.json --json
   ```

2. **Convert the agent definition**:

   ```bash
   python3 ../../utils/definition-content-creator.py qe-agent-definition.yaml --output qe-agent-definition.json --json
   ```

### Step 4: Deploy Platform Resources

#### 4.1 Create Tool Resource

Deploy the Quantum ESPRESSO tool to the Discovery platform using the generated JSON definition.

> **Reference**: See [Tool Deployment Guide](../../../4-how-to/6-tools-models-agents/b--tool-deployment.md) for detailed steps

#### 4.2 Create Agent Resource

Deploy the QE agent using the agent JSON definition.

> **Reference**: See [Agent Deployment Guide](../../../4-how-to/6-tools-models-agents/c--agent-deployment.md) for detailed steps

#### 4.3 Create Workflow Resource

Create a workflow that utilizes the QE agent for electronic structure calculations.

#### 4.4 Create Project Resource

Set up a project to organize and manage your computational chemistry workflows.

> **Reference**: See [Project Creation Guide](../../../4-how-to/7-projects/a--creating-project.md) for detailed steps

#### 4.5 Create an Investigation

Create a project investigation that utilizes the QE agent for DFT calculations.

> **Reference**: See [Creating Investigations Guide](../../../4-how-to/8-investigations/a--creating-investigation.md) for detailed steps

#### 4.6 Run an investigation

Run the investigation with prompts from the categories below. Example input files are provided in `example-input-files/silicon/`.

**Basic Calculations** (starter prompts):

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Run an SCF calculation for this silicon structure to compute the ground state energy." | `si.scf.in` | Ground state energy and electron density |
| "Calculate the electronic band structure along high-symmetry k-points." | `si.scf.in`, `si.bands.in` | Band dispersion along L-Γ-X-W-L path |
| "Compute the density of states (DOS) for this material." | `si.scf.in`, `si.nscf.in`, `si.dos.in` | Total DOS with fine k-grid |
| "Calculate the projected density of states (PDOS) to see orbital contributions." | `si.scf.in`, `si.nscf.in`, `si.pdos.in` | Orbital-resolved DOS (s, p, d contributions) |

**Geometry Optimization**:

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Perform a geometry optimization to find the equilibrium atomic positions." | `si.relax.in` | Atomic relaxation with fixed cell |
| "Optimize both atomic positions and cell parameters (variable-cell relaxation)." | `si.vc-relax.in` | Full structural optimization |

**Phonons and Vibrational Properties**:

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Calculate phonon frequencies at the Gamma point." | `si.scf.in`, `si.ph.in` | Zone-center phonon modes |
| "Compute phonon dispersion using finite displacements." | `si.scf.in` | Agent uses phonopy for full dispersion |

**Advanced Analysis** (agent capabilities, no input files required):

| Prompt | Description |
|--------|-------------|
| "Generate a high-symmetry k-path for band structure calculation." | Agent uses seekpath to auto-generate paths |
| "Run a convergence test for ecutwfc from 20 to 60 Ry." | Automated parameter sweep with analysis |
| "Run a k-point convergence test from 2x2x2 to 10x10x10." | K-grid optimization |
| "Calculate the bulk modulus using equation of state fitting." | Birch-Murnaghan EOS from volume-energy data |
| "Compute elastic constants for this crystal." | Strain-stress analysis for C_ij tensor |
| "Find the band gap and identify if it's direct or indirect." | Band extrema analysis |
| "Calculate effective masses at the band edges." | Parabolic fitting of band curvature |
| "Calculate thermal properties (heat capacity, entropy) from phonons." | Phonopy post-processing |

**File Extensions Reference:**

| Extension | Description | QE Code |
|-----------|-------------|---------|
| `*.scf.in` | SCF (self-consistent field) | pw.x |
| `*.nscf.in` | Non-SCF on fine k-grid | pw.x |
| `*.bands.in` | Band structure along k-path | pw.x |
| `*.dos.in` | Density of states | dos.x |
| `*.pdos.in` | Projected DOS | projwfc.x |
| `*.relax.in` | Geometry optimization (atoms only) | pw.x |
| `*.vc-relax.in` | Variable-cell relaxation | pw.x |
| `*.ph.in` | Phonon calculation | ph.x |
| `*.UPF` | Pseudopotential files | (SSSP pre-installed) |

Wait for response and check the generated outputs.

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

### Supported Calculation Types

| Calculation | QE Code | Description |
|-------------|---------|-------------|
| SCF | pw.x | Self-consistent ground state |
| NSCF | pw.x | Non-SCF on dense k-grid |
| Bands | pw.x | Band structure along k-path |
| Relax | pw.x | Geometry optimization |
| VC-Relax | pw.x | Variable-cell optimization |
| DOS | dos.x | Density of states |
| Phonons | ph.x | Phonon frequencies |
| Projections | projwfc.x | Projected DOS (PDOS) |

### Pseudopotential Library

The container includes SSSP Efficiency v1.3.0 pseudopotentials:
- **Location**: `/opt/apps/qe/7.3/pseudo/`
- **Type**: Mixed (GBRV ultrasoft, PSLibrary PAW/USPP)
- **Exchange-correlation**: PBE
- **Coverage**: All elements H through Bi (plus At, Fr, Ra)
- **Naming**: PSLibrary style (e.g., `Si.pbe-n-rrkjus_psl.1.0.0.UPF`) or GBRV style (e.g., `ge_pbe_v1.4.uspp.F.UPF`)
- **Tip**: Use `list_pseudopotentials()` from qe_utils to see available files

### Parallelization Guidelines

The agent automatically selects optimal parallelization based on system size:

| System Size | Strategy | Notes |
|-------------|----------|-------|
| < 50 atoms | Single MPI | Lower overhead |
| 50-200 atoms | MPI (N cores) | Standard parallelization |
| > 200 atoms | MPI + k-pools | Split k-points across pools |

### Networking and Infiniband

**Current Configuration: Single-Node, TCP/Ethernet**

This tool is configured for single-node operation without Infiniband:

| Setting | Value | Purpose |
|---------|-------|---------|
| `infiniband` | `false` | Runs on standard AKS nodes |
| `pool_size` | `1` | Single-node jobs only |
| MPI transport | TCP (`eth0`) | Works without IB drivers |

**Why This Works Without Infiniband:**

1. **Single-node parallelization** - With `pool_size: 1`, all MPI communication stays within one node using shared memory or TCP loopback. Infiniband is only beneficial for inter-node communication.

2. **Container compatibility** - The Dockerfile configures OpenMPI for reliable operation in containerized environments:
   ```bash
   ENV OMPI_MCA_btl_tcp_if_include=eth0      # Force TCP over ethernet
   ENV OMPI_MCA_btl_vader_single_copy_mechanism=none  # Container compatibility
   ```

3. **Portable libraries** - Uses OpenMPI + OpenBLAS which work on any node type, unlike Intel MPI + MKL which may expect specialized interconnects.

**When Infiniband Would Help:**

| Scenario | IB Benefit | Notes |
|----------|------------|-------|
| Single node, <100 atoms | Minimal | Memory bandwidth limited |
| Single node, >200 atoms | Some | Faster intra-node MPI |
| **Multi-node** (pool_size > 1) | **Significant** | 10-100x faster inter-node |
| Phonon supercells (>500 atoms) | Major | Heavy MPI communication |
| AIMD or extensive k-sampling | Major | Frequent data exchange |

**To Enable Infiniband (Advanced HPC):**

If you need multi-node QE for large-scale calculations:

1. **Update tool definition** (`qe-tool-definition.yaml`):
   ```yaml
   infiniband: true
   pool_size: 2-8  # Enable multi-node
   recommended_sku:
     - Standard_HB120rs_v3   # AMD EPYC, 200 Gb/s HDR IB
     - Standard_HB176rs_v4   # AMD Genoa, 400 Gb/s NDR IB
   ```

2. **Modify Dockerfile** to let OpenMPI auto-detect IB:
   ```dockerfile
   # Remove or comment out the forced TCP setting:
   # ENV OMPI_MCA_btl_tcp_if_include=eth0

   # Optionally set explicit BTL preference (IB preferred, TCP fallback):
   ENV OMPI_MCA_btl=self,vader,openib,tcp
   ```

3. **Rebuild and redeploy** the container image to your ACR.

> **Note:** The current configuration works reliably for most DFT calculations. Only modify for specific HPC requirements.

### Directory Structure (Container)

- **Input files**: `/input/` (read-only)
- **Working directory**: `/app/workdir/`
- **Output files**: `/output/`
- **Pseudopotentials**: `/opt/apps/qe/7.3/pseudo/`

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

## Additional Resources

- [Microsoft Discovery Documentation](../../)
- [Container Image Creation Guide](../../../4-how-to/5-tool-image/a--create-and-publish-container-image.md)
- [Quantum ESPRESSO Official Documentation](https://www.quantum-espresso.org/documentation/)
- [SSSP Pseudopotential Library](https://www.materialscloud.org/discover/sssp)
- [pymatgen Documentation](https://pymatgen.org/)
- [seekpath Documentation](https://seekpath.readthedocs.io/)

## Support

For platform-specific issues, refer to the [user guide documentation](../../../4-how-to/) or contact your platform administrator.
