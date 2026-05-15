#!/usr/bin/env python3
"""
AmberTools Utilities Library

Helper functions for running AmberTools simulations and analyzing output.
This module is pre-installed in the AmberTools container for use by generated scripts.

Usage:
    from ambertools_utils import quick_setup, run_sander, compute_rmsd, save_final_results
"""

import os
import re
import sys
import glob
import json
import time
import shutil
import logging
import subprocess
import multiprocessing
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from scipy import stats

# ============= CONFIGURATION =============

NUM_CORES = os.cpu_count() or multiprocessing.cpu_count() or 1

# Standard directories — MUST be set via setup_directories() before use.
INPUT_DIR: str = ''
WORK_DIR: str = ''
OUTPUT_DIR: str = ''
SCRATCH_DIR: str = '/tmp/ambertools_scratch'
_DIRS_CONFIGURED = False

# AMBER home (set by environment)
AMBERHOME = os.environ.get('AMBERHOME', '/opt/conda')

# Force field to leaprc mapping
FF_LEAPRC_MAP = {
    'ff14SB':   'leaprc.protein.ff14SB',
    'ff19SB':   'leaprc.protein.ff19SB',
    'ff14SBonlysc': 'leaprc.protein.ff14SBonlysc',
    'fb15':     'leaprc.protein.fb15',
    'GAFF':     'leaprc.gaff',
    'GAFF2':    'leaprc.gaff2',
    'OL15':     'leaprc.DNA.OL15',
    'OL21':     'leaprc.DNA.OL21',
    'RNA.OL3':  'leaprc.RNA.OL3',
    'Lipid21':  'leaprc.lipid21',
}

# Water model to leaprc mapping
WATER_MODEL_MAP = {
    'TIP3P':    'leaprc.water.tip3p',
    'SPC/E':    'leaprc.water.spce',
    'OPC':      'leaprc.water.opc',
    'OPC3':     'leaprc.water.opc3',
    'TIP4P-Ew': 'leaprc.water.tip4pew',
    'TIP4P':    'leaprc.water.tip4pew',
}

# Water box model names for tleap solvateOct/solvateBox
WATER_BOX_MAP = {
    'TIP3P':    'TIP3PBOX',
    'SPC/E':    'SPCBOX',
    'OPC':      'OPCBOX',
    'OPC3':     'OPC3BOX',
    'TIP4P-Ew': 'TIP4PEWBOX',
    'TIP4P':    'TIP4PEWBOX',
}


# ============= SETUP FUNCTIONS =============

def _require_dirs():
    """Raise if setup_directories() has not been called."""
    if not _DIRS_CONFIGURED:
        raise RuntimeError(
            "Directories not configured. Call setup_directories(input_dir=..., output_dir=...) "
            "or quick_setup() before using any utility functions."
        )


def setup_logging():
    """Configure logging with explicit flushing for real-time output in containers."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stdout,
        force=True
    )
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode='w', buffering=1)


def setup_directories(input_dir: str, output_dir: str, work_dir: str = None,
                      copy_input: bool = True) -> None:
    """Create standard working directories and optionally copy input files.

    Args:
        input_dir: Path to the input directory (required).
        output_dir: Path to the output directory (required).
        work_dir: Path to the working directory. If None, uses /workdir or output_dir.
        copy_input: If True, copy input files to the working directory.
    """
    global INPUT_DIR, WORK_DIR, OUTPUT_DIR, _DIRS_CONFIGURED
    INPUT_DIR = input_dir
    OUTPUT_DIR = output_dir
    WORK_DIR = work_dir if work_dir is not None else '/app/workdir'
    _DIRS_CONFIGURED = True
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    logging.info(f"Input directory: {INPUT_DIR}")
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Output directory: {OUTPUT_DIR}")
    logging.info(f"Detected {NUM_CORES} CPU cores available")
    if copy_input:
        copy_input_files()


def copy_input_files(patterns: List[str] = None) -> List[str]:
    """Copy input files from input directory to working directory.

    Args:
        patterns: List of glob patterns to copy. Defaults to common AMBER patterns.

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        logging.info("Input directory is working directory; skipping copy_input_files")
        return []
    if patterns is None:
        patterns = [
            '*.pdb', '*.mol2', '*.sdf', '*.mol', '*.cif',
            '*.prmtop', '*.parm7', '*.top',
            '*.inpcrd', '*.rst7', '*.crd', '*.ncrst',
            '*.nc', '*.mdcrd', '*.xtc',
            '*.frcmod', '*.lib', '*.off', '*.prep',
            '*.in', '*.mdin', '*.dat', '*.txt',
            '*.pdbqt', '*.csv', '*.json',
        ]
    copied = []
    if os.path.exists(INPUT_DIR):
        for pattern in patterns:
            for f in glob.glob(os.path.join(INPUT_DIR, pattern)):
                if os.path.isfile(f):
                    dest = os.path.join(WORK_DIR, os.path.basename(f))
                    shutil.copy2(f, dest)
                    copied.append(dest)
        if copied:
            logging.info(f"Copied {len(copied)} input files to {WORK_DIR}")
        else:
            logging.warning(f"No input files found in {INPUT_DIR}")
    else:
        logging.warning(f"Input directory does not exist: {INPUT_DIR}")
    return copied


def copy_all_input_files() -> List[str]:
    """Copy ALL files from input directory to working directory.

    Unlike copy_input_files() which filters by extension, this copies every file.
    Useful in cross-agent workflows where upstream agents may produce files with
    non-standard extensions (e.g., .pdbqt from AutoDock).

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        logging.info("Input directory is working directory; skipping copy_all_input_files")
        return []
    copied = []
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                dest = os.path.join(WORK_DIR, os.path.basename(f))
                shutil.copy2(f, dest)
                copied.append(dest)
            elif os.path.isdir(f):
                dest = os.path.join(WORK_DIR, os.path.basename(f))
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(f, dest)
                copied.append(dest)
        logging.info(f"Copied all {len(copied)} input items to {WORK_DIR}")
    return copied


def copy_outputs(patterns: List[str] = None) -> List[str]:
    """Copy output files from working directory to output directory.

    Args:
        patterns: List of glob patterns to copy. Defaults to common AMBER output patterns.

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        logging.info("Working directory is output directory; skipping copy_outputs")
        return []
    if patterns is None:
        patterns = [
            '*.out', '*.mdout', '*.log',
            '*.rst7', '*.ncrst', '*.restrt',
            '*.nc', '*.mdcrd', '*.xtc',
            '*.prmtop', '*.parm7', '*.inpcrd',
            '*.pdb', '*.mol2',
            '*.dat', '*.csv', '*.json',
            '*.png', '*.svg', '*.pdf',
        ]
    copied = []
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            if os.path.isfile(f):
                dest = os.path.join(OUTPUT_DIR, os.path.basename(f))
                shutil.copy2(f, dest)
                copied.append(dest)
    if copied:
        logging.info(f"Copied {len(copied)} output files to {OUTPUT_DIR}")
    return copied


def quick_setup(input_dir: str = '/input', output_dir: str = '/output',
                work_dir: str = '/app/workdir', copy_input: bool = True) -> List[str]:
    """Initialize logging, create directories, copy input files.

    Args:
        input_dir: Path to the input directory.
        output_dir: Path to the output directory.
        work_dir: Path to the working directory.
        copy_input: If True, copy input files to the working directory.

    Returns:
        List of copied input file paths.
    """
    setup_logging()
    setup_directories(input_dir, output_dir, work_dir, copy_input)
    logging.info(f"Files in working directory: {os.listdir(WORK_DIR)}")
    return glob.glob(os.path.join(WORK_DIR, '*'))


