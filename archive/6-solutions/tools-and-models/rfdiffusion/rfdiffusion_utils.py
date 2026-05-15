#!/usr/bin/env python3
"""RFDiffusion utilities library for Discovery platform workflows.

Provides wrappers for RFDiffusion protein backbone diffusion model:
- Unconditional monomer generation
- Protein binder design (PPI)
- Motif scaffolding
- Symmetric oligomer design
- Fold-conditioned generation
"""

import os
import sys
import glob
import json
import logging
import subprocess
import shutil
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

import numpy as np

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/rfdiffusion_scratch"
RFDIFFUSION_DIR = "/opt/RFdiffusion"
MODELS_DIR = "/opt/RFdiffusion/models"
INFERENCE_SCRIPT = "/opt/RFdiffusion/scripts/run_inference.py"

# Available model checkpoints
MODELS = {
    "Base": "Base_ckpt.pt",
    "Complex": "Complex_base_ckpt.pt",
    "Complex_beta": "Complex_beta_ckpt.pt",
    "InpaintSeq": "InpaintSeq_ckpt.pt",
    "InpaintSeq_Fold": "InpaintSeq_Fold_ckpt.pt",
    "ActiveSite": "ActiveSite_ckpt.pt",
    "Base_epoch8": "Base_epoch8_ckpt.pt",
}


# ============= SETUP FUNCTIONS =============

def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else '(none)'}")
    logging.info(f"Available models: {list_available_models()}")


def _copy_input_files():
    """Copy input files to working directory (with same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


# Global counter for generating unique output prefixes within a single process
_PREFIX_COUNTER = {}

def _unique_output_prefix(output_dir: str, base_name: str) -> str:
    """Generate a unique output prefix to avoid RFDiffusion's cautious-mode collisions.

    When generate_unconditional (or other convenience functions) is called
    multiple times with the default prefix, RFDiffusion skips designs if
    PDBs with the same prefix already exist. This function appends an
    auto-incrementing counter (e.g., unconditional_run1, unconditional_run2).

    Args:
        output_dir: Directory for outputs (e.g., /output)
        base_name: Base prefix name (e.g., 'unconditional')

    Returns:
        Unique output prefix path (e.g., /output/unconditional_run2)
    """
    global _PREFIX_COUNTER
    if base_name not in _PREFIX_COUNTER:
        _PREFIX_COUNTER[base_name] = 0

    _PREFIX_COUNTER[base_name] += 1
    count = _PREFIX_COUNTER[base_name]

    if count == 1:
        # First call: use base name directly for backward compatibility
        candidate = os.path.join(output_dir, base_name)
    else:
        candidate = os.path.join(output_dir, f'{base_name}_run{count}')

    # Extra safety: if files already exist on disk, increment further
    while glob.glob(f'{candidate}_*.pdb'):
        count += 1
        _PREFIX_COUNTER[base_name] = count
        candidate = os.path.join(output_dir, f'{base_name}_run{count}')

    return candidate


def copy_outputs():
    """Copy output files to output directory (with same-directory guard)."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.pdb', '*.trb', '*.png', '*.json', '*.csv', '*.log', '*.html']
    for pattern in patterns:
        for f in glob.glob(pattern):
            dst = os.path.join(OUTPUT_DIR, os.path.basename(f))
            if not os.path.exists(dst):
                shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def quick_finish():
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None, status: str = "completed"):
    """Save final results to JSON file (MANDATORY for every script).

    Args:
        results: Summary dict with key metrics
        output_files: Dict mapping names to file paths
        file_descriptions: Dict mapping names to descriptions
        status: Job status string
    """
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(path, 'w') as f:
        json.dump(final_data, f, indent=2, default=str)
    logging.info(f"Saved final_results.json to {path}")


# ============= CONTIG STRING BUILDERS =============

