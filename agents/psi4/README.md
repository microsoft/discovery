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

## Build Docker Image


```bash
# Navigate to the psi4 directory
cd agents/psi4/tools/psi4/

# Build the Docker image
docker build -t psi4:latest .

# Tag for your ACR
docker tag psi4:latest <your-acr>.azurecr.io/psi4:latest

# Login to ACR
az acr login --name <your-acr>

# Push the image
docker push <your-acr>.azurecr.io/psi4:latest
```

## File Structure

```
psi4/
├── Dockerfile                    # Container build instructions
├── psi4-tool-definition.yaml     # Tool infrastructure definition
├── psi4-agent-definition.yaml    # Agent instructions and capabilities
├── psi4_utils.py                 # Python utilities library
├── run_psi4_job.py               # Isolated script launcher
├── psi4_state_job.py             # Private fresh-process four-point worker
├── test_psi4_reliability.py      # Mocked-Psi4 unittest suite
├── smoke_psi4_runtime.py         # Real-Psi4 runtime smoke
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
| `compute_electronic_properties()` | One wavefunction for energy, orbital gap, and explicit dipole |
| `compute_dipole_moment()` | Explicit one-electron dipole, atomic units and Debye |
| `compute_reorganization_energies()` | Gas-phase four-point hole/electron reorganization |
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

```console
cd agents/psi4/tools/psi4
python -m unittest -v test_psi4_reliability
python -m py_compile psi4_utils.py run_psi4_job.py psi4_state_job.py smoke_psi4_runtime.py test_psi4_reliability.py
```

The test runner is stdlib `unittest`; it mocks Psi4 and uses the library's existing
NumPy dependency. Tests include reference selection/validation, single-wavefunction
dipole conversion, nonfinite rejection, optimization retry/exhaustion, candidate-ID
and partial-failure preservation, four-point formulas, concurrent launcher isolation,
nested artifact copying, and child/copy failure exit codes.

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

## Usage

### Basic Calculations

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Calculate the energy of water at the HF/cc-pVDZ level" | water.xyz | Single-point Hartree-Fock energy |
| "Optimize the geometry of ethanol using B3LYP-D3BJ/def2-TZVP" | ethanol.xyz | DFT geometry optimization with dispersion |
| "Compute vibrational frequencies and IR spectrum for methane" | methane.xyz | Frequency analysis + thermochemistry |
| "What is the HOMO-LUMO gap of benzene at the B3LYP/cc-pVTZ level?" | benzene.xyz | Orbital energy analysis |

### Advanced Analysis

| Prompt | Input Files | Description |
|--------|-------------|-------------|
| "Run SAPT0/jun-cc-pVDZ on the water dimer and decompose the interaction energy" | water_dimer.xyz | Symmetry-adapted perturbation theory |
| "Calculate the first 5 excited states of formaldehyde using TD-DFT" | formaldehyde.xyz | Excited-state energies and UV-Vis spectrum |
| "Extrapolate the MP2 correlation energy of water to the CBS limit" | water.xyz | Complete basis set extrapolation |
| "Compare HF, MP2, and CCSD(T) energies for ammonia with cc-pVTZ" | ammonia.xyz | Method benchmark comparison |

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → Psi4 (LLM) → Psi4 Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** Psi4 container for ab initio quantum chemistry calculations (HF, DFT, post-HF, SAPT)

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
| `psiFour` | `tools/psi4/` | Psi4 is an open-source ab initio quantum chemistry package designed for high-throughput |

## Known Limitations

Mocked tests do not validate numerical accuracy, SCF/optimizer behavior, basis/method
availability, or PSIO behavior in the deployed image. Python 3.14 host tests are not
a substitute for the container's Python 3.11/Psi4 runtime. The scratch/working-directory
changes are isolation hardening, **not a proven PSIO root-cause fix**. Reproduce the
original failing input in the approved runtime after the smoke below.

## Gas-phase electronic properties and four-point reorganization

Public helper signatures:

```python
compute_dipole_moment(molecule, method='b3lyp', basis='def2-tzvp', **kwargs)
compute_electronic_properties(molecule, method='b3lyp', basis='def2-tzvp', **kwargs)
compute_reorganization_energies(
    molecule, candidate_id, method='b3lyp-d3bj',
    optimization_basis='def2-svp', energy_basis='def2-tzvp',
    neutral_multiplicity=1, cation_multiplicity=2, anion_multiplicity=2, **kwargs
)
```

`compute_energy`, `compute_homo_lumo_gap`, and `optimize_geometry` retain their
signatures and select `rhf` for singlets or `uhf` for higher multiplicities on **each**
calculation, including DFT. Explicit `reference='rhf'|'uhf'|'rohf'` remains supported.
Closed-shell `rhf` with open-shell multiplicity is rejected before calculation.
Do not substitute `rks`/`uks` keywords. Unconverged SCF acceptance is disabled.
Open-shell orbital gaps retain the existing **alpha-spin** convention; they are not
spin-combined, fundamental, or optical gaps.

The combined helper returns the existing `homo_energy_hartree/eV`,
`lumo_energy_hartree/eV`, `gap_hartree/eV`, and `total_energy_hartree/eV` keys, plus
`reference`, `dipole_vector_au`, `dipole_vector_debye`, and `dipole_moment_debye`.
It computes one energy/wavefunction and explicitly calls
`psi4.oeprop(wfn, 'DIPOLE', title='DISCOVERY')`, retrieving
`wfn.variable('DISCOVERY DIPOLE')` as a finite three-component vector.
The conversion is $1\,e a_0 = 2.5417464518950259\,\mathrm{D}$.
Charged-species dipoles depend on the coordinate origin. No polarizability or
optional-property artifact is required for these helpers to succeed.

API/units references verified against upstream documentation and implementation:

- [oeprop signature, wavefunction argument, and title prefix](https://psicode.org/psi4manual/master/oeprop.html)
- [Vector dipoles and atomic units](https://psicode.org/psi4manual/master/glossary_psivariables.html#psivar-SCF-DIPOLE)
- [Atomic-unit-to-Debye conversion](https://psicode.org/psi4manual/master/autodoc_physconst.html)
- [OEProp title-prefixed array storage on the wavefunction](https://github.com/psi4/psi4/blob/master/psi4/src/psi4/libmints/oeprop.cc)
- [OptimizationConvergenceError last wavefunction](https://psicode.org/psi4manual/master/_modules/psi4/driver/p4util/exceptions.html#OptimizationConvergenceError)

Four-point calculations always reoptimize the neutral, cation, and anion; an
upstream partial neutral result is **never** assumed converged. Defaults represent
a singlet neutral and doublet singly charged ions; supply the actual multiplicities
for other spin states. Input must be neutral. Each state uses its own validated
reference. Every optimization has at most **one** retry, from the exception's last
wavefunction geometry, with doubled `geom_maxiter`. If no last wavefunction is
available it fails without restarting the original geometry. Neither convergence
tolerances nor method/basis are weakened.

Let $Q_0$, $Q_+$, and $Q_-$ denote the optimized neutral, cation, and anion geometries.
At the **same final method/energy basis**, the two four-point sums are:

$$
\lambda_h = [E_+(Q_0)-E_+(Q_+)] + [E_0(Q_+)-E_0(Q_0)]
$$
$$
\lambda_e = [E_-(Q_0)-E_-(Q_-)] + [E_0(Q_-)-E_0(Q_0)].
$$

Results preserve `candidate_id`, `status`, method/bases, `energy_units='hartree'`,
`states` (charges, multiplicities, references, convergence flags, geometries in
angstrom), and `components`. Component keys are `E_neutral_at_neutral`,
`E_cation_at_cation`, `E_anion_at_anion`, `E_cation_at_neutral`,
`E_neutral_at_cation`, `E_anion_at_neutral`, and `E_neutral_at_anion`.
Success adds `hole_reorganization_hartree/eV` and `electron_reorganization_hartree/eV`.
On failure `status='failed'`, error details and all completed components remain;
do not treat them as completed reorganization results. Negative values are not
clamped or hidden. The helper persists `reorganization_result.json` in its unique
`artifact_directory`, with per-state requests/results and Psi4/worker logs.

### Invocation isolation and deployment use

The Dockerfile **packages source only when an approved image is built**. Editing it
does not update a deployed image. Do not build, push, retag, replace an image, or
change live tool references without explicit approval.

The execution command in the matching tool definition should use positional args:

```console
/opt/conda/envs/psi4env/bin/python /usr/local/lib/run_psi4_job.py /path/to/script.py /path/to/output
```

The launcher executes `[sys.executable, script_path]` without shell reparsing.
It creates unique writable work/scratch directories under the output directory's
parent, preflights writes, sets `PSI_SCRATCH` **before imports**, streams combined
stdout/stderr to terminal and `logs.out`, and copies nested work artifacts even
after failure. Scratch and symlinks are excluded. A child nonzero exit is preserved;
copy failure makes an otherwise successful invocation fail. `launcher_failure.json`
records failures. Invocation directories are cleaned only after copying.

`quick_setup(input_dir=..., output_dir=...)` retains the supplied data-handling
input/output paths; work resolves to invocation-specific `PSI4_WORK_DIR`, then an
explicit `work_dir`, otherwise a unique directory. `setup_psi4` binds the Psi4
IOManager to the selected writable scratch path. Use these settings rather than
shared work/scratch names. Four-point state jobs launch seven fresh processes
(three optimizations plus final diagonal energies, four cross energies) with their
own scratch directories and filenames. Non-JSON wavefunctions remain process-local.

```python
from psi4_utils import (
    quick_setup, setup_psi4, create_molecule, compute_electronic_properties,
    compute_reorganization_energies, save_final_results, quick_finish,
)
# Supply actual paths from the task's dataHandlingContext.
quick_setup(input_dir=input_directory, output_dir=output_directory)
setup_psi4(memory='4 GB', nthreads=1)
molecule = create_molecule(geometry, charge=0, multiplicity=1)
properties = compute_electronic_properties(molecule, method='b3lyp', basis='def2-tzvp')
reorganization = compute_reorganization_energies(molecule, candidate_id='candidate-001')
save_final_results(
    {'electronic_properties': properties, 'reorganization': reorganization},
    status='completed' if reorganization['status'] == 'success' else 'failed',
)
quick_finish()
```

In the approved Psi4 runtime, run the real smoke using the launcher:

```console
python run_psi4_job.py smoke_psi4_runtime.py smoke-output
```

It checks a water dipole, charged doublet water SCF energies, and tiny LiH
four-point calculations with a diffuse basis. It writes `smoke_results.json` and
asserts convergence and finite values. **Not yet run successfully in a real Psi4
runtime**: the local Windows Python has no Psi4 and Docker is unavailable. This is
the remaining verification gate before relying on L4b production numerical results.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.