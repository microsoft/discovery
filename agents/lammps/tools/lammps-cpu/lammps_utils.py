"""
LAMMPS Utilities Library

Helper functions for running LAMMPS simulations and analyzing output.
This module is pre-installed in the LAMMPS container for use by generated scripts.

Usage:
    from lammps_utils import run_lammps, parse_temperature_profile, compute_thermal_conductivity_nemd
"""

import os
import sys
import re
import glob
import json
import time
import shutil
import logging
import subprocess
import multiprocessing

import numpy as np
from scipy import stats

# ============= CONFIGURATION =============

# Detect available CPU cores
NUM_CORES = os.cpu_count() or multiprocessing.cpu_count() or 1

# Standard directories — MUST be set via setup_directories() before use.
# No defaults: the agent-generated code must provide paths from dataHandlingContext.
INPUT_DIR: str = ''
WORK_DIR: str = ''
OUTPUT_DIR: str = ''
_DIRS_CONFIGURED = False


def _require_dirs():
    """Raise if setup_directories() has not been called."""
    if not _DIRS_CONFIGURED:
        raise RuntimeError(
            "Directories not configured. Call setup_directories(input_dir=..., output_dir=...) "
            "before using any utility functions."
        )


def setup_logging():
    """Configure logging with explicit flushing for real-time output in containers."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stdout,
        force=True
    )
    # Force unbuffered output
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode='w', buffering=1)


def setup_directories(input_dir, output_dir, work_dir=None, copy_input=True):
    """Create standard working directories and optionally copy input files.

    Args:
        input_dir: Path to the input directory (required).
        output_dir: Path to the output directory (required).
        work_dir: Path to the working directory. If None, works directly in output_dir.
        copy_input: If True, copy input files to the working directory so that
                    relative paths (e.g. ``run_lammps("in.lj.ehex", ...)``) resolve
                    correctly after ``os.chdir(WORK_DIR)``.
    """
    global INPUT_DIR, WORK_DIR, OUTPUT_DIR, _DIRS_CONFIGURED
    INPUT_DIR = input_dir
    OUTPUT_DIR = output_dir
    WORK_DIR = work_dir if work_dir is not None else '/app/workdir'
    _DIRS_CONFIGURED = True
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    logging.info(f"Input directory: {INPUT_DIR}")
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Output directory: {OUTPUT_DIR}")
    logging.info(f"Detected {NUM_CORES} CPU cores available")
    if copy_input:
        copy_input_files()


def copy_input_files(patterns=None):
    """Copy input files from input directory to working directory.

    Args:
        patterns: List of glob patterns to copy. Defaults to common LAMMPS patterns.

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        logging.info("Input directory is working directory; skipping copy_input_files")
        return []
    if patterns is None:
        patterns = ['in.*', 'data.*', '*.lmp', '*.in', '*.data', '*.params', '*.ff']

    copied = []
    for pattern in patterns:
        for src_file in glob.glob(os.path.join(INPUT_DIR, pattern)):
            dst_file = os.path.join(WORK_DIR, os.path.basename(src_file))
            shutil.copy(src_file, dst_file)
            logging.info(f"Copied: {os.path.basename(src_file)}")
            copied.append(dst_file)
    return copied