def build_contigs_unconditional(length: Union[int, Tuple[int, int]]) -> str:
    """Build contig string for unconditional monomer generation.

    Args:
        length: Exact length (int) or range (min, max) tuple

    Returns:
        Contig string like '[150-150]' or '[100-200]'
    """
    if isinstance(length, (list, tuple)):
        return f'[{length[0]}-{length[1]}]'
    return f'[{length}-{length}]'


def build_contigs_binder(target_chain: str, target_start: int, target_end: int,
                         binder_length: Union[int, Tuple[int, int]],
                         gap: int = 0) -> str:
    """Build contig string for binder design.

    Args:
        target_chain: Chain ID of target (e.g., 'A')
        target_start: First residue of target to keep
        target_end: Last residue of target to keep
        binder_length: Length or (min, max) range for designed binder
        gap: Gap between target and binder (0 = directly connected)

    Returns:
        Contig string like '[A1-100/0 70-100]'
    """
    if isinstance(binder_length, (list, tuple)):
        binder_str = f'{binder_length[0]}-{binder_length[1]}'
    else:
        binder_str = f'{binder_length}-{binder_length}'
    return f'[{target_chain}{target_start}-{target_end}/{gap} {binder_str}]'


def build_contigs_motif_scaffold(motif_spec: str,
                                 n_term_length: Union[int, Tuple[int, int]],
                                 c_term_length: Union[int, Tuple[int, int]]) -> str:
    """Build contig string for motif scaffolding.

    Args:
        motif_spec: Motif residue specification (e.g., 'A163-181')
        n_term_length: N-terminal scaffold length or range
        c_term_length: C-terminal scaffold length or range

    Returns:
        Contig string like '[10-40/A163-181/10-40]'
    """
    def _range_str(x):
        if isinstance(x, (list, tuple)):
            return f'{x[0]}-{x[1]}'
        return f'{x}-{x}'

    return f'[{_range_str(n_term_length)}/{motif_spec}/{_range_str(c_term_length)}]'


def build_contigs_symmetric(protomer_length: Union[int, Tuple[int, int]]) -> str:
    """Build contig string for symmetric oligomer (one protomer spec).

    Args:
        protomer_length: Length or range for each protomer

    Returns:
        Contig string for one protomer
    """
    if isinstance(protomer_length, (list, tuple)):
        return f'[{protomer_length[0]}-{protomer_length[1]}]'
    return f'[{protomer_length}-{protomer_length}]'


# ============= CORE INFERENCE =============

