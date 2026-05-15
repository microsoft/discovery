# Psi4 Tool & Agent Deployment Guide

## Overview

Psi4 is an open-source ab initio quantum chemistry package designed for high-throughput quantum chemistry calculations. It provides a comprehensive suite of methods for electronic structure calculations, including:

- **Hartree-Fock** (RHF, UHF, ROHF)
- **Density Functional Theory** (B3LYP, PBE0, wB97X-D, M06-2X, and many more)
- **Post-Hartree-Fock methods** (MP2, CCSD, CCSD(T), CISD)
- **Symmetry-Adapted Perturbation Theory** (SAPT0, SAPT2, SAPT2+, SAPT2+(3))
- **Excited States** (EOM-CCSD, TD-DFT/TDA)
- **Geometry Optimization** with analytic gradients
- **Frequency Calculations** and thermochemistry
- **Basis Set Extrapolation** to complete basis set limit

Psi4 features a Python API for scriptable workflows, density fitting for computational efficiency, and multi-core parallelism for calculations with 2500+ basis functions.

## Prerequisites

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally
4. Azure CLI configured

## Deployment Steps

### Step 1: Build and Publish Docker Image

```bash
# Navigate to the psi4 directory
cd 6-solutions/tools-and-models/psi4/

# Build the Docker image
docker build -t psi4:latest .

# Tag for your ACR
docker tag psi4:latest <your-acr>.azurecr.io/psi4:latest

# Login to ACR
az acr login --name <your-acr>

# Push the image
docker push <your-acr>.azurecr.io/psi4:latest
```

### Step 2: Update Tool Definition

Edit `psi4-tool-definition.yaml` and update the ACR path:
```yaml
image:
  acr: "<your-acr>.azurecr.io/psi4:latest"
```

### Step 3: Deploy Platform Resources

```bash
# Publish the tool and agent using the Discovery CLI
discovery publish tool --path psi4-tool-definition.yaml
discovery publish agent --path psi4-agent-definition.yaml
```

### Step 4: Run Investigations

**Basic Energy Calculations:**

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Calculate the HF energy of water" | `water.xyz` | Single-point HF energy |
| "Compute B3LYP/def2-TZVP energy for ethanol" | `ethanol.xyz` | DFT single-point |
| "Run CCSD(T)/cc-pVTZ on methane" | `methane.xyz` | High-accuracy energy |

**Geometry Optimization:**

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Optimize the geometry of water at B3LYP/def2-SVP" | `water.xyz` | Geometry optimization |
| "Optimize benzene with B3LYP-D3BJ/def2-TZVP" | `benzene.xyz` | Dispersion-corrected DFT |

**Frequency & Thermochemistry:**

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Calculate vibrational frequencies of methane" | `methane.xyz` | Harmonic frequencies |
| "Compute thermochemistry for ammonia at 298K" | `ammonia.xyz` | Enthalpy, entropy, Gibbs |

**Interaction Energy Analysis:**

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Calculate SAPT interaction energy for water dimer" | `water_dimer.xyz` | SAPT decomposition |
| "Compute counterpoise-corrected interaction energy" | (dimer geometry) | BSSE correction |

**Excited States:**

| Prompt | Input File(s) | Description |
|--------|---------------|-------------|
| "Calculate TD-DFT excited states of formaldehyde" | `formaldehyde.xyz` | UV-Vis transitions |
| "Compute EOM-CCSD excited states" | (small molecule) | High-accuracy excitations |

## File Structure

```
psi4/
├── Dockerfile                    # Container build instructions
├── psi4-tool-definition.yaml     # Tool infrastructure definition
├── psi4-agent-definition.yaml    # Agent instructions and capabilities
├── psi4_utils.py                 # Python utilities library
├── test_psi4_utils.py           # Unit tests
├── README.md                     # This file
└── example-input-files/
    ├── water.xyz                 # Water molecule
    ├── methane.xyz               # Methane molecule
    ├── ethanol.xyz               # Ethanol molecule
    ├── benzene.xyz               # Benzene molecule
    ├── formaldehyde.xyz          # Formaldehyde (excited states)
    ├── water_dimer.xyz           # Water dimer (SAPT)
    ├── ammonia.xyz               # Ammonia molecule
    └── README.md                 # Example files documentation
```

## Agent Capabilities

### Methods Supported

| Method | Description | Typical Use |
|--------|-------------|-------------|
| HF | Hartree-Fock | Quick geometry checks |
| DFT | Density Functional Theory | General purpose |
| MP2 | 2nd-order Moller-Plesset | Correlation energy |
| CCSD | Coupled Cluster Singles+Doubles | High accuracy |
| CCSD(T) | CCSD with perturbative triples | Gold standard |
| SAPT | Symmetry-Adapted Perturbation Theory | Interaction energies |
| TD-DFT | Time-Dependent DFT | Excited states |
| EOM-CCSD | Equation-of-Motion CCSD | Accurate excitations |

