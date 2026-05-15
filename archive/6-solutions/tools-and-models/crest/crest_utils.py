"""
CREST Utilities Library for Microsoft Discovery Platform.

Provides functions for conformational sampling, protonation/deprotonation screening,
tautomer generation, entropy calculations, and ensemble analysis using CREST 3.0 and xtb.

Reference: Pracht et al., J. Chem. Phys. 2024, 160, 114110. DOI: 10.1063/5.0197592
"""

import os
import sys
import json
import shutil
import subprocess
import logging
import traceback
import glob as globmod
from typing import List, Dict, Optional, Tuple, Any, Union
from pathlib import Path

import numpy as np

# ============================================================================
# CONSTANTS
# ============================================================================
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/crest_scratch"

# Physical constants
HARTREE_TO_KCAL = 627.5094740631
HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KJ = 2625.4996394799
R_GAS_KCAL = 0.001987204  # kcal/(mol·K)

# CREST output file names
CREST_CONFORMERS = "crest_conformers.xyz"
CREST_ROTAMERS = "crest_rotamers.xyz"
CREST_BEST = "crest_best.xyz"
CREST_ENERGIES = "crest.energies"


# ============================================================================
# SETUP FUNCTIONS
# ============================================================================
def quick_setup(input_dir: str = '/input', output_dir: str = '/output',
                work_dir: str = '/workdir') -> None:
    """Initialize the working environment.

    Args:
        input_dir: Path to input files (read-only mount).
        output_dir: Path for output files (persistent after job).
        work_dir: Writable working directory for calculations.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR = input_dir
    OUTPUT_DIR = output_dir
    WORK_DIR = work_dir

    # Setup logging with line buffering
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    try:
        sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
        sys.stderr = open(sys.stderr.fileno(), mode='w', buffering=1)
    except Exception:
        pass  # Non-TTY environments may not support this

    # Create directories
    for d in [OUTPUT_DIR, WORK_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)

    # Copy input files to working directory
    if os.path.isdir(input_dir):
        for f in os.listdir(input_dir):
            src = os.path.join(input_dir, f)
            dst = os.path.join(work_dir, f)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                logging.info(f"Copied input: {f}")

    os.chdir(work_dir)
    logging.info(f"Working directory: {work_dir}")
    logging.info(f"Input files: {os.listdir(input_dir) if os.path.isdir(input_dir) else 'none'}")

    # Version checks
    logging.info(f"CREST: {get_crest_version()}")
    logging.info(f"xtb:   {get_xtb_version()}")
    logging.info(f"CPUs:  {get_available_threads()}")


def quick_finish() -> None:
    """Copy key output files to the output directory."""
    output_patterns = [
        "crest_conformers.xyz", "crest_rotamers.xyz", "crest_best.xyz",
        "crest.energies", "crest_ensemble.xyz",
        "protonated.xyz", "deprotonated.xyz", "tautomers.xyz",
        "crest_msreact_products.xyz", "crestopt.xyz",
        "*.png", "*.pdf", "final_results.json", "*.log",
    ]
    copied = []
    for pattern in output_patterns:
        for f in globmod.glob(os.path.join(WORK_DIR, pattern)):
            dst = os.path.join(OUTPUT_DIR, os.path.basename(f))
            if not os.path.exists(dst):
                try:
                    shutil.copy2(f, dst)
                    copied.append(os.path.basename(f))
                except Exception:
                    pass
    logging.info(f"Copied {len(copied)} files to output: {copied[:20]}")


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None,
                       status: str = "completed") -> None:
    """Save structured results to final_results.json.

    The output JSON has the structure:
        {"status": "...", "results": <results>, "output_files": {...}, ...}

    NOTE: Unlike other agents that use a ``'summary'`` key, CREST stores
    the results dict under the ``'results'`` key. Downstream agents reading
    this file must access ``data['results']``.

    Args:
        results: Dictionary of calculation results.
        output_files: Optional mapping of output file categories to filenames.
        file_descriptions: Optional descriptions for output files.
        status: Job status ('completed', 'failed', 'partial').
    """
    final = {
        "status": status,
        "results": results,
    }
    if output_files:
        final["output_files"] = output_files
    if file_descriptions:
        final["file_descriptions"] = file_descriptions

    for path in [os.path.join(OUTPUT_DIR, "final_results.json"),
                 os.path.join(WORK_DIR, "final_results.json")]:
        try:
            with open(path, 'w') as f:
                json.dump(final, f, indent=2, default=_json_serializer)
        except Exception:
            pass
    logging.info(f"Results saved (status={status})")


def _json_serializer(obj: Any) -> Any:
    """Handle numpy types and other non-serializable objects."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


# ============================================================================
# VERSION AND ENVIRONMENT
# ============================================================================
def get_crest_version() -> str:
    """Get CREST version string."""
    try:
        result = subprocess.run(['crest', '--version'], capture_output=True,
                                text=True, timeout=30)
        output = result.stdout + result.stderr
        for line in output.split('\n'):
            low = line.lower()
            if 'version' in low or 'crest' in low:
                stripped = line.strip()
                if stripped:
                    return stripped
        return output.strip()[:120]
    except Exception:
        return "unknown"


def get_xtb_version() -> str:
    """Get xtb version string."""
    try:
        result = subprocess.run(['xtb', '--version'], capture_output=True,
                                text=True, timeout=30)
        output = result.stdout + result.stderr
        for line in output.split('\n'):
            low = line.lower()
            if 'version' in low or 'xtb' in low:
                stripped = line.strip()
                if stripped:
                    return stripped
        return output.strip()[:120]
    except Exception:
        return "unknown"


def get_available_threads() -> int:
    """Get the number of available CPU threads."""
    return os.cpu_count() or 4


# ============================================================================
# COMMAND EXECUTION
# ============================================================================
def run_command(cmd: List[str], cwd: str = None, timeout: int = 7200,
                env: Dict = None, input_text: str = None) -> subprocess.CompletedProcess:
    """Execute a shell command with logging and error handling.

    Args:
        cmd: Command and arguments as a list.
        cwd: Working directory (defaults to WORK_DIR).
        timeout: Maximum execution time in seconds.
        env: Additional environment variables (merged with os.environ).
        input_text: Optional stdin text.

    Returns:
        subprocess.CompletedProcess with stdout/stderr.

    Raises:
        subprocess.TimeoutExpired: If command exceeds timeout.
    """
    if cwd is None:
        cwd = WORK_DIR

    cmd_str = ' '.join(str(c) for c in cmd)
    logging.info(f"Running: {cmd_str}")

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, env=run_env, input=input_text
        )

        if result.stdout:
            lines = result.stdout.strip().split('\n')
            display = lines[-50:] if len(lines) > 50 else lines
            if len(lines) > 50:
                logging.info(f"stdout (last 50 of {len(lines)} lines):")
            for line in display:
                logging.info(f"  {line}")

        if result.returncode != 0:
            logging.warning(f"Exit code {result.returncode}")
            if result.stderr:
                logging.warning(f"stderr (tail): {result.stderr[-1000:]}")

        return result

    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout}s: {cmd_str}")
        raise
    except Exception as e:
        logging.error(f"Command failed: {cmd_str}: {e}")
        raise