def quick_finish() -> List[str]:
    """Copy output files to output directory.

    Returns:
        List of copied output file paths.
    """
    return copy_outputs()


# ============= COMMAND EXECUTION =============

def run_command(command: List[str], input_text: str = None,
                cwd: str = None, timeout: int = None) -> subprocess.CompletedProcess:
    """Execute a command with error handling and timing.

    Args:
        command: Command as list of strings.
        input_text: Optional text to pipe to stdin.
        cwd: Working directory for the command.
        timeout: Timeout in seconds (None = no timeout).

    Returns:
        subprocess.CompletedProcess result.

    Raises:
        subprocess.CalledProcessError: If the command fails.
    """
    cmd_str = ' '.join(command[:4])
    logging.info(f"Running: {cmd_str}...")
    start = time.time()
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            check=True,
            capture_output=True,
            cwd=cwd or WORK_DIR if _DIRS_CONFIGURED else None,
            timeout=timeout,
        )
        elapsed = time.time() - start
        logging.info(f"Completed: {cmd_str} ({elapsed:.1f}s)")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {cmd_str}")
        if e.stdout:
            logging.error(f"STDOUT (last 500 chars): {e.stdout[-500:]}")
        if e.stderr:
            logging.error(f"STDERR (last 500 chars): {e.stderr[-500:]}")
        raise
    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout}s: {cmd_str}")
        raise


# ============= AMBER EXECUTION FUNCTIONS =============

def run_sander(input_file: str, topology: str, coordinates: str,
               output_prefix: str = None, ref_coords: str = None,
               num_cores: int = None, use_mpi: bool = True) -> str:
    """Run sander MD engine.

    Args:
        input_file: Path to mdin input file.
        topology: Path to prmtop topology file.
        coordinates: Path to inpcrd/rst7 coordinate file.
        output_prefix: Output file prefix. If None, derived from input_file.
        ref_coords: Reference coordinates for restraints.
        num_cores: Number of CPU cores to use. None = auto-detect.
        use_mpi: If True and num_cores > 1, use MPI parallel sander.

    Returns:
        Path to the output file (.mdout).
    """
    _require_dirs()
    if output_prefix is None:
        output_prefix = Path(input_file).stem

    mdout = f"{output_prefix}.mdout"
    restrt = f"{output_prefix}.rst7"
    mdcrd = f"{output_prefix}.nc"
    mdinfo = f"{output_prefix}.mdinfo"

    if num_cores is None:
        num_cores = max(1, NUM_CORES - 1)

    cmd = []
    if use_mpi and num_cores > 1:
        sander_mpi = shutil.which('sander.MPI')
        if sander_mpi:
            cmd = ['mpirun', '--allow-run-as-root', '-np', str(num_cores), 'sander.MPI']
        else:
            logging.warning("sander.MPI not found, falling back to serial sander")
            cmd = ['sander']
    else:
        cmd = ['sander']

    cmd.extend([
        '-O',
        '-i', input_file,
        '-o', mdout,
        '-p', topology,
        '-c', coordinates,
        '-r', restrt,
        '-x', mdcrd,
        '-inf', mdinfo,
    ])

    if ref_coords:
        cmd.extend(['-ref', ref_coords])

    run_command(cmd)

    if os.path.exists(mdout):
        size = os.path.getsize(mdout)
        logging.info(f"Sander output: {mdout} ({size} bytes)")
    else:
        logging.warning(f"Expected output file not found: {mdout}")

    return mdout


def run_tleap(script_content: str, script_file: str = "tleap.in") -> subprocess.CompletedProcess:
    """Write tleap script to file and execute.

    Args:
        script_content: Content of the tleap input script.
        script_file: Filename for the tleap script.

    Returns:
        CompletedProcess result.
    """
    _require_dirs()
    script_path = os.path.join(WORK_DIR, script_file)
    with open(script_path, 'w') as f:
        f.write(script_content)
    logging.info(f"tleap script written to {script_path}")

    # Remove old leap.log — tleap appends rather than overwrites, so stale
    # errors from a previous run would pollute parse_tleap_log.
    old_log = os.path.join(WORK_DIR, 'leap.log')
    if os.path.exists(old_log):
        os.remove(old_log)

    # tleap returns warning count as exit code, so we cannot use check=True
    cmd_str = f"tleap -f {script_path}"
    logging.info(f"Running: {cmd_str}")
    start = time.time()
    proc = subprocess.run(
        ['tleap', '-f', script_path],
        text=True, capture_output=True,
        cwd=WORK_DIR if _DIRS_CONFIGURED else None,
    )
    elapsed = time.time() - start
    logging.info(f"tleap completed in {elapsed:.1f}s (exit code {proc.returncode})")

    if proc.stdout:
        logging.info(f"tleap stdout (last 300 chars): {proc.stdout[-300:]}")

    log_file = os.path.join(WORK_DIR, 'leap.log')
    if os.path.exists(log_file):
        log_info = parse_tleap_log(log_file)
        if log_info.get('warnings'):
            for w in log_info['warnings'][:5]:
                logging.warning(f"tleap warning: {w}")
        if log_info.get('errors'):
            for e in log_info['errors']:
                logging.error(f"tleap error: {e}")
            if log_info['errors']:
                raise RuntimeError(f"tleap reported errors: {log_info['errors']}")

    return proc


def run_cpptraj(topology: str, script_content: str,
                script_file: str = "cpptraj.in") -> subprocess.CompletedProcess:
    """Write cpptraj script to file and execute.

    Args:
        topology: Path to prmtop topology file.
        script_content: Content of the cpptraj input script.
        script_file: Filename for the cpptraj script.

    Returns:
        CompletedProcess result.
    """
    _require_dirs()
    script_path = os.path.join(WORK_DIR, script_file)
    with open(script_path, 'w') as f:
        f.write(script_content)

    return run_command(['cpptraj', '-p', topology, '-i', script_path])


def run_antechamber(input_file: str, output_file: str,
                    charge_method: str = "bcc", atom_type: str = "gaff2",
                    net_charge: int = 0, multiplicity: int = 1) -> subprocess.CompletedProcess:
    """Run antechamber for small molecule parameterization.

    Args:
        input_file: Input molecule file (PDB, MOL2, SDF).
        output_file: Output MOL2 file with assigned atom types and charges.
        charge_method: Charge method (bcc=AM1-BCC, mul=Mulliken, gas=Gasteiger).
        atom_type: Atom type (gaff, gaff2).
        net_charge: Net charge of the molecule.
        multiplicity: Spin multiplicity.

    Returns:
        CompletedProcess result.
    """
    _require_dirs()
    ext = Path(input_file).suffix.lower()
    fmt_map = {'.pdb': 'pdb', '.mol2': 'mol2', '.sdf': 'sdf', '.mol': 'mdl'}
    input_format = fmt_map.get(ext, 'pdb')
    output_format = 'mol2'

    cmd = [
        'antechamber',
        '-i', input_file,
        '-fi', input_format,
        '-o', output_file,
        '-fo', output_format,
        '-c', charge_method,
        '-at', atom_type,
        '-nc', str(net_charge),
        '-m', str(multiplicity),
        '-pf', 'y',  # remove intermediate files
    ]

    return run_command(cmd)


def run_parmchk2(input_file: str, output_file: str,
                 force_field: str = "gaff2") -> subprocess.CompletedProcess:
    """Run parmchk2 to check for missing parameters.

    Args:
        input_file: Input MOL2 file with atom types.
        output_file: Output frcmod file with missing parameters.
        force_field: Force field to check against (gaff, gaff2).

    Returns:
        CompletedProcess result.
    """
    _require_dirs()
    ff_flag = '2' if 'gaff2' in force_field.lower() else '1'
    return run_command([
        'parmchk2',
        '-i', input_file,
        '-f', 'mol2',
        '-o', output_file,
        '-s', ff_flag,
    ])


