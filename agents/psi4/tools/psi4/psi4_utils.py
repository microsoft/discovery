#!/usr/bin/env python3
"""
Psi4 Utilities Library for Discovery Platform

Helper functions for running Psi4 quantum chemistry calculations and analyzing output.
This module is pre-installed in the Psi4 container for use by generated scripts.

Psi4 is a comprehensive ab initio quantum chemistry package supporting:
- Hartree-Fock (HF) and post-HF methods (MP2, CCSD, CCSD(T))
- Density Functional Theory (DFT) with many functionals
- Symmetry-Adapted Perturbation Theory (SAPT)
- Excited states (EOM-CCSD, TD-DFT/TDA)
- Geometry optimization and frequency calculations
- Thermochemistry analysis

Usage:
    from psi4_utils import (
        quick_setup, quick_finish, save_final_results,
        run_psi4, run_psi4_script, parse_psi4_output,
        optimize_geometry, compute_frequencies, compute_energy,
        compute_homo_lumo_gap, compute_fundamental_gap,
        compute_thermochemistry, compute_sapt, compute_excited_states
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
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

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

# Psi4 specific directories
PSI4_SCRATCH = os.environ.get('PSI_SCRATCH', '/tmp/psi4_scratch')

# Physical constants
HARTREE_TO_EV = 27.211386245988
HARTREE_TO_KCAL = 627.5094740631
HARTREE_TO_KJ = 2625.4996394799
BOHR_TO_ANGSTROM = 0.529177210903
ANGSTROM_TO_BOHR = 1.8897259886

# Common basis sets
COMMON_BASIS_SETS = [
    'sto-3g', '3-21g', '6-31g', '6-31g*', '6-31g**', '6-31+g*', '6-31++g**',
    '6-311g', '6-311g*', '6-311g**', '6-311+g*', '6-311++g**',
    'cc-pvdz', 'cc-pvtz', 'cc-pvqz', 'cc-pv5z',
    'aug-cc-pvdz', 'aug-cc-pvtz', 'aug-cc-pvqz',
    'def2-svp', 'def2-tzvp', 'def2-tzvpp', 'def2-qzvp',
]

# Common DFT functionals
COMMON_FUNCTIONALS = [
    'b3lyp', 'b3lyp-d3bj', 'pbe', 'pbe0', 'pbe0-d3bj',
    'm06-2x', 'wb97x-d', 'wb97m-v', 'cam-b3lyp',
    'bp86', 'tpss', 'revpbe', 'b97-d3'
]


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
    os.makedirs(PSI4_SCRATCH, exist_ok=True)
    os.chdir(WORK_DIR)
    logging.info(f"Input directory: {INPUT_DIR}")
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Output directory: {OUTPUT_DIR}")
    logging.info(f"Detected {NUM_CORES} CPU cores available")
    logging.info(f"Psi4 scratch directory: {PSI4_SCRATCH}")
    if copy_input and work_dir is not None:
        copy_input_files()


def copy_input_files(patterns: List[str] = None) -> List[str]:
    """Copy input files from input directory to working directory.

    Args:
        patterns: List of glob patterns to copy. Defaults to common chemistry patterns.

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if patterns is None:
        patterns = ['*.xyz', '*.pdb', '*.mol', '*.mol2', '*.sdf', '*.cif',
                    '*.in', '*.dat', '*.py', '*.json', '*.csv', 'POSCAR']

    copied = []
    for pattern in patterns:
        for src_file in glob.glob(os.path.join(INPUT_DIR, pattern)):
            dst_file = os.path.join(WORK_DIR, os.path.basename(src_file))
            shutil.copy(src_file, dst_file)
            logging.info(f"Copied: {os.path.basename(src_file)}")
            copied.append(dst_file)
    return copied


def copy_outputs(patterns: List[str] = None) -> List[str]:
    """Copy output files to output directory.

    Args:
        patterns: List of glob patterns to copy. Defaults to common output patterns.

    Returns:
        List of copied file paths.
    """
    _require_dirs()
    if patterns is None:
        patterns = ['*.out', '*.log', '*.dat', '*.csv', '*.png', '*.json',
                    '*.xyz', '*.molden', '*.fchk', '*.cube', '*.wfn']

    copied = []
    for pattern in patterns:
        for src_file in glob.glob(os.path.join(WORK_DIR, pattern)):
            dst_file = os.path.join(OUTPUT_DIR, os.path.basename(src_file))
            shutil.copy(src_file, dst_file)
            logging.info(f"Output: {os.path.basename(src_file)}")
            copied.append(dst_file)
    return copied


# ============= COMMAND EXECUTION =============

