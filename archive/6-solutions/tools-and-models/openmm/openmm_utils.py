#!/usr/bin/env python3
"""OpenMM utilities library for Microsoft Discovery platform workflows.

Provides helper functions for molecular dynamics simulations using OpenMM,
including PDB preparation (PDBFixer), system building, simulation execution,
trajectory analysis (MDTraj), and visualization (matplotlib).
"""

import os
import sys
import glob
import json
import logging
import shutil
import time
import traceback
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/openmm_scratch"

# Unit conversion helpers (OpenMM units -> common units)
_KJ_PER_MOL_TO_KCAL = 0.239006

# ============= SETUP FUNCTIONS =============

def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.

    Args:
        input_dir: Path to input files (mounted by Discovery)
        output_dir: Path for output files (persisted after job)
        work_dir: Working directory for intermediate files
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    copy_input_files()
    logging.info(f"OpenMM utils initialized. Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(WORK_DIR)}")

    # Log available OpenMM platforms
    try:
        import openmm
        platforms = [openmm.Platform.getPlatform(i).getName()
                     for i in range(openmm.Platform.getNumPlatforms())]
        logging.info(f"Available OpenMM platforms: {platforms}")
    except Exception as e:
        logging.warning(f"Could not detect OpenMM platforms: {e}")


def copy_input_files(patterns=None):
    """Copy input files to working directory.

    Args:
        patterns: Optional list of glob patterns (e.g., ['*.pdb', '*.xml']).
                  If None, copies all files.
    """
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if not os.path.exists(INPUT_DIR):
        return
    if patterns:
        for pat in patterns:
            for f in glob.glob(os.path.join(INPUT_DIR, pat)):
                if os.path.isfile(f):
                    shutil.copy(f, WORK_DIR)
    else:
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def copy_outputs(patterns=None):
    """Copy output files to output directory.

    Args:
        patterns: Optional list of glob patterns. If None, copies common types.
    """
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    if patterns is None:
        patterns = ['*.pdb', '*.dcd', '*.xml', '*.csv', '*.log', '*.png',
                     '*.json', '*.dat', '*.out', '*.xtc', '*.chk']
    for pat in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pat)):
            if os.path.isfile(f):
                shutil.copy(f, OUTPUT_DIR)
    logging.info(f"Outputs copied to {OUTPUT_DIR}")


def quick_finish():
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None, status: str = "completed"):
    """Save final results to JSON file. MANDATORY for every script.

    Args:
        results: Dictionary of key results/metrics
        output_files: Dict mapping names to file paths
        file_descriptions: Dict mapping names to descriptions
        status: Job status ('completed', 'failed', 'partial')
    """
    def _make_serializable(obj):
        """Convert numpy types to Python native types for JSON serialization."""
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: _make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_make_serializable(v) for v in obj]
        return obj

    final_data = {"status": status, "summary": _make_serializable(results)}
    if output_files:
        final_data["output_files"] = _make_serializable(output_files)
    if file_descriptions:
        final_data["file_descriptions"] = _make_serializable(file_descriptions)

    output_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(output_path, 'w') as f:
        json.dump(final_data, f, indent=2, default=str)
    logging.info(f"Saved final_results.json to {output_path}")


# ============= PDB PREPARATION =============

def fix_pdb(input_pdb: str, output_pdb: str = None,
            add_missing_atoms: bool = True,
            add_missing_residues: bool = False,
            replace_nonstandard: bool = True,
            add_hydrogens: bool = True,
            ph: float = 7.0,
            remove_heterogens: bool = False,
            keep_water: bool = True,
            output_file: str = None) -> str:
    """Fix PDB structure using PDBFixer.

    Handles missing atoms, non-standard residues, and adds hydrogens.

    Args:
        input_pdb: Path to input PDB file
        output_pdb: Path for fixed PDB (default: input stem + '_fixed.pdb')
        add_missing_atoms: Add missing heavy atoms
        add_missing_residues: Add missing residues (loops)
        replace_nonstandard: Replace non-standard residues with standard
        add_hydrogens: Add hydrogen atoms at specified pH
        ph: pH for protonation state (default 7.0)
        remove_heterogens: Remove heterogens (ligands, etc.)
        keep_water: Keep water molecules (only if remove_heterogens=True)

    Returns:
        Path to fixed PDB file
    """
    if not os.path.isfile(input_pdb):
        raise FileNotFoundError(f"Input PDB not found: {input_pdb}")

    from pdbfixer import PDBFixer
    from openmm.app import PDBFile

    # Accept output_file as alias for output_pdb (documented API compat)
    if output_file is not None and output_pdb is None:
        output_pdb = output_file

    if output_pdb is None:
        stem = Path(input_pdb).stem
        output_pdb = f"{stem}_fixed.pdb"

    logging.info(f"Fixing PDB: {input_pdb}")
    fixer = PDBFixer(filename=input_pdb)

    if replace_nonstandard:
        fixer.findNonstandardResidues()
        # Preserve terminal cap residues (ACE, NME) - PDBFixer corrupts them
        cap_names = {'ACE', 'NME', 'NMA'}
        original_count = len(fixer.nonstandardResidues)
        fixer.nonstandardResidues = [
            (r, replacement) for r, replacement in fixer.nonstandardResidues
            if r.name not in cap_names
        ]
        skipped = original_count - len(fixer.nonstandardResidues)
        fixer.replaceNonstandardResidues()
        logging.info(f"  Replaced {len(fixer.nonstandardResidues)} non-standard residues"
                     f" (skipped {skipped} terminal caps)")

    if add_missing_residues:
        fixer.findMissingResidues()
        logging.info(f"  Found {len(fixer.missingResidues)} missing residue segments")
    else:
        fixer.missingResidues = {}

    if remove_heterogens:
        fixer.removeHeterogens(keepWater=keep_water)
        logging.info("  Removed heterogens")

    if add_missing_atoms:
        fixer.findMissingAtoms()
        # Skip cap residues - PDBFixer corrupts ACE/NME/NMA
        cap_names = {'ACE', 'NME', 'NMA'}
        for residue in list(fixer.missingAtoms.keys()):
            if residue.name in cap_names:
                del fixer.missingAtoms[residue]
        for residue in list(fixer.missingTerminals.keys()):
            if residue.name in cap_names:
                del fixer.missingTerminals[residue]
        fixer.addMissingAtoms()
        logging.info("  Added missing heavy atoms")

    if add_hydrogens:
        fixer.addMissingHydrogens(ph)
        logging.info(f"  Added hydrogens at pH {ph}")

    with open(output_pdb, 'w') as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)
    logging.info(f"  Fixed PDB saved: {output_pdb}")
    return output_pdb


# ============= SYSTEM BUILDING =============

def select_platform(preferred: str = 'auto') -> 'openmm.Platform':
    """Select the best available OpenMM compute platform.

    Args:
        preferred: 'CUDA', 'OpenCL', 'CPU', 'Reference', or 'auto' (fastest available)

    Returns:
        OpenMM Platform object
    """
    import openmm

    if preferred == 'auto':
        # Try platforms in order of speed
        for name in ['CUDA', 'OpenCL', 'CPU', 'Reference']:
            try:
                platform = openmm.Platform.getPlatformByName(name)
                logging.info(f"Selected platform: {name}")
                return platform
            except Exception:
                continue
        raise RuntimeError("No OpenMM platform available")
    else:
        platform = openmm.Platform.getPlatformByName(preferred)
        logging.info(f"Selected platform: {preferred}")
        return platform


