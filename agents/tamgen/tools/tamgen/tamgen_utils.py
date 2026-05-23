"""TamGen Utilities for Microsoft Discovery Platform
===================================================
Target-aware Molecule Generation for Drug Design Using a Chemical Language Model.

Reference: Wu et al., Nature Communications 15:9360 (2024)
Repository: https://github.com/microsoft/TamGen

Provides high-level wrappers for:
- Pocket data preparation from PDB structures
- Target-aware molecule generation (unconditional + scaffold-constrained)
- Molecular property analysis and filtering
- Result summarization and export
"""

import os
import sys
import json
import logging
import shutil
import subprocess
import traceback
import csv
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union, Any

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
logger = logging.getLogger("tamgen_utils")

# ---------------------------------------------------------------------------
# Paths – baked into the Docker image
# ---------------------------------------------------------------------------
TAMGEN_ROOT = os.environ.get("TAMGEN_ROOT", "/app/TamGen")
CHECKPOINT_CROSSDOCK = os.path.join(
    TAMGEN_ROOT, "checkpoints", "crossdock_pdb_A10", "checkpoint_best.pt"
)
CHECKPOINT_CROSSDOCKED = os.path.join(
    TAMGEN_ROOT, "checkpoints", "crossdocked_model", "checkpoint_best.pt"
)
GPT_MODEL_DIR = os.path.join(TAMGEN_ROOT, "gpt_model")

# Runtime state
_config: Dict[str, str] = {}
_model_cache: Dict[str, Any] = {}

# ============================================================================
# SETUP (required for every script)
# ============================================================================

def quick_setup(
    input_dir: str = "/input",
    output_dir: str = "/output",
    work_dir: str = "/app/workdir",
) -> dict:
    """Initialise TamGen environment, directories, and logging.

    Returns a dict with environment diagnostics (GPU, paths, etc.).
    """
    global _config

    for d in [input_dir, output_dir, work_dir]:
        os.makedirs(d, exist_ok=True)

    data_dir = os.path.join(work_dir, "tamgen_data")
    os.makedirs(data_dir, exist_ok=True)

    _config.update(
        {
            "input_dir": input_dir,
            "output_dir": output_dir,
            "work_dir": work_dir,
            "tamgen_root": TAMGEN_ROOT,
            "data_dir": data_dir,
        }
    )

    # Logging ----------------------------------------------------------------
    log_path = os.path.join(output_dir, "tamgen.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path),
        ],
    )

    # Diagnostics ------------------------------------------------------------
    info: Dict[str, Any] = {
        "tamgen_root": TAMGEN_ROOT,
        "tamgen_installed": os.path.isdir(TAMGEN_ROOT),
        "checkpoint_crossdock": os.path.isfile(CHECKPOINT_CROSSDOCK),
        "checkpoint_crossdocked": os.path.isfile(CHECKPOINT_CROSSDOCKED),
        "gpt_model": os.path.isfile(
            os.path.join(GPT_MODEL_DIR, "checkpoint_best.pt")
        ),
        "data_dir": data_dir,
    }

    try:
        import torch

        info["cuda_available"] = torch.cuda.is_available()
        if info["cuda_available"]:
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_memory_gb"] = round(
                torch.cuda.get_device_properties(0).total_mem / 1e9, 1
            )
    except Exception as exc:
        info["cuda_available"] = False
        info["cuda_error"] = str(exc)

    logger.info(f"TamGen environment:\n{json.dumps(info, indent=2)}")
    return info


def quick_finish() -> None:
    """Copy working-directory artefacts to /output."""
    output_dir = _config.get("output_dir", "/output")
    work_dir = _config.get("work_dir", "/app/workdir")

    for item in Path(work_dir).iterdir():
        dst = Path(output_dir) / item.name
        if dst.exists():
            continue
        try:
            if item.is_dir():
                shutil.copytree(str(item), str(dst))
            else:
                shutil.copy2(str(item), str(dst))
        except Exception as exc:
            logger.warning(f"Could not copy {item.name}: {exc}")

    logger.info("quick_finish completed")