def run_command(command: str, cwd: str = None, stream: bool = True,
                timeout: int = None) -> subprocess.CompletedProcess:
    """Execute command with real-time output streaming.

    Args:
        command: Shell command to execute
        cwd: Working directory (optional)
        stream: If True, stream output line-by-line; if False, capture all at once
        timeout: Command timeout in seconds (optional)

    Returns:
        subprocess.CompletedProcess result
    """
    logging.info(f"Running: {command}")
    start_time = time.time()

    if not stream:
        result = subprocess.run(
            command, shell=True, check=True,
            capture_output=True, text=True, cwd=cwd, timeout=timeout
        )
        elapsed = time.time() - start_time
        logging.info(f"Completed in {elapsed:.2f}s")
        if result.stdout:
            logging.info(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        return result

    # Streaming mode
    process = subprocess.Popen(
        command, shell=True, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )

    output_lines = []
    try:
        for line in process.stdout:
            line = line.rstrip('\n')
            print(line)
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


def run_psi4(input_file: str, output_file: str = None, nthreads: int = None,
             memory: str = None) -> str:
    """Run Psi4 calculation from input file.

    Args:
        input_file: Path to Psi4 input file (.dat or .in)
        output_file: Path to output file (default: input_file.out)
        nthreads: Number of OpenMP threads (default: auto-detect)
        memory: Memory allocation (e.g., '4 GB', default: auto)

    Returns:
        Path to output file
    """
    if output_file is None:
        base = os.path.splitext(input_file)[0]
        output_file = f"{base}.out"

    if nthreads is None:
        nthreads = min(NUM_CORES, 16)

    cmd = f"psi4 -n {nthreads}"
    if memory:
        cmd += f" -m '{memory}'"
    cmd += f" -i {input_file} -o {output_file}"

    logging.info(f"Running Psi4 with {nthreads} threads")
    run_command(cmd)

    return output_file


def run_psi4_script(script_content: str, output_file: str = "psi4_calc.out",
                    nthreads: int = None, memory: str = None) -> str:
    """Run Psi4 calculation from script content string.

    Args:
        script_content: Psi4 input script as string
        output_file: Path to output file
        nthreads: Number of OpenMP threads
        memory: Memory allocation

    Returns:
        Path to output file
    """
    input_file = "psi4_input.dat"
    with open(input_file, 'w') as f:
        f.write(script_content)

    return run_psi4(input_file, output_file, nthreads, memory)


# ============= PSI4 PYTHON API HELPERS =============

def setup_psi4(memory: str = '4 GB', nthreads: int = None, output_file: str = None):
    """Initialize Psi4 module with common settings.

    Args:
        memory: Memory to use (e.g., '4 GB', '8 GB')
        nthreads: Number of OpenMP threads
        output_file: Output file for Psi4 (None = stdout)

    Returns:
        psi4 module reference
    """
    import psi4

    psi4.set_memory(memory)

    if nthreads is None:
        nthreads = min(NUM_CORES, 16)
    psi4.set_num_threads(nthreads)

    if output_file:
        psi4.core.set_output_file(output_file, False)

    psi4.set_options({
        'scf_type': 'df',  # Density fitting for efficiency
        'reference': 'rhf',  # Closed-shell reference
    })

    logging.info(f"Psi4 initialized: {memory} memory, {nthreads} threads")
    return psi4


def create_molecule(geometry: str, charge: int = 0, multiplicity: int = 1,
                    units: str = 'angstrom', symmetry: str = None) -> 'psi4.core.Molecule':
    """Create a Psi4 molecule from geometry string.

    Args:
        geometry: Molecular geometry (XYZ format or Z-matrix)
        charge: Molecular charge
        multiplicity: Spin multiplicity (1=singlet, 2=doublet, etc.)
        units: 'angstrom' or 'bohr'
        symmetry: Point group symmetry (e.g., 'c2v', None=auto)

    Returns:
        Psi4 Molecule object

    Example:
        >>> mol = create_molecule('''
        ...     O   0.000  0.000  0.117
        ...     H  -0.756  0.000 -0.470
        ...     H   0.756  0.000 -0.470
        ... ''')
    """
    import psi4

    mol_string = f"{charge} {multiplicity}\n{geometry}"

    if symmetry:
        mol_string += f"\nsymmetry {symmetry}"
    if units == 'bohr':
        mol_string += "\nunits bohr"

    mol = psi4.geometry(mol_string)
    logging.info(f"Created molecule: {mol.natom()} atoms, charge={charge}, mult={multiplicity}")

    return mol


def create_dimer_molecule(geometry1: str, geometry2: str,
                          charge1: int = 0, multiplicity1: int = 1,
                          charge2: int = 0, multiplicity2: int = 1,
                          units: str = 'angstrom') -> 'psi4.core.Molecule':
    """Create a Psi4 molecule with two fragments for SAPT or counterpoise calculations.

    SAPT and counterpoise (CP) corrections require the molecule to have exactly
    two fragments separated by '--'. This function builds the correct Psi4
    molecule specification from two separate geometry strings.

    Args:
        geometry1: XYZ geometry of fragment 1 (e.g., first water molecule)
        geometry2: XYZ geometry of fragment 2 (e.g., second water molecule)
        charge1: Charge of fragment 1
        multiplicity1: Spin multiplicity of fragment 1
        charge2: Charge of fragment 2
        multiplicity2: Spin multiplicity of fragment 2
        units: 'angstrom' or 'bohr'

    Returns:
        Psi4 Molecule object with two fragments

    Example:
        >>> water1 = '''
        ...     O  -1.551  0.114  0.000
        ...     H  -1.934  0.762  0.673
        ...     H  -0.599  0.040  0.000
        ... '''
        >>> water2 = '''
        ...     O   1.350  0.111  0.000
        ...     H   1.680 -0.520  0.673
        ...     H   1.680 -0.520 -0.673
        ... '''
        >>> dimer = create_dimer_molecule(water1, water2)
        >>> sapt_result = compute_sapt(dimer, method='sapt0')
    """
    import psi4

    mol_string = f"{charge1} {multiplicity1}\n{geometry1.strip()}\n--\n{charge2} {multiplicity2}\n{geometry2.strip()}"

    if units == 'bohr':
        mol_string += "\nunits bohr"

    mol = psi4.geometry(mol_string)

    n1 = len([l for l in geometry1.strip().splitlines() if l.strip()])
    n2 = len([l for l in geometry2.strip().splitlines() if l.strip()])
    logging.info(f"Created dimer molecule: {mol.natom()} atoms ({n1} + {n2}), "
                 f"fragment 1: charge={charge1} mult={multiplicity1}, "
                 f"fragment 2: charge={charge2} mult={multiplicity2}")

    return mol


def split_xyz_into_fragments(geometry: str, n_atoms_frag1: int) -> tuple:
    """Split a geometry string into two fragments by atom count.

    Useful for SAPT calculations when reading from an XYZ file that contains
    a dimer but without fragment markers. The caller must know how many atoms
    belong to the first fragment.

    Args:
        geometry: Full XYZ geometry string (atom lines only, no header)
        n_atoms_frag1: Number of atoms in the first fragment

    Returns:
        Tuple of (fragment1_geometry, fragment2_geometry) as strings

    Example:
        >>> geom = read_xyz_file('water_dimer.xyz')  # 6 atoms total
        >>> frag1, frag2 = split_xyz_into_fragments(geom, 3)  # 3 atoms per water
        >>> dimer = create_dimer_molecule(frag1, frag2)
    """
    lines = [l for l in geometry.strip().splitlines() if l.strip()]
    if n_atoms_frag1 >= len(lines):
        raise ValueError(f"n_atoms_frag1={n_atoms_frag1} >= total atoms={len(lines)}")

    frag1 = '\n'.join(lines[:n_atoms_frag1])
    frag2 = '\n'.join(lines[n_atoms_frag1:])

    logging.info(f"Split geometry into fragments: {n_atoms_frag1} + {len(lines) - n_atoms_frag1} atoms")
    return frag1, frag2


def read_xyz_file(filename: str) -> str:
    """Read XYZ file and return geometry string for Psi4.

    Args:
        filename: Path to XYZ file

    Returns:
        Geometry string suitable for create_molecule()
    """
    with open(filename, 'r') as f:
        lines = f.readlines()

    # Skip first two lines (atom count and comment)
    geometry_lines = [l.strip() for l in lines[2:] if l.strip()]
    return '\n'.join(geometry_lines)


def write_xyz_file(molecule, filename: str, comment: str = ""):
    """Write molecule geometry to XYZ file.

    Args:
        molecule: Psi4 Molecule object, or XYZ geometry string
                  (e.g. opt_result['molecule'] or opt_result['optimized_geometry'])
        filename: Output XYZ file path
        comment: Comment line for XYZ file
    """
    if isinstance(molecule, str):
        # Handle XYZ geometry string (e.g. from opt_result['optimized_geometry'])
        lines = [l for l in molecule.strip().splitlines() if l.strip()]
        natom = len(lines)
        with open(filename, 'w') as f:
            f.write(f"{natom}\n")
            f.write(f"{comment}\n")
            for line in lines:
                f.write(f"{line}\n")
    elif hasattr(molecule, 'save_xyz_file'):
        molecule.save_xyz_file(filename, False)
    else:
        # Manual writing from Psi4 Molecule object
        natom = molecule.natom()
        with open(filename, 'w') as f:
            f.write(f"{natom}\n")
            f.write(f"{comment}\n")
            for i in range(natom):
                symbol = molecule.symbol(i)
                x = molecule.x(i) * BOHR_TO_ANGSTROM
                y = molecule.y(i) * BOHR_TO_ANGSTROM
                z = molecule.z(i) * BOHR_TO_ANGSTROM
                f.write(f"{symbol:2s} {x:15.10f} {y:15.10f} {z:15.10f}\n")

    logging.info(f"Wrote XYZ file: {filename}")


# ============= ENERGY CALCULATIONS =============

def compute_energy(molecule, method: str = 'hf', basis: str = 'cc-pvdz',
                   return_wfn: bool = False, **kwargs) -> Dict:
    """Compute single-point energy.

    Args:
        molecule: Psi4 Molecule object
        method: Quantum chemistry method (hf, mp2, ccsd, ccsd(t), b3lyp, etc.)
        basis: Basis set
        return_wfn: Also return wavefunction object
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - energy_hartree: Total energy in Hartree
            - energy_eV: Energy in eV
            - energy_kcal: Energy in kcal/mol
            - method: Method used
            - basis: Basis set used
            - wfn: Wavefunction (if return_wfn=True)

    Example:
        >>> result = compute_energy(mol, method='b3lyp', basis='def2-tzvp')
        >>> print(f"Energy: {result['energy_hartree']:.10f} Hartree")
    """
    import psi4

    psi4.set_options({'basis': basis, **kwargs})

    logging.info(f"Computing {method.upper()}/{basis} energy...")

    if return_wfn:
        energy, wfn = psi4.energy(method, molecule=molecule, return_wfn=True)
    else:
        energy = psi4.energy(method, molecule=molecule)
        wfn = None

    result = {
        'energy_hartree': energy,
        'energy_eV': energy * HARTREE_TO_EV,
        'energy_kcal': energy * HARTREE_TO_KCAL,
        'method': method.upper(),
        'basis': basis,
    }

    if return_wfn:
        result['wfn'] = wfn

    logging.info(f"Energy: {energy:.10f} Hartree ({energy * HARTREE_TO_EV:.6f} eV)")
    return result


def _extract_orbital_energies(wfn) -> Tuple[np.ndarray, np.ndarray]:
    """Extract sorted occupied and virtual orbital energies from a Psi4 wavefunction.

    Handles both single-irrep (C1) and multi-irrep (e.g., D2h) wavefunctions.
    Psi4 stores orbital energies blocked by irreducible representation;
    np.array(wfn.epsilon_a()) fails when nirrep > 1.

    Args:
        wfn: Psi4 wavefunction object

    Returns:
        Tuple of (occupied_energies, virtual_energies) as sorted numpy arrays in Hartree
    """
    nirrep = wfn.nirrep()

    if nirrep == 1:
        eps_a = np.array(wfn.epsilon_a())
        nocc = wfn.nalpha()
        return eps_a[:nocc], eps_a[nocc:]

    # Multi-irrep: collect from each irrep, tag as occupied/virtual, then sort
    occ_list = []
    virt_list = []
    for h in range(nirrep):
        eps_h = wfn.epsilon_a().nph[h]
        nocc_h = wfn.doccpi()[h] + wfn.soccpi()[h]
        for i, e in enumerate(eps_h):
            if i < nocc_h:
                occ_list.append(float(e))
            else:
                virt_list.append(float(e))

    occ_energies = np.sort(np.array(occ_list))
    virt_energies = np.sort(np.array(virt_list))
    return occ_energies, virt_energies


def compute_homo_lumo_gap(molecule, method: str = 'b3lyp', basis: str = 'def2-tzvp',
                          **kwargs) -> Dict:
    """Compute Kohn-Sham HOMO-LUMO gap and orbital energies.

    Runs a single-point energy calculation with return_wfn=True and extracts
    orbital energies from the wavefunction to determine HOMO, LUMO, and gap.

    IMPORTANT LIMITATIONS:
    The Kohn-Sham (KS) HOMO-LUMO gap from standard DFT is NOT the same as:
      - The fundamental gap (IP - EA): use ΔSCF (separate neutral/cation/anion calculations)
      - The optical gap (lowest excitation energy): use TD-DFT via compute_excited_states()
    KS-DFT with standard functionals (B3LYP, PBE) systematically underestimates the gap.
    Range-separated hybrids (CAM-B3LYP, wB97X-D) give somewhat better orbital gaps.

    For more rigorous gap estimates:
      - Fundamental gap: compute_fundamental_gap() (ΔSCF approach: IP - EA)
      - Optical gap: compute_excited_states(mol, method='tddft') for S0→S1 energy
      - Quasiparticle gap: GW methods (not available in Psi4)

    Args:
        molecule: Psi4 Molecule object
        method: Quantum chemistry method (range-separated hybrids like 'cam-b3lyp'
                or 'wb97x-d' give more reliable orbital gaps than standard functionals)
        basis: Basis set
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - homo_energy_hartree/eV: HOMO orbital energy
            - lumo_energy_hartree/eV: LUMO orbital energy
            - gap_hartree/eV: KS HOMO-LUMO gap
            - total_energy_hartree/eV: Total electronic energy
            - method, basis: Method and basis set used
            - n_occupied, n_virtual: Number of occupied/virtual orbitals
            - caveat: Explanation of KS gap limitations
            - recommendations: Suggestions for more accurate gap calculations

    Example:
        >>> mol = create_molecule('C 0 0 0\\nO 0 0 1.2\\nH 0.9 0 -0.6\\nH -0.9 0 -0.6')
        >>> gap = compute_homo_lumo_gap(mol, method='b3lyp', basis='def2-tzvp')
        >>> print(f"HOMO-LUMO gap: {gap['gap_eV']:.2f} eV")
        >>> print(gap['caveat'])  # Always report limitations
    """
    import psi4

    psi4.set_options({'basis': basis, **kwargs})

    logging.info(f"Computing {method.upper()}/{basis} HOMO-LUMO gap...")

    energy, wfn = psi4.energy(method, molecule=molecule, return_wfn=True)

    # Extract orbital energies (handles multi-irrep wavefunctions like D2h benzene)
    occ_energies, virt_energies = _extract_orbital_energies(wfn)
    nocc = len(occ_energies)
    nvirt = len(virt_energies)

    homo_energy = float(occ_energies[-1])
    lumo_energy = float(virt_energies[0])
    gap = lumo_energy - homo_energy

    # Determine if method is a range-separated hybrid (more reliable for gaps)
    rs_hybrids = {'cam-b3lyp', 'wb97x-d', 'wb97x', 'wb97m-v', 'lc-blyp', 'lc-wpbe'}
    is_range_separated = method.lower() in rs_hybrids

    caveat = (
        f"This is a Kohn-Sham orbital energy gap from {method.upper()}/{basis}, "
        f"which is NOT the fundamental gap (IP - EA) or the optical gap (S0->S1 excitation). "
        f"KS-DFT with {'range-separated hybrids provides a better approximation to the fundamental gap' if is_range_separated else 'standard functionals systematically underestimates the true gap'}. "
        f"For quantitative accuracy, use ΔSCF for the fundamental gap or TD-DFT for the optical gap."
    )

    recommendations = []
    if not is_range_separated:
        recommendations.append(
            "Consider using a range-separated hybrid (CAM-B3LYP, wB97X-D) for more "
            "reliable orbital gap values."
        )
    recommendations.append(
        "For the fundamental gap (IP - EA), use compute_fundamental_gap() which performs "
        "ΔSCF calculations (separate neutral, cation, and anion energies)."
    )
    recommendations.append(
        "For the optical gap, use compute_excited_states(mol, method='tddft') to get "
        "the S0 -> S1 excitation energy."
    )

    result = {
        'homo_energy_hartree': homo_energy,
        'homo_energy_eV': homo_energy * HARTREE_TO_EV,
        'lumo_energy_hartree': lumo_energy,
        'lumo_energy_eV': lumo_energy * HARTREE_TO_EV,
        'gap_hartree': gap,
        'gap_eV': gap * HARTREE_TO_EV,
        'total_energy_hartree': energy,
        'total_energy_eV': energy * HARTREE_TO_EV,
        'method': method.upper(),
        'basis': basis,
        'n_occupied': nocc,
        'n_virtual': nvirt,
        'caveat': caveat,
        'recommendations': recommendations,
    }

    logging.info(f"HOMO: {homo_energy:.6f} Hartree ({homo_energy * HARTREE_TO_EV:.4f} eV)")
    logging.info(f"LUMO: {lumo_energy:.6f} Hartree ({lumo_energy * HARTREE_TO_EV:.4f} eV)")
    logging.info(f"HOMO-LUMO gap: {gap:.6f} Hartree ({gap * HARTREE_TO_EV:.4f} eV)")
    logging.info(f"NOTE: {caveat}")

    return result


def compute_fundamental_gap(molecule, method: str = 'b3lyp', basis: str = 'def2-tzvp',
                             **kwargs) -> Dict:
    """Compute the fundamental gap (IP - EA) using the ΔSCF method.

    The fundamental gap is the difference between the ionization potential (IP)
    and electron affinity (EA), computed from total energy differences:
      IP = E(cation) - E(neutral)
      EA = E(neutral) - E(anion)
      Fundamental gap = IP - EA

    This is more physically meaningful and accurate than the KS HOMO-LUMO gap.

    Args:
        molecule: Psi4 Molecule object (neutral species)
        method: Quantum chemistry method
        basis: Basis set
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - ip_eV: Ionization potential in eV
            - ea_eV: Electron affinity in eV
            - fundamental_gap_eV: Fundamental gap (IP - EA) in eV
            - ip_hartree, ea_hartree, fundamental_gap_hartree: Same in Hartree
            - neutral_energy, cation_energy, anion_energy: Total energies
            - method, basis: Method and basis set used

    Example:
        >>> mol = create_molecule('''
        ...     C  0.000  0.000  0.000
        ...     C  1.395  0.000  0.000
        ...     C  2.093  1.209  0.000
        ...     C  1.395  2.418  0.000
        ...     C  0.000  2.418  0.000
        ...     C -0.698  1.209  0.000
        ...     H -0.540 -0.944  0.000
        ...     H  1.935 -0.944  0.000
        ...     H  3.173  1.209  0.000
        ...     H  1.935  3.362  0.000
        ...     H -0.540  3.362  0.000
        ...     H -1.778  1.209  0.000
        ... ''')
        >>> gap = compute_fundamental_gap(mol, method='b3lyp', basis='def2-tzvp')
        >>> print(f"IP = {gap['ip_eV']:.2f} eV, EA = {gap['ea_eV']:.2f} eV")
        >>> print(f"Fundamental gap = {gap['fundamental_gap_eV']:.2f} eV")
    """
    import psi4

    # Get charge and multiplicity of neutral species
    charge = molecule.molecular_charge()
    mult = molecule.multiplicity()

    logging.info(f"Computing ΔSCF fundamental gap with {method.upper()}/{basis}...")
    logging.info(f"Neutral: charge={charge}, mult={mult}")

    # 1. Neutral species energy
    psi4.set_options({'basis': basis, 'reference': 'rhf' if mult == 1 else 'uhf', **kwargs})
    E_neutral = psi4.energy(method, molecule=molecule)
    logging.info(f"E(neutral) = {E_neutral:.10f} Hartree")

    # 2. Cation energy (remove one electron)
    cation_charge = charge + 1
    cation_mult = mult + 1 if mult == 1 else mult - 1  # doublet from singlet, or vice versa
    # Rebuild geometry string for cation
    geom_str = ""
    for i in range(molecule.natom()):
        sym = molecule.symbol(i)
        x = molecule.x(i) * BOHR_TO_ANGSTROM
        y = molecule.y(i) * BOHR_TO_ANGSTROM
        z = molecule.z(i) * BOHR_TO_ANGSTROM
        geom_str += f"{sym} {x:.10f} {y:.10f} {z:.10f}\n"

    cation_mol = psi4.geometry(f"{cation_charge} {cation_mult}\n{geom_str}")
    psi4.set_options({'basis': basis, 'reference': 'uhf', **kwargs})
    E_cation = psi4.energy(method, molecule=cation_mol)
    logging.info(f"E(cation, charge={cation_charge}, mult={cation_mult}) = {E_cation:.10f} Hartree")

    # 3. Anion energy (add one electron)
    anion_charge = charge - 1
    anion_mult = mult + 1 if mult == 1 else mult - 1
    anion_mol = psi4.geometry(f"{anion_charge} {anion_mult}\n{geom_str}")
    psi4.set_options({'basis': basis, 'reference': 'uhf', **kwargs})
    E_anion = psi4.energy(method, molecule=anion_mol)
    logging.info(f"E(anion, charge={anion_charge}, mult={anion_mult}) = {E_anion:.10f} Hartree")

    # Compute IP and EA
    ip = E_cation - E_neutral  # Positive value = energy cost to remove electron
    ea = E_neutral - E_anion    # Positive value = energy gained by adding electron
    fundamental_gap = ip - ea

    result = {
        'ip_hartree': ip,
        'ip_eV': ip * HARTREE_TO_EV,
        'ea_hartree': ea,
        'ea_eV': ea * HARTREE_TO_EV,
        'fundamental_gap_hartree': fundamental_gap,
        'fundamental_gap_eV': fundamental_gap * HARTREE_TO_EV,
        'neutral_energy_hartree': E_neutral,
        'cation_energy_hartree': E_cation,
        'anion_energy_hartree': E_anion,
        'method': method.upper(),
        'basis': basis,
    }

    logging.info(f"IP = {ip * HARTREE_TO_EV:.4f} eV")
    logging.info(f"EA = {ea * HARTREE_TO_EV:.4f} eV")
    logging.info(f"Fundamental gap (IP - EA) = {fundamental_gap * HARTREE_TO_EV:.4f} eV")

    return result


def compute_gradient(molecule, method: str = 'hf', basis: str = 'cc-pvdz',
                     return_wfn: bool = False) -> Dict:
    """Compute energy gradient (forces).

    Args:
        molecule: Psi4 Molecule object
        method: Quantum chemistry method
        basis: Basis set
        return_wfn: Also return wavefunction

    Returns:
        dict with:
            - gradient: Gradient matrix (natom x 3) in Hartree/Bohr
            - gradient_eV_angstrom: Gradient in eV/Angstrom
            - energy_hartree: Energy
            - max_force: Maximum force component
            - rms_force: RMS force
    """
    import psi4

    psi4.set_options({'basis': basis})

    logging.info(f"Computing {method.upper()}/{basis} gradient...")

    if return_wfn:
        grad, wfn = psi4.gradient(method, molecule=molecule, return_wfn=True)
        energy = wfn.energy()
    else:
        grad = psi4.gradient(method, molecule=molecule)
        energy = psi4.core.variable('CURRENT ENERGY')
        wfn = None

    grad_np = np.array(grad)

    # Convert to eV/Angstrom
    grad_eV_ang = grad_np * HARTREE_TO_EV / BOHR_TO_ANGSTROM

    result = {
        'gradient': grad_np,
        'gradient_eV_angstrom': grad_eV_ang,
        'energy_hartree': energy,
        'max_force': np.max(np.abs(grad_np)),
        'rms_force': np.sqrt(np.mean(grad_np**2)),
    }

    if return_wfn:
        result['wfn'] = wfn

    logging.info(f"Max force: {result['max_force']:.6f} Hartree/Bohr")
    return result


# ============= GEOMETRY OPTIMIZATION =============

def optimize_geometry(molecule, method: str = 'hf', basis: str = 'cc-pvdz',
                      geom_maxiter: int = 100, full_hess_every: int = -1,
                      **kwargs) -> Dict:
    """Optimize molecular geometry.

    Args:
        molecule: Psi4 Molecule object
        method: Quantum chemistry method
        basis: Basis set
        geom_maxiter: Maximum optimization steps
        full_hess_every: Compute full Hessian every N steps (-1 = never)
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - optimized_energy_hartree: Final energy
            - initial_energy_hartree: Starting energy
            - converged: Whether optimization converged
            - n_iterations: Number of optimization steps
            - optimized_geometry: Final XYZ coordinates as string
            - molecule: Optimized Psi4 molecule object
    """
    import psi4

    psi4.set_options({
        'basis': basis,
        'geom_maxiter': geom_maxiter,
        'full_hess_every': full_hess_every,
        **kwargs
    })

    logging.info(f"Optimizing geometry with {method.upper()}/{basis}...")
    logging.info(f"Max iterations: {geom_maxiter}")

    # Get initial energy
    initial_energy = psi4.energy(method, molecule=molecule)

    # Run optimization
    try:
        opt_energy, opt_wfn = psi4.optimize(method, molecule=molecule, return_wfn=True)
        converged = True
    except psi4.OptimizationConvergenceError as e:
        logging.warning(f"Optimization did not converge: {e}")
        opt_energy = psi4.core.variable('CURRENT ENERGY')
        converged = False
        opt_wfn = None

    # Get optimized geometry
    opt_mol = molecule  # Psi4 modifies molecule in place
    geometry_str = ""
    for i in range(opt_mol.natom()):
        symbol = opt_mol.symbol(i)
        x = opt_mol.x(i) * BOHR_TO_ANGSTROM
        y = opt_mol.y(i) * BOHR_TO_ANGSTROM
        z = opt_mol.z(i) * BOHR_TO_ANGSTROM
        geometry_str += f"{symbol:2s} {x:15.10f} {y:15.10f} {z:15.10f}\n"

    result = {
        'optimized_energy_hartree': opt_energy,
        'optimized_energy_eV': opt_energy * HARTREE_TO_EV,
        'initial_energy_hartree': initial_energy,
        'energy_change_kcal': (opt_energy - initial_energy) * HARTREE_TO_KCAL,
        'converged': converged,
        'optimized_geometry': geometry_str.strip(),
        'molecule': opt_mol,
    }

    logging.info(f"Optimization {'converged' if converged else 'did not converge'}")
    logging.info(f"Final energy: {opt_energy:.10f} Hartree")
    logging.info(f"Energy change: {result['energy_change_kcal']:.4f} kcal/mol")

    return result


# ============= FREQUENCY CALCULATIONS =============

def compute_frequencies(molecule, method: str = 'hf', basis: str = 'cc-pvdz',
                        dertype: str = 'gradient', **kwargs) -> Dict:
    """Compute vibrational frequencies.

    Args:
        molecule: Psi4 Molecule object (should be optimized geometry)
        method: Quantum chemistry method
        basis: Basis set
        dertype: Derivative type for Hessian computation:
            - 'gradient': Numerical Hessian from analytical gradients (default,
              works for all methods including DFT). Slower but universally compatible.
            - 'hessian': Analytical Hessian (only available for HF and a few other
              methods; will fail for DFT methods like B3LYP).
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - frequencies_cm: Vibrational frequencies in cm^-1
            - frequencies_thz: Frequencies in THz
            - intensities: IR intensities (km/mol)
            - n_imaginary: Number of imaginary frequencies
            - zpve_hartree: Zero-point vibrational energy
            - zpve_kcal: ZPVE in kcal/mol
            - is_minimum: True if no imaginary frequencies
    """
    import psi4

    # Guard: molecule must be a Psi4 Molecule object, not a string.
    # Common mistake: passing opt_result['optimized_geometry'] (string) instead
    # of opt_result['molecule'] (Psi4 Molecule object) from optimize_geometry().
    if isinstance(molecule, str):
        raise TypeError(
            "molecule must be a Psi4 Molecule object, not a string. "
            "If using optimize_geometry(), pass opt_result['molecule'] "
            "(not opt_result['optimized_geometry'])."
        )

    psi4.set_options({'basis': basis, **kwargs})

    logging.info(f"Computing {method.upper()}/{basis} frequencies (dertype={dertype})...")

    # Run frequency calculation
    # Default dertype='gradient' computes Hessian numerically from analytical
    # gradients, which works for all methods. Use dertype='hessian' only for
    # methods with analytical second derivatives (e.g. HF).
    energy, wfn = psi4.frequency(method, molecule=molecule, return_wfn=True,
                                  dertype=dertype)

    # Extract frequencies
    freqs = np.array(wfn.frequencies())

    # Get IR intensities if available
    try:
        intensities = np.array(wfn.ir_intensities())
    except:
        intensities = np.zeros_like(freqs)

    # Count imaginary frequencies (negative values)
    n_imaginary = np.sum(freqs < 0)

    # Get ZPVE
    zpve = psi4.core.variable('ZPVE')

    result = {
        'frequencies_cm': freqs.tolist(),
        'frequencies_thz': (freqs * 0.02998).tolist(),  # cm^-1 to THz
        'intensities_km_mol': intensities.tolist(),
        'n_imaginary': int(n_imaginary),
        'zpve_hartree': zpve,
        'zpve_kcal': zpve * HARTREE_TO_KCAL,
        'zpve_kJ': zpve * HARTREE_TO_KJ,
        'is_minimum': n_imaginary == 0,
        'energy_hartree': energy,
    }

    logging.info(f"Found {len(freqs)} vibrational modes")
    logging.info(f"Imaginary frequencies: {n_imaginary}")
    logging.info(f"ZPVE: {zpve * HARTREE_TO_KCAL:.4f} kcal/mol")

    if n_imaginary > 0:
        logging.warning(f"Structure has {n_imaginary} imaginary frequency(ies) - may be a transition state")

    return result


# ============= THERMOCHEMISTRY =============

def compute_thermochemistry(molecule, method: str = 'hf', basis: str = 'cc-pvdz',
                            temperature: float = 298.15, pressure: float = 1.0,
                            dertype: str = 'gradient', **kwargs) -> Dict:
    """Compute thermochemistry (enthalpy, entropy, Gibbs free energy).

    Args:
        molecule: Psi4 Molecule object (should be optimized)
        method: Quantum chemistry method
        basis: Basis set
        temperature: Temperature in Kelvin
        pressure: Pressure in atm
        dertype: Derivative type ('gradient' for numerical Hessian, 'hessian' for
                 analytical - only HF supports analytical Hessian)
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - electronic_energy: E0 (Hartree)
            - zpve: Zero-point vibrational energy (Hartree)
            - enthalpy: H (Hartree)
            - entropy: S (Hartree/K)
            - gibbs_free_energy: G (Hartree)
            - thermal_correction_H: Thermal correction to enthalpy
            - thermal_correction_G: Thermal correction to Gibbs energy
            - All values also provided in kcal/mol and kJ/mol
    """
    import psi4

    psi4.set_options({
        'basis': basis,
        'T': temperature,
        'P': pressure * 101325,  # atm to Pa
        **kwargs
    })

    logging.info(f"Computing thermochemistry at {temperature} K, {pressure} atm...")

    # Run frequency calculation to get thermodynamic properties
    # dertype='gradient' ensures compatibility with DFT methods
    energy, wfn = psi4.frequency(method, molecule=molecule, return_wfn=True,
                                  dertype=dertype)

    # Extract thermodynamic quantities
    zpve = psi4.core.variable('ZPVE')
    h_corr = psi4.core.variable('THERMAL ENERGY CORRECTION')
    g_corr = psi4.core.variable('GIBBS FREE ENERGY CORRECTION')

    h_total = energy + h_corr
    g_total = energy + g_corr

    # Calculate entropy from H and G: S = (H - G) / T
    s_total = (h_total - g_total) / temperature

    result = {
        'temperature_K': temperature,
        'pressure_atm': pressure,
        'electronic_energy_hartree': energy,
        'zpve_hartree': zpve,
        'zpve_kcal': zpve * HARTREE_TO_KCAL,
        'enthalpy_hartree': h_total,
        'enthalpy_kcal': h_total * HARTREE_TO_KCAL,
        'entropy_hartree_K': s_total,
        'entropy_cal_mol_K': s_total * HARTREE_TO_KCAL * 1000,  # cal/mol/K
        'gibbs_free_energy_hartree': g_total,
        'gibbs_free_energy_kcal': g_total * HARTREE_TO_KCAL,
        'thermal_correction_H_hartree': h_corr,
        'thermal_correction_G_hartree': g_corr,
    }

    logging.info(f"E0: {energy:.10f} Hartree")
    logging.info(f"H:  {h_total:.10f} Hartree ({h_total * HARTREE_TO_KCAL:.4f} kcal/mol)")
    logging.info(f"G:  {g_total:.10f} Hartree ({g_total * HARTREE_TO_KCAL:.4f} kcal/mol)")
    logging.info(f"S:  {s_total * HARTREE_TO_KCAL * 1000:.4f} cal/mol/K")

    return result


# ============= SAPT (SYMMETRY-ADAPTED PERTURBATION THEORY) =============

def compute_sapt(dimer_molecule, method: str = 'sapt0', basis: str = 'jun-cc-pvdz',
                 **kwargs) -> Dict:
    """Compute SAPT interaction energy decomposition.

    SAPT provides a physically meaningful decomposition of intermolecular
    interactions into electrostatics, exchange, induction, and dispersion.

    Args:
        dimer_molecule: Psi4 Molecule with two fragments separated by '--'
        method: SAPT level (sapt0, sapt2, sapt2+, sapt2+(3), etc.)
        basis: Basis set
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - total_interaction_energy: Total SAPT interaction energy (kcal/mol)
            - electrostatics: Electrostatic component
            - exchange: Exchange-repulsion component
            - induction: Induction (polarization) component
            - dispersion: Dispersion component
            - All values in Hartree and kcal/mol

    Example:
        >>> dimer = psi4.geometry('''
        ...     0 1
        ...     O  0.000  0.000  0.117
        ...     H -0.756  0.000 -0.470
        ...     H  0.756  0.000 -0.470
        ...     --
        ...     0 1
        ...     O  3.000  0.000  0.117
        ...     H  2.244  0.000 -0.470
        ...     H  3.756  0.000 -0.470
        ... ''')
        >>> result = compute_sapt(dimer, method='sapt0')
    """
    import psi4

    psi4.set_options({'basis': basis, **kwargs})

    logging.info(f"Computing {method.upper()}/{basis} interaction energy...")

    energy = psi4.energy(method, molecule=dimer_molecule)

    # Extract SAPT components
    elst = psi4.core.variable('SAPT ELST ENERGY')
    exch = psi4.core.variable('SAPT EXCH ENERGY')
    ind = psi4.core.variable('SAPT IND ENERGY')
    disp = psi4.core.variable('SAPT DISP ENERGY')
    total = psi4.core.variable('SAPT TOTAL ENERGY')

    result = {
        'method': method.upper(),
        'basis': basis,
        'total_interaction_hartree': total,
        'total_interaction_kcal': total * HARTREE_TO_KCAL,
        'electrostatics_hartree': elst,
        'electrostatics_kcal': elst * HARTREE_TO_KCAL,
        'exchange_hartree': exch,
        'exchange_kcal': exch * HARTREE_TO_KCAL,
        'induction_hartree': ind,
        'induction_kcal': ind * HARTREE_TO_KCAL,
        'dispersion_hartree': disp,
        'dispersion_kcal': disp * HARTREE_TO_KCAL,
    }

    logging.info(f"SAPT Interaction Energy Decomposition (kcal/mol):")
    logging.info(f"  Electrostatics: {result['electrostatics_kcal']:+.4f}")
    logging.info(f"  Exchange:       {result['exchange_kcal']:+.4f}")
    logging.info(f"  Induction:      {result['induction_kcal']:+.4f}")
    logging.info(f"  Dispersion:     {result['dispersion_kcal']:+.4f}")
    logging.info(f"  Total:          {result['total_interaction_kcal']:+.4f}")

    return result


# ============= EXCITED STATES =============

def compute_excited_states(molecule, method: str = 'eom-ccsd', basis: str = 'cc-pvdz',
                           n_states: int = 5, **kwargs) -> Dict:
    """Compute excited state energies and properties.

    Args:
        molecule: Psi4 Molecule object
        method: Excited state method ('eom-ccsd', 'tddft', 'tda', 'adc(2)')
        basis: Basis set
        n_states: Number of excited states to compute
        **kwargs: Additional Psi4 options

    Returns:
        dict with:
            - ground_state_energy: Ground state energy (Hartree)
            - excitation_energies_eV: List of excitation energies
            - excitation_energies_nm: Wavelengths in nm
            - oscillator_strengths: List of oscillator strengths (if available)
    """
    import psi4

    # Set up options based on method
    if method.lower() in ['tddft', 'tda']:
        psi4.set_options({
            'basis': basis,
            'tdscf_states': n_states,
            'tdscf_tda': method.lower() == 'tda',
            **kwargs
        })
        logging.info(f"Computing TD-DFT/{basis} excited states...")

        # Need a DFT ground state first
        energy, wfn = psi4.energy('b3lyp', molecule=molecule, return_wfn=True)
        psi4.tdscf(wfn)

        # Extract excitation energies using correct Psi4 variable naming convention
        # Format: 'TD-DFT ROOT 0 -> ROOT {n} EXCITATION ENERGY'
        # Format: 'TD-DFT ROOT 0 -> ROOT {n} OSCILLATOR STRENGTH (LEN)'
        exc_energies_hartree = []
        osc_strengths = []
        for i in range(1, n_states + 1):
            try:
                exc_e = psi4.core.variable(f'TD-DFT ROOT 0 -> ROOT {i} EXCITATION ENERGY')
                exc_energies_hartree.append(exc_e)
                try:
                    osc_f = psi4.core.variable(f'TD-DFT ROOT 0 -> ROOT {i} OSCILLATOR STRENGTH (LEN)')
                    osc_strengths.append(osc_f)
                except:
                    osc_strengths.append(None)
            except:
                break

    elif method.lower() == 'eom-ccsd':
        psi4.set_options({
            'basis': basis,
            'roots_per_irrep': [n_states],  # All states in first irrep
            **kwargs
        })
        logging.info(f"Computing EOM-CCSD/{basis} excited states...")

        energy, wfn = psi4.energy('eom-ccsd', molecule=molecule, return_wfn=True)

        # Extract EOM-CCSD excitation energies
        exc_energies_hartree = []
        for i in range(n_states):
            try:
                exc_e = psi4.core.variable(f'EOM-CCSD ROOT {i+1} TOTAL ENERGY') - energy
                exc_energies_hartree.append(exc_e)
            except:
                break
        osc_strengths = [None] * len(exc_energies_hartree)  # Not typically available for EOM-CCSD

    else:
        raise ValueError(f"Unknown excited state method: {method}")

    # Convert to eV and nm
    exc_energies_eV = [e * HARTREE_TO_EV for e in exc_energies_hartree]
    exc_energies_nm = [1240.0 / e if e > 0 else 0 for e in exc_energies_eV]

    result = {
        'method': method.upper(),
        'basis': basis,
        'n_states': len(exc_energies_hartree),
        'ground_state_energy_hartree': energy,
        'excitation_energies_hartree': exc_energies_hartree,
        'excitation_energies_eV': exc_energies_eV,
        'excitation_energies_nm': exc_energies_nm,
        'oscillator_strengths': osc_strengths,
    }

    logging.info(f"Computed {len(exc_energies_hartree)} excited states:")
    for i, (eV, nm, f) in enumerate(zip(exc_energies_eV, exc_energies_nm, osc_strengths)):
        f_str = f"f={f:.4f}" if f is not None else ""
        logging.info(f"  State {i+1}: {eV:.4f} eV ({nm:.1f} nm) {f_str}")

    return result


# ============= OUTPUT PARSING =============

def parse_psi4_output(output_file: str) -> Dict:
    """Parse Psi4 output file for key results.

    Args:
        output_file: Path to Psi4 output file

    Returns:
        dict with parsed results
    """
    results = {
        'converged': False,
        'total_energy_hartree': None,
        'total_energy_eV': None,
        'method': None,
        'basis': None,
        'n_basis_functions': None,
        'n_electrons': None,
        'dipole_moment': None,
        'wall_time_seconds': None,
        'scf_iterations': None,
    }

    if not os.path.exists(output_file):
        logging.warning(f"Output file not found: {output_file}")
        return results

    with open(output_file, 'r') as f:
        content = f.read()

    # Check for successful completion
    if 'Psi4 exiting successfully' in content or 'beer' in content.lower():
        results['converged'] = True

    # Parse energy
    energy_patterns = [
        r'Total Energy\s*=\s*([-\d.]+)',
        r'@\w+\s+Final Energy:\s*([-\d.]+)',
        r'CCSD\(T\) total energy\s*=\s*([-\d.]+)',
        r'MP2 Total Energy\s*=\s*([-\d.]+)',
    ]
    for pattern in energy_patterns:
        match = re.search(pattern, content)
        if match:
            results['total_energy_hartree'] = float(match.group(1))
            results['total_energy_eV'] = results['total_energy_hartree'] * HARTREE_TO_EV
            break

    # Parse basis set
    match = re.search(r'Basis Set:\s*(\S+)', content)
    if match:
        results['basis'] = match.group(1)

    # Parse number of basis functions
    match = re.search(r'Number of basis functions:\s*(\d+)', content)
    if match:
        results['n_basis_functions'] = int(match.group(1))

    # Parse SCF iterations
    match = re.search(r'(\d+)\s+SCF Iterations', content)
    if match:
        results['scf_iterations'] = int(match.group(1))

    # Parse dipole moment
    match = re.search(r'Dipole Moment:.*?\n.*?Total\s+([-\d.]+)', content, re.DOTALL)
    if match:
        results['dipole_moment'] = float(match.group(1))

    # Parse wall time
    match = re.search(r'Psi4 wall time for execution:\s*([\d:]+(?:\.\d+)?)', content)
    if match:
        time_str = match.group(1)
        # Convert HH:MM:SS.ms to seconds
        parts = time_str.split(':')
        if len(parts) == 3:
            results['wall_time_seconds'] = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            results['wall_time_seconds'] = float(time_str)

    return results


# ============= VISUALIZATION =============

def plot_orbital_energies(wfn, output_file: str = 'orbital_energies.png',
                          show_homo_lumo: bool = True) -> str:
    """Plot orbital energy diagram.

    Args:
        wfn: Psi4 wavefunction object
        output_file: Output file path
        show_homo_lumo: Highlight HOMO and LUMO

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    # Get orbital energies (handles multi-irrep wavefunctions)
    occ_raw, virt_raw = _extract_orbital_energies(wfn)

    fig, ax = plt.subplots(figsize=(8, 6))

    # Plot occupied orbitals
    occ_energies = occ_raw * HARTREE_TO_EV
    virt_energies = virt_raw[:10] * HARTREE_TO_EV  # First 10 virtual

    ax.hlines(occ_energies, 0.2, 0.8, colors='blue', linewidths=2, label='Occupied')
    ax.hlines(virt_energies, 0.2, 0.8, colors='red', linewidths=2, label='Virtual')

    if show_homo_lumo and len(occ_energies) > 0:
        ax.hlines([occ_energies[-1]], 0.1, 0.9, colors='green', linewidths=3)
        ax.text(0.92, occ_energies[-1], 'HOMO', va='center')
        if len(virt_energies) > 0:
            ax.hlines([virt_energies[0]], 0.1, 0.9, colors='orange', linewidths=3)
            ax.text(0.92, virt_energies[0], 'LUMO', va='center')

    ax.set_ylabel('Energy (eV)')
    ax.set_xlim(0, 1.2)
    ax.set_xticks([])
    ax.legend(loc='upper right')
    ax.set_title('Molecular Orbital Energies')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved orbital energy plot: {output_file}")
    return output_file


def plot_ir_spectrum(frequencies: List[float], intensities: List[float],
                     output_file: str = 'ir_spectrum.png',
                     broadening: float = 10.0) -> str:
    """Plot IR spectrum.

    Args:
        frequencies: Vibrational frequencies in cm^-1
        intensities: IR intensities in km/mol
        output_file: Output file path
        broadening: Gaussian broadening width (cm^-1)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    frequencies = np.array(frequencies)
    intensities = np.array(intensities)

    # Filter out imaginary frequencies
    mask = frequencies > 0
    frequencies = frequencies[mask]
    intensities = intensities[mask]

    # Create broadened spectrum
    x = np.linspace(0, max(frequencies) + 500, 2000)
    y = np.zeros_like(x)

    for freq, inten in zip(frequencies, intensities):
        y += inten * np.exp(-0.5 * ((x - freq) / broadening) ** 2)

    fig, ax = plt.subplots(figsize=(10, 6))

    # Plot broadened spectrum
    ax.plot(x, y, 'b-', linewidth=1.5)
    ax.fill_between(x, 0, y, alpha=0.3)

    # Mark peak positions
    ax.vlines(frequencies, 0, intensities * 0.1, colors='red', alpha=0.5, linewidths=1)

    ax.set_xlabel('Wavenumber (cm$^{-1}$)')
    ax.set_ylabel('Intensity (km/mol)')
    ax.set_title('Calculated IR Spectrum')
    ax.set_xlim(0, max(frequencies) + 500)
    ax.set_ylim(bottom=0)
    ax.invert_xaxis()  # IR convention: high wavenumber on left

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved IR spectrum plot: {output_file}")
    return output_file


def plot_uv_vis_spectrum(excitation_energies: List[float],
                         oscillator_strengths: List[float],
                         output_file: str = 'uv_vis_spectrum.png',
                         broadening: float = 0.3) -> str:
    """Plot UV-Vis absorption spectrum.

    Args:
        excitation_energies: Excitation energies in eV
        oscillator_strengths: Oscillator strengths
        output_file: Output file path
        broadening: Gaussian broadening (eV)

    Returns:
        Path to saved figure
    """
    import matplotlib.pyplot as plt

    exc_eV = np.array(excitation_energies)
    osc = np.array(oscillator_strengths)

    # Convert to wavelength
    exc_nm = 1240.0 / exc_eV

    # Create spectrum
    nm_range = np.linspace(100, 800, 1000)
    eV_range = 1240.0 / nm_range

    spectrum = np.zeros_like(nm_range)
    for e, f in zip(exc_eV, osc):
        if f is not None and f > 0:
            spectrum += f * np.exp(-0.5 * ((eV_range - e) / broadening) ** 2)

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(nm_range, spectrum, 'b-', linewidth=1.5)
    ax.fill_between(nm_range, 0, spectrum, alpha=0.3)

    # Mark transitions
    for nm, f in zip(exc_nm, osc):
        if f is not None and f > 0:
            ax.axvline(nm, color='red', alpha=0.5, linestyle='--', linewidth=1)

    ax.set_xlabel('Wavelength (nm)')
    ax.set_ylabel('Absorption (arb. units)')
    ax.set_title('Calculated UV-Vis Absorption Spectrum')
    ax.set_xlim(100, 800)
    ax.set_ylim(bottom=0)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    plt.close()

    logging.info(f"Saved UV-Vis spectrum plot: {output_file}")
    return output_file


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


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None, status: str = "completed") -> str:
    """Save final results to OUTPUT_DIR/final_results.json.

    The output JSON has the structure:
        {"status": "...", "summary": <results>, "output_files": {...}, ...}

    IMPORTANT: The ``results`` dict is stored under the ``'summary'`` key.
    Downstream agents reading this file must access ``data['summary']`` to
    retrieve the actual results, NOT the top-level keys.

    Args:
        results: dict containing the main analysis results
        output_files: dict mapping names to file paths
        file_descriptions: dict mapping names to descriptions
        status: workflow status string

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


# ============= CONVENIENCE FUNCTIONS =============

def quick_setup(input_dir, output_dir, work_dir=None, copy_input=True) -> List[str]:
    """Quick setup for typical Psi4 workflow.

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