def run_rfdiffusion(contigs: str, output_prefix: str, num_designs: int = 1,
                    model: str = 'Base', input_pdb: str = None,
                    hotspot_res: List[str] = None, diffuser_T: int = 50,
                    symmetry: str = None, extra_args: Dict[str, Any] = None,
                    timeout: int = 3600) -> Dict:
    """Run RFDiffusion inference.

    Args:
        contigs: Contig string defining topology (e.g., '[150-150]')
        output_prefix: Output path prefix for generated PDBs
        num_designs: Number of designs to generate
        model: Model name ('Base', 'Complex', 'ActiveSite', etc.)
        input_pdb: Path to input PDB file (required for binder design, scaffolding)
        hotspot_res: List of hotspot residues (e.g., ['A30', 'A33', 'A34'])
        diffuser_T: Number of diffusion timesteps (default 50)
        symmetry: Symmetry type (e.g., 'C3', 'C6', 'tetrahedral')
        extra_args: Additional Hydra override args as dict
        timeout: Timeout in seconds (default 3600)

    Returns:
        Dict with keys: output_pdbs, trb_files, num_generated, model_used, contigs
    """
    # Ensure output directory exists
    output_dir = os.path.dirname(output_prefix)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Build command
    cmd = [
        'python3', INFERENCE_SCRIPT,
        f'inference.output_prefix={output_prefix}',
        f'inference.num_designs={num_designs}',
        f'contigmap.contigs={contigs}',
        f'diffuser.T={diffuser_T}',
        f'inference.model_directory_path={MODELS_DIR}',
    ]

    # Model checkpoint override
    if model not in MODELS:
        valid_names = ', '.join(sorted(MODELS.keys()))
        raise ValueError(
            f"Unknown model '{model}'. Valid model names: {valid_names}"
        )
    ckpt_path = os.path.join(MODELS_DIR, MODELS[model])
    if os.path.exists(ckpt_path):
        cmd.append(f'inference.ckpt_override_path={ckpt_path}')
    else:
        logging.warning(f"Model checkpoint not found: {ckpt_path}, using default")

    # Input PDB
    if input_pdb:
        # Resolve relative to working directory
        if not os.path.isabs(input_pdb):
            input_pdb = os.path.join(WORK_DIR, input_pdb)
        if not os.path.exists(input_pdb):
            raise FileNotFoundError(f"Input PDB not found: {input_pdb}")
        cmd.append(f'inference.input_pdb={input_pdb}')

    # Hotspot residues for PPI/binder design
    if hotspot_res:
        hotspot_str = ','.join(hotspot_res)
        cmd.append(f'ppi.hotspot_res=[{hotspot_str}]')

    # Symmetry
    if symmetry:
        cmd.append(f'inference.symmetry={symmetry}')

    # Extra arguments
    if extra_args:
        for key, value in extra_args.items():
            if isinstance(value, list):
                val_str = ','.join(str(v) for v in value)
                cmd.append(f'{key}=[{val_str}]')
            elif isinstance(value, bool):
                cmd.append(f'{key}={str(value).lower()}')
            else:
                cmd.append(f'{key}={value}')

    # Log command
    cmd_str = ' '.join(cmd)
    logging.info(f"Running RFDiffusion command:\n{cmd_str}")

    # Execute
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=WORK_DIR
        )

        # Log output
        if result.stdout:
            logging.info(f"STDOUT (last 3000 chars):\n{result.stdout[-3000:]}")
        if result.stderr:
            logging.info(f"STDERR (last 3000 chars):\n{result.stderr[-3000:]}")

        if result.returncode != 0:
            logging.error(f"RFDiffusion failed with return code {result.returncode}")
            raise RuntimeError(
                f"RFDiffusion failed (rc={result.returncode}):\n{result.stderr[-1000:]}"
            )

    except subprocess.TimeoutExpired:
        logging.error(f"RFDiffusion timed out after {timeout}s")
        raise

    # Collect output files
    pdb_files = sorted(glob.glob(f'{output_prefix}_*.pdb'))
    trb_files = sorted(glob.glob(f'{output_prefix}_*.trb'))

    # Copy outputs to OUTPUT_DIR
    for f in pdb_files + trb_files:
        dst = os.path.join(OUTPUT_DIR, os.path.basename(f))
        if not os.path.exists(dst):
            shutil.copy(f, OUTPUT_DIR)

    result_info = {
        'output_pdbs': [os.path.basename(f) for f in pdb_files],
        'trb_files': [os.path.basename(f) for f in trb_files],
        'num_generated': len(pdb_files),
        'model_used': model,
        'contigs': contigs,
        'diffuser_T': diffuser_T,
    }

    logging.info(f"Generated {len(pdb_files)} designs")
    return result_info


# ============= CONVENIENCE FUNCTIONS =============

def generate_unconditional(length: Union[int, Tuple[int, int]],
                           num_designs: int = 10,
                           output_prefix: str = None,
                           diffuser_T: int = 50,
                           **kwargs) -> Dict:
    """Generate unconditional protein backbones.

    Args:
        length: Backbone length (int) or range (min, max)
        num_designs: Number of designs
        output_prefix: Output prefix (default: /output/unconditional_<counter>)
        diffuser_T: Diffusion timesteps

    Returns:
        Dict with design results
    """
    if output_prefix is None:
        output_prefix = _unique_output_prefix(OUTPUT_DIR, 'unconditional')

    contigs = build_contigs_unconditional(length)
    return run_rfdiffusion(
        contigs=contigs,
        output_prefix=output_prefix,
        num_designs=num_designs,
        model='Base',
        diffuser_T=diffuser_T,
        **kwargs
    )