def create_system(pdb_file: str,
                  force_field: str = 'amber14-all.xml',
                  water_model: str = 'amber14/tip3pfb.xml',
                  nonbonded_method: str = 'PME',
                  nonbonded_cutoff_nm: float = 1.0,
                  constraints: str = 'HBonds',
                  rigid_water: bool = True,
                  solvate: bool = True,
                  box_padding_nm: float = 1.0,
                  ionic_strength_M: float = 0.15,
                  positive_ion: str = 'Na+',
                  negative_ion: str = 'Cl-',
                  extra_ff_files: List[str] = None) -> Dict:
    """Build an OpenMM System from a PDB file.

    Loads the structure, applies force field, optionally solvates with water
    and ions, and creates the System object.

    Args:
        pdb_file: Path to PDB file (should already be fixed with fix_pdb)
        force_field: Force field XML file name
        water_model: Water model XML file name
        nonbonded_method: 'PME', 'CutoffPeriodic', 'CutoffNonPeriodic', 'NoCutoff'
        nonbonded_cutoff_nm: Nonbonded cutoff in nm
        constraints: 'HBonds', 'AllBonds', 'HAngles', or None
        rigid_water: Whether to constrain water geometry
        solvate: Whether to add solvent box
        box_padding_nm: Padding around solute in nm
        ionic_strength_M: Ionic strength in molar
        positive_ion: Positive ion type
        negative_ion: Negative ion type
        extra_ff_files: Additional force field XML files (e.g., for ligands)

    Returns:
        Dict with keys: system, topology, positions, modeller, force_field_obj,
                        n_atoms, n_residues, box_vectors
    """
    if not os.path.isfile(pdb_file):
        raise FileNotFoundError(f"PDB file not found: {pdb_file}")

    import openmm
    from openmm import app, unit

    logging.info(f"Creating system from {pdb_file}")
    logging.info(f"  Force field: {force_field}, Water: {water_model}")

    # Warn about incompatible solvation/nonbonded settings
    if not solvate and nonbonded_method in ('PME', 'CutoffPeriodic'):
        logging.warning(f"solvate=False with nonbonded_method='{nonbonded_method}' "
                        f"requires periodic box vectors in the PDB. Consider using "
                        f"'NoCutoff' or 'CutoffNonPeriodic' for unsolvated systems.")

    # Load PDB (prefer PDBFixer for robust handling of non-standard residues/caps)
    try:
        from pdbfixer import PDBFixer
        fixer = PDBFixer(filename=pdb_file)
        topology = fixer.topology
        positions = fixer.positions
    except Exception:
        pdb = app.PDBFile(pdb_file)
        topology = pdb.topology
        positions = pdb.positions

    # Set up force field
    ff_files = [force_field, water_model]
    if extra_ff_files:
        ff_files.extend(extra_ff_files)
    ff = app.ForceField(*ff_files)

    # Create modeller and ensure correct hydrogens via ForceField templates
    modeller = app.Modeller(topology, positions)
    try:
        ff.createSystem(modeller.topology, nonbondedMethod=app.NoCutoff)
    except ValueError:
        # Template mismatch — strip hydrogens and re-add using ForceField
        to_delete = [a for a in modeller.topology.atoms()
                     if a.element is not None and a.element.symbol == 'H']
        modeller.delete(to_delete)
        modeller.addHydrogens(ff)

    # Solvate
    if solvate:
        logging.info(f"  Solvating with {box_padding_nm} nm padding, "
                     f"{ionic_strength_M} M ionic strength")
        modeller.addSolvent(
            ff,
            padding=box_padding_nm * unit.nanometers,
            ionicStrength=ionic_strength_M * unit.molar,
            positiveIon=positive_ion,
            negativeIon=negative_ion
        )

    # Map string to OpenMM nonbonded method
    nb_methods = {
        'PME': app.PME,
        'CutoffPeriodic': app.CutoffPeriodic,
        'CutoffNonPeriodic': app.CutoffNonPeriodic,
        'NoCutoff': app.NoCutoff,
    }
    nb_method = nb_methods.get(nonbonded_method, app.PME)

    # Map constraints
    constraint_map = {
        'HBonds': app.HBonds,
        'AllBonds': app.AllBonds,
        'HAngles': app.HAngles,
        None: None,
        'None': None,
    }
    constraint_val = constraint_map.get(constraints, app.HBonds)

    # Safety: AllBonds + custom covalent ligand force fields causes SHAKE failures
    # on non-standard bonds from frcmod files. Downgrade to HBonds automatically.
    if constraint_val == app.AllBonds and extra_ff_files:
        logging.warning("AllBonds constraints with custom force field files (extra_ff_files) "
                        "can cause SHAKE failures on non-standard covalent bonds. "
                        "Downgrading to HBonds. Use HBonds + 1 fs timestep for safety.")
        constraint_val = app.HBonds

    # Create system
    system = ff.createSystem(
        modeller.topology,
        nonbondedMethod=nb_method,
        nonbondedCutoff=nonbonded_cutoff_nm * unit.nanometers,
        constraints=constraint_val,
        rigidWater=rigid_water
    )

    n_atoms = modeller.topology.getNumAtoms()
    n_residues = modeller.topology.getNumResidues()
    box_vectors = modeller.topology.getPeriodicBoxVectors()

    logging.info(f"  System created: {n_atoms} atoms, {n_residues} residues")
    if box_vectors:
        box_nm = [v[i].value_in_unit(unit.nanometers) for i, v in enumerate(box_vectors)]
        logging.info(f"  Box dimensions: {box_nm[0]:.2f} x {box_nm[1]:.2f} x {box_nm[2]:.2f} nm")

    return {
        'system': system,
        'topology': modeller.topology,
        'positions': modeller.positions,
        'modeller': modeller,
        'force_field_obj': ff,
        'n_atoms': n_atoms,
        'n_residues': n_residues,
        'box_vectors': box_vectors,
    }


def create_system_from_amber(prmtop_file: str, inpcrd_file: str,
                              nonbonded_method: str = 'PME',
                              nonbonded_cutoff_nm: float = 1.0,
                              constraints: str = 'HBonds',
                              rigid_water: bool = True) -> Dict:
    """Build an OpenMM System from AMBER topology/coordinate files.

    Args:
        prmtop_file: Path to AMBER prmtop file
        inpcrd_file: Path to AMBER inpcrd/rst7 file
        nonbonded_method: Nonbonded method string
        nonbonded_cutoff_nm: Cutoff in nm
        constraints: Constraint type
        rigid_water: Rigid water geometry

    Returns:
        Dict with keys: system, topology, positions, n_atoms, box_vectors
    """
    if not os.path.isfile(prmtop_file):
        raise FileNotFoundError(f"AMBER prmtop file not found: {prmtop_file}")
    if not os.path.isfile(inpcrd_file):
        raise FileNotFoundError(f"AMBER inpcrd file not found: {inpcrd_file}")

    import openmm
    from openmm import app, unit

    logging.info(f"Loading AMBER files: {prmtop_file}, {inpcrd_file}")
    prmtop = app.AmberPrmtopFile(prmtop_file)
    inpcrd = app.AmberInpcrdFile(inpcrd_file)

    nb_methods = {'PME': app.PME, 'CutoffPeriodic': app.CutoffPeriodic,
                  'CutoffNonPeriodic': app.CutoffNonPeriodic, 'NoCutoff': app.NoCutoff}
    constraint_map = {'HBonds': app.HBonds, 'AllBonds': app.AllBonds,
                      'HAngles': app.HAngles, None: None, 'None': None}

    system = prmtop.createSystem(
        nonbondedMethod=nb_methods.get(nonbonded_method, app.PME),
        nonbondedCutoff=nonbonded_cutoff_nm * unit.nanometers,
        constraints=constraint_map.get(constraints, app.HBonds),
        rigidWater=rigid_water
    )

    positions = inpcrd.positions
    box_vectors = inpcrd.boxVectors
    if box_vectors is not None:
        system.setDefaultPeriodicBoxVectors(*box_vectors)

    n_atoms = prmtop.topology.getNumAtoms()
    logging.info(f"  AMBER system: {n_atoms} atoms")

    return {
        'system': system,
        'topology': prmtop.topology,
        'positions': positions,
        'n_atoms': n_atoms,
        'box_vectors': box_vectors,
    }


# ============= SIMULATION SETUP & EXECUTION =============

def setup_simulation(system: 'openmm.System',
                     topology: 'openmm.app.Topology',
                     positions: Any,
                     temperature_K: float = 300.0,
                     timestep_ps: float = 0.002,
                     friction_per_ps: float = 1.0,
                     platform: str = 'auto',
                     precision: str = 'mixed') -> 'openmm.app.Simulation':
    """Create an OpenMM Simulation object with Langevin integrator.

    Args:
        system: OpenMM System object
        topology: OpenMM Topology object
        positions: Initial positions
        temperature_K: Temperature in Kelvin
        timestep_ps: Integration timestep in picoseconds
        friction_per_ps: Langevin friction coefficient (1/ps)
        platform: Platform name or 'auto'
        precision: 'single', 'mixed', or 'double' (for CUDA/OpenCL)

    Returns:
        OpenMM Simulation object
    """
    import openmm
    from openmm import app, unit

    integrator = openmm.LangevinMiddleIntegrator(
        temperature_K * unit.kelvin,
        friction_per_ps / unit.picoseconds,
        timestep_ps * unit.picoseconds
    )

    plat = select_platform(platform)
    properties = {}
    if plat.getName() in ('CUDA', 'OpenCL'):
        properties['Precision'] = precision

    simulation = app.Simulation(topology, system, integrator, plat, properties)
    simulation.context.setPositions(positions)
    logging.info(f"Simulation created: T={temperature_K}K, dt={timestep_ps}ps, "
                 f"platform={plat.getName()}")
    return simulation


def add_barostat(system: 'openmm.System',
                 temperature_K: float = 300.0,
                 pressure_atm: float = 1.0,
                 frequency: int = 25) -> int:
    """Add Monte Carlo barostat for NPT ensemble.

    Args:
        system: OpenMM System object
        temperature_K: Temperature in Kelvin
        pressure_atm: Pressure in atmospheres
        frequency: Barostat update frequency (steps)

    Returns:
        Index of the added force
    """
    import openmm
    from openmm import unit

    barostat = openmm.MonteCarloBarostat(
        pressure_atm * unit.atmospheres,
        temperature_K * unit.kelvin,
        frequency
    )
    force_idx = system.addForce(barostat)
    logging.info(f"Added barostat: P={pressure_atm} atm, T={temperature_K} K")
    return force_idx


def add_reporters(simulation: 'openmm.app.Simulation',
                  trajectory_file: str = 'trajectory.dcd',
                  log_file: str = 'simulation.log',
                  checkpoint_file: str = 'checkpoint.chk',
                  report_interval: int = 5000,
                  checkpoint_interval: int = 50000) -> None:
    """Add trajectory, log, and checkpoint reporters to simulation.

    Args:
        simulation: OpenMM Simulation object
        trajectory_file: Path for trajectory output (DCD format)
        log_file: Path for energy/temperature log (CSV)
        checkpoint_file: Path for checkpoint file
        report_interval: Steps between trajectory/log writes
        checkpoint_interval: Steps between checkpoint saves
    """
    from openmm import app

    simulation.reporters.append(
        app.DCDReporter(trajectory_file, report_interval)
    )
    simulation.reporters.append(
        app.StateDataReporter(
            log_file, report_interval,
            step=True, time=True,
            potentialEnergy=True, kineticEnergy=True, totalEnergy=True,
            temperature=True, volume=True, density=True,
            speed=True, separator=','
        )
    )
    simulation.reporters.append(
        app.CheckpointReporter(checkpoint_file, checkpoint_interval)
    )
    logging.info(f"Added reporters: traj={trajectory_file} (every {report_interval} steps), "
                 f"log={log_file}, checkpoint={checkpoint_file}")


# ============= RESTRAINTS & VALIDATION =============

