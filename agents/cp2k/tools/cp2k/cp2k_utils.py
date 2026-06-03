#!/usr/bin/env python3
"""CP2K utilities library for the Microsoft Discovery platform.

Provides setup, execution, input generation, output parsing, analysis,
and visualization functions for CP2K atomistic simulations including
DFT (GPW/GAPW), geometry optimization, molecular dynamics, vibrational
analysis, band structure, and nudged elastic band calculations.
"""

import os
import sys
import glob
import json
import logging
import subprocess
import shutil
import re
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

# =============================================================================
# CONSTANTS (defaults — overridden by quick_setup params)
# =============================================================================
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/app/workdir"
SCRATCH_DIR = "/tmp/cp2k_scratch"

# CP2K data directory (basis sets, pseudopotentials)
# conda-forge installs to $CONDA_PREFIX/share/cp2k/data/
CP2K_DATA_DIR = os.environ.get(
    "CP2K_DATA_DIR",
    os.path.join(os.environ.get("CONDA_PREFIX", "/opt/conda/envs/cp2kenv"), "share", "cp2k", "data"),
)

# CP2K executable
CP2K_EXE = os.environ.get("CP2K_EXE", "cp2k.ssmp")

# Unit conversions
HARTREE_TO_EV = 27.211386245988
BOHR_TO_ANGSTROM = 0.529177210903
ANGSTROM_TO_BOHR = 1.0 / BOHR_TO_ANGSTROM
RY_TO_EV = 13.605693122994
EV_TO_KJ_MOL = 96.4853329
HARTREE_TO_KJ_MOL = HARTREE_TO_EV * EV_TO_KJ_MOL
HARTREE_TO_KCAL = 627.5094740631

# Common basis sets available in CP2K data directory
COMMON_BASIS_SETS = {
    "SZV-GTH": "Single-zeta valence (minimal, fast)",
    "DZVP-GTH": "Double-zeta valence polarized (standard)",
    "TZVP-GTH": "Triple-zeta valence polarized (accurate)",
    "TZV2P-GTH": "Triple-zeta with 2 polarization (high accuracy)",
    "QZV2P-GTH": "Quadruple-zeta (benchmark)",
    "DZVP-MOLOPT-SR-GTH": "MOLOPT short-range (condensed phase)",
    "TZVP-MOLOPT-GTH": "MOLOPT triple-zeta (recommended for solids)",
    "TZV2P-MOLOPT-GTH": "MOLOPT TZ2P (high accuracy solids)",
}

# Common GTH pseudopotentials
COMMON_POTENTIALS = {
    "GTH-PBE": "PBE functional pseudopotentials",
    "GTH-BLYP": "BLYP functional pseudopotentials",
    "GTH-BP": "BP86 functional pseudopotentials",
    "GTH-PADE": "LDA (Pade) pseudopotentials",
    "GTH-HF": "Hartree-Fock pseudopotentials (for hybrid DFT)",
}

HYBRID_FUNCTIONALS = {"B3LYP", "PBE0", "HSE06", "HSE"}

# Transition metal elements (3d, 4d, 5d blocks) — used for auto-hardening
# open-shell SCF settings. These elements have partially filled d-orbitals that
# make UKS SCF convergence significantly harder, especially on surfaces.
_TRANSITION_METALS = {
    # 3d
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    # 4d
    "Y", "Zr", "Nb", "Mo", "Ru", "Rh", "Pd", "Ag", "Cd",
    # 5d
    "La", "W", "Pt", "Au",
}

# =============================================================================
# SETUP FUNCTIONS
# =============================================================================


def quick_setup(
    input_dir: str = "/input",
    output_dir: str = "/output",
    work_dir: str = "/app/workdir",
) -> None:
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.

    Args:
        input_dir: Directory containing input files (mounted by platform).
        output_dir: Directory for output files (persisted by platform).
        work_dir: Working directory for calculations.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)

    os.chdir(WORK_DIR)
    _copy_input_files()

    # Auto-configure OpenMP parallelization for maximum performance
    optimal_threads = _get_optimal_threads()
    os.environ.setdefault("OMP_NUM_THREADS", str(optimal_threads))
    os.environ.setdefault("OMP_STACKSIZE", "512m")
    active_threads = os.environ.get("OMP_NUM_THREADS", str(optimal_threads))

    logging.info(f"CP2K utilities initialized")
    logging.info(f"  Working directory : {WORK_DIR}")
    logging.info(f"  Input directory   : {INPUT_DIR}")
    logging.info(f"  Output directory  : {OUTPUT_DIR}")
    logging.info(f"  CP2K data         : {CP2K_DATA_DIR}")
    logging.info(f"  CP2K executable   : {CP2K_EXE}")
    logging.info(f"  Available CPUs    : {os.cpu_count()}")
    logging.info(f"  OMP_NUM_THREADS   : {active_threads}")
    logging.info(f"  Files in workdir  : {os.listdir('.')}")


def _copy_input_files() -> None:
    """Copy input files to working directory (with same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy2(f, WORK_DIR)
            elif os.path.isdir(f):
                dest = os.path.join(WORK_DIR, os.path.basename(f))
                if not os.path.exists(dest):
                    shutil.copytree(f, dest)


def copy_outputs(
    patterns: Optional[List[str]] = None,
) -> None:
    """Copy output files to output directory.

    Args:
        patterns: Glob patterns to match. Defaults to common output types.
    """
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    if patterns is None:
        patterns = [
            "*.out", "*.log", "*.dat", "*.png", "*.json", "*.csv",
            "*.xyz", "*.cube", "*.pdos", "*.ener", "*.cell", "*.stress",
            "*.restart", "*.bs",
            # Wavefunction and restart files for calculation chaining/recovery
            "*.wfn", "*.kp", "*.bak",
            # Trajectory files for MD postprocessing
            "*-pos-*.xyz", "*-frc-*.xyz", "*-vel-*.xyz",
        ]
    copied = 0
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            if os.path.isfile(f):
                shutil.copy2(f, OUTPUT_DIR)
                copied += 1
    logging.info(f"Copied {copied} output files to {OUTPUT_DIR}")


def quick_finish() -> None:
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(
    results: Dict,
    output_files: Optional[Dict] = None,
    file_descriptions: Optional[Dict] = None,
    status: str = "completed",
) -> None:
    """Save final results to JSON file (MANDATORY for every script).

    Args:
        results: Dictionary of results/summary.
        output_files: Mapping of name -> file path for output files.
        file_descriptions: Mapping of name -> description for output files.
        status: Overall status string.
    """
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions

    out_path = os.path.join(OUTPUT_DIR, "final_results.json")
    with open(out_path, "w") as f:
        json.dump(final_data, f, indent=2, default=_json_serializer)
    logging.info(f"Saved final_results.json to {out_path}")


def _json_serializer(obj: Any) -> Any:
    """JSON serializer for non-standard types."""
    import numpy as np

    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, complex):
        return {"real": obj.real, "imag": obj.imag}
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# =============================================================================
# EXECUTION FUNCTIONS
# =============================================================================


def run_command(
    cmd: Union[str, List[str]],
    input_text: Optional[str] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict] = None,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Execute a shell command with proper error handling.

    Args:
        cmd: Command as a string (shell-parsed via shlex) or list of args.
        input_text: Optional stdin text.
        cwd: Working directory (default: current).
        env: Environment variables (merged with os.environ).
        timeout: Timeout in seconds.

    Returns:
        CompletedProcess with stdout/stderr.

    Raises:
        subprocess.CalledProcessError: If the command returns non-zero exit.
    """
    import shlex

    if isinstance(cmd, str):
        cmd = shlex.split(cmd)

    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    cmd_preview = ' '.join(cmd[:5]) + ('...' if len(cmd) > 5 else '')
    logging.info(f"Running: {cmd_preview}")
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            check=True,
            capture_output=True,
            cwd=cwd or WORK_DIR,
            env=run_env,
            timeout=timeout,
        )
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed (exit {e.returncode}): {cmd_preview}")
        if e.stderr:
            logging.error(f"STDERR (last 2000 chars):\n{e.stderr[-2000:]}")
        raise
    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout}s: {cmd_preview}")
        raise