def save_final_results(
    results: Any,
    output_files: Optional[List[str]] = None,
    file_descriptions: Optional[Dict[str, str]] = None,
) -> str:
    """Persist structured results as ``final_results.json``."""
    output_dir = _config.get("output_dir", "/output")

    payload: Dict[str, Any] = {"status": "success", "results": results}
    if output_files:
        payload["output_files"] = output_files
    if file_descriptions:
        payload["file_descriptions"] = file_descriptions

    path = os.path.join(output_dir, "final_results.json")
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)

    logger.info(f"Final results saved to {path}")
    return path


# ============================================================================
# DATA PREPARATION
# ============================================================================

def prepare_pocket_from_pdb_id(
    pdb_id: str,
    ligand_inchi: Optional[str] = None,
    threshold: float = 10.0,
    data_dir: Optional[str] = None,
    pdb_path: Optional[str] = None,
) -> Dict[str, str]:
    """Prepare pocket data from a PDB ID with automatic binding-site detection.

    The binding site is identified from co-crystallised ligands in the PDB
    structure.  Optionally narrow to a specific ligand via *ligand_inchi*.

    Parameters
    ----------
    pdb_id : str
        PDB identifier (e.g. ``"1iep"``, ``"8fln"``).
    ligand_inchi : str, optional
        InChI string to select a particular ligand.
    threshold : float
        Pocket radius in Angstroms (default 10 A).
    data_dir : str, optional
        Where to write processed data.  Defaults to ``work_dir/tamgen_data``.
    pdb_path : str, optional
        Directory containing custom PDB/mmCIF files.

    Returns
    -------
    dict
        ``{"data_dir": ..., "subset_name": ...}`` for downstream generation.
    """
    data_dir = data_dir or _config.get("data_dir", "/app/workdir/tamgen_data")
    os.makedirs(data_dir, exist_ok=True)

    subset_name = f"gen_{pdb_id.lower()}"

    csv_path = os.path.join(data_dir, f"_tmp_pdb_{pdb_id}.csv")
    with open(csv_path, "w", newline="") as fh:
        if ligand_inchi:
            fh.write("pdb_id,ligand_inchi\n")
            fh.write(f"{pdb_id},{ligand_inchi}\n")
        else:
            fh.write("pdb_id\n")
            fh.write(f"{pdb_id}\n")

    script = os.path.join(
        TAMGEN_ROOT, "scripts", "build_data", "prepare_pdb_ids.py"
    )
    cmd = [sys.executable, script, csv_path, subset_name, "-o", data_dir, "-t", str(threshold)]
    if pdb_path:
        cmd.extend(["-pp", str(pdb_path)])

    logger.info(
        f"Preparing pocket from PDB {pdb_id} (threshold={threshold} A)"
    )
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=TAMGEN_ROOT)

    if result.returncode != 0:
        logger.error(f"prepare_pdb_ids.py STDERR:\n{result.stderr}")
        logger.error(f"prepare_pdb_ids.py STDOUT:\n{result.stdout}")
        raise RuntimeError(
            f"Pocket preparation failed for {pdb_id}: {result.stderr[-500:]}"
        )

    logger.info(f"Pocket data ready: data_dir={data_dir}, subset={subset_name}")
    _safe_remove(csv_path)

    return {"data_dir": data_dir, "subset_name": subset_name}


