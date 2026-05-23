#!/usr/bin/env python3
"""
AutoDock utilities library for Microsoft Discovery platform workflows.

This module provides comprehensive functions for molecular docking using AutoDock Vina,
including receptor/ligand preparation, grid box configuration, docking execution,
results parsing, and visualization.

Key Features:
- Receptor preparation from PDB files
- Ligand preparation with 3D coordinate generation
- Automatic grid box calculation from binding site residues
- Single and batch docking workflows
- Docking results parsing and ranking
- Pose visualization and analysis
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
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, asdict, field

# ============= CONSTANTS =============
# Standard directories — MUST be set via quick_setup() before use.
# No defaults: the agent-generated code must provide paths from dataHandlingContext.
INPUT_DIR: str = ''
OUTPUT_DIR: str = ''
WORK_DIR: str = ''
_DIRS_CONFIGURED = False

# AutoDock Vina executable
VINA_EXECUTABLE = "vina"
VINA_GPU_EXECUTABLE = "vina-gpu"

# Open Babel for file conversions
OBABEL = "obabel"

# Default docking parameters
DEFAULT_EXHAUSTIVENESS = 32
DEFAULT_NUM_MODES = 9
DEFAULT_ENERGY_RANGE = 3.0
DEFAULT_CPU = None  # Use all available

# Grid box defaults
DEFAULT_BOX_SIZE = (20.0, 20.0, 20.0)  # Angstroms
DEFAULT_SPACING = 0.375  # Angstroms
MAX_BOX_DIMENSION = 50.0  # Angstroms — boxes larger than this are almost certainly wrong
MAX_LIGAND_ATOMS = 200  # Ligands should not exceed this many atoms

# ============= DATA CLASSES =============

@dataclass
class GridBox:
    """Represents the docking grid box configuration."""
    center_x: float
    center_y: float
    center_z: float
    size_x: float = 20.0
    size_y: float = 20.0
    size_z: float = 20.0
    spacing: float = 0.375

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_vina_params(self) -> str:
        """Generate Vina command line parameters for the grid box."""
        return (f"--center_x {self.center_x:.3f} --center_y {self.center_y:.3f} "
                f"--center_z {self.center_z:.3f} --size_x {self.size_x:.3f} "
                f"--size_y {self.size_y:.3f} --size_z {self.size_z:.3f}")


@dataclass
class DockingResult:
    """Represents a single docking pose result."""
    mode: int
    affinity: float  # kcal/mol
    rmsd_lb: float  # Lower bound RMSD
    rmsd_ub: float  # Upper bound RMSD

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DockingResults:
    """Complete docking results for a ligand."""
    ligand_name: str
    receptor_name: str
    poses: List[DockingResult]
    output_pdbqt: str
    best_affinity: float = 0.0
    config_file: str = ""

    def __post_init__(self):
        if self.poses and self.best_affinity == 0.0:
            self.best_affinity = min(p.affinity for p in self.poses)

    def to_dict(self) -> Dict:
        return {
            "ligand_name": self.ligand_name,
            "receptor_name": self.receptor_name,
            "best_affinity_kcal_mol": self.best_affinity,
            "num_poses": len(self.poses),
            "poses": [p.to_dict() for p in self.poses],
            "output_pdbqt": self.output_pdbqt,
            "config_file": self.config_file
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'DockingResults':
        """Reconstruct a DockingResults from a dict (e.g., from batch_dock output)."""
        poses = [
            DockingResult(
                mode=p.get('mode', i + 1),
                affinity=p.get('affinity', 0.0),
                rmsd_lb=p.get('rmsd_lb', 0.0),
                rmsd_ub=p.get('rmsd_ub', 0.0),
            )
            for i, p in enumerate(d.get('poses', []))
        ]
        return cls(
            ligand_name=d.get('ligand_name', ''),
            receptor_name=d.get('receptor_name', ''),
            poses=poses,
            output_pdbqt=d.get('output_pdbqt', ''),
            best_affinity=d.get('best_affinity_kcal_mol', 0.0),
            config_file=d.get('config_file', ''),
        )


# ============= SETUP FUNCTIONS =============

def _require_dirs():
    """Raise if quick_setup() has not been called."""
    if not _DIRS_CONFIGURED:
        raise RuntimeError(
            "Directories not configured. Call quick_setup(input_dir=..., output_dir=...) "
            "before using any utility functions."
        )


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging with unbuffered output for real-time monitoring."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    # Force unbuffered output
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)


def quick_setup(input_dir, output_dir, work_dir=None, copy_input=True) -> None:
    """Initialize logging, create directories, and optionally copy input files.

    Args:
        input_dir: Path to the input directory (required).
        output_dir: Path to the output directory (required).
        work_dir: Path to the working directory. Defaults to '/app/workdir' if None.
                  IMPORTANT: Must be different from output_dir to avoid SameFileError
                  during quick_finish().
        copy_input: If True, copy input files to work_dir.
    """
    global INPUT_DIR, WORK_DIR, OUTPUT_DIR, _DIRS_CONFIGURED
    INPUT_DIR = input_dir
    OUTPUT_DIR = output_dir
    WORK_DIR = work_dir if work_dir is not None else '/app/workdir'
    _DIRS_CONFIGURED = True
    setup_logging()

    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    logging.info(f"Input directory: {INPUT_DIR}")
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Output directory: {OUTPUT_DIR}")

    # Copy all input files to working directory
    if copy_input and os.path.realpath(INPUT_DIR) != os.path.realpath(WORK_DIR) and os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)
                logging.info(f"Copied input file: {os.path.basename(f)}")
            elif os.path.isdir(f):
                dest = os.path.join(WORK_DIR, os.path.basename(f))
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(f, dest)
                logging.info(f"Copied input directory: {os.path.basename(f)}")

    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Files available: {os.listdir('.')}")


def quick_finish() -> None:
    """Copy output files from working directory to output directory."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        logging.info("Working directory is output directory; skipping copy in quick_finish")
        return

    output_patterns = [
        '*.pdbqt', '*.pdb', '*.sdf', '*.mol2',
        '*.log', '*.txt', '*.out',
        '*.png', '*.svg', '*.pdf',
        '*.json', '*.csv',
        '*_docked.pdbqt', '*_out.pdbqt'
    ]

    for pattern in output_patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            if os.path.isfile(f):
                dest = os.path.join(OUTPUT_DIR, os.path.basename(f))
                if os.path.realpath(f) != os.path.realpath(dest):
                    shutil.copy(f, dest)

    logging.info(f"Outputs copied to {OUTPUT_DIR}")
    if os.path.exists(OUTPUT_DIR):
        logging.info(f"Output files: {os.listdir(OUTPUT_DIR)}")


def save_final_results(
    results: Dict,
    output_files: Optional[Dict[str, str]] = None,
    file_descriptions: Optional[Dict[str, str]] = None,
    status: str = "completed"
) -> None:
    """
    Save final results to JSON file (MANDATORY for all workflows).

    The output JSON has the structure:
        {"status": "...", "summary": <results>, "output_files": {...}, ...}

    IMPORTANT: The ``results`` dict is stored under the ``'summary'`` key.
    Downstream agents reading this file must access ``data['summary']`` to
    retrieve the actual results, NOT the top-level keys.

    Args:
        results: Dictionary containing computation results and metrics
        output_files: Dictionary mapping file keys to file paths
        file_descriptions: Dictionary mapping file keys to descriptions
        status: Workflow status (completed, failed, partial)
    """
    final_data = {
        "status": status,
        "summary": results
    }

    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions

    output_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(output_path, 'w') as f:
        json.dump(final_data, f, indent=2, default=str)

    logging.info(f"Saved final results to {output_path}")


