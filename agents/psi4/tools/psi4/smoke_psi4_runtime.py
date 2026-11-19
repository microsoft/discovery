"""Real-Psi4 smoke; run through run_psi4_job.py in the approved built runtime."""
import json
import math
import os
from pathlib import Path

from psi4_utils import (
    setup_psi4, create_molecule, compute_energy, compute_electronic_properties,
    compute_reorganization_energies,
)


def main():
    setup_psi4(memory='1 GB', nthreads=1, output_file='smoke.out')
    water = create_molecule('O 0 0 0\nH 0 0.757 0.587\nH 0 -0.757 0.587', symmetry='c1')
    properties = compute_electronic_properties(water, method='hf', basis='sto-3g')
    assert 0.1 < properties['dipole_moment_debye'] < 5
    assert len(properties['dipole_vector_debye']) == 3
    assert all(math.isfinite(v) for v in properties['dipole_vector_debye'])
    # Water doublet ions exercise unrestricted charged SCF with a diffuse basis.
    for charge in (1, -1):
        ion = water.clone()
        ion.set_molecular_charge(charge)
        ion.set_multiplicity(2)
        energy = compute_energy(ion, method='hf', basis='6-31+g*')
        assert energy['reference'] == 'uhf'
        assert math.isfinite(energy['energy_hartree'])
    # LiH has bound neutral/cation/anion states and a tiny nuclear geometry.
    molecule = create_molecule('Li 0 0 0\nH 0 0 1.6', symmetry='c1')
    reorganization = compute_reorganization_energies(
        molecule, 'smoke-LiH', method='hf', optimization_basis='6-31+g*',
        energy_basis='6-31+g*', geom_maxiter=50)
    Path('smoke_results.json').write_text(json.dumps(
        {'properties': properties, 'reorganization': reorganization}, indent=2, allow_nan=False))
    assert reorganization['status'] == 'success', reorganization
    assert all(state['converged'] for state in reorganization['states'].values())
    assert len(reorganization['components']) == 7
    assert all(math.isfinite(value) for value in reorganization['components'].values())
    assert all(math.isfinite(reorganization[f'{carrier}_reorganization_eV'])
               for carrier in ('hole', 'electron'))


if __name__ == '__main__':
    main()
