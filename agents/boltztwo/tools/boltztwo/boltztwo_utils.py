#!/usr/bin/env python3
"""Boltz-2 utilities library for Discovery platform workflows.

Provides helpers for biomolecular structure prediction and binding affinity
estimation using the Boltz-2 foundation model.  Covers input YAML generation,
CLI invocation, output parsing, confidence analysis, and visualization.

Schema notes (validated against boltz==2.2.1 schema parser):
  - Top-level entity types are EXACTLY: protein, dna, rna, ligand
  - A ligand entity carries either ``smiles: <str>`` or ``ccd: <str>`` inside it
  - Per-residue pLDDT and PAE are stored as ``.npz`` files, not in the JSON
  - Affinity is enabled by adding a ``properties`` block referencing a ligand
    chain id, AND passing ``--affinity`` to the CLI
"""

import os
import sys
import glob
import json
import logging
import subprocess
import shutil
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/boltz_scratch"
CACHE_DIR = "/cache"
BOLTZ_CMD = "boltz"

# Stdout patterns that indicate Boltz silently skipped an input despite exit 0
_SILENT_FAILURE_PATTERNS = (
    "Failed to process",
    "Skipping",
    "Error: Missing MSA",
)


# ============= SETUP FUNCTIONS =============

def quick_setup(
    input_dir: str = "/input",
    output_dir: str = "/output",
    work_dir: str = "/workdir",
) -> None:
    """Initialize logging, create directories, copy input files."""
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    for d in (WORK_DIR, OUTPUT_DIR, SCRATCH_DIR):
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.isdir(INPUT_DIR) else 'none'}")


def _copy_input_files() -> None:
    """Copy input files to working directory (with same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.isdir(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def quick_finish() -> None:
    """Copy working-directory outputs to /output."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = [
        "*.cif", "*.pdb", "*.json", "*.csv", "*.png", "*.yaml",
        "*.log", "*.out", "*.npz",
    ]
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    boltz_out = os.path.join(WORK_DIR, "boltz_results")
    if os.path.isdir(boltz_out):
        dst = os.path.join(OUTPUT_DIR, "boltz_results")
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(boltz_out, dst)
    logging.info("Outputs copied to /output")


def save_final_results(
    results: Dict,
    output_files: Optional[Dict] = None,
    file_descriptions: Optional[Dict] = None,
    status: str = "completed",
) -> None:
    """Save final results to JSON file (MANDATORY for every script)."""
    final_data: Dict[str, Any] = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    path = os.path.join(OUTPUT_DIR, "final_results.json")
    with open(path, "w") as f:
        json.dump(final_data, f, indent=2, default=str)
    logging.info(f"Saved final_results.json -> {path}")


# ============= INPUT YAML GENERATION =============

def build_input_yaml(
    sequences: List[Dict],
    output_path: str = "boltz_input.yaml",
    binder: Optional[str] = None,
) -> str:
    """Build a Boltz-2 input YAML file from a list of sequence definitions.

    Each entry in ``sequences`` is a dict with ONE top-level key indicating the
    entity type: ``protein``, ``rna``, ``dna``, or ``ligand``.  A ``ligand``
    entry carries either ``smiles`` or ``ccd`` inside it.

    Example ``sequences`` list::

        [
            {"protein": {"id": "A", "sequence": "MKTAYIA..."}},
            {"ligand":  {"id": "B", "smiles": "CCO"}},
            {"ligand":  {"id": "C", "ccd": "ATP"}},
            {"rna":     {"id": "D", "sequence": "AUGCAUGC"}},
        ]

    Args:
        sequences: List of entity dicts.
        output_path: Where to write the YAML file.
        binder: Optional chain id of a ligand to enable affinity prediction
            on (adds a ``properties.affinity.binder`` block).  The chain id
            must reference one of the ligand entries.

    Returns:
        Absolute path of the written YAML file.
    """
    data: Dict[str, Any] = {"version": 1, "sequences": sequences}

    if binder is not None:
        ligand_ids: List[str] = []
        for entry in sequences:
            if "ligand" in entry:
                lid = entry["ligand"].get("id")
                if isinstance(lid, list):
                    ligand_ids.extend(lid)
                elif lid is not None:
                    ligand_ids.append(lid)
        if binder not in ligand_ids:
            raise ValueError(
                f"binder='{binder}' must reference a ligand chain id. "
                f"Available ligand ids: {ligand_ids}"
            )
        data["properties"] = [{"affinity": {"binder": binder}}]

    abs_path = os.path.join(WORK_DIR, output_path)
    with open(abs_path, "w") as fh:
        yaml.dump(data, fh, default_flow_style=False, sort_keys=False)
    logging.info(f"Wrote Boltz-2 input YAML: {abs_path}")
    return abs_path