def prepare_pocket_from_center(
    pdb_id: str,
    center_x: float,
    center_y: float,
    center_z: float,
    threshold: float = 10.0,
    data_dir: Optional[str] = None,
    pdb_path: Optional[str] = None,
) -> Dict[str, str]:
    """Prepare pocket data using explicit binding-site centre coordinates.

    Parameters
    ----------
    pdb_id : str
        PDB identifier or filename in *pdb_path*.
    center_x, center_y, center_z : float
        Binding-site centre in Angstroms.
    threshold : float
        Pocket radius (default 10 A).

    Returns
    -------
    dict
        ``{"data_dir": ..., "subset_name": ...}``
    """
    data_dir = data_dir or _config.get("data_dir", "/app/workdir/tamgen_data")
    os.makedirs(data_dir, exist_ok=True)

    subset_name = f"gen_{pdb_id.lower()}"

    csv_path = os.path.join(data_dir, f"_tmp_center_{pdb_id}.csv")
    with open(csv_path, "w", newline="") as fh:
        fh.write("pdb_id,center_x,center_y,center_z\n")
        fh.write(f"{pdb_id},{center_x},{center_y},{center_z}\n")

    script = os.path.join(
        TAMGEN_ROOT, "scripts", "build_data", "prepare_pdb_ids_center.py"
    )
    cmd = [sys.executable, script, csv_path, subset_name, "-o", data_dir, "-t", str(threshold)]
    if pdb_path:
        cmd.extend(["-pp", str(pdb_path)])

    logger.info(
        f"Preparing pocket from centre ({center_x}, {center_y}, {center_z}), "
        f"radius={threshold} A"
    )
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=TAMGEN_ROOT)

    if result.returncode != 0:
        logger.error(f"prepare_pdb_ids_center.py STDERR:\n{result.stderr}")
        logger.error(f"prepare_pdb_ids_center.py STDOUT:\n{result.stdout}")
        raise RuntimeError(
            f"Centre-based pocket preparation failed: {result.stderr[-500:]}"
        )

    logger.info(f"Pocket data ready (centre mode): subset={subset_name}")
    _safe_remove(csv_path)

    return {"data_dir": data_dir, "subset_name": subset_name}


def prepare_pocket_with_scaffold(
    pdb_id: str,
    center_x: float,
    center_y: float,
    center_z: float,
    scaffold_smiles: str,
    threshold: float = 10.0,
    data_dir: Optional[str] = None,
    pdb_path: Optional[str] = None,
) -> Dict[str, str]:
    """Prepare pocket data with a scaffold constraint for conditional generation.

    Parameters
    ----------
    scaffold_smiles : str
        SMILES of the molecular scaffold to condition on.
    """
    data_dir = data_dir or _config.get("data_dir", "/app/workdir/tamgen_data")
    os.makedirs(data_dir, exist_ok=True)

    subset_name = f"gen_{pdb_id.lower()}"

    csv_path = os.path.join(data_dir, f"_tmp_scaffold_{pdb_id}.csv")
    with open(csv_path, "w", newline="") as fh:
        fh.write("pdb_id,center_x,center_y,center_z\n")
        fh.write(f"{pdb_id},{center_x},{center_y},{center_z}\n")

    scaffold_file = os.path.join(data_dir, f"_scaffold_{pdb_id}.txt")
    with open(scaffold_file, "w") as fh:
        fh.write(scaffold_smiles + "\n")

    script = os.path.join(
        TAMGEN_ROOT,
        "scripts",
        "build_data",
        "prepare_pdb_ids_center_scaffold.py",
    )
    cmd = [
        sys.executable, script, csv_path, subset_name,
        "-o", data_dir, "-t", str(threshold),
        "--scaffold-file", scaffold_file,
    ]
    if pdb_path:
        cmd.extend(["-pp", str(pdb_path)])

    logger.info(f"Preparing scaffold-constrained pocket (scaffold={scaffold_smiles!r})")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=TAMGEN_ROOT)

    if result.returncode != 0:
        logger.error(f"Scaffold preparation STDERR:\n{result.stderr}")
        raise RuntimeError(
            f"Scaffold preparation failed: {result.stderr[-500:]}"
        )

    logger.info(f"Scaffold data ready: subset={subset_name}")
    _safe_remove(csv_path)
    _safe_remove(scaffold_file)

    return {"data_dir": data_dir, "subset_name": subset_name}


# ============================================================================
# MOLECULE GENERATION
# ============================================================================

