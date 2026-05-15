#!/usr/bin/env python3
"""Quick verification script for container imports and basics."""
import sys
sys.path.insert(0, '/app')

print("=== Import Tests ===")
from crest_utils import (
    quick_setup, quick_finish, save_final_results,
    smiles_to_xyz, conformer_search, compute_boltzmann_populations,
    compute_ensemble_statistics, parse_ensemble, parse_crest_output,
    read_xyz_file, write_xyz_file, get_crest_version, get_xtb_version,
    HARTREE_TO_KCAL, HARTREE_TO_EV
)
print("  crest_utils: OK")

from rdkit import Chem
from rdkit.Chem import AllChem
print("  RDKit: OK")

import numpy as np
print("  NumPy: OK")

import scipy
print("  SciPy: OK")

import matplotlib
print("  Matplotlib: OK")

import pandas as pd
print("  Pandas: OK")

import ase
print("  ASE: OK")

print("\n=== Version Checks ===")
print(f"  CREST: {get_crest_version()}")
print(f"  xtb: {get_xtb_version()}")
print(f"  Python: {sys.version}")

print("\n=== SMILES to XYZ Test ===")
import tempfile, os
tmpdir = tempfile.mkdtemp()
import crest_utils
crest_utils.WORK_DIR = tmpdir
xyz = smiles_to_xyz("CCO", os.path.join(tmpdir, "ethanol.xyz"))
atoms, coords, _ = read_xyz_file(xyz)
print(f"  Ethanol: {len(atoms)} atoms ({atoms.count('C')}C, {atoms.count('O')}O, {atoms.count('H')}H)")
assert len(atoms) == 9, f"Expected 9 atoms, got {len(atoms)}"
assert atoms.count('C') == 2
assert atoms.count('O') == 1
print("  SMILES->XYZ: PASS")

print("\n=== Boltzmann Analysis Test ===")
energies = [-76.1, -76.09, -76.08, -76.05, -76.0]
boltz = compute_boltzmann_populations(energies)
print(f"  {len(energies)} energies -> populations sum = {sum(boltz['populations']):.6f}")
assert abs(sum(boltz['populations']) - 1.0) < 1e-10
stats = compute_ensemble_statistics(energies)
print(f"  Energy range: {stats['energy_range_kcal']:.2f} kcal/mol")
print("  Boltzmann: PASS")

print("\n=== Parse Output Test ===")
mock = "number of unique conformers for further processing: 12\nCREST terminated normally."
info = parse_crest_output(mock)
assert info['n_conformers'] == 12
assert info['converged'] == True
print("  Output parsing: PASS")

print("\n=== ALL TESTS PASSED ===")