def run_cp2k(
    input_file: str,
    output_file: Optional[str] = None,
    nthreads: Optional[int] = None,
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Run CP2K with optimal OpenMP parallelization.

    Unlike run_command() which raises on non-zero exit, this function
    always returns a CompletedProcess so callers can check .returncode.

    Args:
        input_file: CP2K input file name (must be in cwd or WORK_DIR).
        output_file: Output file name. If None, derived from input_file.
        nthreads: Number of OpenMP threads. Auto-detected if None.
        cwd: Working directory.
        timeout: Timeout in seconds.

    Returns:
        CompletedProcess with .returncode, .stdout, .stderr.
        Check result.returncode == 0 for success.
    """
    if output_file is None:
        base = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f"{base}.out"

    if nthreads is None:
        nthreads = _get_optimal_threads()

    # Auto-detect available CP2K executable
    cp2k_exe = CP2K_EXE
    if not shutil.which(cp2k_exe):
        # Fallback chain: psmp -> ssmp -> popt -> sopt
        for fallback in ["cp2k.psmp", "cp2k.ssmp", "cp2k.popt", "cp2k.sopt", "cp2k"]:
            if shutil.which(fallback):
                logging.warning(f"  {cp2k_exe} not found, falling back to {fallback}")
                cp2k_exe = fallback
                break

    run_env = dict(os.environ)
    run_env.update({
        "OMP_NUM_THREADS": str(nthreads),
        "OMP_STACKSIZE": "512m",
        "CP2K_DATA_DIR": CP2K_DATA_DIR,
    })

    cmd = [cp2k_exe, "-i", input_file, "-o", output_file]
    logging.info(f"Running CP2K: {input_file} -> {output_file} (exe={cp2k_exe}, threads={nthreads})")

    try:
        result = subprocess.run(
            cmd,
            text=True,
            check=False,
            capture_output=True,
            cwd=cwd or WORK_DIR,
            env=run_env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logging.error(f"CP2K timed out after {timeout}s: {input_file}")
        raise

    if result.returncode != 0:
        logging.error(f"CP2K failed (exit {result.returncode}): {input_file}")
        if result.stderr:
            logging.error(f"STDERR (last 2000 chars):\n{result.stderr[-2000:]}")
    else:
        logging.info(f"CP2K completed successfully: {input_file}")

    # Also check that output file was created
    out_path = os.path.join(cwd or WORK_DIR, output_file)
    if os.path.exists(out_path):
        logging.info(f"CP2K output written to {output_file}")
    else:
        logging.warning(f"CP2K ran but output file {output_file} not found")

    return result


def _get_optimal_threads() -> int:
    """Determine optimal number of OpenMP threads."""
    try:
        ncpu = os.cpu_count() or 1
        # Reserve 1 core for system, use rest for CP2K
        return max(1, ncpu - 1)
    except Exception:
        return 1


def _get_mpi_omp_split(nprocs: int = -1) -> Tuple[int, int]:
    """Compute optimal MPI ranks x OMP threads split.

    Strategy: target 4 OMP threads per rank — the sweet spot for CP2K's
    DBCSR library.  On a 96-core node this gives 24 ranks × 4 threads,
    which benchmarks show is optimal (12.7× speedup vs single-thread).

    The CMA bus error that previously required a 24-rank cap is now fixed
    via OMPI_MCA_btl_vader_single_copy_mechanism=none in run_cp2k_mpi(),
    so the cap has been removed to support large HPC SKUs (e.g. HBv4 176 cores).

    Args:
        nprocs: Number of MPI ranks. -1 for auto-detect.

    Returns:
        Tuple of (nranks, nthreads_per_rank).
    """
    ncpu = os.cpu_count() or 1
    usable = max(1, ncpu - 1)  # reserve 1 core for system

    if nprocs == -1:
        # Auto: target 4 threads per rank (optimal for CP2K DBCSR)
        # Fall back to 2 threads if very few cores available
        target_threads = 4 if usable >= 8 else 2
        nranks = max(1, usable // target_threads)
    elif nprocs == 0 or nprocs == 1:
        nranks = 1
    else:
        nranks = min(nprocs, usable)

    nthreads = max(1, usable // nranks)
    logging.info(
        f"MPI/OMP split: {nranks} ranks x {nthreads} threads "
        f"= {nranks * nthreads} cores (of {ncpu} available)"
    )
    return nranks, nthreads


def run_cp2k_mpi(
    input_file: str,
    output_file: Optional[str] = None,
    nprocs: int = -1,
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Run CP2K with MPI + OpenMP hybrid parallelization.

    Uses cp2k.psmp (MPI+SMP) if available, falls back to cp2k.ssmp (OMP only).

    Args:
        input_file: CP2K input file name.
        output_file: Output file name. Auto-derived if None.
        nprocs: Number of MPI ranks. -1 for auto-detect.
        cwd: Working directory.
        timeout: Timeout in seconds.

    Returns:
        CompletedProcess with .returncode, .stdout, .stderr.
    """
    if output_file is None:
        base = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f"{base}.out"

    nranks, nthreads = _get_mpi_omp_split(nprocs)

    # Detect available CP2K executable: prefer psmp (MPI+OMP) over ssmp (OMP only)
    cp2k_exe = CP2K_EXE
    for candidate in ["cp2k.psmp", "cp2k.popt"]:
        if shutil.which(candidate):
            cp2k_exe = candidate
            break

    run_env = dict(os.environ)
    run_env.update({
        "OMP_NUM_THREADS": str(nthreads),
        "OMP_STACKSIZE": "512m",
        "CP2K_DATA_DIR": CP2K_DATA_DIR,
        # Disable CMA shared memory to prevent bus errors in containers
        # (kernel ptrace_scope blocks cross-process memory access)
        "OMPI_MCA_btl_vader_single_copy_mechanism": "none",
    })

    if nranks > 1 and cp2k_exe in ("cp2k.psmp", "cp2k.popt"):
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec") or "mpirun"
        # Container-safe MPI launch: use --bind-to none and --oversubscribe.
        # OpenMPI 5.x (PRTE) in containers lacks hwloc topology visibility,
        # so any affinity-based binding (--bind-to core, --map-by socket:PE=N)
        # fails with "more cpus than available" or "PE cannot combine with
        # bind-to none" errors.  Dropping all binding/mapping directives and
        # relying on OMP_NUM_THREADS for thread control is the only robust
        # strategy in cgroup-constrained environments.
        cmd = [mpirun, "-np", str(nranks),
               "--bind-to", "none",
               "--oversubscribe",
               "--allow-run-as-root",
               cp2k_exe, "-i", input_file, "-o", output_file]
    else:
        if nranks > 1:
            logging.warning(
                f"MPI requested ({nranks} ranks) but only {cp2k_exe} available. "
                f"Using OMP only."
            )
            nthreads = max(1, (os.cpu_count() or 1) - 1)
            run_env["OMP_NUM_THREADS"] = str(nthreads)
        cmd = [cp2k_exe, "-i", input_file, "-o", output_file]

    logging.info(f"Running CP2K: {' '.join(cmd)} (MPI={nranks}, OMP={nthreads})")

    try:
        result = subprocess.run(
            cmd, text=True, check=False, capture_output=True,
            cwd=cwd or WORK_DIR, env=run_env, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logging.error(f"CP2K timed out after {timeout}s: {input_file}")
        raise

    if result.returncode != 0:
        logging.error(f"CP2K MPI failed (exit {result.returncode}): {input_file}")
        if result.stderr:
            logging.error(f"STDERR (last 2000 chars):\n{result.stderr[-2000:]}")
    else:
        logging.info(f"CP2K MPI completed successfully: {input_file}")

    out_path = os.path.join(cwd or WORK_DIR, output_file)
    if os.path.exists(out_path):
        logging.info(f"CP2K output written to {output_file}")
    else:
        logging.warning(f"CP2K ran but output file {output_file} not found")

    return result


def generate_restart_input(
    original_input_file: str,
    restart_file: str,
    project_name: Optional[str] = None,
    run_type: Optional[str] = None,
    extra_modifications: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a CP2K input file that restarts from a previous calculation.

    Modifies the original input to use SCF_GUESS RESTART and point to the
    wavefunction restart file.  Useful for continuing crashed calculations
    or chaining calculations (e.g., GEO_OPT -> VIBRATIONAL_ANALYSIS).

    Args:
        original_input_file: Path to the original CP2K input file.
        restart_file: Path to the .wfn or .restart file from previous run.
        project_name: Override project name (optional).
        run_type: Override RUN_TYPE (e.g., 'VIBRATIONAL_ANALYSIS') (optional).
        extra_modifications: Dict of keyword -> value modifications (optional).

    Returns:
        Modified CP2K input content as string.
    """
    with open(original_input_file) as f:
        content = f.read()

    # Replace SCF_GUESS ATOMIC with SCF_GUESS RESTART
    content = re.sub(
        r"SCF_GUESS\s+\w+",
        "SCF_GUESS RESTART",
        content,
    )

    # Add WFN_RESTART_FILE_NAME if not present
    if "WFN_RESTART_FILE_NAME" not in content:
        content = content.replace(
            "SCF_GUESS RESTART",
            f"SCF_GUESS RESTART\n      WFN_RESTART_FILE_NAME {restart_file}",
        )
    else:
        content = re.sub(
            r"WFN_RESTART_FILE_NAME\s+\S+",
            f"WFN_RESTART_FILE_NAME {restart_file}",
            content,
        )

    # Override project name if requested
    if project_name:
        content = re.sub(
            r"PROJECT\s+\S+",
            f"PROJECT {project_name}",
            content,
        )

    # Override RUN_TYPE if requested (e.g., for GEO_OPT -> VIBRATIONAL_ANALYSIS chain)
    if run_type:
        content = re.sub(
            r"RUN_TYPE\s+\S+",
            f"RUN_TYPE {run_type}",
            content,
        )

    # Apply extra modifications
    if extra_modifications:
        for key, value in extra_modifications.items():
            pattern = rf"{re.escape(key)}\s+\S+"
            replacement = f"{key} {value}"
            content = re.sub(pattern, replacement, content)

    logging.info(f"Generated restart input from {original_input_file}")
    logging.info(f"  WFN restart file: {restart_file}")
    return content


def find_restart_files(
    project_name: str,
    search_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Find CP2K restart files from a previous calculation.

    Args:
        project_name: CP2K project name.
        search_dir: Directory to search (default: WORK_DIR).

    Returns:
        Dict with paths to found restart files:
        - wfn: Wavefunction file (.wfn)
        - restart: Full restart file (.restart)
        - kp_wfn: K-point wavefunction files (list)
    """
    search = search_dir or WORK_DIR
    result: Dict[str, Any] = {"wfn": None, "restart": None, "kp_wfn": []}

    # Look for wavefunction files
    wfn_patterns = [
        f"{project_name}-RESTART.wfn",
        f"{project_name}-RESTART.kp",
        f"{project_name}.wfn",
    ]
    for pat in wfn_patterns:
        path = os.path.join(search, pat)
        if os.path.isfile(path):
            result["wfn"] = path
            break

    # Look for .restart file
    restart_path = os.path.join(search, f"{project_name}-1.restart")
    if os.path.isfile(restart_path):
        result["restart"] = restart_path

    # K-point wavefunction files
    kp_pattern = os.path.join(search, f"{project_name}-RESTART.wfn.kp-*")
    result["kp_wfn"] = sorted(glob.glob(kp_pattern))

    found = {k: v for k, v in result.items() if v}
    if found:
        logging.info(f"Found restart files for '{project_name}': {list(found.keys())}")
    else:
        logging.warning(f"No restart files found for '{project_name}' in {search}")

    return result


# =============================================================================
# INPUT FILE GENERATION
# =============================================================================


def generate_input(
    project_name: str,
    run_type: str,
    structure: Dict,
    dft_params: Optional[Dict] = None,
    md_params: Optional[Dict] = None,
    geo_opt_params: Optional[Dict] = None,
    cell_opt_params: Optional[Dict] = None,
    vib_params: Optional[Dict] = None,
    band_structure_params: Optional[Dict] = None,
    neb_params: Optional[Dict] = None,
    print_forces: bool = True,
    print_stress: bool = False,
    extra_sections: Optional[str] = None,
) -> str:
    """Generate a CP2K input file.

    Args:
        project_name: Project name (used for output file prefixes).
        run_type: One of ENERGY, ENERGY_FORCE, GEO_OPT, CELL_OPT, MD,
                  VIBRATIONAL_ANALYSIS, BAND, NEB.
        structure: Dict with keys:
            - coords: List of [symbol, x, y, z] or XYZ string
            - cell: [a, b, c] or [[ax,ay,az],[bx,by,bz],[cx,cy,cz]]
            - coord_type: 'CARTESIAN' (default) or 'SCALED'
            - periodic: 'XYZ' (default), 'XY', 'X', 'NONE'
            - charge: System charge (default 0)
            - multiplicity: Spin multiplicity (default 1)
        dft_params: Dict with keys (all optional):
            - functional: XC functional (default 'PBE')
            - basis_set: Basis set name (default 'DZVP-MOLOPT-SR-GTH')
            - potential: Pseudopotential family (default 'GTH-PBE')
            - cutoff: PW cutoff in Ry (default 300)
            - rel_cutoff: Relative cutoff in Ry (default 60)
            - scf_convergence: SCF convergence criterion (default 1.0E-6)
            - max_scf: Max SCF iterations (default 50)
            - added_mos: Number of added empty MOs (default 0)
            - smearing: Enable smearing (default False)
            - smearing_method: 'FERMI_DIRAC' or 'GAUSSIAN' (default 'FERMI_DIRAC')
            - electronic_temperature: Temperature for smearing in K (default 300)
            - uks: Unrestricted Kohn-Sham (default False)
            - dispersion: Dispersion correction 'D3', 'D3BJ', 'D4', 'DFTD3', 'DFTD4' (default None)
            - basis_set_file: Basis set file name (default 'BASIS_MOLOPT')
            - potential_file: Potential file name (default 'GTH_POTENTIALS')
            - kpoints: [n1, n2, n3] for Monkhorst-Pack grid (default None = Gamma)
            - scf_method: 'OT', 'DIAGONALIZATION', or 'AUTO' (default 'AUTO')
            - ot_minimizer: OT minimizer: 'DIIS' (default), 'CG', 'BROYDEN'
            - ot_preconditioner: 'FULL_SINGLE_INVERSE' (default), 'FULL_ALL',
                                'FULL_KINETIC', 'NONE'
            - ot_energygap: Estimated HOMO-LUMO gap in Hartree (default 0.08)
            - ot_linesearch: OT linesearch: '2PNT', '3PNT', 'GOLD' (optional)
            - outer_scf: Enable outer SCF loop (default True for OT, False for diag)
            - outer_max_scf: Max outer SCF iterations (default 20)
            - outer_eps_scf: Outer SCF convergence (default same as scf_convergence)
            - level_shift: Level shift in eV for difficult SCF (default None)
            - mixing_method: Mixing method (default 'BROYDEN_MIXING')
            - mixing_alpha: Mixing alpha parameter (default 0.4)
            - mixing_nbroyden: Broyden mixing history (default 8)
            - admm: Enable ADMM for faster hybrid DFT (default False)
            - admm_method: ADMM method (default 'BASIS_PROJECTION')
            - admm_purification: ADMM purification (default 'MO_DIAG')
            - roks: Restricted Open-Shell KS (default False)
        md_params: Dict for MD (ensemble, timestep, steps, temperature, etc.)
        geo_opt_params: Dict for geometry optimization parameters.
        cell_opt_params: Dict for cell optimization parameters.
        vib_params: Dict for vibrational analysis parameters.
        band_structure_params: Dict with 'path' as list of [label, n_points, kx, ky, kz].
        print_forces: Print forces (default True).
        print_stress: Print stress tensor (default False).
        neb_params: Dict for NEB (n_images, spring, reactant_file, product_file, etc.)
        extra_sections: Raw CP2K input text to append.

    Returns:
        CP2K input file content as a string.
    """
    dft = dft_params or {}
    functional = dft.get("functional", "PBE")
    basis_set = dft.get("basis_set", "DZVP-MOLOPT-SR-GTH")
    potential = dft.get("potential", "GTH-PBE")
    cutoff = dft.get("cutoff", 300)
    rel_cutoff = dft.get("rel_cutoff", 60)
    scf_conv = dft.get("scf_convergence", "1.0E-6")
    max_scf = dft.get("max_scf", 50)
    added_mos = dft.get("added_mos", 0)
    smearing = dft.get("smearing", False)
    uks = dft.get("uks", False)
    dispersion = dft.get("dispersion", None)
    basis_file = dft.get("basis_set_file", "BASIS_MOLOPT")
    pot_file = dft.get("potential_file", "GTH_POTENTIALS")
    kpoints = dft.get("kpoints", None)

    charge = structure.get("charge", 0)
    multiplicity = structure.get("multiplicity", 1)
    periodic = structure.get("periodic", "XYZ")
    coord_type = structure.get("coord_type", "CARTESIAN")

    if functional.upper() in HYBRID_FUNCTIONALS:
        raise ValueError(
            f"Functional '{functional}' requires libint/HFX support, which is disabled "
            "in the current CP2K v19 image. Use a GGA functional such as PBE/BLYP/BP86/PADE "
            "with optional D3/D4 dispersion."
        )

    # ── CELL_OPT always requires stress tensor ───────────────────────────
    if run_type == "CELL_OPT":
        print_stress = True

    # ── Validate electron count vs multiplicity ──────────────────────────
    # Compute total valence electrons to detect odd-electron / open-shell
    # issues before CP2K fails with a cryptic SIGABRT.
    coords = structure.get("coords", [])
    _elements = []
    if isinstance(coords, str):
        for _line in coords.strip().split("\n"):
            _parts = _line.split()
            if len(_parts) >= 4:
                _elements.append(_parts[0])
    else:
        for _atom in coords:
            if _atom:
                _elements.append(_atom[0])

    total_valence = sum(_get_valence_electrons(e, potential) for e in _elements) - charge
    electron_parity_odd = (total_valence % 2) != 0
    mult_requires_odd = (multiplicity % 2) == 0  # even multiplicity ↔ odd electrons

    if electron_parity_odd and multiplicity == 1:
        logging.warning(
            f"  Odd number of valence electrons ({total_valence}) with multiplicity=1. "
            f"Auto-enabling UKS with multiplicity=2. Set structure['multiplicity']=1 "
            f"and dft_params['uks']=True explicitly if you want a different configuration."
        )
        multiplicity = 2
        uks = True
    elif electron_parity_odd and not mult_requires_odd:
        logging.warning(
            f"  Odd valence electrons ({total_valence}) but even multiplicity ({multiplicity}). "
            f"This is physically inconsistent — CP2K will likely fail."
        )
    elif not electron_parity_odd and mult_requires_odd:
        logging.warning(
            f"  Even valence electrons ({total_valence}) but odd multiplicity ({multiplicity}). "
            f"This is physically inconsistent — CP2K will likely fail."
        )

    # ── Smart defaults for open-shell transition metal systems ───────────
    # When UKS is active (explicitly or auto-enabled) AND the system contains
    # transition metals, apply conservative SCF settings unless the user has
    # explicitly overridden them.  Late 3d (Co, Ni, Cu) and 5d (Pt, Au)
    # metals are especially prone to SCF oscillation with default Broyden
    # mixing (alpha=0.4) because of near-degenerate d-orbital manifolds.
    #
    # The hardened defaults are:
    #   - smearing ON (Fermi-Dirac, 300 K) for fractional occupation
    #   - added_mos >= 20 for adequate virtual orbital space
    #   - mixing_alpha = 0.1 (gentler density mixing)
    #   - level_shift = 0.1 eV (stabilize occupied/virtual gap)
    #
    # These are only applied when the user did NOT explicitly set these params,
    # so expert users can still override with their own values.
    _unique_elements = set(_elements)
    _has_tm = bool(_unique_elements & _TRANSITION_METALS)

    if (uks or multiplicity != 1) and _has_tm:
        _tm_found = sorted(_unique_elements & _TRANSITION_METALS)
        _hardened = []

        # (a) Enable smearing if not explicitly set by user
        if "smearing" not in dft:
            smearing = True
            dft["smearing"] = True
            _hardened.append("smearing=True (Fermi-Dirac 300K)")

        # (b) Increase added_mos if user didn't set it or set it too low
        if "added_mos" not in dft or dft.get("added_mos", 0) < 20:
            added_mos = 20
            _hardened.append("added_mos=20")

        # (c) Lower mixing_alpha for gentler convergence
        if "mixing_alpha" not in dft:
            dft["mixing_alpha"] = 0.1
            _hardened.append("mixing_alpha=0.1")

        # (d) Add level shift to stabilize open-shell SCF
        if "level_shift" not in dft:
            dft["level_shift"] = 0.1
            _hardened.append("level_shift=0.1 eV")

        if _hardened:
            logging.info(
                f"  Open-shell transition metal system detected ({', '.join(_tm_found)}). "
                f"Auto-hardened SCF settings: {'; '.join(_hardened)}. "
                f"Override by setting these explicitly in dft_params."
            )

    lines = []

    # GLOBAL section
    lines.append("&GLOBAL")
    lines.append(f"  PROJECT {project_name}")
    lines.append(f"  RUN_TYPE {run_type}")
    lines.append("  PRINT_LEVEL MEDIUM")
    lines.append("&END GLOBAL")
    lines.append("")

    # FORCE_EVAL section
    lines.append("&FORCE_EVAL")
    lines.append("  METHOD Quickstep")
    # STRESS_TENSOR at the &FORCE_EVAL level activates stress computation.
    # Required for CELL_OPT (BFGS optimizer needs stress gradients) and
    # whenever print_stress is requested (otherwise PRINT > STRESS_TENSOR
    # produces no output).  ANALYTICAL is the standard for GPW/GAPW DFT.
    if run_type == "CELL_OPT" or print_stress:
        lines.append("  STRESS_TENSOR ANALYTICAL")
    # Resolve ADMM early — needed for BASIS_SET_FILE_NAME and KIND sections
    admm = dft.get("admm", False)
    admm_functionals = {"B3LYP", "PBE0", "HSE06", "HSE"}
    admm_active = admm and functional.upper() in admm_functionals
    admm_basis = dft.get("admm_basis", "cFIT3")
    admm_basis_file = dft.get("admm_basis_file", "BASIS_ADMM_MOLOPT")

    # DFT subsection
    lines.append("  &DFT")
    lines.append(f"    BASIS_SET_FILE_NAME {basis_file}")
    if admm_active:
        lines.append(f"    BASIS_SET_FILE_NAME {admm_basis_file}")
    lines.append(f"    POTENTIAL_FILE_NAME {pot_file}")
    lines.append(f"    CHARGE {charge}")
    if multiplicity != 1:
        lines.append(f"    MULTIPLICITY {multiplicity}")
    roks = dft.get("roks", False)
    if roks and multiplicity != 1:
        lines.append("    ROKS .TRUE.")
        logging.info("  Using ROKS (Restricted Open-Shell Kohn-Sham)")
    elif uks or multiplicity != 1:
        lines.append("    UKS .TRUE.")

    # QS
    lines.append("    &QS")
    lines.append("      EPS_DEFAULT 1.0E-12")
    lines.append("    &END QS")

    # MGRID
    lines.append("    &MGRID")
    lines.append(f"      CUTOFF {cutoff}")
    lines.append(f"      REL_CUTOFF {rel_cutoff}")
    lines.append("      NGRIDS 5")
    lines.append("    &END MGRID")

    # SCF - supports OT (Orbital Transformation) and Diagonalization methods
    scf_method = dft.get("scf_method", "AUTO").upper()
    ot_minimizer = dft.get("ot_minimizer", "DIIS")
    ot_preconditioner = dft.get("ot_preconditioner", "FULL_SINGLE_INVERSE")
    ot_energygap = dft.get("ot_energygap", 0.08)
    outer_scf = dft.get("outer_scf", None)  # None = auto, True/False = explicit
    level_shift = dft.get("level_shift", None)  # F7: eV, applied during SCF

    # AUTO SCF method selection:
    #   Metals/smearing -> DIAGONALIZATION (OT incompatible with fractional occupation)
    #   Open-shell UKS  -> DIAGONALIZATION (OT can struggle with UKS)
    #   Gapped systems  -> OT (2-5x faster, better MPI scaling)
    # K-points force DIAGONALIZATION — OT is incompatible with k-point sampling.
    # CP2K aborts: "OT not possible with kpoint calculations" (qs_scf_initialization.F:833)
    if kpoints and scf_method == "OT":
        logging.warning(
            "  K-points requested with SCF method OT — switching to DIAGONALIZATION. "
            "OT is incompatible with k-point sampling in CP2K."
        )
        scf_method = "DIAGONALIZATION"

    if scf_method == "AUTO":
        if smearing or uks or multiplicity != 1 or kpoints:
            scf_method = "DIAGONALIZATION"
        else:
            scf_method = "OT"
        logging.info(f"  Auto-selected SCF method: {scf_method}")

    logging.info(f"  DFT parameters: functional={functional}, basis={basis_set}, "
                 f"cutoff={cutoff} Ry, rel_cutoff={rel_cutoff} Ry, SCF={scf_method}")

    lines.append("    &SCF")
    lines.append(f"      SCF_GUESS ATOMIC")
    lines.append(f"      EPS_SCF {scf_conv}")
    lines.append(f"      MAX_SCF {max_scf}")

    # UKS calculations need virtual orbitals; auto-add if user didn't specify
    effective_mos = added_mos
    if (uks or multiplicity != 1) and added_mos == 0:
        effective_mos = 10
    if effective_mos > 0:
        lines.append(f"      ADDED_MOS {effective_mos}")

    # F7: Level shift for difficult SCF convergence
    if level_shift is not None:
        lines.append(f"      LEVEL_SHIFT [eV] {level_shift}")

    if smearing:
        sm_method = dft.get("smearing_method", "FERMI_DIRAC")
        el_temp = dft.get("electronic_temperature", 300)
        lines.append("      &SMEAR ON")
        lines.append(f"        METHOD {sm_method}")
        lines.append(f"        ELECTRONIC_TEMPERATURE [K] {el_temp}")
        lines.append("      &END SMEAR")
    elif (uks or multiplicity != 1) and not smearing:
        # NOTE: No implicit smearing for open-shell molecular systems.
        # Smearing (fractional occupation) is appropriate for metals but
        # introduces unphysical electron distribution in molecular radicals.
        # Users who need smearing for metallic/near-degenerate systems should
        # set dft_params['smearing'] = True explicitly.
        logging.info(
            "  Open-shell system detected (UKS/multiplicity>1) without smearing. "
            "Using integer occupation. Set dft_params['smearing']=True for metals."
        )

    # F1-F3: OT vs Diagonalization
    if scf_method == "OT":
        lines.append("      &OT ON")
        lines.append(f"        MINIMIZER {ot_minimizer}")
        lines.append(f"        PRECONDITIONER {ot_preconditioner}")
        lines.append(f"        ENERGY_GAP {ot_energygap}")
        if dft.get("ot_linesearch"):
            lines.append(f"        LINESEARCH {dft['ot_linesearch']}")
        lines.append("      &END OT")
        # F3: Outer SCF - wraps inner SCF with preconditioner updates
        use_outer_scf = outer_scf if outer_scf is not None else True
        if use_outer_scf:
            outer_max = dft.get("outer_max_scf", 20)
            outer_eps = dft.get("outer_eps_scf", scf_conv)
            lines.append("      &OUTER_SCF")
            lines.append(f"        MAX_SCF {outer_max}")
            lines.append(f"        EPS_SCF {outer_eps}")
            lines.append("      &END OUTER_SCF")
    else:
        lines.append("      &DIAGONALIZATION")
        lines.append("        ALGORITHM STANDARD")
        lines.append("      &END DIAGONALIZATION")
        # F4: Configurable MIXING parameters
        mix_method = dft.get("mixing_method", "BROYDEN_MIXING")
        mix_alpha = dft.get("mixing_alpha", 0.4)
        mix_nbroyden = dft.get("mixing_nbroyden", 8)
        lines.append("      &MIXING")
        lines.append(f"        METHOD {mix_method}")
        lines.append(f"        ALPHA {mix_alpha}")
        if "BROYDEN" in mix_method.upper():
            lines.append(f"        NBROYDEN {mix_nbroyden}")
        lines.append("      &END MIXING")

    lines.append("      &PRINT")
    lines.append("        &RESTART")
    lines.append("          BACKUP_COPIES 0")
    lines.append("        &END RESTART")
    lines.append("      &END PRINT")
    lines.append("    &END SCF")

    # XC
    lines.append("    &XC")
    _write_xc_functional(lines, functional)
    if dispersion:
        _write_dispersion(lines, dispersion, functional)
    lines.append("    &END XC")

    # ADMM — &AUXILIARY_DENSITY_MATRIX_METHOD goes under &DFT (not &XC)
    if admm_active:
        admm_method = dft.get("admm_method", "BASIS_PROJECTION")
        admm_purification = dft.get("admm_purification", "MO_DIAG")
        lines.append("    &AUXILIARY_DENSITY_MATRIX_METHOD")
        lines.append(f"      METHOD {admm_method}")
        lines.append(f"      ADMM_PURIFICATION_METHOD {admm_purification}")
        lines.append("    &END AUXILIARY_DENSITY_MATRIX_METHOD")

    # POISSON section — required for correct electrostatics with PERIODIC NONE
    if periodic.upper() == "NONE":
        lines.append("    &POISSON")
        lines.append("      PERIODIC NONE")
        lines.append("      POISSON_SOLVER WAVELET")
        lines.append("    &END POISSON")

    # KPOINTS
    if kpoints:
        lines.append("    &KPOINTS")
        lines.append("      SCHEME MONKHORST-PACK " + " ".join(str(k) for k in kpoints))
        lines.append("    &END KPOINTS")

    # PRINT sections within DFT
    if run_type == "BAND":
        _write_band_structure_section(lines, band_structure_params)

    lines.append("  &END DFT")

    # SUBSYS
    lines.append("  &SUBSYS")
    _write_cell(lines, structure)
    _write_coordinates(lines, structure, coord_type)
    _write_kinds(lines, structure, basis_set, potential,
                 admm_basis=admm_basis if admm_active else None)
    lines.append("  &END SUBSYS")

    # PRINT in FORCE_EVAL
    if print_forces:
        lines.append("  &PRINT")
        lines.append("    &FORCES ON")
        lines.append("    &END FORCES")
        if print_stress:
            lines.append("    &STRESS_TENSOR ON")
            lines.append("    &END STRESS_TENSOR")
        lines.append("  &END PRINT")

    lines.append("&END FORCE_EVAL")
    lines.append("")

    # MOTION section for GEO_OPT, CELL_OPT, MD, BAND
    if run_type in ("GEO_OPT", "CELL_OPT", "MD", "BAND", "NEB"):
        _write_motion_section(
            lines, run_type, project_name,
            geo_opt_params=geo_opt_params,
            cell_opt_params=cell_opt_params,
            md_params=md_params,
            band_structure_params=band_structure_params,
            neb_params=neb_params,
        )

    # VIBRATIONAL_ANALYSIS is a top-level section in CP2K 2024.x (NOT under MOTION)
    if run_type == "VIBRATIONAL_ANALYSIS":
        _write_vibrational_analysis_section(lines, vib_params)

    if extra_sections:
        lines.append(extra_sections)

    return "\n".join(lines)


def _write_xc_functional(lines: List[str], functional: str) -> None:
    """Write XC_FUNCTIONAL section."""
    func_upper = functional.upper()
    # Standard functionals with direct section support
    standard = {
        "PBE": "PBE",
        "BLYP": "BLYP",
        "BP86": "BP",
        "LDA": "PADE",
        "PADE": "PADE",
        "PBE0": "PBE0",
        "B3LYP": "B3LYP",
    }
    if func_upper in standard:
        lines.append(f"      &XC_FUNCTIONAL {standard[func_upper]}")
        lines.append(f"      &END XC_FUNCTIONAL")
        # Hybrid functionals (B3LYP, PBE0) require explicit &HF section
        # for exact Hartree-Fock exchange computation. Without this, CP2K
        # aborts with MPI_ABORT because HFX machinery is not initialised.
        # HSE06 is handled separately below with SHORTRANGE potential.
        hybrid_fractions = {"B3LYP": 0.20, "PBE0": 0.25}
        if func_upper in hybrid_fractions:
            frac = hybrid_fractions[func_upper]
            lines.append("      &HF")
            lines.append(f"        FRACTION {frac}")
            lines.append("        &SCREENING")
            lines.append("          EPS_SCHWARZ 1.0E-6")
            lines.append("          SCREEN_ON_INITIAL_P FALSE")
            lines.append("        &END SCREENING")
            lines.append("        &INTERACTION_POTENTIAL")
            lines.append("          POTENTIAL_TYPE TRUNCATED")
            lines.append("          CUTOFF_RADIUS 6.0")
            lines.append("          T_C_G_DATA t_c_g.dat")
            lines.append("        &END INTERACTION_POTENTIAL")
            lines.append("        &MEMORY")
            lines.append("          MAX_MEMORY 2000")
            lines.append("        &END MEMORY")
            lines.append("      &END HF")
    elif func_upper in ("HSE06", "HSE"):
        lines.append("      &XC_FUNCTIONAL")
        lines.append("        &XWPBE")
        lines.append("          SCALE_X -0.25")
        lines.append("          SCALE_X0 1.0")
        lines.append("          OMEGA 0.11")
        lines.append("        &END XWPBE")
        lines.append("        &PBE")
        lines.append("          SCALE_X 0.0")
        lines.append("          SCALE_C 1.0")
        lines.append("        &END PBE")
        lines.append("      &END XC_FUNCTIONAL")
        lines.append("      &HF")
        lines.append("        FRACTION 0.25")
        lines.append("        &SCREENING")
        lines.append("          EPS_SCHWARZ 1.0E-6")
        lines.append("          SCREEN_ON_INITIAL_P .FALSE.")
        lines.append("        &END SCREENING")
        lines.append("        &INTERACTION_POTENTIAL")
        lines.append("          POTENTIAL_TYPE SHORTRANGE")
        lines.append("          OMEGA 0.11")
        lines.append("        &END INTERACTION_POTENTIAL")
        lines.append("      &END HF")
    else:
        # Fallback: use the name as-is
        lines.append(f"      &XC_FUNCTIONAL {func_upper}")
        lines.append(f"      &END XC_FUNCTIONAL")


def _write_dispersion(lines: List[str], dispersion: str, functional: str = "PBE") -> None:
    """Write VDW_POTENTIAL section for dispersion corrections.

    Supports D3, D3(BJ), and D4 parameterizations. The REFERENCE_FUNCTIONAL
    is set automatically based on the active XC functional to ensure correct
    dispersion parameters.
    """
    disp_upper = dispersion.upper()
    # Map functional name to REFERENCE_FUNCTIONAL expected by D3/D4
    ref_func_map = {
        "PBE": "PBE", "BLYP": "BLYP", "BP86": "BP86", "B3LYP": "B3LYP",
        "PBE0": "PBE0", "HSE06": "PBE0", "HSE": "PBE0", "LDA": "PBE",
        "PADE": "PBE", "TPSS": "TPSS", "SCAN": "SCAN", "REVPBE": "revPBE",
    }
    ref_func = ref_func_map.get(functional.upper(), "PBE")

    lines.append("      &VDW_POTENTIAL")
    if disp_upper in ("D3", "DFTD3"):
        lines.append("        POTENTIAL_TYPE PAIR_POTENTIAL")
        lines.append("        &PAIR_POTENTIAL")
        lines.append("          TYPE DFTD3")
        lines.append("          PARAMETER_FILE_NAME dftd3.dat")
        lines.append(f"          REFERENCE_FUNCTIONAL {ref_func}")
        lines.append("        &END PAIR_POTENTIAL")
    elif disp_upper in ("D3BJ", "DFTD3BJ"):
        lines.append("        POTENTIAL_TYPE PAIR_POTENTIAL")
        lines.append("        &PAIR_POTENTIAL")
        lines.append("          TYPE DFTD3(BJ)")
        lines.append("          PARAMETER_FILE_NAME dftd3.dat")
        lines.append(f"          REFERENCE_FUNCTIONAL {ref_func}")
        lines.append("        &END PAIR_POTENTIAL")
    elif disp_upper in ("D4", "DFTD4"):
        lines.append("        POTENTIAL_TYPE PAIR_POTENTIAL")
        lines.append("        &PAIR_POTENTIAL")
        lines.append("          TYPE DFTD4")
        lines.append("          PARAMETER_FILE_NAME dftd4.dat")
        lines.append(f"          REFERENCE_FUNCTIONAL {ref_func}")
        lines.append("        &END PAIR_POTENTIAL")
    lines.append("      &END VDW_POTENTIAL")


def _write_cell(lines: List[str], structure: Dict) -> None:
    """Write CELL section.

    If no cell is provided, automatically generates one from the coordinate
    bounding box plus vacuum padding.  For non-periodic / molecular systems
    the default padding is 10 Å on each side; for periodic systems the user
    MUST supply an explicit cell (a warning is logged and a generous default
    is used as fallback).

    When auto-generating a cell with PERIODIC NONE, coordinates are centered
    in the box so that the WAVELET Poisson solver works correctly (it requires
    all atoms to be inside the cell).
    """
    cell = structure.get("cell")
    periodic = structure.get("periodic", "XYZ")

    # ── Auto-generate cell when not provided ──────────────────────────────
    if cell is None:
        coords = structure.get("coords", [])
        xs, ys, zs = [], [], []
        if isinstance(coords, str):
            for line in coords.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 4:
                    xs.append(float(parts[1]))
                    ys.append(float(parts[2]))
                    zs.append(float(parts[3]))
        else:
            for atom in coords:
                if len(atom) >= 4:
                    xs.append(float(atom[1]))
                    ys.append(float(atom[2]))
                    zs.append(float(atom[3]))

        if xs:
            padding = 10.0  # Angstroms of vacuum on each side
            lx = max(xs) - min(xs) + 2 * padding
            ly = max(ys) - min(ys) + 2 * padding
            lz = max(zs) - min(zs) + 2 * padding
            # Enforce a reasonable minimum cell size
            lx = max(lx, 10.0)
            ly = max(ly, 10.0)
            lz = max(lz, 10.0)

            # WAVELET Poisson solver requires a cubic cell.
            # For PERIODIC NONE, enforce cubic by using the largest dimension.
            if periodic == "NONE":
                l_max = max(lx, ly, lz)
                lx = ly = lz = l_max

            # Center coordinates in the box so all atoms are inside the cell.
            # This is essential for the WAVELET Poisson solver (PERIODIC NONE).
            mid_x = (max(xs) + min(xs)) / 2.0
            mid_y = (max(ys) + min(ys)) / 2.0
            mid_z = (max(zs) + min(zs)) / 2.0
            shift_x = lx / 2.0 - mid_x
            shift_y = ly / 2.0 - mid_y
            shift_z = lz / 2.0 - mid_z

            # Apply centering shift to coordinates in the structure dict
            if isinstance(coords, str):
                new_lines = []
                for cline in coords.strip().split("\n"):
                    parts = cline.split()
                    if len(parts) >= 4:
                        sx = float(parts[1]) + shift_x
                        sy = float(parts[2]) + shift_y
                        sz = float(parts[3]) + shift_z
                        new_lines.append(f"{parts[0]}  {sx:.10f}  {sy:.10f}  {sz:.10f}")
                    else:
                        new_lines.append(cline)
                structure["coords"] = "\n".join(new_lines)
            else:
                new_coords = []
                for atom in coords:
                    atom = list(atom)  # Convert tuple to list if needed
                    if len(atom) >= 4:
                        atom[1] = float(atom[1]) + shift_x
                        atom[2] = float(atom[2]) + shift_y
                        atom[3] = float(atom[3]) + shift_z
                    new_coords.append(atom)
                structure["coords"] = new_coords

            logging.info(f"  Centered coordinates: shift = [{shift_x:.2f}, {shift_y:.2f}, {shift_z:.2f}] Å")
        else:
            lx = ly = lz = 15.0

        cell = [lx, ly, lz]

        # If the user didn't set periodic, default to NONE for auto-generated cells
        if "periodic" not in structure:
            periodic = "NONE"

        logging.info(f"  Auto-generated cell: [{lx:.1f}, {ly:.1f}, {lz:.1f}] Å, periodic={periodic}")

    # ── Write cell vectors ────────────────────────────────────────────────
    lines.append("    &CELL")
    if isinstance(cell[0], (list, tuple)):
        # Full cell vectors
        lines.append(f"      A {cell[0][0]:.10f} {cell[0][1]:.10f} {cell[0][2]:.10f}")
        lines.append(f"      B {cell[1][0]:.10f} {cell[1][1]:.10f} {cell[1][2]:.10f}")
        lines.append(f"      C {cell[2][0]:.10f} {cell[2][1]:.10f} {cell[2][2]:.10f}")
    else:
        # Cubic / orthorhombic shorthand [a, b, c]
        lines.append(f"      A {cell[0]:.10f} 0.0 0.0")
        lines.append(f"      B 0.0 {cell[1]:.10f} 0.0")
        lines.append(f"      C 0.0 0.0 {cell[2]:.10f}")
    lines.append(f"      PERIODIC {periodic}")
    lines.append("    &END CELL")

    # NOTE: Coordinate centering for PERIODIC NONE is handled ONLY in the
    # auto-cell path above (when cell is None).  When the user supplies an
    # explicit cell, we respect their coordinate placement.  If the WAVELET
    # solver fails because atoms are outside the cell, the user should either
    # center manually or omit the cell to let auto-generation handle it.


def _write_coordinates(lines: List[str], structure: Dict, coord_type: str) -> None:
    """Write COORD section."""
    coords = structure.get("coords", [])
    lines.append("    &COORD")
    if coord_type.upper() == "SCALED":
        lines.append("      SCALED .TRUE.")
    if isinstance(coords, str):
        # Raw XYZ string
        for line in coords.strip().split("\n"):
            line = line.strip()
            if line:
                lines.append(f"      {line}")
    else:
        for atom in coords:
            if len(atom) >= 4:
                lines.append(f"      {atom[0]}  {atom[1]:.10f}  {atom[2]:.10f}  {atom[3]:.10f}")
    lines.append("    &END COORD")


def _write_kinds(
    lines: List[str], structure: Dict, basis_set: str, potential: str,
    admm_basis: Optional[str] = None,
) -> None:
    """Write KIND sections for each element.

    Supports per-element basis set and potential overrides via:
        structure['element_basis_sets'] = {'Fe': 'TZV2P-MOLOPT-GTH', ...}
        structure['element_potentials'] = {'Fe': 'GTH-PBE-q16', ...}

    Args:
        admm_basis: When set (e.g. 'cFIT3'), adds AUX_FIT_BASIS_SET to each
            KIND for ADMM hybrid DFT.
    """
    coords = structure.get("coords", [])
    elements = set()
    if isinstance(coords, str):
        for line in coords.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 4:
                elements.add(parts[0])
    else:
        for atom in coords:
            elements.add(atom[0])

    elem_basis = structure.get("element_basis_sets", {})
    elem_pot = structure.get("element_potentials", {})

    for elem in sorted(elements):
        bs = elem_basis.get(elem, basis_set)
        # If user provided full potential name (e.g., 'GTH-PBE-q16'), use as-is
        # Otherwise construct from family + valence electrons
        if elem in elem_pot:
            pot_name = elem_pot[elem]
        else:
            pot_name = f"{potential}-q{_get_valence_electrons(elem, potential)}"
        lines.append(f"    &KIND {elem}")
        lines.append(f"      BASIS_SET {bs}")
        if admm_basis:
            lines.append(f"      AUX_FIT_BASIS_SET {admm_basis}")
        lines.append(f"      POTENTIAL {pot_name}")
        lines.append(f"    &END KIND")


def _get_valence_electrons(element: str, potential: str) -> int:
    """Get number of valence electrons for GTH pseudopotentials.

    Returns the standard number of valence electrons used in GTH pseudopotentials.
    """
    # Standard GTH valence electron counts
    valence_map = {
        "H": 1, "He": 2,
        "Li": 3, "Be": 4, "B": 3, "C": 4, "N": 5, "O": 6, "F": 7, "Ne": 8,
        "Na": 9, "Mg": 10, "Al": 3, "Si": 4, "P": 5, "S": 6, "Cl": 7, "Ar": 8,
        "K": 9, "Ca": 10, "Sc": 11, "Ti": 12, "V": 13, "Cr": 14, "Mn": 15,
        "Fe": 16, "Co": 17, "Ni": 18, "Cu": 11, "Zn": 12,
        "Ga": 13, "Ge": 4, "As": 5, "Se": 6, "Br": 7, "Kr": 8,
        "Rb": 9, "Sr": 10, "Y": 11, "Zr": 12, "Nb": 13, "Mo": 14,
        "Ru": 16, "Rh": 17, "Pd": 18, "Ag": 11, "Cd": 12,
        "In": 13, "Sn": 4, "Sb": 5, "Te": 6, "I": 7, "Xe": 8,
        "Cs": 9, "Ba": 10, "La": 11,
        "W": 14, "Pt": 18, "Au": 11, "Pb": 4, "Bi": 5,
    }
    val = valence_map.get(element)
    if val is None:
        raise ValueError(
            f"Element '{element}' has no GTH pseudopotential valence electron count defined. "
            f"Supported elements: {', '.join(sorted(valence_map.keys()))}. "
            f"For unsupported elements, specify the full potential name via "
            f"structure['element_potentials'] = {{'{element}': 'GTH-PBE-qN'}}."
        )
    return val


def _write_motion_section(
    lines: List[str],
    run_type: str,
    project_name: str,
    geo_opt_params: Optional[Dict] = None,
    cell_opt_params: Optional[Dict] = None,
    md_params: Optional[Dict] = None,
    vib_params: Optional[Dict] = None,
    band_structure_params: Optional[Dict] = None,
    neb_params: Optional[Dict] = None,
) -> None:
    """Write MOTION section."""
    lines.append("&MOTION")

    if run_type == "GEO_OPT":
        gp = geo_opt_params or {}
        lines.append("  &GEO_OPT")
        lines.append(f"    OPTIMIZER {gp.get('optimizer', 'BFGS')}")
        lines.append(f"    MAX_ITER {gp.get('max_iter', 200)}")
        lines.append(f"    MAX_DR {gp.get('max_dr', '3.0E-3')}")
        lines.append(f"    MAX_FORCE {gp.get('max_force', '4.5E-4')}")
        lines.append(f"    RMS_DR {gp.get('rms_dr', '1.5E-3')}")
        lines.append(f"    RMS_FORCE {gp.get('rms_force', '3.0E-4')}")
        lines.append("  &END GEO_OPT")

    elif run_type == "CELL_OPT":
        cp = cell_opt_params or {}
        lines.append("  &CELL_OPT")
        lines.append(f"    OPTIMIZER {cp.get('optimizer', 'BFGS')}")
        lines.append(f"    MAX_ITER {cp.get('max_iter', 200)}")
        lines.append(f"    MAX_DR {cp.get('max_dr', '3.0E-3')}")
        lines.append(f"    MAX_FORCE {cp.get('max_force', '4.5E-4')}")
        lines.append(f"    KEEP_SYMMETRY {'.TRUE.' if cp.get('keep_symmetry', False) else '.FALSE.'}")
        if cp.get("pressure_tolerance"):
            lines.append(f"    PRESSURE_TOLERANCE {cp['pressure_tolerance']}")
        ext_pressure = cp.get("external_pressure")
        if ext_pressure is not None:
            if isinstance(ext_pressure, (int, float)):
                # Scalar: isotropic pressure in GPa
                p = float(ext_pressure)
                lines.append(f"    EXTERNAL_PRESSURE [GPa] {p} 0 0  0 {p} 0  0 0 {p}")
            elif isinstance(ext_pressure, (list, tuple)) and len(ext_pressure) == 9:
                # Full 3x3 tensor as flat list [xx, xy, xz, yx, yy, yz, zx, zy, zz]
                vals = " ".join(str(v) for v in ext_pressure)
                lines.append(f"    EXTERNAL_PRESSURE [GPa] {vals}")
        lines.append("  &END CELL_OPT")

    elif run_type == "MD":
        mp = md_params or {}
        ensemble = mp.get("ensemble", "NVT")
        # Warn about unknown md_params keys to catch typos
        _known_md_keys = {
            'ensemble', 'steps', 'timestep', 'temperature', 'thermostat',
            'thermostat_region', 'nose_length', 'nose_timecon', 'timecon',
            'pressure', 'baro_timecon',
        }
        _unknown_keys = set(mp.keys()) - _known_md_keys
        if _unknown_keys:
            logging.warning(f"  Unknown md_params keys (ignored): {_unknown_keys}")

        lines.append("  &MD")
        lines.append(f"    ENSEMBLE {ensemble}")
        lines.append(f"    STEPS {mp.get('steps', 1000)}")
        lines.append(f"    TIMESTEP {mp.get('timestep', 0.5)}")
        lines.append(f"    TEMPERATURE {mp.get('temperature', 300.0)}")
        if ensemble in ("NVT", "NPT_I", "NPT_F"):
            thermostat_region = mp.get("thermostat_region", "MASSIVE")
            # Accept 'timecon' as alias for 'nose_timecon' (Enhancement 2)
            nose_timecon = mp.get("nose_timecon", mp.get("timecon", 100.0))
            lines.append("    &THERMOSTAT")
            lines.append(f"      TYPE {mp.get('thermostat', 'NOSE')}")
            lines.append(f"      REGION {thermostat_region}")
            lines.append("      &NOSE")
            lines.append(f"        LENGTH {mp.get('nose_length', 3)}")
            lines.append(f"        TIMECON {nose_timecon}")
            lines.append("      &END NOSE")
            lines.append("    &END THERMOSTAT")
        if ensemble in ("NPT_I", "NPT_F"):
            lines.append("    &BAROSTAT")
            lines.append(f"      PRESSURE {mp.get('pressure', 1.0)}")
            lines.append(f"      TIMECON {mp.get('baro_timecon', 1000.0)}")
            lines.append("    &END BAROSTAT")
        lines.append("  &END MD")

    elif run_type == "BAND":
        # Band structure uses MOTION for k-path definition
        pass  # Band-specific MOTION content handled via trajectory printing below

    elif run_type == "NEB":
        # F6: Nudged Elastic Band for transition state / reaction path finding
        np_neb = neb_params or {}
        neb_type = np_neb.get("type", "CI-NEB")
        n_images = np_neb.get("n_images", 8)
        spring = np_neb.get("spring", 0.05)
        neb_optimizer = np_neb.get("optimizer", "DIIS")
        align_frames = np_neb.get("align_frames", True)
        rotate_frames = np_neb.get("rotate_frames", True)

        lines.append("  &BAND")
        lines.append(f"    BAND_TYPE {neb_type}")
        lines.append(f"    NUMBER_OF_REPLICA {n_images}")
        lines.append(f"    K_SPRING {spring}")
        lines.append(f"    ALIGN_FRAMES {'.TRUE.' if align_frames else '.FALSE.'}")
        lines.append(f"    ROTATE_FRAMES {'.TRUE.' if rotate_frames else '.FALSE.'}")

        reactant_file = np_neb.get("reactant_file")
        product_file = np_neb.get("product_file")
        if reactant_file:
            lines.append("    &REPLICA")
            lines.append(f"      COORD_FILE_NAME {reactant_file}")
            lines.append("    &END REPLICA")
        if product_file:
            lines.append("    &REPLICA")
            lines.append(f"      COORD_FILE_NAME {product_file}")
            lines.append("    &END REPLICA")

        lines.append("    &OPTIMIZE_BAND")
        lines.append(f"      OPT_TYPE {neb_optimizer}")
        if neb_optimizer == "DIIS":
            lines.append("      &DIIS")
            lines.append(f"        MAX_STEPS {np_neb.get('max_steps', 100)}")
            lines.append("      &END DIIS")
        lines.append("    &END OPTIMIZE_BAND")

        lines.append("    &CONVERGENCE_CONTROL")
        lines.append(f"      MAX_FORCE {np_neb.get('max_force', '4.5E-4')}")
        lines.append(f"      RMS_FORCE {np_neb.get('rms_force', '3.0E-4')}")
        lines.append("    &END CONVERGENCE_CONTROL")

        lines.append("  &END BAND")

    # Trajectory printing
    if run_type in ("MD", "GEO_OPT", "CELL_OPT", "NEB"):
        lines.append("  &PRINT")
        lines.append("    &TRAJECTORY")
        lines.append("      FORMAT XYZ")
        lines.append(f"      &EACH")
        if run_type == "MD":
            lines.append(f"        MD 1")
        else:
            lines.append(f"        GEO_OPT 1")
        lines.append(f"      &END EACH")
        lines.append("    &END TRAJECTORY")
        lines.append("    &RESTART")
        lines.append("      BACKUP_COPIES 0")
        lines.append("      &EACH")
        if run_type == "MD":
            lines.append(f"        MD 100")
        else:
            lines.append(f"        GEO_OPT 10")
        lines.append(f"      &END EACH")
        lines.append("    &END RESTART")
        if run_type == "MD":
            lines.append("    &CELL")
            lines.append("      &EACH")
            lines.append("        MD 1")
            lines.append("      &END EACH")
            lines.append("    &END CELL")
            lines.append("    &FORCES")
            lines.append("      &EACH")
            lines.append("        MD 1")
            lines.append("      &END EACH")
            lines.append("    &END FORCES")
        lines.append("  &END PRINT")

    lines.append("&END MOTION")
    lines.append("")


def _write_vibrational_analysis_section(
    lines: List[str],
    vib_params: Optional[Dict] = None,
) -> None:
    """Write VIBRATIONAL_ANALYSIS as a top-level section (CP2K 2024.x).

    In CP2K 2024.x, VIBRATIONAL_ANALYSIS is a root-level section,
    NOT a subsection of MOTION.
    """
    vp = vib_params or {}
    lines.append("&VIBRATIONAL_ANALYSIS")
    lines.append(f"  DX {vp.get('dx', 0.01)}")
    lines.append(f"  FULLY_PERIODIC {'.TRUE.' if vp.get('fully_periodic', False) else '.FALSE.'}")
    if vp.get('nproc_rep'):
        lines.append(f"  NPROC_REP {vp['nproc_rep']}")
    if vp.get('intensities', True):
        lines.append("  INTENSITIES .TRUE.")
    lines.append("&END VIBRATIONAL_ANALYSIS")
    lines.append("")


def _write_band_structure_section(lines: List[str], params: Optional[Dict]) -> None:
    """Write band structure PRINT section within DFT.

    Accepts two formats for k-path specification:

    1. **segments** (explicit): list of dicts, each with start_label, start,
       end_label, end, npoints.  Example::

           {'segments': [
               {'start_label': 'GAMMA', 'start': [0,0,0],
                'end_label': 'X',     'end': [0.5,0,0.5], 'npoints': 20},
               ...
           ]}

    2. **path** (compact): list of [label, npoints, kx, ky, kz] tuples.
       Consecutive entries are paired into segments automatically.  Example::

           {'path': [
               ['GAMMA', 20, 0.0, 0.0, 0.0],
               ['X',     20, 0.5, 0.0, 0.5],
               ['W',     20, 0.5, 0.25, 0.75],
           ]}

       This produces segments GAMMA→X (20 pts), X→W (20 pts).
       The npoints value on the *first* point of each pair is used.
    """
    if params is None:
        return

    segments = params.get("segments", [])

    # Auto-convert compact 'path' format → segments if no explicit segments
    if not segments:
        path = params.get("path", [])
        if len(path) < 2:
            return
        for i in range(len(path) - 1):
            p1, p2 = path[i], path[i + 1]
            # Each entry: [label, npoints, kx, ky, kz]
            segments.append({
                "start_label": p1[0],
                "start": [p1[2], p1[3], p1[4]],
                "end_label": p2[0],
                "end": [p2[2], p2[3], p2[4]],
                "npoints": p1[1],
            })

    if not segments:
        return

    lines.append("    &PRINT")
    lines.append("      &BAND_STRUCTURE")
    for seg in segments:
        lines.append("        &KPOINT_SET")
        lines.append(f"          NPOINTS {seg.get('npoints', 20)}")
        lines.append(f"          SPECIAL_POINT {seg['start_label']} {seg['start'][0]} {seg['start'][1]} {seg['start'][2]}")
        lines.append(f"          SPECIAL_POINT {seg['end_label']} {seg['end'][0]} {seg['end'][1]} {seg['end'][2]}")
        lines.append("        &END KPOINT_SET")
    lines.append("      &END BAND_STRUCTURE")
    lines.append("    &END PRINT")


def write_input_file(content: str, filename: str) -> str:
    """Write CP2K input content to a file.

    Args:
        content: CP2K input file content.
        filename: Output file name.

    Returns:
        Full path to the written file.
    """
    filepath = os.path.join(WORK_DIR, filename)
    with open(filepath, "w") as f:
        f.write(content)
    logging.info(f"Wrote input file: {filepath}")
    return filepath


# =============================================================================
# DATA FILE UTILITIES
# =============================================================================


def list_basis_sets(element: Optional[str] = None) -> List[str]:
    """List available basis sets from CP2K data directory.

    Args:
        element: If provided, filter basis sets for this element.

    Returns:
        List of basis set names available.
    """
    basis_files = [
        "BASIS_MOLOPT", "BASIS_MOLOPT_UZH", "BASIS_SET", "GTH_BASIS_SETS",
        "BASIS_ADMM", "BASIS_ADMM_MOLOPT",
    ]
    found = set()
    for bf in basis_files:
        filepath = os.path.join(CP2K_DATA_DIR, bf)
        if os.path.isfile(filepath):
            try:
                with open(filepath) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split()
                        if len(parts) >= 2 and parts[0].isalpha() and len(parts[0]) <= 3:
                            if element is None or parts[0] == element:
                                found.add(parts[1])
            except Exception:
                pass
    return sorted(found)


def list_potentials(element: Optional[str] = None) -> List[str]:
    """List available pseudopotentials from CP2K data directory.

    Args:
        element: If provided, filter potentials for this element.

    Returns:
        List of potential names available.
    """
    pot_files = ["GTH_POTENTIALS", "POTENTIAL", "ALL_POTENTIALS", "ECP_POTENTIALS"]
    found = set()
    for pf in pot_files:
        filepath = os.path.join(CP2K_DATA_DIR, pf)
        if os.path.isfile(filepath):
            try:
                with open(filepath) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split()
                        if len(parts) >= 2 and parts[0].isalpha() and len(parts[0]) <= 3:
                            if element is None or parts[0] == element:
                                found.add(parts[1])
            except Exception:
                pass
    return sorted(found)


def check_data_files() -> Dict[str, Any]:
    """Check that CP2K data files are accessible.

    Returns:
        Dict with status and list of found data files.
    """
    result = {
        "data_dir": CP2K_DATA_DIR,
        "exists": os.path.isdir(CP2K_DATA_DIR),
        "files": [],
    }
    if result["exists"]:
        result["files"] = sorted(os.listdir(CP2K_DATA_DIR))
        result["basis_files"] = [f for f in result["files"] if "BASIS" in f.upper()]
        result["potential_files"] = [f for f in result["files"] if "POTENTIAL" in f.upper() or f.startswith("GTH_")]
        result["basis_sets_ok"] = len(result["basis_files"]) > 0
        result["potentials_ok"] = len(result["potential_files"]) > 0
    else:
        result["basis_sets_ok"] = False
        result["potentials_ok"] = False
    return result


# =============================================================================
# OUTPUT PARSING FUNCTIONS
# =============================================================================


def parse_cp2k_output(filename: str) -> Dict[str, Any]:
    """Parse CP2K output file for key results.

    Args:
        filename: Path to CP2K output file. **Must include the file extension**
            (e.g., ``'water.out'`` or ``'/app/workdir/water.out'``). Passing only
            the project name (e.g., ``'water'``) will raise FileNotFoundError.
            This is different from ``parse_md_output()`` which takes the
            project name without extension.

    Returns:
        Dict with parsed results including:
        - total_energy_hartree, total_energy_eV
        - converged (bool)
        - n_scf_cycles
        - forces (if available)
        - stress_tensor (if available)
        - band_gap_eV (if available)
        - walltime_seconds
    """
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"Output file not found: {filename}")

    result = {
        "converged": False,
        "total_energy_hartree": None,
        "total_energy_eV": None,
        "n_scf_cycles": 0,
        "scf_energies": [],
        "forces": [],
        "stress_tensor": None,
        "walltime_seconds": None,
        "warnings": [],
    }

    with open(filename) as f:
        content = f.read()

    # Total energy
    energies = re.findall(r"ENERGY\| Total FORCE_EVAL.*?:\s+([-\d.E+]+)", content)
    if energies:
        result["total_energy_hartree"] = float(energies[-1])
        result["total_energy_eV"] = float(energies[-1]) * HARTREE_TO_EV

    # SCF convergence
    # Match multiple CP2K output formats for SCF convergence
    scf_matches = re.findall(r"SCF run converged in\s+(\d+)\s+step", content)
    if scf_matches:
        result["converged"] = True
        result["n_scf_cycles"] = int(scf_matches[-1])
    else:
        # Fallback: count actual SCF iteration lines if converged but pattern missed
        if "SCF run converged" in content and "SCF run NOT converged" not in content:
            result["converged"] = True
            scf_iter_lines = re.findall(
                r"^\s+(\d+)\s+(?:OT|NoMix|Broy\.|P_Mix|DIIS)\S*\s+",
                content, re.MULTILINE,
            )
            if scf_iter_lines:
                result["n_scf_cycles"] = int(scf_iter_lines[-1])

    if "SCF run NOT converged" in content:
        result["converged"] = False
        result["warnings"].append("SCF did not converge")

    # SCF iteration energies
    # Format: step mixing_method time convergence total_energy change
    # e.g.: "  1 NoMix/Diag. 0.40E+00    0.3     1.567       -17.128305 -1.71E+01"
    scf_energies = re.findall(
        r"^\s+\d+\s+(?:OT|NoMix|Broy\.|P_Mix|DIIS)\S*\s+\S+\s+\S+\s+\S+\s+([-]?\d+\.\d+)\s+[-\d.E+]+",
        content, re.MULTILINE,
    )
    result["scf_energies"] = [float(e) for e in scf_energies]

    # Forces
    force_block = re.search(
        r"ATOMIC FORCES in.*?\n\s*#.*?\n(.*?)SUM OF ATOMIC FORCES",
        content, re.DOTALL,
    )
    if force_block:
        forces = []
        for line in force_block.group(1).strip().split("\n"):
            parts = line.split()
            if len(parts) >= 6:
                try:
                    forces.append({
                        "atom": int(parts[0]),
                        "kind": int(parts[1]),
                        "element": parts[2],
                        "fx": float(parts[3]),
                        "fy": float(parts[4]),
                        "fz": float(parts[5]),
                    })
                except (ValueError, IndexError):
                    pass
        result["forces"] = forces
        # Provide forces as a 2D nested list [[fx,fy,fz], ...] for easy numpy conversion.
        # np.array(result["forces_array"]).shape == (N_atoms, 3)
        result["forces_array"] = [[f["fx"], f["fy"], f["fz"]] for f in forces]

    # Stress tensor — CP2K 2024.x uses "STRESS| Analytical stress tensor [GPa]"
    # with pipe-prefixed rows.  Keep older "STRESS TENSOR [GPa]" as fallback.
    # NOTE: each continuation line needs \s* to consume the leading whitespace
    # that CP2K places before the "STRESS|" prefix.
    stress_match = re.search(
        r"STRESS\|\s+(?:Analytical|Numerical)\s+stress\s+tensor\s+\[GPa\]\s*\n"
        r"\s*STRESS\|\s+x\s+y\s+z\s*\n"
        r"\s*STRESS\|\s+x\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*\n"
        r"\s*STRESS\|\s+y\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*\n"
        r"\s*STRESS\|\s+z\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)",
        content,
    )
    if not stress_match:
        # Fallback for older CP2K versions
        stress_match = re.search(
            r"STRESS TENSOR \[GPa\]\s*\n\s*X\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)\s*\n"
            r"\s*Y\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)\s*\n"
            r"\s*Z\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)",
            content,
        )
    if stress_match:
        vals = [float(stress_match.group(i)) for i in range(1, 10)]
        result["stress_tensor"] = {
            "unit": "GPa",
            "matrix": [vals[0:3], vals[3:6], vals[6:9]],
            "pressure": -(vals[0] + vals[4] + vals[8]) / 3.0,
        }

    # F8: Mulliken population analysis
    mulliken_block = re.search(
        r"Mulliken Population Analysis.*?\n\s*#.*?\n(.*?)(?:# Total charge|$)",
        content, re.DOTALL,
    )
    if mulliken_block:
        mulliken_charges = []
        for mline in mulliken_block.group(1).strip().split("\n"):
            mparts = mline.split()
            if len(mparts) >= 4:
                try:
                    mulliken_charges.append({
                        "atom": int(mparts[0]),
                        "element": mparts[1],
                        "kind": int(mparts[2]),
                        "population": float(mparts[3]),
                        "charge": float(mparts[4]) if len(mparts) >= 5 else None,
                    })
                except (ValueError, IndexError):
                    pass
        if mulliken_charges:
            result["mulliken_charges"] = mulliken_charges

    # F8: Hirshfeld charges
    hirshfeld_blocks = re.findall(
        r"Hirshfeld Charges.*?Atom\s+Element.*?\n(.*?)(?:Total charge|$)",
        content, re.DOTALL,
    )
    if hirshfeld_blocks:
        hirshfeld_charges = []
        for hline in hirshfeld_blocks[-1].strip().split("\n"):
            hparts = hline.split()
            if len(hparts) >= 4:
                try:
                    hirshfeld_charges.append({
                        "atom": int(hparts[0]),
                        "element": hparts[1],
                        "charge": float(hparts[-1]),
                    })
                except (ValueError, IndexError):
                    pass
        if hirshfeld_charges:
            result["hirshfeld_charges"] = hirshfeld_charges

    # HOMO-LUMO gap
    homo_match = re.findall(
        r"Eigenvalues of the occupied.*?HOMO.*?:\s+([-\d.E+]+)", content
    )
    lumo_match = re.findall(
        r"Eigenvalues of the unoccupied.*?LUMO.*?:\s+([-\d.E+]+)", content
    )
    if homo_match and lumo_match:
        homo = float(homo_match[-1])
        lumo = float(lumo_match[-1])
        result["homo_eV"] = homo * HARTREE_TO_EV
        result["lumo_eV"] = lumo * HARTREE_TO_EV
        result["band_gap_eV"] = (lumo - homo) * HARTREE_TO_EV

    # Walltime — extract from CP2K timing table (TOTAL TIME MAXIMUM column)
    wt_match = re.search(
        r"^\s+CP2K\s+1\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)",
        content, re.MULTILINE,
    )
    if wt_match:
        result["walltime_seconds"] = float(wt_match.group(1))

    return result


def parse_geo_opt(filename: str) -> Dict[str, Any]:
    """Parse geometry optimization output.

    Args:
        filename: Path to CP2K output file from GEO_OPT run.

    Returns:
        Dict with optimization steps, energies, convergence info.
        The geo_opt sub-dict contains:
        - n_steps / steps: number of optimization steps
        - energies / energies_hartree: list of energies at each step (Ha)
        - converged: whether optimization completed
        - step_details: list of per-step convergence info
    """
    base = parse_cp2k_output(filename)

    with open(filename) as f:
        content = f.read()

    # Optimization steps — parse step-by-step convergence info
    # CP2K format: "--------  Informations at step =     N ------------"
    opt_steps = re.findall(
        r"Informations at step\s*=\s*(\d+).*?"
        r"Max\.\s+step\s+size\s*=\s*([-\d.E+]+).*?"
        r"Conv\.\s+limit\s+for\s+step\s+size\s*=\s*([-\d.E+]+).*?"
        r"Conv\.\s+in\s+step\s+size\s*=\s*(\w+)",
        content, re.DOTALL,
    )

    # Also try a simpler regex if the detailed one fails
    if not opt_steps:
        opt_steps = re.findall(
            r"--------\s+Informations at step\s*=\s*(\d+)\s+",
            content,
        )
        # Convert to tuples for consistency (step_num, None, None, None)
        opt_steps = [(s, None, None, None) for s in opt_steps]

    geo_opt_energies = re.findall(
        r"ENERGY\| Total FORCE_EVAL.*?:\s+([-\d.E+]+)", content
    )
    energy_list = [float(e) for e in geo_opt_energies]

    # Build step details if available
    step_details = []
    for step_info in opt_steps:
        detail = {"step": int(step_info[0]) if step_info[0] is not None else None}
        if step_info[1] is not None:
            detail["max_step_size"] = float(step_info[1])
            detail["step_size_limit"] = float(step_info[2])
            detail["step_converged"] = step_info[3] == "YES"
        step_details.append(detail)

    n = len(opt_steps)
    base["geo_opt"] = {
        "n_steps": n,
        "steps": n,                          # alias for compatibility
        "energies_hartree": energy_list,
        "energies": energy_list,             # alias for compatibility
        "converged": "GEOMETRY OPTIMIZATION COMPLETED" in content,
        "step_details": step_details,
    }

    return base


def parse_md_output(project_name: str) -> Dict[str, Any]:
    """Parse MD output files (energy, trajectory).

    Args:
        project_name: CP2K project name used as prefix for output files.
            Also accepts the .out filename (e.g. 'water_md.out'), in which
            case the project name is derived by stripping the extension.

    Returns:
        Dict with MD trajectory data (energies, temperatures, etc).
    """
    # Accept both 'water_md' and 'water_md.out'
    if project_name.endswith('.out'):
        project_name = os.path.splitext(os.path.basename(project_name))[0]

    result = {"steps": [], "n_steps": 0}

    # Parse .ener file
    ener_file = f"{project_name}-1.ener"
    if os.path.isfile(ener_file):
        steps = []
        with open(ener_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        step_data = {
                            "step": int(parts[0]),
                            "time_fs": float(parts[1]),
                            "kinetic_hartree": float(parts[2]),
                            "temperature_K": float(parts[3]),
                            "potential_hartree": float(parts[4]),
                            "total_energy_hartree": float(parts[2]) + float(parts[4]),
                        }
                        # Column 6: conserved quantity (Nosé-Hoover extended energy for NVT,
                        # enthalpy for NPT). Critical diagnostic for MD quality — drift
                        # indicates timestep too large or thermostat instability.
                        if len(parts) >= 6:
                            step_data["conserved_hartree"] = float(parts[5])
                        steps.append(step_data)
                    except (ValueError, IndexError):
                        pass
        result["steps"] = steps
        result["n_steps"] = len(steps)
        if steps:
            temps = [s["temperature_K"] for s in steps]
            energies = [s["total_energy_hartree"] for s in steps]
            pot_energies = [s["potential_hartree"] for s in steps]
            kin_energies = [s["kinetic_hartree"] for s in steps]
            result["temperatures"] = temps
            result["energies"] = energies
            result["potential_energies"] = pot_energies
            result["kinetic_energies"] = kin_energies
            # Conserved quantity (Nosé-Hoover extended energy for NVT,
            # enthalpy for NPT). Drift diagnostic for MD quality.
            if steps[0].get("conserved_hartree") is not None:
                conserved = [s["conserved_hartree"] for s in steps]
                result["conserved_quantities"] = conserved
                result["conserved_drift_hartree"] = conserved[-1] - conserved[0]
            result["avg_temperature"] = sum(temps) / len(temps)
            result["std_temperature"] = (
                sum((t - result["avg_temperature"]) ** 2 for t in temps) / len(temps)
            ) ** 0.5
    else:
        logging.warning(f"MD .ener file not found: {ener_file}")

    return result


def parse_vibrational_output(filename: str) -> Dict[str, Any]:
    """Parse vibrational analysis output.

    Args:
        filename: Path to CP2K output file from VIBRATIONAL_ANALYSIS run.

    Returns:
        Dict with frequencies, IR intensities, zero-point energy.
    """
    result = {"frequencies_cm": [], "intensities": [], "n_modes": 0, "has_imaginary": False}

    if not os.path.isfile(filename):
        raise FileNotFoundError(f"Output file not found: {filename}")

    with open(filename) as f:
        content = f.read()

    # Parse frequencies — CP2K prints multiple frequencies per line
    # e.g. "VIB|Frequency (cm^-1)  1614.86  3719.03  3824.04"
    freq_lines = re.findall(
        r"VIB\|Frequency\s+\(cm\^-1\)\s+(.*)", content
    )
    all_freqs = []
    for fl in freq_lines:
        nums = re.findall(r"[-]?\d+\.\d+", fl)
        all_freqs.extend([float(n) for n in nums])
    if all_freqs:
        result["frequencies_cm"] = all_freqs
        result["n_modes"] = len(all_freqs)
        result["has_imaginary"] = any(f < 0 for f in all_freqs)

    # Parse IR intensities — same multi-value-per-line format
    ir_lines = re.findall(
        r"VIB\|Intensities\s+\(km/mol\)\s+(.*)", content
    )
    all_intens = []
    for il in ir_lines:
        nums = re.findall(r"[-]?\d+\.\d+", il)
        all_intens.extend([float(n) for n in nums])
    if all_intens:
        result["intensities"] = all_intens

    # Zero-point energy — handle various CP2K formatting of this line
    zpe_match = re.search(r"VIB\|Zero Point Energy\s+\[kJ/mol\]\s*:?\s*([-\d.E+]+)", content)
    if not zpe_match:
        zpe_match = re.search(r"VIB\|Zero Point Energy.*?:\s+([-\d.E+]+)\s+kJ/mol", content)
    if zpe_match:
        result["zpe_kJ_mol"] = float(zpe_match.group(1))
        result["zpve_hartree"] = float(zpe_match.group(1)) / HARTREE_TO_KJ_MOL

    # Convenience: list of imaginary frequencies (negative values)
    result["imaginary_freqs"] = [f for f in result["frequencies_cm"] if f < 0]

    return result


def parse_band_structure(filename: str) -> Dict[str, Any]:
    """Parse band structure output from CP2K .bs file.

    Args:
        filename: Path to .bs band structure file.

    Returns:
        Dict with kpoints, eigenvalues, special point labels.
    """
    result = {"kpoints": [], "eigenvalues": [], "special_points": []}

    if not os.path.isfile(filename):
        raise FileNotFoundError(f"Band structure file not found: {filename}")

    with open(filename) as f:
        lines = f.readlines()

    set_started = False
    current_kpoints = []
    current_bands = []

    for line in lines:
        line = line.strip()
        if line.startswith("# Set"):
            if current_kpoints:
                result["kpoints"].extend(current_kpoints)
                result["eigenvalues"].extend(current_bands)
            current_kpoints = []
            current_bands = []
            set_started = True
        elif line.startswith("# Point"):
            continue
        elif line.startswith("#  Special"):
            parts = line.split()
            if len(parts) >= 6:
                result["special_points"].append({
                    "label": parts[3],
                    "kpoint": [float(parts[4]), float(parts[5]), float(parts[6])],
                })
        elif line.startswith("#"):
            continue
        elif set_started and line:
            parts = line.split()
            if len(parts) >= 5:
                try:
                    # Format: kx ky kz e1 e2 e3 ...
                    kpt = [float(parts[0]), float(parts[1]), float(parts[2])]
                    eigs = [float(e) * HARTREE_TO_EV for e in parts[3:]]
                    current_kpoints.append(kpt)
                    current_bands.append(eigs)
                except ValueError:
                    pass

    if current_kpoints:
        result["kpoints"].extend(current_kpoints)
        result["eigenvalues"].extend(current_bands)

    return result


def parse_pdos(filename: str) -> Dict[str, Any]:
    """Parse projected density of states file.

    Args:
        filename: Path to PDOS file (e.g., *-k1-1.pdos).

    Returns:
        Dict with energies and DOS arrays.
    """
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"PDOS file not found: {filename}")

    energies = []
    total_dos = []
    orbital_dos = {}
    header = None

    with open(filename) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#"):
                if "Eigenvalue" in line or "Energy" in line:
                    header = line
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    # CP2K PDOS format: eigenvalue_a.u., occupation, s, p, d, ...
                    # (some versions prepend an index column)
                    # Heuristic: if first value looks like an integer index, skip it
                    offset = 0
                    if len(parts) >= 4:
                        try:
                            idx_val = float(parts[0])
                            # If it's a small positive integer, it's likely a step/index
                            if idx_val == int(idx_val) and idx_val > 0:
                                offset = 1
                        except ValueError:
                            pass
                    energies.append(float(parts[offset]))
                    total_dos.append(float(parts[offset + 1]))
                    for i, val in enumerate(parts[offset + 2:]):
                        orb_name = f"orbital_{i}"
                        if orb_name not in orbital_dos:
                            orbital_dos[orb_name] = []
                        orbital_dos[orb_name].append(float(val))
                except (ValueError, IndexError):
                    pass

    return {
        "energies_eV": energies,
        "total_dos": total_dos,
        "orbital_dos": orbital_dos,
        "header": header,
    }


# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================


def compute_equation_of_state(
    volumes: List[float],
    energies: List[float],
    eos_type: str = "birch_murnaghan",
) -> Dict[str, Any]:
    """Fit equation of state to energy-volume data.

    Args:
        volumes: List of volumes in Å³.
        energies: List of total energies in eV.
        eos_type: 'birch_murnaghan' (default) or 'murnaghan'.

    Returns:
        Dict with V0, E0, B0 (GPa), B0_prime, fitted_energies.
    """
    import numpy as np
    from scipy.optimize import curve_fit

    V = np.array(volumes)
    E = np.array(energies)

    # Initial guesses
    idx_min = np.argmin(E)
    V0_guess = V[idx_min]
    E0_guess = E[idx_min]
    B0_guess = 100.0  # GPa
    Bp_guess = 4.0

    if eos_type == "birch_murnaghan":
        def bm_eos(v, e0, v0, b0, bp):
            eta = (v0 / v) ** (2.0 / 3.0)
            return e0 + (9.0 * v0 * b0 / 16.0) * (
                (eta - 1.0) ** 3 * bp
                + (eta - 1.0) ** 2 * (6.0 - 4.0 * eta)
            )

        # Convert B0 guess from GPa to eV/Å³
        b0_eV = B0_guess / 160.2176634

        popt, pcov = curve_fit(
            bm_eos, V, E, p0=[E0_guess, V0_guess, b0_eV, Bp_guess],
            maxfev=10000,
        )
        E0, V0, B0, Bp = popt
        fitted = bm_eos(V, *popt)
    else:
        raise ValueError(f"Unknown EOS type: {eos_type}")

    return {
        "E0_eV": float(E0),
        "V0_angstrom3": float(V0),
        "B0_GPa": float(B0 * 160.2176634),
        "B0_prime": float(Bp),
        "volumes": volumes,
        "energies_eV": energies,
        "fitted_energies_eV": fitted.tolist(),
        "residual": float(np.sum((E - fitted) ** 2)),
    }


def compute_convergence(
    parameter_values: List[float],
    energies: List[float],
    threshold: float = 0.001,
) -> Dict[str, Any]:
    """Analyze convergence of energy with respect to a parameter.

    Args:
        parameter_values: List of parameter values tested.
        energies: Corresponding total energies (eV).
        threshold: Convergence threshold in eV (default 1 meV).

    Returns:
        Dict with converged_value, energy_differences, converged (bool).
    """
    diffs = []
    for i in range(1, len(energies)):
        diffs.append(abs(energies[i] - energies[i - 1]))

    converged_idx = None
    for i, d in enumerate(diffs):
        if d < threshold:
            converged_idx = i + 1
            break

    return {
        "parameter_values": parameter_values,
        "energies_eV": energies,
        "energy_differences_eV": diffs,
        "threshold_eV": threshold,
        "converged": converged_idx is not None,
        "converged_value": parameter_values[converged_idx] if converged_idx else None,
        "converged_index": converged_idx,
    }


# =============================================================================
# STRUCTURE UTILITIES
# =============================================================================


def read_xyz(filename: str) -> Dict[str, Any]:
    """Read XYZ file and return structure dict compatible with generate_input.

    Args:
        filename: Path to XYZ file.

    Returns:
        Dict with 'coords' as list of [symbol, x, y, z].
    """
    coords = []
    with open(filename) as f:
        lines = f.readlines()
    n_atoms = int(lines[0].strip())
    comment = lines[1].strip() if len(lines) > 1 else ""
    for line in lines[2 : 2 + n_atoms]:
        parts = line.split()
        if len(parts) >= 4:
            coords.append([parts[0], float(parts[1]), float(parts[2]), float(parts[3])])
    return {"coords": coords, "n_atoms": n_atoms, "comment": comment}


def write_xyz(coords: List, filename: str, comment: str = "") -> str:
    """Write coordinates to XYZ file.

    Args:
        coords: List of [symbol, x, y, z].
        filename: Output file path.
        comment: Comment line.

    Returns:
        Path to written file.
    """
    filepath = os.path.join(WORK_DIR, filename) if not os.path.isabs(filename) else filename
    with open(filepath, "w") as f:
        f.write(f"{len(coords)}\n")
        f.write(f"{comment}\n")
        for atom in coords:
            f.write(f"{atom[0]}  {atom[1]:.10f}  {atom[2]:.10f}  {atom[3]:.10f}\n")
    return filepath


def read_cif_to_structure(filename: str) -> Dict[str, Any]:
    """Read CIF file using ASE and return structure dict.

    Requires ASE to be installed.

    Args:
        filename: Path to CIF file.

    Returns:
        Dict compatible with generate_input's structure parameter.
    """
    from ase.io import read as ase_read

    atoms = ase_read(filename)
    cell = atoms.cell.tolist()
    positions = atoms.positions.tolist()
    symbols = atoms.get_chemical_symbols()

    coords = [[sym, pos[0], pos[1], pos[2]] for sym, pos in zip(symbols, positions)]

    return {
        "coords": coords,
        "cell": cell,
        "periodic": "XYZ",
        "coord_type": "CARTESIAN",
    }


# =============================================================================
# VISUALIZATION FUNCTIONS
# =============================================================================


def plot_scf_convergence(
    scf_energies: List[float],
    output_file: str = "scf_convergence.png",
    title: str = "SCF Convergence",
) -> str:
    """Plot SCF energy convergence.

    Args:
        scf_energies: List of SCF iteration energies (Hartree).
        output_file: Output file name.
        title: Plot title.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    iterations = list(range(1, len(scf_energies) + 1))
    ax.plot(iterations, scf_energies, "o-", color="#2196F3", markersize=4)
    ax.set_xlabel("SCF Iteration")
    ax.set_ylabel("Energy (Hartree)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved SCF convergence plot: {filepath}")
    return filepath


def plot_geo_opt_convergence(
    energies,
    output_file: str = "geo_opt_convergence.png",
    title: str = "Geometry Optimization",
) -> str:
    """Plot geometry optimization energy convergence.

    Args:
        energies: List of energies (Hartree) OR a dict from parse_geo_opt().
            If a dict is passed, energies are extracted from
            geo_opt.energies or geo_opt.energies_hartree automatically.
        output_file: Output file name.
        title: Plot title.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Accept dict from parse_geo_opt() — extract energy list
    if isinstance(energies, dict):
        geo = energies.get("geo_opt", energies)
        energy_list = (
            geo.get("energies")
            or geo.get("energies_hartree")
            or []
        )
    else:
        energy_list = list(energies)

    if not energy_list:
        logging.warning("No energies to plot for geo-opt convergence")
        return ""

    fig, ax = plt.subplots(figsize=(8, 5))
    steps = list(range(1, len(energy_list) + 1))
    ax.plot(steps, energy_list, "s-", color="#4CAF50", markersize=5)
    ax.set_xlabel("Optimization Step")
    ax.set_ylabel("Energy (Hartree)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved geo-opt convergence plot: {filepath}")
    return filepath


def plot_md_energy(
    md_data: Dict,
    output_file: str = "md_energy.png",
    title: str = "MD Energy",
) -> str:
    """Plot MD energy and temperature over time.

    Args:
        md_data: Output from parse_md_output().
        output_file: Output file name.
        title: Plot title.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    steps = md_data["steps"]
    if not steps:
        logging.warning("No MD steps to plot")
        return ""

    times = [s["time_fs"] for s in steps]
    pot_e = [s["potential_hartree"] * HARTREE_TO_EV for s in steps]
    kin_e = [s["kinetic_hartree"] * HARTREE_TO_EV for s in steps]
    temps = [s["temperature_K"] for s in steps]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax1.plot(times, pot_e, label="Potential", color="#2196F3", alpha=0.8)
    ax1.plot(times, kin_e, label="Kinetic", color="#FF9800", alpha=0.8)
    ax1.set_ylabel("Energy (eV)")
    ax1.set_title(title)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(times, temps, color="#F44336", alpha=0.8)
    ax2.set_xlabel("Time (fs)")
    ax2.set_ylabel("Temperature (K)")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved MD energy plot: {filepath}")
    return filepath


def plot_band_structure(
    band_data: Dict,
    fermi_energy: Optional[float] = None,
    output_file: str = "band_structure.png",
    title: str = "Band Structure",
    energy_range: Optional[Tuple[float, float]] = None,
) -> str:
    """Plot electronic band structure.

    Args:
        band_data: Output from parse_band_structure().
        fermi_energy: Fermi energy in eV (for shifting zero).
        output_file: Output file name.
        title: Plot title.
        energy_range: (min, max) energy range in eV.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    eigenvalues = np.array(band_data["eigenvalues"])
    if eigenvalues.size == 0:
        logging.warning("No band structure data to plot")
        return ""

    n_kpoints = eigenvalues.shape[0]
    n_bands = eigenvalues.shape[1]
    x = np.arange(n_kpoints)

    if fermi_energy is not None:
        eigenvalues = eigenvalues - fermi_energy

    fig, ax = plt.subplots(figsize=(10, 6))
    for band_idx in range(n_bands):
        ax.plot(x, eigenvalues[:, band_idx], color="#2196F3", linewidth=0.8)

    if fermi_energy is not None:
        ax.axhline(y=0, color="red", linestyle="--", linewidth=0.8, label="Fermi level")

    # Mark special points with vertical lines and labels
    special_points = band_data.get("special_points", [])
    sp_labels = []
    sp_positions = []
    for sp in special_points:
        label = sp["label"]
        if label.upper() == "GAMMA":
            label = r"$\Gamma$"
        kpt = sp["kpoint"]
        # Find the closest x-index for this k-point
        min_dist = float("inf")
        best_idx = 0
        for idx, k in enumerate(band_data["kpoints"]):
            dist = sum((a - b) ** 2 for a, b in zip(k, kpt)) ** 0.5
            if dist < min_dist:
                min_dist = dist
                best_idx = idx
        sp_labels.append(label)
        sp_positions.append(best_idx)
        ax.axvline(x=best_idx, color="gray", linestyle="-", linewidth=0.5, alpha=0.5)

    if sp_labels:
        ax.set_xticks(sp_positions)
        ax.set_xticklabels(sp_labels)

    ax.set_xlabel("k-point")
    ax.set_ylabel("Energy (eV)")
    ax.set_title(title)
    if energy_range:
        ax.set_ylim(energy_range)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()

    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved band structure plot: {filepath}")
    return filepath


def plot_dos(
    pdos_data: Dict,
    fermi_energy: Optional[float] = None,
    output_file: str = "dos.png",
    title: str = "Density of States",
    energy_range: Optional[Tuple[float, float]] = None,
) -> str:
    """Plot density of states.

    Args:
        pdos_data: Output from parse_pdos().
        fermi_energy: Fermi energy in eV.
        output_file: Output file name.
        title: Plot title.
        energy_range: (min, max) energy range in eV.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    energies = np.array(pdos_data["energies_eV"])
    dos = np.array(pdos_data["total_dos"])

    if fermi_energy is not None:
        energies = energies - fermi_energy

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(energies, dos, color="#2196F3", linewidth=0.8)
    ax.fill_between(energies, 0, dos, alpha=0.2, color="#2196F3")

    if fermi_energy is not None:
        ax.axvline(x=0, color="red", linestyle="--", linewidth=0.8, label="Fermi level")

    ax.set_xlabel("Energy (eV)")
    ax.set_ylabel("DOS")
    ax.set_title(title)
    if energy_range:
        ax.set_xlim(energy_range)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved DOS plot: {filepath}")
    return filepath


def plot_ir_spectrum(
    frequencies: List[float],
    intensities: List[float],
    output_file: str = "ir_spectrum.png",
    title: str = "IR Spectrum",
    broadening: float = 10.0,
) -> str:
    """Plot IR spectrum from vibrational analysis.

    Args:
        frequencies: Frequencies in cm^-1.
        intensities: IR intensities in km/mol.
        output_file: Output file name.
        title: Plot title.
        broadening: Gaussian broadening in cm^-1.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    freq = np.array(frequencies)
    intens = np.array(intensities)

    # Only positive frequencies
    mask = freq > 0
    freq = freq[mask]
    intens = intens[mask] if len(intens) == len(frequencies) else intens

    x = np.linspace(max(0, freq.min() - 200), freq.max() + 200, 2000)
    y = np.zeros_like(x)
    for f, i in zip(freq, intens):
        y += i * np.exp(-0.5 * ((x - f) / broadening) ** 2)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x, y, color="#2196F3")
    ax.fill_between(x, 0, y, alpha=0.2, color="#2196F3")
    ax.set_xlabel("Wavenumber (cm$^{-1}$)")
    ax.set_ylabel("Intensity (km/mol)")
    ax.set_title(title)
    ax.invert_xaxis()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved IR spectrum plot: {filepath}")
    return filepath


def plot_convergence(
    parameter_values: List[float],
    energies: List[float],
    parameter_name: str = "Parameter",
    output_file: str = "convergence.png",
    title: str = "Convergence Test",
    threshold: Optional[float] = None,
) -> str:
    """Plot convergence of energy vs parameter.

    Args:
        parameter_values: Parameter values tested.
        energies: Corresponding energies in eV.
        parameter_name: Name of the parameter for axis label.
        output_file: Output file name.
        title: Plot title.
        threshold: Optional convergence threshold line.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8))

    ax1.plot(parameter_values, energies, "o-", color="#2196F3", markersize=6)
    ax1.set_xlabel(parameter_name)
    ax1.set_ylabel("Total Energy (eV)")
    ax1.set_title(title)
    ax1.grid(True, alpha=0.3)

    # Energy differences
    diffs = [abs(energies[i] - energies[i - 1]) for i in range(1, len(energies))]
    ax2.semilogy(parameter_values[1:], diffs, "s-", color="#FF5722", markersize=6)
    if threshold:
        ax2.axhline(y=threshold, color="green", linestyle="--", label=f"Threshold: {threshold} eV")
        ax2.legend()
    ax2.set_xlabel(parameter_name)
    ax2.set_ylabel("|ΔE| (eV)")
    ax2.set_title("Energy Differences")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved convergence plot: {filepath}")
    return filepath


def plot_equation_of_state(
    eos_result: Dict,
    output_file: str = "eos.png",
    title: str = "Equation of State",
) -> str:
    """Plot equation of state fit.

    Args:
        eos_result: Output from compute_equation_of_state().
        output_file: Output file name.
        title: Plot title.

    Returns:
        Path to saved plot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    volumes = eos_result.get("volumes", [])
    energies = eos_result.get("energies_eV", [])
    fitted = eos_result.get("fitted_energies_eV", [])

    if not volumes:
        logging.warning("No EOS data to plot")
        return ""

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(volumes, energies, "o", color="#2196F3", markersize=8, label="DFT data")
    if fitted:
        v_fine = np.linspace(min(volumes), max(volumes), 200)
        # Re-fit for smooth curve
        ax.plot(volumes, fitted, "-", color="#F44336", linewidth=2, label="BM fit")

    ax.axvline(x=eos_result["V0_angstrom3"], color="green", linestyle="--", alpha=0.5)
    ax.set_xlabel("Volume (Å³)")
    ax.set_ylabel("Energy (eV)")
    ax.set_title(f"{title}\nB₀ = {eos_result['B0_GPa']:.1f} GPa, V₀ = {eos_result['V0_angstrom3']:.2f} Å³")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    filepath = os.path.join(OUTPUT_DIR, output_file)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved EOS plot: {filepath}")
    return filepath


# =============================================================================
# INPUT VALIDATION
# =============================================================================


def validate_cp2k_input(input_content: str) -> Dict[str, Any]:
    """Validate CP2K input using cp2k-input-tools (if available).

    Parses the input through cp2k-input-tools to catch syntax errors,
    unknown keywords, and structural issues before submitting to CP2K.

    Args:
        input_content: CP2K input file content as string.

    Returns:
        Dict with keys:
        - valid: bool — True if input passes validation
        - errors: list of error messages (empty if valid)
        - warnings: list of warning messages
        - parsed: parsed input tree (if valid, else None)
    """
    result = {"valid": False, "errors": [], "warnings": [], "parsed": None}

    try:
        from cp2k_input_tools.parser import CP2KInputParser
    except ImportError:
        logging.warning("cp2k-input-tools not installed — skipping input validation")
        result["valid"] = True
        result["warnings"].append("cp2k-input-tools not available; validation skipped")
        return result

    try:
        parser = CP2KInputParser()
        # Write to temp file for parsing
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".inp", delete=False) as tmp:
            tmp.write(input_content)
            tmp_path = tmp.name

        try:
            parsed = parser.parse(tmp_path)
            result["valid"] = True
            result["parsed"] = parsed
            logging.info("  CP2K input validation: PASSED")
        except Exception as e:
            result["errors"].append(str(e))
            logging.error(f"  CP2K input validation FAILED: {e}")
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        result["warnings"].append(f"Validation error: {e}")
        # Don't block on validation infrastructure errors
        result["valid"] = True
        logging.warning(f"  Input validation infrastructure error: {e}")

    return result