### Basis Sets

- **Pople**: 6-31G*, 6-311+G**, etc.
- **Dunning**: cc-pVDZ, cc-pVTZ, cc-pVQZ, aug-cc-pVXZ
- **Karlsruhe**: def2-SVP, def2-TZVP, def2-QZVP

### Analysis Functions

| Function | Description |
|----------|-------------|
| `compute_energy()` | Single-point energy calculation |
| `compute_gradient()` | Energy gradient (forces) |
| `optimize_geometry()` | Geometry optimization |
| `compute_frequencies()` | Vibrational frequencies |
| `compute_thermochemistry()` | Enthalpy, entropy, Gibbs energy |
| `compute_sapt()` | SAPT interaction decomposition |
| `compute_excited_states()` | TD-DFT or EOM-CCSD excitations |
| `extrapolate_cbs()` | Complete basis set extrapolation |
| `compute_counterpoise_correction()` | BSSE correction |

## Key Configuration Details

### psi4_utils Library Functions

```python
from psi4_utils import (
    # Setup
    quick_setup, quick_finish, save_final_results,
    setup_psi4, create_molecule, read_xyz_file,

    # Calculations
    compute_energy, compute_gradient, optimize_geometry,
    compute_frequencies, compute_thermochemistry,
    compute_sapt, compute_excited_states,

    # Analysis
    extrapolate_cbs, compute_counterpoise_correction,

    # Visualization
    plot_orbital_energies, plot_ir_spectrum, plot_uv_vis_spectrum,

    # Constants
    HARTREE_TO_EV, HARTREE_TO_KCAL
)
```

### Memory and Parallelization

```python
# Set memory and threads
psi4 = setup_psi4(memory='8 GB', nthreads=16)

# For large calculations
psi4 = setup_psi4(memory='32 GB', nthreads=32)
```

### Common Psi4 Options

```python
psi4.set_options({
    'basis': 'def2-tzvp',
    'scf_type': 'df',           # Density fitting (fast)
    'reference': 'rhf',         # Closed-shell
    'd_convergence': 1e-8,      # Density convergence
    'e_convergence': 1e-8,      # Energy convergence
    'freeze_core': True,        # Freeze core electrons
})
```

## Testing

### Local Testing (without Psi4)

```bash
cd 6-solutions/tools-and-models/psi4/
python -m venv .venv-psi4
source .venv-psi4/bin/activate  # or .venv-psi4\Scripts\activate on Windows
pip install numpy scipy matplotlib pandas pytest
pytest test_psi4_utils.py -v
```

### Docker Testing

```bash
# Build and test
docker build -t psi4:test .
docker run --rm psi4:test python -c "import psi4; print(psi4.__version__)"
docker run --rm psi4:test python -c "from psi4_utils import quick_setup; print('OK')"
```

### Full Integration Test

```bash
# Run with example input
docker run --rm \
  -v $(pwd)/example-input-files:/input \
  -v $(pwd)/test-output:/output \
  psi4:test python -c "
from psi4_utils import quick_setup, setup_psi4, create_molecule, compute_energy, read_xyz_file
quick_setup()
psi4 = setup_psi4(memory='2 GB')
geom = read_xyz_file('/input/water.xyz')
mol = create_molecule(geom)
result = compute_energy(mol, 'hf', 'sto-3g')
print(f'Energy: {result[\"energy_hartree\"]:.6f} Hartree')
"
```

## Additional Resources

- [Psi4 Official Documentation](https://psicode.org/psi4manual/master/)
- [Psi4 GitHub Repository](https://github.com/psi4/psi4)
- [Psi4 Tutorials](https://psicode.org/psi4manual/master/tutorial.html)
- [Psi4 1.4 Paper](https://pubs.aip.org/aip/jcp/article/152/18/184108/972964/PSI4-1-4-Open-source-software-for-high-throughput)

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| SCF not converging | Try `scf_type='pk'` or reduce `d_convergence` |
| Memory errors | Increase memory allocation |
| Linear dependency | Use smaller basis set or increase `S_TOLERANCE` |
| Open-shell issues | Set correct `reference` (uhf/rohf) and multiplicity |
| Slow calculations | Use density fitting (`scf_type='df'`) |

### Getting Help

- Check Psi4 documentation for method-specific options
- Review the agent instructions in `psi4-agent-definition.yaml`
- Examine example scripts in the `example-input-files/` directory
