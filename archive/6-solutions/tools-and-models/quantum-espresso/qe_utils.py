"""
Quantum ESPRESSO Utilities Library

Helper functions for running QE calculations and analyzing output.
This module is pre-installed in the QE container for use by generated scripts.

Usage:
    from qe_utils import (
        run_qe_adaptive, parse_qe_output, parse_phonon_output,
        quick_setup, quick_finish, save_final_results
    )
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

# ============= CONFIGURATION =============

# Detect available CPU cores
NUM_CORES = os.cpu_count() or multiprocessing.cpu_count() or 1

# Standard directories — MUST be set via quick_setup() or setup_directories() before use.
# No defaults: the agent-generated code must provide paths from dataHandlingContext.
INPUT_DIR: str = ''
WORK_DIR: str = ''
OUTPUT_DIR: str = ''
_DIRS_CONFIGURED = False
PSEUDO_DIR = os.environ.get('PSEUDO_DIR', '/opt/apps/qe/7.3/pseudo')

# Rydberg to eV conversion factor
RY_TO_EV = 13.605693


def _require_dirs():
    """Raise if setup_directories() has not been called."""
    if not _DIRS_CONFIGURED:
        raise RuntimeError(
            "Directories not configured. Call quick_setup(input_dir=..., output_dir=...) "
            "or setup_directories(input_dir=..., output_dir=...) before using any utility functions."
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
        copy_input: If True and work_dir is set, copy input files to work_dir.
    """
    global INPUT_DIR, WORK_DIR, OUTPUT_DIR, _DIRS_CONFIGURED
    INPUT_DIR = input_dir
    OUTPUT_DIR = output_dir
    WORK_DIR = work_dir if work_dir is not None else '/app/workdir'
    _DIRS_CONFIGURED = True
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(WORK_DIR, 'tmp'), exist_ok=True)
    os.chdir(WORK_DIR)
    logging.info(f"Input directory: {INPUT_DIR}")
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Output directory: {OUTPUT_DIR}")
    logging.info(f"Detected {NUM_CORES} CPU cores available")
    logging.info(f"Pseudopotential directory: {PSEUDO_DIR}")
    if copy_input:
        copy_input_files()