def protein_entity(chain_id: str, sequence: str, msa: Optional[str] = None) -> Dict:
    """Create a protein entity dict for ``build_input_yaml``.

    Returns:
        ``{"protein": {"id": chain_id, "sequence": sequence, ...}}``
    """
    if not sequence or not isinstance(sequence, str):
        raise ValueError(f"protein_entity: sequence must be a non-empty string, got {sequence!r}")
    entry: Dict[str, Any] = {"id": chain_id, "sequence": sequence}
    if msa:
        entry["msa"] = msa
    return {"protein": entry}


def _validate_smiles(smiles: str) -> str:
    """Validate a SMILES string using rdkit; return canonical form."""
    try:
        from rdkit import Chem
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
    except ImportError:
        logging.warning("rdkit not available, skipping SMILES validation")
        return smiles

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r} (rdkit could not parse)")
    return Chem.MolToSmiles(mol)


def ligand_entity_smiles(chain_id: str, smiles: str, validate: bool = True) -> Dict:
    """Create a small-molecule ligand entity from a SMILES string.

    Returns the canonical Boltz-2 schema:
    ``{"ligand": {"id": chain_id, "smiles": <smiles>}}``
    """
    if validate:
        smiles = _validate_smiles(smiles)
    return {"ligand": {"id": chain_id, "smiles": smiles}}


def ligand_entity_ccd(chain_id: str, ccd_code: str) -> Dict:
    """Create a small-molecule ligand entity from a CCD code.

    Returns the canonical Boltz-2 schema:
    ``{"ligand": {"id": chain_id, "ccd": <code>}}``
    """
    if not ccd_code or not isinstance(ccd_code, str):
        raise ValueError(f"ccd_code must be a non-empty string, got {ccd_code!r}")
    return {"ligand": {"id": chain_id, "ccd": ccd_code}}


def rna_entity(chain_id: str, sequence: str) -> Dict:
    """Create an RNA entity dict.

    Returns: ``{"rna": {"id": chain_id, "sequence": sequence}}``
    """
    if not sequence:
        raise ValueError("rna_entity: sequence must be non-empty")
    return {"rna": {"id": chain_id, "sequence": sequence}}


def dna_entity(chain_id: str, sequence: str) -> Dict:
    """Create a DNA entity dict.

    Returns: ``{"dna": {"id": chain_id, "sequence": sequence}}``
    """
    if not sequence:
        raise ValueError("dna_entity: sequence must be non-empty")
    return {"dna": {"id": chain_id, "sequence": sequence}}


def _yaml_has_msa(yaml_path: str) -> bool:
    """Return True if every protein entry in the YAML carries an ``msa`` field."""
    try:
        with open(yaml_path) as fh:
            data = yaml.safe_load(fh)
        seqs = data.get("sequences", [])
        proteins = [s.get("protein") for s in seqs if "protein" in s]
        if not proteins:
            return True
        return all("msa" in p for p in proteins)
    except Exception:
        return False


# ============= PREDICTION =============