def copy_outputs(patterns=None):
    """Copy output files to output directory.

    Args:
        patterns: List of glob patterns to copy. Defaults to common output patterns.

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        logging.info("Working directory is output directory; skipping copy_outputs")
        return []
    if patterns is None:
        patterns = ['*.log', '*.lammpstrj', '*.restart', 'out.*', '*.dat', '*.csv', '*.png']

    copied = []
    for pattern in patterns:
        for src_file in glob.glob(os.path.join(WORK_DIR, pattern)):
            dst_file = os.path.join(OUTPUT_DIR, os.path.basename(src_file))
            shutil.copy(src_file, dst_file)
            logging.info(f"Output: {os.path.basename(src_file)}")
            copied.append(dst_file)
    return copied


# ============= COMMAND EXECUTION =============

def run_command(command, cwd=None):
    """Execute subprocess command with error handling and timing.

    Args:
        command: List of command arguments (e.g., ["lmp", "-in", "input.lmp"])
        cwd: Working directory for the command

    Returns:
        subprocess.CompletedProcess result

    Raises:
        subprocess.CalledProcessError: If command fails
    """
    try:
        cmd_str = ' '.join(command)
        logging.info(f"Executing: {cmd_str}")
        start_time = time.time()

        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd
        )

        elapsed = time.time() - start_time
        logging.info(f"Completed in {elapsed:.2f}s: {cmd_str}")

        if result.stdout:
            print(result.stdout)
        sys.stdout.flush()

        return result

    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        logging.error(f"Failed after {elapsed:.2f}s: {' '.join(command)}")
        if e.stdout:
            logging.info(f"STDOUT: {e.stdout}")
        if e.stderr:
            logging.error(f"STDERR: {e.stderr}")
        sys.stdout.flush()
        raise


def get_atom_count_from_data_file(data_file):
    """Extract the number of atoms from a LAMMPS data file header.

    LAMMPS data files have a header section with lines like:
        2000 atoms
        1000 bonds
        ...

    Args:
        data_file: Path to LAMMPS data file

    Returns:
        int: Number of atoms, or None if not found
    """
    try:
        with open(data_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Look for "N atoms" pattern
                match = re.match(r'^\s*(\d+)\s+atoms\b', line, re.IGNORECASE)
                if match:
                    return int(match.group(1))
                # Stop if we hit the Atoms section (header is done)
                if line.lower().startswith('atoms'):
                    break
    except (IOError, OSError) as e:
        logging.warning(f"Could not read data file {data_file}: {e}")
    return None


def get_box_dimensions_from_data_file(data_file):
    """Extract box dimensions (Lx, Ly, Lz) from a LAMMPS data file header.

    LAMMPS data files have box bounds in the header section:
        0.0 50.0 xlo xhi
        0.0 50.0 ylo yhi
        0.0 100.0 zlo zhi

    For triclinic boxes, there may be tilt factors (ignored here):
        0.0 50.0 0.0 xlo xhi xy

    Args:
        data_file: Path to LAMMPS data file

    Returns:
        dict with keys:
            - Lx, Ly, Lz: Box dimensions
            - xlo, xhi, ylo, yhi, zlo, zhi: Box bounds
            - volume: Box volume (Lx * Ly * Lz)
        Returns None if box bounds not found.

    Example:
        >>> box = get_box_dimensions_from_data_file("data.lj")
        >>> area = box['Lx'] * box['Ly']  # Cross-sectional area for NEMD
        >>> volume = box['volume']  # For Green-Kubo
    """
    bounds = {}

    try:
        with open(data_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Look for box bound lines: "lo hi xlo xhi" or "lo hi tilt xlo xhi xy"
                # Pattern: two floats followed by xlo/ylo/zlo xhi/yhi/zhi
                parts = line.split()

                if len(parts) >= 4:
                    # Check for xlo xhi, ylo yhi, zlo zhi patterns
                    if 'xlo' in line.lower() and 'xhi' in line.lower():
                        try:
                            bounds['xlo'] = float(parts[0])
                            bounds['xhi'] = float(parts[1])
                        except (ValueError, IndexError):
                            pass
                    elif 'ylo' in line.lower() and 'yhi' in line.lower():
                        try:
                            bounds['ylo'] = float(parts[0])
                            bounds['yhi'] = float(parts[1])
                        except (ValueError, IndexError):
                            pass
                    elif 'zlo' in line.lower() and 'zhi' in line.lower():
                        try:
                            bounds['zlo'] = float(parts[0])
                            bounds['zhi'] = float(parts[1])
                        except (ValueError, IndexError):
                            pass

                # Stop if we hit the Atoms section (header is done)
                if line.lower() == 'atoms' or line.lower().startswith('atoms '):
                    break

        # Calculate dimensions if we have all bounds
        if all(k in bounds for k in ['xlo', 'xhi', 'ylo', 'yhi', 'zlo', 'zhi']):
            bounds['Lx'] = bounds['xhi'] - bounds['xlo']
            bounds['Ly'] = bounds['yhi'] - bounds['ylo']
            bounds['Lz'] = bounds['zhi'] - bounds['zlo']
            bounds['volume'] = bounds['Lx'] * bounds['Ly'] * bounds['Lz']
            logging.info(f"Box dimensions from {data_file}: Lx={bounds['Lx']:.3f}, Ly={bounds['Ly']:.3f}, Lz={bounds['Lz']:.3f}")
            return bounds

        logging.warning(f"Could not find complete box bounds in {data_file}")
        return None

    except (IOError, OSError) as e:
        logging.warning(f"Could not read data file {data_file}: {e}")
        return None


def get_data_file_from_input(input_file):
    """Extract the data file path from a LAMMPS input script.

    Searches for 'read_data' command in the input file.
    Handles both quoted and unquoted filenames.

    Args:
        input_file: Path to LAMMPS input script

    Returns:
        str: Path to data file (relative to input file directory), or None if not found
    """
    try:
        input_dir = os.path.dirname(input_file) or '.'
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments
                if line.startswith('#'):
                    continue
                # Look for read_data command - handle quoted or unquoted filenames
                # Pattern matches: read_data "file" or read_data 'file' or read_data file
                match = re.match(r'^read_data\s+["\']?([^"\'\s]+)["\']?', line, re.IGNORECASE)
                if match:
                    data_file = match.group(1)
                    # Strip any remaining quotes (belt and suspenders)
                    data_file = data_file.strip('"\'')
                    # Handle relative paths
                    if not os.path.isabs(data_file):
                        # Try relative to input file directory first
                        candidate = os.path.join(input_dir, data_file)
                        if os.path.exists(candidate):
                            return candidate
                        # Try current directory
                        if os.path.exists(data_file):
                            return data_file
                    return data_file
    except (IOError, OSError) as e:
        logging.warning(f"Could not read input file {input_file}: {e}")
    return None


def auto_detect_atom_count(input_file):
    """Automatically detect atom count from a LAMMPS input file.

    Parses the input script to find the read_data command, then reads the
    data file header to extract the atom count.

    Args:
        input_file: Path to LAMMPS input script

    Returns:
        int: Number of atoms, or None if detection fails
    """
    data_file = get_data_file_from_input(input_file)
    if data_file is None:
        logging.debug(f"No read_data command found in {input_file}")
        return None

    num_atoms = get_atom_count_from_data_file(data_file)
    if num_atoms is not None:
        logging.info(f"Auto-detected {num_atoms} atoms from {data_file}")
    return num_atoms


def get_heat_flux_from_input(input_file):
    """Extract heat flux value from LAMMPS input script.

    Parses fix commands that impose heat flux for NEMD simulations:
    - fix ehex: Enhanced Heat Exchange (recommended)
    - fix heat: Simple velocity rescaling

    Syntax patterns:
        fix ID group ehex N flux [region region-ID]
        fix ID group heat N flux [region region-ID]

    Args:
        input_file: Path to LAMMPS input script

    Returns:
        dict with keys:
            - heat_flux: Absolute value of heat flux (energy/time)
            - method: 'ehex' or 'heat'
            - fix_ids: List of fix IDs found (e.g., ['hot', 'cold'])
            - raw_values: List of raw flux values (positive and negative)
        Returns None if no heat flux fix found.

    Example:
        >>> flux_info = get_heat_flux_from_input("in.lj.ehex")
        >>> heat_flux = flux_info['heat_flux']  # Use this for thermal conductivity
        >>> print(f"Method: {flux_info['method']}, J = {heat_flux}")
    """
    heat_fixes = []

    try:
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue

                # Remove inline comments
                if '#' in line:
                    line = line[:line.index('#')].strip()

                parts = line.split()
                if len(parts) < 6:
                    continue

                # Look for: fix ID group ehex/heat N flux ...
                if parts[0].lower() == 'fix':
                    fix_id = parts[1]
                    # parts[2] is group
                    fix_type = parts[3].lower()

                    if fix_type in ('ehex', 'heat'):
                        try:
                            # parts[4] is N (nevery), parts[5] is flux
                            flux_value = float(parts[5])
                            heat_fixes.append({
                                'fix_id': fix_id,
                                'method': fix_type,
                                'flux': flux_value
                            })
                        except (ValueError, IndexError):
                            continue

        if not heat_fixes:
            logging.debug(f"No heat flux fix (ehex/heat) found in {input_file}")
            return None

        # Extract results
        raw_values = [f['flux'] for f in heat_fixes]
        methods = list(set(f['method'] for f in heat_fixes))
        fix_ids = [f['fix_id'] for f in heat_fixes]

        # Heat flux magnitude (use absolute value of positive flux)
        # In NEMD, one fix adds heat (+) and one removes (-)
        positive_fluxes = [v for v in raw_values if v > 0]
        if positive_fluxes:
            heat_flux = positive_fluxes[0]
        else:
            # If only negative values, use absolute value
            heat_flux = abs(min(raw_values))

        result = {
            'heat_flux': heat_flux,
            'method': methods[0] if len(methods) == 1 else 'mixed',
            'fix_ids': fix_ids,
            'raw_values': raw_values
        }

        logging.info(f"Heat flux from {input_file}: {heat_flux} ({result['method']} method)")
        return result

    except (IOError, OSError) as e:
        logging.warning(f"Could not read input file {input_file}: {e}")
        return None


def get_simulation_parameters_from_input(input_file, data_file=None):
    """Extract all key simulation parameters from LAMMPS input script.

    This is a convenience function that extracts commonly needed parameters
    for post-processing analysis in a single call. It parses the input script
    and optionally the associated data file.

    Args:
        input_file: Path to LAMMPS input script
        data_file: Path to data file (optional; auto-detected from input if not provided)

    Returns:
        dict with keys:
            - units: Unit system ('lj', 'real', 'metal', 'si', 'cgs', 'electron', 'micro', 'nano')
            - timestep: Simulation timestep (in unit-appropriate time units)
            - temperature: Target temperature (from fix nvt/npt or variable T/temp)
            - heat_flux: Heat flux magnitude (if fix ehex/heat present)
            - heat_flux_method: 'ehex' or 'heat' (if applicable)
            - data_file: Path to data file (from read_data command)
            - box: Box dimensions dict (if data_file found and readable)
            - atom_count: Number of atoms (if data_file found and readable)
        Values are None if not found/applicable.

    Example:
        >>> params = get_simulation_parameters_from_input("in.lj.ehex")
        >>> print(f"Units: {params['units']}, dt: {params['timestep']}, T: {params['temperature']}")
        >>> if params['box']:
        ...     area = params['box']['Lx'] * params['box']['Ly']
        ...     kappa = compute_thermal_conductivity_nemd(T_profile, params['heat_flux'], area)
    """
    params = {
        'units': None,
        'timestep': None,
        'temperature': None,
        'heat_flux': None,
        'heat_flux_method': None,
        'data_file': None,
        'box': None,
        'atom_count': None
    }

    try:
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue

                # Remove inline comments
                if '#' in line:
                    line = line[:line.index('#')].strip()

                parts = line.split()
                if not parts:
                    continue

                cmd = parts[0].lower()

                # Parse units command: "units lj"
                if cmd == 'units' and len(parts) >= 2:
                    params['units'] = parts[1].lower()

                # Parse timestep command: "timestep 0.005"
                elif cmd == 'timestep' and len(parts) >= 2:
                    try:
                        params['timestep'] = float(parts[1])
                    except ValueError:
                        pass

                # Parse temperature from fix nvt/npt: "fix ID group nvt temp T_start T_stop ..."
                elif cmd == 'fix' and len(parts) >= 6:
                    fix_style = parts[3].lower()
                    if fix_style in ('nvt', 'npt', 'nvt/omp', 'npt/omp'):
                        # Look for "temp" keyword followed by T_start T_stop
                        for i, p in enumerate(parts):
                            if p.lower() == 'temp' and i + 2 < len(parts):
                                try:
                                    # T_start and T_stop - use T_start as the target
                                    params['temperature'] = float(parts[i + 1])
                                    break
                                except ValueError:
                                    pass

                # Parse temperature from variable: "variable T equal 1.0" or "variable temp equal 300"
                elif cmd == 'variable' and len(parts) >= 4:
                    var_name = parts[1].lower()
                    if var_name in ('t', 'temp', 'temperature') and parts[2].lower() == 'equal':
                        try:
                            params['temperature'] = float(parts[3])
                        except ValueError:
                            pass

                # Parse read_data command: "read_data data.lj"
                elif cmd == 'read_data' and len(parts) >= 2:
                    params['data_file'] = parts[1].strip('"\'')

    except (IOError, OSError) as e:
        logging.warning(f"Could not read input file {input_file}: {e}")
        return params

    # Get heat flux using dedicated function
    heat_flux_info = get_heat_flux_from_input(input_file)
    if heat_flux_info:
        params['heat_flux'] = heat_flux_info['heat_flux']
        params['heat_flux_method'] = heat_flux_info['method']

    # Resolve data file path and get box dimensions
    if data_file is None and params['data_file']:
        # Try to find data file relative to input file
        input_dir = os.path.dirname(input_file) or '.'
        candidate = os.path.join(input_dir, params['data_file'])
        if os.path.exists(candidate):
            data_file = candidate
        elif os.path.exists(params['data_file']):
            data_file = params['data_file']

    if data_file:
        params['data_file'] = data_file
        params['box'] = get_box_dimensions_from_data_file(data_file)
        params['atom_count'] = get_atom_count_from_data_file(data_file)

    logging.info(f"Simulation parameters from {input_file}: units={params['units']}, "
                 f"dt={params['timestep']}, T={params['temperature']}")

    return params


def run_lammps(input_file, log_file=None, num_atoms=None, num_cores=None, auto_detect=True):
    """Run LAMMPS with optimal parallelization based on system size.

    Automatically selects between OpenMP (for small systems) and MPI (for large systems).

    Args:
        input_file: Path to LAMMPS input script
        log_file: Path for log file (default: derived from input_file)
        num_atoms: Number of atoms in system (used to select parallelization strategy)
                   If None and auto_detect=True, attempts to detect from data file
        num_cores: Number of cores to use (default: all available)
        auto_detect: If True and num_atoms not provided, automatically detect
                     atom count from the data file (default: True)

    Parallelization strategy:
        - num_atoms < 5000: OpenMP (lower communication overhead)
        - num_atoms >= 5000: MPI (better scaling for large systems)
    """
    if log_file is None:
        base = os.path.splitext(os.path.basename(input_file))[0]
        log_file = f"{base}.log"

    # Auto-detect atom count if not provided
    if num_atoms is None and auto_detect:
        num_atoms = auto_detect_atom_count(input_file)

    cores = num_cores or NUM_CORES

    # Default to OpenMP for small/unknown systems
    use_openmp = (num_atoms is None) or (num_atoms < 5000)

    if cores > 1:
        if use_openmp:
            # OpenMP: better for small systems, lower communication overhead
            os.environ["OMP_NUM_THREADS"] = str(cores)
            lammps_cmd = [
                "lmp", "-sf", "omp", "-pk", "omp", str(cores),
                "-in", input_file, "-log", log_file
            ]
            logging.info(f"Using OpenMP with {cores} threads (small system mode)")
        else:
            # MPI: better for large systems
            lammps_cmd = [
                "mpirun", "--allow-run-as-root", "--oversubscribe",
                "-np", str(cores), "lmp",
                "-in", input_file, "-log", log_file
            ]
            logging.info(f"Using MPI with {cores} ranks (large system mode)")
    else:
        lammps_cmd = ["lmp", "-in", input_file, "-log", log_file]
        logging.info("Running in serial mode")

    return run_command(lammps_cmd)


# ============= FILE MODIFICATION =============

def modify_lammps_variable(content, var_name, new_value):
    """Modify a LAMMPS variable in script content using regex.

    Handles variable whitespace in LAMMPS input files.

    Args:
        content: Original script content (string)
        var_name: Variable name to modify (e.g., "dt", "temp")
        new_value: New value for the variable

    Returns:
        Modified script content

    Example:
        modified = modify_lammps_variable(script, "dt", 0.001)
    """
    pattern = rf'variable\s+{var_name}\s+equal\s+[\d.eE+-]+'
    replacement = f'variable {var_name} equal {new_value}'
    modified = re.sub(pattern, replacement, content)
    return modified


def create_parameter_sweep_inputs(original_file, var_name, values, output_prefix=None):
    """Create multiple input files for a parameter sweep.

    Args:
        original_file: Path to original LAMMPS input script
        var_name: Variable name to sweep (e.g., "dt", "temp")
        values: List of values to sweep over
        output_prefix: Prefix for output files (default: original filename)

    Returns:
        List of (input_file, value) tuples

    Example:
        files = create_parameter_sweep_inputs("in.lj.hex", "dt", [0.001, 0.005, 0.01])
    """
    with open(original_file, 'r') as f:
        original_content = f.read()

    if output_prefix is None:
        output_prefix = os.path.splitext(os.path.basename(original_file))[0]

    created_files = []
    for value in values:
        modified = modify_lammps_variable(original_content, var_name, value)
        output_file = f"{output_prefix}_{var_name}{value}"

        with open(output_file, 'w') as f:
            f.write(modified)

        # Verify modification
        if f'variable {var_name} equal {value}' not in modified:
            logging.warning(f"Variable {var_name} may not have been modified correctly")

        created_files.append((output_file, value))
        logging.info(f"Created: {output_file} with {var_name}={value}")

    return created_files


# ============= THERMAL CONDUCTIVITY ANALYSIS =============

def parse_temperature_profile(filename):
    """Parse LAMMPS temperature profile output (out.T* files).

    Args:
        filename: Path to temperature profile file (fix ave/chunk output)

    Returns:
        numpy array with columns [z_coordinate, temperature]

    File format expected (fix ave/chunk output):
        # Chunk-averaged data
        # Timestep Number-of-chunks
        # Chunk Coord Ncount v_T
        1 -14.5 33.0 1.02
        ...

    Note: Ncount may be float (time-averaged) or int depending on LAMMPS version/settings.
    """
    data = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 4:
                try:
                    chunk = int(parts[0])
                    coord = float(parts[1])
                    ncount = float(parts[2])  # Use float - LAMMPS may output time-averaged counts
                    temp = float(parts[3])
                    if ncount > 0:  # Only include bins with atoms
                        data.append((coord, temp))
                except (ValueError, IndexError):
                    continue
    return np.array(data)


def compute_thermal_conductivity_nemd(T_profile, heat_flux, area=None):
    """Compute thermal conductivity from NEMD temperature gradient.

    Uses Fourier's law: κ = J / (dT/dz)

    Args:
        T_profile: Temperature profile array from parse_temperature_profile()
        heat_flux: Imposed heat flux (energy/time, from fix ehex)
        area: Cross-sectional area (Lx * Ly). If None, returns κ*A.

    Returns:
        dict with keys:
            - kappa: thermal conductivity (or κ*A if area not provided)
            - dT_dz: temperature gradient
            - r_squared: R² of linear fit (quality metric)
            - slope_std_err: standard error of slope
    """
    z = T_profile[:, 0]
    T = T_profile[:, 1]

    # Fit linear profile, excluding hot/cold reservoir regions (use middle 60%)
    z_range = z.max() - z.min()
    mask = (z > z.min() + 0.2 * z_range) & (z < z.max() - 0.2 * z_range)

    if mask.sum() < 3:
        logging.warning("Too few points for linear fit, using all data")
        mask = np.ones(len(z), dtype=bool)

    slope, intercept, r_value, p_value, std_err = stats.linregress(z[mask], T[mask])
    dT_dz = abs(slope)

    # Thermal conductivity: κ = J / (A * dT/dz)
    if area is not None and area > 0:
        kappa = heat_flux / (area * dT_dz) if dT_dz > 0 else float('inf')
        # Error propagation: σ_κ/κ = σ_slope/slope
        kappa_std_err = kappa * (std_err / abs(slope)) if slope != 0 else float('inf')
    else:
        # Return κ*A if area not provided
        kappa = heat_flux / dT_dz if dT_dz > 0 else float('inf')
        kappa_std_err = kappa * (std_err / abs(slope)) if slope != 0 else float('inf')

    return {
        'kappa': kappa,
        'kappa_std_err': kappa_std_err,
        'dT_dz': dT_dz,
        'r_squared': r_value ** 2,
        'slope_std_err': std_err,
        'n_points': mask.sum()
    }


def parse_hfacf(filename, use_final_block=True):
    """Parse heat flux autocorrelation function from LAMMPS output.

    Handles LAMMPS fix ave/correlate output with "ave running" option,
    which produces multiple blocks as the running average evolves.
    By default, only the final (most converged) block is returned.

    File format (with ave running):
    - Header comments starting with #
    - Block header: "Timestep Nwindows" (2 values)
    - Block data: "Index TimeDelta Ncount Jx_acf Jy_acf Jz_acf" (6 values)

    Args:
        filename: Path to HFACF file (fix ave/correlate output)
        use_final_block: If True, only return data from the final block
                        (recommended for "ave running" output). Default: True

    Returns:
        numpy array with columns [timestep, Jx_acf, Jy_acf, Jz_acf]
        Returns empty 2D array with shape (0, 4) if no data found.
    """
    all_blocks = []
    current_block = []

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()

            # Detect block header: "Timestep Nwindows" (exactly 2 integer values)
            if len(parts) == 2:
                try:
                    int(parts[0])  # Timestep
                    int(parts[1])  # Nwindows
                    # Save previous block if non-empty and start new one
                    if current_block:
                        all_blocks.append(current_block)
                    current_block = []
                    continue
                except ValueError:
                    pass  # Not a block header, try parsing as data

            # Handle 6-column format: Index TimeDelta Ncount Jx Jy Jz
            if len(parts) >= 6:
                try:
                    # Second column is TimeDelta (in timesteps, not time)
                    time_delta = float(parts[1])
                    # ACF values are in columns 3, 4, 5
                    jx_acf = float(parts[3])
                    jy_acf = float(parts[4])
                    jz_acf = float(parts[5])
                    current_block.append((time_delta, jx_acf, jy_acf, jz_acf))
                except (ValueError, IndexError):
                    continue
            # Handle simpler 4-column format: timestep Jx Jy Jz
            elif len(parts) >= 4:
                try:
                    timestep = float(parts[0])
                    jx_acf = float(parts[1])
                    jy_acf = float(parts[2])
                    jz_acf = float(parts[3])
                    current_block.append((timestep, jx_acf, jy_acf, jz_acf))
                except (ValueError, IndexError):
                    continue

    # Don't forget the last block
    if current_block:
        all_blocks.append(current_block)

    if not all_blocks:
        logging.warning(f"No HFACF data found in {filename}. Check file format.")
        return np.empty((0, 4))

    # Use final block (most converged) or all data
    if use_final_block and len(all_blocks) > 1:
        logging.info(f"HFACF file contains {len(all_blocks)} blocks; using final block")
        data = all_blocks[-1]
    else:
        # Flatten all blocks (legacy behavior)
        data = [item for block in all_blocks for item in block]

    return np.array(data)


def compute_thermal_conductivity_gk(hfacf_data, volume, temperature=None, timestep=None, metal_units=False, temp=None, dt=None):
    """Compute thermal conductivity from Green-Kubo integral.

    Green-Kubo formula: κ = (V / 3kT²) × ∫₀^∞ <J(0)·J(t)> dt

    Args:
        hfacf_data: HFACF array from parse_hfacf() - shape (N, 4) with columns [timestep, Jx, Jy, Jz]
        volume: System volume
        temperature: System temperature (alias: temp)
        timestep: Simulation timestep (alias: dt)
        metal_units: If True, use metal units (eV, Angstrom, ps)
                    If False, use LJ units (kB=1)

    Returns:
        dict with keys:
            - kappa: thermal conductivity
            - integral: raw integral value
            - acf_data: tuple of (time, total_acf) for plotting
    """
    # Handle parameter aliases
    if temperature is None:
        temperature = temp
    if timestep is None:
        timestep = dt
    if temperature is None or timestep is None:
        raise ValueError("Must provide temperature and timestep")

    # Validate input data
    hfacf_data = np.array(hfacf_data)
    if hfacf_data.size == 0:
        raise ValueError("HFACF data is empty. Check that parse_hfacf() successfully read the file.")
    if hfacf_data.ndim != 2:
        raise ValueError(f"HFACF data must be 2D array with shape (N, 4), got shape {hfacf_data.shape}")
    if hfacf_data.shape[1] < 4:
        raise ValueError(f"HFACF data must have at least 4 columns [timestep, Jx, Jy, Jz], got {hfacf_data.shape[1]}")

    t = hfacf_data[:, 0] * timestep
    acf_x = hfacf_data[:, 1]
    acf_y = hfacf_data[:, 2]
    acf_z = hfacf_data[:, 3]
    total_acf = acf_x + acf_y + acf_z

    # Integrate using trapezoidal rule (use trapezoid for numpy >= 2.0 compatibility)
    def trapz_compat(y, x):
        try:
            return np.trapezoid(y, x)
        except AttributeError:
            return np.trapz(y, x)

    integral = trapz_compat(total_acf, t)

    # Also compute per-direction integrals for uncertainty estimation
    integral_x = trapz_compat(acf_x, t)
    integral_y = trapz_compat(acf_y, t)
    integral_z = trapz_compat(acf_z, t)

    # Boltzmann constant
    kB = 8.617333e-5 if metal_units else 1.0  # eV/K for metal, 1 for LJ

    # Prefactor for thermal conductivity
    # Green-Kubo formula: κ = (1 / 3Vk_B T²) × ∫<J(0)·J(t)> dt
    # Note: LAMMPS compute heat/flux returns total heat flux (not per volume),
    # so we divide by volume (not multiply)
    prefactor = 1.0 / (volume * kB * temperature ** 2)

    # Total thermal conductivity (using sum of all directions / 3)
    kappa = (prefactor / 3) * integral

    # Per-direction thermal conductivities for error estimation
    kappa_x = prefactor * integral_x
    kappa_y = prefactor * integral_y
    kappa_z = prefactor * integral_z

    # Standard error from directional components
    kappa_components = np.array([kappa_x, kappa_y, kappa_z])
    kappa_std_err = np.std(kappa_components, ddof=1) / np.sqrt(3)

    # R² is not directly applicable to Green-Kubo, but we can report
    # a "convergence quality" metric based on how well the 3 directions agree
    # Using coefficient of variation as a proxy (lower = better agreement)
    cv = np.std(kappa_components) / np.abs(np.mean(kappa_components)) if np.mean(kappa_components) != 0 else float('inf')
    # Convert to R²-like metric (1 = perfect agreement, 0 = poor)
    r_squared = max(0, 1 - cv)

    return {
        'kappa': kappa,
        'kappa_std_err': kappa_std_err,
        'kappa_x': kappa_x,
        'kappa_y': kappa_y,
        'kappa_z': kappa_z,
        'r_squared': r_squared,
        'integral': integral,
        'acf_data': (t, total_acf)
    }


# ============= TRAJECTORY ANALYSIS =============

def parse_dump_file(filename, frame=-1):
    """Parse LAMMPS dump file to extract atomic data.

    Args:
        filename: Path to LAMMPS dump file
        frame: Frame index to read (-1 for last frame, 'all' for all frames)

    Returns:
        dict with keys:
            - timestep: simulation timestep
            - natoms: number of atoms
            - box: [[xlo, xhi], [ylo, yhi], [zlo, zhi]]
            - atoms: numpy array with columns as in dump file
            - columns: list of column names

    For frame='all', returns list of such dicts.
    """
    frames = []
    current_frame = None

    with open(filename, 'r') as f:
        line = f.readline()
        while line:
            if 'ITEM: TIMESTEP' in line:
                if current_frame is not None:
                    frames.append(current_frame)
                current_frame = {'atoms': []}
                current_frame['timestep'] = int(f.readline().strip())

            elif 'ITEM: NUMBER OF ATOMS' in line:
                current_frame['natoms'] = int(f.readline().strip())

            elif 'ITEM: BOX BOUNDS' in line:
                box = []
                for _ in range(3):
                    bounds = f.readline().split()
                    box.append([float(bounds[0]), float(bounds[1])])
                current_frame['box'] = box

            elif 'ITEM: ATOMS' in line:
                # Parse column names
                columns = line.split()[2:]  # Skip "ITEM: ATOMS"
                current_frame['columns'] = columns

                # Read atom data
                for _ in range(current_frame['natoms']):
                    atom_line = f.readline().split()
                    current_frame['atoms'].append([float(x) if '.' in x or 'e' in x.lower() else int(x)
                                                   for x in atom_line])

            line = f.readline()

    if current_frame is not None:
        frames.append(current_frame)

    # Convert atoms to numpy arrays
    for fr in frames:
        fr['atoms'] = np.array(fr['atoms'])

    if frame == 'all':
        return frames
    elif frame == -1:
        return frames[-1] if frames else None
    else:
        return frames[frame] if 0 <= frame < len(frames) else None


def parse_rdf_file(filename):
    """Parse LAMMPS RDF output (fix ave/time with compute rdf).

    Args:
        filename: Path to RDF output file

    Returns:
        dict with keys:
            - r: radial distance array
            - g_r: g(r) values (may be 2D if multiple pairs)
            - coord: coordination number (running integral)
    """
    data = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    # Format: bin r g(r) coord [g2(r) coord2 ...]
                    row = [float(x) for x in parts[1:]]  # Skip bin number
                    data.append(row)
                except ValueError:
                    continue

    data = np.array(data)
    if len(data) == 0:
        return {'r': np.array([]), 'g_r': np.array([]), 'coord': np.array([])}

    return {
        'r': data[:, 0],
        'g_r': data[:, 1],
        'coord': data[:, 2] if data.shape[1] > 2 else None
    }


def parse_msd_file(filename):
    """Parse LAMMPS MSD output (fix ave/time with compute msd).

    Args:
        filename: Path to MSD output file

    Returns:
        dict with keys:
            - time: time array (timesteps)
            - msd: total MSD values
            - msd_components: [msd_x, msd_y, msd_z] if available
    """
    data = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    row = [float(x) for x in parts]
                    data.append(row)
                except ValueError:
                    continue

    data = np.array(data)
    if len(data) == 0:
        return {'time': np.array([]), 'msd': np.array([]), 'msd_components': None}

    result = {
        'time': data[:, 0],
        'msd': data[:, -1]  # Total MSD is usually last column
    }

    # If we have component data (timestep, msd_x, msd_y, msd_z, msd_total)
    if data.shape[1] >= 5:
        result['msd_components'] = data[:, 1:4]

    return result


def compute_diffusion_coefficient(msd_data, timestep, dimensions=3, fit_fraction=0.5):
    """Compute diffusion coefficient from MSD using Einstein relation.

    D = lim(t→∞) MSD / (2 * d * t)

    where d is the number of dimensions.

    Args:
        msd_data: MSD data dict from parse_msd_file() or array [time, msd]
        timestep: Simulation timestep (time units)
        dimensions: Number of dimensions for diffusion (default: 3)
        fit_fraction: Fraction of data to use for linear fit (default: 0.5, uses latter half)
                      This avoids the ballistic regime at short times.

    Returns:
        dict with keys:
            - D: diffusion coefficient
            - D_std_err: standard error of D
            - r_squared: R² of linear fit
            - fit_region: (t_start, t_end) used for fitting
    """
    if isinstance(msd_data, dict):
        t = msd_data['time'] * timestep
        msd = msd_data['msd']
    else:
        msd_data = np.array(msd_data)
        t = msd_data[:, 0] * timestep
        msd = msd_data[:, 1]

    # Use latter portion for linear fit (avoid ballistic regime)
    start_idx = int(len(t) * (1 - fit_fraction))
    t_fit = t[start_idx:]
    msd_fit = msd[start_idx:]

    # Linear fit: MSD = 2*d*D*t + c
    slope, intercept, r_value, p_value, std_err = stats.linregress(t_fit, msd_fit)

    D = slope / (2 * dimensions)
    D_std_err = std_err / (2 * dimensions)

    return {
        'D': D,
        'D_std_err': D_std_err,
        'r_squared': r_value ** 2,
        'fit_region': (t_fit[0], t_fit[-1])
    }


# ============= STATISTICAL ANALYSIS =============

def block_average(data, num_blocks=10):
    """Compute block-averaged mean and standard error.

    Block averaging accounts for time correlations in MD data,
    providing more accurate error estimates than simple standard error.

    Reference: Flyvbjerg & Petersen, J. Chem. Phys. 91, 461 (1989)

    Args:
        data: 1D array of time series data
        num_blocks: Number of blocks for averaging

    Returns:
        dict with keys:
            - mean: block-averaged mean
            - std_err: standard error of mean (accounting for correlations)
            - block_means: individual block means
            - block_size: size of each block
    """
    data = np.array(data)
    n = len(data)
    block_size = n // num_blocks

    # Truncate to fit exact number of blocks
    data_truncated = data[:block_size * num_blocks]
    blocks = data_truncated.reshape(num_blocks, block_size)

    block_means = blocks.mean(axis=1)
    overall_mean = block_means.mean()

    # Standard error of the mean from block variance
    std_err = np.std(block_means, ddof=1) / np.sqrt(num_blocks)

    return {
        'mean': overall_mean,
        'std_err': std_err,
        'block_means': block_means,
        'block_size': block_size
    }


def autocorrelation_function(data, max_lag=None):
    """Compute normalized autocorrelation function.

    ACF(t) = <δA(0) δA(t)> / <δA²>

    where δA = A - <A>

    Args:
        data: 1D array of time series data
        max_lag: Maximum lag to compute (default: len(data)//4)

    Returns:
        dict with keys:
            - lag: lag indices
            - acf: normalized autocorrelation values
            - correlation_time: integrated correlation time (τ)
    """
    data = np.array(data)
    data = data - data.mean()
    n = len(data)

    if max_lag is None:
        max_lag = n // 4

    # Compute ACF using FFT for efficiency
    fft_data = np.fft.fft(data, n=2*n)
    acf_full = np.fft.ifft(fft_data * np.conj(fft_data)).real[:n]

    # Normalize
    acf = acf_full / acf_full[0]
    acf = acf[:max_lag]

    # Integrated correlation time (truncate when ACF crosses zero or becomes noisy)
    # Use the "first zero crossing" or "first minimum" heuristic
    zero_crossings = np.where(acf[1:] <= 0)[0]
    if len(zero_crossings) > 0:
        cutoff = zero_crossings[0] + 1
    else:
        cutoff = len(acf)

    correlation_time = 1 + 2 * np.sum(acf[1:cutoff])

    return {
        'lag': np.arange(max_lag),
        'acf': acf,
        'correlation_time': correlation_time,
        'effective_samples': n / correlation_time if correlation_time > 0 else n
    }


# ============= MECHANICAL PROPERTIES =============

def parse_stress_strain(log_file, strain_component='Lz', stress_component='Pzz'):
    """Extract stress-strain data from LAMMPS deformation simulation.

    Args:
        log_file: Path to LAMMPS log file
        strain_component: Length component for strain ('Lx', 'Ly', 'Lz')
        stress_component: Stress component ('Pxx', 'Pyy', 'Pzz', 'Pxy', 'Pxz', 'Pyz')

    Returns:
        dict with keys:
            - strain: engineering strain array
            - stress: stress array (converted to positive for tension)
            - L0: initial length
    """
    data = parse_log_file(log_file, columns=[strain_component, stress_component])

    if strain_component not in data or stress_component not in data:
        raise ValueError(f"Could not find {strain_component} or {stress_component} in log file")

    L = data[strain_component]
    stress = data[stress_component]

    L0 = L[0]
    strain = (L - L0) / L0

    # Convert pressure to stress (LAMMPS outputs negative pressure for tension)
    stress = -stress

    return {
        'strain': strain,
        'stress': stress,
        'L0': L0
    }


def compute_elastic_modulus(stress_strain_data, strain_range=(0, 0.02)):
    """Compute Young's modulus from stress-strain curve.

    Args:
        stress_strain_data: dict from parse_stress_strain()
        strain_range: (min, max) strain range for linear fit

    Returns:
        dict with keys:
            - E: Young's modulus (same units as stress)
            - E_std_err: standard error
            - r_squared: R² of linear fit
            - yield_stress: estimated yield stress (0.2% offset if detectable)
    """
    strain = stress_strain_data['strain']
    stress = stress_strain_data['stress']

    # Select linear region
    mask = (strain >= strain_range[0]) & (strain <= strain_range[1])
    if mask.sum() < 3:
        raise ValueError(f"Not enough points in strain range {strain_range}")

    slope, intercept, r_value, p_value, std_err = stats.linregress(strain[mask], stress[mask])

    result = {
        'E': slope,
        'E_std_err': std_err,
        'r_squared': r_value ** 2
    }

    # Attempt to find yield stress using 0.2% offset method
    try:
        offset_line = slope * (strain - 0.002) + intercept
        # Find intersection with stress-strain curve beyond elastic region
        diff = stress - offset_line
        beyond_elastic = strain > strain_range[1]
        if beyond_elastic.any() and (diff[beyond_elastic] < 0).any():
            yield_idx = np.where(beyond_elastic & (diff < 0))[0][0]
            result['yield_stress'] = stress[yield_idx]
            result['yield_strain'] = strain[yield_idx]
    except (IndexError, ValueError):
        pass

    return result


def compute_surface_tension(log_file, box_normal='z'):
    """Compute surface tension from pressure tensor anisotropy.

    γ = (L_n/2) * (<P_nn> - 0.5*(<P_tt1> + <P_tt2>))

    For a slab geometry with two interfaces.

    Args:
        log_file: Path to LAMMPS log file with pressure tensor components
        box_normal: Direction normal to interface ('x', 'y', or 'z')

    Returns:
        dict with keys:
            - gamma: surface tension
            - gamma_std_err: standard error (from block averaging)
            - P_normal: mean normal pressure
            - P_tangential: mean tangential pressure
    """
    # Map box_normal to pressure components
    component_map = {
        'x': ('Pxx', 'Pyy', 'Pzz', 'Lx'),
        'y': ('Pyy', 'Pxx', 'Pzz', 'Ly'),
        'z': ('Pzz', 'Pxx', 'Pyy', 'Lz')
    }

    P_nn, P_t1, P_t2, L_comp = component_map[box_normal.lower()]
    data = parse_log_file(log_file, columns=[P_nn, P_t1, P_t2, L_comp])

    if P_nn not in data:
        raise ValueError(f"Could not find pressure components in log file")

    P_normal = data[P_nn]
    P_tangential = 0.5 * (data[P_t1] + data[P_t2])
    L_n = data[L_comp]

    # Surface tension (factor of 2 for two interfaces)
    gamma_timeseries = (L_n / 2) * (P_normal - P_tangential)

    # Use block averaging for error estimation
    block_result = block_average(gamma_timeseries)

    return {
        'gamma': block_result['mean'],
        'gamma_std_err': block_result['std_err'],
        'P_normal': P_normal.mean(),
        'P_tangential': P_tangential.mean(),
        'L_normal': L_n.mean()
    }


def parse_density_profile(filename):
    """Parse LAMMPS density profile (fix ave/chunk with density/number or density/mass).

    Args:
        filename: Path to density profile file

    Returns:
        dict with keys:
            - coord: spatial coordinate array
            - density: density values
            - count: atom counts per bin (if available)
    """
    data = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    # Format: chunk coord Ncount density
                    chunk = int(parts[0])
                    coord = float(parts[1])
                    count = float(parts[2])
                    density = float(parts[3]) if len(parts) > 3 else count
                    data.append((coord, density, count))
                except (ValueError, IndexError):
                    continue

    data = np.array(data)
    if len(data) == 0:
        return {'coord': np.array([]), 'density': np.array([]), 'count': np.array([])}

    return {
        'coord': data[:, 0],
        'density': data[:, 1],
        'count': data[:, 2]
    }


def parse_gyration_file(filename):
    """Parse LAMMPS gyration output (fix ave/time with compute gyration).

    Args:
        filename: Path to gyration output file

    Returns:
        dict with keys:
            - time: timestep array
            - Rg: radius of gyration
            - Rg_components: [Rgxx, Rgyy, Rgzz] eigenvalues if available
    """
    data = []
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    row = [float(x) for x in parts]
                    data.append(row)
                except ValueError:
                    continue

    data = np.array(data)
    if len(data) == 0:
        return {'time': np.array([]), 'Rg': np.array([]), 'Rg_components': None}

    result = {
        'time': data[:, 0],
        'Rg': data[:, 1]
    }

    # If we have component data (Rg² eigenvalues)
    if data.shape[1] >= 5:
        result['Rg_components'] = np.sqrt(data[:, 2:5])  # Convert Rg² to Rg

    return result


# ============= ENERGY ANALYSIS =============

def analyze_energy_drift(energy_file):
    """Analyze energy drift from LAMMPS output (out.E* files).

    Monitors energy conservation to validate simulation quality.

    Args:
        energy_file: Path to energy file (fix ave/time output)

    Returns:
        dict with keys:
            - drift_rate: energy change per timestep
            - relative_drift_percent: total drift as percentage of mean energy
            - initial_energy, final_energy, mean_energy, energy_std
    """
    data = []
    with open(energy_file, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    timestep = int(parts[0])
                    energy = float(parts[1])
                    data.append((timestep, energy))
                except (ValueError, IndexError):
                    continue

    data = np.array(data)
    t, E = data[:, 0], data[:, 1]

    # Compute drift rate via linear regression
    slope, intercept, r_value, _, _ = stats.linregress(t, E)
    drift_rate = slope
    relative_drift = abs(slope * (t[-1] - t[0])) / abs(E.mean()) * 100 if E.mean() != 0 else 0

    return {
        'drift_rate': drift_rate,
        'relative_drift_percent': relative_drift,
        'initial_energy': E[0],
        'final_energy': E[-1],
        'mean_energy': E.mean(),
        'energy_std': E.std()
    }


def parse_log_file(log_file, columns=None):
    """Parse thermodynamic data from LAMMPS log file.

    Args:
        log_file: Path to LAMMPS log file
        columns: List of column names to extract (default: all)

    Returns:
        dict mapping column names to numpy arrays of values
    """
    data = {}
    header = None
    in_thermo = False

    with open(log_file, 'r') as f:
        for line in f:
            line = line.strip()

            # Detect thermo header line
            if line.startswith('Step ') or (line.startswith('Step') and 'Temp' in line):
                header = line.split()
                for col in header:
                    if col not in data:
                        data[col] = []
                in_thermo = True
                continue

            # End of thermo block
            if in_thermo and (line.startswith('Loop') or line.startswith('ERROR') or not line):
                in_thermo = False
                continue

            # Parse thermo data
            if in_thermo and header:
                parts = line.split()
                if len(parts) == len(header):
                    try:
                        for i, col in enumerate(header):
                            data[col].append(float(parts[i]))
                    except ValueError:
                        in_thermo = False

    # Convert to numpy arrays
    for col in data:
        data[col] = np.array(data[col])

    # Filter columns if specified
    if columns:
        data = {k: v for k, v in data.items() if k in columns}

    return data


# ============= CONVENIENCE FUNCTIONS =============

def quick_setup(input_dir, output_dir, work_dir=None, copy_input=True):
    """Quick setup for typical LAMMPS workflow.

    Initializes logging, creates directories, and optionally copies input files.

    Args:
        input_dir: Path to the input directory (required).
        output_dir: Path to the output directory (required).
        work_dir: Path to the working directory. If None, works directly in output_dir.
        copy_input: If True and work_dir is set, copy input files to work_dir.

    Returns:
        List of copied input files (empty if copy_input is False or work_dir is None)
    """
    setup_logging()
    setup_directories(input_dir=input_dir, output_dir=output_dir,
                      work_dir=work_dir, copy_input=copy_input)
    return []


def quick_finish():
    """Quick finish for typical LAMMPS workflow.

    Copies output files to output directory.

    Returns:
        List of copied output files
    """
    return copy_outputs()


class NumpyJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles NumPy types.

    NumPy types (np.float64, np.int64, np.bool_, np.ndarray) are not
    natively JSON serializable. This encoder converts them to Python types.
    Compatible with NumPy 1.x and 2.x.
    """

    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.complexfloating):
            return {'real': float(obj.real), 'imag': float(obj.imag)}
        return super().default(obj)


