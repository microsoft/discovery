#!/usr/bin/env python3
"""RetroChimera utilities library for Discovery platform workflows.

Provides high-level functions for single-step retrosynthesis prediction and
multi-step route search using the RetroChimera model (Maziarz et al., 2025).
"""

import glob
import json
import logging
import os
import pickle
import shutil
import subprocess
import sys
import threading
import multiprocessing as _mp
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/retrochimera_scratch"

# Default model directory inside the container (Pistachio checkpoint)
DEFAULT_MODEL_DIR = "/app/models/pistachio"

# Default purchasable inventory for Syntheseus multi-step search.  At image build
# time this file is populated with the full eMolecules building blocks catalog
# (~5M compounds).  Pass a different file via search_routes() to restrict to a
# specific vendor inventory.
DEFAULT_INVENTORY_FILE = "/app/data/building_blocks.smi"

# Maximum recommended num_results to avoid hallucinated reactions
MAX_RECOMMENDED_RESULTS = 10


def _canonical_smiles(smiles: str) -> str:
    """Return RDKit-canonicalized SMILES, or the original string on failure."""
    try:
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            return Chem.MolToSmiles(mol)
    except Exception:
        pass
    return smiles


def _mol_properties(smiles: str) -> Dict[str, Any]:
    """Return molecular formula and weight for a SMILES string."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return {}
        return {
            "molecular_formula": Chem.rdMolDescriptors.CalcMolFormula(mol),
            "molecular_weight": round(Descriptors.ExactMolWt(mol), 2),
        }
    except Exception:
        return {}


def _mol_to_base64_svg(smiles: str, size: int = 250) -> Optional[str]:
    """Render a SMILES string to a base64-encoded SVG for inline embedding."""
    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D
        import base64

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        drawer = rdMolDraw2D.MolDraw2DSVG(size, size)
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        svg = drawer.GetDrawingText()
        return base64.b64encode(svg.encode("utf-8")).decode("ascii")
    except Exception:
        return None


def _enrich_mol(smiles: str, depictions: Dict[str, str]) -> Dict[str, Any]:
    """Build an enriched molecule record with properties and depiction."""
    info: Dict[str, Any] = {"smiles": smiles}
    info.update(_mol_properties(smiles))
    if smiles not in depictions:
        svg = _mol_to_base64_svg(smiles)
        if svg:
            depictions[smiles] = svg
    return info


# ============= SETUP FUNCTIONS =============
def quick_setup(input_dir="/input", output_dir="/output", work_dir="/workdir"):
    """Initialize logging, create directories, copy input files."""
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Files: {os.listdir('.')}")


def _copy_input_files():
    """Copy input files to working directory (with same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def _copy_output_files():
    """Copy output files to output directory (with same-directory guard)."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ["*.json", "*.csv", "*.png", "*.svg", "*.html", "*.log", "*.txt"]
    for pattern in patterns:
        for f in glob.glob(pattern):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def quick_finish():
    """Copy output files to output directory and emit shutdown diagnostics."""
    _trace_runtime("quick_finish_start")
    _copy_output_files()
    _trace_runtime("quick_finish_after_copy_outputs")


def save_final_results(
    results: Dict,
    output_files: Dict = None,
    file_descriptions: Dict = None,
    status: str = "completed",
):
    """Save final results to JSON file (MANDATORY for every script)."""
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    path = os.path.join(OUTPUT_DIR, "final_results.json")
    with open(path, "w") as f:
        json.dump(final_data, f, indent=2, default=str)
    logging.info("Saved final_results.json")


# ============= MODEL LOADING =============
_model_cache: Dict[str, Any] = {}


def load_model(
    model_dir: str = None,
    device: str = None,
) -> Any:
    """Load the RetroChimera model from a checkpoint directory.

    Args:
        model_dir: Path to the model checkpoint directory.
                   Defaults to DEFAULT_MODEL_DIR (Pistachio checkpoint).
        device: PyTorch device string ('cpu', 'cuda:0', etc.).
                Defaults to CUDA if available, else CPU.

    Returns:
        A RetroChimeraModel instance ready for inference.
    """
    model_dir = model_dir or DEFAULT_MODEL_DIR

    cache_key = f"{model_dir}:{device or 'auto'}"
    if cache_key in _model_cache:
        logging.info(f"Using cached model from {model_dir}")
        return _model_cache[cache_key]

    # Silence verbose upstream loggers (vocabulary dumps, rulebase loading messages)
    for _name in ("retrochimera", "syntheseus", "smiles_tokenizer", "rules"):
        logging.getLogger(_name).setLevel(logging.WARNING)

    from retrochimera import RetroChimeraModel

    logging.info(f"Loading RetroChimera model from {model_dir}...")
    t0 = time.time()
    model = RetroChimeraModel(model_dir=model_dir, device=device)
    elapsed = time.time() - t0
    logging.info(f"Model loaded in {elapsed:.1f}s (device={model.device})")

    _model_cache[cache_key] = model
    return model


# ============= SINGLE-STEP RETROSYNTHESIS =============
def _parse_predictions(preds, target_smiles: str = "") -> List[Dict]:
    """Convert syntheseus prediction objects to plain dicts."""
    reactions = []
    for rank, rxn in enumerate(preds, start=1):
        reactant_smiles = [r.smiles for r in rxn.reactants]
        reaction_dict = {
            "rank": rank,
            "reactants": reactant_smiles,
            "reactant_smiles_joined": ".".join(reactant_smiles),
            "reaction_smiles": ".".join(reactant_smiles) + ">>" + target_smiles,
            "score": float(rxn.metadata.get("score", 0.0)),
            "probability": float(rxn.metadata.get("probability", 0.0)),
        }
        if "individual_ranks" in rxn.metadata:
            reaction_dict["individual_ranks"] = {
                k: v for k, v in rxn.metadata["individual_ranks"].items()
            }
        reactions.append(reaction_dict)
    return reactions


def predict_precursors(
    smiles_list: List[str],
    num_results: int = 5,
    model_dir: str = None,
    device: str = None,
) -> Tuple[List[Dict], List[Dict]]:
    """Single-step retrosynthesis for one or more molecules.

    Always pass a list of SMILES (use ``["CCO"]`` for a single molecule).
    Uses the model's native batching for efficient GPU inference.

    Args:
        smiles_list: List of target SMILES strings.
        num_results: Number of reaction predictions per molecule (max recommended: 10).
        model_dir: Path to the model checkpoint directory.
        device: PyTorch device string.

    Returns:
        Tuple of (successes, failures).
        successes: list of dicts, each with keys target_smiles, num_results,
            reactions (list of ranked reaction dicts), elapsed_seconds.
        failures: list of dicts with 'smiles' and 'error' keys.
    """
    from syntheseus import Molecule

    if num_results > MAX_RECOMMENDED_RESULTS:
        logging.warning(
            f"Requesting {num_results} results. Reactions ranked lower than "
            f"{MAX_RECOMMENDED_RESULTS} are increasingly likely to be hallucinations."
        )

    model = load_model(model_dir=model_dir, device=device)

    valid_mols = []
    failures = []
    for idx, smi in enumerate(smiles_list):
        try:
            mol = Molecule(smi)
            valid_mols.append(mol)
        except Exception as e:
            failures.append({"smiles": smi, "error": str(e)})
            logging.warning(f"Invalid SMILES '{smi}': {e}")

    if not valid_mols:
        logging.warning("No valid molecules to process")
        return [], failures

    logging.info(
        f"Batch prediction: {len(valid_mols)} valid molecules "
        f"({len(failures)} failed SMILES validation)"
    )
    t0 = time.time()
    all_predictions = model(valid_mols, num_results=num_results)
    elapsed = time.time() - t0

    successes = []
    depictions: Dict[str, str] = {}
    per_mol_elapsed = elapsed / max(len(valid_mols), 1)
    for mol, preds in zip(valid_mols, all_predictions):
        target_smi = mol.smiles
        reactions = _parse_predictions(preds, target_smiles=target_smi)

        # Enrich each reaction with reactant properties
        for rxn in reactions:
            rxn["reactant_details"] = [
                _enrich_mol(rsmi, depictions) for rsmi in rxn["reactants"]
            ]

        # Collect target depiction
        _enrich_mol(target_smi, depictions)

        successes.append({
            "target_smiles": target_smi,
            **_mol_properties(target_smi),
            "num_results": len(reactions),
            "reactions": reactions,
            "elapsed_seconds": round(per_mol_elapsed, 2),
        })

    logging.info(
        f"Batch complete: {len(successes)} molecules in {elapsed:.2f}s "
        f"({elapsed / max(len(successes), 1):.2f}s/mol)"
    )
    return successes, failures, depictions


# ============= TRACING / SUBPROCESS ISOLATION =============
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_proc_status() -> Dict[str, str]:
    fields = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key in {
                    "Name", "State", "Threads", "VmRSS", "VmHWM", "VmSize",
                    "voluntary_ctxt_switches", "nonvoluntary_ctxt_switches",
                }:
                    fields[key] = value.strip()
    except Exception as exc:
        fields["error"] = repr(exc)
    return fields


def _trace_runtime(label: str, extra: Dict[str, Any] = None) -> Dict[str, Any]:
    extra = extra or {}
    try:
        threads = threading.enumerate()
        children = _mp.active_children()
        snapshot = {
            "ts_utc": _utc_now(),
            "label": label,
            "pid": os.getpid(),
            "ppid": os.getppid() if hasattr(os, "getppid") else None,
            "cwd": os.getcwd(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "argv": sys.argv,
            "thread_count": len(threads),
            "threads": [
                {
                    "name": t.name,
                    "ident": t.ident,
                    "daemon": t.daemon,
                    "alive": t.is_alive(),
                    "class": type(t).__name__,
                }
                for t in threads
            ],
            "active_children": [
                {
                    "name": p.name,
                    "pid": p.pid,
                    "daemon": p.daemon,
                    "exitcode": p.exitcode,
                    "alive": p.is_alive(),
                }
                for p in children
            ],
            "proc_status": _read_proc_status(),
            "mp_start_method": _mp.get_start_method(allow_none=True),
            "torch_loaded": "torch" in sys.modules,
            "retrochimera_loaded": "retrochimera" in sys.modules,
            "syntheseus_loaded": "syntheseus" in sys.modules,
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "extra": extra,
        }
        logging.debug("RETROCHIMERA_TRACE %s", json.dumps(snapshot, default=str, sort_keys=True))
        return snapshot
    except Exception as exc:
        logging.debug("RETROCHIMERA_TRACE_FAILED label=%s error=%r", label, exc)
        return {"label": label, "error": repr(exc)}


def _tail_file(path: str, max_bytes: int = 20000) -> str:
    try:
        if not os.path.exists(path):
            return ""
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception as exc:
        return f"<could not read {path}: {exc!r}>"


def _safe_name_from_smiles(smiles: str) -> str:
    digest = hashlib.sha1(smiles.encode("utf-8", errors="replace")).hexdigest()[:12]
    safe = "".join(ch if ch.isalnum() else "_" for ch in smiles[:32]).strip("_")
    return f"{safe[:40] or 'target'}_{digest}"


def _run_search_subprocess(args: List[str], target_smiles: str, time_limit_s: int, scratch_dir: str) -> Path:
    os.makedirs(scratch_dir, exist_ok=True)
    trace_root = os.path.join(OUTPUT_DIR, "retrochimera_traces")
    os.makedirs(trace_root, exist_ok=True)

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{_safe_name_from_smiles(target_smiles)}"
    child_log = os.path.join(trace_root, f"{run_id}.child.log")
    config_path = os.path.join(trace_root, f"{run_id}.child_config.json")
    status_path = os.path.join(trace_root, f"{run_id}.child_status.json")
    child_results_root = os.path.join(scratch_dir, f"child_{run_id}")
    os.makedirs(child_results_root, exist_ok=True)

    child_args = [a for a in args if not str(a).startswith("results_dir=")]
    child_args.append(f"results_dir={child_results_root}")

    config = {
        "argv": child_args,
        "status_path": status_path,
        "target_smiles": target_smiles,
        "results_root": child_results_root,
        "output_dir": OUTPUT_DIR,
        "scratch_dir": scratch_dir,
        "created_utc": _utc_now(),
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    child_code = """
import json, logging, os, sys, time, traceback, threading, multiprocessing as mp
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def trace(label, extra=None):
    extra = extra or {}
    try:
        threads = threading.enumerate()
        children = mp.active_children()
        snap = {
            "ts_utc": utc_now(),
            "label": label,
            "pid": os.getpid(),
            "ppid": os.getppid() if hasattr(os, "getppid") else None,
            "cwd": os.getcwd(),
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "thread_count": len(threads),
            "threads": [{"name": t.name, "daemon": t.daemon, "alive": t.is_alive(), "class": type(t).__name__} for t in threads],
            "active_children": [{"name": p.name, "pid": p.pid, "daemon": p.daemon, "exitcode": p.exitcode, "alive": p.is_alive()} for p in children],
            "mp_start_method": mp.get_start_method(allow_none=True),
            "torch_loaded": "torch" in sys.modules,
            "retrochimera_loaded": "retrochimera" in sys.modules,
            "syntheseus_loaded": "syntheseus" in sys.modules,
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "extra": extra,
        }
        print("RETROCHIMERA_CHILD_TRACE " + json.dumps(snap, sort_keys=True, default=str), file=sys.stderr, flush=True)
        return snap
    except Exception as exc:
        print(f"RETROCHIMERA_CHILD_TRACE_FAILED label={label} error={exc!r}", file=sys.stderr, flush=True)
        return {"label": label, "error": repr(exc)}

def write_status(path, payload):
    payload.setdefault("ts_utc", utc_now())
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    os.replace(tmp, path)

config_path = sys.argv[1]
config = json.load(open(config_path))
status_path = config["status_path"]
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
for _n in ("retrochimera", "syntheseus", "smiles_tokenizer", "rules"):
    logging.getLogger(_n).setLevel(logging.WARNING)
start = time.time()
try:
    trace("child_start", {"config_path": config_path, "target": config.get("target_smiles")})
    from retrochimera.cli.run_search import main as search_main
    trace("child_after_import_search_main")
    search_output_dir = search_main(argv=config["argv"])
    if search_output_dir is None:
        search_output_dir = os.path.join(config["results_root"], "RetroChimera")
    trace("child_after_search_main", {"search_output_dir": str(search_output_dir), "elapsed_s": round(time.time() - start, 3)})
    write_status(status_path, {
        "status": "ok",
        "returncode": 0,
        "elapsed_s": round(time.time() - start, 3),
        "search_output_dir": str(search_output_dir),
        "argv": config["argv"],
    })
    trace("child_status_written", {"status_path": status_path})
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0)
except BaseException as exc:
    tb = traceback.format_exc()
    print(tb, flush=True)
    trace("child_exception", {"error": repr(exc)})
    try:
        write_status(status_path, {
            "status": "error",
            "returncode": 2,
            "elapsed_s": round(time.time() - start, 3),
            "error": repr(exc),
            "traceback": tb,
            "argv": config.get("argv", []),
        })
    finally:
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(2)
"""

    _trace_runtime("parent_before_launch_child", {
        "target": target_smiles,
        "config_path": config_path,
        "child_log": child_log,
        "child_results_root": child_results_root,
    })

    timeout_s = max(int(time_limit_s) + 600, int(time_limit_s) * 3 + 180)
    cmd = [sys.executable, "-u", "-c", child_code, config_path]
    logging.info("Launching isolated RetroChimera child: timeout=%ss log=%s", timeout_s, child_log)

    with open(child_log, "w", buffering=1) as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            cwd=WORK_DIR,
            env=os.environ.copy(),
            text=True,
        )
        start = time.time()
        next_heartbeat = start + 30
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            elapsed = time.time() - start
            if elapsed >= timeout_s:
                logging.error("Child timeout after %.1fs; terminating pid=%s", elapsed, proc.pid)
                _trace_runtime("parent_child_timeout_before_terminate", {"pid": proc.pid, "elapsed_s": elapsed, "log_tail": _tail_file(child_log, 8000)})
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    logging.error("Child did not terminate; killing pid=%s", proc.pid)
                    proc.kill()
                    proc.wait(timeout=30)
                break
            if time.time() >= next_heartbeat:
                logging.info("Child still running: pid=%s elapsed=%.1fs target=%s", proc.pid, elapsed, target_smiles)
                next_heartbeat += 30
            time.sleep(2)

    elapsed = time.time() - start
    logging.info("Child finished: pid=%s returncode=%s elapsed=%.1fs log=%s", proc.pid, proc.returncode, elapsed, child_log)
    _trace_runtime("parent_after_child_exit", {"returncode": proc.returncode, "elapsed_s": round(elapsed, 3), "child_log": child_log})

    if not os.path.exists(status_path):
        tail = _tail_file(child_log)
        raise RuntimeError(f"RetroChimera child did not write status file {status_path}; returncode={proc.returncode}; log tail:\n{tail}")

    with open(status_path) as f:
        status = json.load(f)
    logging.info("Child status: %s", json.dumps(status, default=str, sort_keys=True))

    if proc.returncode != 0 or status.get("status") != "ok":
        tail = _tail_file(child_log)
        raise RuntimeError(f"RetroChimera child failed returncode={proc.returncode} status={status}; log tail:\n{tail}")

    search_output_dir = Path(status.get("search_output_dir") or os.path.join(child_results_root, "RetroChimera"))
    if not search_output_dir.exists():
        tail = _tail_file(child_log)
        raise FileNotFoundError(f"Search output directory not found: {search_output_dir}; log tail:\n{tail}")
    return search_output_dir


# ============= MULTI-STEP ROUTE SEARCH =============
def _search_routes_single(
    smiles: str,
    num_routes: int = 5,
    time_limit_s: int = 120,
    inventory_smiles_file: str = None,
    num_top_results: int = 50,
    num_routes_for_initial_extraction: int = None,
    model_dir: str = None,
    device: str = None,
    search_algorithm: str = "retro_star",
    max_expansion_depth: int = None,
) -> Dict:
    """Run multi-step retrosynthetic route search using syntheseus.

    Uses RetroChimera as the single-step model inside a tree search algorithm
    to find complete synthesis routes from purchasable starting materials.

    Args:
        smiles: SMILES string of the target product.
        num_routes: Number of routes to return.
        time_limit_s: Time limit in seconds for the search.
        inventory_smiles_file: Path to a Syntheseus purchasable inventory file,
            one SMILES per line. Defaults to DEFAULT_INVENTORY_FILE
            (eMolecules building blocks, ~5M compounds).
        num_top_results: Number of single-step disconnections to request per
            expanded molecule.
        num_routes_for_initial_extraction: Deprecated alias for num_top_results.
        model_dir: Path to the model checkpoint directory.
        device: PyTorch device string. Syntheseus search accepts GPU as a
            boolean; use "cpu" to force CPU, or leave unset/use "cuda" for GPU.
        search_algorithm: Syntheseus search algorithm name, e.g. "retro_star".
        max_expansion_depth: Optional maximum expansion depth for the selected
            search algorithm.

    Returns:
        Dict with keys: target_smiles, num_routes_found, routes (list of dicts),
        elapsed_seconds, search_params.
    """
    import tempfile

    model_dir = model_dir or DEFAULT_MODEL_DIR
    inventory_smiles_file = inventory_smiles_file or DEFAULT_INVENTORY_FILE
    if num_routes_for_initial_extraction is not None:
        logging.warning(
            "num_routes_for_initial_extraction is deprecated; using it as "
            "num_top_results for Syntheseus search."
        )
        num_top_results = num_routes_for_initial_extraction

    use_gpu = not (device and device.lower().startswith("cpu"))

    args = [
        "model_class=RetroChimera",
        f"model_dir={model_dir}",
        f"search_target={smiles}",
        f"inventory_smiles_file={inventory_smiles_file}",
        f"time_limit_s={time_limit_s}",
        f"num_top_results={num_top_results}",
        f"search_algorithm={search_algorithm}",
        "append_timestamp_to_dir=False",
        "save_graph=True",
        "num_routes_to_plot=0",
        f"use_gpu={str(use_gpu)}",
    ]
    if max_expansion_depth is not None:
        args.append(f"{search_algorithm}_config.max_expansion_depth={max_expansion_depth}")

    # Log search configuration for traceability
    logging.info(f"Starting multi-step search for: {smiles}")
    logging.info(f"  algorithm={search_algorithm}, time_limit={time_limit_s}s, "
                 f"num_routes={num_routes}, num_top_results={num_top_results}")
    logging.info(f"  inventory={inventory_smiles_file}, use_gpu={use_gpu}")
    if max_expansion_depth is not None:
        logging.info(f"  max_expansion_depth={max_expansion_depth}")
    logging.info(f"  model_dir={model_dir}")

    t0 = time.time()
    routes: List[Dict] = []
    stats: Dict[str, Any] = {}
    error: Optional[str] = None

    with tempfile.TemporaryDirectory(dir=SCRATCH_DIR) as tmpdir:
        args.append(f"results_dir={tmpdir}")

        try:
            if not os.path.exists(inventory_smiles_file):
                raise FileNotFoundError(
                    f"Inventory file not found: {inventory_smiles_file}. "
                    "Pass inventory_smiles_file with one purchasable SMILES per line."
                )

            with open(inventory_smiles_file) as inv_f:
                inv_size = sum(1 for _ in inv_f)
            logging.info(f"  inventory loaded: {inv_size:,} building blocks")

            search_output_dir = _run_search_subprocess(
                args=args,
                target_smiles=smiles,
                time_limit_s=time_limit_s,
                scratch_dir=tmpdir,
            )
            routes = _parse_search_output(str(search_output_dir), max_routes=num_routes)
            stats = _read_search_stats(str(search_output_dir))
        except Exception as e:
            logging.error(f"Multi-step search failed: {e}")
            import traceback
            traceback.print_exc()
            error = str(e)

    elapsed = time.time() - t0

    result = {
        "target_smiles": _canonical_smiles(smiles),
        "num_routes_found": len(routes),
        "routes": routes,
        "elapsed_seconds": round(elapsed, 2),
        "search_params": {
            "num_routes": num_routes,
            "time_limit_s": time_limit_s,
            "inventory_smiles_file": inventory_smiles_file,
            "num_top_results": num_top_results,
            "search_algorithm": search_algorithm,
            "max_expansion_depth": max_expansion_depth,
            "use_gpu": use_gpu,
        },
    }
    if stats:
        result["stats"] = stats
    if error:
        result["error"] = error
    logging.info(f"Multi-step search complete: {len(routes)} routes in {elapsed:.1f}s")
    return result


def find_routes(
    smiles_list: List[str],
    num_routes: int = 5,
    time_limit_s: int = 120,
    inventory_smiles_file: str = None,
    model_dir: str = None,
    device: str = None,
    checkpoint_path: str = None,
) -> Tuple[List[Dict], List[Dict]]:
    """Multi-step route search for one or more molecules.

    Always pass a list of SMILES (use ``["CCO"]`` for a single molecule).
    Processes molecules sequentially with incremental checkpointing so that
    already-completed molecules are skipped on restart.

    Args:
        smiles_list: List of target SMILES strings.
        num_routes: Number of routes to find per molecule.
        time_limit_s: Time limit in seconds per molecule.
        inventory_smiles_file: Path to purchasable SMILES file (one per line).
            Defaults to the built-in eMolecules building blocks (~5M compounds).
        model_dir: Path to the model checkpoint directory.
        device: PyTorch device string.
        checkpoint_path: Path for incremental checkpoint JSON.  Defaults to
            ``/output/route_search_checkpoint.json``.

    Returns:
        Tuple of (successes, failures, depictions).
        successes: list of route-search result dicts.
        failures: list of dicts with 'smiles' and 'error' keys.
        depictions: dict mapping SMILES to base64-encoded SVG strings.
    """
    checkpoint_path = checkpoint_path or os.path.join(OUTPUT_DIR, "route_search_checkpoint.json")

    # Load existing checkpoint to skip completed molecules
    completed: Dict[str, Dict] = {}
    if os.path.isfile(checkpoint_path):
        try:
            with open(checkpoint_path) as f:
                data = json.load(f)
            for entry in data.get("results", []):
                smi = entry.get("target_smiles")
                if smi:
                    completed[_canonical_smiles(smi)] = entry
            logging.info(f"Resuming from checkpoint: {len(completed)} molecules already done")
        except (json.JSONDecodeError, IOError) as exc:
            logging.warning(f"Could not read checkpoint {checkpoint_path}: {exc}")

    successes: List[Dict] = []
    failures: List[Dict] = []

    for idx, smiles in enumerate(smiles_list, 1):
        canon = _canonical_smiles(smiles)
        if canon in completed:
            prev = completed[canon]
            if prev.get("error"):
                failures.append({"smiles": smiles, "error": prev["error"]})
            else:
                successes.append(prev)
            logging.info(f"[{idx}/{len(smiles_list)}] {smiles}: skipped (checkpoint)")
            continue

        logging.info(f"[{idx}/{len(smiles_list)}] {smiles}: starting route search")
        try:
            result = _search_routes_single(
                smiles,
                num_routes=num_routes,
                time_limit_s=time_limit_s,
                inventory_smiles_file=inventory_smiles_file,
                model_dir=model_dir,
                device=device,
            )
            if result.get("error"):
                failures.append({"smiles": smiles, "error": result["error"]})
            else:
                successes.append(result)
            completed[canon] = result
        except Exception as exc:
            err_msg = str(exc)
            logging.error(f"[{idx}/{len(smiles_list)}] {smiles}: {err_msg}")
            failure_entry = {"smiles": smiles, "error": err_msg}
            failures.append(failure_entry)
            completed[canon] = {"target_smiles": canon, "error": err_msg}

        # Write checkpoint after each molecule
        _write_checkpoint(checkpoint_path, completed)

    logging.info(
        f"Route search complete: {len(successes)} succeeded, {len(failures)} failed "
        f"out of {len(smiles_list)} targets"
    )

    # Collect depictions for all unique molecules across all routes
    depictions: Dict[str, str] = {}
    for result in successes:
        _enrich_mol(result.get("target_smiles", ""), depictions)
        result.update(_mol_properties(result.get("target_smiles", "")))
        for route in result.get("routes", []):
            for bb in route.get("building_blocks", []):
                _enrich_mol(bb.get("smiles", ""), depictions)
            for step in route.get("steps", []):
                _enrich_mol(step.get("product", ""), depictions)
                for rsmi in step.get("reactants", []):
                    _enrich_mol(rsmi, depictions)

    return successes, failures, depictions


def _write_checkpoint(path: str, completed: Dict[str, Dict]) -> None:
    """Write incremental checkpoint JSON."""
    data = {"results": list(completed.values()), "updated_utc": _utc_now()}
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception as exc:
        logging.warning(f"Could not write checkpoint {path}: {exc}")


def _read_search_stats(output_dir: str) -> Dict[str, Any]:
    """Read Syntheseus stats.json if present."""
    stats_path = os.path.join(output_dir, "stats.json")
    if not os.path.exists(stats_path):
        return {}
    try:
        with open(stats_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Could not parse search stats {stats_path}: {e}")
        return {}


def _parse_search_output(output_dir: str, max_routes: int = None) -> List[Dict]:
    """Parse syntheseus search output directory into a list of route dicts."""
    routes: List[Dict] = []

    graph_path = os.path.join(output_dir, "graph.pkl")
    if os.path.exists(graph_path):
        routes.extend(_extract_routes_from_graph(graph_path, max_routes=max_routes))

    route_pickles = sorted(glob.glob(os.path.join(output_dir, "route_*.pkl")))
    for route_pickle in route_pickles:
        if max_routes is not None and len(routes) >= max_routes:
            break
        try:
            with open(route_pickle, "rb") as f:
                route_nodes = pickle.load(f)
            routes.append({
                "route_id": f"route_{len(routes) + 1:02d}",
                "source_file": os.path.basename(route_pickle),
                "node_count": len(route_nodes),
            })
        except (pickle.PickleError, IOError, AttributeError, TypeError) as e:
            logging.warning(f"Could not parse route file {route_pickle}: {e}")

    route_files = sorted(glob.glob(os.path.join(output_dir, "**/*.json"), recursive=True))
    for route_file in route_files:
        if max_routes is not None and len(routes) >= max_routes:
            break
        if os.path.basename(route_file) == "stats.json":
            continue
        try:
            with open(route_file) as f:
                route_data = json.load(f)
            routes.append(route_data)
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Could not parse route file {route_file}: {e}")

    if not routes:
        txt_files = glob.glob(os.path.join(output_dir, "**/*.txt"), recursive=True)
        for tf in txt_files:
            try:
                with open(tf) as f:
                    content = f.read()
                if content.strip():
                    routes.append({"raw_output": content, "source_file": os.path.basename(tf)})
            except IOError:
                pass

    return routes


def _extract_routes_from_graph(graph_path: str, max_routes: int = None) -> List[Dict]:
    """Extract solved routes from a Syntheseus graph.pkl without requiring Graphviz."""
    max_routes = max_routes or 5
    try:
        with open(graph_path, "rb") as f:
            graph = pickle.load(f)
        from syntheseus.search.analysis.route_extraction import iter_routes_time_order

        routes = []
        for route_idx, route_nodes in enumerate(
            iter_routes_time_order(graph, max_routes=max_routes), start=1
        ):
            routes.append(_serialize_route(graph, route_nodes, route_idx))
        return routes
    except Exception as e:
        logging.warning(f"Could not extract routes from graph {graph_path}: {e}")
        return []


def _serialize_route(graph, route_nodes, route_idx: int) -> Dict[str, Any]:
    """Convert a Syntheseus route node collection to enriched JSON data."""
    route_set = set(route_nodes)
    root = getattr(graph, "root_node", None)
    if root is not None and hasattr(root, "mol"):
        tree = _serialize_or_node(graph, root, route_set)
        steps = _linearize_tree(tree)
        building_blocks = _collect_building_blocks(tree)
        route_score = _compute_route_score(steps)
        return {
            "route_id": f"route_{route_idx:02d}",
            "n_steps": len(steps),
            "solved": bool(getattr(root, "has_solution", False)),
            "route_score": route_score,
            "steps": steps,
            "building_blocks": building_blocks,
            "reaction_tree": tree,
        }

    return {
        "route_id": f"route_{route_idx:02d}",
        "node_count": len(route_set),
        "nodes": [_serialize_generic_node(node) for node in route_set],
    }


def _serialize_or_node(graph, or_node, route_set: set) -> Dict[str, Any]:
    mol = getattr(or_node, "mol", None)
    smiles = getattr(mol, "smiles", str(mol))
    reaction_children = [node for node in graph.successors(or_node) if node in route_set]
    if not reaction_children:
        metadata = getattr(mol, "metadata", {}) or {}
        return {
            "type": "mol",
            "smiles": smiles,
            "in_stock": bool(metadata.get("is_purchasable", False)),
            "solved": bool(getattr(or_node, "has_solution", False)),
        }

    reaction_node = reaction_children[0]
    return {
        "type": "reaction",
        "smiles": smiles,
        "metadata": _serialize_reaction(getattr(reaction_node, "reaction", None)),
        "children": [
            _serialize_or_node(graph, child, route_set)
            for child in graph.successors(reaction_node)
            if child in route_set
        ],
    }


def _serialize_reaction(reaction) -> Dict[str, Any]:
    if reaction is None:
        return {}
    metadata = dict(getattr(reaction, "metadata", {}) or {})
    return {
        "reaction_smiles": getattr(reaction, "reaction_smiles", None),
        "reactants": sorted(mol.smiles for mol in getattr(reaction, "reactants", [])),
        "score": _json_safe(metadata.get("score")),
        "probability": _json_safe(metadata.get("probability")),
        "model_metadata": _json_safe(metadata),
    }


def _serialize_generic_node(node) -> Dict[str, Any]:
    if hasattr(node, "mol"):
        mol = node.mol
        return {"type": "mol", "smiles": getattr(mol, "smiles", str(mol))}
    if hasattr(node, "reaction"):
        return {"type": "reaction", **_serialize_reaction(node.reaction)}
    return {"type": type(node).__name__, "repr": repr(node)}


def _json_safe(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(v) for v in value]
        return str(value)


def _linearize_tree(tree: Dict, step_num: List = None) -> List[Dict]:
    """Flatten a reaction_tree into an ordered list of synthesis steps.

    Walks the tree depth-first from leaves to root so that building-block
    reactions appear first and the final step produces the target.
    """
    if step_num is None:
        step_num = [0]

    children = tree.get("children", [])
    steps: List[Dict] = []
    for child in children:
        steps.extend(_linearize_tree(child, step_num))

    if tree.get("type") == "reaction" and children:
        step_num[0] += 1
        reactant_smiles = [c.get("smiles", "?") for c in children]
        product_smiles = tree.get("smiles", "?")
        meta = tree.get("metadata", {})
        steps.append({
            "step_number": step_num[0],
            "product": product_smiles,
            "reactants": reactant_smiles,
            "reaction_smiles": ".".join(reactant_smiles) + ">>" + product_smiles,
            "probability": meta.get("probability"),
            "score": meta.get("score"),
        })
    return steps


def _collect_building_blocks(tree: Dict) -> List[Dict]:
    """Collect deduplicated leaf molecules (purchasable starting materials)."""
    seen: set = set()
    blocks: List[Dict] = []

    def _walk(node):
        children = node.get("children", [])
        if node.get("type") == "mol" and not children:
            smi = node.get("smiles", "")
            if smi not in seen:
                seen.add(smi)
                entry = {"smiles": smi, "in_stock": node.get("in_stock", False)}
                entry.update(_mol_properties(smi))
                blocks.append(entry)
        for child in children:
            _walk(child)

    _walk(tree)
    return blocks


def _compute_route_score(steps: List[Dict]) -> Optional[float]:
    """Compute aggregate route confidence as the product of step probabilities."""
    probs = [s["probability"] for s in steps if s.get("probability") is not None]
    if not probs:
        return None
    score = 1.0
    for p in probs:
        score *= float(p)
    return round(score, 6)


def validate_smiles(smiles: str) -> bool:
    """Check if a SMILES string is valid using RDKit.

    Args:
        smiles: SMILES string to validate.

    Returns:
        True if valid, False otherwise.
    """
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        return mol is not None
    except ImportError:
        try:
            from syntheseus import Molecule
            Molecule(smiles)
            return True
        except Exception:
            return False


def validate_smiles_list(smiles_list: List[str]) -> Tuple[List[str], List[str]]:
    """Validate a list of SMILES strings.

    Args:
        smiles_list: List of SMILES to validate.

    Returns:
        Tuple of (valid_smiles, invalid_smiles).
    """
    valid = []
    invalid = []
    for smi in smiles_list:
        if validate_smiles(smi):
            valid.append(smi)
        else:
            invalid.append(smi)
    if invalid:
        logging.warning(f"{len(invalid)} invalid SMILES: {invalid}")
    return valid, invalid


# ============= CLEANUP =============
def cleanup(deep: bool = False):
    """Clean up temporary files and model cache.

    Args:
        deep: If True, also clear the model cache (forces reload on next use).
    """
    global _model_cache
    if deep:
        _model_cache.clear()
        logging.info("Cleared model cache")
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