def add_positional_restraints(simulation: 'openmm.app.Simulation',
                              atom_indices: List[int] = None,
                              force_constant_kj: float = 1000.0,
                              selection: str = 'heavy') -> Dict:
    """Add harmonic positional restraints via CustomExternalForce.

    Reference positions are taken from the current simulation context state
    (in nm), avoiding Angstrom-vs-nanometer mismatches that occur when using
    raw ParmEd or file-based coordinates directly.

    A sanity check verifies that activating restraints at reference positions
    produces delta-E ~0 (since atoms are already at their reference positions).

    Args:
        simulation: OpenMM Simulation object
        atom_indices: 0-based atom indices to restrain.  If None, uses selection.
        force_constant_kj: Restraint strength in kJ/mol/nm**2
            (1 kcal/mol/A**2 = 418.4 kJ/mol/nm**2)
        selection: Atom selection when atom_indices is None:
            'heavy', 'backbone', 'ca', 'all'

    Returns:
        Dict with: force_index, n_restrained, force_constant_kj, delta_energy_kj
    """
    import openmm
    from openmm import unit

    # Energy BEFORE adding restraints
    state = simulation.context.getState(getEnergy=True, getPositions=True)
    positions = state.getPositions(asNumpy=False)
    energy_before = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)

    # Determine atoms to restrain
    if atom_indices is None:
        atom_indices = []
        for atom in simulation.topology.atoms():
            if selection == 'all':
                atom_indices.append(atom.index)
            elif selection == 'heavy' and atom.element is not None and atom.element.symbol != 'H':
                atom_indices.append(atom.index)
            elif selection == 'backbone' and atom.name in ('CA', 'C', 'N', 'O'):
                atom_indices.append(atom.index)
            elif selection == 'ca' and atom.name == 'CA':
                atom_indices.append(atom.index)

    if not atom_indices:
        logging.warning("No atoms matched for restraints.")
        return {'force_index': -1, 'n_restrained': 0,
                'force_constant_kj': force_constant_kj, 'delta_energy_kj': 0.0}

    # Build CustomExternalForce — all values in OpenMM internal units (nm, kJ/mol)
    force = openmm.CustomExternalForce(
        '0.5*k*((x-x0)^2+(y-y0)^2+(z-z0)^2)'
    )
    force.addGlobalParameter('k', force_constant_kj)
    force.addPerParticleParameter('x0')
    force.addPerParticleParameter('y0')
    force.addPerParticleParameter('z0')

    # Set reference positions from context.getState() — already in nm
    for idx in atom_indices:
        pos = positions[idx]
        x0 = pos[0].value_in_unit(unit.nanometers)
        y0 = pos[1].value_in_unit(unit.nanometers)
        z0 = pos[2].value_in_unit(unit.nanometers)
        force.addParticle(idx, [x0, y0, z0])

    force_index = simulation.system.addForce(force)
    simulation.context.reinitialize(preserveState=True)

    # Sanity check: energy with restraints ON at reference positions should be ~unchanged
    state_after = simulation.context.getState(getEnergy=True)
    energy_after = state_after.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    delta_energy = abs(energy_after - energy_before)

    if delta_energy > 1.0:
        logging.warning(f"Restraint sanity check: dE = {delta_energy:.4f} kJ/mol "
                        f"(expected ~0 at reference positions). "
                        f"Possible unit mismatch (Angstrom vs nm)!")
    else:
        logging.info(f"Restraint sanity check passed: dE = {delta_energy:.6f} kJ/mol")

    logging.info(f"Added positional restraints: {len(atom_indices)} atoms, "
                 f"k={force_constant_kj} kJ/mol/nm^2 "
                 f"({force_constant_kj / 418.4:.2f} kcal/mol/A^2)")

    return {
        'force_index': force_index,
        'n_restrained': len(atom_indices),
        'force_constant_kj': force_constant_kj,
        'force_constant_kcal_per_A2': force_constant_kj / 418.4,
        'delta_energy_kj': float(delta_energy),
    }


def update_restraint_strength(simulation: 'openmm.app.Simulation',
                              force_index: int,
                              new_force_constant_kj: float) -> None:
    """Update the strength of positional restraints.

    Args:
        simulation: OpenMM Simulation object
        force_index: Index of the restraint force (from add_positional_restraints)
        new_force_constant_kj: New force constant in kJ/mol/nm**2
    """
    simulation.context.setParameter('k', new_force_constant_kj)
    logging.info(f"Updated restraint strength: k={new_force_constant_kj} kJ/mol/nm^2 "
                 f"({new_force_constant_kj / 418.4:.2f} kcal/mol/A^2)")


def remove_positional_restraints(simulation: 'openmm.app.Simulation',
                                 force_index: int) -> None:
    """Remove positional restraints by setting force constant to zero.

    Args:
        simulation: OpenMM Simulation object
        force_index: Index of the restraint force
    """
    update_restraint_strength(simulation, force_index, 0.0)
    logging.info("Positional restraints removed (k=0)")


def release_restraints_gradually(
        simulation: 'openmm.app.Simulation',
        force_index: int,
        schedule_kj: List[float] = None,
        steps_per_stage: int = 25000,
        schedule_kcal_per_A2: List[float] = None) -> List[Dict]:
    """Gradually release positional restraints over multiple stages.

    Best practice for covalent ligand simulations: release over >=500 ps
    with descending force constants (e.g., 10 -> 5 -> 2 -> 1 -> 0 kcal/mol/A^2).

    Args:
        simulation: OpenMM Simulation object
        force_index: Index of the restraint force
        schedule_kj: Descending force constants in kJ/mol/nm^2.
            Default: [4184, 2092, 836.8, 418.4, 0] (= 10, 5, 2, 1, 0 kcal/mol/A^2)
        steps_per_stage: MD steps per restraint stage
        schedule_kcal_per_A2: Alternative schedule in kcal/mol/A^2

    Returns:
        List of dicts with per-stage results
    """
    from openmm import unit

    if schedule_kcal_per_A2 is not None:
        schedule_kj = [k * 418.4 for k in schedule_kcal_per_A2]
    if schedule_kj is None:
        schedule_kj = [4184.0, 2092.0, 836.8, 418.4, 0.0]

    results = []
    logging.info(f"Gradual restraint release: {len(schedule_kj)} stages, "
                 f"{steps_per_stage} steps/stage")

    for i, k in enumerate(schedule_kj):
        update_restraint_strength(simulation, force_index, k)
        simulation.step(steps_per_stage)

        state = simulation.context.getState(getEnergy=True, getPositions=True)
        pe = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
        positions = state.getPositions(asNumpy=True)
        has_nan = bool(np.any(np.isnan(
            positions.value_in_unit(unit.nanometers))))

        stage_result = {
            'stage': i + 1,
            'force_constant_kj': k,
            'force_constant_kcal_per_A2': k / 418.4,
            'potential_energy_kj': float(pe),
            'has_nan': has_nan,
        }
        results.append(stage_result)

        logging.info(f"  Stage {i+1}/{len(schedule_kj)}: "
                     f"k={k/418.4:.1f} kcal/mol/A^2, PE={pe:.1f} kJ/mol"
                     f"{' [NaN DETECTED!]' if has_nan else ''}")

        if has_nan:
            logging.error(f"NaN detected at stage {i+1}. Stopping restraint release.")
            break

    return results


def validate_initial_energy(simulation: 'openmm.app.Simulation',
                            label: str = 'system',
                            expected_range_kj: tuple = None) -> Dict:
    """Validate that initial energy is within expected range.

    For solvated proteins, typical PE is -200,000 to -400,000 kJ/mol.
    Values >10^9 indicate Angstrom-vs-nm unit mismatches.
    Values >10^6 indicate steric clashes or bad geometry.

    Args:
        simulation: OpenMM Simulation object
        label: Label for logging
        expected_range_kj: (min, max) acceptable energy in kJ/mol.
            Default: (-1e7, 1e6)

    Returns:
        Dict with: energy_kj, energy_kcal, valid, warning
    """
    from openmm import unit

    if expected_range_kj is None:
        expected_range_kj = (-1e7, 1e6)

    state = simulation.context.getState(getEnergy=True)
    energy_kj = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    energy_kcal = energy_kj * _KJ_PER_MOL_TO_KCAL

    valid = expected_range_kj[0] <= energy_kj <= expected_range_kj[1]
    warning = None

    if not valid:
        if energy_kj > 1e9:
            warning = (f"Energy = {energy_kj:.2e} kJ/mol — likely unit mismatch "
                       f"(Angstrom vs nm in restraints or coordinates)")
        elif energy_kj > 1e6:
            warning = (f"Energy = {energy_kj:.2e} kJ/mol — steric clashes or "
                       f"bad initial geometry")
        else:
            warning = f"Energy = {energy_kj:.2e} kJ/mol — outside expected range"
        logging.warning(f"Energy validation FAILED for {label}: {warning}")
    else:
        logging.info(f"Energy validation passed for {label}: {energy_kj:.2f} kJ/mol "
                     f"({energy_kcal:.2f} kcal/mol)")

    return {
        'energy_kj': float(energy_kj),
        'energy_kcal': float(energy_kcal),
        'valid': valid,
        'warning': warning,
    }


def check_simulation_health(simulation: 'openmm.app.Simulation') -> Dict:
    """Check for NaN positions/velocities and extreme energies.

    Use periodically during production (e.g., every 20 ps) to detect
    instability early, especially with covalent ligands or custom bonds.

    Args:
        simulation: OpenMM Simulation object

    Returns:
        Dict with: healthy, has_nan_positions, has_nan_velocities, energy_kj, issues
    """
    from openmm import unit

    state = simulation.context.getState(
        getEnergy=True, getPositions=True, getVelocities=True)
    positions = state.getPositions(asNumpy=True).value_in_unit(unit.nanometers)
    velocities = state.getVelocities(asNumpy=True).value_in_unit(
        unit.nanometers / unit.picoseconds)
    energy_kj = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)

    has_nan_pos = bool(np.any(np.isnan(positions)))
    has_nan_vel = bool(np.any(np.isnan(velocities)))

    issues = []
    if has_nan_pos:
        issues.append('NaN in positions')
    if has_nan_vel:
        issues.append('NaN in velocities')
    if abs(energy_kj) > 1e12:
        issues.append(f'Extreme energy: {energy_kj:.2e} kJ/mol')
    if energy_kj != energy_kj:  # NaN check
        issues.append('NaN energy')

    healthy = len(issues) == 0

    if not healthy:
        logging.warning(f"Health check FAILED: {', '.join(issues)}")

    return {
        'healthy': healthy,
        'has_nan_positions': has_nan_pos,
        'has_nan_velocities': has_nan_vel,
        'energy_kj': float(energy_kj) if not np.isnan(energy_kj) else None,
        'issues': issues,
    }