def run_boltz_predict(
    input_yaml: str,
    out_dir: str = "boltz_results",
    cache_dir: str = CACHE_DIR,
    num_recycling_steps: int = 3,
    num_diffn_samples: int = 1,
    num_steps: int = 200,
    use_affinity: bool = False,
    auto_msa: bool = True,
    extra_args: Optional[List[str]] = None,
    timeout_seconds: int = 3600,
) -> Dict[str, Any]:
    """Run ``boltz predict`` and return a summary dict.

    Validates that the prediction actually produced output, not just that
    the CLI exited 0.  Boltz can silently skip inputs (e.g. missing MSAs)
    while still returning success.

    Returns:
        Dict with keys: ``success`` (bool), ``out_dir`` (abs path),
        ``command``, ``elapsed_s``, ``stdout``, ``stderr``, ``num_structures``,
        ``parse_error`` (str or None).
    """
    abs_out = os.path.join(WORK_DIR, out_dir)
    os.makedirs(abs_out, exist_ok=True)

    cmd = [
        BOLTZ_CMD, "predict", input_yaml,
        "--out_dir", abs_out,
        "--cache", cache_dir,
        "--recycling_steps", str(num_recycling_steps),
        "--diffusion_samples", str(num_diffn_samples),
        "--sampling_steps", str(num_steps),
    ]
    # NOTE: Boltz-2 does NOT have a --affinity CLI flag.  Affinity is enabled
    # purely by including a ``properties: [{affinity: {binder: <id>}}]`` block
    # in the input YAML (see ``build_input_yaml(binder=...)``).  The
    # ``use_affinity`` parameter is kept for API compatibility but is a no-op
    # at the CLI level; it only serves as a sanity check.
    if use_affinity:
        # Light sanity check: warn if YAML lacks the affinity properties block
        try:
            with open(input_yaml) as _fh:
                _ydata = yaml.safe_load(_fh)
            _props = _ydata.get("properties") or []
            _has_aff = any("affinity" in p for p in _props)
            if not _has_aff:
                logging.warning(
                    "use_affinity=True but input YAML lacks a "
                    "'properties.affinity.binder' block; affinity will NOT be "
                    "predicted. Use build_input_yaml(binder=<chain_id>)."
                )
        except Exception:
            pass

    user_extras = list(extra_args) if extra_args else []
    if auto_msa and "--use_msa_server" not in user_extras and not _yaml_has_msa(input_yaml):
        logging.info("Auto-injecting --use_msa_server (no MSAs found in input YAML)")
        user_extras.append("--use_msa_server")
    cmd.extend(user_extras)

    logging.info(f"Running: {' '.join(cmd)}")
    t0 = time.time()
    stdout_text = ""
    stderr_text = ""
    returncode = -1
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        elapsed = time.time() - t0
        stdout_text = result.stdout or ""
        stderr_text = result.stderr or ""
        returncode = result.returncode
        logging.info(f"boltz predict completed in {elapsed:.1f}s (exit={returncode})")
        if stdout_text:
            logging.info(f"STDOUT:\n{stdout_text[-2000:]}")
        if returncode != 0 and stderr_text:
            logging.error(f"STDERR:\n{stderr_text[-2000:]}")
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        logging.error(f"boltz predict timed out after {elapsed:.0f}s")
        return {
            "success": False, "out_dir": abs_out, "command": " ".join(cmd),
            "elapsed_s": round(elapsed, 1), "stdout": "",
            "stderr": f"Timed out after {timeout_seconds}s",
            "num_structures": 0, "parse_error": "timeout",
        }
    except Exception as e:
        logging.error(f"boltz predict failed: {e}")
        traceback.print_exc()
        return {
            "success": False, "out_dir": abs_out, "command": " ".join(cmd),
            "elapsed_s": round(time.time() - t0, 1), "stdout": "",
            "stderr": str(e), "num_structures": 0, "parse_error": "subprocess_exception",
        }

    cifs = find_output_structures(abs_out)
    parse_error: Optional[str] = None
    success = returncode == 0

    if returncode == 0:
        for pat in _SILENT_FAILURE_PATTERNS:
            if pat in stdout_text:
                parse_error = f"Boltz reported '{pat}' in stdout despite exit 0"
                success = False
                logging.error(parse_error)
                break
        if success and not cifs:
            parse_error = "Boltz exited 0 but produced no structure files"
            success = False
            logging.error(parse_error)
    else:
        parse_error = f"Non-zero exit code: {returncode}"

    return {
        "success": success,
        "out_dir": abs_out,
        "command": " ".join(cmd),
        "elapsed_s": round(time.time() - t0, 1),
        "stdout": stdout_text,
        "stderr": stderr_text,
        "num_structures": len(cifs),
        "parse_error": parse_error,
    }


