#!/usr/bin/env python3
"""
OpenFOAM run.py — entrypoint wrapper for the Discovery agent.

Supports TWO execution modes:
  A. PARAMS MODE (Discovery Studio): Receives a JSON string with structured
     simulation parameters via sys.argv[1]. The JSON has no single quotes,
     so it survives bash '{{params_json}}' substitution safely.
  B. SCRIPT MODE  (Workbench): Finds a .py script in /input/ uploaded via
     job_submit_code or job_submit_action with session_id.

Script discovery priority:
  1. JSON params in sys.argv[1] (Discovery Studio — preferred)
  2. .py file(s) already present in /input/ (Workbench mode)
  3. JSON params file in /input/ with a 'scenario' field
  4. Environment variable OPENFOAM_PARAMS_JSON
"""
import glob
import json
import os
import runpy
import sys
import traceback
import logging


def log(msg):
    """Print a timestamped diagnostic message."""
    print(f"[run.py] {msg}", flush=True)


# =====================================================================
# PARAMS MODE — run scenario directly from structured JSON
# =====================================================================

SCENARIO_PARAM_KEYS = {
    'pipe_flow': ['velocity', 'diameter', 'length', 'nu', 'n_iterations'],
    'mrf_fan': ['rpm', 'inlet_velocity', 'nu', 'duct_length', 'duct_radius',
                'hub_radius', 'rotor_length', 'rotor_position',
                'nx', 'ny', 'nz', 'n_iterations', 'turb_model'],
    'external_flow': ['velocity', 'domain_x', 'domain_y', 'domain_z',
                      'nx', 'ny', 'nz', 'nu', 'n_iterations', 'turb_model'],
    'heat_transfer': ['velocity', 'T_inlet', 'T_wall',
                      'domain_x', 'domain_y', 'domain_z',
                      'nx', 'ny', 'nz', 'nu', 'n_iterations'],
    'cavity': ['velocity', 'domain_x', 'domain_y', 'domain_z',
               'nx', 'ny', 'nz', 'nu', 'n_iterations'],
}