def run_pdb4amber(input_pdb: str, output_pdb: str,
                  reduce: bool = True, dry: bool = False,
                  most_populous: bool = True) -> subprocess.CompletedProcess:
    """Run pdb4amber to clean PDB files for AMBER.

    Args:
        input_pdb: Input PDB file path.
        output_pdb: Output cleaned PDB file path.
        reduce: If True, add hydrogens with reduce.
        dry: If True, remove water molecules.
        most_populous: If True, keep only the most populous altloc.

    Returns:
        CompletedProcess result.
    """
    _require_dirs()
    cmd = ['pdb4amber', '-i', input_pdb, '-o', output_pdb]
    if reduce:
        cmd.append('--reduce')
    if dry:
        cmd.append('--dry')
    if most_populous:
        cmd.append('--most-populous')

    try:
        return run_command(cmd)
    except subprocess.CalledProcessError as e:
        logging.warning(f"pdb4amber returned non-zero exit code. "
                        f"This may be OK for NMR structures. Using output if it exists.")
        if os.path.exists(output_pdb) and os.path.getsize(output_pdb) > 0:
            logging.info(f"pdb4amber output exists: {output_pdb}")
            return e  # Return the error but don't re-raise since output was produced
        raise


# ============= SYSTEM PREPARATION =============

def write_tleap_script(pdb_file: str, force_field: str = "ff14SB",
                       water_model: str = "TIP3P", box_buffer: float = 10.0,
                       box_type: str = "oct", neutralize: bool = True,
                       ion_conc: float = 0.15, extra_commands: List[str] = None,
                       ligand_mol2: str = None, ligand_frcmod: str = None,
                       ligand_resname: str = "LIG",
                       output_prefix: str = "system") -> str:
    """Generate a tleap input script for system preparation.

    Args:
        pdb_file: Input PDB file path.
        force_field: Force field name (key in FF_LEAPRC_MAP).
        water_model: Water model name (key in WATER_MODEL_MAP).
        box_buffer: Buffer size in Angstroms for solvation box.
        box_type: Box type ('oct' for truncated octahedron, 'box' for rectangular).
        neutralize: If True, add counterions to neutralize the system.
        ion_conc: Salt concentration in M (for addIonsRand).
        extra_commands: Additional tleap commands to insert before solvation.
        ligand_mol2: Path to ligand MOL2 file with GAFF2 types.
        ligand_frcmod: Path to ligand frcmod file.
        ligand_resname: Residue name used for the ligand.
        output_prefix: Prefix for output files (prmtop, inpcrd, pdb).

    Returns:
        tleap script content as string.
    """
    lines = []

    # Load force field
    ff_leaprc = FF_LEAPRC_MAP.get(force_field, force_field)
    lines.append(f"source {ff_leaprc}")

    # Load water model
    water_leaprc = WATER_MODEL_MAP.get(water_model, water_model)
    lines.append(f"source {water_leaprc}")

    # Load ligand parameters if provided
    if ligand_mol2 and ligand_frcmod:
        lines.append("source leaprc.gaff2")
        lines.append(f"loadAmberParams {ligand_frcmod}")
        lines.append(f"{ligand_resname} = loadMol2 {ligand_mol2}")

    # Load protein/complex
    lines.append(f"mol = loadPdb {pdb_file}")

    # Extra commands (e.g., disulfide bonds, custom modifications)
    if extra_commands:
        for cmd in extra_commands:
            lines.append(cmd)

    # Check structure
    lines.append("check mol")

    # Solvation
    water_box = WATER_BOX_MAP.get(water_model, 'TIP3PBOX')
    if box_type == 'oct':
        lines.append(f"solvateOct mol {water_box} {box_buffer}")
    else:
        lines.append(f"solvateBox mol {water_box} {box_buffer}")

    # Add counterions to neutralize
    if neutralize:
        lines.append("addIons mol Na+ 0")
        lines.append("addIons mol Cl- 0")

    # Save files
    lines.append(f"saveAmberParm mol {output_prefix}.prmtop {output_prefix}.inpcrd")
    lines.append(f"savePdb mol {output_prefix}.pdb")
    lines.append("quit")

    return '\n'.join(lines) + '\n'


def prepare_system(pdb_file: str, force_field: str = "ff14SB",
                   water_model: str = "TIP3P", box_buffer: float = 10.0,
                   box_type: str = "oct", neutralize: bool = True,
                   ion_conc: float = 0.15, output_prefix: str = "system",
                   extra_commands: List[str] = None,
                   ligand_mol2: str = None, ligand_frcmod: str = None,
                   ligand_resname: str = "LIG",
                   clean_pdb: bool = True) -> Dict:
    """Full system preparation pipeline: pdb4amber -> tleap.

    Args:
        pdb_file: Input PDB file.
        force_field: Force field name.
        water_model: Water model name.
        box_buffer: Solvation box buffer in Angstroms.
        box_type: 'oct' for truncated octahedron, 'box' for rectangular.
        neutralize: Add counterions.
        ion_conc: Salt concentration in M.
        output_prefix: Prefix for output files.
        extra_commands: Additional tleap commands.
        ligand_mol2: Ligand MOL2 file.
        ligand_frcmod: Ligand frcmod file.
        ligand_resname: Ligand residue name.
        clean_pdb: If True, run pdb4amber first.

    Returns:
        Dict with keys: prmtop, inpcrd, pdb, tleap_log.
    """
    _require_dirs()
    prepared_pdb = pdb_file

    if clean_pdb:
        cleaned_pdb = f"{output_prefix}_clean.pdb"
        try:
            run_pdb4amber(pdb_file, cleaned_pdb, reduce=True)
            if os.path.exists(cleaned_pdb) and os.path.getsize(cleaned_pdb) > 0:
                prepared_pdb = cleaned_pdb
                logging.info(f"Using cleaned PDB: {cleaned_pdb}")
            else:
                logging.warning("pdb4amber produced empty output; using original PDB")
        except Exception as e:
            logging.warning(f"pdb4amber failed ({e}); using original PDB")

    script = write_tleap_script(
        pdb_file=prepared_pdb,
        force_field=force_field,
        water_model=water_model,
        box_buffer=box_buffer,
        box_type=box_type,
        neutralize=neutralize,
        ion_conc=ion_conc,
        extra_commands=extra_commands,
        ligand_mol2=ligand_mol2,
        ligand_frcmod=ligand_frcmod,
        ligand_resname=ligand_resname,
        output_prefix=output_prefix,
    )

    run_tleap(script)

    result = {
        'prmtop': f"{output_prefix}.prmtop",
        'inpcrd': f"{output_prefix}.inpcrd",
        'pdb': f"{output_prefix}.pdb",
        'tleap_log': 'leap.log',
    }

    for key in ['prmtop', 'inpcrd']:
        fpath = result[key]
        if os.path.exists(fpath):
            size = os.path.getsize(fpath)
            logging.info(f"Generated {key}: {fpath} ({size} bytes)")
        else:
            logging.error(f"Expected file not generated: {fpath}")
            raise FileNotFoundError(f"tleap failed to generate {fpath}")

    return result