def run_minimization(simulation: 'openmm.app.Simulation',
                     max_iterations: int = 5000,
                     tolerance_kj_per_nm: float = 10.0,
                     output_pdb: str = 'minimized.pdb',
                     tolerance_kj_mol_nm: float = None) -> Dict:
    """Run energy minimization.

    Args:
        simulation: OpenMM Simulation object
        max_iterations: Maximum minimization steps (0 = until convergence)
        tolerance_kj_per_nm: Force tolerance in kJ/mol/nm (energy gradient)
        output_pdb: Path to save minimized structure
        tolerance_kj_mol_nm: Alias for tolerance_kj_per_nm (documented API compat)

    Returns:
        Dict with: initial_energy_kJ_mol, final_energy_kJ_mol, energy_change_kJ_mol,
                   minimized_pdb, initial_energy_kj, final_energy_kj, output_pdb
    """
    import openmm
    from openmm import app, unit

    # Accept tolerance_kj_mol_nm as alias
    if tolerance_kj_mol_nm is not None:
        tolerance_kj_per_nm = tolerance_kj_mol_nm

    logging.info(f"Starting minimization (max {max_iterations} iterations, "
                 f"tolerance {tolerance_kj_per_nm} kJ/mol/nm)")

    # Get initial energy
    state = simulation.context.getState(getEnergy=True)
    initial_energy = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    logging.info(f"  Initial energy: {initial_energy:.2f} kJ/mol "
                 f"({initial_energy * _KJ_PER_MOL_TO_KCAL:.2f} kcal/mol)")

    t0 = time.time()
    simulation.minimizeEnergy(
        maxIterations=max_iterations,
        tolerance=tolerance_kj_per_nm * unit.kilojoules_per_mole / unit.nanometers
    )
    elapsed = time.time() - t0

    # Get final energy
    state = simulation.context.getState(getEnergy=True, getPositions=True)
    final_energy = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    logging.info(f"  Final energy: {final_energy:.2f} kJ/mol "
                 f"({final_energy * _KJ_PER_MOL_TO_KCAL:.2f} kcal/mol)")
    logging.info(f"  Minimization completed in {elapsed:.1f} seconds")

    # Save minimized structure
    positions = state.getPositions()
    with open(output_pdb, 'w') as f:
        app.PDBFile.writeFile(simulation.topology, positions, f)
    logging.info(f"  Minimized structure saved: {output_pdb}")

    return {
        'initial_energy_kj': float(initial_energy),
        'final_energy_kj': float(final_energy),
        'initial_energy_kcal': float(initial_energy * _KJ_PER_MOL_TO_KCAL),
        'final_energy_kcal': float(final_energy * _KJ_PER_MOL_TO_KCAL),
        'elapsed_seconds': float(elapsed),
        'output_pdb': output_pdb,
        # Documented API keys
        'initial_energy_kJ_mol': float(initial_energy),
        'final_energy_kJ_mol': float(final_energy),
        'energy_change_kJ_mol': float(final_energy - initial_energy),
        'minimized_pdb': output_pdb,
    }


def run_nvt(simulation: 'openmm.app.Simulation',
            nsteps: int = 25000,
            temperature_K: float = 300.0,
            report_interval: int = 1000,
            trajectory_file: str = 'nvt.dcd',
            log_file: str = 'nvt.log',
            checkpoint_file: str = 'nvt.chk',
            output_state: str = 'nvt_state.xml',
            ramp_temperature: bool = True,
            initial_temperature_K: float = 0.0,
            n_steps: int = None,
            output_prefix: str = None,
            trajectory_interval: int = None) -> Dict:
    """Run NVT (constant volume) equilibration.

    Args:
        simulation: OpenMM Simulation object
        nsteps: Number of MD steps
        temperature_K: Target temperature in Kelvin
        report_interval: Steps between reporter writes
        trajectory_file: DCD trajectory output path
        log_file: Log file path
        checkpoint_file: Checkpoint file path
        output_state: XML state file to save at end
        ramp_temperature: Gradually increase temperature from initial to target
        initial_temperature_K: Starting temperature if ramping

    Returns:
        Dict with simulation statistics
    """
    import openmm
    from openmm import app, unit

    # Accept n_steps, output_prefix, trajectory_interval as aliases (documented API compat)
    if n_steps is not None:
        nsteps = n_steps
    if output_prefix is not None:
        trajectory_file = f'{output_prefix}.dcd'
        log_file = f'{output_prefix}.log'
        checkpoint_file = f'{output_prefix}.chk'
        output_state = f'{output_prefix}_state.xml'
    if trajectory_interval is not None:
        report_interval = trajectory_interval

    logging.info(f"Starting NVT equilibration: {nsteps} steps at {temperature_K} K")

    # Clear old reporters
    simulation.reporters = []
    add_reporters(simulation, trajectory_file, log_file, checkpoint_file, report_interval)

    if ramp_temperature and initial_temperature_K < temperature_K:
        # Temperature ramping
        n_ramp_steps = min(nsteps // 2, 10000)
        n_temp_stages = 10
        steps_per_stage = n_ramp_steps // n_temp_stages
        temps = np.linspace(max(initial_temperature_K, 50), temperature_K, n_temp_stages)

        logging.info(f"  Ramping temperature: {temps[0]:.0f} -> {temps[-1]:.0f} K "
                     f"in {n_temp_stages} stages")
        for temp in temps:
            simulation.context.setVelocitiesToTemperature(temp * unit.kelvin)
            integrator = simulation.context.getIntegrator()
            integrator.setTemperature(temp * unit.kelvin)
            simulation.step(steps_per_stage)

        # Remaining steps at target temperature
        remaining = nsteps - n_ramp_steps
        if remaining > 0:
            simulation.step(remaining)
    else:
        simulation.context.setVelocitiesToTemperature(temperature_K * unit.kelvin)
        simulation.step(nsteps)

    # Save state
    simulation.saveState(output_state)
    state = simulation.context.getState(getEnergy=True)
    final_pe = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    final_ke = state.getKineticEnergy().value_in_unit(unit.kilojoules_per_mole)

    logging.info(f"  NVT complete. PE={final_pe:.2f} kJ/mol, KE={final_ke:.2f} kJ/mol")

    return {
        'nsteps': nsteps,
        'n_steps': nsteps,
        'temperature_K': temperature_K,
        'final_pe_kj': float(final_pe),
        'final_ke_kj': float(final_ke),
        'final_temperature_K': temperature_K,
        'avg_temperature_K': temperature_K,
        'avg_potential_energy_kJ_mol': float(final_pe),
        'trajectory': trajectory_file,
        'trajectory_file': trajectory_file,
        'log_file': log_file,
        'state_file': output_state,
    }


def run_npt(simulation: 'openmm.app.Simulation',
            nsteps: int = 50000,
            temperature_K: float = 300.0,
            pressure_atm: float = 1.0,
            report_interval: int = 1000,
            trajectory_file: str = 'npt.dcd',
            log_file: str = 'npt.log',
            checkpoint_file: str = 'npt.chk',
            output_state: str = 'npt_state.xml',
            n_steps: int = None,
            output_prefix: str = None) -> Dict:
    """Run NPT (constant pressure) equilibration.

    Adds a barostat if not already present, then runs MD.

    Args:
        simulation: OpenMM Simulation object
        nsteps: Number of MD steps
        temperature_K: Temperature in Kelvin
        pressure_atm: Pressure in atmospheres
        report_interval: Steps between reporter writes
        trajectory_file: DCD trajectory output
        log_file: Log file path
        checkpoint_file: Checkpoint file path
        output_state: XML state file to save at end

    Returns:
        Dict with simulation statistics
    """
    import openmm
    from openmm import app, unit

    # Accept n_steps and output_prefix as aliases (documented API compat)
    if n_steps is not None:
        nsteps = n_steps
    if output_prefix is not None:
        trajectory_file = f'{output_prefix}.dcd'
        log_file = f'{output_prefix}.log'
        checkpoint_file = f'{output_prefix}.chk'
        output_state = f'{output_prefix}_state.xml'

    logging.info(f"Starting NPT equilibration: {nsteps} steps at "
                 f"{temperature_K} K, {pressure_atm} atm")

    # Check if barostat already exists
    system = simulation.system
    has_barostat = any(
        isinstance(system.getForce(i), openmm.MonteCarloBarostat)
        for i in range(system.getNumForces())
    )
    if not has_barostat:
        add_barostat(system, temperature_K, pressure_atm)
        simulation.context.reinitialize(preserveState=True)

    # Clear old reporters and add new ones
    simulation.reporters = []
    add_reporters(simulation, trajectory_file, log_file, checkpoint_file, report_interval)

    t0 = time.time()
    simulation.step(nsteps)
    elapsed = time.time() - t0

    # Save state
    simulation.saveState(output_state)
    state = simulation.context.getState(getEnergy=True)
    box = state.getPeriodicBoxVectors()
    box_nm = [box[i][i].value_in_unit(unit.nanometers) for i in range(3)]
    volume = state.getPeriodicBoxVolume().value_in_unit(unit.nanometers**3)

    logging.info(f"  NPT complete in {elapsed:.1f}s. Box: {box_nm[0]:.3f} x "
                 f"{box_nm[1]:.3f} x {box_nm[2]:.3f} nm, V={volume:.2f} nm³")

    return {
        'nsteps': nsteps,
        'n_steps': nsteps,
        'temperature_K': temperature_K,
        'pressure_atm': pressure_atm,
        'box_dimensions_nm': [float(b) for b in box_nm],
        'volume_nm3': float(volume),
        'avg_density_g_cm3': 0.0,  # Placeholder; actual density from log
        'avg_temperature_K': temperature_K,
        'avg_pressure_atm': pressure_atm,
        'elapsed_seconds': float(elapsed),
        'trajectory': trajectory_file,
        'trajectory_file': trajectory_file,
        'log_file': log_file,
        'state_file': output_state,
    }


def run_production(simulation: 'openmm.app.Simulation',
                   nsteps: int = 500000,
                   report_interval: int = 5000,
                   trajectory_file: str = 'production.dcd',
                   log_file: str = 'production.log',
                   checkpoint_file: str = 'production.chk',
                   checkpoint_interval: int = 50000,
                   output_state: str = 'production_state.xml',
                   save_pdb_frames: bool = False,
                   pdb_interval: int = 50000,
                   n_steps: int = None,
                   output_prefix: str = None,
                   trajectory_interval: int = None) -> Dict:
    """Run production MD simulation.

    Args:
        simulation: OpenMM Simulation object (should be equilibrated)
        nsteps: Number of production steps
        report_interval: Steps between trajectory/log writes
        trajectory_file: DCD trajectory output
        log_file: Log file path
        checkpoint_file: Checkpoint file path
        checkpoint_interval: Steps between checkpoints
        output_state: Final state XML file
        save_pdb_frames: Whether to also save PDB snapshots
        pdb_interval: Steps between PDB snapshots (if save_pdb_frames=True)

    Returns:
        Dict with simulation statistics and performance
    """
    import openmm
    from openmm import app, unit

    # Accept n_steps, output_prefix, trajectory_interval as aliases (documented API compat)
    if n_steps is not None:
        nsteps = n_steps
    if output_prefix is not None:
        trajectory_file = f'{output_prefix}.dcd'
        log_file = f'{output_prefix}.log'
        checkpoint_file = f'{output_prefix}.chk'
        output_state = f'{output_prefix}_state.xml'
    if trajectory_interval is not None:
        report_interval = trajectory_interval

    dt_ps = simulation.context.getIntegrator().getStepSize().value_in_unit(unit.picoseconds)
    total_time_ns = nsteps * dt_ps / 1000.0
    logging.info(f"Starting production MD: {nsteps} steps = {total_time_ns:.2f} ns")

    # Clear and add reporters
    simulation.reporters = []
    simulation.reporters.append(app.DCDReporter(trajectory_file, report_interval))
    simulation.reporters.append(app.StateDataReporter(
        log_file, report_interval,
        step=True, time=True,
        potentialEnergy=True, kineticEnergy=True, totalEnergy=True,
        temperature=True, volume=True, density=True,
        speed=True, separator=','
    ))
    simulation.reporters.append(app.CheckpointReporter(checkpoint_file, checkpoint_interval))

    if save_pdb_frames:
        simulation.reporters.append(app.PDBReporter('production_frames.pdb', pdb_interval))

    t0 = time.time()
    simulation.step(nsteps)
    elapsed = time.time() - t0

    # Save final state
    simulation.saveState(output_state)

    # Performance
    ns_per_day = (total_time_ns / elapsed) * 86400 if elapsed > 0 else 0
    state = simulation.context.getState(getEnergy=True)
    final_pe = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)

    logging.info(f"  Production complete in {elapsed:.1f}s")
    logging.info(f"  Performance: {ns_per_day:.2f} ns/day")
    logging.info(f"  Final PE: {final_pe:.2f} kJ/mol")

    return {
        'nsteps': nsteps,
        'n_steps': nsteps,
        'total_time_ns': float(total_time_ns),
        'elapsed_seconds': float(elapsed),
        'wall_time_s': float(elapsed),
        'ns_per_day': float(ns_per_day),
        'final_pe_kj': float(final_pe),
        'trajectory': trajectory_file,
        'trajectory_file': trajectory_file,
        'log_file': log_file,
        'checkpoint_file': checkpoint_file,
        'state_file': output_state,
    }