def save_final_results(results, output_files=None, file_descriptions=None, status="completed"):
    """Save final results to OUTPUT_DIR/final_results.json for workflow consistency.

    This function creates a standardized final_results.json file that other agents
    and workflow systems can consume.

    The output JSON has the structure:
        {"status": "...", "summary": <results>, "output_files": {...}, ...}

    IMPORTANT: The ``results`` dict is stored under the ``'summary'`` key.
    Downstream agents reading this file must access ``data['summary']`` to
    retrieve the actual results, NOT the top-level keys.

    Args:
        results: dict containing the main analysis results (e.g., thermal conductivity,
                diffusion coefficients, simulation metrics). This becomes the "summary" section.
                Values can include NumPy types - they will be automatically converted.
        output_files: dict mapping descriptive names to file paths for generated outputs
                     (e.g., {"temperature_profile": "/output/temp_profile.png"})
        file_descriptions: dict mapping the same keys to human-readable descriptions
        status: workflow status string (default: "completed")

    Returns:
        Path to the saved final_results.json file

    Example:
        >>> results = {
        ...     "thermal_conductivity": 0.075,
        ...     "thermal_conductivity_std_err": 0.002,
        ...     "r_squared": 0.987,
        ...     "method": "NEMD-eHEX"
        ... }
        >>> output_files = {
        ...     "temperature_profile": "/output/temperature_profile.png",
        ...     "simulation_log": "/output/simulation.log"
        ... }
        >>> file_descriptions = {
        ...     "temperature_profile": "Temperature gradient plot from NEMD simulation",
        ...     "simulation_log": "Complete LAMMPS simulation log"
        ... }
        >>> save_final_results(results, output_files, file_descriptions)
    """
    final_data = {
        "status": status,
        "summary": results
    }

    if output_files:
        final_data["output_files"] = output_files

    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions

    output_path = os.path.join(OUTPUT_DIR, "final_results.json")

    with open(output_path, 'w') as f:
        json.dump(final_data, f, indent=2, cls=NumpyJSONEncoder)

    logging.info(f"Saved final results to {output_path}")
    return output_path