def parameterize_ligand(input_file: str, charge_method: str = "bcc",
                        atom_type: str = "gaff2", net_charge: int = 0,
                        output_prefix: str = "ligand") -> Dict:
    """Complete ligand parameterization: antechamber -> parmchk2 -> tleap lib.

    Args:
        input_file: Input molecule file (PDB, MOL2, SDF).
        charge_method: Charge method (bcc, mul, gas).
        atom_type: Atom type (gaff, gaff2).
        net_charge: Net charge of the molecule.
        output_prefix: Prefix for output files.

    Returns:
        Dict with keys: mol2, frcmod, prmtop, inpcrd.
    """
    _require_dirs()
    mol2_file = f"{output_prefix}.mol2"
    frcmod_file = f"{output_prefix}.frcmod"

    # Step 1: Assign atom types and charges
    run_antechamber(input_file, mol2_file, charge_method=charge_method,
                    atom_type=atom_type, net_charge=net_charge)
    logging.info(f"Antechamber completed: {mol2_file}")

    # Step 2: Check for missing parameters
    run_parmchk2(mol2_file, frcmod_file, force_field=atom_type)
    logging.info(f"Parmchk2 completed: {frcmod_file}")

    # Step 3: Build topology with tleap
    gaff_leaprc = 'leaprc.gaff2' if 'gaff2' in atom_type.lower() else 'leaprc.gaff'
    tleap_script = f"""source {gaff_leaprc}
loadAmberParams {frcmod_file}
mol = loadMol2 {mol2_file}
check mol
saveAmberParm mol {output_prefix}.prmtop {output_prefix}.inpcrd
savePdb mol {output_prefix}.pdb
quit
"""
    run_tleap(tleap_script, script_file=f"tleap_{output_prefix}.in")

    result = {
        'mol2': mol2_file,
        'frcmod': frcmod_file,
        'prmtop': f"{output_prefix}.prmtop",
        'inpcrd': f"{output_prefix}.inpcrd",
        'pdb': f"{output_prefix}.pdb",
    }

    for key, fpath in result.items():
        if os.path.exists(fpath):
            logging.info(f"Generated {key}: {fpath}")
        else:
            logging.warning(f"File not generated: {fpath}")

    return result


# ============= MD INPUT GENERATION =============

def write_minimization_input(max_cycles: int = 5000, steepest_descent: int = 2500,
                             restraint_wt: float = 0.0, restraint_mask: str = None,
                             cutoff: float = 10.0) -> str:
    """Generate sander minimization input file content.

    Args:
        max_cycles: Maximum minimization cycles.
        steepest_descent: Switch from steepest descent to conjugate gradient after this many steps.
        restraint_wt: Restraint weight in kcal/(mol*A^2). 0 = no restraints.
        restraint_mask: Atom mask for positional restraints (e.g., '@CA,C,N,O').
        cutoff: Nonbonded cutoff in Angstroms.

    Returns:
        Content string for the mdin file.
    """
    ntr = 1 if (restraint_wt > 0 and restraint_mask) else 0
    lines = [
        "Minimization",
        " &cntrl",
        "  imin=1,",
        f"  maxcyc={max_cycles},",
        f"  ncyc={steepest_descent},",
        f"  cut={cutoff},",
        "  ntb=1,",
        f"  ntr={ntr},",
        " /",
    ]
    if ntr:
        lines.append(f"Hold restrained atoms")
        lines.append(f"{restraint_wt}")
        lines.append(f"RES 1 99999")
        lines.append("END")
        lines.append("END")
    return '\n'.join(lines) + '\n'


def write_heating_input(target_temp: float = 300.0, nsteps: int = 25000,
                        dt: float = 0.002, restraint_wt: float = 10.0,
                        restraint_mask: str = "@CA,C,N,O",
                        cutoff: float = 10.0, ntt: int = 3,
                        gamma_ln: float = 1.0, ntpr: int = 500,
                        ntwx: int = 500) -> str:
    """Generate sander NVT heating input file content.

    Args:
        target_temp: Target temperature in Kelvin.
        nsteps: Number of MD steps.
        dt: Timestep in picoseconds.
        restraint_wt: Restraint weight in kcal/(mol*A^2).
        restraint_mask: Atom mask for restraints.
        cutoff: Nonbonded cutoff in Angstroms.
        ntt: Thermostat type (1=Berendsen, 3=Langevin).
        gamma_ln: Langevin collision frequency (ps^-1).
        ntpr: Print energy every ntpr steps.
        ntwx: Write trajectory every ntwx steps.

    Returns:
        Content string for the mdin file.
    """
    ntr = 1 if (restraint_wt > 0 and restraint_mask) else 0
    lines = [
        "Heating",
        " &cntrl",
        "  imin=0,",
        f"  nstlim={nsteps},",
        f"  dt={dt},",
        "  irest=0, ntx=1,",
        f"  tempi=0.0, temp0={target_temp},",
        f"  ntt={ntt}, gamma_ln={gamma_ln},",
        "  ntb=1, ntp=0,",
        f"  cut={cutoff},",
        "  ntc=2, ntf=2,",
        f"  ntpr={ntpr}, ntwx={ntwx}, ntwr={nsteps},",
        f"  ntr={ntr},",
        "  nmropt=1,",
        " /",
        " &wt type='TEMP0', istep1=0, istep2=nsteps,",
        f"  value1=0.0, value2={target_temp}, /",
        " &wt type='END' /",
    ]
    # Fix: replace nsteps placeholder in &wt section
    lines = [l.replace('istep2=nsteps', f'istep2={nsteps}') for l in lines]

    if ntr:
        lines.append(f"Hold restrained atoms")
        lines.append(f"{restraint_wt}")
        lines.append(f"RES 1 99999")
        lines.append("END")
        lines.append("END")
    return '\n'.join(lines) + '\n'


def write_equilibration_input(target_temp: float = 300.0, target_pressure: float = 1.0,
                              nsteps: int = 50000, dt: float = 0.002,
                              restraint_wt: float = 1.0,
                              restraint_mask: str = "@CA,C,N,O",
                              cutoff: float = 10.0, ntt: int = 3,
                              gamma_ln: float = 1.0, barostat: int = 2,
                              ntpr: int = 500, ntwx: int = 500) -> str:
    """Generate sander NPT equilibration input file content.

    Args:
        target_temp: Target temperature in Kelvin.
        target_pressure: Target pressure in bar.
        nsteps: Number of MD steps.
        dt: Timestep in picoseconds.
        restraint_wt: Restraint weight in kcal/(mol*A^2).
        restraint_mask: Atom mask for restraints.
        cutoff: Nonbonded cutoff in Angstroms.
        ntt: Thermostat type (3=Langevin recommended).
        gamma_ln: Langevin collision frequency (ps^-1).
        barostat: Barostat type (1=Berendsen, 2=Monte Carlo).
        ntpr: Print energy every ntpr steps.
        ntwx: Write trajectory every ntwx steps.

    Returns:
        Content string for the mdin file.
    """
    ntr = 1 if (restraint_wt > 0 and restraint_mask) else 0
    lines = [
        "NPT Equilibration",
        " &cntrl",
        "  imin=0,",
        f"  nstlim={nsteps},",
        f"  dt={dt},",
        "  irest=1, ntx=5,",
        f"  temp0={target_temp},",
        f"  ntt={ntt}, gamma_ln={gamma_ln},",
        f"  ntb=2, ntp=1, pres0={target_pressure}, barostat={barostat},",
        f"  cut={cutoff},",
        "  ntc=2, ntf=2,",
        f"  ntpr={ntpr}, ntwx={ntwx}, ntwr={nsteps},",
        f"  ntr={ntr},",
        " /",
    ]
    if ntr:
        lines.append(f"Hold restrained atoms")
        lines.append(f"{restraint_wt}")
        lines.append(f"RES 1 99999")
        lines.append("END")
        lines.append("END")
    return '\n'.join(lines) + '\n'


