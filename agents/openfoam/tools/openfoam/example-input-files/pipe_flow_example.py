#!/usr/bin/env python3
"""Example: Pipe flow pressure drop calculation.

Simulates turbulent flow in a 0.1m diameter, 1m long pipe at 1 m/s.
Extracts pressure drop and friction factor.
"""
import sys
sys.path.insert(0, '/app')
from openfoam_utils import *
import logging

quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir')
CASE = '/workdir/pipe_case'
results = {}

try:
    logging.info("=" * 60)
    logging.info("STEP 1: Setting up pipe flow case")
    logging.info("=" * 60)
    params = setup_pipe_flow(
        CASE, velocity=1.0, diameter=0.1, length=1.0,
        nu=1e-6, n_iterations=500
    )
    results['parameters'] = params
    logging.info(f"Re = {params['reynolds_number']:.0f}, solver = {params['solver']}")

    logging.info("=" * 60)
    logging.info("STEP 2: Running simulation")
    logging.info("=" * 60)
    sim = run_simulation(CASE, solver=params['solver'], timeout=1800)
    results['simulation'] = sim

    logging.info("=" * 60)
    logging.info("STEP 3: Extracting metrics")
    logging.info("=" * 60)
    dp = extract_pressure_drop(CASE)
    results['metrics'] = {
        'pressure_drop': dp,
        'convergence': sim['convergence'],
    }
    logging.info(f"Pressure drop: {dp}")

except Exception as e:
    import traceback
    logging.error(f"Error: {e}")
    traceback.print_exc()
    results['error'] = str(e)

finally:
    save_final_results(results)
    quick_finish()