def design_binder(target_pdb: str, target_chain: str,
                  target_start: int, target_end: int,
                  binder_length: Union[int, Tuple[int, int]] = (50, 100),
                  hotspot_residues: List[str] = None,
                  num_designs: int = 10,
                  output_prefix: str = None,
                  diffuser_T: int = 50,
                  **kwargs) -> Dict:
    """Design a protein binder against a target.

    Args:
        target_pdb: Path to target PDB file
        target_chain: Chain ID of target
        target_start: First residue of target
        target_end: Last residue of target
        binder_length: Binder length or (min, max) range
        hotspot_residues: Target residues to focus binding (e.g., ['A30', 'A33'])
        num_designs: Number of designs
        output_prefix: Output prefix
        diffuser_T: Diffusion timesteps

    Returns:
        Dict with design results
    """
    if output_prefix is None:
        output_prefix = _unique_output_prefix(OUTPUT_DIR, 'binder')

    contigs = build_contigs_binder(
        target_chain, target_start, target_end, binder_length
    )

    return run_rfdiffusion(
        contigs=contigs,
        output_prefix=output_prefix,
        num_designs=num_designs,
        model='Complex',
        input_pdb=target_pdb,
        hotspot_res=hotspot_residues,
        diffuser_T=diffuser_T,
        **kwargs
    )


def scaffold_motif(motif_pdb: str, motif_spec: str,
                   n_term_length: Union[int, Tuple[int, int]] = (10, 40),
                   c_term_length: Union[int, Tuple[int, int]] = (10, 40),
                   num_designs: int = 10,
                   output_prefix: str = None,
                   diffuser_T: int = 50,
                   **kwargs) -> Dict:
    """Design a scaffold around a functional motif.

    Args:
        motif_pdb: Path to PDB containing the motif
        motif_spec: Motif residue range (e.g., 'A163-181')
        n_term_length: N-terminal scaffold length or range
        c_term_length: C-terminal scaffold length or range
        num_designs: Number of designs
        output_prefix: Output prefix
        diffuser_T: Diffusion timesteps

    Returns:
        Dict with design results
    """
    if output_prefix is None:
        output_prefix = _unique_output_prefix(OUTPUT_DIR, 'scaffold')

    contigs = build_contigs_motif_scaffold(motif_spec, n_term_length, c_term_length)

    return run_rfdiffusion(
        contigs=contigs,
        output_prefix=output_prefix,
        num_designs=num_designs,
        model='Base',
        input_pdb=motif_pdb,
        diffuser_T=diffuser_T,
        **kwargs
    )


def _get_symmetry_order(symmetry: str) -> Optional[int]:
    """Extract the symmetry order from a symmetry string.

    Args:
        symmetry: Symmetry group string (e.g., 'C3', 'C6', 'D2')

    Returns:
        Integer order, or None if not determinable (e.g., 'tetrahedral')
    """
    if not symmetry:
        return None
    sym_upper = symmetry.upper()
    # Cyclic symmetry: C2, C3, C4, C5, C6, ...
    if sym_upper.startswith('C') and sym_upper[1:].isdigit():
        return int(sym_upper[1:])
    # Dihedral symmetry: D2, D3, D4, ...
    if sym_upper.startswith('D') and sym_upper[1:].isdigit():
        return int(sym_upper[1:]) * 2
    # For tetrahedral (12), octahedral (24), icosahedral (60) — don't validate
    return None