# ============= OUTPUT PARSING =============

def find_output_structures(out_dir: str) -> List[str]:
    """Find all predicted structure files (.cif and .pdb)."""
    files = sorted(
        glob.glob(os.path.join(out_dir, "**", "*.cif"), recursive=True)
        + glob.glob(os.path.join(out_dir, "**", "*.pdb"), recursive=True)
    )
    logging.info(f"Found {len(files)} predicted structure(s) in {out_dir}")
    return files


def parse_confidence_json(out_dir: str) -> List[Dict[str, Any]]:
    """Parse ``confidence_<id>_model_<rank>.json`` files.

    Boltz-2 fields: ``confidence_score``, ``ptm``, ``iptm``, ``ligand_iptm``,
    ``protein_iptm``, ``complex_plddt``, ``complex_iplddt``, ``complex_pde``,
    ``complex_ipde``, ``chains_ptm``, ``pair_chains_iptm``.
    """
    patterns = ["confidence*.json", "*confidence*.json"]
    found: List[str] = []
    for pat in patterns:
        found.extend(glob.glob(os.path.join(out_dir, "**", pat), recursive=True))
    found = sorted(set(found))

    results = []
    for fp in found:
        try:
            with open(fp) as fh:
                data = json.load(fh)
            data["source_file"] = fp
            data["model_rank"] = _parse_model_rank(Path(fp).stem)
            results.append(data)
            logging.info(f"Parsed confidence: {fp}")
        except Exception as e:
            logging.warning(f"Failed to parse {fp}: {e}")
    return results


def _parse_model_rank(stem: str) -> int:
    """Extract numeric model rank from 'confidence_xxx_model_2'."""
    parts = stem.split("_")
    for i, p in enumerate(parts):
        if p == "model" and i + 1 < len(parts):
            try:
                return int(parts[i + 1])
            except ValueError:
                pass
    return -1


def parse_affinity_output(out_dir: str) -> List[Dict[str, Any]]:
    """Parse ``affinity_<record_id>.json`` files."""
    found = sorted(set(
        glob.glob(os.path.join(out_dir, "**", "affinity_*.json"), recursive=True)
        + glob.glob(os.path.join(out_dir, "**", "*affinity*.json"), recursive=True)
    ))

    results = []
    for fp in found:
        try:
            with open(fp) as fh:
                data = json.load(fh)
            data["source_file"] = fp
            results.append(data)
            logging.info(f"Parsed affinity: {fp}")
        except Exception as e:
            logging.warning(f"Failed to parse {fp}: {e}")
    return results


def extract_affinity_summary(out_dir: str) -> Optional[Dict[str, Any]]:
    """Return the first affinity prediction with friendly aliases."""
    aff_list = parse_affinity_output(out_dir)
    if not aff_list:
        return None
    aff = dict(aff_list[0])
    if "affinity_pred_value" in aff and "pic50" not in aff:
        aff["pic50"] = aff["affinity_pred_value"]
    if "affinity_probability_binary" in aff and "binder_probability" not in aff:
        aff["binder_probability"] = aff["affinity_probability_binary"]
    return aff