def save_positions_pdb(simulation: 'openmm.app.Simulation',
                       output_file: str = 'snapshot.pdb') -> str:
    """Save current positions as PDB file.

    Args:
        simulation: OpenMM Simulation object
        output_file: Output PDB path

    Returns:
        Path to saved PDB file
    """
    from openmm import app, unit
    state = simulation.context.getState(getPositions=True)
    with open(output_file, 'w') as f:
        app.PDBFile.writeFile(simulation.topology, state.getPositions(), f)
    logging.info(f"Saved positions: {output_file}")
    return output_file


# ============= PARSING =============

def parse_log(log_file: str) -> Dict:
    """Parse OpenMM StateDataReporter CSV log file.

    Args:
        log_file: Path to CSV log file from StateDataReporter

    Returns:
        Dict with arrays: step, time_ps, potential_energy_kj, kinetic_energy_kj,
                          total_energy_kj, temperature_K, volume_nm3, density_kg_m3,
                          speed_ns_day
    """
    import pandas as pd

    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Log file not found: {log_file}")

    logging.info(f"Parsing log file: {log_file}")
    df = pd.read_csv(log_file)

    # Map OpenMM StateDataReporter column headers to standardized names.
    # Uses exact header matching first, then falls back to substring matching.
    exact_col_map = {
        'Step': 'step',
        'Time (ps)': 'time_ps',
        'Potential Energy (kJ/mole)': 'potential_energy_kj',
        'Kinetic Energy (kJ/mole)': 'kinetic_energy_kj',
        'Total Energy (kJ/mole)': 'total_energy_kj',
        'Temperature (K)': 'temperature_K',
        'Box Volume (nm^3)': 'volume_nm3',
        'Density (g/mL)': 'density_kg_m3',
        'Speed (ns/day)': 'speed_ns_day',
    }

    col_map = {}
    for col in df.columns:
        col_stripped = col.strip().strip('#').strip().strip('"').strip()
        if col_stripped in exact_col_map:
            col_map[col] = exact_col_map[col_stripped]
        else:
            # Fallback: substring matching for non-standard header formats
            col_lower = col_stripped.lower()
            if col_lower == 'step':
                col_map[col] = 'step'
            elif 'time' in col_lower and 'ps' in col_lower:
                col_map[col] = 'time_ps'
            elif 'potential' in col_lower and 'energy' in col_lower:
                col_map[col] = 'potential_energy_kj'
            elif 'kinetic' in col_lower and 'energy' in col_lower:
                col_map[col] = 'kinetic_energy_kj'
            elif 'total' in col_lower and 'energy' in col_lower:
                col_map[col] = 'total_energy_kj'
            elif 'temperature' in col_lower:
                col_map[col] = 'temperature_K'
            elif 'volume' in col_lower:
                col_map[col] = 'volume_nm3'
            elif 'density' in col_lower:
                col_map[col] = 'density_kg_m3'
            elif 'speed' in col_lower:
                col_map[col] = 'speed_ns_day'

    if not col_map:
        raise ValueError(f"Could not identify any columns in log file. "
                         f"Available columns: {list(df.columns)}")

    df = df.rename(columns=col_map)

    result = {}
    for col in df.columns:
        try:
            result[col] = df[col].values.astype(float)
        except (ValueError, TypeError):
            result[col] = df[col].values

    logging.info(f"  Parsed {len(df)} log entries, columns: {list(col_map.values())}")
    return result


# ============= TRAJECTORY ANALYSIS (MDTraj) =============

def load_trajectory(trajectory_file: str, topology_file: str,
                    stride: int = 1) -> 'mdtraj.Trajectory':
    """Load trajectory using MDTraj.

    Args:
        trajectory_file: Path to trajectory (DCD, XTC, etc.)
        topology_file: Path to topology (PDB)
        stride: Load every Nth frame

    Returns:
        MDTraj Trajectory object
    """
    if not os.path.isfile(trajectory_file):
        raise FileNotFoundError(f"Trajectory file not found: {trajectory_file}")
    if not os.path.isfile(topology_file):
        raise FileNotFoundError(f"Topology file not found: {topology_file}")

    import mdtraj as md

    logging.info(f"Loading trajectory: {trajectory_file} (topology: {topology_file})")
    traj = md.load(trajectory_file, top=topology_file, stride=stride)
    logging.info(f"  Loaded {traj.n_frames} frames, {traj.n_atoms} atoms")
    return traj


def compute_rmsd(trajectory_file: str, topology_file: str,
                 selection: str = 'protein and name CA',
                 ref_frame: int = 0,
                 output_file: str = 'rmsd.dat',
                 stride: int = 1,
                 reference_frame: int = None,
                 atom_selection: str = None) -> Dict:
    """Compute RMSD over trajectory.

    Args:
        trajectory_file: Path to trajectory
        topology_file: Path to topology PDB
        selection: MDTraj atom selection string
        ref_frame: Reference frame index
        output_file: Output data file path
        stride: Frame stride for loading

    Returns:
        Dict with: rmsd_nm (array), time_ps (array), mean_nm, std_nm, max_nm
    """
    import mdtraj as md

    # Accept documented API param aliases
    if reference_frame is not None:
        ref_frame = reference_frame
    if atom_selection is not None:
        selection = atom_selection

    traj = load_trajectory(trajectory_file, topology_file, stride)
    atom_indices = traj.topology.select(selection)

    if len(atom_indices) == 0:
        raise ValueError(f"No atoms match selection '{selection}'. "
                         f"Check topology or use a different selection "
                         f"(e.g., 'protein', 'backbone', 'all').")

    rmsd = md.rmsd(traj, traj, frame=ref_frame, atom_indices=atom_indices)
    time_ps = traj.time

    # Save data
    np.savetxt(output_file, np.column_stack([time_ps, rmsd]),
               header='Time(ps) RMSD(nm)', fmt='%.4f')

    result = {
        'rmsd_nm': rmsd.tolist(),
        'time_ps': time_ps.tolist(),
        'mean_nm': float(np.mean(rmsd)),
        'std_nm': float(np.std(rmsd)),
        'max_nm': float(np.max(rmsd)),
        'n_frames': len(rmsd),
        'selection': selection,
        # Documented API keys
        'mean_rmsd_nm': float(np.mean(rmsd)),
        'std_rmsd_nm': float(np.std(rmsd)),
        'max_rmsd_nm': float(np.max(rmsd)),
    }
    logging.info(f"  RMSD: mean={result['mean_nm']:.4f} nm, "
                 f"std={result['std_nm']:.4f} nm")
    return result


