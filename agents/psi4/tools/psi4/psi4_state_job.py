#!/usr/bin/env python3
"""Private JSON worker: one fresh Psi4 process per optimization/electronic state."""
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    request_path = Path(sys.argv[1]).resolve()
    request = json.loads(request_path.read_text(encoding='utf-8'))
    scratch = request_path.parent / 'scratch'
    scratch.mkdir(exist_ok=True)
    os.environ['PSI_SCRATCH'] = str(scratch)
    from psi4_utils import create_molecule, setup_psi4, optimize_geometry, compute_energy
    setup_psi4(memory=os.environ.get('PSI4_MEMORY', '4 GB'),
               nthreads=int(os.environ.get('OMP_NUM_THREADS', '1')),
               output_file=str(request_path.parent / 'psi4.out'))
    molecule = create_molecule(request['geometry'], charge=request['charge'],
                               multiplicity=request['multiplicity'], symmetry='c1')
    options = dict(request['options'])
    if request['optimize']:
        result = optimize_geometry(molecule, request['method'], request['optimization_basis'],
                                   **options)
        molecule = result.pop('molecule')
        if not result['converged']:
            result['status'] = 'failed'
            return result
    else:
        result = {}
    options.pop('geom_maxiter', None)
    options.pop('full_hess_every', None)
    result.update(compute_energy(molecule, request['method'], request['energy_basis'], **options))
    result['status'] = 'success'
    return result


if __name__ == '__main__':
    result_path = Path(sys.argv[1]).resolve().with_name('result.json')
    try:
        result = main()
        result_path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
        sys.exit(0 if result['status'] == 'success' else 1)
    except Exception as error:
        # Process boundary: persist failure evidence, but never turn an exception into success.
        traceback.print_exc()
        result_path.write_text(json.dumps({'status': 'failed', 'error': str(error),
                                           'error_type': type(error).__name__}, indent=2),
                               encoding='utf-8')
        sys.exit(1)