def generate_molecules(
    data_dir: str,
    subset_name: str,
    num_molecules: int = 50,
    beam_size: int = 20,
    beta: float = 1.0,
    seed: int = 42,
    checkpoint: Optional[str] = None,
    use_conditional: bool = True,
    max_seeds: int = 101,
) -> List[Dict[str, Any]]:
    """Generate molecules for a prepared protein pocket using TamGenDemo.

    Parameters
    ----------
    data_dir : str
        Directory produced by ``prepare_pocket_*``.
    subset_name : str
        Dataset subset name (e.g. ``"gen_1iep"``).
    num_molecules : int
        Target number of unique valid molecules.
    beam_size : int
        Beam width (higher → more diverse hypotheses per step).
    beta : float
        VAE β – controls diversity (higher → more exploration).
    seed : int
        Starting random seed.
    checkpoint : str, optional
        Model checkpoint path.  Default: CrossDocked-PDB-A10.
    use_conditional : bool
        Use conditional (VAE) generation.
    max_seeds : int
        Maximum number of random seeds to iterate over.

    Returns
    -------
    list[dict]
        Each dict has ``smiles``, ``valid``, plus molecular properties.
    """
    checkpoint = checkpoint or CHECKPOINT_CROSSDOCK

    orig_dir = os.getcwd()
    try:
        os.chdir(TAMGEN_ROOT)
        if TAMGEN_ROOT not in sys.path:
            sys.path.insert(0, TAMGEN_ROOT)

        from TamGen_Demo import TamGenDemo  # noqa: E402

        logger.info(f"Loading TamGen model from {checkpoint}")
        model = TamGenDemo(
            ckpt=checkpoint,
            data=data_dir,
            use_conditional=use_conditional,
        )

        logger.info(f"Loading dataset subset: {subset_name}")
        model.reload_data(subset_name)

        # Override beam args that TamGenDemo hard-codes
        model.args.beam = beam_size
        model.args.nbest = beam_size
        model.args.sample_beta = beta

        logger.info(
            f"Generating up to {num_molecules} molecules "
            f"(beam={beam_size}, beta={beta}, max_seeds={max_seeds})"
        )
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)

        results_set, ref_compound = model.sample(
            m_sample=num_molecules,
            use_cuda=torch.cuda.is_available(),
            maxseed=max_seeds,
        )

        logger.info(f"Generated {len(results_set)} unique valid molecules")

    finally:
        os.chdir(orig_dir)

    # Build structured output with properties
    molecules: List[Dict[str, Any]] = []
    for smi, mol in results_set.items():
        mol_info = _compute_mol_properties(smi, mol)
        molecules.append(mol_info)

    molecules.sort(key=lambda x: x.get("qed", 0), reverse=True)

    # Persist incrementally
    _save_molecules_csv(molecules)

    return molecules