def quick_finish() -> List[str]:
    """Quick finish for typical Psi4 workflow.

    Copies output files to output directory.

    Returns:
        List of copied output files
    """
    return copy_outputs()


# ============= BASIS SET EXTRAPOLATION =============

def extrapolate_cbs(energies: Dict[str, float], scheme: str = 'scf_xtpl_helgaker_2') -> Dict:
    """Extrapolate energy to complete basis set limit.

    Args:
        energies: Dict mapping basis set to energy, e.g.,
                  {'cc-pvdz': -76.0, 'cc-pvtz': -76.1}
        scheme: Extrapolation scheme ('scf_xtpl_helgaker_2', 'corl_xtpl_helgaker_2')

    Returns:
        dict with CBS limit energy and extrapolation parameters
    """
    import psi4

    # Basis cardinal numbers
    cardinal_map = {
        'cc-pvdz': 2, 'aug-cc-pvdz': 2,
        'cc-pvtz': 3, 'aug-cc-pvtz': 3,
        'cc-pvqz': 4, 'aug-cc-pvqz': 4,
        'cc-pv5z': 5, 'aug-cc-pv5z': 5,
    }

    basis_sets = list(energies.keys())
    E_values = [energies[b] for b in basis_sets]
    X_values = [cardinal_map.get(b.lower(), 3) for b in basis_sets]

    if len(energies) < 2:
        raise ValueError("Need at least 2 basis sets for extrapolation")

    # Two-point extrapolation using Helgaker formula
    X1, X2 = X_values[-2], X_values[-1]
    E1, E2 = E_values[-2], E_values[-1]

    # E(X) = E_CBS + A * X^(-3) for correlation energy
    # E(X) = E_CBS + A * exp(-B*X) for SCF

    if 'scf' in scheme:
        # SCF extrapolation (exponential)
        # Using two-point formula
        E_cbs = (E2 * np.exp(1.63 * X2) - E1 * np.exp(1.63 * X1)) / \
                (np.exp(1.63 * X2) - np.exp(1.63 * X1))
    else:
        # Correlation extrapolation (inverse cubic)
        E_cbs = (E2 * X2**3 - E1 * X1**3) / (X2**3 - X1**3)

    result = {
        'cbs_energy_hartree': E_cbs,
        'cbs_energy_kcal': E_cbs * HARTREE_TO_KCAL,
        'input_energies': energies,
        'scheme': scheme,
        'basis_cardinal_numbers': dict(zip(basis_sets, X_values)),
    }

    logging.info(f"CBS extrapolation ({scheme}): {E_cbs:.10f} Hartree")
    return result