def design_symmetric_oligomer(symmetry: str,
                              protomer_length: Union[int, Tuple[int, int]],
                              num_designs: int = 10,
                              output_prefix: str = None,
                              diffuser_T: int = 50,
                              **kwargs) -> Dict:
    """Design symmetric protein oligomers.

    Args:
        symmetry: Symmetry group (e.g., 'C3', 'C6', 'tetrahedral', 'octahedral')
        protomer_length: Length or range for each protomer
        num_designs: Number of designs
        output_prefix: Output prefix
        diffuser_T: Diffusion timesteps

    Returns:
        Dict with design results

    Raises:
        ValueError: If protomer length is not divisible by the symmetry order
    """
    if output_prefix is None:
        output_prefix = _unique_output_prefix(OUTPUT_DIR, 'symmetric')

    # Validate protomer length divisibility by symmetry order
    sym_order = _get_symmetry_order(symmetry)
    if sym_order is not None:
        lengths = list(protomer_length) if isinstance(protomer_length, (list, tuple)) else [protomer_length]
        for val in lengths:
            if val % sym_order != 0:
                nearest = val + (sym_order - val % sym_order)
                raise ValueError(
                    f"Protomer length {val} is not divisible by symmetry order "
                    f"{sym_order} ({symmetry}). Use a multiple of {sym_order} "
                    f"(e.g., {nearest})."
                )

    contigs = build_contigs_symmetric(protomer_length)

    return run_rfdiffusion(
        contigs=contigs,
        output_prefix=output_prefix,
        num_designs=num_designs,
        model='Base',
        symmetry=symmetry,
        diffuser_T=diffuser_T,
        **kwargs
    )


# ============= PDB PARSING =============

def parse_pdb(pdb_file: str) -> Dict:
    """Parse a PDB file and extract key information.

    Args:
        pdb_file: Path to PDB file

    Returns:
        Dict with chains, total_residues, total_atoms, ca_coords, num_chains
    """
    if not os.path.exists(pdb_file):
        raise FileNotFoundError(f"PDB file not found: {pdb_file}")

    chains = {}
    ca_coords = []
    all_atoms = []

    with open(pdb_file, 'r') as f:
        for line in f:
            if line.startswith(('ATOM', 'HETATM')):
                atom_name = line[12:16].strip()
                chain_id = line[21]
                res_num = int(line[22:26].strip())
                res_name = line[17:20].strip()
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])

                if chain_id not in chains:
                    chains[chain_id] = {'residues': {}, 'atom_count': 0}

                chains[chain_id]['residues'][res_num] = res_name
                chains[chain_id]['atom_count'] += 1
                all_atoms.append({
                    'name': atom_name, 'chain': chain_id,
                    'resnum': res_num, 'resname': res_name,
                    'coords': [x, y, z]
                })

                if atom_name == 'CA':
                    ca_coords.append([x, y, z])

    return {
        'chains': {
            k: {
                'num_residues': len(v['residues']),
                'atom_count': v['atom_count'],
                'residue_range': (
                    min(v['residues'].keys()),
                    max(v['residues'].keys())
                ) if v['residues'] else (0, 0)
            }
            for k, v in chains.items()
        },
        'total_residues': sum(len(v['residues']) for v in chains.values()),
        'total_atoms': len(all_atoms),
        'ca_coords': np.array(ca_coords) if ca_coords else np.array([]).reshape(0, 3),
        'num_chains': len(chains),
    }


# ============= ANALYSIS FUNCTIONS =============