def generate_molecules_cli(
    data_dir: str,
    subset_name: str,
    beam_size: int = 20,
    beta: float = 1.0,
    seed: int = 42,
    checkpoint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Generate molecules via the TamGen CLI (``generate.py``).

    Useful when you want subprocess isolation or need to pipe large outputs.

    Returns
    -------
    list[dict]
        Parsed molecules with properties.
    """
    checkpoint = checkpoint or CHECKPOINT_CROSSDOCK
    output_dir = _config.get("output_dir", "/output")

    cmd = [
        sys.executable,
        os.path.join(TAMGEN_ROOT, "generate.py"),
        data_dir,
        "-s", "tg", "-t", "m1",
        "--task", "translation_coord",
        "--path", checkpoint,
        "--gen-subset", subset_name,
        "--beam", str(beam_size),
        "--nbest", str(beam_size),
        "--max-tokens", "1024",
        "--seed", str(seed),
        "--sample-beta", str(beta),
        "--use-src-coord",
        "--gen-vae",
    ]

    logger.info(f"CLI generation: subset={subset_name}, beam={beam_size}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=TAMGEN_ROOT)

    # Save raw output regardless
    raw_path = os.path.join(output_dir, f"raw_output_{subset_name}.txt")
    with open(raw_path, "w") as fh:
        fh.write(result.stdout)

    if result.returncode != 0:
        logger.error(f"generate.py STDERR:\n{result.stderr}")
        raise RuntimeError(f"CLI generation failed: {result.stderr[-500:]}")

    molecules = _parse_raw_output(result.stdout)
    logger.info(f"CLI generated {len(molecules)} unique molecules")

    _save_molecules_csv(molecules)
    return molecules


# ============================================================================
# ANALYSIS  &  PROPERTIES
# ============================================================================

def validate_molecules(smiles_list: List[str]) -> List[Dict[str, Any]]:
    """Validate SMILES and compute RDKit properties for each.

    Returns a list of property dicts (one per input SMILES).
    """
    results = [_compute_mol_properties(smi) for smi in smiles_list]
    valid = sum(1 for r in results if r.get("valid"))
    logger.info(
        f"Validated {len(smiles_list)} SMILES: {valid} valid, "
        f"{len(smiles_list) - valid} invalid"
    )
    return results


def compute_diversity(
    smiles_list: List[str],
    fingerprint: str = "morgan",
    radius: int = 2,
    nbits: int = 2048,
) -> Dict[str, Any]:
    """Compute pairwise Tanimoto diversity for a set of molecules."""
    from rdkit import Chem, DataStructs
    from rdkit.Chem import AllChem
    import numpy as np

    fps, valid_smi = [], []
    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            continue
        if fingerprint == "morgan":
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=nbits)
        else:
            fp = Chem.RDKFingerprint(mol, fpSize=nbits)
        fps.append(fp)
        valid_smi.append(smi)

    n = len(fps)
    if n < 2:
        return {"n_valid": n, "mean_diversity": 0.0}

    sims = []
    for i in range(n):
        for j in range(i + 1, n):
            sims.append(DataStructs.TanimotoSimilarity(fps[i], fps[j]))

    divs = [1.0 - s for s in sims]
    return {
        "n_valid": n,
        "mean_diversity": round(float(np.mean(divs)), 4),
        "min_diversity": round(float(np.min(divs)), 4),
        "max_diversity": round(float(np.max(divs)), 4),
        "mean_similarity": round(float(np.mean(sims)), 4),
    }


def summarize_generation(molecules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate statistics over a list of molecule property dicts."""
    import numpy as np

    valid = [m for m in molecules if m.get("valid")]
    if not valid:
        return {"total": len(molecules), "valid": 0}

    summary: Dict[str, Any] = {
        "total_generated": len(molecules),
        "valid_molecules": len(valid),
        "validity_rate": round(len(valid) / max(len(molecules), 1), 4),
        "unique_molecules": len({m["smiles"] for m in valid}),
    }

    for prop in ["molecular_weight", "logp", "qed", "tpsa", "heavy_atoms"]:
        vals = [m[prop] for m in valid if prop in m]
        if vals:
            arr = np.array(vals, dtype=float)
            summary[f"{prop}_mean"] = round(float(arr.mean()), 2)
            summary[f"{prop}_std"] = round(float(arr.std()), 2)
            summary[f"{prop}_min"] = round(float(arr.min()), 2)
            summary[f"{prop}_max"] = round(float(arr.max()), 2)

    lp = sum(1 for m in valid if m.get("lipinski_pass"))
    summary["lipinski_pass_rate"] = round(lp / len(valid), 4)

    return summary


def filter_molecules(
    molecules: List[Dict[str, Any]],
    mw_range: Optional[Tuple[float, float]] = None,
    logp_range: Optional[Tuple[float, float]] = None,
    qed_min: Optional[float] = None,
    hbd_max: Optional[int] = None,
    hba_max: Optional[int] = None,
    lipinski_only: bool = False,
) -> List[Dict[str, Any]]:
    """Filter molecules by drug-likeness criteria.

    Returns the subset that passes all specified filters.
    """
    out = []
    for m in molecules:
        if not m.get("valid"):
            continue
        if mw_range and not (mw_range[0] <= m.get("molecular_weight", 0) <= mw_range[1]):
            continue
        if logp_range and not (logp_range[0] <= m.get("logp", 0) <= logp_range[1]):
            continue
        if qed_min is not None and m.get("qed", 0) < qed_min:
            continue
        if hbd_max is not None and m.get("hbd", 0) > hbd_max:
            continue
        if hba_max is not None and m.get("hba", 0) > hba_max:
            continue
        if lipinski_only and not m.get("lipinski_pass"):
            continue
        out.append(m)

    logger.info(f"Filtered {len(molecules)} -> {len(out)} molecules")
    return out


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _compute_mol_properties(
    smiles: str, mol: "Optional[Chem.Mol]" = None  # noqa: F821
) -> Dict[str, Any]:
    """Compute a standard set of drug-likeness descriptors."""
    from rdkit import Chem
    from rdkit.Chem import Descriptors, QED, Crippen, rdMolDescriptors

    if mol is None:
        mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"smiles": smiles, "valid": False}

    canonical = Chem.MolToSmiles(mol)
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    hbd = rdMolDescriptors.CalcNumHBD(mol)
    hba = rdMolDescriptors.CalcNumHBA(mol)

    props = {
        "smiles": canonical,
        "valid": True,
        "molecular_weight": round(mw, 2),
        "logp": round(logp, 2),
        "hbd": hbd,
        "hba": hba,
        "tpsa": round(Descriptors.TPSA(mol), 2),
        "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(mol),
        "rings": rdMolDescriptors.CalcNumRings(mol),
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "qed": round(QED.qed(mol), 4),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
    }

    violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    props["lipinski_violations"] = violations
    props["lipinski_pass"] = violations == 0

    return props


