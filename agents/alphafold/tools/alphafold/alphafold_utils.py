#!/usr/bin/env python3
"""AlphaFold/ColabFold utilities library for Microsoft Discovery platform workflows.

Provides helper functions for protein structure prediction using ColabFold
(AlphaFold2 backend). Supports monomer and multimer predictions, MSA handling,
confidence analysis (pLDDT, PAE, pTM), AMBER relaxation, and visualization.
"""

import os
import sys
import glob
import json
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/tool_scratch"

# ============= SETUP FUNCTIONS =============

def quick_setup(input_dir: str = '/input', output_dir: str = '/output',
                work_dir: str = '/workdir') -> None:
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.

    Args:
        input_dir: Directory containing input files (mounted by Discovery)
        output_dir: Directory for output files (persisted after job)
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

    logging.info(f"Working directory: {WORK_DIR}")
    if os.path.exists(INPUT_DIR):
        logging.info(f"Input files: {os.listdir(INPUT_DIR)}")
    else:
        logging.info("No input directory found")

    # Log GPU availability
    try:
        import jax
        devices = jax.devices()
        logging.info(f"JAX devices: {devices}")
    except Exception:
        logging.info("JAX not available or no GPU detected")


def copy_input_files() -> None:
    """Copy input files to working directory (with same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy2(f, WORK_DIR)
            elif os.path.isdir(f):
                dest = os.path.join(WORK_DIR, os.path.basename(f))
                if not os.path.exists(dest):
                    shutil.copytree(f, dest)


def copy_outputs() -> None:
    """Copy output files to output directory (with same-directory guard)."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.pdb', '*.cif', '*.json', '*.png', '*.csv', '*.a3m',
                '*.log', '*.out', '*.fasta', '*.fa']
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, '**', pattern), recursive=True):
            rel = os.path.relpath(f, WORK_DIR)
            dest = os.path.join(OUTPUT_DIR, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not os.path.exists(dest):
                shutil.copy2(f, dest)
    logging.info("Outputs copied to /output")


def quick_finish() -> None:
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None,
                       status: str = "completed") -> None:
    """Save final results to JSON file (MANDATORY for every script).

    Args:
        results: Dictionary of key results/metrics
        output_files: Dictionary mapping names to output file paths
        file_descriptions: Dictionary mapping names to descriptions
        status: Job status ("completed" or "failed")
    """
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions

    def _convert(obj):
        """Convert numpy types for JSON serialization."""
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return obj

    out_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(out_path, 'w') as f:
        json.dump(final_data, f, indent=2, default=_convert)
    logging.info(f"Saved final_results.json to {out_path}")


# ============= FASTA UTILITIES =============

def write_fasta(sequences: Dict[str, str], output_path: str) -> str:
    """Write sequences to FASTA file.

    Args:
        sequences: Dict mapping sequence names to amino acid sequences
        output_path: Path to write FASTA file

    Returns:
        Path to written FASTA file
    """
    with open(output_path, 'w') as f:
        for name, seq in sequences.items():
            seq_clean = seq.strip().upper().replace(' ', '').replace('\n', '')
            f.write(f">{name}\n{seq_clean}\n")
    logging.info(f"Wrote FASTA with {len(sequences)} sequence(s) to {output_path}")
    return output_path


def write_multimer_fasta(chains: Dict[str, str], output_path: str,
                         complex_name: str = "complex") -> str:
    """Write multimer FASTA for complex prediction.

    ColabFold uses ':' separator between chains in a single FASTA entry
    to indicate they should be predicted as a complex.

    Args:
        chains: Dict mapping chain names to sequences
        output_path: Path to write FASTA file
        complex_name: Name for the complex entry

    Returns:
        Path to written FASTA file
    """
    seqs = [seq.strip().upper().replace(' ', '').replace('\n', '')
            for seq in chains.values()]
    combined_seq = ":".join(seqs)
    chain_names = ",".join(chains.keys())
    with open(output_path, 'w') as f:
        f.write(f">{complex_name} chains={chain_names}\n{combined_seq}\n")
    logging.info(f"Wrote multimer FASTA with {len(chains)} chains to {output_path}")
    return output_path


