# CP2K Agent — Example Input Files

This directory contains ready-to-use input structures for testing and demonstrating the CP2K agent on the Microsoft Discovery platform.

## File Inventory

### Molecules (XYZ format, non-periodic)

| File | System | Atoms | Use Cases | Notes |
|------|--------|-------|-----------|-------|
| `water.xyz` | H2O | 3 | DFT energy, SCF convergence | PBE/DZVP ref: ~-17.22 Ha |
| `h2.xyz` | H2 | 2 | Vibrational analysis, bond stretch | Expected stretch: ~4400 cm-1 |
| `methane.xyz` | CH4 | 5 | DFT energy, forces | Tetrahedral Td symmetry |
| `ethanol.xyz` | C2H5OH | 9 | Geometry optimization, dispersion | Good test for PBE-D3 |
| `benzene.xyz` | C6H6 | 12 | Delocalization, dispersion, symmetry | D6h, good for D3/D3BJ test |
| `oh_minus.xyz` | OH- | 2 | Charged system (charge=-1) | Tests charge handling |
| `o_atom.xyz` | O | 1 | Open-shell triplet (mult=3, UKS) | Tests unrestricted KS |

### Crystals (CIF format, periodic)

| File | System | Space Group | Use Cases | Notes |
|------|--------|-------------|-----------|-------|
| `silicon.cif` | Si (diamond) | Fd-3m (#227) | Band structure, DOS, cell opt | a=5.431 A, 2 atoms/cell |
| `nacl.cif` | NaCl (rocksalt) | Fm-3m (#225) | Ionic solid, band gap | a=5.640 A, 2 atoms/cell |

### Liquid/MD (XYZ format, periodic box)

| File | System | Atoms | Use Cases | Notes |
|------|--------|-------|-----------|-------|
| `water_box_8.xyz` | 8 x H2O | 24 | Ab initio MD (NVT/NPT) | Box: 7.8 A cubic, ~1 g/cm3 |

## Quick Start Examples

### 1. Single-point energy (water)
```python
structure = read_xyz('water.xyz')  # from /input/
structure['cell'] = [10.0, 10.0, 10.0]
structure['periodic'] = 'NONE'
inp = generate_input('water', 'ENERGY', structure)
```

### 2. Geometry optimization (ethanol with dispersion)
```python
structure = read_xyz('ethanol.xyz')
structure['cell'] = [15.0, 15.0, 15.0]
structure['periodic'] = 'NONE'
inp = generate_input('ethanol_opt', 'GEO_OPT', structure,
    dft_params={'dispersion': 'D3'},
    geo_opt_params={'optimizer': 'BFGS', 'max_iter': 200})
```

### 3. Vibrational analysis (H2)
```python
structure = read_xyz('h2.xyz')
structure['cell'] = [10.0, 10.0, 10.0]
structure['periodic'] = 'NONE'
inp = generate_input('h2_vib', 'VIBRATIONAL_ANALYSIS', structure,
    dft_params={'cutoff': 400})
```

### 4. Charged system (OH-)
```python
structure = read_xyz('oh_minus.xyz')
structure['cell'] = [10.0, 10.0, 10.0]
structure['periodic'] = 'NONE'
structure['charge'] = -1
inp = generate_input('oh_minus', 'ENERGY', structure)
```

### 5. Open-shell atom (O triplet)
```python
structure = read_xyz('o_atom.xyz')
structure['cell'] = [10.0, 10.0, 10.0]
structure['periodic'] = 'NONE'
structure['multiplicity'] = 3
inp = generate_input('o_atom', 'ENERGY', structure,
    dft_params={'uks': True})
```

### 6. Crystal band structure (silicon)
```python
structure = read_cif_to_structure('silicon.cif')
inp = generate_input('si_bands', 'BAND', structure,
    dft_params={'cutoff': 600, 'added_mos': 10, 'kpoints': [4, 4, 4]},
    band_structure_params={'path': [
        ['GAMMA', 10, 0.0, 0.0, 0.0],
        ['X', 10, 0.5, 0.0, 0.5],
        ['L', 10, 0.5, 0.5, 0.5],
        ['GAMMA', 10, 0.0, 0.0, 0.0],
    ]})
```

### 7. Ab initio MD (water box)
```python
structure = read_xyz('water_box_8.xyz')
structure['cell'] = [7.8, 7.8, 7.8]
structure['periodic'] = 'XYZ'
inp = generate_input('water_md', 'MD', structure,
    dft_params={'functional': 'PBE', 'cutoff': 400, 'dispersion': 'D3'},
    md_params={'ensemble': 'NVT', 'timestep': 0.5, 'steps': 100,
               'temperature': 300, 'thermostat': 'NOSE'})
```

## Recommended Settings per System

| System | Functional | Basis | Cutoff (Ry) | Cell Padding (A) | Periodic |
|--------|-----------|-------|-------------|-------------------|----------|
| water.xyz | PBE | DZVP-MOLOPT-SR-GTH | 300-400 | +10 | NONE |
| h2.xyz | PBE | DZVP-MOLOPT-SR-GTH | 400 | +10 | NONE |
| methane.xyz | PBE | DZVP-MOLOPT-SR-GTH | 300 | +10 | NONE |
| ethanol.xyz | PBE+D3 | DZVP-MOLOPT-SR-GTH | 400 | +12 | NONE |
| benzene.xyz | PBE+D3 | DZVP-MOLOPT-SR-GTH | 400 | +12 | NONE |
| oh_minus.xyz | PBE | DZVP-MOLOPT-SR-GTH | 400 | +10 | NONE |
| o_atom.xyz | PBE (UKS) | DZVP-MOLOPT-SR-GTH | 400 | +10 | NONE |
| silicon.cif | PBE | DZVP-MOLOPT-SR-GTH | 600 | N/A | XYZ |
| nacl.cif | PBE | DZVP-MOLOPT-SR-GTH | 600 | N/A | XYZ |
| water_box_8.xyz | PBE+D3 | DZVP-MOLOPT-SR-GTH | 400 | N/A | XYZ |