def write_production_input(target_temp: float = 300.0, target_pressure: float = 1.0,
                           nsteps: int = 500000, dt: float = 0.002,
                           ntwx: int = 5000, ntpr: int = 500,
                           cutoff: float = 10.0, ntt: int = 3,
                           gamma_ln: float = 1.0, barostat: int = 2,
                           iwrap: int = 1) -> str:
    """Generate sander NPT production MD input file content.

    Args:
        target_temp: Target temperature in Kelvin.
        target_pressure: Target pressure in bar.
        nsteps: Number of MD steps.
        dt: Timestep in picoseconds.
        ntwx: Write trajectory every ntwx steps.
        ntpr: Print energy every ntpr steps.
        cutoff: Nonbonded cutoff in Angstroms.
        ntt: Thermostat type (3=Langevin).
        gamma_ln: Langevin collision frequency (ps^-1).
        barostat: Barostat type (2=Monte Carlo recommended).
        iwrap: Wrap coordinates into primary box (1=yes, 0=no).

    Returns:
        Content string for the mdin file.
    """
    lines = [
        "Production MD",
        " &cntrl",
        "  imin=0,",
        f"  nstlim={nsteps},",
        f"  dt={dt},",
        "  irest=1, ntx=5,",
        f"  temp0={target_temp},",
        f"  ntt={ntt}, gamma_ln={gamma_ln},",
        f"  ntb=2, ntp=1, pres0={target_pressure}, barostat={barostat},",
        f"  cut={cutoff},",
        "  ntc=2, ntf=2,",
        f"  ntpr={ntpr}, ntwx={ntwx}, ntwr={nsteps},",
        f"  iwrap={iwrap},",
        "  ntr=0,",
        " /",
    ]
    return '\n'.join(lines) + '\n'


# ============= PARSING FUNCTIONS =============

def parse_mdout(filename: str) -> Dict:
    """Parse sander output file (.mdout) for energy and thermodynamic data.

    Args:
        filename: Path to sander output file.

    Returns:
        Dict with arrays: steps, time, etot, ektot, eptot, temp, press, volume, density.
        For minimization: steps, etot only.
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Output file not found: {filename}")

    data = {
        'steps': [], 'time': [], 'etot': [], 'ektot': [], 'eptot': [],
        'temp': [], 'press': [], 'volume': [], 'density': [],
    }
    is_minimization = False

    with open(filename, 'r') as f:
        content = f.read()

    if 'FINAL RESULTS' in content and 'NSTEP' in content and 'ENERGY' in content:
        # Minimization output parsing
        is_minimization = True
        pattern = r'NSTEP\s+ENERGY\s+RMS\s+GMAX.*?\n\s+(\d+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)'
        for match in re.finditer(pattern, content):
            data['steps'].append(int(match.group(1)))
            data['etot'].append(float(match.group(2)))
    else:
        # MD output parsing
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            if 'NSTEP' in line and 'TIME(PS)' in line:
                # Values are on the same line: NSTEP = val TIME(PS) = val TEMP(K) = val
                parts = line.split()
                for j, p in enumerate(parts):
                    if p == 'NSTEP' and j + 2 < len(parts):
                        try:
                            data['steps'].append(int(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
                    if p == 'TIME(PS)' and j + 2 < len(parts):
                        try:
                            data['time'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
                    if p == 'TEMP(K)' and j + 2 < len(parts):
                        try:
                            data['temp'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
            elif 'Etot' in line and '=' in line:
                parts = line.split()
                for j, p in enumerate(parts):
                    if p == 'Etot' and j + 2 < len(parts):
                        try:
                            data['etot'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
                    if p == 'EKtot' and j + 2 < len(parts):
                        try:
                            data['ektot'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
                    if p == 'EPtot' and j + 2 < len(parts):
                        try:
                            data['eptot'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
            elif 'PRESS' in line and '=' in line and 'VIRIAL' not in line:
                parts = line.split()
                for j, p in enumerate(parts):
                    if p == 'PRESS' and j + 2 < len(parts):
                        try:
                            data['press'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
            elif 'VOLUME' in line and '=' in line:
                parts = line.split()
                for j, p in enumerate(parts):
                    if p == 'VOLUME' and j + 2 < len(parts):
                        try:
                            data['volume'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
            elif 'Density' in line and '=' in line:
                parts = line.split()
                for j, p in enumerate(parts):
                    if p == 'Density' and j + 2 < len(parts):
                        try:
                            data['density'].append(float(parts[j + 2]))
                        except (ValueError, IndexError):
                            pass
            i += 1

    # Convert to numpy arrays
    for key in data:
        data[key] = np.array(data[key]) if data[key] else np.array([])

    data['is_minimization'] = is_minimization
    n_records = len(data['etot'])
    logging.info(f"Parsed {n_records} energy records from {filename} "
                 f"({'minimization' if is_minimization else 'dynamics'})")
    return data


def parse_mdinfo(filename: str) -> Dict:
    """Parse mdinfo file for current simulation status.

    Args:
        filename: Path to mdinfo file.

    Returns:
        Dict with simulation status info.
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"mdinfo file not found: {filename}")

    info = {}
    with open(filename, 'r') as f:
        for line in f:
            if 'NSTEP' in line and '=' in line:
                parts = line.split()
                for j, p in enumerate(parts):
                    if p == 'NSTEP' and j + 2 < len(parts):
                        try:
                            info['nstep'] = int(parts[j + 2])
                        except (ValueError, IndexError):
                            pass
                    if p == 'TIME(PS)' and j + 2 < len(parts):
                        try:
                            info['time'] = float(parts[j + 2])
                        except (ValueError, IndexError):
                            pass
    return info


def parse_tleap_log(filename: str) -> Dict:
    """Parse tleap log file for system info, warnings, and errors.

    Args:
        filename: Path to leap.log file.

    Returns:
        Dict with keys: n_atoms, n_residues, warnings, errors.
    """
    if not os.path.exists(filename):
        return {'n_atoms': 0, 'n_residues': 0, 'warnings': [], 'errors': []}

    info = {'n_atoms': 0, 'n_residues': 0, 'warnings': [], 'errors': []}
    with open(filename, 'r') as f:
        for line in f:
            line_stripped = line.strip()
            if 'Total atoms in' in line:
                match = re.search(r'Total atoms in.*?:\s*(\d+)', line)
                if match:
                    info['n_atoms'] = int(match.group(1))
            elif 'Total residues in' in line:
                match = re.search(r'Total residues in.*?:\s*(\d+)', line)
                if match:
                    info['n_residues'] = int(match.group(1))
            elif line_stripped.startswith('WARNING') or 'WARNING' in line_stripped:
                info['warnings'].append(line_stripped)
            elif line_stripped.startswith('ERROR') or 'FATAL' in line_stripped:
                info['errors'].append(line_stripped)
    return info