# ============= SYSTEM DETECTION =============

def get_num_cpus() -> int:
    """Get the number of available CPUs."""
    try:
        return os.cpu_count() or 4
    except Exception:
        return 4


def get_available_memory_gb() -> Optional[float]:
    """Get available system memory in GB. Returns None if detection fails."""
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / (1024 * 1024)  # kB -> GB
    except Exception:
        pass
    return None


def compute_max_workers(
    cpu_count: Optional[int] = None,
    memory_per_worker_mb: float = 200,
    cpu_per_worker: int = 1,
    memory_headroom: float = 0.8
) -> int:
    """Compute max parallel workers respecting both CPU and memory limits.

    Returns the minimum of CPU-based and memory-based limits to prevent OOM.

    Args:
        cpu_count: Available CPUs. None = auto-detect.
        memory_per_worker_mb: Estimated peak memory per worker process in MB.
        cpu_per_worker: CPUs allocated to each worker.
        memory_headroom: Fraction of available memory to use (0.8 = 80%).

    Returns:
        Max workers (at least 1).
    """
    if cpu_count is None:
        cpu_count = get_num_cpus()

    cpu_workers = max(1, cpu_count // cpu_per_worker - 2)

    avail_gb = get_available_memory_gb()
    if avail_gb is not None and memory_per_worker_mb > 0:
        mem_workers = max(1, int(avail_gb * memory_headroom * 1024 / memory_per_worker_mb))
        workers = min(cpu_workers, mem_workers)
        if mem_workers < cpu_workers:
            logging.info(f"  Memory-limited: {avail_gb:.1f}GB avail, "
                         f"~{memory_per_worker_mb}MB/worker -> "
                         f"{mem_workers} workers (vs {cpu_workers} from CPUs)")
        return workers

    return cpu_workers


def check_gpu_available() -> bool:
    """Check if GPU is available for AutoDock-GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def detect_file_format(filepath: str) -> str:
    """Detect molecular file format from extension."""
    ext = Path(filepath).suffix.lower()
    format_map = {
        '.pdb': 'pdb',
        '.pdbqt': 'pdbqt',
        '.mol': 'mol',
        '.mol2': 'mol2',
        '.sdf': 'sdf',
        '.xyz': 'xyz',
        '.smi': 'smi',
        '.smiles': 'smi'
    }
    return format_map.get(ext, 'unknown')


# ============= FILE CONVERSION FUNCTIONS =============

def run_command(
    cmd: List[str],
    input_text: Optional[str] = None,
    cwd: Optional[str] = None,
    timeout: int = 3600
) -> subprocess.CompletedProcess:
    """
    Execute a command with proper error handling.

    Args:
        cmd: Command as list of strings
        input_text: Optional input text to pass to stdin
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        CompletedProcess object
    """
    try:
        kwargs = {
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": timeout
        }
        if cwd:
            kwargs["cwd"] = cwd
        if input_text:
            kwargs["input"] = input_text

        result = subprocess.run(cmd, **kwargs)
        logging.info(f"Command completed: {' '.join(cmd[:3])}...")
        return result

    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(cmd)}")
        logging.error(f"STDERR: {e.stderr}")
        logging.error(f"STDOUT: {e.stdout}")
        raise
    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout}s: {' '.join(cmd)}")
        raise


def convert_to_pdbqt(
    input_file: str,
    output_file: str,
    is_receptor: bool = False,
    add_hydrogens: bool = True,
    ph: float = 7.4
) -> str:
    """
    Convert molecular file to PDBQT format using Open Babel.

    Args:
        input_file: Input molecular file (PDB, MOL2, SDF, etc.)
        output_file: Output PDBQT file path
        is_receptor: True for receptor (rigid), False for ligand (flexible)
        add_hydrogens: Whether to add hydrogens
        ph: pH for protonation state

    Returns:
        Path to output PDBQT file
    """
    input_format = detect_file_format(input_file)

    cmd = [OBABEL, input_file, "-O", output_file]

    if add_hydrogens:
        cmd.extend(["-h", f"--ph", str(ph)])

    # Add partial charges (Gasteiger)
    cmd.append("--partialcharge")
    cmd.append("gasteiger")

    run_command(cmd)
    logging.info(f"Converted {input_file} to {output_file}")

    return output_file


def pdb_to_pdbqt_receptor(
    pdb_file: str,
    output_file: Optional[str] = None,
    remove_waters: bool = True,
    remove_heteroatoms: bool = False,
    add_hydrogens: bool = True
) -> str:
    """
    Prepare receptor PDBQT from PDB file.

    Args:
        pdb_file: Input PDB file
        output_file: Output PDBQT file (default: same name with .pdbqt)
        remove_waters: Remove water molecules
        remove_heteroatoms: Remove all heteroatoms (ligands, ions, etc.)
        add_hydrogens: Add hydrogen atoms

    Returns:
        Path to prepared receptor PDBQT file
    """
    if output_file is None:
        output_file = Path(pdb_file).stem + "_receptor.pdbqt"

    # First clean the PDB file
    cleaned_pdb = Path(pdb_file).stem + "_cleaned.pdb"

    with open(pdb_file, 'r') as f:
        lines = f.readlines()

    cleaned_lines = []
    for line in lines:
        # Keep ATOM records
        if line.startswith('ATOM'):
            cleaned_lines.append(line)
        # Keep HETATM unless removing
        elif line.startswith('HETATM'):
            residue = line[17:20].strip()
            if remove_waters and residue in ['HOH', 'WAT', 'H2O', 'TIP']:
                continue
            if remove_heteroatoms:
                continue
            cleaned_lines.append(line)
        # Keep connectivity and end records
        elif line.startswith(('TER', 'END', 'CONECT')):
            cleaned_lines.append(line)

    with open(cleaned_pdb, 'w') as f:
        f.writelines(cleaned_lines)

    # Convert to PDBQT
    cmd = [OBABEL, cleaned_pdb, "-O", output_file, "-xr"]
    if add_hydrogens:
        cmd.append("-h")
    cmd.extend(["--partialcharge", "gasteiger"])

    run_command(cmd)
    logging.info(f"Prepared receptor: {output_file}")

    return output_file


def prepare_ligand(
    input_file: str,
    output_file: Optional[str] = None,
    add_hydrogens: bool = True,
    gen_3d: bool = True,
    ph: float = 7.4,
    num_conformers: int = 1
) -> str:
    """
    Prepare ligand PDBQT from various input formats.

    Args:
        input_file: Input ligand file (SDF, MOL2, PDB, SMILES)
        output_file: Output PDBQT file
        add_hydrogens: Add hydrogens at specified pH
        gen_3d: Generate 3D coordinates if needed
        ph: pH for protonation
        num_conformers: Number of conformers to generate

    Returns:
        Path to prepared ligand PDBQT file
    """
    if output_file is None:
        output_file = Path(input_file).stem + "_ligand.pdbqt"

    input_format = detect_file_format(input_file)

    cmd = [OBABEL, input_file, "-O", output_file]

    if add_hydrogens:
        cmd.extend(["-h", "--ph", str(ph)])

    if gen_3d and input_format in ['smi', 'smiles']:
        cmd.append("--gen3d")

    cmd.extend(["--partialcharge", "gasteiger"])

    run_command(cmd)
    logging.info(f"Prepared ligand: {output_file}")

    return output_file


def smiles_to_pdbqt(
    smiles: str,
    output_file: str,
    name: str = "ligand",
    add_hydrogens: bool = True,
    gen_3d: bool = True
) -> str:
    """
    Convert SMILES string to PDBQT file.

    Args:
        smiles: SMILES string
        output_file: Output PDBQT file path
        name: Molecule name
        add_hydrogens: Add hydrogens
        gen_3d: Generate 3D coordinates

    Returns:
        Path to output PDBQT file
    """
    # Write SMILES to temp file
    smi_file = f"{name}.smi"
    with open(smi_file, 'w') as f:
        f.write(f"{smiles} {name}\n")

    return prepare_ligand(
        smi_file,
        output_file,
        add_hydrogens=add_hydrogens,
        gen_3d=gen_3d
    )


# ============= GRID BOX FUNCTIONS =============

# Common non-ligand HETATM residue names to exclude when extracting ligands
_NON_LIGAND_HETATMS = frozenset({
    'HOH', 'WAT', 'DOD', 'TIP',  # Water
    'NA', 'CL', 'MG', 'ZN', 'CA', 'MN', 'FE', 'CU', 'CO', 'NI', 'K',  # Ions
    'SO4', 'PO4', 'NO3', 'CO3',  # Common anions
    'GOL', 'EDO', 'PEG', 'PGE', 'DMS', 'MPD',  # Cryoprotectants / buffers
    'ACE', 'NME', 'NH2',  # Capping groups
    'UNX', 'UNL',  # Unknown atoms/ligands
})


def extract_reference_ligand(
    pdb_file: str,
    ligand_resname: Optional[str] = None,
    output_file: Optional[str] = None
) -> str:
    """Extract the co-crystallized ligand from a PDB file.

    If ligand_resname is given, extract that specific HETATM residue.
    Otherwise, auto-detect: find the largest non-water/ion HETATM group.

    Args:
        pdb_file: Path to receptor PDB file containing the ligand
        ligand_resname: Specific residue name (e.g., 'LZ9', 'ISP'). None = auto-detect.
        output_file: Path for the extracted ligand PDB. None = auto-generated.

    Returns:
        Path to a PDB file containing only the ligand atoms.

    Raises:
        ValueError: If no suitable ligand found in the PDB file.
    """
    if output_file is None:
        output_file = Path(pdb_file).stem + "_ligand.pdb"

    hetatm_groups: Dict[str, List[str]] = {}  # resname -> list of PDB lines

    with open(pdb_file, 'r') as f:
        for line in f:
            if line.startswith('HETATM'):
                resname = line[17:20].strip()
                if resname not in _NON_LIGAND_HETATMS:
                    if resname not in hetatm_groups:
                        hetatm_groups[resname] = []
                    hetatm_groups[resname].append(line)

    if not hetatm_groups:
        raise ValueError(
            f"No ligand HETATM records found in {pdb_file}. "
            f"The PDB may not contain a co-crystallized ligand. "
            f"Use calculate_grid_box_from_residues() instead."
        )

    if ligand_resname:
        if ligand_resname not in hetatm_groups:
            available = sorted(hetatm_groups.keys())
            raise ValueError(
                f"Ligand '{ligand_resname}' not found in {pdb_file}. "
                f"Available HETATM residues: {available}"
            )
        selected_name = ligand_resname
    else:
        # Auto-detect: pick the largest HETATM group (most atoms = likely the drug)
        selected_name = max(hetatm_groups.keys(), key=lambda r: len(hetatm_groups[r]))
        logging.info(f"Auto-detected ligand: {selected_name} "
                     f"({len(hetatm_groups[selected_name])} atoms) "
                     f"from {len(hetatm_groups)} HETATM groups")

    ligand_lines = hetatm_groups[selected_name]

    with open(output_file, 'w') as f:
        for line in ligand_lines:
            f.write(line)
        f.write("END\n")

    logging.info(f"Extracted ligand {selected_name} ({len(ligand_lines)} atoms) "
                 f"-> {output_file}")
    return output_file

def read_pdb_coordinates(pdb_file: str) -> List[Tuple[float, float, float]]:
    """Read all atom coordinates from PDB file."""
    coords = []
    with open(pdb_file, 'r') as f:
        for line in f:
            if line.startswith(('ATOM', 'HETATM')):
                try:
                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])
                    coords.append((x, y, z))
                except ValueError:
                    continue
    return coords


def read_pdbqt_coordinates(pdbqt_file: str) -> List[Tuple[float, float, float]]:
    """Read atom coordinates from PDBQT file."""
    coords = []
    with open(pdbqt_file, 'r') as f:
        for line in f:
            if line.startswith(('ATOM', 'HETATM')):
                try:
                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])
                    coords.append((x, y, z))
                except ValueError:
                    continue
    return coords


def calculate_grid_box_from_coords(
    coords: List[Tuple[float, float, float]],
    padding: float = 5.0
) -> GridBox:
    """
    Calculate grid box that encompasses given coordinates with padding.

    Args:
        coords: List of (x, y, z) coordinates
        padding: Extra space around coordinates in Angstroms

    Returns:
        GridBox object
    """
    if not coords:
        raise ValueError("No coordinates provided")

    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]

    center_x = (min(xs) + max(xs)) / 2
    center_y = (min(ys) + max(ys)) / 2
    center_z = (min(zs) + max(zs)) / 2

    size_x = max(xs) - min(xs) + 2 * padding
    size_y = max(ys) - min(ys) + 2 * padding
    size_z = max(zs) - min(zs) + 2 * padding

    return GridBox(
        center_x=center_x,
        center_y=center_y,
        center_z=center_z,
        size_x=size_x,
        size_y=size_y,
        size_z=size_z
    )


def calculate_grid_box_from_ligand(
    ligand_file: str,
    padding: float = 5.0
) -> GridBox:
    """
    Calculate grid box centered on a reference ligand.

    IMPORTANT: This function expects a LIGAND file (small molecule, <200 atoms),
    NOT a full receptor PDB. If you have a receptor PDB with a co-crystallized
    ligand, first call extract_reference_ligand() to get just the ligand.

    Args:
        ligand_file: Path to ligand PDB/PDBQT/SDF file
        padding: Extra space around ligand in Angstroms

    Returns:
        GridBox object

    Raises:
        ValueError: If the file has too many atoms (likely a receptor, not a ligand)
                    or if the resulting box exceeds MAX_BOX_DIMENSION
    """
    file_format = detect_file_format(ligand_file)

    if file_format in ['pdb', 'pdbqt']:
        coords = read_pdbqt_coordinates(ligand_file)
    else:
        # Convert to PDB first
        temp_pdb = "temp_ligand.pdb"
        run_command([OBABEL, ligand_file, "-O", temp_pdb])
        coords = read_pdb_coordinates(temp_pdb)
        os.remove(temp_pdb)

    # Guard: detect if a full receptor was passed instead of a ligand
    if len(coords) > MAX_LIGAND_ATOMS:
        raise ValueError(
            f"File '{ligand_file}' has {len(coords)} atoms — this looks like a "
            f"receptor, not a ligand (expected <{MAX_LIGAND_ATOMS} atoms). "
            f"Use extract_reference_ligand() to extract the co-crystallized "
            f"ligand first, or use calculate_grid_box_from_residues() instead."
        )

    box = calculate_grid_box_from_coords(coords, padding)

    # Guard: reject absurdly large boxes
    max_dim = max(box.size_x, box.size_y, box.size_z)
    if max_dim > MAX_BOX_DIMENSION:
        raise ValueError(
            f"Calculated grid box is {box.size_x:.0f} x {box.size_y:.0f} x "
            f"{box.size_z:.0f} Å — this is too large for focused docking "
            f"(max {MAX_BOX_DIMENSION} Å per dimension). Check that you "
            f"passed a ligand file, not a receptor."
        )

    return box


def calculate_grid_box_from_residues(
    pdb_file: str,
    residue_ids: List[str],
    padding: float = 5.0
) -> GridBox:
    """
    Calculate grid box centered on specific residues.

    Args:
        pdb_file: Path to receptor PDB file
        residue_ids: List of residue IDs (e.g., ["ASP25", "ILE50", "VAL82"])
        padding: Extra space around residues in Angstroms

    Returns:
        GridBox object
    """
    coords = []

    # Parse residue IDs to get residue names and numbers
    residue_specs = []
    for rid in residue_ids:
        # Extract residue name and number (e.g., "ASP25" -> ("ASP", 25))
        match = re.match(r'([A-Z]+)(\d+)', rid.upper())
        if match:
            residue_specs.append((match.group(1), int(match.group(2))))
        else:
            # Try just number
            try:
                residue_specs.append((None, int(rid)))
            except ValueError:
                logging.warning(f"Could not parse residue ID: {rid}")

    with open(pdb_file, 'r') as f:
        for line in f:
            if line.startswith(('ATOM', 'HETATM')):
                try:
                    res_name = line[17:20].strip()
                    res_num = int(line[22:26])

                    for spec_name, spec_num in residue_specs:
                        if spec_num == res_num:
                            if spec_name is None or spec_name == res_name:
                                x = float(line[30:38])
                                y = float(line[38:46])
                                z = float(line[46:54])
                                coords.append((x, y, z))
                                break
                except (ValueError, IndexError):
                    continue

    if not coords:
        raise ValueError(f"No atoms found for residues: {residue_ids}")

    return calculate_grid_box_from_coords(coords, padding)


def create_grid_box(
    center: Tuple[float, float, float],
    size: Tuple[float, float, float] = DEFAULT_BOX_SIZE
) -> GridBox:
    """
    Create a grid box with specified center and size.

    Args:
        center: (x, y, z) center coordinates in Angstroms
        size: (x, y, z) box dimensions in Angstroms

    Returns:
        GridBox object
    """
    return GridBox(
        center_x=center[0],
        center_y=center[1],
        center_z=center[2],
        size_x=size[0],
        size_y=size[1],
        size_z=size[2]
    )


# ============= DOCKING EXECUTION =============

def write_vina_config(
    receptor: str,
    ligand: str,
    grid_box: GridBox,
    output_file: str = "config.txt",
    exhaustiveness: int = DEFAULT_EXHAUSTIVENESS,
    num_modes: int = DEFAULT_NUM_MODES,
    energy_range: float = DEFAULT_ENERGY_RANGE,
    cpu: Optional[int] = None,
    seed: Optional[int] = None
) -> str:
    """
    Write Vina configuration file.

    Args:
        receptor: Path to receptor PDBQT file
        ligand: Path to ligand PDBQT file
        grid_box: GridBox object with search space
        output_file: Path to output config file
        exhaustiveness: Search exhaustiveness
        num_modes: Maximum number of poses
        energy_range: Energy range for poses
        cpu: Number of CPUs (None for auto)
        seed: Random seed for reproducibility

    Returns:
        Path to config file
    """
    out_pdbqt = Path(ligand).stem + "_out.pdbqt"

    config_lines = [
        f"receptor = {receptor}",
        f"ligand = {ligand}",
        f"out = {out_pdbqt}",
        "",
        f"center_x = {grid_box.center_x:.3f}",
        f"center_y = {grid_box.center_y:.3f}",
        f"center_z = {grid_box.center_z:.3f}",
        "",
        f"size_x = {grid_box.size_x:.3f}",
        f"size_y = {grid_box.size_y:.3f}",
        f"size_z = {grid_box.size_z:.3f}",
        "",
        f"exhaustiveness = {exhaustiveness}",
        f"num_modes = {num_modes}",
        f"energy_range = {energy_range}",
    ]

    if cpu:
        config_lines.append(f"cpu = {cpu}")

    if seed is not None:
        config_lines.append(f"seed = {seed}")

    with open(output_file, 'w') as f:
        f.write('\n'.join(config_lines))

    logging.info(f"Wrote Vina config: {output_file}")
    return output_file


def run_vina(
    config_file: str = None,
    receptor: str = None,
    ligand: str = None,
    grid_box: GridBox = None,
    output_pdbqt: str = None,
    exhaustiveness: int = DEFAULT_EXHAUSTIVENESS,
    num_modes: int = DEFAULT_NUM_MODES,
    energy_range: float = DEFAULT_ENERGY_RANGE,
    cpu: Optional[int] = None,
    seed: Optional[int] = None,
    log_file: str = "vina.log"
) -> DockingResults:
    """
    Run AutoDock Vina docking.

    Args:
        config_file: Path to config file (if using config-based approach)
        receptor: Path to receptor PDBQT (if not using config)
        ligand: Path to ligand PDBQT (if not using config)
        grid_box: GridBox object (if not using config)
        output_pdbqt: Output PDBQT file path
        exhaustiveness: Search exhaustiveness
        num_modes: Maximum number of poses to generate
        energy_range: Energy range for poses
        cpu: Number of CPUs
        seed: Random seed
        log_file: Path to log file

    Returns:
        DockingResults object
    """
    if config_file:
        cmd = [VINA_EXECUTABLE, "--config", config_file]

        # Parse config to get file paths
        with open(config_file, 'r') as f:
            config_content = f.read()

        receptor_match = re.search(r'receptor\s*=\s*(\S+)', config_content)
        ligand_match = re.search(r'ligand\s*=\s*(\S+)', config_content)
        out_match = re.search(r'out\s*=\s*(\S+)', config_content)

        receptor = receptor_match.group(1) if receptor_match else "unknown"
        ligand = ligand_match.group(1) if ligand_match else "unknown"
        output_pdbqt = out_match.group(1) if out_match else f"{Path(ligand).stem}_out.pdbqt"

    else:
        if not all([receptor, ligand, grid_box]):
            raise ValueError("Must provide either config_file or (receptor, ligand, grid_box)")

        # Safety check: reject grid boxes that are too large
        max_dim = max(grid_box.size_x, grid_box.size_y, grid_box.size_z)
        if max_dim > MAX_BOX_DIMENSION:
            raise ValueError(
                f"Grid box is {grid_box.size_x:.0f} x {grid_box.size_y:.0f} x "
                f"{grid_box.size_z:.0f} Å — exceeds the {MAX_BOX_DIMENSION} Å "
                f"safety limit. A box this large will consume excessive memory "
                f"(~{max_dim * grid_box.size_y * grid_box.size_z / 1e6:.0f}M grid points) "
                f"and produce unreliable results. Use a focused binding site box "
                f"(typically 20-30 Å per side)."
            )

        if output_pdbqt is None:
            output_pdbqt = Path(ligand).stem + "_out.pdbqt"

        cmd = [
            VINA_EXECUTABLE,
            "--receptor", receptor,
            "--ligand", ligand,
            "--out", output_pdbqt,
            "--center_x", str(grid_box.center_x),
            "--center_y", str(grid_box.center_y),
            "--center_z", str(grid_box.center_z),
            "--size_x", str(grid_box.size_x),
            "--size_y", str(grid_box.size_y),
            "--size_z", str(grid_box.size_z),
            "--exhaustiveness", str(exhaustiveness),
            "--num_modes", str(num_modes),
            "--energy_range", str(energy_range)
        ]

        if cpu:
            cmd.extend(["--cpu", str(cpu)])

        if seed is not None:
            cmd.extend(["--seed", str(seed)])

    logging.info(f"Running Vina: {' '.join(cmd)}")

    # Run docking
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=7200  # 2 hour timeout
    )

    # Save log
    with open(log_file, 'w') as f:
        f.write("=== STDOUT ===\n")
        f.write(result.stdout)
        f.write("\n=== STDERR ===\n")
        f.write(result.stderr)

    if result.returncode != 0:
        logging.error(f"Vina failed with return code {result.returncode}")
        logging.error(f"STDERR: {result.stderr}")
        raise RuntimeError(f"Vina docking failed: {result.stderr}")

    # Parse results
    poses = parse_vina_output(result.stdout)

    return DockingResults(
        ligand_name=Path(ligand).stem,
        receptor_name=Path(receptor).stem,
        poses=poses,
        output_pdbqt=output_pdbqt,
        config_file=config_file or ""
    )


def parse_vina_output(stdout: str) -> List[DockingResult]:
    """
    Parse Vina stdout to extract docking results.

    Args:
        stdout: Vina stdout content

    Returns:
        List of DockingResult objects
    """
    poses = []

    # Pattern: mode | affinity | rmsd l.b. | rmsd u.b.
    # Example:    1     -10.3      0.000      0.000
    pattern = r'^\s*(\d+)\s+([-\d.]+)\s+([\d.]+)\s+([\d.]+)'

    in_results = False
    for line in stdout.split('\n'):
        if 'mode |   affinity' in line.lower() or 'mode |  affinity' in line:
            in_results = True
            continue

        if in_results:
            match = re.match(pattern, line)
            if match:
                poses.append(DockingResult(
                    mode=int(match.group(1)),
                    affinity=float(match.group(2)),
                    rmsd_lb=float(match.group(3)),
                    rmsd_ub=float(match.group(4))
                ))

    return poses


# ============= BATCH DOCKING =============

def batch_dock(
    receptor: str,
    ligand_files: List[str],
    grid_box: GridBox,
    exhaustiveness: int = DEFAULT_EXHAUSTIVENESS,
    num_modes: int = DEFAULT_NUM_MODES,
    output_dir: str = "docking_results",
    max_workers: Optional[int] = None,
    cpu_per_worker: int = 1
) -> List[Dict]:
    """
    Dock multiple ligands against a single receptor using parallel execution.

    Each ligand runs in its own Vina process. By default, each worker uses
    1 CPU core, maximizing throughput for large screening campaigns.
    For small campaigns with complex ligands, increase cpu_per_worker to
    speed up individual dockings at the cost of fewer concurrent workers.

    Throughput guide (96-vCPU node, exhaustiveness=16):
      cpu_per_worker=1: 94 workers, ~90s/ligand, ~63 ligands/min (best for screening)
      cpu_per_worker=2: 47 workers, ~50s/ligand, ~56 ligands/min
      cpu_per_worker=4: 24 workers, ~30s/ligand, ~48 ligands/min (best for <50 ligands)

    Includes automatic checkpointing to /output/ (blob-mounted). Partial results
    survive OOM kills and cancellation.

    Args:
        receptor: Path to receptor PDBQT file
        ligand_files: List of ligand PDBQT file paths
        grid_box: GridBox object for all dockings
        exhaustiveness: Search exhaustiveness (default: 32)
        num_modes: Maximum poses per ligand (default: 9)
        output_dir: Directory for output files
        max_workers: Max parallel workers (default: auto-detect from CPU and memory).
                     Set to 1 for sequential execution.
        cpu_per_worker: CPU cores allocated to each Vina process (default: 1).
                        Vina's --cpu flag. Higher values speed up individual dockings
                        but reduce the number of concurrent workers.
        num_modes: Maximum poses per ligand (default: 9)
        output_dir: Directory for output files
        max_workers: Max parallel workers (default: number of CPUs minus 2,
                     minimum 1). Set to 1 for sequential execution.

    Returns:
        List of result dictionaries (same schema as DockingResults.to_dict(),
        with an additional 'error' key for failed dockings)
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import threading

    os.makedirs(output_dir, exist_ok=True)

    if max_workers is None:
        max_workers = compute_max_workers(
            memory_per_worker_mb=300,  # Vina + receptor loading per worker
            cpu_per_worker=cpu_per_worker
        )
    logging.info(f"batch_dock config: {max_workers} workers x {cpu_per_worker} CPUs/worker "
                 f"= {max_workers * cpu_per_worker} total cores")

    total = len(ligand_files)
    # Write checkpoint to OUTPUT_DIR so it's visible on blob storage during
    # execution and survives OOM/cancellation.
    checkpoint_path = os.path.join(OUTPUT_DIR, "_docking_checkpoint.jsonl")

    # ── Resume: load previously completed results ──
    completed_map = {}  # ligand_name -> result dict
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        completed_map[entry.get("ligand_name", "")] = entry
            if completed_map:
                logging.info(f"Resuming: {len(completed_map)}/{total} ligands "
                             f"already docked (from checkpoint)")
        except Exception as e:
            logging.warning(f"Could not read checkpoint, starting fresh: {e}")
            completed_map = {}

    # Determine which ligands still need docking
    remaining_args = []
    remaining_indices = []
    results = [None] * total

    for idx, lig in enumerate(ligand_files):
        ligand_name = Path(lig).stem
        if ligand_name in completed_map:
            results[idx] = completed_map[ligand_name]
        else:
            remaining_args.append(
                (receptor, lig, grid_box.to_dict(), exhaustiveness, num_modes, output_dir, cpu_per_worker)
            )
            remaining_indices.append(idx)

    skipped = total - len(remaining_indices)
    logging.info(f"Batch docking: {total} ligands, {skipped} cached, "
                 f"{len(remaining_indices)} to dock, {max_workers} workers")

    if not remaining_indices:
        logging.info("All ligands already docked (checkpoint complete)")
        return results

    # Thread-safe checkpoint writer
    _ckpt_lock = threading.Lock()

    def _save_checkpoint(result_dict):
        with _ckpt_lock:
            with open(checkpoint_path, 'a') as f:
                f.write(json.dumps(result_dict, default=str) + '\n')

    completed = 0
    _last_log_time = time.time()
    _LOG_INTERVAL = 60  # Log at least every 60 seconds
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(_dock_single_ligand, args): remaining_indices[i]
            for i, args in enumerate(remaining_args)
        }
        logging.info(f"  All {len(remaining_indices)} docking tasks submitted to "
                     f"{max_workers} workers \u2014 waiting for first results...")
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
            except Exception as e:
                ligand_name = Path(ligand_files[idx]).stem
                result = {
                    "ligand_name": ligand_name,
                    "receptor_name": Path(receptor).stem,
                    "best_affinity_kcal_mol": float('inf'),
                    "num_poses": 0,
                    "poses": [],
                    "output_pdbqt": "",
                    "error": str(e)
                }
            results[idx] = result
            _save_checkpoint(result)
            completed += 1
            now = time.time()
            if (completed == 1
                    or completed == len(remaining_indices)
                    or now - _last_log_time >= _LOG_INTERVAL):
                logging.info(f"  Docking progress: {skipped + completed}/{total} "
                             f"({completed} new)")
                _last_log_time = now

    successful = sum(1 for r in results if r and 'error' not in r)
    logging.info(f"Batch docking complete: {successful}/{total} successful")
    return results