def run_crest(coord_file: Optional[str] = None, args: List[str] = None,
              work_dir: str = None, timeout: int = 7200,
              nthreads: int = None) -> subprocess.CompletedProcess:
    """Run CREST with specified arguments.

    Args:
        coord_file: Input coordinate file (XYZ or coord format). None for
                    standalone operations like --cregen.
        args: Additional CREST command-line arguments.
        work_dir: Working directory for the calculation.
        timeout: Maximum execution time in seconds.
        nthreads: Number of CPU threads (auto-detected if None).

    Returns:
        subprocess.CompletedProcess with stdout/stderr.
    """
    if work_dir is None:
        work_dir = WORK_DIR
    if args is None:
        args = []
    if nthreads is None:
        nthreads = get_available_threads()

    cmd = ['crest']
    if coord_file:
        cmd.append(coord_file)
    cmd.extend(args)

    # Add thread count if not already specified
    args_str = ' '.join(str(a) for a in args)
    if '--T ' not in args_str and '-T ' not in args_str:
        cmd.extend(['--T', str(nthreads)])

    env = {'OPENBLAS_NUM_THREADS': '1', 'OMP_STACKSIZE': '4G'}
    return run_command(cmd, cwd=work_dir, timeout=timeout, env=env)


def run_xtb(coord_file: str, args: List[str] = None, work_dir: str = None,
            timeout: int = 3600, nthreads: int = None) -> subprocess.CompletedProcess:
    """Run xtb with specified arguments.

    Args:
        coord_file: Input coordinate file.
        args: Additional xtb command-line arguments.
        work_dir: Working directory.
        timeout: Maximum execution time in seconds.
        nthreads: Number of CPU threads.

    Returns:
        subprocess.CompletedProcess with stdout/stderr.
    """
    if work_dir is None:
        work_dir = WORK_DIR
    if args is None:
        args = []
    if nthreads is None:
        nthreads = get_available_threads()

    cmd = ['xtb', coord_file] + args

    args_str = ' '.join(str(a) for a in args)
    if '--parallel' not in args_str and '-P' not in args_str:
        cmd.extend(['--parallel', str(nthreads)])

    env = {'OPENBLAS_NUM_THREADS': '1', 'OMP_STACKSIZE': '4G',
           'OMP_NUM_THREADS': str(nthreads)}
    return run_command(cmd, cwd=work_dir, timeout=timeout, env=env)