def parse_cpptraj_dat(filename: str, comment_char: str = '#') -> Dict:
    """Parse cpptraj output .dat file into arrays.

    Handles standard cpptraj output with comment lines starting with '#'
    and space-separated data columns.

    Args:
        filename: Path to cpptraj output file.
        comment_char: Character indicating comment lines.

    Returns:
        Dict with column names as keys and numpy arrays as values.
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"cpptraj output not found: {filename}")

    columns = []
    data_rows = []

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(comment_char):
                # Parse column headers from first comment line
                if not columns:
                    parts = line.lstrip(comment_char).split()
                    columns = parts
                continue
            # Data line
            try:
                vals = [float(x) for x in line.split()]
                data_rows.append(vals)
            except ValueError:
                continue

    if not data_rows:
        logging.warning(f"No data rows found in {filename}")
        return {}

    data_array = np.array(data_rows)
    result = {}
    for i, col in enumerate(columns):
        if i < data_array.shape[1]:
            result[col] = data_array[:, i]

    # If no column headers found, use generic names
    if not result and data_array.size > 0:
        for i in range(data_array.shape[1]):
            result[f'col_{i}'] = data_array[:, i]

    return result


def parse_hbond_output(filename: str) -> Dict:
    """Parse cpptraj hydrogen bond average output.

    Args:
        filename: Path to cpptraj hbond avgout file.

    Returns:
        Dict with keys: hbonds (list of dicts), n_hbonds.
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Hbond output not found: {filename}")

    hbonds: List[Dict[str, Any]] = []
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 4:
                try:
                    # cpptraj hbond avgout format:
                    # Acceptor DonorH Donor Frames Frac AvgDist AvgAng
                    # :1@O :5@H :5@N 80 0.8000 2.890 165.234
                    hbond: Dict[str, Any] = {
                        'acceptor': parts[0],
                        'donor_h': parts[1] if len(parts) > 1 else '',
                        'donor': parts[2] if len(parts) > 2 else '',
                    }
                    # Numeric fields start after atom masks
                    num_start = 3
                    for idx in range(len(parts)):
                        try:
                            float(parts[idx])
                            num_start = idx
                            break
                        except ValueError:
                            continue
                    nums = parts[num_start:]
                    if len(nums) >= 1:
                        hbond['frames'] = int(float(nums[0]))
                    if len(nums) >= 2:
                        hbond['frac'] = float(nums[1])
                    if len(nums) >= 3:
                        hbond['avg_dist'] = float(nums[2])
                    if len(nums) >= 4:
                        hbond['avg_angle'] = float(nums[3])
                    hbonds.append(hbond)
                except (ValueError, IndexError):
                    continue

    return {'hbonds': hbonds, 'n_hbonds': len(hbonds)}


def get_system_info(prmtop: str) -> Dict:
    """Extract system information from topology file using parmed.

    Args:
        prmtop: Path to AMBER prmtop topology file.

    Returns:
        Dict with system info: n_atoms, n_residues, n_waters, n_ions,
        has_box, residue_names, unique_residues.
    """
    try:
        import parmed
    except ImportError:
        logging.warning("parmed not available; returning minimal system info")
        return {'n_atoms': 0, 'n_residues': 0, 'error': 'parmed not available'}

    parm = parmed.load_file(prmtop)
    residue_names = [r.name for r in parm.residues]
    water_names = {'WAT', 'HOH', 'TIP3', 'TP3', 'SPC', 'T4E', 'OPC'}
    ion_names = {'Na+', 'Cl-', 'K+', 'Mg2+', 'Ca2+', 'Zn2+', 'Na', 'Cl', 'K'}

    n_waters = sum(1 for r in residue_names if r in water_names)
    n_ions = sum(1 for r in residue_names if r in ion_names)

    info = {
        'n_atoms': len(parm.atoms),
        'n_residues': len(parm.residues),
        'n_waters': n_waters,
        'n_ions': n_ions,
        'has_box': parm.box is not None,
        'residue_names': residue_names,
        'unique_residues': sorted(set(residue_names)),
    }
    if parm.box is not None:
        info['box_dimensions'] = list(parm.box)

    logging.info(f"System: {info['n_atoms']} atoms, {info['n_residues']} residues, "
                 f"{n_waters} waters, {n_ions} ions")
    return info


# ============= ANALYSIS FUNCTIONS =============

def compute_rmsd(topology: str, trajectory: str, mask: str = "@CA",
                 ref_frame: int = 0, output_file: str = "rmsd.dat") -> Dict:
    """Compute RMSD using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file (nc, mdcrd).
        mask: Atom mask for RMSD calculation.
        ref_frame: Reference frame number.
        output_file: Output file path.

    Returns:
        Dict with frame, rmsd arrays and output_file path.
    """
    _require_dirs()
    if ref_frame == 0:
        script = f"""trajin {trajectory}
rms rmsd_calc {mask} first out {output_file}
run
"""
    else:
        script = f"""trajin {trajectory}
reference {trajectory} lastframe
rms rmsd_calc {mask} reference out {output_file}
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_rmsd.in")

    result = parse_cpptraj_dat(output_file)
    result['output_file'] = output_file
    if 'rmsd_calc' in result:
        result['rmsd'] = result.pop('rmsd_calc')
    logging.info(f"RMSD computed: {len(result.get('rmsd', []))} frames")
    return result


def compute_rmsf(topology: str, trajectory: str, mask: str = "@CA",
                 output_file: str = "rmsf.dat") -> Dict:
    """Compute RMSF per residue using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file.
        mask: Atom mask for RMSF calculation.
        output_file: Output file path.

    Returns:
        Dict with residue, rmsf arrays and output_file path.
    """
    _require_dirs()
    script = f"""trajin {trajectory}
atomicfluct rmsf_calc {mask} out {output_file} byres
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_rmsf.in")

    result = parse_cpptraj_dat(output_file)
    result['output_file'] = output_file
    if 'rmsf_calc' in result:
        result['rmsf'] = result.pop('rmsf_calc')
    logging.info(f"RMSF computed: {len(result.get('rmsf', []))} residues")
    return result


def compute_hbonds(topology: str, trajectory: str,
                   donor_mask: str = ":*", acceptor_mask: str = ":*",
                   output_file: str = "hbonds.dat",
                   avg_file: str = "hbonds_avg.dat") -> Dict:
    """Compute hydrogen bonds using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file.
        donor_mask: Donor atom mask.
        acceptor_mask: Acceptor atom mask.
        output_file: Time series output file.
        avg_file: Average hbond output file.

    Returns:
        Dict with hbond data.
    """
    _require_dirs()
    script = f"""trajin {trajectory}
hbond hb donormask {donor_mask} acceptormask {acceptor_mask} out {output_file} avgout {avg_file}
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_hbonds.in")

    result = {}
    if os.path.exists(output_file):
        ts_data = parse_cpptraj_dat(output_file)
        result.update(ts_data)
    if os.path.exists(avg_file):
        avg_data = parse_hbond_output(avg_file)
        result.update(avg_data)

    result['output_file'] = output_file
    result['avg_file'] = avg_file
    return result


def compute_secondary_structure(topology: str, trajectory: str,
                                output_file: str = "secstruct.dat") -> Dict:
    """Compute secondary structure (DSSP) using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file.
        output_file: Output file path.

    Returns:
        Dict with secondary structure data.
    """
    _require_dirs()
    script = f"""trajin {trajectory}
secstruct ss out {output_file} sumout secstruct_summary.dat
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_secstruct.in")

    result = {}
    if os.path.exists(output_file):
        result = parse_cpptraj_dat(output_file)
    if os.path.exists("secstruct_summary.dat"):
        result['summary_file'] = "secstruct_summary.dat"
    result['output_file'] = output_file
    return result


def compute_distance(topology: str, trajectory: str,
                     mask1: str = "", mask2: str = "",
                     output_file: str = "distance.dat") -> Dict:
    """Compute distance between two atom selections using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file.
        mask1: First atom mask.
        mask2: Second atom mask.
        output_file: Output file path.

    Returns:
        Dict with frame, distance arrays and statistics.
    """
    _require_dirs()
    script = f"""trajin {trajectory}
distance dist_calc {mask1} {mask2} out {output_file}
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_distance.in")

    result = parse_cpptraj_dat(output_file)
    result['output_file'] = output_file
    if 'dist_calc' in result:
        dist = result.pop('dist_calc')
        result['distance'] = dist
        result['mean'] = float(np.mean(dist))
        result['std'] = float(np.std(dist))
    return result


def compute_rdf(topology: str, trajectory: str,
                mask1: str = ":WAT@O", mask2: str = ":*@CA",
                rdf_range: float = 12.0, bins: int = 120,
                output_file: str = "rdf.dat") -> Dict:
    """Compute radial distribution function using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file.
        mask1: First atom mask (center).
        mask2: Second atom mask (around).
        rdf_range: Maximum distance in Angstroms.
        bins: Number of histogram bins.
        output_file: Output file path.

    Returns:
        Dict with r, g_r arrays and output_file path.
    """
    _require_dirs()
    spacing = rdf_range / bins
    script = f"""trajin {trajectory}