def read_fasta(fasta_path: str) -> Dict[str, str]:
    """Read sequences from FASTA file.

    Args:
        fasta_path: Path to FASTA file

    Returns:
        Dict mapping sequence names to sequences

    Raises:
        FileNotFoundError: If fasta_path does not exist
    """
    if not os.path.exists(fasta_path):
        raise FileNotFoundError(f"FASTA file not found: {fasta_path}")

    sequences = {}
    current_name = None
    current_seq = []

    with open(fasta_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('>'):
                if current_name is not None:
                    sequences[current_name] = ''.join(current_seq)
                current_name = line[1:].split()[0]
                current_seq = []
            elif line:
                current_seq.append(line)
    if current_name is not None:
        sequences[current_name] = ''.join(current_seq)

    return sequences


def validate_sequence(sequence: str) -> Tuple[bool, str]:
    """Validate amino acid sequence.

    Args:
        sequence: Amino acid sequence string

    Returns:
        Tuple of (is_valid, message)
    """
    standard_aa = set('ACDEFGHIKLMNPQRSTVWY')
    extended_aa = standard_aa | set('XUBZJO')
    seq_clean = sequence.strip().upper().replace(' ', '').replace('\n', '')

    if not seq_clean:
        return False, "Empty sequence"
    if len(seq_clean) < 10:
        return False, f"Sequence too short ({len(seq_clean)} residues, minimum 10)"
    if len(seq_clean) > 4000:
        return False, (f"Sequence too long ({len(seq_clean)} residues, "
                       "maximum ~4000 for GPU memory)")

    invalid_chars = set(seq_clean) - extended_aa
    if invalid_chars:
        return False, f"Invalid characters: {invalid_chars}"

    return True, f"Valid sequence ({len(seq_clean)} residues)"


def validate_fasta(fasta_path: str) -> Dict[str, Any]:
    """Validate all sequences in a FASTA file.

    Args:
        fasta_path: Path to FASTA file

    Returns:
        Dict with validation results for each sequence
    """
    sequences = read_fasta(fasta_path)
    results = {"valid": True, "sequences": {}, "total": len(sequences)}

    for name, seq in sequences.items():
        is_valid, msg = validate_sequence(seq)
        results["sequences"][name] = {
            "valid": is_valid,
            "message": msg,
            "length": len(seq.strip())
        }
        if not is_valid:
            results["valid"] = False

    return results


# ============= COLABFOLD EXECUTION =============

def run_colabfold_batch(
    input_path: str,
    output_dir: str,
    num_recycle: int = 3,
    num_models: int = 5,
    num_seeds: int = 1,
    use_amber: bool = True,
    use_templates: bool = False,
    model_type: str = "auto",
    msa_mode: str = "mmseqs2_uniref_env",
    pair_mode: str = "unpaired_paired",
    num_relax: int = 1,
    use_gpu_relax: bool = True,
    extra_args: Optional[List[str]] = None,
    timeout: int = 7200
) -> Dict[str, Any]:
    """Run ColabFold batch prediction.

    Args:
        input_path: Path to FASTA file, directory of FASTAs, or a3m MSA file
        output_dir: Output directory for predictions
        num_recycle: Number of recycles (default 3, more = better but slower)
        num_models: Number of models to predict (1-5)
        num_seeds: Number of random seeds per model
        use_amber: Whether to relax with AMBER force field
        use_templates: Whether to use PDB templates
        model_type: Model type ("auto" auto-detects monomer/multimer,
                    "alphafold2_ptm" for monomer, "alphafold2_multimer_v3"
                    for complex)
        msa_mode: MSA mode ("mmseqs2_uniref_env", "mmseqs2_uniref",
                  "single_sequence")
        pair_mode: Pair mode for multimer ("unpaired_paired", "paired",
                   "unpaired")
        num_relax: Number of top models to relax (0=no relaxation)
        use_gpu_relax: Use GPU for AMBER relaxation
        extra_args: Additional command line arguments
        timeout: Timeout in seconds (default 2h)

    Returns:
        Dict with prediction results, file paths, and success status
    """
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "colabfold_batch",
        input_path,
        output_dir,
        "--num-recycle", str(num_recycle),
        "--num-models", str(num_models),
        "--num-seeds", str(num_seeds),
        "--msa-mode", msa_mode,
        "--pair-mode", pair_mode,
    ]

    if model_type != "auto":
        cmd.extend(["--model-type", model_type])

    if use_amber:
        cmd.append("--amber")
        cmd.extend(["--num-relax", str(num_relax)])
        if use_gpu_relax:
            cmd.append("--use-gpu-relax")

    if use_templates:
        cmd.append("--templates")

    if extra_args:
        cmd.extend(extra_args)

    logging.info(f"Running ColabFold: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORK_DIR
        )

        if result.stdout:
            logging.info(f"ColabFold stdout (last 2000 chars):\n{result.stdout[-2000:]}")
        if result.stderr:
            logging.info(f"ColabFold stderr (last 2000 chars):\n{result.stderr[-2000:]}")

        if result.returncode != 0:
            logging.error(f"ColabFold failed with return code {result.returncode}")
            return {
                "success": False,
                "error": result.stderr[-1000:] if result.stderr else "Unknown error",
                "returncode": result.returncode,
                "output_dir": output_dir
            }

        # Parse results
        parsed = parse_colabfold_output(output_dir)
        parsed["success"] = True
        parsed["output_dir"] = output_dir
        return parsed

    except subprocess.TimeoutExpired:
        logging.error(f"ColabFold timed out after {timeout}s")
        # Try to parse any partial results
        partial = parse_colabfold_output(output_dir)
        partial["success"] = False
        partial["error"] = f"Timeout after {timeout}s"
        partial["output_dir"] = output_dir
        return partial
    except FileNotFoundError:
        logging.error("colabfold_batch not found. Is ColabFold installed?")
        return {"success": False, "error": "colabfold_batch not found",
                "output_dir": output_dir}
    except Exception as e:
        logging.error(f"ColabFold error: {e}")
        return {"success": False, "error": str(e), "output_dir": output_dir}


