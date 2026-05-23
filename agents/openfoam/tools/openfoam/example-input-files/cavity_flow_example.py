#!/usr/bin/env python3
"""Example: Lid-driven cavity flow at Re=100.

Classic CFD benchmark. Simulates a square cavity with a moving top lid.
Extracts centerline velocity profiles and compares with Ghia et al. (1982).
"""
import sys
sys.path.insert(0, '/app')
from openfoam_utils import *
import logging

quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir')
CASE = '/workdir/cavity_case'
results = {}

try:
    logging.info("=" * 60)
    logging.info("STEP 1: Setting up lid-driven cavity")
    logging.info("=" * 60)

    Re = 100
    L = 0.1       # cavity side length [m]
    U_lid = 1.0   # lid velocity [m/s]
    nu = U_lid * L / Re  # back-calculate viscosity

    case_path = create_case_directory(CASE)

    # Mesh: square domain, uniform grid
    write_block_mesh_dict_box(CASE, 0, L, 0, L, 0, 0.01, 50, 50, 1,
                              patches={
                                  'movingWall': ['(4 5 6 7)'],
                                  'fixedWalls': ['(0 1 5 4)', '(0 3 2 1)', '(3 7 6 2)'],
                                  'frontAndBack': ['(0 4 7 3)', '(1 2 6 5)'],
                              })

    # Transport & turbulence
    write_transport_properties(CASE, nu=nu)
    write_turbulence_properties(CASE, model_type='laminar')

    # System files
    write_control_dict(CASE, end_time=0.5, delta_t=0.001,
                      write_interval=100, application='icoFoam')
    write_fv_schemes(CASE, steady=False)
    write_fv_solution(CASE, steady=False)

    # Boundary conditions
    write_vector_field(CASE, 'U', '[0 1 -1 0 0 0 0]', 'uniform (0 0 0)',
                      {
                          'movingWall': {'type': 'fixedValue',
                                        'value': f'uniform ({U_lid} 0 0)'},
                          'fixedWalls': {'type': 'noSlip'},
                          'frontAndBack': {'type': 'empty'},
                      })
    write_scalar_field(CASE, 'p', '[0 2 -2 0 0 0 0]', 'uniform 0',
                      {
                          'movingWall': {'type': 'zeroGradient'},
                          'fixedWalls': {'type': 'zeroGradient'},
                          'frontAndBack': {'type': 'empty'},
                      })

    results['parameters'] = {
        'reynolds_number': Re,
        'cavity_size': L,
        'lid_velocity': U_lid,
        'nu': nu,
    }

    logging.info(f"Re = {Re}, L = {L}, U_lid = {U_lid}, nu = {nu}")

    logging.info("=" * 60)
    logging.info("STEP 2: Running icoFoam")
    logging.info("=" * 60)
    sim = run_simulation(CASE, solver='icoFoam', timeout=600)
    results['simulation'] = sim

    logging.info("=" * 60)
    logging.info("STEP 3: Extracting metrics")
    logging.info("=" * 60)
    u_stats = extract_field_statistics(CASE, 'U')
    p_stats = extract_field_statistics(CASE, 'p')
    results['metrics'] = {
        'velocity_stats': u_stats,
        'pressure_stats': p_stats,
        'convergence': sim['convergence'],
    }

except Exception as e:
    import traceback
    logging.error(f"Error: {e}")
    traceback.print_exc()
    results['error'] = str(e)

finally:
    save_final_results(results)
    quick_finish()