def copy_input_files(patterns=None):
    """Copy input files from input directory to working directory.

    Args:
        patterns: List of glob patterns to copy. Defaults to common QE patterns.

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        logging.info("Input directory is working directory; skipping copy_input_files")
        return []
    if patterns is None:
        patterns = ['*.cif', '*.xyz', '*.in', '*.UPF', '*.upf', 'POSCAR', '*.vasp', '*.pdb']

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
        patterns = ['*.out', '*.xml', '*.dat', '*.csv', '*.png', '*.json', '*.cif', '*.xyz']

    copied = []
    for pattern in patterns:
        for src_file in glob.glob(os.path.join(WORK_DIR, pattern)):
            dst_file = os.path.join(OUTPUT_DIR, os.path.basename(src_file))
            shutil.copy(src_file, dst_file)
            logging.info(f"Output: {os.path.basename(src_file)}")
            copied.append(dst_file)
    return copied


# ============= COMMAND EXECUTION =============

def run_command(command, cwd=None, stream=True):
    """Execute command with real-time output streaming.

    Args:
        command: Shell command to execute
        cwd: Working directory (optional)
        stream: If True, stream output line-by-line; if False, capture all at once

    Returns:
        subprocess.CompletedProcess result
    """
    logging.info(f"Running: {command}")
    start_time = time.time()

    if not stream:
        # Non-streaming mode for simple commands
        result = subprocess.run(
            command, shell=True, check=True,
            capture_output=True, text=True, cwd=cwd
        )
        elapsed = time.time() - start_time
        logging.info(f"Completed in {elapsed:.2f}s")
        if result.stdout:
            logging.info(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        return result

    # Streaming mode - show output line by line in real-time
    process = subprocess.Popen(
        command, shell=True, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1  # Line buffered
    )

    output_lines = []
    try:
        for line in process.stdout:
            line = line.rstrip('\n')
            print(line)  # Real-time output to stdout
            sys.stdout.flush()
            output_lines.append(line)
    finally:
        process.stdout.close()
        return_code = process.wait()

    elapsed = time.time() - start_time
    logging.info(f"Completed in {elapsed:.2f}s")

    if return_code != 0:
        error_msg = f"Command failed with exit code {return_code}"
        logging.error(error_msg)
        raise subprocess.CalledProcessError(return_code, command, '\n'.join(output_lines))

    return subprocess.CompletedProcess(command, return_code, '\n'.join(output_lines), '')


def run_qe_adaptive(executable, input_file, output_file, nprocs=None):
    """Run QE executable with automatic parallelization handling.

    Uses tee to both save output to file AND stream to stdout for real-time display.
    QE writes progress to stderr, so we merge stderr into stdout with 2>&1.

    Args:
        executable: QE executable name (pw.x, ph.x, pp.x, dos.x, etc.)
        input_file: Input file path
        output_file: Output file path
        nprocs: Number of MPI processes (None = auto-detect)

    Returns:
        True if successful
    """
    # Detect available CPUs
    if nprocs is None:
        try:
            nprocs = len(os.sched_getaffinity(0))
        except:
            nprocs = NUM_CORES
        nprocs = min(nprocs, 16)  # Cap at 16 for small calculations

    logging.info(f"Running {executable} with {nprocs} processes")

    # Try parallel execution first
    # Use tee to both save output AND stream to stdout (QE writes progress to stderr)
    # MPI flags for container compatibility:
    # --allow-run-as-root: Required for container runtimes
    # --oversubscribe: Allow more processes than detected slots (common in containers)
    # --bind-to none: CRITICAL - disable CPU binding which hangs in containers
    # --mca btl ^vader: Explicitly exclude vader BTL (shared memory issues in containers)
    if nprocs > 1:
        cmd = f"mpirun --allow-run-as-root --oversubscribe --bind-to none --mca btl ^vader -np {nprocs} {executable} < {input_file} 2>&1 | tee {output_file}"
        try:
            run_command(cmd)
            return True
        except subprocess.CalledProcessError as e:
            logging.warning(f"Parallel execution failed, trying serial...")

    # Fall back to serial execution
    cmd = f"{executable} < {input_file} 2>&1 | tee {output_file}"
    run_command(cmd)
    return True


# ============= PSEUDOPOTENTIAL HANDLING =============

def check_pseudopotentials(elements, pseudo_dir=None):
    """Verify pseudopotentials exist for all elements.

    Args:
        elements: List of element symbols (e.g., ['Si', 'O']) or full filenames
                  (e.g., ['Si.pbe-n-rrkjus_psl.1.0.0.UPF'])
        pseudo_dir: Directory to search (default: PSEUDO_DIR)

    Returns:
        dict mapping element -> pseudopotential filename

    Raises:
        FileNotFoundError: If pseudopotential not found for any element
    """
    if pseudo_dir is None:
        pseudo_dir = PSEUDO_DIR

    missing = []
    found = {}

    available_pseudos = glob.glob(os.path.join(pseudo_dir, '*.UPF')) + \
                       glob.glob(os.path.join(pseudo_dir, '*.upf'))
    available_basenames = [os.path.basename(p) for p in available_pseudos]
    available_basenames_lower = [b.lower() for b in available_basenames]

    for element in elements:
        element_found = False

        # If element looks like a filename (contains .UPF or .upf), extract element symbol
        if '.upf' in element.lower():
            # Extract element from filename: "Si.pbe-..." -> "Si", "si_pbe..." -> "si"
            if '.' in element and not element.startswith('.'):
                element_symbol = element.split('.')[0]
            elif '_' in element:
                element_symbol = element.split('_')[0]
            else:
                element_symbol = element

            # Also check if the exact filename exists
            if element in available_basenames:
                found[element_symbol] = element
                element_found = True
                logging.info(f"Found exact pseudopotential: {element}")
            elif element.lower() in available_basenames_lower:
                # Case-insensitive match for exact filename
                idx = available_basenames_lower.index(element.lower())
                found[element_symbol] = available_basenames[idx]
                element_found = True
                logging.info(f"Found pseudopotential (case-insensitive): {available_basenames[idx]}")
        else:
            element_symbol = element

        # If not found yet, search by element symbol
        if not element_found:
            for i, basename in enumerate(available_basenames):
                basename_lower = available_basenames_lower[i]
                element_lower = element_symbol.lower()
                # Match patterns like "Si.pbe-...", "Si_pbe...", "si.pbe-...", "si_pbe..."
                if (basename_lower.startswith(element_lower + '.') or
                    basename_lower.startswith(element_lower + '_')):
                    found[element_symbol] = basename
                    element_found = True
                    logging.info(f"Found pseudopotential for {element_symbol}: {basename}")
                    break

        if not element_found:
            missing.append(element)

    if missing:
        avail_list = available_basenames[:10]
        raise FileNotFoundError(
            f"Missing pseudopotentials for: {missing}. "
            f"Available (first 10): {avail_list}"
        )

    return found


def list_pseudopotentials(pseudo_dir=None):
    """List all available pseudopotentials.

    Args:
        pseudo_dir: Directory to search (default: PSEUDO_DIR)

    Returns:
        List of pseudopotential filenames
    """
    if pseudo_dir is None:
        pseudo_dir = PSEUDO_DIR

    pseudos = glob.glob(os.path.join(pseudo_dir, '*.UPF')) + \
              glob.glob(os.path.join(pseudo_dir, '*.upf'))
    return sorted([os.path.basename(p) for p in pseudos])


# ============= OUTPUT PARSING =============

def parse_qe_output(output_file):
    """Parse QE output file for key results.

    Works for SCF, relax, vc-relax, nscf, and bands calculations.

    Args:
        output_file: Path to QE output file (*.out)

    Returns:
        dict with keys:
            - converged: bool
            - total_energy_Ry: float (Rydberg)
            - total_energy_eV: float (electron-volts)
            - fermi_energy_eV: float (for metals)
            - highest_occupied_eV: float (for insulators/semiconductors)
            - lowest_unoccupied_eV: float (if available)
            - band_gap_eV: float (if semiconductor)
            - total_force: float (Ry/Bohr)
            - pressure_kbar: float
            - n_scf_iterations: int
            - wall_time_seconds: float
            - system_type: 'metal' or 'semiconductor/insulator'
            - calculation_type: 'scf', 'nscf', 'bands', 'relax', etc.
    """
    results = {
        'converged': False,
        'total_energy_Ry': None,
        'total_energy_eV': None,
        'fermi_energy_eV': None,
        'highest_occupied_eV': None,
        'lowest_unoccupied_eV': None,
        'band_gap_eV': None,
        'total_force': None,
        'pressure_kbar': None,
        'n_scf_iterations': 0,
        'wall_time_seconds': None,
        'system_type': None,
        'calculation_type': None
    }

    if not os.path.exists(output_file):
        logging.warning(f"Output file not found: {output_file}")
        return results

    # Track if this is an NSCF/bands calculation (no SCF convergence needed)
    is_nscf_or_bands = False
    job_done = False

    with open(output_file, 'r') as f:
        for line in f:
            # Detect NSCF or bands calculation (no SCF convergence needed)
            if 'Band Structure Calculation' in line:
                is_nscf_or_bands = True
                results['calculation_type'] = 'nscf/bands'
            elif "calculation='nscf'" in line or 'calculation = "nscf"' in line.lower():
                is_nscf_or_bands = True
                results['calculation_type'] = 'nscf'
            elif "calculation='bands'" in line or 'calculation = "bands"' in line.lower():
                is_nscf_or_bands = True
                results['calculation_type'] = 'bands'

            # Check for successful job completion
            if 'JOB DONE' in line:
                job_done = True
            # Total energy (final value)
            if '!    total energy' in line:
                results['total_energy_Ry'] = float(line.split()[-2])
                results['total_energy_eV'] = results['total_energy_Ry'] * RY_TO_EV

            # SCF convergence
            elif 'convergence has been achieved' in line:
                results['converged'] = True
                try:
                    results['n_scf_iterations'] = int(line.split()[5])
                except (IndexError, ValueError):
                    pass

            # Fermi energy (metals)
            elif 'the Fermi energy is' in line:
                results['fermi_energy_eV'] = float(line.split()[-2])
                results['system_type'] = 'metal'

            # Highest occupied level (insulators/semiconductors without unoccupied)
            elif 'highest occupied level' in line:
                results['highest_occupied_eV'] = float(line.split()[-1])
                results['system_type'] = 'semiconductor/insulator'

            # Band edges (semiconductors/insulators with unoccupied states)
            elif 'highest occupied, lowest unoccupied' in line:
                try:
                    parts = line.split(':')[1].split()
                    results['highest_occupied_eV'] = float(parts[0])
                    results['lowest_unoccupied_eV'] = float(parts[1])
                    results['band_gap_eV'] = results['lowest_unoccupied_eV'] - results['highest_occupied_eV']
                    results['system_type'] = 'semiconductor/insulator'
                except (IndexError, ValueError):
                    pass

            # Total force
            elif 'Total force' in line:
                try:
                    results['total_force'] = float(line.split()[3])
                except (IndexError, ValueError):
                    pass

            # Pressure
            elif 'P=' in line:
                try:
                    parts = line.split('P=')
                    if len(parts) > 1:
                        results['pressure_kbar'] = float(parts[1].split()[0])
                except (IndexError, ValueError):
                    pass

            # Wall time
            elif 'PWSCF' in line and 'WALL' in line:
                try:
                    # Parse format like "PWSCF        :     25.05s CPU     26.32s WALL"
                    wall_match = re.search(r'(\d+\.?\d*)\s*s\s+WALL', line)
                    if wall_match:
                        results['wall_time_seconds'] = float(wall_match.group(1))
                except (ValueError, AttributeError):
                    pass

    # For NSCF/bands calculations, convergence is determined by JOB DONE
    # (they don't have SCF iterations to converge)
    if is_nscf_or_bands and job_done and not results['converged']:
        results['converged'] = True
        logging.info(f"NSCF/bands calculation completed successfully (JOB DONE found)")

    return results


def parse_scf_convergence(output_file):
    """Parse SCF convergence history from QE output.

    Useful for plotting convergence or diagnosing SCF problems.

    Args:
        output_file: Path to QE output file

    Returns:
        dict with keys:
            - iterations: list of iteration numbers
            - energies: list of total energies (Ry)
            - accuracies: list of estimated scf accuracies (Ry)
    """
    iterations = []
    energies = []
    accuracies = []

    if not os.path.exists(output_file):
        return {'iterations': [], 'energies': [], 'accuracies': []}

    with open(output_file, 'r') as f:
        current_iter = None
        for line in f:
            # Match iteration line
            if 'iteration #' in line:
                try:
                    current_iter = int(line.split('#')[1].split()[0])
                except (IndexError, ValueError):
                    pass

            # Match total energy during SCF
            elif 'total energy' in line and '!' not in line and current_iter is not None:
                try:
                    energy = float(line.split('=')[1].split()[0])
                    iterations.append(current_iter)
                    energies.append(energy)
                except (IndexError, ValueError):
                    pass

            # Match estimated scf accuracy
            elif 'estimated scf accuracy' in line:
                try:
                    accuracy = float(line.split('<')[1].split()[0])
                    accuracies.append(accuracy)
                except (IndexError, ValueError):
                    pass

    return {
        'iterations': iterations,
        'energies': energies,
        'accuracies': accuracies
    }


def parse_bands(bands_file):
    """Parse band structure data from bands.x output.

    Args:
        bands_file: Path to bands.dat or bands.gnu file

    Returns:
        dict with keys:
            - kpoints: array of k-point distances
            - bands: 2D array of band energies (n_kpoints x n_bands)
            - n_bands: number of bands
            - n_kpoints: number of k-points
    """
    kpoints = []
    bands = []

    with open(bands_file, 'r') as f:
        current_bands = []
        for line in f:
            line = line.strip()
            if not line:
                if current_bands:
                    bands.append(current_bands)
                    current_bands = []
                continue

            parts = line.split()
            if len(parts) == 2:
                # k-point line: k_distance, energy
                try:
                    k = float(parts[0])
                    e = float(parts[1])
                    if len(kpoints) < len(bands) + 1:
                        kpoints.append(k)
                    current_bands.append(e)
                except ValueError:
                    pass

    if current_bands:
        bands.append(current_bands)

    bands = np.array(bands).T if bands else np.array([])

    return {
        'kpoints': np.array(kpoints),
        'bands': bands,
        'n_bands': bands.shape[0] if len(bands.shape) > 1 else 0,
        'n_kpoints': len(kpoints)
    }


def parse_phonon_output(output_file):
    """Parse phonon frequencies from ph.x output.

    Works for both Gamma-point calculations and q-point dispersions.

    Args:
        output_file: Path to ph.x output file (*.out)

    Returns:
        dict with keys:
            - frequencies: list of phonon frequencies (cm^-1)
            - frequencies_THz: list of phonon frequencies (THz)
            - q_point: q-point coordinates (if single q-point)
            - n_modes: number of phonon modes
            - has_imaginary: True if imaginary frequencies present
            - converged: True if calculation converged
    """
    results = {
        'frequencies': [],
        'frequencies_THz': [],
        'q_point': None,
        'n_modes': 0,
        'has_imaginary': False,
        'converged': False
    }

    if not os.path.exists(output_file):
        logging.warning(f"Phonon output file not found: {output_file}")
        return results

    with open(output_file, 'r') as f:
        content = f.read()
        lines = content.split('\n')

    # Check for convergence
    if 'End of self-consistent calculation' in content or 'JOB DONE' in content:
        results['converged'] = True

    # Parse q-point (for single q-point calculations)
    for line in lines:
        if 'Calculation of q' in line or 'q =' in line:
            # Extract q-point coordinates
            match = re.search(r'q\s*=\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)', line)
            if match:
                results['q_point'] = [float(match.group(i)) for i in range(1, 4)]
            break

    # Parse phonon frequencies
    # Format: "     omega( 1 -  1) =      -0.1  [cm-1]   -->      -0.0 [THz]"
    # Or: "     freq (    1) =       0.000000 [THz] =       0.000000 [cm-1]"
    for line in lines:
        # Pattern 1: omega format (older QE versions)
        if 'omega(' in line and 'cm-1' in line:
            match = re.search(r'omega\([^)]+\)\s*=\s*([-\d.]+)\s*\[cm-1\]', line)
            if match:
                freq_cm = float(match.group(1))
                results['frequencies'].append(freq_cm)
                # Convert cm^-1 to THz: 1 cm^-1 = 0.02998 THz
                results['frequencies_THz'].append(freq_cm * 0.02998)
                if freq_cm < -1.0:  # Threshold for imaginary modes
                    results['has_imaginary'] = True

        # Pattern 2: freq format (newer QE versions)
        elif 'freq (' in line and 'THz' in line:
            match = re.search(r'freq\s*\(\s*\d+\)\s*=\s*([-\d.]+)\s*\[THz\]', line)
            if match:
                freq_THz = float(match.group(1))
                results['frequencies_THz'].append(freq_THz)
                # Convert THz to cm^-1
                results['frequencies'].append(freq_THz / 0.02998)
                if freq_THz < -0.03:  # ~1 cm^-1 threshold
                    results['has_imaginary'] = True

    results['n_modes'] = len(results['frequencies'])

    if results['n_modes'] > 0:
        logging.info(f"Parsed {results['n_modes']} phonon modes from {output_file}")
        logging.info(f"Frequency range: {min(results['frequencies']):.1f} to {max(results['frequencies']):.1f} cm^-1")
        if results['has_imaginary']:
            logging.warning("Imaginary frequencies detected - structure may be unstable")
    else:
        logging.warning(f"No phonon frequencies found in {output_file}")

    return results


def parse_dos(dos_file):
    """Parse density of states from dos.x output.

    Args:
        dos_file: Path to DOS output file (*.dos)

    Returns:
        dict with keys:
            - energy: energy array (eV)
            - dos: total DOS array
            - integrated_dos: integrated DOS (if available)
    """
    data = []

    with open(dos_file, 'r') as f:
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
        return {'energy': np.array([]), 'dos': np.array([]), 'integrated_dos': None}

    result = {
        'energy': data[:, 0],
        'dos': data[:, 1]
    }

    if data.shape[1] >= 3:
        result['integrated_dos'] = data[:, 2]

    return result


# ============= STRUCTURE HANDLING =============

def get_elements_from_input(input_file):
    """Extract element symbols from QE input file.

    Parses the ATOMIC_SPECIES section.

    Args:
        input_file: Path to QE input file

    Returns:
        List of element symbols
    """
    elements = []
    in_atomic_species = False

    with open(input_file, 'r') as f:
        for line in f:
            line_stripped = line.strip().upper()

            if line_stripped.startswith('ATOMIC_SPECIES'):
                in_atomic_species = True
                continue

            if in_atomic_species:
                # Check for end of section
                if line_stripped.startswith('ATOMIC_POSITIONS') or \
                   line_stripped.startswith('K_POINTS') or \
                   line_stripped.startswith('CELL_PARAMETERS') or \
                   line_stripped.startswith('&'):
                    break

                # Parse element line: Element mass pseudopotential
                parts = line.split()
                if len(parts) >= 3 and not parts[0].startswith('#'):
                    element = parts[0].capitalize()
                    if element.isalpha():
                        elements.append(element)

    return elements


# ============= RESULTS SAVING =============

class NumpyJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles NumPy types."""

    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def save_final_results(results, output_files=None, file_descriptions=None, status="completed"):
    """Save final results to OUTPUT_DIR/final_results.json.

    Creates a standardized final_results.json file that other agents
    and workflow systems can consume.

    The output JSON has the structure:
        {"status": "...", "summary": <results>, "output_files": {...}, ...}

    IMPORTANT: The ``results`` dict is stored under the ``'summary'`` key.
    Downstream agents reading this file must access ``data['summary']`` to
    retrieve the actual results, NOT the top-level keys.

    Args:
        results: dict containing the main analysis results
        output_files: dict mapping names to file paths
        file_descriptions: dict mapping names to descriptions
        status: workflow status string (default: "completed")

    Returns:
        Path to the saved final_results.json file
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

def plot_scf_convergence(convergence_data, output_file='scf_convergence.png', title=None):
    """Plot SCF convergence history.

    Args:
        convergence_data: dict from parse_scf_convergence()
        output_file: Output filename for plot
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    iterations = convergence_data['iterations']
    energies = convergence_data['energies']

    if not iterations:
        logging.warning("No convergence data to plot")
        return None

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(iterations, energies, 'bo-', markersize=6, linewidth=1.5)
    ax.set_xlabel('SCF Iteration')
    ax.set_ylabel('Total Energy (Ry)')
    ax.set_title(title or 'SCF Convergence')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved convergence plot: {output_file}")
    return output_file