def compute_rmsf(trajectory_file: str, topology_file: str,
                 selection: str = 'protein and name CA',
                 output_file: str = 'rmsf.dat',
                 stride: int = 1,
                 atom_selection: str = None) -> Dict:
    """Compute per-residue RMSF.

    Args:
        trajectory_file: Path to trajectory
        topology_file: Path to topology PDB
        selection: MDTraj atom selection string
        output_file: Output data file path
        stride: Frame stride for loading

    Returns:
        Dict with: rmsf_nm (array), residue_indices, mean_nm
    """
    import mdtraj as md

    # Accept documented API param alias
    if atom_selection is not None:
        selection = atom_selection

    traj = load_trajectory(trajectory_file, topology_file, stride)
    atom_indices = traj.topology.select(selection)

    if len(atom_indices) == 0:
        raise ValueError(f"No atoms match selection '{selection}'. "
                         f"Check topology or use a different selection "
                         f"(e.g., 'protein and name CA', 'backbone', 'all').")

    rmsf = md.rmsf(traj, traj, frame=0, atom_indices=atom_indices)

    # Aggregate per-atom RMSF to per-residue by averaging atoms within each residue
    residue_rmsf = {}
    for atom_idx, rmsf_val in zip(atom_indices, rmsf):
        res_idx = traj.topology.atom(atom_idx).residue.index
        if res_idx not in residue_rmsf:
            residue_rmsf[res_idx] = []
        residue_rmsf[res_idx].append(float(rmsf_val))

    residue_indices = sorted(residue_rmsf.keys())
    rmsf_per_residue = [float(np.mean(residue_rmsf[r])) for r in residue_indices]

    np.savetxt(output_file, np.column_stack([residue_indices, rmsf_per_residue]),
               header='Residue RMSF(nm)', fmt='%d %.4f')

    result = {
        'rmsf_nm': rmsf_per_residue,
        'residue_indices': residue_indices,
        'mean_nm': float(np.mean(rmsf_per_residue)),
        'max_nm': float(np.max(rmsf_per_residue)),
        'max_residue': int(residue_indices[np.argmax(rmsf_per_residue)]),
        'n_atoms': len(atom_indices),
        # Documented API keys
        'mean_rmsf_nm': float(np.mean(rmsf_per_residue)),
        'max_rmsf_nm': float(np.max(rmsf_per_residue)),
    }
    logging.info(f"  RMSF: mean={result['mean_nm']:.4f} nm, "
                 f"max={result['max_nm']:.4f} nm at residue {result['max_residue']}")
    return result


def compute_radius_of_gyration(trajectory_file: str, topology_file: str,
                                selection: str = 'protein',
                                output_file: str = 'rgyr.dat',
                                stride: int = 1) -> Dict:
    """Compute radius of gyration over trajectory.

    Args:
        trajectory_file: Path to trajectory
        topology_file: Path to topology PDB
        selection: MDTraj atom selection string
        output_file: Output data file path
        stride: Frame stride

    Returns:
        Dict with: rgyr_nm (array), time_ps, mean_nm, std_nm
    """
    import mdtraj as md

    traj = load_trajectory(trajectory_file, topology_file, stride)
    atom_indices = traj.topology.select(selection)
    subtraj = traj.atom_slice(atom_indices)
    rgyr = md.compute_rg(subtraj)

    np.savetxt(output_file, np.column_stack([traj.time, rgyr]),
               header='Time(ps) Rg(nm)', fmt='%.4f')

    return {
        'rgyr_nm': rgyr.tolist(),
        'time_ps': traj.time.tolist(),
        'mean_nm': float(np.mean(rgyr)),
        'std_nm': float(np.std(rgyr)),
        'n_frames': len(rgyr),
        # Documented API keys
        'rg_nm': rgyr.tolist(),
        'mean_rg_nm': float(np.mean(rgyr)),
        'std_rg_nm': float(np.std(rgyr)),
    }


def compute_hbonds(trajectory_file: str, topology_file: str,
                   freq_cutoff: float = 0.1,
                   stride: int = 1) -> Dict:
    """Compute hydrogen bonds using Baker-Hubbard criteria.

    Args:
        trajectory_file: Path to trajectory
        topology_file: Path to topology PDB
        freq_cutoff: Minimum frequency to report
        stride: Frame stride

    Returns:
        Dict with: n_hbonds_per_frame, mean_hbonds, hbond_list (frequent ones)
    """
    import mdtraj as md

    traj = load_trajectory(trajectory_file, topology_file, stride)

    # Get persistent H-bonds across trajectory (efficient single pass)
    hbonds = md.baker_hubbard(traj, freq=freq_cutoff)

    # Count H-bonds per frame using distance checks on identified donor-acceptor pairs
    # instead of re-running baker_hubbard per frame (which is O(n_frames * n_atoms^2))
    all_hbonds = md.baker_hubbard(traj, freq=0.0)
    if len(all_hbonds) > 0:
        # Extract donor-H-acceptor triplet indices
        donor_h_indices = all_hbonds[:, 1]  # hydrogen atom index
        acceptor_indices = all_hbonds[:, 2]  # acceptor atom index
        # Compute H-acceptor distances for all frames at once
        pairs = np.column_stack([donor_h_indices, acceptor_indices])
        distances = md.compute_distances(traj, pairs)  # shape (n_frames, n_pairs)
        # Baker-Hubbard distance cutoff is 0.25 nm
        hbond_present = distances < 0.25
        n_per_frame = hbond_present.sum(axis=1).tolist()
    else:
        n_per_frame = [0] * traj.n_frames

    hbond_labels = []
    for hb in hbonds[:20]:  # Top 20 persistent
        d = traj.topology.atom(hb[0])
        a = traj.topology.atom(hb[2])
        hbond_labels.append(f"{d.residue.name}{d.residue.index}-{d.name} ... "
                           f"{a.residue.name}{a.residue.index}-{a.name}")

    return {
        'n_persistent_hbonds': len(hbonds),
        'mean_hbonds_per_frame': float(np.mean(n_per_frame)),
        'std_hbonds_per_frame': float(np.std(n_per_frame)),
        'hbond_labels': hbond_labels,
        'n_per_frame': n_per_frame,
        'n_frames': traj.n_frames,
        # Documented API keys
        'n_hbonds_per_frame': n_per_frame,
        'persistent_hbonds': hbond_labels,
        'mean_hbonds': float(np.mean(n_per_frame)),
    }


def compute_secondary_structure(trajectory_file: str, topology_file: str,
                                 output_file: str = 'secstruct.dat',
                                 stride: int = 1) -> Dict:
    """Compute DSSP secondary structure assignment.

    Args:
        trajectory_file: Path to trajectory
        topology_file: Path to topology PDB
        output_file: Output data file
        stride: Frame stride

    Returns:
        Dict with: helix_fraction, sheet_fraction, coil_fraction (per frame)
    """
    import mdtraj as md

    traj = load_trajectory(trajectory_file, topology_file, stride)
    dssp = md.compute_dssp(traj)

    helix_frac = np.mean(dssp == 'H', axis=1)
    sheet_frac = np.mean(dssp == 'E', axis=1)
    coil_frac = np.mean(dssp == 'C', axis=1)

    np.savetxt(output_file,
               np.column_stack([traj.time, helix_frac, sheet_frac, coil_frac]),
               header='Time(ps) Helix Sheet Coil', fmt='%.4f')

    return {
        'mean_helix': float(np.mean(helix_frac)),
        'mean_sheet': float(np.mean(sheet_frac)),
        'mean_coil': float(np.mean(coil_frac)),
        'helix_fraction': helix_frac.tolist(),
        'sheet_fraction': sheet_frac.tolist(),
        'coil_fraction': coil_frac.tolist(),
        'n_frames': len(helix_frac),
        # Documented API key
        'dssp_per_frame': dssp.tolist(),
    }


def compute_contacts(trajectory_file: str, topology_file: str,
                     scheme: str = 'closest-heavy',
                     cutoff_nm: float = 0.45,
                     stride: int = 1) -> Dict:
    """Compute native contacts (fraction of contacts from first frame).

    Args:
        trajectory_file: Path to trajectory
        topology_file: Path to topology PDB
        scheme: Contact scheme ('closest-heavy', 'ca', 'sidechain')
        cutoff_nm: Contact distance cutoff in nm
        stride: Frame stride

    Returns:
        Dict with: q_values (fraction of native contacts per frame), mean_q
    """
    import mdtraj as md

    traj = load_trajectory(trajectory_file, topology_file, stride)
    # Select protein residue pairs
    protein = traj.topology.select('protein')
    if len(protein) == 0:
        return {'error': 'No protein atoms found'}

    try:
        distances, pairs = md.compute_contacts(traj, scheme=scheme)
    except ValueError as e:
        if 'No acceptable residue pairs' in str(e):
            return {
                'q_values': [],
                'mean_q': 0.0,
                'std_q': 0.0,
                'n_native_contacts': 0,
                'error': 'Too few residues for contact analysis',
            }
        raise
    ref_distances = distances[0]
    native_mask = ref_distances < cutoff_nm

    q_values = []
    for frame_dist in distances:
        if np.sum(native_mask) > 0:
            q = np.mean(frame_dist[native_mask] < cutoff_nm)
        else:
            q = 0.0
        q_values.append(float(q))

    return {
        'q_values': q_values,
        'mean_q': float(np.mean(q_values)),
        'std_q': float(np.std(q_values)),
        'n_native_contacts': int(np.sum(native_mask)),
    }