def extract_plddt_per_residue(out_dir: str) -> Dict[str, List[float]]:
    """Extract per-residue pLDDT from ``plddt_*_model_*.npz`` files."""
    try:
        import numpy as np
    except ImportError:
        logging.error("numpy not available; cannot read plddt NPZ files")
        return {}

    npz_files = sorted(glob.glob(os.path.join(out_dir, "**", "plddt_*.npz"), recursive=True))
    if not npz_files:
        logging.warning(f"No plddt_*.npz files found under {out_dir}")
        return {}

    plddt_map: Dict[str, List[float]] = {}
    for fp in npz_files:
        try:
            with np.load(fp) as data:
                if "plddt" not in data.files:
                    logging.warning(f"{fp} has no 'plddt' key; keys={data.files}")
                    continue
                arr = data["plddt"]
            label = Path(fp).stem
            plddt_map[label] = arr.tolist()
            logging.info(f"Loaded pLDDT from {fp}: {len(plddt_map[label])} residues")
        except Exception as e:
            logging.warning(f"Failed to load {fp}: {e}")
    return plddt_map


def extract_pae_matrix(out_dir: str, model_rank: int = 0) -> Optional[Any]:
    """Load a PAE matrix from ``pae_*.npz``. Returns numpy array or None."""
    try:
        import numpy as np
    except ImportError:
        logging.error("numpy not available; cannot read pae NPZ files")
        return None

    candidates = sorted(
        glob.glob(os.path.join(out_dir, "**", f"pae_*_model_{model_rank}.npz"), recursive=True)
    )
    if not candidates:
        candidates = sorted(glob.glob(os.path.join(out_dir, "**", "pae_*.npz"), recursive=True))
    if not candidates:
        logging.warning(f"No pae_*.npz files found under {out_dir}")
        return None

    fp = candidates[0]
    try:
        with np.load(fp) as data:
            if "pae" not in data.files:
                logging.warning(f"{fp} has no 'pae' key; keys={data.files}")
                return None
            return data["pae"]
    except Exception as e:
        logging.warning(f"Failed to load {fp}: {e}")
        return None


def summarize_prediction(out_dir: str) -> Dict[str, Any]:
    """Build a summary dict, picking the best model by ``confidence_score``."""
    structures = find_output_structures(out_dir)
    confidence = parse_confidence_json(out_dir)
    affinity = extract_affinity_summary(out_dir)
    plddt = extract_plddt_per_residue(out_dir)

    mean_plddts = {}
    for label, scores in plddt.items():
        if scores:
            mean_plddts[label] = round(sum(scores) / len(scores), 2)

    summary: Dict[str, Any] = {
        "num_structures": len(structures),
        "structure_files": [os.path.basename(s) for s in structures],
    }

    if confidence:
        ranked = sorted(
            confidence,
            key=lambda c: (-(c.get("confidence_score") or 0.0), c.get("model_rank", 99)),
        )
        best = ranked[0]
        summary["best_model_source"] = os.path.basename(best.get("source_file", ""))
        for key in (
            "confidence_score", "ptm", "iptm",
            "ligand_iptm", "protein_iptm",
            "complex_plddt", "complex_iplddt",
            "complex_pde", "complex_ipde",
        ):
            if key in best:
                summary[key] = best[key]
        summary["num_models"] = len(confidence)

    if mean_plddts:
        summary["mean_plddt"] = mean_plddts

    if affinity:
        summary["affinity"] = affinity

    return summary


# ============= VISUALIZATION =============