def plot_bands(bands_data, output_file='band_structure.png', title=None,
               fermi_energy=None, energy_range=None):
    """Plot electronic band structure.

    Args:
        bands_data: dict from parse_bands()
        output_file: Output filename for plot
        title: Plot title (optional)
        fermi_energy: Fermi energy to shift bands (optional)
        energy_range: Tuple (min, max) for y-axis (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    kpoints = bands_data['kpoints']
    bands = bands_data['bands']

    if len(kpoints) == 0 or len(bands) == 0:
        logging.warning("No band data to plot")
        return None

    # Shift to Fermi level if provided
    if fermi_energy is not None:
        bands = bands - fermi_energy

    fig, ax = plt.subplots(figsize=(8, 6))

    for i in range(bands.shape[0]):
        ax.plot(kpoints, bands[i], 'b-', linewidth=1)

    if fermi_energy is not None:
        ax.axhline(y=0, color='r', linestyle='--', linewidth=0.5, label='Fermi level')

    ax.set_xlabel('k-path')
    ax.set_ylabel('Energy (eV)')
    ax.set_title(title or 'Electronic Band Structure')

    if energy_range:
        ax.set_ylim(energy_range)

    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved band structure plot: {output_file}")
    return output_file


def plot_dos(dos_data, output_file='dos.png', title=None,
             fermi_energy=None, energy_range=None):
    """Plot density of states.

    Args:
        dos_data: dict from parse_dos()
        output_file: Output filename for plot
        title: Plot title (optional)
        fermi_energy: Fermi energy for vertical line (optional)
        energy_range: Tuple (min, max) for x-axis (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    energy = dos_data['energy']
    dos = dos_data['dos']

    if len(energy) == 0:
        logging.warning("No DOS data to plot")
        return None

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(energy, dos, 'b-', linewidth=1.5)
    ax.fill_between(energy, 0, dos, alpha=0.3)

    if fermi_energy is not None:
        ax.axvline(x=fermi_energy, color='r', linestyle='--', linewidth=1, label='Fermi level')
        ax.legend()

    ax.set_xlabel('Energy (eV)')
    ax.set_ylabel('DOS (states/eV)')
    ax.set_title(title or 'Density of States')
    ax.set_ylim(bottom=0)

    if energy_range:
        ax.set_xlim(energy_range)

    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved DOS plot: {output_file}")
    return output_file


# ============= CONVENIENCE FUNCTIONS =============

def quick_setup(input_dir, output_dir, work_dir=None, copy_input=True):
    """Quick setup for typical QE workflow.

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
    """Quick finish for typical QE workflow.

    Copies output files to output directory.

    Returns:
        List of copied output files
    """
    return copy_outputs()


# ============= EQUATION OF STATE =============

def fit_equation_of_state(volumes, energies, eos_type='birchmurnaghan'):
    """Fit equation of state to energy-volume data.

    Uses ASE's EquationOfState for robust fitting with multiple EOS forms.
    This is the standard approach for computing bulk modulus from DFT.

    Args:
        volumes: Array of unit cell volumes (Å³ or Bohr³)
        energies: Array of total energies (eV or Ry)
        eos_type: EOS form to use. Options:
            - 'birchmurnaghan' (default): 3rd-order Birch-Murnaghan (most common)
            - 'murnaghan': Murnaghan EOS
            - 'birch': Birch EOS
            - 'vinet': Vinet (universal) EOS
            - 'antonschmidt': Anton-Schmidt EOS (metals)
            - 'p3': 3rd-order polynomial

    Returns:
        dict with keys:
            - V0: equilibrium volume
            - E0: energy at equilibrium
            - B0: bulk modulus (GPa)
            - B0_prime: pressure derivative of bulk modulus (dimensionless)
            - residuals: fitting residuals
            - eos_type: EOS form used
            - volumes: input volumes
            - energies: input energies
            - fitted_energies: energies from fitted curve

    Example:
        >>> # Run vc-relax at different pressures or manual volume scaling
        >>> volumes = [150, 155, 160, 165, 170]  # Å³
        >>> energies = [-310.5, -310.7, -310.8, -310.75, -310.6]  # eV
        >>> eos = fit_equation_of_state(volumes, energies)
        >>> print(f"Bulk modulus: {eos['B0']:.1f} GPa")
    """
    try:
        from ase.eos import EquationOfState
        from ase.units import kJ
    except ImportError:
        raise ImportError("ASE is required for EOS fitting. Install with: pip install ase")

    volumes = np.array(volumes)
    energies = np.array(energies)

    if len(volumes) < 4:
        raise ValueError("At least 4 data points required for reliable EOS fitting")

    # ASE's EquationOfState expects energies in eV
    eos = EquationOfState(volumes, energies, eos=eos_type)

    try:
        v0, e0, B = eos.fit()
    except RuntimeError as e:
        logging.error(f"EOS fitting failed: {e}")
        raise

    # B is in eV/Å³, convert to GPa (1 eV/Å³ = 160.21766 GPa)
    B0_GPa = B * 160.21766208

    # Get B' (pressure derivative) - ASE stores this internally after fit
    # For Birch-Murnaghan, B' is typically ~4
    # We extract it from the fitted parameters
    B0_prime = 4.0  # Default for 3rd-order BM
    if hasattr(eos, 'eos_parameters') and len(eos.eos_parameters) > 3:
        B0_prime = eos.eos_parameters[3]

    # Calculate fitted curve for plotting
    v_fit = np.linspace(volumes.min() * 0.98, volumes.max() * 1.02, 100)
    e_fit = eos.func(v_fit, *eos.eos_parameters)

    # Calculate residuals
    e_predicted = eos.func(volumes, *eos.eos_parameters)
    residuals = energies - e_predicted
    rmse = np.sqrt(np.mean(residuals**2))

    result = {
        'V0': v0,
        'E0': e0,
        'B0': B0_GPa,
        'B0_prime': B0_prime,
        'residuals': residuals,
        'rmse': rmse,
        'eos_type': eos_type,
        'volumes': volumes,
        'energies': energies,
        'v_fit': v_fit,
        'e_fit': e_fit
    }

    logging.info(f"EOS fit ({eos_type}): V0={v0:.3f} Å³, E0={e0:.6f} eV, B0={B0_GPa:.1f} GPa")
    return result


def plot_equation_of_state(eos_data, output_file='eos.png', title=None):
    """Plot equation of state fit.

    Args:
        eos_data: dict from fit_equation_of_state()
        output_file: Output filename
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))

    # Data points
    ax.plot(eos_data['volumes'], eos_data['energies'], 'bo', markersize=8, label='DFT data')

    # Fitted curve
    ax.plot(eos_data['v_fit'], eos_data['e_fit'], 'r-', linewidth=2, label='EOS fit')

    # Mark equilibrium
    ax.axvline(x=eos_data['V0'], color='g', linestyle='--', alpha=0.5)
    ax.axhline(y=eos_data['E0'], color='g', linestyle='--', alpha=0.5)

    ax.set_xlabel('Volume (Å³)')
    ax.set_ylabel('Energy (eV)')
    ax.set_title(title or f"Equation of State ({eos_data['eos_type']})\n"
                 f"V₀={eos_data['V0']:.2f} Å³, B₀={eos_data['B0']:.1f} GPa")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved EOS plot: {output_file}")
    return output_file