radial rdf_calc {spacing} {rdf_range} {mask1} {mask2} out {output_file}
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_rdf.in")

    result = parse_cpptraj_dat(output_file)
    result['output_file'] = output_file
    return result


def compute_radgyr(topology: str, trajectory: str,
                   mask: str = "@CA", output_file: str = "radgyr.dat") -> Dict:
    """Compute radius of gyration using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file.
        mask: Atom mask for radius of gyration.
        output_file: Output file path.

    Returns:
        Dict with frame, radgyr arrays and statistics.
    """
    _require_dirs()
    script = f"""trajin {trajectory}
radgyr rg_calc {mask} out {output_file}
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_radgyr.in")

    result = parse_cpptraj_dat(output_file)
    result['output_file'] = output_file
    if 'rg_calc' in result:
        rg = result.pop('rg_calc')
        result['radgyr'] = rg
        result['mean'] = float(np.mean(rg))
        result['std'] = float(np.std(rg))
    return result


def strip_and_image(topology: str, trajectory: str,
                    strip_mask: str = ":WAT,Na+,Cl-",
                    output_traj: str = "stripped.nc",
                    output_prmtop: str = "stripped.prmtop") -> Dict:
    """Strip solvent/ions and image trajectory using cpptraj.

    Args:
        topology: Path to prmtop file.
        trajectory: Path to trajectory file.
        strip_mask: Mask of atoms to strip (solvent, ions).
        output_traj: Output stripped trajectory file.
        output_prmtop: Output stripped topology file.

    Returns:
        Dict with paths to stripped files.
    """
    _require_dirs()
    script = f"""parm {topology}
trajin {trajectory}
autoimage
strip {strip_mask}
trajout {output_traj}
parmwrite out {output_prmtop}
run
"""
    run_cpptraj(topology, script, script_file="cpptraj_strip.in")

    return {
        'trajectory': output_traj,
        'topology': output_prmtop,
    }


def analyze_energy(mdout_file: str) -> Dict:
    """Analyze energy trajectory from sander output.

    Args:
        mdout_file: Path to sander output file.

    Returns:
        Dict with energy statistics and analysis.
    """
    data = parse_mdout(mdout_file)
    result = {}

    if len(data['etot']) > 0:
        result['mean_etot'] = float(np.mean(data['etot']))
        result['std_etot'] = float(np.std(data['etot']))
        result['min_etot'] = float(np.min(data['etot']))
        result['max_etot'] = float(np.max(data['etot']))

    if len(data['temp']) > 0:
        result['mean_temp'] = float(np.mean(data['temp']))
        result['std_temp'] = float(np.std(data['temp']))

    if len(data['press']) > 0:
        result['mean_press'] = float(np.mean(data['press']))
        result['std_press'] = float(np.std(data['press']))

    if len(data['volume']) > 0:
        result['mean_volume'] = float(np.mean(data['volume']))
        result['std_volume'] = float(np.std(data['volume']))

    if len(data['density']) > 0:
        result['mean_density'] = float(np.mean(data['density']))
        result['std_density'] = float(np.std(data['density']))

    # Estimate energy drift if we have enough data
    if len(data['etot']) > 10:
        n = len(data['etot'])
        x = np.arange(n)
        slope, _, _, _, _ = stats.linregress(x, data['etot'])
        result['energy_drift_per_step'] = float(slope)

    result['n_records'] = len(data['etot'])
    result['is_minimization'] = data.get('is_minimization', False)
    return result


def block_average(data: np.ndarray, num_blocks: int = 10) -> Dict:
    """Compute block averages for error estimation.

    Args:
        data: 1D numpy array of values.
        num_blocks: Number of blocks to divide data into.

    Returns:
        Dict with mean, std_err, block_means, block_size.
    """
    data = np.asarray(data)
    n = len(data)
    if n < num_blocks:
        num_blocks = max(1, n)
    block_size = n // num_blocks
    if block_size == 0:
        return {
            'mean': float(np.mean(data)),
            'std_err': float(np.std(data) / np.sqrt(n)) if n > 0 else 0.0,
            'block_means': [float(np.mean(data))],
            'block_size': n,
        }
    block_means = []
    for i in range(num_blocks):
        start = i * block_size
        end = start + block_size
        block_means.append(float(np.mean(data[start:end])))

    overall_mean = float(np.mean(block_means))
    std_err = float(np.std(block_means) / np.sqrt(num_blocks))

    return {
        'mean': overall_mean,
        'std_err': std_err,
        'block_means': block_means,
        'block_size': block_size,
    }


# ============= VISUALIZATION =============

def plot_energy(mdout_data: Dict, output_file: str = "energy.png",
                properties: List[str] = None, title: str = None) -> str:
    """Plot energy/temperature/pressure vs time from sander output.

    Args:
        mdout_data: Dict from parse_mdout().
        output_file: Output image file path.
        properties: List of properties to plot (etot, ektot, eptot, temp, press, volume, density).
        title: Plot title.

    Returns:
        Path to saved figure.
    """
    import matplotlib.pyplot as plt

    if properties is None:
        properties = ['etot', 'temp']
        if len(mdout_data.get('press', [])) > 0:
            properties.append('press')

    n_plots = len(properties)
    fig, axes = plt.subplots(n_plots, 1, figsize=(10, 3 * n_plots), squeeze=False)

    labels = {
        'etot': ('Total Energy', 'kcal/mol'),
        'ektot': ('Kinetic Energy', 'kcal/mol'),
        'eptot': ('Potential Energy', 'kcal/mol'),
        'temp': ('Temperature', 'K'),
        'press': ('Pressure', 'bar'),
        'volume': ('Volume', r'$\AA^3$'),
        'density': ('Density', r'g/cm$^3$'),
    }

    x_data = mdout_data.get('time', np.arange(len(mdout_data.get('etot', []))))
    x_label = 'Time (ps)' if len(mdout_data.get('time', [])) > 0 else 'Step'

    for i, prop in enumerate(properties):
        ax = axes[i, 0]
        y = mdout_data.get(prop, np.array([]))
        if len(y) == 0:
            ax.text(0.5, 0.5, f"No {prop} data", transform=ax.transAxes, ha='center')
            continue
        x = x_data[:len(y)] if len(x_data) >= len(y) else np.arange(len(y))
        label_name, unit = labels.get(prop, (prop, ''))
        ax.plot(x, y, linewidth=0.5)
        ax.set_xlabel(x_label)
        ax.set_ylabel(f"{label_name} ({unit})")
        ax.set_title(f"{label_name} vs {x_label}")
        mean_val = np.mean(y)
        ax.axhline(y=mean_val, color='r', linestyle='--', alpha=0.5,
                    label=f'Mean: {mean_val:.2f}')
        ax.legend()

    if title:
        fig.suptitle(title, fontsize=14)
    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR if _DIRS_CONFIGURED else '.', output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved energy plot: {output_path}")
    return output_path


def plot_rmsd(rmsd_data: Dict, output_file: str = "rmsd.png",
              title: str = None) -> str:
    """Plot RMSD vs time/frame.

    Args:
        rmsd_data: Dict from compute_rmsd().
        output_file: Output image file path.
        title: Plot title.

    Returns:
        Path to saved figure.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))

    rmsd = rmsd_data.get('rmsd', rmsd_data.get('RMSD', np.array([])))
    frames = rmsd_data.get('Frame', rmsd_data.get('#Frame', np.arange(1, len(rmsd) + 1)))
    frames = frames[:len(rmsd)]

    ax.plot(frames, rmsd, linewidth=0.8)
    ax.set_xlabel('Frame')
    ax.set_ylabel(r'RMSD ($\AA$)')
    ax.set_title(title or 'RMSD')
    mean_rmsd = np.mean(rmsd) if len(rmsd) > 0 else 0
    ax.axhline(y=mean_rmsd, color='r', linestyle='--', alpha=0.5,
               label=f'Mean: {mean_rmsd:.2f} A')
    ax.legend()

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR if _DIRS_CONFIGURED else '.', output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved RMSD plot: {output_path}")
    return output_path