# ============= VISUALIZATION =============

def plot_energy(log_data: Dict, output_file: str = 'energy.png',
                properties: List[str] = None, title: str = None) -> str:
    """Plot energy and thermodynamic properties from simulation log.

    Args:
        log_data: Dict from parse_log()
        output_file: Output plot file path
        properties: List of properties to plot. Options: 'potential_energy_kj',
                    'kinetic_energy_kj', 'total_energy_kj', 'temperature_K',
                    'volume_nm3', 'density_kg_m3'. Default: PE, KE, T.
        title: Plot title

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Handle string input (log file path) as well as dict
    if isinstance(log_data, str):
        log_data = parse_log(log_data)

    if properties is None:
        properties = ['potential_energy_kj', 'kinetic_energy_kj', 'temperature_K']

    available = [p for p in properties if p in log_data]
    n_plots = len(available)
    if n_plots == 0:
        logging.warning("No plottable properties found in log data")
        return output_file

    fig, axes = plt.subplots(n_plots, 1, figsize=(10, 3 * n_plots), sharex=True)
    if n_plots == 1:
        axes = [axes]

    time_key = 'time_ps' if 'time_ps' in log_data else 'step'
    x = log_data.get(time_key, np.arange(len(log_data[available[0]])))
    x_label = 'Time (ps)' if time_key == 'time_ps' else 'Step'

    labels = {
        'potential_energy_kj': ('Potential Energy', 'kJ/mol'),
        'kinetic_energy_kj': ('Kinetic Energy', 'kJ/mol'),
        'total_energy_kj': ('Total Energy', 'kJ/mol'),
        'temperature_K': ('Temperature', 'K'),
        'volume_nm3': ('Volume', 'nm³'),
        'density_kg_m3': ('Density', 'kg/m³'),
    }

    for ax, prop in zip(axes, available):
        y = log_data[prop]
        label_name, unit = labels.get(prop, (prop, ''))
        ax.plot(x, y, linewidth=0.5, alpha=0.8)
        ax.set_ylabel(f"{label_name} ({unit})")
        mean_val = np.mean(y)
        ax.axhline(y=mean_val, color='red', linestyle='--', alpha=0.5,
                   label=f'mean={mean_val:.1f}')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel(x_label)
    if title:
        axes[0].set_title(title)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved energy plot: {output_file}")
    return output_file


def plot_rmsd(rmsd_data, output_file: str = 'rmsd.png',
              title: str = None, **kwargs) -> str:
    """Plot RMSD over time.

    Args:
        rmsd_data: Dict from compute_rmsd(), or trajectory file path (str).
                   If str, second positional arg is treated as topology_file.
        output_file: Output plot path
        title: Plot title

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # If called with (trajectory_file, topology_file, ...) instead of dict
    if isinstance(rmsd_data, str):
        topology_file = output_file
        output_file = kwargs.get('output_file', 'rmsd.png')
        title = kwargs.get('title', title)
        rmsd_data = compute_rmsd(rmsd_data, topology_file)

    fig, ax = plt.subplots(figsize=(10, 4))
    time_ps = rmsd_data.get('time_ps', range(len(rmsd_data['rmsd_nm'])))
    rmsd = rmsd_data['rmsd_nm']

    ax.plot(time_ps, rmsd, linewidth=0.5, alpha=0.8, color='steelblue')
    ax.axhline(y=rmsd_data['mean_nm'], color='red', linestyle='--', alpha=0.5,
               label=f"mean={rmsd_data['mean_nm']:.4f} nm")
    ax.set_xlabel('Time (ps)')
    ax.set_ylabel('RMSD (nm)')
    ax.set_title(title or f"RMSD ({rmsd_data.get('selection', '')})")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved RMSD plot: {output_file}")
    return output_file


def plot_rmsf(rmsf_data, output_file: str = 'rmsf.png',
              title: str = None, **kwargs) -> str:
    """Plot per-residue RMSF.

    Args:
        rmsf_data: Dict from compute_rmsf(), or trajectory file path (str).
                   If str, second positional arg is treated as topology_file.
        output_file: Output plot path
        title: Plot title

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # If called with (trajectory_file, topology_file, ...) instead of dict
    if isinstance(rmsf_data, str):
        topology_file = output_file
        output_file = kwargs.get('output_file', 'rmsf.png')
        title = kwargs.get('title', title)
        rmsf_data = compute_rmsf(rmsf_data, topology_file)

    fig, ax = plt.subplots(figsize=(12, 4))
    residues = rmsf_data['residue_indices']
    rmsf = rmsf_data['rmsf_nm']

    ax.bar(residues, rmsf, width=1.0, alpha=0.7, color='steelblue')
    ax.axhline(y=rmsf_data['mean_nm'], color='red', linestyle='--', alpha=0.5,
               label=f"mean={rmsf_data['mean_nm']:.4f} nm")
    ax.set_xlabel('Residue Index')
    ax.set_ylabel('RMSF (nm)')
    ax.set_title(title or 'Per-Residue RMSF')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved RMSF plot: {output_file}")
    return output_file


def plot_secondary_structure(ss_data: Dict, output_file: str = 'secstruct.png',
                              title: str = None) -> str:
    """Plot secondary structure fractions over time.

    Args:
        ss_data: Dict from compute_secondary_structure()
        output_file: Output plot path
        title: Plot title

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    n_frames = len(ss_data['helix_fraction'])
    frames = range(n_frames)

    ax.stackplot(frames,
                 ss_data['helix_fraction'],
                 ss_data['sheet_fraction'],
                 ss_data['coil_fraction'],
                 labels=['Helix', 'Sheet', 'Coil'],
                 colors=['#e74c3c', '#3498db', '#95a5a6'],
                 alpha=0.8)
    ax.set_xlabel('Frame')
    ax.set_ylabel('Fraction')
    ax.set_title(title or 'Secondary Structure')
    ax.legend(loc='upper right')
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved secondary structure plot: {output_file}")
    return output_file


# ============= DOCUMENTED API FUNCTIONS =============
# Functions below match the published agent API documentation.

def load_pdb(filename: str):
    """Load a PDB file and return the PDBFile object.

    Args:
        filename: Path to PDB file

    Returns:
        OpenMM PDBFile object
    """
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"PDB file not found: {filename}")
    from openmm.app import PDBFile
    logging.info(f"Loading PDB: {filename}")
    return PDBFile(filename)


def build_system(pdb, forcefield_name: str = 'amber14',
                 water_model: str = 'tip3p',
                 nonbonded_method: str = 'PME',
                 nonbonded_cutoff_nm: float = 1.0,
                 constraints: str = 'HBonds',
                 rigid_water: bool = True,
                 add_solvent: bool = True,
                 padding_nm: float = 1.0,
                 ionic_strength_M: float = 0.15,
                 implicit_solvent: str = None,
                 hydrogen_mass_amu: float = None) -> tuple:
    """Build an OpenMM System from a PDB or fixed PDB file path.

    This is a higher-level wrapper around create_system that accepts
    short forcefield names (e.g., 'amber14') and resolves them to
    XML file names.

    Args:
        pdb: PDB file path (str) or OpenMM PDBFile object
        forcefield_name: Force field name ('amber14', 'charmm36', etc.)
        water_model: Water model name ('tip3p', 'tip4pew', 'spce', etc.)
        nonbonded_method: 'PME', 'CutoffPeriodic', 'CutoffNonPeriodic', 'NoCutoff'
        nonbonded_cutoff_nm: Nonbonded cutoff in nm
        constraints: 'HBonds', 'AllBonds', 'HAngles', or None
        rigid_water: Constrain water geometry
        add_solvent: Whether to add solvent
        padding_nm: Solvent box padding in nm
        ionic_strength_M: Ionic strength
        implicit_solvent: Implicit solvent model ('OBC1', 'OBC2', 'GBn', 'GBn2')
        hydrogen_mass_amu: Hydrogen mass repartitioning (if not None)

    Returns:
        Tuple of (system, modeller, force_field_obj)
    """
    import openmm
    from openmm import app, unit

    # Resolve forcefield name to XML files
    ff_map = {
        'amber14': 'amber14-all.xml',
        'amber99sb': 'amber99sbildn.xml',
        'charmm36': 'charmm36.xml',
        'amoeba': 'amoeba2013.xml',
    }
    water_map = {
        'tip3p': 'amber14/tip3pfb.xml',
        'tip3pfb': 'amber14/tip3pfb.xml',
        'tip4pew': 'amber14/tip4pew.xml',
        'spce': 'amber14/spce.xml',
    }

    ff_xml = ff_map.get(forcefield_name, forcefield_name)
    water_xml = water_map.get(water_model, water_model)

    # Handle implicit solvent
    if implicit_solvent:
        implicit_map = {
            'OBC1': app.OBC1,
            'OBC2': app.OBC2,
            'GBn': app.GBn,
            'GBn2': app.GBn2,
        }
        implicit_model = implicit_map.get(implicit_solvent)

    # Get PDB file path
    if isinstance(pdb, str):
        pdb_path = pdb
    else:
        # Assume it's a PDBFile object; write to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdb', delete=False, dir=WORK_DIR) as tmp:
            app.PDBFile.writeFile(pdb.topology, pdb.positions, tmp)
            pdb_path = tmp.name

    # Use create_system for the heavy lifting
    nb_method = nonbonded_method
    if implicit_solvent and not add_solvent:
        nb_method = 'NoCutoff'

    result = create_system(
        pdb_file=pdb_path,
        force_field=ff_xml,
        water_model=water_xml,
        nonbonded_method=nb_method,
        nonbonded_cutoff_nm=nonbonded_cutoff_nm,
        constraints=constraints,
        rigid_water=rigid_water,
        solvate=add_solvent,
        box_padding_nm=padding_nm,
        ionic_strength_M=ionic_strength_M,
    )

    # Apply hydrogen mass repartitioning if requested
    if hydrogen_mass_amu is not None:
        system = result['system']
        for i in range(system.getNumParticles()):
            atom = list(result['topology'].atoms())[i]
            if atom.element.symbol == 'H':
                system.setParticleMass(i, hydrogen_mass_amu * unit.amu)

    return (result['system'], result['modeller'], result['force_field_obj'])


