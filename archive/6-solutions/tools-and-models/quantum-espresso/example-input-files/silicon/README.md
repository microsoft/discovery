# Silicon Example for Quantum ESPRESSO

This example demonstrates typical DFT workflows for bulk silicon (diamond structure). Silicon is an ideal test material: well-characterized, fast to compute, and a standard benchmark in computational materials science.

## Input Files

| File | Calculation | QE Code | Prerequisites |
|------|-------------|---------|---------------|
| `si.scf.in` | Self-consistent field | pw.x | None |
| `si.nscf.in` | Non-SCF (dense k-grid) | pw.x | SCF |
| `si.bands.in` | Band structure | pw.x | SCF |
| `si.dos.in` | Density of states | dos.x | NSCF |
| `si.pdos.in` | Projected DOS | projwfc.x | NSCF |
| `si.relax.in` | Geometry optimization | pw.x | None |
| `si.vc-relax.in` | Variable-cell relaxation | pw.x | None |
| `si.ph.in` | Phonon at Gamma | ph.x | SCF |

## Workflow Examples

### 1. Ground State Energy (SCF)
```bash
pw.x < si.scf.in > si.scf.out
```

### 2. Band Structure
```bash
pw.x < si.scf.in > si.scf.out      # Step 1: SCF
pw.x < si.bands.in > si.bands.out  # Step 2: Bands along k-path
```

### 3. Density of States
```bash
pw.x < si.scf.in > si.scf.out      # Step 1: SCF
pw.x < si.nscf.in > si.nscf.out    # Step 2: NSCF on dense k-grid
dos.x < si.dos.in > si.dos.out     # Step 3: DOS post-processing
```

### 4. Projected DOS (Orbital-resolved)
```bash
pw.x < si.scf.in > si.scf.out          # Step 1: SCF
pw.x < si.nscf.in > si.nscf.out        # Step 2: NSCF
projwfc.x < si.pdos.in > si.pdos.out   # Step 3: PDOS
```

### 5. Geometry Optimization
```bash
pw.x < si.relax.in > si.relax.out      # Atomic positions only
# OR
pw.x < si.vc-relax.in > si.vc-relax.out  # Atoms + cell parameters
```

### 6. Phonon Frequencies at Gamma
```bash
pw.x < si.scf.in > si.scf.out    # Step 1: SCF
ph.x < si.ph.in > si.ph.out      # Step 2: Phonon calculation
```

## System Details

- **Structure**: Diamond cubic (FCC with 2-atom basis)
- **Space group**: Fd-3m (#227)
- **Lattice constant**: celldm(1) = 10.2 Bohr (~5.4 A)
- **ibrav = 2**: FCC lattice (Quantum ESPRESSO convention)
- **Atoms**: 2 Si atoms at (0,0,0) and (0.25,0.25,0.25)

## Computational Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| ecutwfc | 30 Ry | Suitable for quick tests; use 40-50 Ry for production |
| ecutrho | 240 Ry | 8x ecutwfc for ultrasoft PP |
| k-points (SCF) | 4x4x4 | Adequate for Si; increase for metals |
| k-points (DOS) | 8x8x8 | Denser grid for smooth DOS |
| conv_thr | 1.0e-8 | Standard SCF convergence |

## Pseudopotential

Uses `Si.pbe-n-rrkjus_psl.1.0.0.UPF` from SSSP 1.3.0 Efficiency library (PSLibrary):
- **Type**: Ultrasoft (USPP)
- **XC functional**: PBE
- **Valence electrons**: 4 (3s2 3p2)
- **Cutoffs**: ecutwfc=30 Ry, ecutrho=240 Ry (as specified in SSSP)
- **Source**: [SSSP 1.3.0 Efficiency](https://archive.materialscloud.org/record/2023.65)

## Expected Results

| Property | DFT (PBE) | Experimental |
|----------|-----------|--------------|
| Band gap | ~0.5-0.6 eV | 1.17 eV |
| Lattice constant | ~5.47 A | 5.43 A |
| Bulk modulus | ~89-92 GPa | 98 GPa |

**Note**: DFT-PBE systematically underestimates band gaps. The discrepancy with experiment is expected and well-documented.

## Band Structure K-Path

The `si.bands.in` file uses the standard FCC high-symmetry path:
- **L** (0.5, 0.5, 0.5) -> **Gamma** (0, 0, 0) -> **X** (0.5, 0, 0.5) -> **W** (0.5, 0.25, 0.75) -> **L**

This path captures the key features:
- Valence band maximum at Gamma
- Conduction band minimum near X (indirect gap)