# ============= ELASTIC CONSTANTS =============

# Voigt notation mapping for strain tensors
VOIGT_STRAIN_MAP = {
    0: (0, 0),  # xx
    1: (1, 1),  # yy
    2: (2, 2),  # zz
    3: (1, 2),  # yz
    4: (0, 2),  # xz
    5: (0, 1),  # xy
}


def generate_strain_patterns(crystal_system='cubic', strain_magnitude=0.01):
    """Generate strain patterns for elastic constant calculation.

    Uses the standard approach of applying small strains and measuring stress response.
    Returns strain tensors in Voigt notation.

    Args:
        crystal_system: Crystal symmetry. Options:
            - 'cubic': 3 independent constants (C11, C12, C44)
            - 'hexagonal': 5 independent constants
            - 'tetragonal': 6-7 independent constants
            - 'orthorhombic': 9 independent constants
            - 'monoclinic': 13 independent constants
            - 'triclinic': 21 independent constants (full tensor)
        strain_magnitude: Magnitude of applied strain (default 0.01 = 1%)

    Returns:
        list of dicts, each with:
            - 'strain_voigt': 6-component strain in Voigt notation
            - 'strain_matrix': 3x3 strain tensor
            - 'deformation_matrix': 3x3 deformation gradient F
            - 'description': Human-readable description
    """
    e = strain_magnitude
    patterns = []

    if crystal_system == 'cubic':
        # For cubic: need strains to determine C11, C12, C44
        # 1. Hydrostatic strain for B = (C11 + 2*C12)/3
        # 2. Tetragonal strain for C11 - C12
        # 3. Shear strain for C44

        # Strain 1: Volume-conserving tetragonal (for C11-C12)
        patterns.append({
            'strain_voigt': np.array([e, -e/2, -e/2, 0, 0, 0]),
            'description': 'Tetragonal strain (C11-C12)'
        })

        # Strain 2: Pure shear in xy plane (for C44)
        patterns.append({
            'strain_voigt': np.array([0, 0, 0, 0, 0, e]),
            'description': 'Shear strain xy (C44)'
        })

        # Strain 3: Hydrostatic for cross-check
        patterns.append({
            'strain_voigt': np.array([e, e, e, 0, 0, 0]),
            'description': 'Hydrostatic strain (bulk modulus)'
        })

    elif crystal_system == 'hexagonal':
        # 5 independent: C11, C12, C13, C33, C44
        patterns.append({'strain_voigt': np.array([e, 0, 0, 0, 0, 0]), 'description': 'e_xx'})
        patterns.append({'strain_voigt': np.array([0, 0, e, 0, 0, 0]), 'description': 'e_zz'})
        patterns.append({'strain_voigt': np.array([0, 0, 0, e, 0, 0]), 'description': 'e_yz'})
        patterns.append({'strain_voigt': np.array([0, 0, 0, 0, 0, e]), 'description': 'e_xy'})
        patterns.append({'strain_voigt': np.array([e, e, 0, 0, 0, 0]), 'description': 'e_xx+e_yy'})

    else:  # General/triclinic - use all 6 independent strains
        for i in range(6):
            strain = np.zeros(6)
            strain[i] = e
            labels = ['e_xx', 'e_yy', 'e_zz', 'e_yz', 'e_xz', 'e_xy']
            patterns.append({
                'strain_voigt': strain,
                'description': labels[i]
            })

    # Convert Voigt to matrix form and compute deformation gradient
    for p in patterns:
        # Voigt to tensor: [e1,e2,e3,e4,e5,e6] -> [[e1,e6/2,e5/2],[e6/2,e2,e4/2],[e5/2,e4/2,e3]]
        ev = p['strain_voigt']
        strain_matrix = np.array([
            [ev[0], ev[5]/2, ev[4]/2],
            [ev[5]/2, ev[1], ev[3]/2],
            [ev[4]/2, ev[3]/2, ev[2]]
        ])
        p['strain_matrix'] = strain_matrix

        # Deformation gradient F = I + strain (for small strains)
        p['deformation_matrix'] = np.eye(3) + strain_matrix

    return patterns