def run_mmseqs2_search(
    fasta_path: str,
    output_dir: str,
    db_path: Optional[str] = None,
    threads: Optional[int] = None,
    sensitivity: float = 8.0
) -> Optional[str]:
    """Run MMseqs2 for MSA generation (local database search).

    Args:
        fasta_path: Input FASTA file
        output_dir: Output directory for MSA results
        db_path: Path to MMseqs2 database (required for local search)
        threads: Number of CPU threads (default: all available)
        sensitivity: Search sensitivity (1-8, higher = more sensitive)

    Returns:
        Path to generated a3m MSA file, or None if search failed
    """
    if threads is None:
        threads = os.cpu_count() or 4

    os.makedirs(output_dir, exist_ok=True)

    if not db_path:
        logging.warning("No local MMseqs2 database specified. "
                        "Use colabfold_batch with --msa-mode mmseqs2_uniref_env "
                        "for API-based MSA generation.")
        return None

    cmd = [
        "colabfold_search",
        fasta_path,
        db_path,
        output_dir,
        "--threads", str(threads),
        "-s", str(sensitivity),
    ]

    logging.info(f"Running MMseqs2 search: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if result.stdout:
            logging.info(result.stdout[-500:])
    except subprocess.CalledProcessError as e:
        logging.error(f"MMseqs2 search failed: {e.stderr}")
        return None
    except FileNotFoundError:
        logging.error("colabfold_search not found")
        return None

    a3m_files = sorted(glob.glob(os.path.join(output_dir, "*.a3m")))
    if a3m_files:
        logging.info(f"MSA generated: {a3m_files[0]}")
        return a3m_files[0]

    logging.warning("No a3m files generated by MMseqs2 search")
    return None


# ============= RESULT PARSING =============

def parse_colabfold_output(output_dir: str) -> Dict[str, Any]:
    """Parse ColabFold prediction output directory.

    Args:
        output_dir: Directory containing ColabFold output

    Returns:
        Dict with parsed results including models, scores, and file paths
    """
    results = {
        "models": [],
        "pdb_files": [],
        "score_files": [],
        "pae_files": [],
        "plot_files": [],
        "best_model": None,
        "best_plddt": None,
        "best_ptm": None,
        "num_models": 0,
    }

    # Find PDB files (ranked output)
    pdb_files = sorted(glob.glob(os.path.join(output_dir, "*rank_*.pdb")))
    if not pdb_files:
        pdb_files = sorted(glob.glob(os.path.join(output_dir, "**", "*rank_*.pdb"),
                                     recursive=True))
    if not pdb_files:
        pdb_files = sorted(glob.glob(os.path.join(output_dir, "*.pdb")))
    results["pdb_files"] = pdb_files
    results["num_models"] = len(pdb_files)

    # Find score JSON files
    score_files = sorted(glob.glob(os.path.join(output_dir, "*scores_rank_*.json")))
    if not score_files:
        score_files = sorted(glob.glob(os.path.join(output_dir, "**",
                                                     "*scores_rank_*.json"),
                                       recursive=True))
    results["score_files"] = score_files

    # Find plot files
    results["pae_files"] = sorted(glob.glob(os.path.join(output_dir, "*pae*.png")))
    results["plot_files"] = sorted(glob.glob(os.path.join(output_dir, "*.png")))

    # Parse individual model scores
    best_plddt = -1.0
    best_ptm = -1.0

    for sf in score_files:
        try:
            with open(sf) as f:
                scores = json.load(f)

            plddt_vals = scores.get("plddt", [0])
            model_info = {
                "score_file": sf,
                "mean_plddt": float(np.mean(plddt_vals)),
                "median_plddt": float(np.median(plddt_vals)),
                "min_plddt": float(np.min(plddt_vals)),
                "max_plddt": float(np.max(plddt_vals)),
                "ptm": float(scores.get("ptm", 0)),
            }

            if "iptm" in scores:
                model_info["iptm"] = float(scores["iptm"])
                model_info["ranking_confidence"] = (
                    0.8 * scores["iptm"] + 0.2 * scores.get("ptm", 0)
                )

            if "max_pae" in scores:
                model_info["max_pae"] = float(scores["max_pae"])

            results["models"].append(model_info)

            if model_info["mean_plddt"] > best_plddt:
                best_plddt = model_info["mean_plddt"]
            ptm_val = model_info["ptm"]
            if ptm_val > best_ptm:
                best_ptm = ptm_val

        except Exception as e:
            logging.warning(f"Could not parse score file {sf}: {e}")

    if best_plddt > 0:
        results["best_plddt"] = round(best_plddt, 2)
    if best_ptm > 0:
        results["best_ptm"] = round(best_ptm, 4)
    if pdb_files:
        results["best_model"] = pdb_files[0]  # rank_001 is best

    logging.info(f"Parsed {len(pdb_files)} models. "
                 f"Best pLDDT: {results['best_plddt']}, "
                 f"Best pTM: {results['best_ptm']}")

    return results


def extract_plddt_from_pdb(pdb_path: str) -> List[float]:
    """Extract per-residue pLDDT scores from AlphaFold PDB B-factor column.

    AlphaFold stores pLDDT confidence in the B-factor column of PDB files.
    This function extracts CA atom B-factors as per-residue pLDDT scores.

    Args:
        pdb_path: Path to PDB file from AlphaFold/ColabFold

    Returns:
        List of per-residue pLDDT scores

    Raises:
        FileNotFoundError: If PDB file doesn't exist
    """
    if not os.path.exists(pdb_path):
        raise FileNotFoundError(f"PDB file not found: {pdb_path}")

    plddt_scores = []
    seen_residues = set()

    with open(pdb_path, 'r') as f:
        for line in f:
            if line.startswith("ATOM") and len(line) >= 66:
                atom_name = line[12:16].strip()
                if atom_name == "CA":
                    chain = line[21]
                    resnum = line[22:26].strip()
                    res_id = f"{chain}_{resnum}"
                    if res_id not in seen_residues:
                        seen_residues.add(res_id)
                        try:
                            bfactor = float(line[60:66].strip())
                            plddt_scores.append(bfactor)
                        except ValueError:
                            pass

    logging.info(f"Extracted pLDDT for {len(plddt_scores)} residues from "
                 f"{os.path.basename(pdb_path)}")
    return plddt_scores


def extract_pae_matrix(score_file: str) -> Optional[np.ndarray]:
    """Extract Predicted Aligned Error (PAE) matrix from score file.

    Args:
        score_file: Path to ColabFold score JSON file

    Returns:
        2D numpy array of PAE values, or None if not available
    """
    try:
        with open(score_file) as f:
            scores = json.load(f)
        if "pae" in scores:
            pae = np.array(scores["pae"])
            logging.info(f"PAE matrix shape: {pae.shape}")
            return pae
    except Exception as e:
        logging.warning(f"Could not extract PAE from {score_file}: {e}")
    return None


# ============= ANALYSIS FUNCTIONS =============

def compute_confidence_metrics(score_file: str) -> Dict[str, float]:
    """Compute comprehensive confidence metrics from ColabFold score file.

    Args:
        score_file: Path to ColabFold score JSON file

    Returns:
        Dict with confidence metrics including pLDDT stats, pTM, iPTM, PAE
    """
    with open(score_file) as f:
        scores = json.load(f)

    metrics = {}

    if "plddt" in scores:
        plddt = np.array(scores["plddt"])
        metrics["mean_plddt"] = float(np.mean(plddt))
        metrics["median_plddt"] = float(np.median(plddt))
        metrics["min_plddt"] = float(np.min(plddt))
        metrics["max_plddt"] = float(np.max(plddt))
        metrics["std_plddt"] = float(np.std(plddt))
        metrics["plddt_above_90"] = float(np.sum(plddt > 90) / len(plddt) * 100)
        metrics["plddt_above_70"] = float(np.sum(plddt > 70) / len(plddt) * 100)
        metrics["plddt_below_50"] = float(np.sum(plddt < 50) / len(plddt) * 100)
        metrics["num_residues"] = int(len(plddt))

    if "ptm" in scores:
        metrics["ptm"] = float(scores["ptm"])

    if "iptm" in scores:
        metrics["iptm"] = float(scores["iptm"])
        metrics["ranking_confidence"] = (
            0.8 * float(scores["iptm"]) + 0.2 * float(scores.get("ptm", 0))
        )

    if "pae" in scores:
        pae = np.array(scores["pae"])
        metrics["mean_pae"] = float(np.mean(pae))
        metrics["max_pae"] = float(np.max(pae))
        metrics["median_pae"] = float(np.median(pae))

    return metrics


def classify_confidence(plddt: float) -> str:
    """Classify pLDDT confidence level per AlphaFold conventions.

    Args:
        plddt: pLDDT score (0-100)

    Returns:
        Confidence classification string
    """
    if plddt >= 90:
        return "Very high (pLDDT >= 90)"
    elif plddt >= 70:
        return "Confident (70 <= pLDDT < 90)"
    elif plddt >= 50:
        return "Low (50 <= pLDDT < 70)"
    else:
        return "Very low (pLDDT < 50)"


def rank_models(output_dir: str) -> List[Dict]:
    """Rank predicted models by confidence scores.

    Args:
        output_dir: ColabFold output directory

    Returns:
        Sorted list of model info dicts (best first)
    """
    models = []
    score_files = sorted(glob.glob(os.path.join(output_dir, "*scores_rank_*.json")))
    pdb_files = sorted(glob.glob(os.path.join(output_dir, "*rank_*.pdb")))

    for i, sf in enumerate(score_files):
        try:
            metrics = compute_confidence_metrics(sf)
            model = {
                "rank": i + 1,
                "score_file": sf,
                "pdb_file": pdb_files[i] if i < len(pdb_files) else None,
                **metrics
            }
            models.append(model)
        except Exception as e:
            logging.warning(f"Could not parse model {sf}: {e}")

    sort_key = ("ranking_confidence"
                if any("ranking_confidence" in m for m in models)
                else "mean_plddt")
    models.sort(key=lambda x: x.get(sort_key, 0), reverse=True)

    for i, m in enumerate(models):
        m["rank"] = i + 1

    return models


def summarize_prediction(output_dir: str) -> Dict[str, Any]:
    """Generate a comprehensive summary of a prediction run.

    Args:
        output_dir: ColabFold output directory

    Returns:
        Dict with summary statistics and model rankings
    """
    ranked = rank_models(output_dir)
    parsed = parse_colabfold_output(output_dir)

    summary = {
        "num_models": len(ranked),
        "best_plddt": parsed.get("best_plddt"),
        "best_ptm": parsed.get("best_ptm"),
        "best_model_file": parsed.get("best_model"),
        "num_pdb_files": len(parsed["pdb_files"]),
        "model_rankings": ranked,
    }

    if ranked:
        best = ranked[0]
        summary["best_model_metrics"] = {
            k: v for k, v in best.items()
            if k not in ("score_file", "pdb_file", "rank")
        }
        summary["confidence_class"] = classify_confidence(
            best.get("mean_plddt", 0)
        )

    return summary


# ============= VISUALIZATION =============

def plot_plddt(plddt_scores: List[float], output_file: str,
               title: str = "pLDDT per Residue") -> str:
    """Plot per-residue pLDDT confidence scores with AlphaFold color scheme.

    Args:
        plddt_scores: List of per-residue pLDDT values
        output_file: Path to save plot
        title: Plot title

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(12, 4))
    residues = range(1, len(plddt_scores) + 1)

    # AlphaFold color scheme
    colors = []
    for score in plddt_scores:
        if score >= 90:
            colors.append('#0053D6')    # Very high - blue
        elif score >= 70:
            colors.append('#65CBF3')    # Confident - light blue
        elif score >= 50:
            colors.append('#FFDB13')    # Low - yellow
        else:
            colors.append('#FF7D45')    # Very low - orange

    ax.bar(residues, plddt_scores, color=colors, width=1.0, edgecolor='none')
    ax.set_xlabel('Residue Position', fontsize=11)
    ax.set_ylabel('pLDDT Score', fontsize=11)
    ax.set_title(title, fontsize=13)
    ax.set_ylim(0, 100)
    ax.set_xlim(0.5, len(plddt_scores) + 0.5)

    # Reference lines
    for y, ls in [(90, '--'), (70, ':'), (50, '-.')]:
        ax.axhline(y=y, color='gray', linestyle=ls, alpha=0.4)

    # Legend
    legend_elements = [
        Patch(facecolor='#0053D6', label='Very high (>90)'),
        Patch(facecolor='#65CBF3', label='Confident (70-90)'),
        Patch(facecolor='#FFDB13', label='Low (50-70)'),
        Patch(facecolor='#FF7D45', label='Very low (<50)'),
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=8,
              framealpha=0.9)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved pLDDT plot: {output_file}")
    return output_file


def plot_pae(pae_matrix: np.ndarray, output_file: str,
             title: str = "Predicted Aligned Error (PAE)") -> str:
    """Plot Predicted Aligned Error heatmap.

    Args:
        pae_matrix: 2D numpy array of PAE values
        output_file: Path to save plot
        title: Plot title

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(pae_matrix, cmap='Greens_r', vmin=0, vmax=30)
    ax.set_xlabel('Scored Residue', fontsize=11)
    ax.set_ylabel('Aligned Residue', fontsize=11)
    ax.set_title(title, fontsize=13)
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label('Expected Position Error (Angstrom)', fontsize=10)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved PAE plot: {output_file}")
    return output_file


def plot_model_comparison(models: List[Dict], output_file: str,
                          title: str = "Model Comparison") -> str:
    """Plot comparison of model confidence scores.

    Args:
        models: List of model info dicts from rank_models()
        output_file: Path to save plot
        title: Overall title for the figure

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    has_iptm = any("iptm" in m for m in models)
    n_plots = 3 if has_iptm else 2
    fig, axes = plt.subplots(1, n_plots, figsize=(5 * n_plots, 5))
    if n_plots == 1:
        axes = [axes]

    ranks = [m["rank"] for m in models]
    plddts = [m.get("mean_plddt", 0) for m in models]
    ptms = [m.get("ptm", 0) for m in models]

    # pLDDT
    colors = [
        '#0053D6' if p >= 90 else '#65CBF3' if p >= 70
        else '#FFDB13' if p >= 50 else '#FF7D45'
        for p in plddts
    ]
    axes[0].bar(ranks, plddts, color=colors)
    axes[0].set_xlabel('Model Rank')
    axes[0].set_ylabel('Mean pLDDT')
    axes[0].set_title('pLDDT Comparison')
    axes[0].set_ylim(0, 100)

    # pTM
    axes[1].bar(ranks, ptms, color='#0053D6')
    axes[1].set_xlabel('Model Rank')
    axes[1].set_ylabel('pTM Score')
    axes[1].set_title('pTM Comparison')
    axes[1].set_ylim(0, 1)

    # iPTM (if multimer)
    if has_iptm:
        iptms = [m.get("iptm", 0) for m in models]
        axes[2].bar(ranks, iptms, color='#0053D6')
        axes[2].set_xlabel('Model Rank')
        axes[2].set_ylabel('iPTM Score')
        axes[2].set_title('iPTM Comparison')
        axes[2].set_ylim(0, 1)

    fig.suptitle(title, fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved model comparison plot: {output_file}")
    return output_file


def plot_coverage(msa_path: str, output_file: str,
                  title: str = "MSA Coverage") -> str:
    """Plot MSA sequence coverage per residue position.

    Args:
        msa_path: Path to a3m MSA file
        output_file: Path to save plot
        title: Plot title

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    sequences = []
    with open(msa_path) as f:
        seq = []
        for line in f:
            line = line.strip()
            if line.startswith('>'):
                if seq:
                    sequences.append(''.join(seq))
                seq = []
            elif line:
                seq.append(line)
        if seq:
            sequences.append(''.join(seq))

    if not sequences:
        logging.warning("No sequences found in MSA")
        return output_file

    query_len = len(sequences[0].replace('-', ''))
    coverage = np.zeros(query_len)

    for seq in sequences[1:]:
        pos = 0
        for char in seq:
            if char.isupper() or char == '-':
                if char != '-' and pos < query_len:
                    coverage[pos] += 1
                pos += 1
                if pos >= query_len:
                    break

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(range(1, query_len + 1), coverage, color='#0053D6', width=1.0)
    ax.set_xlabel('Residue Position', fontsize=11)
    ax.set_ylabel('MSA Depth', fontsize=11)
    ax.set_title(f'{title} ({len(sequences) - 1} sequences)', fontsize=13)
    ax.set_xlim(0.5, query_len + 0.5)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved coverage plot: {output_file}")
    return output_file


# ============= CLEANUP =============

def alphafold_cleanup(deep: bool = False) -> None:
    """Clean up AlphaFold state between predictions.

    Args:
        deep: If True, also clear scratch files and JAX compilation cache
    """
    try:
        if deep:
            _clear_scratch_files()
            # Clear JAX compilation cache
            jax_cache = os.path.expanduser("~/.cache/jax")
            if os.path.exists(jax_cache):
                shutil.rmtree(jax_cache, ignore_errors=True)
            logging.info("Deep cleanup completed")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")


def _clear_scratch_files() -> None:
    """Remove scratch files to recover from I/O corruption."""
    cleared = 0
    for d in [SCRATCH_DIR]:
        try:
            for entry in os.scandir(d):
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