def compute_backbone_metrics(pdb_file: str) -> Dict:
    """Compute backbone quality metrics for a design.

    Args:
        pdb_file: Path to PDB file

    Returns:
        Dict with radius_of_gyration, end_to_end_distance, compactness,
        num_residues, ca_distance_mean/std, total_atoms, num_chains
    """
    pdb_data = parse_pdb(pdb_file)
    ca_coords = pdb_data['ca_coords']

    if len(ca_coords) == 0:
        return {'error': 'No CA atoms found', 'num_residues': 0}

    n_res = len(ca_coords)

    # Center of mass
    com = np.mean(ca_coords, axis=0)

    # Radius of gyration
    diffs = ca_coords - com
    rg = np.sqrt(np.mean(np.sum(diffs**2, axis=1)))

    # End-to-end distance
    end_to_end = np.linalg.norm(ca_coords[-1] - ca_coords[0])

    # Sequential CA-CA distances
    ca_dists = np.array([
        np.linalg.norm(ca_coords[i + 1] - ca_coords[i])
        for i in range(len(ca_coords) - 1)
    ])

    # Compactness (Rg / sqrt(N))
    compactness = rg / np.sqrt(n_res)

    return {
        'num_residues': n_res,
        'num_chains': pdb_data['num_chains'],
        'radius_of_gyration': float(rg),
        'end_to_end_distance': float(end_to_end),
        'compactness': float(compactness),
        'ca_distance_mean': float(np.mean(ca_dists)) if len(ca_dists) > 0 else 0.0,
        'ca_distance_std': float(np.std(ca_dists)) if len(ca_dists) > 0 else 0.0,
        'total_atoms': pdb_data['total_atoms'],
    }


def compute_ca_rmsd(pdb1: str, pdb2: str) -> float:
    """Compute CA RMSD between two PDB structures (no alignment).

    Args:
        pdb1: Path to first PDB
        pdb2: Path to second PDB

    Returns:
        RMSD in Angstroms
    """
    data1 = parse_pdb(pdb1)
    data2 = parse_pdb(pdb2)

    ca1 = data1['ca_coords']
    ca2 = data2['ca_coords']

    if len(ca1) != len(ca2):
        raise ValueError(f"CA atom count mismatch: {len(ca1)} vs {len(ca2)}")

    if len(ca1) == 0:
        raise ValueError("No CA atoms found")

    diff = ca1 - ca2
    rmsd = np.sqrt(np.mean(np.sum(diff**2, axis=1)))
    return float(rmsd)


def analyze_designs(output_prefix: str, num_designs: int = None) -> List[Dict]:
    """Analyze all generated designs from an RFDiffusion run.

    Args:
        output_prefix: The output prefix used in run_rfdiffusion
        num_designs: Expected number of designs (auto-detected if None)

    Returns:
        List of metric dicts, one per design
    """
    pdb_files = sorted(glob.glob(f'{output_prefix}_*.pdb'))
    if not pdb_files:
        # Check in OUTPUT_DIR
        base = os.path.basename(output_prefix)
        pdb_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, f'{base}_*.pdb')))

    if not pdb_files:
        logging.warning(f"No PDB files found for prefix: {output_prefix}")
        return []

    metrics = []
    for pdb_file in pdb_files:
        try:
            m = compute_backbone_metrics(pdb_file)
            m['filename'] = os.path.basename(pdb_file)

            # Parse .trb file if available (contains RFDiffusion metadata)
            trb_file = pdb_file.replace('.pdb', '.trb')
            if os.path.exists(trb_file):
                try:
                    trb_data = np.load(trb_file, allow_pickle=True)
                    # TRB files saved with np.save() return a 0-d ndarray
                    # wrapping a dict — use .item() to unwrap.
                    # Files saved with np.savez() return NpzFile with .files attr.
                    if hasattr(trb_data, 'files'):
                        # NpzFile format
                        trb_dict = {k: trb_data[k] for k in trb_data.files}
                    elif isinstance(trb_data, np.ndarray) and trb_data.ndim == 0:
                        # 0-d array wrapping a dict (np.save format)
                        trb_dict = trb_data.item()
                    elif isinstance(trb_data, dict):
                        trb_dict = trb_data
                    else:
                        trb_dict = {}

                    if 'lddt' in trb_dict:
                        lddt = trb_dict['lddt']
                        if hasattr(lddt, '__len__') and len(lddt) > 0:
                            m['mean_plddt'] = float(np.mean(lddt))
                            m['min_plddt'] = float(np.min(lddt))
                    if 'con_hal_pdb_idx' in trb_dict:
                        m['has_contig_info'] = True
                except Exception as e:
                    logging.warning(f"Could not parse TRB file {trb_file}: {e}")

            metrics.append(m)
        except Exception as e:
            logging.error(f"Error analyzing {pdb_file}: {e}")
            metrics.append({'filename': os.path.basename(pdb_file), 'error': str(e)})

    logging.info(f"Analyzed {len(metrics)} designs")
    return metrics