def apply_strain_to_structure(structure, deformation_matrix):
    """Apply strain to a pymatgen Structure.

    Args:
        structure: pymatgen Structure object
        deformation_matrix: 3x3 deformation gradient matrix

    Returns:
        New strained Structure
    """
    try:
        from pymatgen.core import Structure
        from pymatgen.analysis.elasticity.strain import Deformation
    except ImportError:
        raise ImportError("pymatgen is required. Install with: pip install pymatgen")

    deformation = Deformation(deformation_matrix)
    strained = deformation.apply_to_structure(structure)
    return strained


def parse_stress_tensor(output_file):
    """Parse stress tensor from QE output.

    QE outputs stress in kbar. This function extracts the full tensor.

    Args:
        output_file: Path to QE output file

    Returns:
        dict with:
            - 'stress_kbar': 3x3 stress tensor in kbar
            - 'stress_GPa': 3x3 stress tensor in GPa
            - 'stress_voigt': 6-component Voigt notation (GPa)
            - 'pressure_kbar': hydrostatic pressure
    """
    stress_matrix = None

    with open(output_file, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if 'total   stress' in line:
            # Next 3 lines contain the stress tensor
            stress_matrix = np.zeros((3, 3))
            for j in range(3):
                parts = lines[i + 1 + j].split()
                # Format: sigma_xx sigma_xy sigma_xz  P_xx P_xy P_xz
                # First 3 are stress in kbar, last 3 are pressure contribution
                stress_matrix[j] = [float(parts[k]) for k in range(3)]

    if stress_matrix is None:
        logging.warning(f"No stress tensor found in {output_file}")
        return None

    # Convert kbar to GPa (1 kbar = 0.1 GPa)
    stress_GPa = stress_matrix * 0.1

    # Voigt notation: [xx, yy, zz, yz, xz, xy]
    stress_voigt = np.array([
        stress_GPa[0, 0], stress_GPa[1, 1], stress_GPa[2, 2],
        stress_GPa[1, 2], stress_GPa[0, 2], stress_GPa[0, 1]
    ])

    pressure = -np.trace(stress_matrix) / 3

    return {
        'stress_kbar': stress_matrix,
        'stress_GPa': stress_GPa,
        'stress_voigt': stress_voigt,
        'pressure_kbar': pressure
    }


def compute_elastic_tensor(strains, stresses, crystal_system='cubic'):
    """Compute elastic tensor from strain-stress data.

    Uses linear regression to fit C_ij from σ_i = C_ij * ε_j.

    Args:
        strains: List of strain tensors (Voigt notation, 6-component)
        stresses: List of stress tensors (Voigt notation, 6-component, GPa)
        crystal_system: Crystal symmetry for constraints

    Returns:
        dict with:
            - 'C': Full 6x6 elastic tensor (GPa)
            - 'C_dict': Dict of independent elastic constants
            - 'bulk_modulus_voigt': Voigt average bulk modulus (GPa)
            - 'bulk_modulus_reuss': Reuss average bulk modulus (GPa)
            - 'shear_modulus_voigt': Voigt average shear modulus (GPa)
            - 'shear_modulus_reuss': Reuss average shear modulus (GPa)
            - 'youngs_modulus': Young's modulus (GPa)
            - 'poissons_ratio': Poisson's ratio
    """
    try:
        from pymatgen.analysis.elasticity.elastic import ElasticTensor
        from pymatgen.analysis.elasticity.stress import Stress
        from pymatgen.analysis.elasticity.strain import Strain
    except ImportError:
        raise ImportError("pymatgen is required. Install with: pip install pymatgen")

    strains = np.array(strains)
    stresses = np.array(stresses)

    # Solve for elastic tensor using least squares: σ = C * ε
    # For n strain patterns: [σ1, σ2, ...] = C * [ε1, ε2, ...]
    C, residuals, rank, s = np.linalg.lstsq(strains, stresses, rcond=None)
    C = C.T  # Transpose to get proper C_ij

    # Make symmetric
    C = (C + C.T) / 2

    # Use pymatgen's ElasticTensor for proper analysis
    try:
        elastic_tensor = ElasticTensor.from_voigt(C)

        # Get derived properties
        bulk_voigt = elastic_tensor.k_voigt
        bulk_reuss = elastic_tensor.k_reuss
        shear_voigt = elastic_tensor.g_voigt
        shear_reuss = elastic_tensor.g_reuss
        youngs = elastic_tensor.y_mod
        poisson = elastic_tensor.universal_anisotropy

    except Exception as e:
        logging.warning(f"pymatgen elastic analysis failed: {e}, using manual calculation")
        # Manual Voigt-Reuss-Hill averages for cubic
        bulk_voigt = (C[0,0] + C[1,1] + C[2,2] + 2*(C[0,1] + C[0,2] + C[1,2])) / 9
        bulk_reuss = bulk_voigt  # Approximation
        shear_voigt = ((C[0,0] + C[1,1] + C[2,2]) - (C[0,1] + C[0,2] + C[1,2]) + 3*(C[3,3] + C[4,4] + C[5,5])) / 15
        shear_reuss = shear_voigt
        youngs = 9 * bulk_voigt * shear_voigt / (3 * bulk_voigt + shear_voigt)
        poisson = (3 * bulk_voigt - 2 * shear_voigt) / (6 * bulk_voigt + 2 * shear_voigt)

    # Extract key constants based on crystal system
    C_dict = {}
    if crystal_system == 'cubic':
        C_dict = {
            'C11': C[0, 0],
            'C12': C[0, 1],
            'C44': C[3, 3]
        }
    elif crystal_system == 'hexagonal':
        C_dict = {
            'C11': C[0, 0],
            'C12': C[0, 1],
            'C13': C[0, 2],
            'C33': C[2, 2],
            'C44': C[3, 3]
        }
    else:
        # Full tensor
        for i in range(6):
            for j in range(i, 6):
                if abs(C[i, j]) > 0.1:  # Only significant values
                    C_dict[f'C{i+1}{j+1}'] = C[i, j]

    result = {
        'C': C,
        'C_dict': C_dict,
        'bulk_modulus_voigt': bulk_voigt,
        'bulk_modulus_reuss': bulk_reuss,
        'bulk_modulus_vrh': (bulk_voigt + bulk_reuss) / 2,
        'shear_modulus_voigt': shear_voigt,
        'shear_modulus_reuss': shear_reuss,
        'shear_modulus_vrh': (shear_voigt + shear_reuss) / 2,
        'youngs_modulus': youngs,
        'poissons_ratio': poisson
    }

    logging.info(f"Elastic constants: {C_dict}")
    logging.info(f"Bulk modulus (VRH): {result['bulk_modulus_vrh']:.1f} GPa")
    logging.info(f"Shear modulus (VRH): {result['shear_modulus_vrh']:.1f} GPa")

    return result


# ============= CONVERGENCE TESTING =============

def generate_convergence_inputs(base_input, parameter, values, output_dir='.'):
    """Generate QE input files for convergence testing.

    Creates multiple input files varying a single parameter (ecutwfc, k-points, etc.)

    Args:
        base_input: Path to base QE input file or dict of parameters
        parameter: Parameter to vary. Options:
            - 'ecutwfc': Wavefunction cutoff
            - 'kpoints': k-point grid (values should be list of [nx,ny,nz])
            - 'ecutrho': Charge density cutoff
        values: List of values to test
        output_dir: Directory for output files

    Returns:
        List of generated input file paths
    """
    import re

    if isinstance(base_input, str):
        with open(base_input, 'r') as f:
            base_content = f.read()
    else:
        raise ValueError("base_input must be a file path")

    os.makedirs(output_dir, exist_ok=True)
    generated_files = []

    for val in values:
        content = base_content

        if parameter == 'ecutwfc':
            # Replace ecutwfc value
            content = re.sub(
                r'ecutwfc\s*=\s*[\d.]+',
                f'ecutwfc = {val}',
                content,
                flags=re.IGNORECASE
            )
            filename = f'conv_ecutwfc_{val}.in'

        elif parameter == 'ecutrho':
            content = re.sub(
                r'ecutrho\s*=\s*[\d.]+',
                f'ecutrho = {val}',
                content,
                flags=re.IGNORECASE
            )
            filename = f'conv_ecutrho_{val}.in'

        elif parameter == 'kpoints':
            # Replace K_POINTS line
            if isinstance(val, (list, tuple)):
                kstr = f'{val[0]} {val[1]} {val[2]} 0 0 0'
            else:
                kstr = f'{val} {val} {val} 0 0 0'
            content = re.sub(
                r'(K_POINTS\s+\{?\s*automatic\s*\}?\s*\n)\s*\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+',
                f'\\1{kstr}',
                content,
                flags=re.IGNORECASE
            )
            if isinstance(val, (list, tuple)):
                filename = f'conv_kpt_{val[0]}x{val[1]}x{val[2]}.in'
            else:
                filename = f'conv_kpt_{val}x{val}x{val}.in'

        else:
            raise ValueError(f"Unknown parameter: {parameter}")

        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        generated_files.append(filepath)
        logging.info(f"Generated: {filename}")

    return generated_files


def analyze_convergence(results, parameter_name='parameter', energy_threshold=0.001,
                       force_threshold=0.01):
    """Analyze convergence from a series of calculations.

    Args:
        results: List of dicts with 'parameter', 'energy_eV', and optionally 'force'
        parameter_name: Name of varied parameter (for plotting)
        energy_threshold: Energy convergence threshold in eV/atom (default: 1 meV)
        force_threshold: Force convergence threshold in eV/Å (default: 10 meV/Å)

    Returns:
        dict with:
            - 'converged_value': First parameter value meeting convergence criteria
            - 'convergence_data': DataFrame with all data
            - 'energy_differences': Energy differences from highest parameter
            - 'is_converged': List of boolean convergence flags
    """
    if not results:
        raise ValueError("No results provided")

    # Sort by parameter
    results = sorted(results, key=lambda x: x['parameter'] if not isinstance(x['parameter'], (list, tuple))
                     else x['parameter'][0])

    params = [r['parameter'] for r in results]
    energies = np.array([r['energy_eV'] for r in results])

    # Reference is the last (highest) value
    ref_energy = energies[-1]
    energy_diffs = np.abs(energies - ref_energy)

    # Check convergence
    converged_idx = None
    for i in range(len(energy_diffs) - 1):
        if energy_diffs[i] < energy_threshold:
            converged_idx = i
            break

    result = {
        'parameters': params,
        'energies': energies,
        'energy_differences': energy_diffs,
        'reference_energy': ref_energy,
        'converged_index': converged_idx,
        'converged_value': params[converged_idx] if converged_idx is not None else None,
        'parameter_name': parameter_name,
        'threshold': energy_threshold
    }

    if converged_idx is not None:
        logging.info(f"Converged at {parameter_name}={params[converged_idx]} "
                    f"(ΔE={energy_diffs[converged_idx]*1000:.2f} meV)")
    else:
        logging.warning(f"Not converged within threshold {energy_threshold*1000:.1f} meV")

    return result


def plot_convergence(conv_data, output_file='convergence.png', title=None):
    """Plot convergence test results.

    Args:
        conv_data: dict from analyze_convergence()
        output_file: Output filename
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    params = conv_data['parameters']
    energy_diffs = conv_data['energy_differences'] * 1000  # Convert to meV

    # Handle k-point tuples
    if isinstance(params[0], (list, tuple)):
        x_vals = [p[0] for p in params]  # Use first component
        x_label = f"{conv_data['parameter_name']} (first component)"
    else:
        x_vals = params
        x_label = conv_data['parameter_name']

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.semilogy(x_vals, energy_diffs, 'bo-', markersize=8, linewidth=2)

    # Mark convergence threshold
    threshold_meV = conv_data['threshold'] * 1000
    ax.axhline(y=threshold_meV, color='r', linestyle='--', label=f'Threshold ({threshold_meV:.1f} meV)')

    # Mark converged value
    if conv_data['converged_index'] is not None:
        conv_x = x_vals[conv_data['converged_index']]
        ax.axvline(x=conv_x, color='g', linestyle='--', alpha=0.7,
                  label=f'Converged: {conv_data["converged_value"]}')

    ax.set_xlabel(x_label)
    ax.set_ylabel('ΔE (meV)')
    ax.set_title(title or f'{conv_data["parameter_name"]} Convergence')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved convergence plot: {output_file}")
    return output_file


# ============= EFFECTIVE MASS =============

def extract_effective_mass(bands_data, band_index, k_index, direction='auto',
                          n_points=5, lattice_constant=None):
    """Extract effective mass from band curvature.

    Computes m* = ℏ² / (d²E/dk²) by fitting a parabola to band energies
    near band extrema (VBM or CBM).

    Args:
        bands_data: dict from parse_bands() or array of (k, energy) points
        band_index: Index of band to analyze (0-indexed)
        k_index: Index of k-point at band extremum (VBM or CBM)
        direction: Direction for mass calculation. Options:
            - 'auto': Use k-path direction
            - 'x', 'y', 'z': Specific Cartesian direction
        n_points: Number of points on each side of extremum for fitting
        lattice_constant: Lattice constant in Å (needed for k-space scaling)

    Returns:
        dict with:
            - 'effective_mass': m*/m_e (electron masses)
            - 'curvature': d²E/dk² in eV·Å²
            - 'fit_quality': R² of parabolic fit
            - 'band_type': 'electron' or 'hole' (based on curvature sign)

    Note:
        For accurate effective masses, use dense k-point sampling near the extremum.
        The effective mass tensor requires calculations along multiple directions.
    """
    from scipy.optimize import curve_fit

    # Physical constants
    HBAR_EV_S = 6.582119569e-16  # ℏ in eV·s
    M_E = 9.10938e-31  # electron mass in kg
    HBAR_SI = 1.054571817e-34  # ℏ in J·s

    if isinstance(bands_data, dict):
        k_points = bands_data['kpoints']
        energies = bands_data['bands'][band_index]
    else:
        # Assume array of (k, E) pairs
        bands_data = np.array(bands_data)
        k_points = bands_data[:, 0]
        energies = bands_data[:, 1]

    # Extract region around extremum
    i_min = max(0, k_index - n_points)
    i_max = min(len(k_points), k_index + n_points + 1)

    k_region = k_points[i_min:i_max]
    e_region = energies[i_min:i_max]

    # Center around the extremum
    k0 = k_points[k_index]
    e0 = energies[k_index]

    k_centered = k_region - k0
    e_centered = e_region - e0

    # Fit parabola: E(k) = a*k² + b*k + c
    def parabola(k, a, b, c):
        return a * k**2 + b * k + c

    try:
        popt, pcov = curve_fit(parabola, k_centered, e_centered,
                               p0=[1.0, 0.0, 0.0])
        a, b, c = popt

        # Calculate R²
        e_fit = parabola(k_centered, *popt)
        ss_res = np.sum((e_centered - e_fit)**2)
        ss_tot = np.sum((e_centered - np.mean(e_centered))**2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    except RuntimeError:
        logging.warning("Parabolic fit failed")
        return None

    # Curvature d²E/dk² = 2a (in units of eV / (2π/a)²)
    curvature = 2 * a  # eV per (k-unit)²

    # If lattice constant provided, convert to proper units
    if lattice_constant is not None:
        # k is in units of 2π/a, so dk is in Å⁻¹ when multiplied by 2π/a
        k_scale = 2 * np.pi / lattice_constant  # Å⁻¹
        curvature_SI = curvature / (k_scale**2)  # eV·Å²

        # m* = ℏ² / curvature (need to convert units carefully)
        # ℏ² in eV²·s² = (6.582e-16)² ≈ 4.33e-31 eV²·s²
        # 1 Å = 1e-10 m
        # m* = ℏ²/(d²E/dk²) where d²E/dk² is in eV·Å²

        # Using: ℏ²/(eV·Å²) → kg
        # ℏ² = 1.054e-34² J²·s² = 1.11e-68 J²·s²
        # 1 eV = 1.6e-19 J, 1 Å² = 1e-20 m²
        # ℏ²/(eV·Å²) = 1.11e-68 / (1.6e-19 * 1e-20) = 6.94e-30 kg

        HBAR2_FACTOR = 7.62  # ℏ²/(eV·Å²) in units of m_e
        effective_mass = HBAR2_FACTOR / abs(curvature_SI) if curvature_SI != 0 else float('inf')
    else:
        # Return in arbitrary units
        effective_mass = 1.0 / abs(curvature) if curvature != 0 else float('inf')
        curvature_SI = curvature
        logging.warning("Lattice constant not provided - effective mass in arbitrary units")

    # Determine if electron or hole mass
    band_type = 'electron' if curvature > 0 else 'hole'

    result = {
        'effective_mass': effective_mass,
        'curvature': curvature_SI,
        'fit_quality': r_squared,
        'band_type': band_type,
        'k_index': k_index,
        'band_index': band_index,
        'fit_coefficients': popt.tolist()
    }

    logging.info(f"Effective mass ({band_type}): {effective_mass:.3f} m_e, R²={r_squared:.4f}")
    return result


def find_band_extrema(bands_data, fermi_energy=None, n_bands_search=4):
    """Find valence band maximum (VBM) and conduction band minimum (CBM).

    Args:
        bands_data: dict from parse_bands()
        fermi_energy: Fermi energy in eV (if known)
        n_bands_search: Number of bands near gap to search

    Returns:
        dict with:
            - 'vbm': dict with 'energy', 'band_index', 'k_index'
            - 'cbm': dict with 'energy', 'band_index', 'k_index'
            - 'band_gap': Band gap in eV
            - 'gap_type': 'direct' or 'indirect'
    """
    bands = bands_data['bands']  # Shape: (n_bands, n_kpoints)
    n_bands, n_kpoints = bands.shape

    if fermi_energy is not None:
        # Find bands below and above Fermi level
        max_below = -float('inf')
        min_above = float('inf')
        vbm_info = None
        cbm_info = None

        for i in range(n_bands):
            band = bands[i]
            band_max = np.max(band)
            band_min = np.min(band)

            if band_max <= fermi_energy and band_max > max_below:
                max_below = band_max
                k_idx = np.argmax(band)
                vbm_info = {'energy': band_max, 'band_index': i, 'k_index': k_idx}

            if band_min >= fermi_energy and band_min < min_above:
                min_above = band_min
                k_idx = np.argmin(band)
                cbm_info = {'energy': band_min, 'band_index': i, 'k_index': k_idx}

    else:
        # Use middle of band structure as estimate
        mid_band = n_bands // 2

        # Search for VBM in lower bands
        vbm_info = None
        max_e = -float('inf')
        for i in range(max(0, mid_band - n_bands_search), mid_band):
            band_max = np.max(bands[i])
            if band_max > max_e:
                max_e = band_max
                vbm_info = {'energy': band_max, 'band_index': i, 'k_index': np.argmax(bands[i])}

        # Search for CBM in upper bands
        cbm_info = None
        min_e = float('inf')
        for i in range(mid_band, min(n_bands, mid_band + n_bands_search)):
            band_min = np.min(bands[i])
            if band_min < min_e:
                min_e = band_min
                cbm_info = {'energy': band_min, 'band_index': i, 'k_index': np.argmin(bands[i])}

    if vbm_info is None or cbm_info is None:
        logging.warning("Could not identify VBM/CBM")
        return None

    band_gap = cbm_info['energy'] - vbm_info['energy']
    gap_type = 'direct' if vbm_info['k_index'] == cbm_info['k_index'] else 'indirect'

    result = {
        'vbm': vbm_info,
        'cbm': cbm_info,
        'band_gap': band_gap,
        'gap_type': gap_type
    }

    logging.info(f"Band gap: {band_gap:.3f} eV ({gap_type})")
    logging.info(f"VBM: band {vbm_info['band_index']}, k-point {vbm_info['k_index']}")
    logging.info(f"CBM: band {cbm_info['band_index']}, k-point {cbm_info['k_index']}")

    return result


# ============= PHONOPY INTERFACE =============

def create_phonopy_supercell(structure, supercell_matrix=None, displacement=0.01):
    """Create displaced supercells for phonon calculation using phonopy.

    This generates the structures needed for finite-displacement phonon calculations.
    After running QE on these structures, use `compute_phonons_from_forces()`.

    Args:
        structure: pymatgen Structure or path to structure file (CIF, POSCAR, etc.)
        supercell_matrix: 3x3 matrix or [nx, ny, nz] for diagonal supercell.
                         Default: 2x2x2 for bulk systems
        displacement: Atomic displacement magnitude in Å (default: 0.01)

    Returns:
        dict with:
            - 'phonopy': phonopy.Phonopy object
            - 'supercell': Supercell structure (ASE Atoms)
            - 'displacements': List of displacement info
            - 'structures': List of displaced structures (ASE Atoms)
            - 'structure_files': List of generated POSCAR files

    Example:
        >>> result = create_phonopy_supercell('relaxed.cif', [2, 2, 2])
        >>> # Run QE on each structure in result['structure_files']
        >>> # Then: compute_phonons_from_forces(result['phonopy'], forces_list)
    """
    try:
        from phonopy import Phonopy
        from phonopy.structure.atoms import PhonopyAtoms
        from pymatgen.core import Structure
        from pymatgen.io.ase import AseAtomsAdaptor
        from ase.io import write as ase_write
    except ImportError as e:
        raise ImportError(f"Required package not found: {e}. "
                         "Install with: pip install phonopy pymatgen ase")

    # Load structure
    if isinstance(structure, str):
        pmg_structure = Structure.from_file(structure)
    else:
        pmg_structure = structure

    # Convert to phonopy atoms
    phonopy_atoms = PhonopyAtoms(
        symbols=[str(s) for s in pmg_structure.species],
        cell=pmg_structure.lattice.matrix,
        scaled_positions=pmg_structure.frac_coords
    )

    # Default supercell
    if supercell_matrix is None:
        supercell_matrix = [[2, 0, 0], [0, 2, 0], [0, 0, 2]]
    elif isinstance(supercell_matrix, (list, tuple)) and len(supercell_matrix) == 3:
        if isinstance(supercell_matrix[0], (int, float)):
            supercell_matrix = np.diag(supercell_matrix)

    # Create phonopy object
    phonopy = Phonopy(phonopy_atoms, supercell_matrix)

    # Generate displacements
    phonopy.generate_displacements(distance=displacement)

    # Get displaced supercells
    supercells = phonopy.supercells_with_displacements
    displacements = phonopy.displacements

    logging.info(f"Generated {len(supercells)} displaced structures")
    logging.info(f"Supercell size: {np.diag(supercell_matrix) if isinstance(supercell_matrix, np.ndarray) else supercell_matrix}")

    # Convert to ASE and save as POSCAR files
    structure_files = []
    ase_structures = []

    adaptor = AseAtomsAdaptor()

    # Also save the perfect supercell
    sc = phonopy.supercell
    sc_pmg = Structure(
        sc.cell,
        [str(s) for s in sc.symbols],
        sc.scaled_positions
    )
    sc_ase = adaptor.get_atoms(sc_pmg)

    for i, supercell in enumerate(supercells):
        # Convert phonopy atoms to ASE
        ase_atoms = adaptor.get_atoms(Structure(
            supercell.cell,
            [str(s) for s in supercell.symbols],
            supercell.scaled_positions
        ))
        ase_structures.append(ase_atoms)

        # Save as POSCAR
        filename = f'POSCAR-{i+1:03d}'
        ase_write(filename, ase_atoms, format='vasp')
        structure_files.append(filename)

    return {
        'phonopy': phonopy,
        'supercell': sc_ase,
        'displacements': displacements,
        'structures': ase_structures,
        'structure_files': structure_files,
        'n_displacements': len(supercells)
    }


def compute_phonons_from_forces(phonopy, forces_list, save_fc=True):
    """Compute phonon properties from calculated forces.

    After running QE on displaced structures, use this to compute phonons.

    Args:
        phonopy: Phonopy object from create_phonopy_supercell()
        forces_list: List of force arrays, one per displaced structure.
                    Each should be shape (n_atoms, 3) in eV/Å
        save_fc: Save force constants to file

    Returns:
        dict with:
            - 'phonopy': Updated Phonopy object with force constants
            - 'force_constants': Force constant matrix
    """
    forces_array = np.array(forces_list)

    # Set forces in phonopy
    phonopy.forces = forces_array

    # Compute force constants
    phonopy.produce_force_constants()

    if save_fc:
        from phonopy.file_IO import write_force_constants_to_hdf5
        write_force_constants_to_hdf5(phonopy.force_constants, filename='force_constants.hdf5')
        logging.info("Saved force constants to force_constants.hdf5")

    return {
        'phonopy': phonopy,
        'force_constants': phonopy.force_constants
    }


def calculate_phonon_dispersion(phonopy, path=None, n_points=51):
    """Calculate phonon band structure along high-symmetry path.

    Args:
        phonopy: Phonopy object with force constants
        path: High-symmetry path as list of labels, e.g., ['G', 'X', 'M', 'G']
              If None, uses seekpath to auto-generate
        n_points: Number of points per segment

    Returns:
        dict with:
            - 'distances': k-point distances
            - 'frequencies': Phonon frequencies (THz)
            - 'eigenvectors': Phonon eigenvectors (if requested)
            - 'path_labels': Labels for special points
            - 'path_connections': Connection points
    """
    try:
        import seekpath
    except ImportError:
        seekpath = None

    # Auto-generate path using seekpath
    if path is None and seekpath is not None:
        cell = phonopy.primitive.cell
        positions = phonopy.primitive.scaled_positions
        numbers = phonopy.primitive.numbers

        path_data = seekpath.get_path((cell, positions, numbers))
        path = path_data['path']
        point_coords = path_data['point_coords']

        # Convert to phonopy format
        labels = []
        coords = []
        for segment in path:
            for point in segment:
                if point not in labels:
                    labels.append(point)
                    coords.append(point_coords[point])

        # Set band structure path
        phonopy.auto_band_structure(npoints=n_points)
    else:
        phonopy.auto_band_structure(npoints=n_points)

    # Get band data
    band_dict = phonopy.get_band_structure_dict()

    distances = band_dict['distances']
    frequencies = band_dict['frequencies']

    result = {
        'distances': distances,
        'frequencies': frequencies,
        'path_labels': band_dict.get('labels', []),
        'n_qpoints': sum(len(d) for d in distances)
    }

    logging.info(f"Computed phonon dispersion with {result['n_qpoints']} q-points")
    return result


def calculate_phonon_dos(phonopy, mesh=None, n_points=201):
    """Calculate phonon density of states.

    Args:
        phonopy: Phonopy object with force constants
        mesh: q-point mesh [nx, ny, nz]. Default: [20, 20, 20]
        n_points: Number of frequency points for DOS

    Returns:
        dict with:
            - 'frequency': Frequency array (THz)
            - 'total_dos': Total phonon DOS
            - 'partial_dos': Partial DOS per atom type (if available)
    """
    if mesh is None:
        mesh = [20, 20, 20]

    phonopy.run_mesh(mesh)
    phonopy.run_total_dos()

    dos_dict = phonopy.get_total_dos_dict()

    result = {
        'frequency': dos_dict['frequency_points'],
        'total_dos': dos_dict['total_dos']
    }

    logging.info(f"Computed phonon DOS on {mesh} mesh")
    return result


def calculate_thermal_properties(phonopy, t_min=0, t_max=1000, t_step=10):
    """Calculate thermal properties from phonons.

    Computes heat capacity, free energy, and entropy using the harmonic approximation.

    Args:
        phonopy: Phonopy object with force constants
        t_min: Minimum temperature (K)
        t_max: Maximum temperature (K)
        t_step: Temperature step (K)

    Returns:
        dict with:
            - 'temperatures': Temperature array (K)
            - 'free_energy': Helmholtz free energy (kJ/mol)
            - 'entropy': Entropy (J/K/mol)
            - 'heat_capacity': Heat capacity Cv (J/K/mol)
    """
    # Run thermal properties calculation
    phonopy.run_thermal_properties(t_min=t_min, t_max=t_max, t_step=t_step)

    tp_dict = phonopy.get_thermal_properties_dict()

    result = {
        'temperatures': tp_dict['temperatures'],
        'free_energy': tp_dict['free_energy'],
        'entropy': tp_dict['entropy'],
        'heat_capacity': tp_dict['heat_capacity']
    }

    logging.info(f"Computed thermal properties from {t_min}K to {t_max}K")
    return result


def plot_phonon_dispersion(dispersion_data, output_file='phonon_bands.png', title=None):
    """Plot phonon band structure.

    Args:
        dispersion_data: dict from calculate_phonon_dispersion()
        output_file: Output filename
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))

    # Plot each segment
    for i, (dist, freq) in enumerate(zip(dispersion_data['distances'],
                                         dispersion_data['frequencies'])):
        for band in range(freq.shape[1]):
            ax.plot(dist, freq[:, band], 'b-', linewidth=1)

    ax.axhline(y=0, color='k', linestyle='--', linewidth=0.5)
    ax.set_xlabel('Wave Vector')
    ax.set_ylabel('Frequency (THz)')
    ax.set_title(title or 'Phonon Dispersion')
    ax.set_xlim(0, dispersion_data['distances'][-1][-1])
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved phonon dispersion plot: {output_file}")
    return output_file