def plot_plddt(
    plddt_scores: Dict[str, List[float]],
    output_file: str = "plddt_plot.png",
    title: str = "Per-Residue pLDDT",
) -> str:
    """Plot per-residue pLDDT confidence scores."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 4))
    for label, scores in plddt_scores.items():
        ax.plot(range(1, len(scores) + 1), scores, label=label, linewidth=0.8)
    ax.set_xlabel("Residue Index")
    ax.set_ylabel("pLDDT")
    ax.set_title(title)
    ax.set_ylim(0, 100)
    ax.axhline(y=90, color="green", linestyle="--", alpha=0.5, label="Very high (>90)")
    ax.axhline(y=70, color="orange", linestyle="--", alpha=0.5, label="Confident (>70)")
    ax.axhline(y=50, color="red", linestyle="--", alpha=0.5, label="Low (<50)")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    abs_path = os.path.join(OUTPUT_DIR, output_file)
    plt.savefig(abs_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved pLDDT plot: {abs_path}")
    return abs_path


def plot_pae(
    pae_matrix: Any,
    output_file: str = "pae_plot.png",
    title: str = "Predicted Aligned Error (PAE)",
) -> str:
    """Plot PAE matrix as heatmap."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    arr = np.array(pae_matrix)
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(arr, cmap="Greens_r", vmin=0, vmax=30)
    ax.set_xlabel("Scored Residue")
    ax.set_ylabel("Aligned Residue")
    ax.set_title(title)
    plt.colorbar(im, ax=ax, label="Expected Position Error (A)")
    plt.tight_layout()

    abs_path = os.path.join(OUTPUT_DIR, output_file)
    plt.savefig(abs_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved PAE plot: {abs_path}")
    return abs_path


def plot_affinity_comparison(
    labels: List[str],
    pic50_values: List[float],
    output_file: str = "affinity_comparison.png",
    title: str = "Predicted Binding Affinity (pIC50)",
) -> str:
    """Bar chart comparing predicted pIC50 across candidates."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.8), 5))
    colors = ["#2196F3" if v >= 6.0 else "#FFC107" if v >= 4.0 else "#F44336"
              for v in pic50_values]
    ax.bar(labels, pic50_values, color=colors, edgecolor="black", linewidth=0.5)
    ax.set_xlabel("Candidate")
    ax.set_ylabel("pIC50")
    ax.set_title(title)
    ax.axhline(y=6.0, color="green", linestyle="--", alpha=0.5, label="Strong (>6)")
    ax.axhline(y=4.0, color="orange", linestyle="--", alpha=0.5, label="Moderate (>4)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    abs_path = os.path.join(OUTPUT_DIR, output_file)
    plt.savefig(abs_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logging.info(f"Saved affinity plot: {abs_path}")
    return abs_path


# ============= BATCH PROCESSING =============

def batch_predict(
    input_yamls: List[str],
    out_base_dir: str = "batch_results",
    cache_dir: str = CACHE_DIR,
    num_recycling_steps: int = 3,
    num_diffn_samples: int = 1,
    num_steps: int = 200,
    use_affinity: bool = False,
    auto_msa: bool = True,
    extra_args: Optional[List[str]] = None,
    timeout_seconds: int = 3600,
) -> Tuple[List[Dict], List[Dict]]:
    """Sequential batch with checkpointing."""
    successes: List[Dict] = []
    failures: List[Dict] = []

    os.makedirs(os.path.join(WORK_DIR, out_base_dir), exist_ok=True)

    ckpt_path = os.path.join(OUTPUT_DIR, "batch_checkpoint.json")
    done_inputs = set()
    if os.path.exists(ckpt_path):
        with open(ckpt_path) as fh:
            ckpt = json.load(fh)
        successes = ckpt.get("successes", [])
        failures = ckpt.get("failures", [])
        done_inputs = {s["input"] for s in successes} | {f["input"] for f in failures}
        logging.info(f"Resuming batch: {len(done_inputs)}/{len(input_yamls)} already done")

    for i, inp_yaml in enumerate(input_yamls):
        if inp_yaml in done_inputs:
            continue

        name = Path(inp_yaml).stem
        sub_out = os.path.join(out_base_dir, name)
        logging.info(f"Batch [{i+1}/{len(input_yamls)}]: {name}")

        try:
            result = run_boltz_predict(
                input_yaml=inp_yaml,
                out_dir=sub_out,
                cache_dir=cache_dir,
                num_recycling_steps=num_recycling_steps,
                num_diffn_samples=num_diffn_samples,
                num_steps=num_steps,
                use_affinity=use_affinity,
                auto_msa=auto_msa,
                extra_args=extra_args,
                timeout_seconds=timeout_seconds,
            )
            if result["success"]:
                summary = summarize_prediction(result["out_dir"])
                successes.append({
                    "input": inp_yaml,
                    "out_dir": result["out_dir"],
                    "summary": summary,
                })
            else:
                err = result.get("parse_error") or result["stderr"][:500]
                failures.append({"input": inp_yaml, "error": err})
        except Exception as e:
            failures.append({"input": inp_yaml, "error": str(e)[:500]})

        with open(ckpt_path, "w") as fh:
            json.dump({"successes": successes, "failures": failures}, fh, indent=2, default=str)

    logging.info(f"Batch complete: {len(successes)} succeeded, {len(failures)} failed")
    return successes, failures


# ============= HELPER UTILITIES =============

def read_fasta(fasta_path: str) -> List[Dict[str, str]]:
    """Read a FASTA file and return list of {id, sequence} dicts."""
    entries: List[Dict[str, str]] = []
    current_id = ""
    current_seq: List[str] = []
    with open(fasta_path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if current_id:
                    entries.append({"id": current_id, "sequence": "".join(current_seq)})
                current_id = line[1:].split()[0]
                current_seq = []
            elif line:
                current_seq.append(line)
    if current_id:
        entries.append({"id": current_id, "sequence": "".join(current_seq)})
    return entries


def fasta_to_boltz_yaml(
    fasta_path: str,
    output_yaml: str = "boltz_input.yaml",
    ligand_smiles: Optional[str] = None,
    ligand_ccd: Optional[str] = None,
    binder: Optional[str] = None,
) -> str:
    """Convert a FASTA file to a Boltz-2 input YAML."""
    entries = read_fasta(fasta_path)
    sequences: List[Dict] = []
    chain_ids = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    for i, entry in enumerate(entries):
        cid = chain_ids[i] if i < 26 else f"chain_{i}"
        sequences.append(protein_entity(cid, entry["sequence"]))

    if ligand_smiles:
        lig_id = chain_ids[len(entries)] if len(entries) < 26 else "L"
        sequences.append(ligand_entity_smiles(lig_id, ligand_smiles))
    elif ligand_ccd:
        lig_id = chain_ids[len(entries)] if len(entries) < 26 else "L"
        sequences.append(ligand_entity_ccd(lig_id, ligand_ccd))

    return build_input_yaml(sequences, output_yaml, binder=binder)


def copy_structures_to_output(out_dir: str) -> List[str]:
    """Copy predicted CIF/PDB structures to OUTPUT_DIR."""
    copied = []
    for ext in ("*.cif", "*.pdb"):
        for f in glob.glob(os.path.join(out_dir, "**", ext), recursive=True):
            dst = os.path.join(OUTPUT_DIR, os.path.basename(f))
            shutil.copy(f, dst)
            copied.append(dst)
    logging.info(f"Copied {len(copied)} structure file(s) to {OUTPUT_DIR}")
    return copied


def tool_cleanup(deep: bool = False) -> None:
    """Clean up scratch files between calculations."""
    try:
        if deep:
            cleared = 0
            if os.path.isdir(SCRATCH_DIR):
                for entry in os.scandir(SCRATCH_DIR):
                    if entry.is_file():
                        try:
                            os.remove(entry.path)
                            cleared += 1
                        except OSError:
                            pass
            if cleared:
                logging.info(f"Deep cleanup: cleared {cleared} scratch files")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")