def get_pdb_chain_info(pdb_file: str) -> Dict:
    """Get chain information from a PDB file for contig construction.

    Only counts standard ATOM records (not HETATM), so waters, ligands,
    and other heteroatoms are excluded from residue counts and ranges.

    Args:
        pdb_file: Path to PDB file

    Returns:
        Dict mapping chain IDs to {num_residues, start, end}
    """
    if not os.path.exists(pdb_file):
        raise FileNotFoundError(f"PDB file not found: {pdb_file}")

    chains = {}
    with open(pdb_file, 'r') as f:
        for line in f:
            # Only parse standard ATOM records — HETATM (waters, ligands)
            # would inflate residue counts and break contig construction
            if line.startswith('ATOM  '):
                chain_id = line[21]
                try:
                    res_num = int(line[22:26].strip())
                except ValueError:
                    continue  # skip malformed lines (e.g., insertion codes)
                if chain_id not in chains:
                    chains[chain_id] = set()
                chains[chain_id].add(res_num)

    result = {}
    for chain_id, residues in chains.items():
        if residues:
            sorted_res = sorted(residues)
            result[chain_id] = {
                'num_residues': len(sorted_res),
                'start': sorted_res[0],
                'end': sorted_res[-1],
            }
        else:
            result[chain_id] = {'num_residues': 0, 'start': 0, 'end': 0}

    return result


def list_available_models() -> List[str]:
    """List available model checkpoints in the container.

    Returns:
        List of strings like 'Base (Base_ckpt.pt, 650 MB)' or 'Base (NOT FOUND)'
    """
    available = []
    for name, filename in MODELS.items():
        path = os.path.join(MODELS_DIR, filename)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            available.append(f"{name} ({filename}, {size_mb:.0f} MB)")
        else:
            available.append(f"{name} ({filename}, NOT FOUND)")
    return available


# ============= VISUALIZATION =============