def run_from_params(params):
    """Execute a CFD scenario directly from structured parameters.

    This is the preferred mode for Discovery Studio where template
    substitution of raw Python scripts is unsafe.
    """
    from openfoam_utils import (
        quick_setup, quick_finish, save_final_results,
        setup_pipe_flow, setup_box_flow, setup_heated_surface,
        setup_mrf_fan_flow, run_simulation,
        extract_pressure_drop, extract_forces,
        extract_field_statistics, extract_fan_metrics, rpm_to_rads,
    )

    quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir')
    CASE = '/workdir/cfd_case'
    scenario = params.get('scenario', 'pipe_flow')
    results = {'scenario': scenario, 'input_parameters': dict(params)}

    log(f"=== PARAMS MODE: scenario={scenario} ===")
    log(f"Parameters: {json.dumps(params, indent=2)}")

    try:
        # ---- PIPE FLOW ----
        if scenario == 'pipe_flow':
            kw = _extract_kwargs(params, SCENARIO_PARAM_KEYS['pipe_flow'])
            setup = setup_pipe_flow(CASE, **kw)
            results['setup'] = setup
            log(f"Setup complete: Re={setup.get('Re')}, solver={setup.get('solver')}")

            sim = run_simulation(CASE, solver=setup.get('solver', 'simpleFoam'))
            results['simulation'] = sim

            metrics = extract_pressure_drop(CASE,
                                            inlet_patch='inlet',
                                            outlet_patch='outlet')
            results['metrics'] = metrics
            log(f"Pressure drop: {metrics}")

        # ---- MRF FAN ----
        elif scenario == 'mrf_fan':
            kw = _extract_kwargs(params, SCENARIO_PARAM_KEYS['mrf_fan'])
            setup = setup_mrf_fan_flow(CASE, **kw)
            results['setup'] = setup
            log(f"MRF setup complete")

            sim = run_simulation(CASE, solver='simpleFoam')
            results['simulation'] = sim

            rpm = params.get('rpm', 3000.0)
            metrics = extract_fan_metrics(
                CASE,
                inlet_patch='inlet',
                outlet_patch='outlet',
                rotor_zone='rotorZone',
                omega_rads=rpm_to_rads(rpm),
                duct_radius=params.get('duct_radius', 0.15),
            )
            results['metrics'] = metrics
            log(f"Fan metrics: {metrics}")

        # ---- EXTERNAL FLOW ----
        elif scenario == 'external_flow':
            kw = _extract_kwargs(params, SCENARIO_PARAM_KEYS['external_flow'])
            setup = setup_box_flow(CASE, **kw)
            results['setup'] = setup
            log(f"Box flow setup complete: Re={setup.get('Re')}")

            sim = run_simulation(CASE, solver=setup.get('solver', 'simpleFoam'))
            results['simulation'] = sim

            try:
                forces = extract_forces(CASE,
                                        patch_name=params.get('patch_name', 'walls'))
                results['forces'] = forces
            except Exception as e:
                log(f"Force extraction skipped: {e}")

            field_stats = extract_field_statistics(CASE, field='U')
            results['field_stats'] = field_stats

        # ---- HEAT TRANSFER ----
        elif scenario == 'heat_transfer':
            kw = _extract_kwargs(params, SCENARIO_PARAM_KEYS['heat_transfer'])
            setup = setup_heated_surface(CASE, **kw)
            results['setup'] = setup
            log(f"Heated surface setup complete")

            sim = run_simulation(CASE, solver='simpleFoam')
            results['simulation'] = sim

            T_stats = extract_field_statistics(CASE, field='T')
            results['temperature_stats'] = T_stats
            U_stats = extract_field_statistics(CASE, field='U')
            results['velocity_stats'] = U_stats

        # ---- LID-DRIVEN CAVITY ----
        elif scenario == 'cavity':
            kw = _extract_kwargs(params, SCENARIO_PARAM_KEYS['cavity'])
            # Cavity uses box flow setup with special BCs
            kw.setdefault('domain_x', 0.1)
            kw.setdefault('domain_y', 0.1)
            kw.setdefault('domain_z', 0.01)
            kw.setdefault('nx', 50)
            kw.setdefault('ny', 50)
            kw.setdefault('nz', 1)
            setup = setup_box_flow(CASE, **kw)
            results['setup'] = setup

            # Cavity typically uses icoFoam for laminar transient
            solver = 'icoFoam' if setup.get('Re', 1000) < 2300 else 'simpleFoam'
            sim = run_simulation(CASE, solver=solver)
            results['simulation'] = sim

            U_stats = extract_field_statistics(CASE, field='U')
            results['velocity_stats'] = U_stats

        else:
            raise ValueError(
                f"Unknown scenario: '{scenario}'. "
                f"Valid: {list(SCENARIO_PARAM_KEYS.keys())}"
            )

        results['status'] = 'completed'
        log("=== SIMULATION COMPLETED SUCCESSFULLY ===")

    except Exception as e:
        log(f"ERROR: {e}")
        traceback.print_exc()
        results['error'] = str(e)
        results['traceback'] = traceback.format_exc()
        results['status'] = 'failed'

    finally:
        save_final_results(results)
        quick_finish()

    return 0 if results.get('status') == 'completed' else 1


def _extract_kwargs(params, valid_keys):
    """Extract only the keys relevant to a setup function."""
    return {k: params[k] for k in valid_keys if k in params}


# =====================================================================
# SCRIPT MODE — find and execute a user-provided .py script
# =====================================================================

def find_script():
    """Locate /input/script.py from available sources (Workbench mode)."""

    log("=== SCRIPT DISCOVERY ===")
    input_contents = os.listdir('/input/') if os.path.isdir('/input/') else []
    log(f"/input/ contents ({len(input_contents)} items): {input_contents}")

    # .py files in /input/ (job_submit_code uploads them here)
    py_files = sorted(glob.glob('/input/*.py'))
    if py_files:
        chosen = py_files[0]
        if len(py_files) > 1:
            for preferred in ('script.py', 'main.py'):
                candidate = f'/input/{preferred}'
                if candidate in py_files:
                    chosen = candidate
                    break
            else:
                for f in py_files:
                    if os.path.basename(f).startswith('run_'):
                        chosen = f
                        break
        log(f"Found script: {chosen}")
        return chosen

    # JSON params file in /input/
    for params_path in ('/input/input.json', '/input/params.json',
                        '/input/parameters.json', '/input/tool_input.json'):
        if os.path.exists(params_path):
            try:
                with open(params_path) as f:
                    data = json.load(f)
                if 'scenario' in data:
                    log(f"Found params file: {params_path}")
                    return ('params', data)
                if 'script_content' in data and data['script_content']:
                    content = data['script_content']
                    with open('/input/script.py', 'w') as f:
                        f.write(content)
                    return '/input/script.py'
            except Exception as e:
                log(f"Error reading {params_path}: {e}")

    # Environment variable
    env_content = os.environ.get('OPENFOAM_PARAMS_JSON', '')
    if env_content.strip():
        try:
            data = json.loads(env_content)
            if 'scenario' in data:
                log(f"Found params in OPENFOAM_PARAMS_JSON env var")
                return ('params', data)
        except json.JSONDecodeError:
            pass

    # Nothing found
    log("ERROR: No script or params found")
    log(f"  /input/: {input_contents}")
    log(f"  sys.argv: {sys.argv}")
    env_keys = sorted(os.environ.keys())
    log(f"  Env vars ({len(env_keys)}): {env_keys}")
    for root, dirs, files in os.walk('/input/'):
        for fname in files:
            fpath = os.path.join(root, fname)
            log(f"  FILE: {fpath} ({os.path.getsize(fpath)} bytes)")
    return None