def plot_phonon_dos(dos_data, output_file='phonon_dos.png', title=None):
    """Plot phonon density of states.

    Args:
        dos_data: dict from calculate_phonon_dos()
        output_file: Output filename
        title: Plot title (optional)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(dos_data['frequency'], dos_data['total_dos'], 'b-', linewidth=1.5)
    ax.fill_between(dos_data['frequency'], 0, dos_data['total_dos'], alpha=0.3)

    ax.axvline(x=0, color='k', linestyle='--', linewidth=0.5)
    ax.set_xlabel('Frequency (THz)')
    ax.set_ylabel('DOS')
    ax.set_title(title or 'Phonon Density of States')
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=dos_data['frequency'].min())
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved phonon DOS plot: {output_file}")
    return output_file


def parse_qe_forces(output_file):
    """Parse forces from QE output for phonon calculations.

    Args:
        output_file: Path to QE output file

    Returns:
        numpy array of forces, shape (n_atoms, 3), in eV/Å
    """
    forces = []

    with open(output_file, 'r') as f:
        lines = f.readlines()

    in_forces = False
    for i, line in enumerate(lines):
        if 'Forces acting on atoms' in line:
            in_forces = True
            continue

        if in_forces:
            if 'atom' in line and 'force' in line:
                # Format: atom    1 type  1   force =    -0.00000   -0.00000   -0.00000
                parts = line.split('=')[1].split()
                fx, fy, fz = float(parts[0]), float(parts[1]), float(parts[2])
                forces.append([fx, fy, fz])
            elif 'Total force' in line:
                break

    forces = np.array(forces)

    # QE outputs forces in Ry/Bohr, convert to eV/Å
    # 1 Ry/Bohr = 25.71104 eV/Å
    forces *= 25.71104

    logging.info(f"Parsed {len(forces)} atomic forces from {output_file}")
    return forces


# Module initialization
if __name__ == "__main__":
    print("Quantum ESPRESSO Utilities Library")
    print(f"Available cores: {NUM_CORES}")
    print(f"Pseudopotential directory: {PSEUDO_DIR}")
    print("\nAvailable functions:")
    print("  Setup: quick_setup, quick_finish, copy_input_files, copy_outputs")
    print("  Execution: run_command, run_qe_adaptive")
    print("  Pseudopotentials: check_pseudopotentials, list_pseudopotentials")
    print("  Parsing: parse_qe_output, parse_scf_convergence, parse_bands, parse_dos, parse_phonon_output")
    print("  Structure: get_elements_from_input")
    print("  Results: save_final_results")
    print("  Plotting: plot_scf_convergence, plot_bands, plot_dos")
    print("\n  === NEW ADVANCED FUNCTIONS ===")
    print("  EOS: fit_equation_of_state, plot_equation_of_state")
    print("  Elastic: generate_strain_patterns, apply_strain_to_structure,")
    print("           parse_stress_tensor, compute_elastic_tensor")
    print("  Convergence: generate_convergence_inputs, analyze_convergence, plot_convergence")
    print("  Effective mass: extract_effective_mass, find_band_extrema")
    print("  Phonopy: create_phonopy_supercell, compute_phonons_from_forces,")
    print("           calculate_phonon_dispersion, calculate_phonon_dos,")
    print("           calculate_thermal_properties, parse_qe_forces")