def validate_input_file(input_file: str) -> Dict[str, Any]:
    """Validate a CP2K input file on disk.

    Args:
        input_file: Path to CP2K input file.

    Returns:
        Validation result dict (see validate_cp2k_input).
    """
    with open(input_file) as f:
        content = f.read()
    return validate_cp2k_input(content)


# =============================================================================
# PROVENANCE
# =============================================================================


def capture_provenance(
    project_name: str,
    run_type: str,
    structure: Optional[Dict] = None,
    dft_params: Optional[Dict] = None,
    input_file: Optional[str] = None,
    output_file: Optional[str] = None,
    result: Optional[subprocess.CompletedProcess] = None,
    extra: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Capture structured provenance metadata for a CP2K calculation.

    Records method, basis set, cutoffs, executable version, parallelism,
    restart source, and runtime choices into a structured dict suitable
    for inclusion in final_results.json.

    Args:
        project_name: CP2K project name.
        run_type: Calculation type (ENERGY, GEO_OPT, MD, etc.).
        structure: Structure dict (coords, cell, charge, multiplicity).
        dft_params: DFT parameter dict.
        input_file: Path to CP2K input file used.
        output_file: Path to CP2K output file produced.
        result: CompletedProcess from run_cp2k/run_cp2k_mpi.
        extra: Additional metadata to include.

    Returns:
        Provenance dict with standardized fields.
    """
    import platform
    from datetime import datetime, timezone

    dft = dft_params or {}
    prov = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cp2k_executable": CP2K_EXE,
        "project_name": project_name,
        "run_type": run_type,
        "method": {
            "functional": dft.get("functional", "PBE"),
            "basis_set": dft.get("basis_set", "DZVP-MOLOPT-SR-GTH"),
            "potential": dft.get("potential", "GTH-PBE"),
            "cutoff_ry": dft.get("cutoff", 300),
            "rel_cutoff_ry": dft.get("rel_cutoff", 60),
            "scf_method": dft.get("scf_method", "AUTO"),
            "dispersion": dft.get("dispersion", None),
            "kpoints": dft.get("kpoints", None),
        },
        "system": {
            "charge": structure.get("charge", 0) if structure else 0,
            "multiplicity": structure.get("multiplicity", 1) if structure else 1,
            "periodic": structure.get("periodic", "XYZ") if structure else "XYZ",
        },
        "environment": {
            "hostname": platform.node(),
            "cpu_count": os.cpu_count(),
            "omp_threads": os.environ.get("OMP_NUM_THREADS", "unknown"),
            "cp2k_data_dir": CP2K_DATA_DIR,
        },
    }

    # Add input/output file info
    if input_file and os.path.isfile(input_file):
        prov["input_file"] = input_file
        prov["input_file_size"] = os.path.getsize(input_file)
    if output_file and os.path.isfile(output_file):
        prov["output_file"] = output_file
        prov["output_file_size"] = os.path.getsize(output_file)

    # Add execution result info
    if result is not None:
        prov["exit_code"] = result.returncode
        prov["success"] = result.returncode == 0

    # Merge extra metadata
    if extra:
        prov.update(extra)

    logging.info(f"Captured provenance for {project_name} ({run_type})")
    return prov


# =============================================================================
# RECOVERY / RESILIENT EXECUTION
# =============================================================================


# Error classification for recovery decisions
_RECOVERABLE_ERRORS = {
    "SCF_NOT_CONVERGED": {
        "patterns": ["SCF run NOT converged", "Outer SCF loop did not converge"],
        "strategy": "adjust_scf",
    },
    "UKS_SCF_CRASH": {
        "patterns": ["MPI_ABORT", "SIGABRT"],
        "strategy": "harden_open_shell_scf",
    },
    "TIMEOUT": {
        "patterns": ["timed out after", "timeout expired"],
        "strategy": "reduce_parallelism",
    },
    "OT_KPOINT_CONFLICT": {
        "patterns": ["OT not possible with kpoint"],
        "strategy": "switch_to_diag",
    },
    "CHOLESKY_FAILURE": {
        "patterns": ["Cholesky decompose failed", "Matrix not positive definite"],
        "strategy": "adjust_scf",
    },
}

_UNRECOVERABLE_ERRORS = {
    "MISSING_DATA": ["file not found", "No data file found", "BASIS_SET_FILE_NAME"],
    "BAD_GEOMETRY": ["Atoms too close", "GEOMETRY is PROBLEMATIC"],
    "MEMORY": ["Out of memory", "oom-kill", "Cannot allocate memory", "SIGKILL"],
    "ELEMENT_NOT_FOUND": ["Unknown element", "Potential not found"],
}


def classify_cp2k_error(output_text: str, stderr_text: str = "") -> Dict[str, Any]:
    """Classify a CP2K error into recoverable or unrecoverable.

    Args:
        output_text: CP2K stdout/output file content.
        stderr_text: CP2K stderr content.

    Returns:
        Dict with keys:
        - recoverable: bool
        - error_type: string identifier
        - strategy: recovery strategy name (if recoverable)
        - message: human-readable error description
    """
    combined = (output_text + "\n" + stderr_text).lower()

    # Check unrecoverable first
    for error_type, patterns in _UNRECOVERABLE_ERRORS.items():
        for pat in patterns:
            if pat.lower() in combined:
                return {
                    "recoverable": False,
                    "error_type": error_type,
                    "strategy": None,
                    "message": f"Unrecoverable error: {error_type} (matched: '{pat}')",
                }

    # Special handling for MPI_ABORT/SIGABRT — only classify as UKS_SCF_CRASH
    # when UKS is active (indicated by "uks" or "multiplicity" > 1 in output).
    # Otherwise fall through to UNKNOWN to avoid masking other crash causes.
    _has_abort = "mpi_abort" in combined or "sigabrt" in combined
    _has_uks_context = "uks" in combined or "multiplicity" in combined
    if _has_abort and _has_uks_context:
        return {
            "recoverable": True,
            "error_type": "UKS_SCF_CRASH",
            "strategy": "harden_open_shell_scf",
            "message": (
                "Recoverable error: UKS_SCF_CRASH — MPI abort during open-shell SCF. "
                "Strategy: harden SCF with smearing, lower mixing, level shift."
            ),
        }

    # Check other recoverable errors
    for error_type, info in _RECOVERABLE_ERRORS.items():
        if error_type == "UKS_SCF_CRASH":
            continue  # Already handled above with context check
        for pat in info["patterns"]:
            if pat.lower() in combined:
                return {
                    "recoverable": True,
                    "error_type": error_type,
                    "strategy": info["strategy"],
                    "message": f"Recoverable error: {error_type} (strategy: {info['strategy']})",
                }

    # Unknown error
    return {
        "recoverable": False,
        "error_type": "UNKNOWN",
        "strategy": None,
        "message": "Unclassified CP2K error — manual inspection required",
    }


def run_cp2k_with_recovery(
    input_file: str,
    output_file: Optional[str] = None,
    max_retries: int = 2,
    use_mpi: bool = True,
    nprocs: int = -1,
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Run CP2K with automatic error classification and recovery.

    On failure, classifies the error and attempts recovery:
    - SCF non-convergence: relaxes EPS_SCF, increases MAX_SCF, adjusts mixing
    - OT + k-point conflict: switches to DIAGONALIZATION
    - Cholesky failure: adjusts preconditioner
    - Unrecoverable errors (OOM, missing files, bad geometry): fails immediately

    Args:
        input_file: CP2K input file name.
        output_file: Output file name. Auto-derived if None.
        max_retries: Maximum recovery attempts (default 2).
        use_mpi: Use MPI parallelization (default True).
        nprocs: Number of MPI ranks (-1 for auto).
        cwd: Working directory.
        timeout: Timeout in seconds.

    Returns:
        Dict with keys:
        - success: bool
        - result: CompletedProcess from final run
        - attempts: number of attempts made
        - recovery_log: list of recovery actions taken
        - output_file: path to output file
    """
    if output_file is None:
        base = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f"{base}.out"

    recovery_log = []
    current_input = input_file
    work = cwd or WORK_DIR
    current_use_mpi = use_mpi
    current_nprocs = nprocs

    for attempt in range(1 + max_retries):
        logging.info(f"CP2K run attempt {attempt + 1}/{1 + max_retries}: {current_input}")

        # Run CP2K
        timeout_classification = None
        try:
            if current_use_mpi:
                result = run_cp2k_mpi(
                    current_input, output_file, nprocs=current_nprocs, cwd=work, timeout=timeout
                )
            else:
                result = run_cp2k(current_input, output_file, cwd=work, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            timeout_message = f"CP2K timed out after {timeout}s"
            result = subprocess.CompletedProcess(
                args=exc.cmd or current_input,
                returncode=124,
                stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                stderr=((exc.stderr or "") + f"\n{timeout_message}").strip(),
            )
            timeout_classification = {
                "recoverable": attempt < max_retries,
                "error_type": "TIMEOUT",
                "strategy": "reduce_parallelism" if attempt < max_retries else None,
                "message": timeout_message,
            }

        # Success
        if result.returncode == 0:
            logging.info(f"CP2K succeeded on attempt {attempt + 1}")
            return {
                "success": True,
                "result": result,
                "attempts": attempt + 1,
                "recovery_log": recovery_log,
                "output_file": os.path.join(work, output_file),
            }

        # Read output for error classification
        out_path = os.path.join(work, output_file)
        out_text = ""
        if os.path.isfile(out_path):
            with open(out_path) as f:
                out_text = f.read()

        classification = timeout_classification or classify_cp2k_error(out_text, result.stderr or "")
        recovery_log.append({
            "attempt": attempt + 1,
            "error": classification,
            "parallel_mode": "MPI" if current_use_mpi else "OMP",
        })

        logging.warning(f"  {classification['message']}")

        # No more retries or unrecoverable
        if attempt >= max_retries or not classification["recoverable"]:
            break

        # Apply recovery strategy
        strategy = classification["strategy"]
        logging.info(f"  Applying recovery strategy: {strategy}")

        inp_path = os.path.join(work, current_input)
        with open(inp_path) as f:
            inp_content = f.read()

        if strategy == "adjust_scf":
            # Relax convergence, increase iterations, adjust mixing
            inp_content = re.sub(r"EPS_SCF\s+\S+", "EPS_SCF 1.0E-5", inp_content)
            inp_content = re.sub(r"MAX_SCF\s+\d+", "MAX_SCF 200", inp_content)
            inp_content = re.sub(r"ALPHA\s+[\d.]+", "ALPHA 0.2", inp_content)
            recovery_log[-1]["action"] = "Relaxed EPS_SCF→1E-5, MAX_SCF→200, ALPHA→0.2"

        elif strategy == "switch_to_diag":
            # Replace OT block with DIAGONALIZATION
            inp_content = re.sub(
                r"&OT ON.*?&END OT",
                "&DIAGONALIZATION\n        ALGORITHM STANDARD\n      &END DIAGONALIZATION",
                inp_content, flags=re.DOTALL,
            )
            # Add MIXING if not present
            if "&MIXING" not in inp_content:
                inp_content = inp_content.replace(
                    "&END DIAGONALIZATION",
                    "&END DIAGONALIZATION\n      &MIXING\n        METHOD BROYDEN_MIXING\n        ALPHA 0.4\n      &END MIXING",
                )
            # Add ADDED_MOS if not present
            if "ADDED_MOS" not in inp_content:
                inp_content = inp_content.replace(
                    "SCF_GUESS", "ADDED_MOS 20\n      SCF_GUESS",
                )
            recovery_log[-1]["action"] = "Switched OT→DIAGONALIZATION with Broyden mixing"

        elif strategy == "harden_open_shell_scf":
            # Harden SCF for open-shell transition metal systems that crashed
            # with MPI_ABORT/SIGABRT — typically caused by SCF divergence in
            # UKS calculations on d-block metals. Apply conservative settings:
            #   - Enable smearing (Fermi-Dirac) if not present
            #   - Lower mixing alpha to 0.05
            #   - Add level shift (0.1 eV)
            #   - Increase ADDED_MOS to 30
            #   - Increase MAX_SCF to 200
            actions = []

            # Lower mixing alpha
            if re.search(r"ALPHA\s+[\d.]+", inp_content):
                inp_content = re.sub(r"ALPHA\s+[\d.]+", "ALPHA 0.05", inp_content)
            actions.append("ALPHA→0.05")

            # Increase MAX_SCF
            inp_content = re.sub(r"MAX_SCF\s+\d+", "MAX_SCF 200", inp_content)
            actions.append("MAX_SCF→200")

            # Increase ADDED_MOS
            if re.search(r"ADDED_MOS\s+\d+", inp_content):
                inp_content = re.sub(r"ADDED_MOS\s+\d+", "ADDED_MOS 30", inp_content)
            else:
                inp_content = inp_content.replace(
                    "SCF_GUESS", "ADDED_MOS 30\n      SCF_GUESS",
                )
            actions.append("ADDED_MOS→30")

            # Add level shift if not present
            if "LEVEL_SHIFT" not in inp_content:
                inp_content = inp_content.replace(
                    "SCF_GUESS", "LEVEL_SHIFT [eV] 0.1\n      SCF_GUESS",
                )
                actions.append("LEVEL_SHIFT→0.1eV")

            # Add smearing if not present
            if "&SMEAR" not in inp_content:
                smear_block = (
                    "      &SMEAR ON\n"
                    "        METHOD FERMI_DIRAC\n"
                    "        ELECTRONIC_TEMPERATURE [K] 300\n"
                    "      &END SMEAR"
                )
                inp_content = inp_content.replace(
                    "SCF_GUESS", f"{smear_block}\n      SCF_GUESS",
                )
                actions.append("SMEAR→FD/300K")

            recovery_log[-1]["action"] = (
                f"Hardened open-shell SCF: {', '.join(actions)}"
            )

        elif strategy == "reduce_parallelism":
            if current_use_mpi:
                current_use_mpi = False
                current_nprocs = 1
                recovery_log[-1]["action"] = (
                    "Switched from MPI+OMP to OMP-only after timeout"
                )
            else:
                current_nprocs = 1
                recovery_log[-1]["action"] = (
                    "Retried in OMP-only mode after timeout"
                )

        # Write modified input for retry
        retry_name = f"{os.path.splitext(current_input)[0]}_retry{attempt + 1}.inp"
        retry_path = os.path.join(work, retry_name)
        with open(retry_path, "w") as f:
            f.write(inp_content)

        # Try to use restart wavefunction if available
        project = os.path.splitext(current_input)[0]
        restart = find_restart_files(project, work)
        if restart["wfn"]:
            inp_content = inp_content.replace("SCF_GUESS ATOMIC", "SCF_GUESS RESTART")
            if "WFN_RESTART_FILE_NAME" not in inp_content:
                inp_content = inp_content.replace(
                    "SCF_GUESS RESTART",
                    f"SCF_GUESS RESTART\n      WFN_RESTART_FILE_NAME {restart['wfn']}",
                )
            with open(retry_path, "w") as f:
                f.write(inp_content)
            recovery_log[-1]["used_restart_wfn"] = True

        current_input = retry_name
        output_file = f"{os.path.splitext(retry_name)[0]}.out"

    logging.error(f"CP2K failed after {attempt + 1} attempts")
    return {
        "success": False,
        "result": result,
        "attempts": attempt + 1,
        "recovery_log": recovery_log,
        "output_file": os.path.join(work, output_file),
    }


# =============================================================================
# MOLECULE PREPARATION (via ASE)
# =============================================================================


def prepare_molecule_input(
    source: str,
    format: Optional[str] = None,
    charge: int = 0,
    multiplicity: int = 1,
    cell_padding: float = 10.0,
) -> Dict[str, Any]:
    """Prepare a molecule from various input formats for CP2K calculation.

    Uses ASE to read structures from XYZ, PDB, CIF, SDF, MOL2, POSCAR,
    and other formats. Validates elements against available GTH pseudopotentials
    and generates a structure dict ready for generate_input().

    Args:
        source: File path to a structure file readable by ASE.
        format: ASE format string (auto-detected if None).
        charge: System charge.
        multiplicity: Spin multiplicity.
        cell_padding: Vacuum padding in Angstroms for non-periodic systems.

    Returns:
        Structure dict compatible with generate_input():
        - coords: list of [symbol, x, y, z]
        - cell: [a, b, c] or [[ax,ay,az], ...]
        - periodic: 'XYZ' or 'NONE'
        - charge: int
        - multiplicity: int
        - n_atoms: int
        - elements: sorted list of unique elements
        - validated: bool — True if all elements have GTH pseudopotentials

    Raises:
        FileNotFoundError: If source file doesn't exist.
        ValueError: If elements are not supported by GTH pseudopotentials.
    """
    if not os.path.isfile(source):
        raise FileNotFoundError(f"Structure file not found: {source}")

    try:
        from ase.io import read as ase_read
    except ImportError as exc:
        raise ImportError(
            "prepare_molecule_input requires ASE (`from ase.io import read`). "
            "ASE is available in the CP2K agent container but is not installed in "
            "this local Python environment."
        ) from exc

    atoms = ase_read(source, format=format)

    # Extract coordinates
    coords = []
    for atom in atoms:
        coords.append([atom.symbol, float(atom.position[0]),
                        float(atom.position[1]), float(atom.position[2])])

    elements = sorted(set(a[0] for a in coords))

    # Validate elements against GTH pseudopotential coverage
    unsupported = []
    for elem in elements:
        try:
            _get_valence_electrons(elem, "GTH-PBE")
        except ValueError:
            unsupported.append(elem)

    if unsupported:
        raise ValueError(
            f"Elements {unsupported} have no GTH pseudopotential support. "
            f"Use structure['element_potentials'] to specify custom potentials, "
            f"or choose a different pseudopotential family."
        )

    # Determine periodicity from ASE cell
    pbc = atoms.get_pbc()
    if all(pbc):
        periodic = "XYZ"
        cell_vecs = atoms.get_cell().tolist()
        cell = cell_vecs
    elif any(pbc):
        periodic = "".join(d for d, p in zip("XYZ", pbc) if p)
        cell_vecs = atoms.get_cell().tolist()
        cell = cell_vecs
    else:
        periodic = "NONE"
        cell = None  # Will be auto-generated by generate_input

    structure = {
        "coords": coords,
        "periodic": periodic,
        "charge": charge,
        "multiplicity": multiplicity,
        "n_atoms": len(coords),
        "elements": elements,
        "validated": True,
    }
    if cell is not None:
        structure["cell"] = cell

    logging.info(f"Prepared molecule from {source}: {len(coords)} atoms, "
                 f"elements={elements}, periodic={periodic}")
    return structure


# =============================================================================
# TRAJECTORY ANALYSIS
# =============================================================================


def analyze_md_trajectory(
    trajectory_file: str,
    analyses: Optional[List[str]] = None,
    output_prefix: str = "md_analysis",
) -> Dict[str, Any]:
    """Analyze an AIMD trajectory using MDAnalysis (if available).

    Computes structural and dynamical properties from CP2K MD trajectories.
    Falls back to numpy-based analysis if MDAnalysis is not installed.

    Args:
        trajectory_file: Path to XYZ trajectory file (e.g., project-pos-1.xyz).
        analyses: List of analyses to run. Options:
            - 'rdf': Radial distribution function (all pairs)
            - 'msd': Mean square displacement
            - 'rmsd': Root-mean-square deviation from first frame
            Defaults to all available analyses.
        output_prefix: Prefix for output files.

    Returns:
        Dict with analysis results keyed by analysis name.
    """
    results = {}
    available_analyses = analyses or ["rdf", "msd", "rmsd"]

    if not os.path.isfile(trajectory_file):
        logging.error(f"Trajectory file not found: {trajectory_file}")
        return {"error": f"File not found: {trajectory_file}"}

    try:
        import MDAnalysis as mda
        from MDAnalysis.analysis import rdf as mda_rdf, msd as mda_msd
        _has_mda = True
    except ImportError:
        _has_mda = False
        logging.info("MDAnalysis not available — using numpy-based trajectory analysis")

    if _has_mda:
        try:
            u = mda.Universe(trajectory_file, format="XYZ")
            n_frames = len(u.trajectory)
            logging.info(f"Loaded trajectory: {n_frames} frames, {u.atoms.n_atoms} atoms")

            if "rdf" in available_analyses:
                try:
                    rdf_calc = mda_rdf.InterRDF(u.atoms, u.atoms, nbins=100, range=(0.5, 10.0))
                    rdf_calc.run()
                    results["rdf"] = {
                        "bins": rdf_calc.results.bins.tolist(),
                        "rdf": rdf_calc.results.rdf.tolist(),
                        "n_frames": n_frames,
                    }
                    logging.info("  RDF analysis complete")
                except Exception as e:
                    results["rdf"] = {"error": str(e)}
                    logging.warning(f"  RDF analysis failed: {e}")

            if "msd" in available_analyses:
                try:
                    msd_calc = mda_msd.EinsteinMSD(u, select="all", msd_type="xyz")
                    msd_calc.run()
                    results["msd"] = {
                        "timesteps": list(range(n_frames)),
                        "msd": msd_calc.results.timeseries.tolist(),
                        "n_frames": n_frames,
                    }
                    logging.info("  MSD analysis complete")
                except Exception as e:
                    results["msd"] = {"error": str(e)}
                    logging.warning(f"  MSD analysis failed: {e}")

            if "rmsd" in available_analyses:
                try:
                    from MDAnalysis.analysis.rms import RMSD as mda_RMSD
                    rmsd_calc = mda_RMSD(u, u, select="all", ref_frame=0)
                    rmsd_calc.run()
                    results["rmsd"] = {
                        "frames": rmsd_calc.results.rmsd[:, 0].tolist(),
                        "rmsd": rmsd_calc.results.rmsd[:, 2].tolist(),
                        "n_frames": n_frames,
                    }
                    logging.info("  RMSD analysis complete")
                except Exception as e:
                    results["rmsd"] = {"error": str(e)}
                    logging.warning(f"  RMSD analysis failed: {e}")

        except Exception as e:
            results["error"] = f"MDAnalysis trajectory loading failed: {e}"
            logging.error(f"Trajectory analysis failed: {e}")

    else:
        # Numpy-based fallback for basic trajectory analysis
        import numpy as np
        try:
            frames = []
            current_frame = []
            with open(trajectory_file) as f:
                lines = f.readlines()
            i = 0
            while i < len(lines):
                try:
                    n_atoms = int(lines[i].strip())
                except (ValueError, IndexError):
                    i += 1
                    continue
                comment = lines[i + 1].strip()
                frame_coords = []
                for j in range(i + 2, min(i + 2 + n_atoms, len(lines))):
                    parts = lines[j].split()
                    if len(parts) >= 4:
                        frame_coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
                if frame_coords:
                    frames.append(np.array(frame_coords))
                i += 2 + n_atoms

            n_frames = len(frames)
            logging.info(f"Loaded trajectory (numpy): {n_frames} frames")

            if "rmsd" in available_analyses and n_frames > 1:
                ref = frames[0]
                rmsds = []
                for frame in frames:
                    diff = frame - ref
                    rmsds.append(float(np.sqrt(np.mean(np.sum(diff**2, axis=1)))))
                results["rmsd"] = {
                    "frames": list(range(n_frames)),
                    "rmsd": rmsds,
                    "n_frames": n_frames,
                    "method": "numpy",
                }

            if "msd" in available_analyses and n_frames > 1:
                ref = frames[0]
                msds = []
                for frame in frames:
                    diff = frame - ref
                    msds.append(float(np.mean(np.sum(diff**2, axis=1))))
                results["msd"] = {
                    "timesteps": list(range(n_frames)),
                    "msd": msds,
                    "n_frames": n_frames,
                    "method": "numpy",
                }

        except Exception as e:
            results["error"] = f"Numpy trajectory analysis failed: {e}"
            logging.error(f"Trajectory analysis failed: {e}")

    # Save results
    out_path = os.path.join(OUTPUT_DIR, f"{output_prefix}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=_json_serializer)
    logging.info(f"Trajectory analysis saved to {out_path}")

    return results


# =============================================================================
# CLEANUP
# =============================================================================


def cp2k_cleanup(deep: bool = False) -> None:
    """Clean up temporary files.

    Args:
        deep: If True, also remove scratch directory contents.
    """
    patterns_to_clean = ["*.bak", "*.restart.bak*"]
    cleaned = 0
    for pattern in patterns_to_clean:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            try:
                os.remove(f)
                cleaned += 1
            except OSError:
                pass
    if deep:
        _clear_scratch_files()
    if cleaned:
        logging.info(f"Cleaned {cleaned} temporary files")


def _clear_scratch_files() -> None:
    """Remove scratch files."""
    cleared = 0
    try:
        for entry in os.scandir(SCRATCH_DIR):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                    cleared += 1
                except OSError:
                    pass
    except FileNotFoundError:
        pass
    if cleared:
        logging.info(f"Cleared {cleared} scratch files")