# ============= COUNTERPOISE CORRECTION =============

def compute_counterpoise_correction(dimer_molecule, method: str = 'hf',
                                    basis: str = 'cc-pvdz') -> Dict:
    """Compute counterpoise-corrected interaction energy.

    Corrects for basis set superposition error (BSSE) using the Boys-Bernardi
    counterpoise correction.

    Args:
        dimer_molecule: Psi4 Molecule with two fragments (separated by '--')
        method: Quantum chemistry method
        basis: Basis set

    Returns:
        dict with:
            - interaction_energy: Uncorrected interaction energy
            - cp_correction: Counterpoise correction
            - cp_corrected_energy: BSSE-corrected interaction energy
    """
    import psi4

    psi4.set_options({'basis': basis})

    logging.info(f"Computing counterpoise-corrected {method.upper()}/{basis} interaction...")

    # Psi4 has built-in CP correction
    cp_energy = psi4.energy(f'{method}/cp', molecule=dimer_molecule)
    uncorrected_energy = psi4.energy(method, molecule=dimer_molecule)

    # Get individual fragment energies
    E_A = psi4.core.variable('CURRENT ENERGY:MONOMER A')
    E_B = psi4.core.variable('CURRENT ENERGY:MONOMER B')
    E_AB = psi4.core.variable('CURRENT ENERGY')

    bsse = psi4.core.variable('CP BSSE')
    int_energy = E_AB - E_A - E_B

    result = {
        'interaction_energy_hartree': int_energy,
        'interaction_energy_kcal': int_energy * HARTREE_TO_KCAL,
        'cp_correction_hartree': bsse,
        'cp_correction_kcal': bsse * HARTREE_TO_KCAL,
        'cp_corrected_energy_hartree': int_energy - bsse,
        'cp_corrected_energy_kcal': (int_energy - bsse) * HARTREE_TO_KCAL,
        'monomer_A_energy': E_A,
        'monomer_B_energy': E_B,
        'dimer_energy': E_AB,
    }

    logging.info(f"Interaction energy: {result['interaction_energy_kcal']:.4f} kcal/mol")
    logging.info(f"BSSE correction:    {result['cp_correction_kcal']:.4f} kcal/mol")
    logging.info(f"CP-corrected:       {result['cp_corrected_energy_kcal']:.4f} kcal/mol")

    return result


# Module initialization
if __name__ == "__main__":
    print("Psi4 Utilities Library for Discovery Platform")
    print(f"Available cores: {NUM_CORES}")
    print(f"Scratch directory: {PSI4_SCRATCH}")
    print("\nAvailable functions:")
    print("  Setup: quick_setup, quick_finish, copy_input_files, copy_outputs")
    print("  Execution: run_psi4, run_psi4_script, setup_psi4")
    print("  Molecules: create_molecule, read_xyz_file, write_xyz_file")
    print("  Energy: compute_energy, compute_gradient, compute_homo_lumo_gap, compute_fundamental_gap")
    print("  Optimization: optimize_geometry")
    print("  Frequencies: compute_frequencies, compute_thermochemistry")
    print("  Interactions: compute_sapt, compute_counterpoise_correction")
    print("  Excited states: compute_excited_states")
    print("  Analysis: extrapolate_cbs")
    print("  Parsing: parse_psi4_output")
    print("  Visualization: plot_orbital_energies, plot_ir_spectrum, plot_uv_vis_spectrum")
    print("  Results: save_final_results")