def plot_rmsf(rmsf_data: Dict, output_file: str = "rmsf.png",
              title: str = None) -> str:
    """Plot RMSF per residue.

    Args:
        rmsf_data: Dict from compute_rmsf().
        output_file: Output image file path.
        title: Plot title.

    Returns:
        Path to saved figure.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 5))

    rmsf = rmsf_data.get('rmsf', rmsf_data.get('RMSF', np.array([])))
    residues = rmsf_data.get('Atom', rmsf_data.get('#Atom', np.arange(1, len(rmsf) + 1)))
    residues = residues[:len(rmsf)]

    ax.bar(residues, rmsf, width=1.0, alpha=0.7)
    ax.set_xlabel('Residue')
    ax.set_ylabel(r'RMSF ($\AA$)')
    ax.set_title(title or 'Root Mean Square Fluctuation')

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR if _DIRS_CONFIGURED else '.', output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved RMSF plot: {output_path}")
    return output_path


def plot_hbonds(hbond_data: Dict, output_file: str = "hbonds.png",
                title: str = None) -> str:
    """Plot hydrogen bond count over time.

    Args:
        hbond_data: Dict from compute_hbonds() (time series data).
        output_file: Output image file path.
        title: Plot title.

    Returns:
        Path to saved figure.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))

    # Look for total hbond column
    hb_key = None
    for key in hbond_data:
        if 'hb' in key.lower() and key not in ('hbonds', 'n_hbonds'):
            hb_key = key
            break
    if hb_key is None:
        # Try generic column access
        for key in hbond_data:
            if isinstance(hbond_data[key], np.ndarray) and key not in ('Frame', '#Frame'):
                hb_key = key
                break

    if hb_key and isinstance(hbond_data[hb_key], np.ndarray):
        frames = hbond_data.get('Frame', hbond_data.get('#Frame',
                 np.arange(1, len(hbond_data[hb_key]) + 1)))
        ax.plot(frames[:len(hbond_data[hb_key])], hbond_data[hb_key], linewidth=0.5)
        mean_hb = np.mean(hbond_data[hb_key])
        ax.axhline(y=mean_hb, color='r', linestyle='--', alpha=0.5,
                    label=f'Mean: {mean_hb:.1f}')
        ax.legend()

    ax.set_xlabel('Frame')
    ax.set_ylabel('Number of Hydrogen Bonds')
    ax.set_title(title or 'Hydrogen Bonds')

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR if _DIRS_CONFIGURED else '.', output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved H-bond plot: {output_path}")
    return output_path


def plot_rdf(rdf_data: Dict, output_file: str = "rdf.png",
             title: str = None) -> str:
    """Plot radial distribution function g(r).

    Args:
        rdf_data: Dict from compute_rdf().
        output_file: Output image file path.
        title: Plot title.

    Returns:
        Path to saved figure.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))

    # cpptraj RDF output has columns: Bin, rdf_calc, ...
    r_key = None
    g_key = None
    for key in rdf_data:
        if isinstance(rdf_data[key], np.ndarray):
            if r_key is None:
                r_key = key
            elif g_key is None:
                g_key = key

    if r_key and g_key:
        ax.plot(rdf_data[r_key], rdf_data[g_key], linewidth=1.0)
        ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)

    ax.set_xlabel(r'Distance ($\AA$)')
    ax.set_ylabel('g(r)')
    ax.set_title(title or 'Radial Distribution Function')

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR if _DIRS_CONFIGURED else '.', output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved RDF plot: {output_path}")
    return output_path


def plot_secondary_structure(ss_data: Dict, output_file: str = "secstruct.png",
                             title: str = None) -> str:
    """Plot secondary structure fractions per residue.

    Args:
        ss_data: Dict from compute_secondary_structure().
        output_file: Output image file path.
        title: Plot title.

    Returns:
        Path to saved figure.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 5))

    if ss_data:
        keys = [k for k in ss_data.keys()
                if isinstance(ss_data.get(k), np.ndarray) and k not in ('Frame', '#Frame', 'output_file', 'summary_file')]
        if keys:
            frames = ss_data.get('Frame', ss_data.get('#Frame', np.arange(1, len(ss_data[keys[0]]) + 1)))
            for key in keys[:5]:  # Limit to 5 series
                ax.plot(frames[:len(ss_data[key])], ss_data[key], label=key, linewidth=0.5)
            ax.legend()

    ax.set_xlabel('Frame')
    ax.set_ylabel('Fraction')
    ax.set_title(title or 'Secondary Structure')

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR if _DIRS_CONFIGURED else '.', output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved secondary structure plot: {output_path}")
    return output_path


# ============= RESULTS & UTILITIES =============

class NumpyJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles NumPy types."""

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None,
                       status: str = "completed") -> str:
    """Save final results to JSON file (MANDATORY for every script).

    The output JSON has the structure:
        {"status": "...", "summary": <results>, "output_files": {...}, ...}

    IMPORTANT: The ``results`` dict is stored under the ``'summary'`` key.
    Downstream agents reading this file must access ``data['summary']`` to
    retrieve the actual results, NOT the top-level keys.

    Args:
        results: Dict of key results and metrics.
        output_files: Dict mapping names to output file paths.
        file_descriptions: Dict mapping names to descriptions.
        status: Status string (completed, failed, partial).

    Returns:
        Path to the saved JSON file.
    """
    final_data = {
        "status": status,
        "summary": results,
    }
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions

    output_path = os.path.join(
        OUTPUT_DIR if _DIRS_CONFIGURED else '.',
        'final_results.json'
    )
    with open(output_path, 'w') as f:
        json.dump(final_data, f, indent=2, cls=NumpyJSONEncoder)
    logging.info(f"Saved final_results.json to {output_path}")
    return output_path


# ============= CLEANUP =============

def ambertools_cleanup(deep: bool = False) -> None:
    """Clean AmberTools state between calculations.

    Args:
        deep: If True, also remove scratch files.
    """
    if deep:
        _clear_scratch_files()
        logging.info("Deep cleanup completed")


def _clear_scratch_files() -> None:
    """Remove scratch files to free disk space."""
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
    # Also clean common AMBER temp files in workdir
    if _DIRS_CONFIGURED:
        for pattern in ['ANTECHAMBER_*', 'ATOMTYPE.INF', 'sqm.*', 'divcon.*', 'mdin.4dfp.*']:
            for f in glob.glob(os.path.join(WORK_DIR, pattern)):
                try:
                    os.remove(f)
                    cleared += 1
                except OSError:
                    pass
    if cleared:
        logging.info(f"Cleared {cleared} scratch/temp files")