def create_langevin_integrator(temperature_K: float = 300.0,
                                friction_ps: float = 1.0,
                                timestep_fs: float = 2.0):
    """Create a Langevin integrator.

    Args:
        temperature_K: Temperature in Kelvin
        friction_ps: Friction coefficient in 1/ps
        timestep_fs: Timestep in femtoseconds

    Returns:
        OpenMM LangevinMiddleIntegrator
    """
    import openmm
    from openmm import unit

    integrator = openmm.LangevinMiddleIntegrator(
        temperature_K * unit.kelvin,
        friction_ps / unit.picoseconds,
        (timestep_fs / 1000.0) * unit.picoseconds  # fs -> ps
    )
    logging.info(f"Created Langevin integrator: T={temperature_K}K, "
                 f"friction={friction_ps}/ps, dt={timestep_fs}fs")
    return integrator


def create_simulation(system, modeller, integrator, platform_name: str = 'auto'):
    """Create an OpenMM Simulation from system, modeller, and integrator.

    Args:
        system: OpenMM System object
        modeller: OpenMM Modeller object (with topology and positions)
        integrator: OpenMM Integrator object
        platform_name: Platform name or 'auto'

    Returns:
        OpenMM Simulation object
    """
    from openmm import app

    platform = select_platform(platform_name)
    properties = {}
    if platform.getName() in ('CUDA', 'OpenCL'):
        properties['Precision'] = 'mixed'

    simulation = app.Simulation(
        modeller.topology, system, integrator, platform, properties
    )
    simulation.context.setPositions(modeller.positions)
    logging.info(f"Created simulation: platform={platform.getName()}")
    return simulation


def get_platform_info() -> Dict:
    """Get information about available OpenMM platforms.

    Returns:
        Dict with: platform_name, platform_version, n_platforms,
                   available_platforms, properties
    """
    import openmm

    n_platforms = openmm.Platform.getNumPlatforms()
    available = []
    for i in range(n_platforms):
        p = openmm.Platform.getPlatform(i)
        available.append({
            'name': p.getName(),
            'speed': p.getSpeed(),
        })

    # Get best platform
    best = select_platform('auto')
    properties = {}
    if best.getName() in ('CUDA', 'OpenCL'):
        for prop_name in best.getPropertyNames():
            properties[prop_name] = best.getPropertyDefaultValue(prop_name)

    return {
        'platform_name': best.getName(),
        'platform_version': openmm.Platform.getOpenMMVersion(),
        'n_platforms': n_platforms,
        'available_platforms': available,
        'properties': properties,
    }


def save_checkpoint(simulation, filename: str = 'checkpoint.chk'):
    """Save simulation checkpoint.

    Args:
        simulation: OpenMM Simulation object
        filename: Output checkpoint file path
    """
    simulation.saveCheckpoint(filename)
    logging.info(f"Saved checkpoint: {filename}")


def load_checkpoint(simulation, filename: str = 'checkpoint.chk'):
    """Load simulation from checkpoint.

    Args:
        simulation: OpenMM Simulation object
        filename: Checkpoint file path
    """
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"Checkpoint file not found: {filename}")
    simulation.loadCheckpoint(filename)
    logging.info(f"Loaded checkpoint: {filename}")


def save_pdb(simulation, filename: str = 'snapshot.pdb') -> str:
    """Save current simulation positions as PDB file.

    Alias for save_positions_pdb().

    Args:
        simulation: OpenMM Simulation object
        filename: Output PDB path

    Returns:
        Path to saved PDB file
    """
    return save_positions_pdb(simulation, output_file=filename)


def parse_state_data(csv_file: str) -> Dict:
    """Parse OpenMM StateDataReporter CSV log file.

    Alias for parse_log().

    Args:
        csv_file: Path to CSV log file

    Returns:
        Dict with parsed data arrays
    """
    return parse_log(csv_file)


def compute_hydrogen_bonds(trajectory_file: str, topology_file: str,
                           freq: float = 0.1, stride: int = 1) -> Dict:
    """Compute hydrogen bonds using Baker-Hubbard criteria.

    Alias for compute_hbonds() with documented parameter name.

    Args:
        trajectory_file: Path to trajectory
        topology_file: Path to topology PDB
        freq: Minimum frequency to report (alias for freq_cutoff)
        stride: Frame stride

    Returns:
        Dict with hydrogen bond analysis
    """
    return compute_hbonds(trajectory_file, topology_file,
                          freq_cutoff=freq, stride=stride)


def plot_temperature(log_data: Dict, output_file: str = 'temperature.png',
                     target_temp: float = None) -> str:
    """Plot temperature over time from simulation log.

    Args:
        log_data: Dict from parse_log() / parse_state_data()
        output_file: Output plot file path
        target_temp: Target temperature to show as reference line

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Handle both dict input and string (log file path) input
    if isinstance(log_data, str):
        log_data = parse_log(log_data)

    if 'temperature_K' not in log_data:
        logging.warning("No temperature data found in log")
        return output_file

    fig, ax = plt.subplots(figsize=(10, 4))
    time_key = 'time_ps' if 'time_ps' in log_data else 'step'
    x = log_data.get(time_key, np.arange(len(log_data['temperature_K'])))
    x_label = 'Time (ps)' if time_key == 'time_ps' else 'Step'

    ax.plot(x, log_data['temperature_K'], linewidth=0.5, alpha=0.8, color='steelblue')
    mean_temp = np.mean(log_data['temperature_K'])
    ax.axhline(y=mean_temp, color='red', linestyle='--', alpha=0.5,
               label=f'mean={mean_temp:.1f} K')
    if target_temp is not None:
        ax.axhline(y=target_temp, color='green', linestyle='-', alpha=0.5,
                   label=f'target={target_temp:.1f} K')
    ax.set_xlabel(x_label)
    ax.set_ylabel('Temperature (K)')
    ax.set_title('Temperature')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved temperature plot: {output_file}")
    return output_file


def plot_density(log_data: Dict, output_file: str = 'density.png') -> str:
    """Plot density over time from simulation log.

    Args:
        log_data: Dict from parse_log() / parse_state_data()
        output_file: Output plot file path

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Handle both dict input and string (log file path) input
    if isinstance(log_data, str):
        log_data = parse_log(log_data)

    if 'density_kg_m3' not in log_data:
        logging.warning("No density data found in log")
        return output_file

    fig, ax = plt.subplots(figsize=(10, 4))
    time_key = 'time_ps' if 'time_ps' in log_data else 'step'
    x = log_data.get(time_key, np.arange(len(log_data['density_kg_m3'])))
    x_label = 'Time (ps)' if time_key == 'time_ps' else 'Step'

    ax.plot(x, log_data['density_kg_m3'], linewidth=0.5, alpha=0.8, color='steelblue')
    mean_dens = np.mean(log_data['density_kg_m3'])
    ax.axhline(y=mean_dens, color='red', linestyle='--', alpha=0.5,
               label=f'mean={mean_dens:.4f}')
    ax.set_xlabel(x_label)
    ax.set_ylabel('Density (g/mL)')
    ax.set_title('Density')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved density plot: {output_file}")
    return output_file


def get_system_info(simulation) -> Dict:
    """Get information about the simulation system.

    Args:
        simulation: OpenMM Simulation object

    Returns:
        Dict with: n_atoms, n_residues, n_chains, platform,
                   box_vectors, n_forces
    """
    from openmm import unit

    topology = simulation.topology
    system = simulation.system
    platform = simulation.context.getPlatform()

    n_atoms = topology.getNumAtoms()
    n_residues = topology.getNumResidues()
    n_chains = topology.getNumChains()
    n_forces = system.getNumForces()

    box_vectors = topology.getPeriodicBoxVectors()
    box_info = None
    if box_vectors is not None:
        box_info = [
            [v[i].value_in_unit(unit.nanometers) for i in range(3)]
            for v in box_vectors
        ]

    return {
        'n_atoms': n_atoms,
        'n_residues': n_residues,
        'n_chains': n_chains,
        'platform': platform.getName(),
        'platform_version': platform.getOpenMMVersion() if hasattr(platform, 'getOpenMMVersion') else 'unknown',
        'box_vectors': box_info,
        'n_forces': n_forces,
    }


def get_available_forcefields() -> List[str]:
    """Get list of available OpenMM force field XML files.

    Returns:
        List of force field names
    """
    return [
        'amber14-all.xml',
        'amber99sbildn.xml',
        'amber99sb.xml',
        'amber03.xml',
        'amber10.xml',
        'charmm36.xml',
        'charmm_polar_2019.xml',
        'amoeba2013.xml',
        'amoeba2009.xml',
    ]


# Module-level alias for JSON serialization helper
def _json_serializer(obj):
    """Serialize Python/numpy objects for JSON output."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


# ============= CLEANUP =============

def openmm_cleanup(deep: bool = False):
    """Clean OpenMM state between calculations.

    Args:
        deep: If True, clear scratch files and force garbage collection
    """
    import gc
    try:
        gc.collect()
        if deep:
            _clear_scratch_files()
            logging.info("Deep cleanup completed")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")


def _clear_scratch_files():
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