# ============================================================================
# MOLECULAR INPUT HANDLING
# ============================================================================
def smiles_to_xyz(smiles: str, output_file: str = 'molecule.xyz',
                  optimize: bool = True) -> str:
    """Convert a SMILES string to an XYZ file using RDKit.

    Args:
        smiles: SMILES string of the molecule.
        output_file: Output XYZ filename.
        optimize: Whether to MMFF-optimize the 3D geometry.

    Returns:
        Absolute path to the generated XYZ file.

    Raises:
        ValueError: If SMILES is invalid or 3D embedding fails.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdmolfiles

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")

    mol = Chem.AddHs(mol)

    # Generate 3D coordinates with ETKDGv3
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    result = AllChem.EmbedMolecule(mol, params)
    if result == -1:
        # Retry without seed constraint
        params2 = AllChem.ETKDGv3()
        result = AllChem.EmbedMolecule(mol, params2)
        if result == -1:
            raise ValueError(f"Could not generate 3D coordinates for: {smiles}")

    if optimize:
        try:
            AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
        except Exception:
            logging.warning(f"MMFF optimization failed for {smiles}, using unoptimized geometry")

    output_path = os.path.join(WORK_DIR, output_file) if not os.path.isabs(output_file) else output_file
    rdmolfiles.MolToXYZFile(mol, output_path)

    logging.info(f"SMILES '{smiles}' -> {output_file} ({mol.GetNumAtoms()} atoms)")
    return output_path


def smiles_list_to_xyz(smiles_list: List[str], prefix: str = 'mol') -> List[str]:
    """Convert multiple SMILES to individual XYZ files.

    Args:
        smiles_list: List of SMILES strings.
        prefix: Filename prefix for output files.

    Returns:
        List of absolute paths to successfully generated XYZ files.
    """
    xyz_files = []
    for i, smi in enumerate(smiles_list):
        try:
            xyz_file = smiles_to_xyz(smi, f"{prefix}_{i:03d}.xyz")
            xyz_files.append(xyz_file)
        except Exception as e:
            logging.warning(f"Failed to convert SMILES '{smi}': {e}")
    return xyz_files


def read_xyz_file(filename: str) -> Tuple[List[str], np.ndarray, str]:
    """Read an XYZ file.

    Args:
        filename: Path to XYZ file (absolute or relative to WORK_DIR).

    Returns:
        Tuple of (atom_symbols, coordinates_array, comment_line).
    """
    filepath = os.path.join(WORK_DIR, filename) if not os.path.isabs(filename) else filename

    with open(filepath, 'r') as f:
        lines = f.readlines()

    n_atoms = int(lines[0].strip())
    comment = lines[1].strip() if len(lines) > 1 else ""

    atoms = []
    coords = []
    for line in lines[2:2 + n_atoms]:
        parts = line.split()
        atoms.append(parts[0])
        coords.append([float(parts[1]), float(parts[2]), float(parts[3])])

    return atoms, np.array(coords), comment


def write_xyz_file(atoms: List[str], coords: np.ndarray, filename: str,
                   comment: str = "") -> str:
    """Write an XYZ file.

    Args:
        atoms: List of atom symbols.
        coords: Nx3 array of coordinates in Angstrom.
        filename: Output path (absolute or relative to WORK_DIR).
        comment: Comment line content.

    Returns:
        Absolute path to the written file.
    """
    filepath = os.path.join(WORK_DIR, filename) if not os.path.isabs(filename) else filename

    with open(filepath, 'w') as f:
        f.write(f"{len(atoms)}\n")
        f.write(f"{comment}\n")
        for atom, (x, y, z) in zip(atoms, coords):
            f.write(f"{atom:2s} {x:15.8f} {y:15.8f} {z:15.8f}\n")

    return filepath


# ============================================================================
# CONFORMATIONAL SEARCH
# ============================================================================
def conformer_search(coord_file: str, method: str = 'gfn2',
                     solvent: str = None, ewin: float = 6.0,
                     charge: int = 0, uhf: int = 0,
                     nthreads: int = None, additional_args: List[str] = None,
                     work_dir: str = None, timeout: int = 7200) -> Dict:
    """Run a CREST conformational search (iMTD-GC algorithm, default).

    Args:
        coord_file: Input coordinate file (XYZ or coord format).
        method: Level of theory ('gfn2', 'gfn1', 'gfnff', 'gfn2//gfnff').
        solvent: ALPB solvent name (e.g., 'h2o', 'chcl3', 'dmso'). None = gas phase.
        ewin: Energy window in kcal/mol for conformer selection.
        charge: Molecular charge.
        uhf: Number of unpaired electrons (N_alpha - N_beta).
        nthreads: CPU threads (auto-detected if None).
        additional_args: Extra CREST flags (e.g., ['--quick'], ['--nci']).
        work_dir: Working directory for this calculation.
        timeout: Maximum runtime in seconds.

    Returns:
        Dict with keys: n_conformers, energies, conformers, boltzmann,
        statistics, converged, output_files, exit_code, warnings.
    """
    args = []

    method_map = {
        'gfn2': ['--gfn2'],
        'gfn1': ['--gfn1'],
        'gfnff': ['--gfnff'],
        'gff': ['--gfnff'],
        'gfn2//gfnff': ['--gfn2//gfnff'],
    }
    if method.lower() in method_map:
        args.extend(method_map[method.lower()])

    if solvent:
        args.extend(['--alpb', solvent])

    args.extend(['--ewin', str(ewin)])

    if charge != 0:
        args.extend(['--chrg', str(charge)])
    if uhf != 0:
        args.extend(['--uhf', str(uhf)])

    if additional_args:
        args.extend(additional_args)

    result = run_crest(coord_file, args, work_dir=work_dir,
                       timeout=timeout, nthreads=nthreads)

    return _parse_conformer_search_results(work_dir or WORK_DIR, result)


def quick_conformer_search(coord_file: str, method: str = 'gfn2',
                           solvent: str = None, charge: int = 0,
                           nthreads: int = None,
                           work_dir: str = None) -> Dict:
    """Quick conformer search with reduced settings (--quick).

    Faster but less thorough than the full iMTD-GC search. Good for
    initial screening or when time is limited.
    """
    return conformer_search(
        coord_file, method=method, solvent=solvent, charge=charge,
        nthreads=nthreads, additional_args=['--quick'], work_dir=work_dir
    )


def superquick_conformer_search(coord_file: str, method: str = 'gfnff',
                                solvent: str = None, charge: int = 0,
                                nthreads: int = None,
                                work_dir: str = None) -> Dict:
    """Super-quick conformer search (--squick) with GFN-FF.

    Very fast but lower accuracy. Use for large molecule screening.
    """
    return conformer_search(
        coord_file, method=method, solvent=solvent, charge=charge,
        nthreads=nthreads, additional_args=['--squick'], work_dir=work_dir
    )


def nci_conformer_search(coord_file: str, method: str = 'gfn2',
                         solvent: str = None, charge: int = 0,
                         nthreads: int = None, work_dir: str = None,
                         timeout: int = 7200) -> Dict:
    """NCI mode conformer search for non-covalent complexes.

    Adds an ellipsoid potential and adjusts MTD bias parameters for
    better sampling of aggregates, dimers, and host-guest systems.
    """
    return conformer_search(
        coord_file, method=method, solvent=solvent, charge=charge,
        nthreads=nthreads, additional_args=['--nci'],
        work_dir=work_dir, timeout=timeout
    )


def imtd_smtd_search(coord_file: str, method: str = 'gfn2',
                     solvent: str = None, charge: int = 0,
                     nthreads: int = None, work_dir: str = None,
                     timeout: int = 7200) -> Dict:
    """iMTD-sMTD sampling (--v4) for improved conformer search.

    Uses static metadynamics simulations. Often better convergence
    than iMTD-GC for very flexible systems.
    """
    return conformer_search(
        coord_file, method=method, solvent=solvent, charge=charge,
        nthreads=nthreads, additional_args=['--v4'],
        work_dir=work_dir, timeout=timeout
    )


def constrained_conformer_search(coord_file: str, constraint_file: str,
                                 method: str = 'gfn2', solvent: str = None,
                                 charge: int = 0, nthreads: int = None,
                                 work_dir: str = None,
                                 timeout: int = 7200) -> Dict:
    """Constrained conformational search using xtb constraints.

    Args:
        coord_file: Input structure.
        constraint_file: Path to xTB-format constraint file (.xcontrol).
    """
    return conformer_search(
        coord_file, method=method, solvent=solvent, charge=charge,
        nthreads=nthreads, additional_args=['--cinp', constraint_file],
        work_dir=work_dir, timeout=timeout
    )


# ============================================================================
# PROTONATION / DEPROTONATION / TAUTOMERS
# ============================================================================
def screen_protonation_sites(coord_file: str, method: str = 'gfn2',
                             solvent: str = None, charge: int = 0,
                             nthreads: int = None,
                             work_dir: str = None,
                             timeout: int = 7200) -> Dict:
    """Screen protonation sites and rank by energy.

    Args:
        coord_file: Input structure (neutral molecule).
        method: Level of theory.
        solvent: Implicit solvent (recommended: 'h2o').

    Returns:
        Dict with n_structures, structures, energies, boltzmann, converged.
    """
    args = ['--protonate']
    if method.lower() == 'gfn2':
        args.append('--gfn2')
    elif method.lower() == 'gfn1':
        args.append('--gfn1')
    if solvent:
        args.extend(['--alpb', solvent])
    if charge != 0:
        args.extend(['--chrg', str(charge)])

    result = run_crest(coord_file, args, work_dir=work_dir,
                       nthreads=nthreads, timeout=timeout)
    return _parse_protonation_results(work_dir or WORK_DIR, result, 'protonated')


def screen_deprotonation_sites(coord_file: str, method: str = 'gfn2',
                               solvent: str = None, charge: int = 0,
                               nthreads: int = None,
                               work_dir: str = None,
                               timeout: int = 7200) -> Dict:
    """Screen deprotonation sites (acidic hydrogen removal)."""
    args = ['--deprotonate']
    if method.lower() == 'gfn2':
        args.append('--gfn2')
    elif method.lower() == 'gfn1':
        args.append('--gfn1')
    if solvent:
        args.extend(['--alpb', solvent])
    if charge != 0:
        args.extend(['--chrg', str(charge)])

    result = run_crest(coord_file, args, work_dir=work_dir,
                       nthreads=nthreads, timeout=timeout)
    return _parse_protonation_results(work_dir or WORK_DIR, result, 'deprotonated')


def screen_tautomers(coord_file: str, method: str = 'gfn2',
                     solvent: str = None, charge: int = 0,
                     nthreads: int = None, work_dir: str = None,
                     timeout: int = 7200) -> Dict:
    """Screen prototropic tautomers."""
    args = ['--tautomerize']
    if method.lower() == 'gfn2':
        args.append('--gfn2')
    elif method.lower() == 'gfn1':
        args.append('--gfn1')
    if solvent:
        args.extend(['--alpb', solvent])
    if charge != 0:
        args.extend(['--chrg', str(charge)])

    result = run_crest(coord_file, args, work_dir=work_dir,
                       nthreads=nthreads, timeout=timeout)
    return _parse_protonation_results(work_dir or WORK_DIR, result, 'tautomers')


# ============================================================================
# ENTROPY CALCULATIONS
# ============================================================================
def compute_conformational_entropy(coord_file: str, method: str = 'gfn2',
                                   solvent: str = None, charge: int = 0,
                                   nthreads: int = None,
                                   work_dir: str = None,
                                   timeout: int = 14400) -> Dict:
    """Calculate conformational entropy using CREST's entropy mode.

    Uses the iMTD-sMTD workflow with rovibrational averaging (S_msRRHO).
    Computationally expensive — consider --v4 for a faster estimate.

    Returns:
        Dict with conformational_entropy, temperatures, entropies, converged.
    """
    args = ['--entropy']
    if method.lower() == 'gfn2':
        args.append('--gfn2')
    elif method.lower() == 'gfn1':
        args.append('--gfn1')
    if solvent:
        args.extend(['--alpb', solvent])
    if charge != 0:
        args.extend(['--chrg', str(charge)])

    result = run_crest(coord_file, args, work_dir=work_dir,
                       timeout=timeout, nthreads=nthreads)
    return _parse_entropy_results(work_dir or WORK_DIR, result)


# ============================================================================
# GEOMETRY OPTIMIZATION (STANDALONE ANCOPT)
# ============================================================================
def optimize_geometry(coord_file: str, method: str = 'gfn2',
                      level: str = 'vtight', solvent: str = None,
                      charge: int = 0, uhf: int = 0,
                      nthreads: int = None,
                      work_dir: str = None) -> Dict:
    """Standalone geometry optimization.

    Tries CREST's ANCOPT optimizer first; falls back to xtb --opt if CREST
    encounters the Fortran format bug in conda-forge build 3.0.2.

    Args:
        coord_file: Input structure.
        method: Level of theory ('gfn2', 'gfn1', 'gfnff').
        level: Convergence level ('crude', 'sloppy', 'loose', 'lax',
               'normal', 'tight', 'vtight', 'extreme').
        solvent: Implicit solvent name.
        charge: Molecular charge.
        uhf: Number of unpaired electrons.

    Returns:
        Dict with optimized_energy_hartree, optimized_structure, converged.
    """
    args = ['--opt', level]

    method_map = {
        'gfn2': '--gfn2', 'gfn1': '--gfn1',
        'gfnff': '--gfnff', 'gff': '--gfnff',
    }
    flag = method_map.get(method.lower())
    if flag:
        args.append(flag)
    if solvent:
        args.extend(['--alpb', solvent])
    if charge != 0:
        args.extend(['--chrg', str(charge)])
    if uhf != 0:
        args.extend(['--uhf', str(uhf)])

    result = run_crest(coord_file, args, work_dir=work_dir, nthreads=nthreads)

    # Fallback to xtb if CREST ancopt hits the Fortran format bug
    if result.returncode != 0 and 'Missing comma between descriptors' in (result.stderr or ''):
        logging.warning("CREST ancopt Fortran bug detected, falling back to xtb --opt")
        xtb_args = ['--opt', level]
        gfn_map = {'gfn2': '2', 'gfn1': '1'}
        gfn = gfn_map.get(method.lower())
        if gfn:
            xtb_args.extend(['--gfn', gfn])
        if solvent:
            xtb_args.extend(['--alpb', solvent])
        if charge != 0:
            xtb_args.extend(['--chrg', str(charge)])
        if uhf != 0:
            xtb_args.extend(['--uhf', str(uhf)])
        result = run_xtb(coord_file, xtb_args, work_dir=work_dir, nthreads=nthreads)

    return _parse_optimization_results(work_dir or WORK_DIR, result)


# ============================================================================
# QCG (QUANTUM CLUSTER GROWTH) — EXPLICIT SOLVATION
# ============================================================================
def qcg_grow(solute_file: str, solvent_file: str, nsolv: int = 10,
             method: str = 'gfn2', charge: int = 0,
             nthreads: int = None, work_dir: str = None,
             timeout: int = 14400) -> Dict:
    """Run QCG explicit solvation cluster growth.

    Builds a microsolvation cluster by iteratively adding solvent molecules
    around the solute. Requires external xtb (installed in container).

    Args:
        solute_file: Solute structure (XYZ).
        solvent_file: Solvent molecule structure (XYZ).
        nsolv: Number of solvent molecules to add.
        method: Level of theory.
        charge: Solute charge.

    Returns:
        Dict with cluster_file, converged, exit_code.
    """
    args = ['--qcg', solvent_file, '--nsolv', str(nsolv)]
    if method.lower() == 'gfn2':
        args.append('--gfn2')
    if charge != 0:
        args.extend(['--chrg', str(charge)])

    result = run_crest(solute_file, args, work_dir=work_dir,
                       timeout=timeout, nthreads=nthreads)
    return _parse_qcg_results(work_dir or WORK_DIR, result)


# ============================================================================
# MSREACT (MASS SPECTRAL REACTION)
# ============================================================================
def run_msreact(coord_file: str, method: str = 'gfn2',
                charge: int = 0, nthreads: int = None,
                work_dir: str = None, timeout: int = 7200,
                additional_args: List[str] = None) -> Dict:
    """Run MSREACT mass spectral fragment prediction.

    Generates possible fragmentation products for mass spectrometry prediction.

    Returns:
        Dict with n_products, products, converged, exit_code.
    """
    args = ['--msreact']
    if method.lower() == 'gfn2':
        args.append('--gfn2')
    if charge != 0:
        args.extend(['--chrg', str(charge)])
    if additional_args:
        args.extend(additional_args)

    result = run_crest(coord_file, args, work_dir=work_dir,
                       timeout=timeout, nthreads=nthreads)
    return _parse_msreact_results(work_dir or WORK_DIR, result)


# ============================================================================
# ENSEMBLE SORTING (CREGEN) AND CLUSTERING
# ============================================================================
def sort_ensemble(ensemble_file: str, ewin: float = 6.0,
                  rthr: float = 0.125, ethr: float = 0.05,
                  work_dir: str = None) -> Dict:
    """Sort/filter an ensemble using CREGEN standalone.

    Args:
        ensemble_file: Multi-XYZ ensemble file.
        ewin: Energy window in kcal/mol.
        rthr: RMSD threshold in Angstrom.
        ethr: Energy threshold between pairs in kcal/mol.

    Returns:
        Dict with n_conformers, n_rotamers, exit_code.
    """
    args = ['--cregen', ensemble_file,
            '--ewin', str(ewin), '--rthr', str(rthr), '--ethr', str(ethr)]

    result = run_crest(coord_file=None, args=args, work_dir=work_dir)
    return _parse_cregen_results(work_dir or WORK_DIR, result)


def cluster_ensemble(ensemble_file: str, n_clusters: int = None,
                     mode: str = 'normal', work_dir: str = None) -> Dict:
    """Cluster an ensemble using PCA + k-Means.

    Args:
        ensemble_file: Multi-XYZ ensemble file.
        n_clusters: Fixed number of clusters (None for automatic detection).
        mode: Automatic mode ('loose', 'normal', 'tight', 'vtight').

    Returns:
        Dict with n_clusters, cluster_sizes, exit_code.
    """
    args = ['--cregen', ensemble_file]
    if n_clusters is not None:
        args.extend(['--cluster', str(n_clusters)])
    else:
        args.extend(['--cluster', mode])

    result = run_crest(coord_file=None, args=args, work_dir=work_dir)
    return _parse_cluster_results(work_dir or WORK_DIR, result)


# ============================================================================
# TOML INPUT FILE SUPPORT (CREST 3.0)
# ============================================================================
def _toml_format_value(val: Any) -> str:
    """Format a single value for TOML output."""
    if isinstance(val, bool):  # must check before int (bool is subclass of int)
        return 'true' if val else 'false'
    elif isinstance(val, int):
        return str(val)
    elif isinstance(val, float):
        return str(val)
    elif isinstance(val, str):
        return f'"{val}"'
    elif isinstance(val, list):
        formatted = ', '.join(_toml_format_value(v) for v in val)
        return f'[{formatted}]'
    else:
        return f'"{val}"'


def _toml_serialize(data: Dict, lines: List[str], prefix: str = '') -> None:
    """Recursively serialize a dict to TOML lines.

    Handles arbitrarily nested dicts by emitting dotted section headers
    (e.g. [calculation.level]) as required by the TOML spec.
    """
    # First pass: emit simple key = value pairs at this level
    for key, val in data.items():
        if not isinstance(val, dict):
            lines.append(f'{key} = {_toml_format_value(val)}')

    # Second pass: recurse into nested dict sections
    for key, val in data.items():
        if isinstance(val, dict):
            section_path = f'{prefix}.{key}' if prefix else key
            lines.append('')
            lines.append(f'[{section_path}]')
            _toml_serialize(val, lines, section_path)


def write_crest_input(settings: Dict, filename: str = 'crest_input.toml',
                      work_dir: str = None) -> str:
    """Write a CREST 3.0 TOML input file.

    Supports arbitrarily nested dicts, which are serialized as dotted
    section headers (e.g. ``[calculation.level]``).

    Args:
        settings: Nested dict of CREST settings.
        filename: Output filename.
        work_dir: Directory to write to.

    Returns:
        Absolute path to the written file.
    """
    if work_dir is None:
        work_dir = WORK_DIR

    filepath = os.path.join(work_dir, filename)
    lines: List[str] = []
    _toml_serialize(settings, lines)

    with open(filepath, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    logging.info(f"Written CREST input: {filepath}")
    return filepath


def run_crest_with_input(coord_file: str, input_file: str,
                         nthreads: int = None, work_dir: str = None,
                         timeout: int = 7200) -> subprocess.CompletedProcess:
    """Run CREST with a TOML input file (--input flag).

    For advanced configurations not covered by convenience functions.
    """
    return run_crest(coord_file, ['--input', input_file],
                     work_dir=work_dir, timeout=timeout, nthreads=nthreads)


# ============================================================================
# BATCH PROCESSING
# ============================================================================
def batch_conformer_search(molecules: List[Dict], method: str = 'gfn2',
                           solvent: str = None, ewin: float = 6.0,
                           nthreads: int = None) -> List[Dict]:
    """Run conformer search on multiple molecules with incremental saving.

    Args:
        molecules: List of dicts, each with 'name' and either 'smiles'
                   or 'xyz_file' key.
        method: Level of theory.
        solvent: Implicit solvent.
        ewin: Energy window in kcal/mol.
        nthreads: CPU threads.

    Returns:
        List of result dicts, one per molecule.
    """
    results = []
    checkpoint = os.path.join(OUTPUT_DIR, 'batch_results.json')

    # Resume from checkpoint
    if os.path.exists(checkpoint):
        with open(checkpoint, 'r') as f:
            results = json.load(f)
    done_names = {r.get('name') for r in results if 'error' not in r}

    for i, mol in enumerate(molecules):
        name = mol.get('name', f'mol_{i:03d}')
        if name in done_names:
            logging.info(f"Skipping {name} (already done)")
            continue

        logging.info(f"******* {i+1}/{len(molecules)}: {name} *******")

        mol_dir = os.path.join(WORK_DIR, name)
        os.makedirs(mol_dir, exist_ok=True)

        try:
            if 'smiles' in mol:
                xyz_file = smiles_to_xyz(mol['smiles'],
                                         os.path.join(mol_dir, f'{name}.xyz'))
                xyz_basename = f'{name}.xyz'
            elif 'xyz_file' in mol:
                src = mol['xyz_file']
                if not os.path.isabs(src):
                    src = os.path.join(WORK_DIR, src)
                shutil.copy2(src, mol_dir)
                xyz_basename = os.path.basename(src)
            else:
                results.append({'name': name, 'error': 'no SMILES or xyz_file'})
                continue

            res = conformer_search(
                xyz_basename, method=method, solvent=solvent,
                ewin=ewin, nthreads=nthreads, work_dir=mol_dir
            )
            res['name'] = name
            # Strip large coordinate arrays for checkpoint compactness
            if 'conformers' in res:
                for conf in res['conformers']:
                    if 'coordinates' in conf:
                        conf['coordinates'] = None  # save space
            results.append(res)

        except Exception as e:
            logging.error(f"Error on {name}: {e}")
            traceback.print_exc()
            results.append({'name': name, 'error': str(e)})

        # Incremental save
        with open(checkpoint, 'w') as f:
            json.dump(results, f, indent=2, default=_json_serializer)

    return results


# ============================================================================
# PARSING FUNCTIONS
# ============================================================================
def parse_ensemble(ensemble_file: str, work_dir: str = None) -> List[Dict]:
    """Parse a multi-structure XYZ ensemble file.

    Args:
        ensemble_file: Path to multi-XYZ file (absolute or relative to work_dir).

    Returns:
        List of dicts with keys: index, n_atoms, energy_hartree, atoms,
        coordinates (np.ndarray), comment.
    """
    if work_dir is None:
        work_dir = WORK_DIR

    filepath = os.path.join(work_dir, ensemble_file) \
        if not os.path.isabs(ensemble_file) else ensemble_file

    if not os.path.exists(filepath):
        logging.warning(f"Ensemble file not found: {filepath}")
        return []

    conformers = []
    with open(filepath, 'r') as f:
        lines = f.readlines()

    i = 0
    conf_idx = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        try:
            n_atoms = int(line)
        except ValueError:
            i += 1
            continue

        comment = lines[i + 1].strip() if i + 1 < len(lines) else ""

        # Extract energy from comment (CREST puts energy as first float)
        energy = None
        for token in comment.split():
            try:
                energy = float(token)
                break
            except ValueError:
                continue

        atoms = []
        coords = []
        for j in range(n_atoms):
            idx = i + 2 + j
            if idx >= len(lines):
                break
            parts = lines[idx].split()
            if len(parts) >= 4:
                atoms.append(parts[0])
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])

        # Validate: atom count must match the declared n_atoms
        if len(atoms) != n_atoms:
            logging.warning(
                f"Structure {conf_idx} in {os.path.basename(filepath)}: "
                f"expected {n_atoms} atoms, got {len(atoms)} — skipping"
            )
            i += 2 + n_atoms
            continue

        conformers.append({
            'index': conf_idx,
            'n_atoms': n_atoms,
            'energy_hartree': energy,
            'atoms': atoms,
            'coordinates': np.array(coords),
            'comment': comment,
        })

        conf_idx += 1
        i += 2 + n_atoms

    logging.info(f"Parsed {len(conformers)} structures from {os.path.basename(ensemble_file)}")
    return conformers


def parse_crest_energies(energies_file: str = None,
                         work_dir: str = None) -> List[float]:
    """Parse crest.energies file.

    Args:
        energies_file: Path to energies file (default: 'crest.energies').

    Returns:
        List of energies in Hartree.
    """
    if work_dir is None:
        work_dir = WORK_DIR
    if energies_file is None:
        energies_file = CREST_ENERGIES

    filepath = os.path.join(work_dir, energies_file) \
        if not os.path.isabs(energies_file) else energies_file

    if not os.path.exists(filepath):
        logging.warning(f"Energies file not found: {filepath}")
        return []

    energies = []
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    energies.append(float(parts[1]))
                except ValueError:
                    continue
    return energies


def parse_crest_output(log_text: str) -> Dict:
    """Parse CREST output text for key summary information.

    Args:
        log_text: Combined stdout+stderr text from CREST.

    Returns:
        Dict with n_conformers, n_rotamers, lowest_energy, converged, warnings.
    """
    info = {
        'n_conformers': None,
        'n_rotamers': None,
        'lowest_energy': None,
        'converged': False,
        'warnings': [],
    }

    for line in log_text.split('\n'):
        low = line.strip().lower()

        if 'number of unique conformers' in low:
            for token in line.split():
                if token.isdigit():
                    info['n_conformers'] = int(token)
                    break

        if 'total number unique points' in low:
            for token in line.split():
                if token.isdigit():
                    info['n_rotamers'] = int(token)

        if 'lowest energy' in low:
            for token in line.split():
                try:
                    val = float(token)
                    if abs(val) > 1:
                        info['lowest_energy'] = val
                except ValueError:
                    continue

        if 'crest terminated normally' in low:
            info['converged'] = True

        if 'WARNING' in line or 'Warning' in line:
            info['warnings'].append(line.strip())

    return info


# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================
def compute_boltzmann_populations(energies: List[float],
                                 temperature: float = 298.15) -> Dict:
    """Compute Boltzmann populations from absolute energies in Hartree.

    Args:
        energies: List of energies in Hartree.
        temperature: Temperature in Kelvin.

    Returns:
        Dict with populations, relative_energies_kcal, partition_function,
        dominant_conformer_index, dominant_conformer_population, n_populated.
    """
    if not energies:
        return {'populations': [], 'partition_function': 0.0,
                'relative_energies_kcal': [], 'n_populated': 0}

    energies = np.array(energies)
    rel_kcal = (energies - np.min(energies)) * HARTREE_TO_KCAL

    beta = 1.0 / (R_GAS_KCAL * temperature)
    boltzmann_factors = np.exp(-beta * rel_kcal)
    Z = np.sum(boltzmann_factors)
    populations = boltzmann_factors / Z

    return {
        'populations': populations.tolist(),
        'relative_energies_kcal': rel_kcal.tolist(),
        'partition_function': float(Z),
        'temperature': temperature,
        'dominant_conformer_index': int(np.argmax(populations)),
        'dominant_conformer_population': float(np.max(populations)),
        'n_populated': int(np.sum(populations > 0.01)),
    }


def compute_ensemble_statistics(energies: List[float]) -> Dict:
    """Compute statistical properties of an energy ensemble.

    Args:
        energies: List of energies in Hartree.

    Returns:
        Dict with n_structures, energy range/mean/std in kcal/mol,
        lowest and highest energies in Hartree.
    """
    if not energies:
        return {}

    energies = np.array(energies)
    relative = (energies - np.min(energies)) * HARTREE_TO_KCAL

    return {
        'n_structures': len(energies),
        'lowest_energy_hartree': float(np.min(energies)),
        'highest_energy_hartree': float(np.max(energies)),
        'energy_range_kcal': float(np.max(relative)),
        'mean_relative_energy_kcal': float(np.mean(relative)),
        'std_relative_energy_kcal': float(np.std(relative)),
        'median_relative_energy_kcal': float(np.median(relative)),
    }


def compute_rmsd(coords1: np.ndarray, coords2: np.ndarray,
                 align: bool = True) -> float:
    """Compute RMSD between two coordinate sets.

    When *align* is True (default), performs Kabsch superposition
    (translation + optimal rotation via SVD) before computing RMSD,
    which is the standard approach for comparing molecular conformers.

    Args:
        coords1: Nx3 coordinate array (reference).
        coords2: Nx3 coordinate array (mobile, aligned onto coords1).
        align: If True, apply Kabsch alignment first.

    Returns:
        RMSD in Angstrom.
    """
    c1 = np.asarray(coords1, dtype=float)
    c2 = np.asarray(coords2, dtype=float)

    if align and len(c1) >= 3:
        # Center both structures on their centroids
        c1 = c1 - c1.mean(axis=0)
        c2 = c2 - c2.mean(axis=0)

        # Kabsch algorithm: optimal rotation via SVD of cross-covariance
        H = c2.T @ c1  # 3x3
        U, _S, Vt = np.linalg.svd(H)

        # Correct for reflection (ensure proper rotation)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T

        # Rotate mobile set onto reference
        c2 = (R @ c2.T).T

    diff = c1 - c2
    return float(np.sqrt(np.mean(np.sum(diff**2, axis=1))))


def compute_rmsd_matrix(conformers: List[Dict]) -> np.ndarray:
    """Compute pairwise RMSD matrix for a list of conformers.

    Args:
        conformers: List from parse_ensemble() with 'coordinates' arrays.

    Returns:
        NxN symmetric RMSD matrix.
    """
    n = len(conformers)
    rmsd_matrix = np.zeros((n, n))

    for i in range(n):
        for j in range(i + 1, n):
            c1 = conformers[i].get('coordinates', np.array([]))
            c2 = conformers[j].get('coordinates', np.array([]))
            if len(c1) > 0 and len(c2) > 0 and len(c1) == len(c2):
                rmsd_val = compute_rmsd(c1, c2)
                rmsd_matrix[i, j] = rmsd_val
                rmsd_matrix[j, i] = rmsd_val

    return rmsd_matrix


# ============================================================================
# VISUALIZATION
# ============================================================================
def plot_conformer_energies(energies: List[float],
                            output_file: str = 'conformer_energies.png',
                            title: str = 'Conformer Relative Energies') -> str:
    """Plot conformer relative energies as a bar chart.

    Args:
        energies: Energies in Hartree.
        output_file: Output image filename.
        title: Plot title.

    Returns:
        Absolute path to saved image.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    energies = np.array(energies)
    relative = (energies - np.min(energies)) * HARTREE_TO_KCAL

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(range(len(relative)), relative, color='steelblue', alpha=0.8)
    ax.set_xlabel('Conformer Index', fontsize=12)
    ax.set_ylabel('Relative Energy (kcal/mol)', fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.axhline(y=0, color='r', linestyle='--', alpha=0.3)

    plt.tight_layout()
    filepath = os.path.join(WORK_DIR, output_file) \
        if not os.path.isabs(output_file) else output_file
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved: {filepath}")
    return filepath


def plot_boltzmann_distribution(energies: List[float],
                                temperature: float = 298.15,
                                output_file: str = 'boltzmann_distribution.png') -> str:
    """Plot Boltzmann population distribution (bar + pie chart).

    Args:
        energies: Energies in Hartree.
        temperature: Temperature in Kelvin.
        output_file: Output image filename.

    Returns:
        Absolute path to saved image.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    boltz = compute_boltzmann_populations(energies, temperature)
    pops = boltz['populations']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Bar chart
    ax1.bar(range(len(pops)), pops, color='coral', alpha=0.8)
    ax1.set_xlabel('Conformer Index', fontsize=12)
    ax1.set_ylabel('Population', fontsize=12)
    ax1.set_title(f'Boltzmann Populations (T={temperature:.0f} K)', fontsize=14)

    # Pie chart (top 10)
    sorted_idx = np.argsort(pops)[::-1]
    top_n = min(10, len(pops))
    top_pops = [pops[sorted_idx[i]] for i in range(top_n)]
    top_labels = [f'Conf {sorted_idx[i]}' for i in range(top_n)]
    other = sum(pops[sorted_idx[i]] for i in range(top_n, len(pops)))
    if other > 0.001:
        top_pops.append(other)
        top_labels.append(f'Others ({len(pops) - top_n})')

    ax2.pie(top_pops, labels=top_labels, autopct='%1.1f%%', startangle=90)
    ax2.set_title('Population Distribution', fontsize=14)

    plt.tight_layout()
    filepath = os.path.join(WORK_DIR, output_file) \
        if not os.path.isabs(output_file) else output_file
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved: {filepath}")
    return filepath


def plot_energy_histogram(energies: List[float],
                          output_file: str = 'energy_histogram.png',
                          bins: int = 30) -> str:
    """Plot histogram of conformer energy distribution.

    Args:
        energies: Energies in Hartree.
        output_file: Output image filename.
        bins: Number of histogram bins.

    Returns:
        Absolute path to saved image.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    energies = np.array(energies)
    relative = (energies - np.min(energies)) * HARTREE_TO_KCAL

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(relative, bins=bins, color='teal', alpha=0.7, edgecolor='black')
    ax.set_xlabel('Relative Energy (kcal/mol)', fontsize=12)
    ax.set_ylabel('Count', fontsize=12)
    ax.set_title('Conformer Energy Distribution', fontsize=14)

    plt.tight_layout()
    filepath = os.path.join(WORK_DIR, output_file) \
        if not os.path.isabs(output_file) else output_file
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    return filepath


def plot_rmsd_heatmap(rmsd_matrix: np.ndarray,
                      output_file: str = 'rmsd_heatmap.png') -> str:
    """Plot RMSD heatmap for conformer ensemble.

    Args:
        rmsd_matrix: NxN symmetric RMSD matrix.
        output_file: Output image filename.

    Returns:
        Absolute path to saved image.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(rmsd_matrix, cmap='viridis', aspect='auto')
    plt.colorbar(im, ax=ax, label='RMSD (Å)')
    ax.set_xlabel('Conformer Index', fontsize=12)
    ax.set_ylabel('Conformer Index', fontsize=12)
    ax.set_title('Pairwise RMSD Matrix', fontsize=14)

    plt.tight_layout()
    filepath = os.path.join(WORK_DIR, output_file) \
        if not os.path.isabs(output_file) else output_file
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    return filepath


# ============================================================================
# INTERNAL PARSING HELPERS
# ============================================================================
def _parse_conformer_search_results(work_dir: str,
                                    result: subprocess.CompletedProcess) -> Dict:
    """Parse results from a conformer search run."""
    output = result.stdout + result.stderr
    info = parse_crest_output(output)

    conf_file = os.path.join(work_dir, CREST_CONFORMERS)
    best_file = os.path.join(work_dir, CREST_BEST)

    conformers = parse_ensemble(conf_file) if os.path.exists(conf_file) else []

    # Prefer energies from ensemble (absolute Hartree) over crest.energies
    # (which also contains absolute Hartree but only has the energy column,
    # whereas the ensemble file provides full structures alongside energies).
    energies = [c['energy_hartree'] for c in conformers
                if c['energy_hartree'] is not None]

    # Fallback to crest.energies only if ensemble parsing failed
    if not energies:
        energies = parse_crest_energies(work_dir=work_dir)

    stats = compute_ensemble_statistics(energies) if energies else {}
    boltz = compute_boltzmann_populations(energies) if energies else {}

    return {
        'n_conformers': len(conformers) or info.get('n_conformers'),
        'n_rotamers': info.get('n_rotamers'),
        'lowest_energy_hartree': stats.get('lowest_energy_hartree'),
        'energy_range_kcal': stats.get('energy_range_kcal'),
        'converged': info.get('converged', False),
        'conformers': conformers,
        'energies': energies,
        'statistics': stats,
        'boltzmann': boltz,
        'warnings': info.get('warnings', []),
        'output_files': {
            'conformers': CREST_CONFORMERS if os.path.exists(conf_file) else None,
            'best': CREST_BEST if os.path.exists(best_file) else None,
            'energies': CREST_ENERGIES if os.path.exists(
                os.path.join(work_dir, CREST_ENERGIES)) else None,
        },
        'exit_code': result.returncode,
    }


def _parse_protonation_results(work_dir: str,
                                result: subprocess.CompletedProcess,
                                result_type: str) -> Dict:
    """Parse protonation/deprotonation/tautomer results."""
    output = result.stdout + result.stderr

    result_file = os.path.join(work_dir, f'{result_type}.xyz')
    structures = parse_ensemble(result_file) if os.path.exists(result_file) else []

    energies = [s['energy_hartree'] for s in structures
                if s['energy_hartree'] is not None]
    boltz = compute_boltzmann_populations(energies) if energies else {}

    return {
        'type': result_type,
        'n_structures': len(structures),
        'structures': structures,
        'energies': energies,
        'boltzmann': boltz,
        'converged': 'CREST terminated normally' in output or result.returncode == 0,
        'exit_code': result.returncode,
    }


def _parse_entropy_results(work_dir: str,
                           result: subprocess.CompletedProcess) -> Dict:
    """Parse entropy calculation results."""
    output = result.stdout + result.stderr

    entropy_data = {
        'conformational_entropy': None,
        'temperatures': [],
        'entropies': [],
        'converged': 'CREST terminated normally' in output or result.returncode == 0,
        'exit_code': result.returncode,
    }

    for line in output.split('\n'):
        low = line.lower()
        if 'sconf' in low or 'conformational entropy' in low:
            for token in line.split():
                try:
                    val = float(token)
                    entropy_data['conformational_entropy'] = val
                except ValueError:
                    continue

        # Parse temperature-entropy table rows
        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                temp = float(parts[0])
                ent = float(parts[1])
                if 100 < temp < 2000:  # reasonable temperature range
                    entropy_data['temperatures'].append(temp)
                    entropy_data['entropies'].append(ent)
            except ValueError:
                continue

    return entropy_data


def _parse_optimization_results(work_dir: str,
                                result: subprocess.CompletedProcess) -> Dict:
    """Parse geometry optimization results."""
    output = result.stdout + result.stderr

    # Look for optimized structure
    opt_file = os.path.join(work_dir, 'crestopt.xyz')
    if not os.path.exists(opt_file):
        opt_file = os.path.join(work_dir, CREST_BEST)

    optimized_structure = None
    if os.path.exists(opt_file):
        atoms, coords, comment = read_xyz_file(opt_file)
        optimized_structure = {
            'atoms': atoms,
            'coordinates': coords.tolist(),
            'comment': comment,
        }

    # Extract final energy
    energy = None
    for line in output.split('\n'):
        low = line.lower()
        if 'total energy' in low or 'optimized' in low:
            for token in line.split():
                try:
                    val = float(token)
                    if abs(val) > 1:
                        energy = val
                except ValueError:
                    continue

    return {
        'optimized_energy_hartree': energy,
        'optimized_structure': optimized_structure,
        'converged': result.returncode == 0,
        'exit_code': result.returncode,
    }


def _parse_qcg_results(work_dir: str,
                        result: subprocess.CompletedProcess) -> Dict:
    """Parse QCG results."""
    output = result.stdout + result.stderr

    # Look for cluster files in grow/ subdirectory
    cluster_file = None
    for candidate in ['grow/cluster.xyz', 'crest_best.xyz', 'cluster.xyz']:
        path = os.path.join(work_dir, candidate)
        if os.path.exists(path):
            cluster_file = path
            break

    return {
        'cluster_file': cluster_file,
        'converged': result.returncode == 0,
        'exit_code': result.returncode,
        'output_summary': output[-2000:] if output else '',
    }


def _parse_msreact_results(work_dir: str,
                           result: subprocess.CompletedProcess) -> Dict:
    """Parse MSREACT results."""
    products_file = os.path.join(work_dir, 'crest_msreact_products.xyz')
    products = parse_ensemble(products_file) if os.path.exists(products_file) else []

    return {
        'n_products': len(products),
        'products': products,
        'converged': result.returncode == 0,
        'exit_code': result.returncode,
    }


def _parse_cregen_results(work_dir: str,
                          result: subprocess.CompletedProcess) -> Dict:
    """Parse CREGEN sorting results."""
    output = result.stdout + result.stderr
    info = parse_crest_output(output)

    return {
        'n_conformers': info.get('n_conformers'),
        'n_rotamers': info.get('n_rotamers'),
        'exit_code': result.returncode,
    }


def _parse_cluster_results(work_dir: str,
                           result: subprocess.CompletedProcess) -> Dict:
    """Parse PCA clustering results."""
    output = result.stdout + result.stderr

    clusters = {}
    for line in output.split('\n'):
        low = line.lower()
        if 'cluster' in low and ('member' in low or 'size' in low):
            tokens = line.split()
            for k, tok in enumerate(tokens):
                if tok.lower() == 'cluster' and k + 1 < len(tokens):
                    try:
                        cid = int(tokens[k + 1].rstrip(':'))
                        for t2 in tokens[k + 2:]:
                            try:
                                clusters[cid] = int(t2)
                                break
                            except ValueError:
                                continue
                    except ValueError:
                        continue

    return {
        'n_clusters': len(clusters),
        'cluster_sizes': clusters,
        'exit_code': result.returncode,
    }


# ============================================================================
# CLEANUP
# ============================================================================
def crest_cleanup(deep: bool = False) -> None:
    """Clean up CREST temporary files.

    Args:
        deep: If True, also clears scratch directory and all temp files.
    """
    if deep:
        if os.path.exists(SCRATCH_DIR):
            shutil.rmtree(SCRATCH_DIR, ignore_errors=True)
            os.makedirs(SCRATCH_DIR, exist_ok=True)

        temp_patterns = ['METADYN*', 'NORMMD*', 'MRMSD', 'MDFILES',
                         'tmpcoord*', '.tmpxtbmodinp', 'cregen_*',
                         'coord.original*', '.cre_*']
        for pattern in temp_patterns:
            for f in globmod.glob(os.path.join(WORK_DIR, pattern)):
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                    elif os.path.isdir(f):
                        shutil.rmtree(f, ignore_errors=True)
                except Exception:
                    pass

    logging.info(f"Cleanup complete (deep={deep})")