# Keep as alias for backward compatibility
parallel_batch_dock = batch_dock


def _dock_single_ligand(args):
    """Worker function for parallel batch docking. Runs in a subprocess."""
    receptor, ligand, grid_box_dict, exhaustiveness, num_modes, output_dir, cpu = args
    ligand_name = Path(ligand).stem
    output_pdbqt = os.path.join(output_dir, f"{ligand_name}_out.pdbqt")
    log_file = os.path.join(output_dir, f"{ligand_name}.log")

    grid_box = GridBox(**grid_box_dict)

    try:
        result = run_vina(
            receptor=receptor,
            ligand=ligand,
            grid_box=grid_box,
            output_pdbqt=output_pdbqt,
            exhaustiveness=exhaustiveness,
            num_modes=num_modes,
            cpu=cpu,
            log_file=log_file
        )
        return result.to_dict()
    except Exception as e:
        return {
            "ligand_name": ligand_name,
            "receptor_name": Path(receptor).stem,
            "best_affinity_kcal_mol": float('inf'),
            "num_poses": 0,
            "poses": [],
            "output_pdbqt": "",
            "error": str(e)
        }


def _normalize_result(r):
    """Access a result whether it's a DockingResults object or a dict."""
    if isinstance(r, dict):
        return r
    return {
        'ligand_name': r.ligand_name,
        'best_affinity_kcal_mol': r.best_affinity,
        'num_poses': len(r.poses),
        'poses': r.poses,
        'output_pdbqt': r.output_pdbqt,
    }