def _parse_raw_output(raw_output: str) -> List[Dict[str, Any]]:
    """Parse ``generate.py`` stdout into molecule dicts."""
    from rdkit import Chem
    import numpy as np

    compounds: Dict[str, Dict] = {}

    for line in raw_output.splitlines():
        if not line.startswith("H-"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            score = float(parts[1])
            smi = parts[2].strip().replace(" ", "")
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                continue
            canonical = Chem.MolToSmiles(mol)
            if canonical not in compounds:
                compounds[canonical] = {"scores": [], "count": 0}
            compounds[canonical]["scores"].append(score)
            compounds[canonical]["count"] += 1
        except (ValueError, IndexError):
            continue

    molecules = []
    for canonical, info in compounds.items():
        props = _compute_mol_properties(canonical)
        props["avg_score"] = round(float(np.mean(info["scores"])), 4)
        props["n_occurrences"] = info["count"]
        molecules.append(props)

    molecules.sort(key=lambda x: x.get("avg_score", 0), reverse=True)
    return molecules


def _save_molecules_csv(molecules: List[Dict[str, Any]]) -> str:
    """Incrementally save molecules to CSV in the output directory."""
    output_dir = _config.get("output_dir", "/output")
    csv_path = os.path.join(output_dir, "generated_molecules.csv")

    if not molecules:
        return csv_path

    keys = [
        "smiles", "valid", "molecular_weight", "logp", "hbd", "hba",
        "tpsa", "rotatable_bonds", "rings", "aromatic_rings", "heavy_atoms",
        "qed", "formula", "lipinski_violations", "lipinski_pass",
    ]
    # Include extra keys that may be present
    extra = [k for k in molecules[0] if k not in keys]
    keys.extend(extra)

    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(molecules)

    logger.info(f"Saved {len(molecules)} molecules to {csv_path}")
    return csv_path


def _safe_remove(path: str) -> None:
    """Remove a file if it exists, ignoring errors."""
    try:
        os.remove(path)
    except OSError:
        pass