def plot_design_metrics(metrics: List[Dict], output_file: str = None,
                        title: str = "RFDiffusion Design Metrics"):
    """Plot backbone quality metrics for a set of designs.

    Args:
        metrics: List of metric dicts from analyze_designs
        output_file: Path for output PNG (default: /output/design_metrics.png)
        title: Plot title
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, 'design_metrics.png')

    valid = [m for m in metrics if 'error' not in m]
    if not valid:
        logging.warning("No valid metrics to plot")
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle(title, fontsize=14, fontweight='bold')

    names = [m.get('filename', f'design_{i}') for i, m in enumerate(valid)]
    short_names = [n.split('_')[-1].replace('.pdb', '') for n in names]
    x = range(len(valid))

    # Panel 1: Number of residues
    ax = axes[0, 0]
    ax.bar(x, [m['num_residues'] for m in valid], color='steelblue')
    ax.set_ylabel('Number of Residues')
    ax.set_title('Chain Length')
    ax.set_xticks(list(x))
    ax.set_xticklabels(short_names, rotation=45, ha='right')

    # Panel 2: Radius of gyration
    ax = axes[0, 1]
    ax.bar(x, [m['radius_of_gyration'] for m in valid], color='coral')
    ax.set_ylabel('Rg (Å)')
    ax.set_title('Radius of Gyration')
    ax.set_xticks(list(x))
    ax.set_xticklabels(short_names, rotation=45, ha='right')

    # Panel 3: End-to-end distance
    ax = axes[1, 0]
    ax.bar(x, [m['end_to_end_distance'] for m in valid], color='mediumseagreen')
    ax.set_ylabel('Distance (Å)')
    ax.set_title('End-to-End Distance')
    ax.set_xticks(list(x))
    ax.set_xticklabels(short_names, rotation=45, ha='right')

    # Panel 4: Compactness
    ax = axes[1, 1]
    ax.bar(x, [m['compactness'] for m in valid], color='mediumpurple')
    ax.set_ylabel('Rg / √N')
    ax.set_title('Compactness')
    ax.set_xticks(list(x))
    ax.set_xticklabels(short_names, rotation=45, ha='right')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved metrics plot: {output_file}")


def plot_backbone_trace(pdb_file: str, output_file: str = None,
                        title: str = None):
    """Plot 3D projection of CA backbone trace.

    Args:
        pdb_file: Path to PDB file
        output_file: Output PNG path
        title: Plot title (default: filename)
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if output_file is None:
        base = os.path.splitext(os.path.basename(pdb_file))[0]
        output_file = os.path.join(OUTPUT_DIR, f'{base}_trace.png')

    if title is None:
        title = os.path.basename(pdb_file)

    data = parse_pdb(pdb_file)
    ca_coords = data['ca_coords']

    if len(ca_coords) == 0:
        logging.warning(f"No CA atoms in {pdb_file}")
        return

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')

    colors = plt.cm.viridis(np.linspace(0, 1, len(ca_coords)))

    # Backbone trace
    ax.plot(ca_coords[:, 0], ca_coords[:, 1], ca_coords[:, 2],
            'k-', alpha=0.3, linewidth=0.5)
    ax.scatter(ca_coords[:, 0], ca_coords[:, 1], ca_coords[:, 2],
               c=colors, s=20, alpha=0.8)

    # Mark N and C termini
    ax.scatter(*ca_coords[0], c='blue', s=100, marker='^', label='N-term', zorder=5)
    ax.scatter(*ca_coords[-1], c='red', s=100, marker='v', label='C-term', zorder=5)

    ax.set_xlabel('X (Å)')
    ax.set_ylabel('Y (Å)')
    ax.set_zlabel('Z (Å)')
    ax.set_title(title)
    ax.legend()

    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved backbone trace: {output_file}")


def plot_design_comparison(metrics: List[Dict], output_file: str = None):
    """Scatter plot comparing key metrics across designs.

    Args:
        metrics: List of metric dicts
        output_file: Output PNG path
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, 'design_comparison.png')

    valid = [m for m in metrics if 'error' not in m]
    if not valid:
        return

    fig, ax = plt.subplots(figsize=(8, 6))

    rg = [m['radius_of_gyration'] for m in valid]
    nres = [m['num_residues'] for m in valid]
    compact = [m['compactness'] for m in valid]

    scatter = ax.scatter(nres, rg, c=compact, s=80, cmap='RdYlGn_r',
                         edgecolors='black', linewidth=0.5)
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Compactness (Rg/√N)')

    ax.set_xlabel('Number of Residues')
    ax.set_ylabel('Radius of Gyration (Å)')
    ax.set_title('Design Space Overview')

    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved design comparison: {output_file}")


# ============= CLEANUP =============

def cleanup(deep: bool = False):
    """Clean up temporary files.

    Args:
        deep: If True, also clear scratch directory
    """
    if deep:
        try:
            cleared = 0
            for entry in os.scandir(SCRATCH_DIR):
                if entry.is_file():
                    try:
                        os.remove(entry.path)
                        cleared += 1
                    except OSError:
                        pass
            if cleared:
                logging.info(f"Cleared {cleared} scratch files")
        except FileNotFoundError:
            pass
