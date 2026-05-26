# Example Input Files for Psi4

This directory contains example molecular structures in XYZ format for testing Psi4 calculations.

## Files

| File | Molecule | Atoms | Use Case |
|------|----------|-------|----------|
| `water.xyz` | H2O | 3 | Basic energy, optimization, frequencies |
| `methane.xyz` | CH4 | 5 | Geometry optimization, thermochemistry |
| `ethanol.xyz` | C2H5OH | 9 | Medium-sized organic molecule |
| `benzene.xyz` | C6H6 | 12 | Aromatic system, DFT calculations |
| `formaldehyde.xyz` | H2CO | 4 | Excited states (n-pi* transition) |
| `water_dimer.xyz` | (H2O)2 | 6 | SAPT interaction energy |
| `ammonia.xyz` | NH3 | 4 | Inversion barrier, frequencies |

## Recommended Calculations

### Quick Test (< 1 minute)
```python
# Water single-point energy
mol = create_molecule(read_xyz_file('water.xyz'))
result = compute_energy(mol, method='hf', basis='sto-3g')
```

### Standard Calculation (1-5 minutes)
```python
# Methane optimization + frequencies
mol = create_molecule(read_xyz_file('methane.xyz'))
opt = optimize_geometry(mol, method='b3lyp', basis='def2-svp')
freq = compute_frequencies(opt['molecule'], 'b3lyp', 'def2-svp')
```

### SAPT Interaction (5-10 minutes)
```python
# Water dimer SAPT
# Note: Need to define fragments with '--' separator
dimer = psi4.geometry('''
    0 1
    O     -1.551007   0.114520   0.000000
    H     -1.934259   0.762503   0.673090
    H     -0.599677   0.040712   0.000000
    --
    0 1
    O      1.350625   0.111469   0.000000
    H      1.680398  -0.520237   0.673090
    H      1.680398  -0.520237  -0.673090
''')
sapt = compute_sapt(dimer, method='sapt0', basis='jun-cc-pvdz')
```

### Excited States (5-15 minutes)
```python
# Formaldehyde TD-DFT
mol = create_molecule(read_xyz_file('formaldehyde.xyz'))
opt = optimize_geometry(mol, 'b3lyp', 'def2-svp')
exc = compute_excited_states(opt['molecule'], method='tddft', n_states=5)
```

## Expected Results (Approximate)

| Molecule | Method/Basis | Energy (Hartree) |
|----------|--------------|------------------|
| Water | HF/cc-pVDZ | -76.027 |
| Water | B3LYP/def2-TZVP | -76.437 |
| Methane | HF/cc-pVDZ | -40.195 |
| Benzene | B3LYP/def2-SVP | -232.2 |
| Water dimer | SAPT0/jun-cc-pVDZ | -5.0 kcal/mol (interaction) |

## Notes

- All geometries are provided in Angstroms
- Structures are approximately optimized at B3LYP/cc-pVTZ level
- For production calculations, always re-optimize at your target level of theory
- The water dimer geometry is a hydrogen-bonded minimum structure