# ============= BATCH LIGAND PREPARATION =============

def _prepare_single_ligand(args: Tuple) -> Dict[str, Any]:
    """Worker function for batch_prepare_ligands. Runs in a thread."""
    name, input_value, output_path, is_smiles = args
    try:
        if is_smiles:
            result_path = smiles_to_pdbqt(input_value, output_path, name=name)
        else:
            result_path = prepare_ligand(input_value, output_path)
        if result_path and os.path.exists(result_path):
            return {"name": name, "path": result_path, "error": None}
        else:
            return {"name": name, "path": None, "error": "no output file produced"}
    except Exception as e:
        return {"name": name, "path": None, "error": str(e)}


def batch_prepare_ligands(
    inputs: List[Union[str, Dict[str, str]]],
    output_dir: str = "prepared_ligands",
    max_workers: Optional[int] = None,
    parallel: bool = True
) -> Tuple[List[str], List[Dict]]:
    """
    Prepare multiple ligands to PDBQT format in parallel.

    Uses ThreadPoolExecutor because each conversion spawns an `obabel`
    subprocess (GIL is released during subprocess.run), so threads provide
    full parallelism without process-forking overhead. On a 96-vCPU node,
    this converts ~1,500 SMILES in ~30s vs ~25min sequentially (~50x speedup).

    Skips ligands whose output PDBQT already exists (idempotent/resumable).

    Each input can be:
      - A SMILES string (auto-named ligand_0001, ligand_0002, ...)
      - A file path to SDF/MOL2/PDB/SMI (named from file stem)
      - A dict with keys:
          'smiles' + optional 'name'  -> converted from SMILES
          'file'   + optional 'name'  -> converted from file

    Args:
        inputs: List of ligand inputs (SMILES strings, file paths, or dicts)
        output_dir: Directory for output PDBQT files
        max_workers: Number of parallel threads. None = os.cpu_count() - 2
        parallel: If True (default), run conversions in parallel.
                  Set to False for sequential execution (debugging).

    Returns:
        Tuple of (pdbqt_paths, failures) where:
          - pdbqt_paths: List of successfully created PDBQT file paths
          - failures: List of dicts with 'name', 'input', 'error' keys
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    os.makedirs(output_dir, exist_ok=True)

    # Normalize inputs into (name, input_value, output_path, is_smiles) tuples
    work_items = []
    known_formats = {'sdf', 'mol2', 'pdb', 'pdbqt', 'mol', 'smi'}

    for i, inp in enumerate(inputs):
        if isinstance(inp, dict):
            name = inp.get('name', f'ligand_{i:05d}')
            if 'smiles' in inp:
                output_path = os.path.join(output_dir, f"{name}.pdbqt")
                work_items.append((name, inp['smiles'], output_path, True))
            elif 'file' in inp:
                output_path = os.path.join(output_dir, f"{name}.pdbqt")
                work_items.append((name, inp['file'], output_path, False))
        elif isinstance(inp, str):
            # Heuristic: if it looks like an existing file path, use prepare_ligand
            ext = Path(inp).suffix.lstrip('.').lower() if '.' in inp else ''
            if ext in known_formats and os.path.exists(inp):
                name = Path(inp).stem
                output_path = os.path.join(output_dir, f"{name}.pdbqt")
                work_items.append((name, inp, output_path, False))
            else:
                # Treat as SMILES
                name = f'ligand_{i:05d}'
                output_path = os.path.join(output_dir, f"{name}.pdbqt")
                work_items.append((name, inp, output_path, True))

    # Skip already-converted ligands
    to_process = []
    already_done = []
    for item in work_items:
        name, input_value, output_path, is_smiles = item
        if os.path.exists(output_path):
            already_done.append(output_path)
        else:
            to_process.append(item)

    total = len(work_items)
    logging.info(f"Batch ligand prep: {total} inputs, {len(already_done)} cached, "
                 f"{len(to_process)} to convert")

    if not to_process:
        return already_done, []

    if not parallel or len(to_process) <= 1:
        # Sequential fallback
        results = [_prepare_single_ligand(item) for item in to_process]
    else:
        if max_workers is None:
            max_workers = compute_max_workers(
                memory_per_worker_mb=200,  # obabel 3D conformer generation
                cpu_per_worker=1
            )

        logging.info(f"Parallel ligand prep: {len(to_process)} conversions, "
                     f"{max_workers} threads")

        results = [None] * len(to_process)
        completed = 0
        _last_log_time = time.time()
        _LOG_INTERVAL = 30  # Log at least every 30 seconds
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(_prepare_single_ligand, item): idx
                for idx, item in enumerate(to_process)
            }
            logging.info(f"  All {len(to_process)} prep tasks submitted \u2014 "
                         f"waiting for first results...")
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()
                completed += 1
                now = time.time()
                if (completed == 1
                        or completed == len(to_process)
                        or now - _last_log_time >= _LOG_INTERVAL):
                    logging.info(f"  Ligand prep progress: "
                                 f"{len(already_done) + completed}/{total}")
                    _last_log_time = now

    pdbqt_paths = list(already_done)
    failures = []
    for r in results:
        if r["error"] is None:
            pdbqt_paths.append(r["path"])
        else:
            failures.append({"name": r["name"], "input": r.get("input", ""), "error": r["error"]})

    logging.info(f"Ligand prep complete: {len(pdbqt_paths)} succeeded, "
                 f"{len(failures)} failed")

    # Write progress summary to /output/ for monitoring and OOM survival
    try:
        progress_path = os.path.join(OUTPUT_DIR, "_ligand_prep_progress.json")
        json.dump({
            "total_inputs": total,
            "prepared": len(pdbqt_paths),
            "failed": len(failures),
            "failure_details": failures[:50],
        }, open(progress_path, 'w'), indent=2, default=str)
    except Exception:
        pass  # Non-critical

    return pdbqt_paths, failures


def rank_docking_results(
    results,
    sort_by: str = "affinity"
) -> List[Dict]:
    """
    Rank and sort docking results.

    Args:
        results: List of DockingResults objects OR List of dicts (from batch_dock)
        sort_by: Sorting criterion ("affinity", "ligand_name")

    Returns:
        Sorted list of result dictionaries with ranking
    """
    ranked = []

    for result in results:
        n = _normalize_result(result)
        poses = n.get('poses', [])
        if poses:
            ranked.append({
                "rank": 0,
                "ligand_name": n.get('ligand_name', ''),
                "best_affinity_kcal_mol": n.get('best_affinity_kcal_mol', 0.0),
                "num_poses": n.get('num_poses', len(poses)),
                "output_file": n.get('output_pdbqt', '')
            })

    # Sort by affinity (most negative = best)
    if sort_by == "affinity":
        ranked.sort(key=lambda x: x["best_affinity_kcal_mol"])
    elif sort_by == "ligand_name":
        ranked.sort(key=lambda x: x["ligand_name"])

    # Assign ranks
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    return ranked


# ============= OUTPUT PARSING =============

def split_pdbqt_models(pdbqt_file: str, output_dir: str = ".") -> List[str]:
    """
    Split multi-model PDBQT file into individual pose files.

    Args:
        pdbqt_file: Path to PDBQT file with multiple models
        output_dir: Directory for output files

    Returns:
        List of output file paths
    """
    output_files = []
    base_name = Path(pdbqt_file).stem.replace("_out", "")

    with open(pdbqt_file, 'r') as f:
        content = f.read()

    models = content.split('MODEL')

    for i, model in enumerate(models[1:], 1):  # Skip first empty split
        output_file = os.path.join(output_dir, f"{base_name}_pose{i}.pdbqt")
        with open(output_file, 'w') as f:
            f.write(f"MODEL{model}")
        output_files.append(output_file)

    logging.info(f"Split {pdbqt_file} into {len(output_files)} poses")
    return output_files


def pdbqt_to_pdb(pdbqt_file: str, output_file: Optional[str] = None) -> str:
    """
    Convert PDBQT file to PDB format.

    Args:
        pdbqt_file: Input PDBQT file
        output_file: Output PDB file (default: same name with .pdb)

    Returns:
        Path to output PDB file
    """
    if output_file is None:
        output_file = Path(pdbqt_file).stem + ".pdb"

    run_command([OBABEL, pdbqt_file, "-O", output_file])
    return output_file


def pdbqt_to_sdf(pdbqt_file: str, output_file: Optional[str] = None) -> str:
    """
    Convert PDBQT file to SDF format.

    Args:
        pdbqt_file: Input PDBQT file
        output_file: Output SDF file

    Returns:
        Path to output SDF file
    """
    if output_file is None:
        output_file = Path(pdbqt_file).stem + ".sdf"

    run_command([OBABEL, pdbqt_file, "-O", output_file])
    return output_file


def extract_pose(
    pdbqt_file: str,
    pose_number: int,
    output_file: Optional[str] = None
) -> str:
    """
    Extract a specific pose from multi-model PDBQT file.

    Args:
        pdbqt_file: Input PDBQT file with multiple models
        pose_number: Pose number to extract (1-based)
        output_file: Output file path

    Returns:
        Path to extracted pose file
    """
    if output_file is None:
        base = Path(pdbqt_file).stem.replace("_out", "")
        output_file = f"{base}_pose{pose_number}.pdbqt"

    with open(pdbqt_file, 'r') as f:
        content = f.read()

    models = content.split('MODEL')

    if pose_number > len(models) - 1:
        raise ValueError(f"Pose {pose_number} not found. File has {len(models)-1} poses.")

    pose_content = f"MODEL{models[pose_number]}"

    with open(output_file, 'w') as f:
        f.write(pose_content)

    return output_file


# ============= ANALYSIS FUNCTIONS =============

def calculate_ligand_efficiency(
    affinity: float,
    num_heavy_atoms: int
) -> float:
    """
    Calculate ligand efficiency (LE = -affinity / num_heavy_atoms).

    Args:
        affinity: Binding affinity in kcal/mol (negative)
        num_heavy_atoms: Number of non-hydrogen atoms

    Returns:
        Ligand efficiency value
    """
    if num_heavy_atoms <= 0:
        return 0.0
    return -affinity / num_heavy_atoms


def count_heavy_atoms(pdbqt_file: str) -> int:
    """
    Count non-hydrogen atoms in PDBQT file.

    Args:
        pdbqt_file: Path to PDBQT file

    Returns:
        Number of heavy atoms
    """
    count = 0
    with open(pdbqt_file, 'r') as f:
        for line in f:
            if line.startswith(('ATOM', 'HETATM')):
                # PDBQT format: element is in columns 77-78
                try:
                    element = line[77:79].strip()
                    if element and element.upper() != 'H':
                        count += 1
                except IndexError:
                    # Fallback: check atom name
                    atom_name = line[12:16].strip()
                    if not atom_name.startswith('H'):
                        count += 1
    return count


def calculate_binding_site_contacts(
    receptor_pdb: str,
    ligand_pdbqt: str,
    distance_cutoff: float = 4.0
) -> Dict[str, List[str]]:
    """
    Identify receptor residues in contact with ligand.

    Args:
        receptor_pdb: Path to receptor PDB file
        ligand_pdbqt: Path to docked ligand PDBQT
        distance_cutoff: Contact distance cutoff in Angstroms

    Returns:
        Dictionary with contact information
    """
    # Read ligand coordinates
    ligand_coords = read_pdbqt_coordinates(ligand_pdbqt)

    # Read receptor and find contacts
    contacts = set()

    with open(receptor_pdb, 'r') as f:
        for line in f:
            if line.startswith('ATOM'):
                try:
                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])

                    for lx, ly, lz in ligand_coords:
                        dist = math.sqrt((x-lx)**2 + (y-ly)**2 + (z-lz)**2)
                        if dist <= distance_cutoff:
                            res_name = line[17:20].strip()
                            res_num = line[22:26].strip()
                            chain = line[21].strip() or 'A'
                            contacts.add(f"{chain}:{res_name}{res_num}")
                            break
                except (ValueError, IndexError):
                    continue

    return {
        "distance_cutoff_angstrom": distance_cutoff,
        "num_contacts": len(contacts),
        "contacting_residues": sorted(list(contacts))
    }


# ============= VISUALIZATION FUNCTIONS =============

def plot_docking_scores(
    results,
    output_file: str = "docking_scores.png",
    title: str = "Docking Results",
    top_n: int = 20
) -> str:
    """
    Create bar plot of docking scores.

    Args:
        results: List of DockingResults objects OR List of dicts (from batch_dock)
        output_file: Output plot file path
        title: Plot title
        top_n: Number of top results to show

    Returns:
        Path to saved plot
    """
    import matplotlib.pyplot as plt

    # Normalize and filter valid results
    normalized = [_normalize_result(r) for r in results]
    valid_results = [n for n in normalized if n.get('poses')]
    valid_results.sort(key=lambda x: x.get('best_affinity_kcal_mol', 0.0))

    # Take top N
    plot_results = valid_results[:top_n]

    names = [r.get('ligand_name', '') for r in plot_results]
    scores = [r.get('best_affinity_kcal_mol', 0.0) for r in plot_results]

    fig, ax = plt.subplots(figsize=(12, max(6, len(names) * 0.3)))

    colors = ['#2ecc71' if s < -8 else '#3498db' if s < -6 else '#f39c12'
              for s in scores]

    bars = ax.barh(range(len(names)), scores, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.set_xlabel('Binding Affinity (kcal/mol)')
    ax.set_title(title)
    ax.invert_yaxis()

    # Add value labels
    for i, (bar, score) in enumerate(zip(bars, scores)):
        ax.text(score - 0.1, i, f'{score:.1f}', va='center', ha='right', fontsize=8)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    logging.info(f"Saved docking scores plot: {output_file}")
    return output_file


def plot_pose_comparison(
    results: DockingResults,
    output_file: str = "pose_comparison.png"
) -> str:
    """
    Create plot comparing poses for a single ligand.

    Args:
        results: DockingResults object
        output_file: Output plot file path

    Returns:
        Path to saved plot
    """
    import matplotlib.pyplot as plt

    poses = results.poses

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Affinity plot
    modes = [p.mode for p in poses]
    affinities = [p.affinity for p in poses]

    ax1.bar(modes, affinities, color='#3498db')
    ax1.set_xlabel('Pose')
    ax1.set_ylabel('Affinity (kcal/mol)')
    ax1.set_title(f'{results.ligand_name} - Binding Affinities')
    ax1.axhline(y=affinities[0], color='r', linestyle='--', alpha=0.5, label='Best pose')
    ax1.legend()

    # RMSD plot
    rmsd_lb = [p.rmsd_lb for p in poses]
    rmsd_ub = [p.rmsd_ub for p in poses]

    x = range(len(modes))
    width = 0.35

    ax2.bar([i - width/2 for i in x], rmsd_lb, width, label='RMSD l.b.', color='#2ecc71')
    ax2.bar([i + width/2 for i in x], rmsd_ub, width, label='RMSD u.b.', color='#e74c3c')
    ax2.set_xlabel('Pose')
    ax2.set_ylabel('RMSD (Å)')
    ax2.set_title(f'{results.ligand_name} - RMSD from Best Pose')
    ax2.set_xticks(x)
    ax2.set_xticklabels(modes)
    ax2.legend()

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    logging.info(f"Saved pose comparison plot: {output_file}")
    return output_file


def create_results_summary_table(
    results,
    output_file: str = "docking_summary.csv"
) -> str:
    """
    Create CSV summary of docking results.

    Args:
        results: List of DockingResults objects OR List of dicts (from batch_dock)
        output_file: Output CSV file path

    Returns:
        Path to saved CSV file
    """
    import csv

    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Rank', 'Ligand', 'Best Affinity (kcal/mol)',
            'Num Poses', 'Output File'
        ])

        ranked = rank_docking_results(results)
        for r in ranked:
            writer.writerow([
                r['rank'],
                r['ligand_name'],
                f"{r['best_affinity_kcal_mol']:.2f}",
                r['num_poses'],
                r['output_file']
            ])

    logging.info(f"Saved results summary: {output_file}")
    return output_file


# ============= UTILITY FUNCTIONS =============

def list_input_files(pattern: str = "*") -> List[str]:
    """List files matching pattern in input directory."""
    files = glob.glob(os.path.join(INPUT_DIR, pattern))
    return [os.path.basename(f) for f in files if os.path.isfile(f)]


def list_work_files(pattern: str = "*") -> List[str]:
    """List files matching pattern in working directory."""
    files = glob.glob(os.path.join(WORK_DIR, pattern))
    return [os.path.basename(f) for f in files if os.path.isfile(f)]


def find_receptor_file() -> Optional[str]:
    """Auto-detect receptor file in input/working directory."""
    patterns = ['*receptor*.pdbqt', '*protein*.pdbqt', '*.pdbqt']

    for pattern in patterns:
        files = glob.glob(pattern)
        if files:
            return files[0]

    # Check for PDB files that might need conversion
    pdb_files = glob.glob('*.pdb')
    if pdb_files:
        return pdb_files[0]

    return None


def find_ligand_files() -> List[str]:
    """Auto-detect ligand files in input/working directory."""
    ligand_patterns = ['*ligand*.pdbqt', '*ligand*.sdf', '*ligand*.mol2']

    files = []
    for pattern in ligand_patterns:
        files.extend(glob.glob(pattern))

    # If no explicit ligand files, look for small molecule files
    if not files:
        for ext in ['*.sdf', '*.mol2', '*.mol']:
            files.extend(glob.glob(ext))

    return list(set(files))


def validate_pdbqt(pdbqt_file: str) -> Dict[str, Any]:
    """
    Validate PDBQT file format.

    Args:
        pdbqt_file: Path to PDBQT file

    Returns:
        Dictionary with validation results
    """
    issues = []
    atom_count = 0
    has_charges = False
    has_atom_types = False

    with open(pdbqt_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            if line.startswith(('ATOM', 'HETATM')):
                atom_count += 1

                # Check line length
                if len(line) < 78:
                    issues.append(f"Line {line_num}: Too short ({len(line)} chars)")
                else:
                    # Check charge field
                    try:
                        charge = float(line[70:76])
                        has_charges = True
                    except ValueError:
                        issues.append(f"Line {line_num}: Invalid charge field")

                    # Check atom type
                    atom_type = line[77:79].strip()
                    if atom_type:
                        has_atom_types = True

    return {
        "valid": len(issues) == 0 and has_charges and has_atom_types,
        "atom_count": atom_count,
        "has_charges": has_charges,
        "has_atom_types": has_atom_types,
        "issues": issues
    }