# =====================================================================
# MAIN
# =====================================================================

def main():
    log("=== OPENFOAM RUN.PY STARTING ===")
    log(f"sys.argv ({len(sys.argv)}): {sys.argv[:3]}{'...' if len(sys.argv) > 3 else ''}")

    # --- Priority 1: JSON params from sys.argv[1] (Studio mode) ---
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        # Step 1: HTML-unescape (&quot; -> ", &#34; -> ", &apos; -> ', etc.)
        import html
        arg = html.unescape(arg)
        # Step 2: Normalize Unicode curly/smart quotes to ASCII
        arg = (arg.replace('\u201c', '"').replace('\u201d', '"')
                  .replace('\u2018', "'").replace('\u2019', "'")
                  .replace('\u00ab', '"').replace('\u00bb', '"')
                  .replace('\uff02', '"').replace('\uff07', "'")
                  .replace('\uff5b', '{').replace('\uff5d', '}'))
        log(f"Cleaned arg (first 200): {arg[:200]}")
        if arg.startswith('{'):
            try:
                params = json.loads(arg)
                if 'scenario' in params:
                    log(f"[PARAMS MODE] scenario={params['scenario']}")
                    exit_code = run_from_params(params)
                    sys.exit(exit_code)
            except json.JSONDecodeError as e:
                log(f"sys.argv[1] looks like JSON but failed to parse: {e}")
                log(f"First 200 chars: {arg[:200]}")
                log(f"Byte repr: {arg[:100].encode('utf-8')}")

    # --- Priority 2+: Script discovery (Workbench mode) ---
    result = find_script()

    if result is None:
        _write_error_output("No Python script or params found", "", None)
        sys.exit(1)

    # Params found via file/env
    if isinstance(result, tuple) and result[0] == 'params':
        log(f"[PARAMS MODE via file] scenario={result[1].get('scenario')}")
        exit_code = run_from_params(result[1])
        sys.exit(exit_code)

    # Script found — execute it
    script = result
    try:
        with open(script) as f:
            lines = f.readlines()
        log(f"Script: {script} ({len(lines)} lines, {os.path.getsize(script)} bytes)")
        log("--- preview (first 15 lines) ---")
        for i, line in enumerate(lines[:15]):
            log(f"  {i+1:>3}: {line.rstrip()}")
        if len(lines) > 15:
            log(f"  ... ({len(lines) - 15} more lines)")
        log("--- end preview ---")

        log(f"=== EXECUTING {script} ===")
        sys.argv = [script]
        runpy.run_path(script, run_name='__main__')
        log("=== EXECUTION COMPLETE ===")

    except SystemExit as e:
        code = e.code if e.code is not None else 0
        log(f"Script exited with code {code}")
        if code != 0:
            _write_error_output(f"Script exited with code {code}",
                                traceback.format_exc(), script)
            raise

    except Exception as e:
        log(f"UNHANDLED ERROR: {e}")
        traceback.print_exc()
        _write_error_output(str(e), traceback.format_exc(), script)
        sys.exit(1)

    finally:
        out_contents = os.listdir('/output/') if os.path.isdir('/output/') else []
        log(f"Final /output/ ({len(out_contents)} items): {out_contents}")
        if not out_contents:
            log("WARNING: /output/ is EMPTY")


def _write_error_output(error_msg, tb_text, script_path):
    """Save error details to /output/error.json."""
    try:
        error_info = {
            'error': error_msg,
            'traceback': tb_text,
            'script': script_path,
            'input_contents': os.listdir('/input/') if os.path.isdir('/input/') else [],
            'output_contents': os.listdir('/output/') if os.path.isdir('/output/') else [],
        }
        with open('/output/error.json', 'w') as f:
            json.dump(error_info, f, indent=2)
        log("Error details saved to /output/error.json")
    except Exception:
        log("Could not write error.json")


if __name__ == '__main__':
    main()