# ============= VISUALIZATION =============

def plot_temperature_profile(T_profile, output_file='temperature_profile.png', title=None):
    """Plot temperature profile from NEMD simulation.

    Args:
        T_profile: Temperature profile from parse_temperature_profile()
        output_file: Output filename for plot
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    z = T_profile[:, 0]
    T = T_profile[:, 1]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(z, T, 'bo-', markersize=4, linewidth=1)
    ax.set_xlabel('z coordinate')
    ax.set_ylabel('Temperature')
    ax.set_title(title or 'NEMD Temperature Profile')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved temperature profile plot: {output_file}")
    return output_file


def plot_rdf(rdf_data, output_file='rdf.png', title=None):
    """Plot radial distribution function g(r).

    Args:
        rdf_data: RDF data from parse_rdf_file()
        output_file: Output filename for plot
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(rdf_data['r'], rdf_data['g_r'], 'b-', linewidth=1.5)
    ax.axhline(y=1, color='k', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.set_xlabel('r (distance)')
    ax.set_ylabel('g(r)')
    ax.set_title(title or 'Radial Distribution Function')
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved RDF plot: {output_file}")
    return output_file


def plot_msd(msd_data, timestep=1.0, output_file='msd.png', title=None, fit_result=None):
    """Plot mean square displacement with optional diffusion fit.

    Args:
        msd_data: MSD data from parse_msd_file()
        timestep: Simulation timestep for time axis
        output_file: Output filename for plot
        title: Plot title (optional)
        fit_result: Optional diffusion fit result from compute_diffusion_coefficient()

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    t = msd_data['time'] * timestep
    msd = msd_data['msd']

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(t, msd, 'b-', linewidth=1.5, label='MSD')

    if fit_result is not None:
        # Plot fit line
        t_fit = np.linspace(fit_result['fit_region'][0], fit_result['fit_region'][1], 100)
        msd_fit = 6 * fit_result['D'] * t_fit
        ax.plot(t_fit, msd_fit, 'r--', linewidth=2,
                label=f'Fit: D = {fit_result["D"]:.4e}')

    ax.set_xlabel('Time')
    ax.set_ylabel('MSD')
    ax.set_title(title or 'Mean Square Displacement')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved MSD plot: {output_file}")
    return output_file


def plot_stress_strain(stress_strain_data, output_file='stress_strain.png', title=None, modulus_result=None):
    """Plot stress-strain curve with optional modulus fit.

    Args:
        stress_strain_data: Data from parse_stress_strain()
        output_file: Output filename for plot
        title: Plot title (optional)
        modulus_result: Optional result from compute_elastic_modulus()

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    strain = stress_strain_data['strain']
    stress = stress_strain_data['stress']

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(strain * 100, stress, 'b-', linewidth=1.5, label='Stress-strain')

    if modulus_result is not None:
        # Plot linear fit in elastic region
        strain_fit = np.linspace(0, 0.02, 100)
        stress_fit = modulus_result['E'] * strain_fit
        ax.plot(strain_fit * 100, stress_fit, 'r--', linewidth=2,
                label=f'E = {modulus_result["E"]:.2f}')

        if 'yield_stress' in modulus_result:
            ax.axhline(y=modulus_result['yield_stress'], color='g', linestyle=':',
                       label=f'Yield = {modulus_result["yield_stress"]:.2f}')

    ax.set_xlabel('Strain (%)')
    ax.set_ylabel('Stress')
    ax.set_title(title or 'Stress-Strain Curve')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved stress-strain plot: {output_file}")
    return output_file


def plot_acf(acf_data, output_file='acf.png', title=None):
    """Plot autocorrelation function.

    Args:
        acf_data: ACF data from autocorrelation_function()
        output_file: Output filename for plot
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(acf_data['lag'], acf_data['acf'], 'b-', linewidth=1.5)
    ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
    ax.axhline(y=1/np.e, color='r', linestyle='--', linewidth=0.5, alpha=0.5,
               label=f'1/e (τ ≈ {acf_data["correlation_time"]:.1f})')

    ax.set_xlabel('Lag')
    ax.set_ylabel('ACF')
    ax.set_title(title or 'Autocorrelation Function')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved ACF plot: {output_file}")
    return output_file


# Module initialization
if __name__ == "__main__":
    print("LAMMPS Utilities Library")
    print(f"Available cores: {NUM_CORES}")
    print("\nAvailable functions:")
    print("  Setup: quick_setup, quick_finish, copy_input_files, copy_outputs")
    print("  Execution: run_lammps, run_command")
    print("  Parametric: modify_lammps_variable, create_parameter_sweep_inputs")
    print("  Thermal: parse_temperature_profile, compute_thermal_conductivity_nemd")
    print("  Green-Kubo: parse_hfacf, compute_thermal_conductivity_gk")
    print("  Trajectory: parse_dump_file, parse_rdf_file, parse_msd_file")
    print("  Transport: compute_diffusion_coefficient")
    print("  Statistics: block_average, autocorrelation_function")
    print("  Mechanical: parse_stress_strain, compute_elastic_modulus")
    print("  Interfaces: compute_surface_tension, parse_density_profile")
    print("  Polymers: parse_gyration_file")
    print("  Plotting: plot_temperature_profile, plot_rdf, plot_msd, plot_stress_strain, plot_acf")
