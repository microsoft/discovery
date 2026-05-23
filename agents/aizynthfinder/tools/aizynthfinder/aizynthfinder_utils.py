#!/usr/bin/env python3
"""AiZynthFinder utilities library for Discovery platform workflows.

Provides retrosynthetic route planning using neural-network-guided Monte Carlo
Tree Search (MCTS).  Wraps the AiZynthFinder Python API with batch processing,
checkpointing, parallelisation, and visualisation helpers.

Reference:
  Genheden S et al. (2020) AiZynthFinder: a fast, robust and flexible
  open-source software for retrosynthetic planning. J Cheminform 12:70.
"""

import glob
import json
import logging
import os
import shutil
import time
import traceback
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

# ============= CONSTANTS (defaults - overridden by quick_setup) ==============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/aizynthfinder_scratch"
MODEL_DIR = "/app/models"
DEFAULT_CONFIG_PATH = "/app/models/config.yml"

DEFAULT_SEARCH_PARAMS: Dict[str, Any] = {
    "iteration_limit": 100,
    "time_limit": 120,
    "max_transforms": 6,
    "return_first": False,
    "C": 1.4,
    "default_prior": 0.5,
    "use_prior": True,
    "prune_cycles_in_search": True,
}

AVAILABLE_EXPANSION_POLICIES = {
    "uspto": {
        "model": "uspto_model.onnx",
        "template": "uspto_templates.csv.gz",
    },
    "ringbreaker": {
        "model": "uspto_ringbreaker_model.onnx",
        "template": "uspto_ringbreaker_templates.csv.gz",
    },
}

AVAILABLE_FILTER_POLICIES = {
    "uspto": {"model": "uspto_filter_model.onnx"},
}

AVAILABLE_STOCKS = {
    "zinc": {"file": "zinc_stock.hdf5"},
}


# ===========================  SETUP  =========================================
def quick_setup(
    input_dir: str = "/input",
    output_dir: str = "/output",
    work_dir: str = "/workdir",
) -> None:
    """Initialise logging, create directories, copy input files.

    All three parameters should be passed explicitly in every script.
    """
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
    logging.info("Working directory: %s", WORK_DIR)
    if os.path.exists(INPUT_DIR):
        logging.info("Input files: %s", os.listdir(INPUT_DIR))
    if os.path.exists(MODEL_DIR):
        logging.info("Model files: %s", os.listdir(MODEL_DIR))


def _copy_input_files() -> None:
    """Copy input files to working directory (same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def copy_outputs() -> None:
    """Copy result files from work dir to output dir."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = [
        "*.json", "*.json.gz", "*.png", "*.svg",
        "*.csv", "*.log", "*.yml", "*.yaml", "*.html",
    ]
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to %s", OUTPUT_DIR)


def quick_finish() -> None:
    """Copy output files to output directory."""
    copy_outputs()


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
    with open(path, "w") as fh:
        json.dump(final_data, fh, indent=2, default=str)
    logging.info("Saved final_results.json")


# ==========================  CONFIGURATION  ==================================
def get_default_config_path() -> str:
    """Return path to the pre-generated default config.

    Raises:
        FileNotFoundError: if the default config is missing.
    """
    if os.path.exists(DEFAULT_CONFIG_PATH):
        return DEFAULT_CONFIG_PATH
    raise FileNotFoundError(
        f"Default config not found at {DEFAULT_CONFIG_PATH}. "
        "Ensure models are installed in the container."
    )


def create_config(
    model_dir: Optional[str] = None,
    expansion_policies: Optional[List[str]] = None,
    filter_policies: Optional[List[str]] = None,
    stock_files: Optional[Dict[str, str]] = None,
    search_params: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
) -> str:
    """Create an AiZynthFinder YAML configuration file.

    Args:
        model_dir:  Directory containing model files (default ``/app/models``).
        expansion_policies:  Policy names to include (default ``['uspto']``).
        filter_policies:  Filter names (default ``['uspto']``).
        stock_files:  ``{name: path}`` for stock files.
        search_params:  Overrides for ``DEFAULT_SEARCH_PARAMS``.
        output_path:  Where to write the config.

    Returns:
        Absolute path to the generated config file.
    """
    model_dir = model_dir or MODEL_DIR
    output_path = output_path or os.path.join(WORK_DIR, "config.yml")

    # --- search section ---
    sp = dict(DEFAULT_SEARCH_PARAMS)
    if search_params:
        sp.update(search_params)

    config: Dict[str, Any] = {
        "search": {
            "algorithm": sp.pop("algorithm", "mcts"),
            "iteration_limit": sp.pop("iteration_limit", 100),
            "time_limit": sp.pop("time_limit", 120),
            "max_transforms": sp.pop("max_transforms", 6),
            "return_first": sp.pop("return_first", False),
            "exclude_target_from_stock": sp.pop("exclude_target_from_stock", True),
            "algorithm_config": {
                "C": sp.pop("C", 1.4),
                "default_prior": sp.pop("default_prior", 0.5),
                "use_prior": sp.pop("use_prior", True),
                "prune_cycles_in_search": sp.pop("prune_cycles_in_search", True),
            },
        }
    }
    # Any remaining params go into the search section directly
    if sp:
        config["search"].update(sp)

    # --- expansion policies ---
    expansion_policies = expansion_policies or ["uspto"]
    config["expansion"] = {}
    for name in expansion_policies:
        info = AVAILABLE_EXPANSION_POLICIES.get(name)
        if info:
            config["expansion"][name] = [
                os.path.join(model_dir, info["model"]),
                os.path.join(model_dir, info["template"]),
            ]
        else:
            logging.warning("Unknown expansion policy '%s' -- skipped", name)

    # --- filter policies ---
    filter_policies = filter_policies or ["uspto"]
    config["filter"] = {}
    for name in filter_policies:
        info = AVAILABLE_FILTER_POLICIES.get(name)
        if info:
            config["filter"][name] = os.path.join(model_dir, info["model"])

    # --- stock ---
    if stock_files is None:
        stock_files = {}
        for name, info in AVAILABLE_STOCKS.items():
            stock_files[name] = os.path.join(model_dir, info["file"])
    config["stock"] = stock_files

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as fh:
        yaml.dump(config, fh, default_flow_style=False)
    logging.info("Config written to %s", output_path)
    return output_path


def _apply_search_overrides(config_path: str, search_params: Dict) -> str:
    """Create a modified copy of *config_path* with search-parameter overrides."""
    with open(config_path) as fh:
        config = yaml.safe_load(fh)

    config.setdefault("search", {})
    nested_keys = {
        "C": ("algorithm_config", "C"),
        "default_prior": ("algorithm_config", "default_prior"),
        "use_prior": ("algorithm_config", "use_prior"),
        "prune_cycles_in_search": ("algorithm_config", "prune_cycles_in_search"),
    }

    for key, value in search_params.items():
        if key in nested_keys:
            section = config["search"].setdefault("algorithm_config", {})
            section[nested_keys[key][-1]] = value
        else:
            config["search"][key] = value

    override_path = os.path.join(WORK_DIR, "config_override.yml")
    with open(override_path, "w") as fh:
        yaml.dump(config, fh, default_flow_style=False)
    logging.info("Config with overrides -> %s", override_path)
    return override_path


# ========================  SMILES HELPERS  ===================================
def validate_smiles(smiles: str) -> bool:
    """Check whether *smiles* is a valid, parseable SMILES string.

    Uses RDKit (bundled with aizynthfinder).
    Rejects empty/whitespace-only strings explicitly.
    """
    if not smiles or not smiles.strip():
        return False
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        return mol is not None and mol.GetNumAtoms() > 0
    except Exception:
        return False


def load_smiles_from_file(filepath: str) -> List[str]:
    """Load SMILES strings from a text file (one per line).

    Blank lines and lines starting with ``#`` are ignored.
    """
    smiles = []
    with open(filepath) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                smiles.append(line)
    logging.info("Loaded %d SMILES from %s", len(smiles), filepath)
    return smiles


# ====================  CORE RETROSYNTHESIS  ==================================
def run_retrosynthesis(
    smiles: str,
    config_path: Optional[str] = None,
    search_params: Optional[Dict] = None,
    expansion_policy: Optional[str] = None,
    filter_policy: Optional[str] = None,
    stock: Optional[Union[str, List[str]]] = None,
    nroutes: int = 25,
) -> Dict[str, Any]:
    """Run full retrosynthetic tree search for a single target molecule.

    Args:
        smiles:  Target molecule SMILES.
        config_path:  Path to config YAML (default: container built-in).
        search_params:  Override search parameters.
        expansion_policy:  Expansion policy name to select.
        filter_policy:  Filter policy name to select.
        stock:  Stock name(s) to select.
        nroutes:  Maximum number of routes to extract.

    Returns:
        Dict with keys ``smiles``, ``is_solved``, ``search_time``, ``stats``,
        ``routes``, ``stock_info``, ``trees``, ``n_routes``, ``n_solved_routes``.
    """
    from aizynthfinder.aizynthfinder import AiZynthFinder

    config_path = config_path or get_default_config_path()
    if search_params:
        config_path = _apply_search_overrides(config_path, search_params)

    logging.info("Initialising AiZynthFinder with config: %s", config_path)
    finder = AiZynthFinder(configfile=config_path)

    # ---- select policies & stock ----
    _select_policy(finder.expansion_policy, expansion_policy)
    _select_policy(finder.filter_policy, filter_policy, required=False)
    _select_stock(finder.stock, stock)

    finder.config.post_processing.max_routes = nroutes

    # ---- run ----
    logging.info("Target: %s", smiles)
    finder.target_smiles = smiles

    try:
        search_time = finder.tree_search()
    except Exception as exc:
        logging.error("Tree search failed for %s: %s", smiles, exc)
        traceback.print_exc()
        return _error_result(smiles, str(exc))

    finder.build_routes()
    finder.routes.compute_scores(*finder.scorers.objects())
    stats = finder.extract_statistics()
    stock_info = finder.stock_info()
    trees = finder.routes.dict_with_extra(
        include_metadata=True, include_scores=True
    )

    result: Dict[str, Any] = {
        "smiles": smiles,
        "search_time": search_time,
        "is_solved": stats.get("is_solved", False),
        "stats": _serialisable(stats),
        "routes": _extract_route_summaries(finder),
        "stock_info": _serialisable(stock_info),
        "trees": trees,
        "n_routes": len(finder.routes),
        "n_solved_routes": stats.get("number_of_solved_routes", 0),
    }

    logging.info(
        "Done: %s | solved=%s | routes=%d | time=%.1fs",
        smiles, result["is_solved"], result["n_routes"], search_time,
    )
    return result


def run_single_step_expansion(
    smiles: str,
    config_path: Optional[str] = None,
    expansion_policy: Optional[str] = None,
    filter_policy: Optional[str] = None,
    return_n: int = 5,
) -> Dict[str, Any]:
    """Run single-step retrosynthetic expansion (no tree search).

    Returns immediate precursors for one disconnection step.

    Args:
        smiles:  Target SMILES.
        config_path:  Config YAML path.
        expansion_policy / filter_policy:  Policy names.
        return_n:  Max reactions to return.

    Returns:
        Dict with ``smiles``, ``n_reactions``, ``reactions``, ``stats``.
    """
    from aizynthfinder.aizynthfinder import AiZynthExpander

    config_path = config_path or get_default_config_path()

    logging.info("Initialising AiZynthExpander")
    expander = AiZynthExpander(configfile=config_path)
    _select_policy(expander.expansion_policy, expansion_policy)
    _select_policy(expander.filter_policy, filter_policy, required=False)

    logging.info("Single-step expansion for: %s", smiles)
    reactions = expander.do_expansion(smiles, return_n=return_n)

    reaction_list: List[Dict] = []
    for reaction_tuple in reactions:
        for reaction in reaction_tuple:
            rxn: Dict[str, Any] = {
                "metadata": _serialisable(
                    dict(reaction.metadata) if hasattr(reaction, "metadata") else {}
                ),
                "reactants": [],
            }
            if hasattr(reaction, "reactants") and reaction.reactants:
                for reactant_set in reaction.reactants:
                    rxn["reactants"].append(
                        [mol.smiles for mol in reactant_set]
                    )
            reaction_list.append(rxn)

    result = {
        "smiles": smiles,
        "n_reactions": len(reaction_list),
        "reactions": reaction_list,
        "stats": _serialisable(expander.stats),
    }
    logging.info("Expansion found %d reactions", len(reaction_list))
    return result


# =========================  BATCH / PARALLEL  ================================
def run_retrosynthesis_batch(
    smiles_list: List[str],
    config_path: Optional[str] = None,
    search_params: Optional[Dict] = None,
    checkpoint_file: Optional[str] = None,
    nroutes: int = 25,
) -> List[Dict]:
    """Run retrosynthesis on a batch with automatic checkpointing.

    Processes molecules sequentially.  If *checkpoint_file* exists from a
    previous (interrupted) run, previously-completed molecules are skipped.

    Args:
        smiles_list:  Target SMILES strings.
        config_path:  Config YAML path.
        search_params:  Search-parameter overrides.
        checkpoint_file:  Checkpoint path (default ``/output/checkpoint.jsonl``).
        nroutes:  Max routes per molecule.

    Returns:
        List of result dicts (one per molecule).
    """
    checkpoint_file = checkpoint_file or os.path.join(OUTPUT_DIR, "checkpoint.jsonl")
    completed_results, completed_smiles = _load_checkpoint(checkpoint_file)
    logging.info(
        "Batch: %d molecules, %d already checkpointed",
        len(smiles_list), len(completed_smiles),
    )

    results: List[Dict] = list(completed_results)

    for i, smi in enumerate(smiles_list):
        if smi in completed_smiles:
            logging.info("[%d/%d] Skipping (checkpointed): %s", i + 1, len(smiles_list), smi)
            continue

        logging.info("[%d/%d] Processing: %s", i + 1, len(smiles_list), smi)
        try:
            result = run_retrosynthesis(
                smi, config_path=config_path,
                search_params=search_params, nroutes=nroutes,
            )
        except Exception as exc:
            logging.error("Error processing %s: %s", smi, exc)
            traceback.print_exc()
            result = _error_result(smi, str(exc))

        results.append(result)
        _save_checkpoint(checkpoint_file, result)
        _save_incremental_results(results)

    logging.info("Batch complete: %d molecules processed", len(results))
    return results


def _retro_worker(args: Tuple) -> Dict:
    """Worker function for parallel retrosynthesis."""
    smi, config_path, search_params, nroutes = args
    try:
        return run_retrosynthesis(
            smi, config_path=config_path,
            search_params=search_params, nroutes=nroutes,
        )
    except Exception as exc:
        return _error_result(smi, str(exc))


def run_retrosynthesis_parallel(
    smiles_list: List[str],
    config_path: Optional[str] = None,
    search_params: Optional[Dict] = None,
    nproc: Optional[int] = None,
    nroutes: int = 25,
) -> List[Dict]:
    """Run retrosynthesis on a batch using multiprocessing.

    Args:
        smiles_list:  Target SMILES.
        config_path:  Config YAML.
        search_params:  Search overrides.
        nproc:  Worker count (default ``min(cpu_count(), len(smiles_list))``).
        nroutes:  Max routes per molecule.

    Returns:
        List of result dicts.
    """
    config_path = config_path or get_default_config_path()
    nproc = nproc or min(cpu_count(), len(smiles_list))
    nproc = max(1, min(nproc, len(smiles_list)))
    logging.info(
        "Parallel retrosynthesis: %d molecules, %d workers", len(smiles_list), nproc,
    )

    work = [(smi, config_path, search_params, nroutes) for smi in smiles_list]

    if nproc == 1:
        results = [_retro_worker(w) for w in work]
    else:
        with Pool(nproc) as pool:
            results = pool.map(_retro_worker, work)

    _save_incremental_results(results)
    logging.info("Parallel batch complete: %d molecules", len(results))
    return results


# =======================  ANALYSIS HELPERS  ==================================
def _extract_route_summaries(finder: Any) -> List[Dict]:
    """Build lightweight summaries for each extracted route."""
    summaries: List[Dict] = []
    try:
        all_scores = finder.routes.all_scores
    except Exception:
        all_scores = []

    for idx, tree in enumerate(finder.routes.reaction_trees):
        summary: Dict[str, Any] = {"index": idx}
        try:
            summary["is_solved"] = tree.is_solved
        except Exception:
            summary["is_solved"] = None
        try:
            leaves = list(tree.leafs())
            summary["precursors"] = [leaf.smiles for leaf in leaves]
            summary["n_precursors"] = len(leaves)
        except Exception:
            summary["precursors"] = []
            summary["n_precursors"] = 0
        try:
            summary["n_steps"] = len(list(tree.reactions()))
        except Exception:
            summary["n_steps"] = 0
        if idx < len(all_scores):
            summary["scores"] = _serialisable(all_scores[idx])
        summaries.append(summary)
    return summaries


def summarize_batch_results(results: List[Dict]) -> Dict[str, Any]:
    """Compute aggregate statistics from a batch of retrosynthesis results.

    Args:
        results:  List of per-molecule result dicts.

    Returns:
        Summary dict (solve rate, timing, route counts, etc.).
    """
    n_total = len(results)
    if n_total == 0:
        return {
            "total_molecules": 0, "solved": 0, "unsolved": 0,
            "errors": 0, "solve_rate": 0, "avg_search_time": 0,
            "max_search_time": 0, "min_search_time": 0,
            "total_search_time": 0, "avg_routes": 0,
        }

    n_solved = sum(1 for r in results if r.get("is_solved"))
    n_errors = sum(1 for r in results if "error" in r)
    ok = [r for r in results if "error" not in r]
    times = [r.get("search_time", 0) for r in ok]
    routes = [r.get("n_routes", 0) for r in ok]

    return {
        "total_molecules": n_total,
        "solved": n_solved,
        "unsolved": n_total - n_solved - n_errors,
        "errors": n_errors,
        "solve_rate": round(n_solved / n_total, 4),
        "avg_search_time": round(sum(times) / len(times), 2) if times else 0,
        "max_search_time": round(max(times), 2) if times else 0,
        "min_search_time": round(min(times), 2) if times else 0,
        "total_search_time": round(sum(times), 2),
        "avg_routes": round(sum(routes) / len(routes), 1) if routes else 0,
    }


def parse_route_tree(tree_dict: Dict) -> Dict[str, Any]:
    """Parse a serialised route-tree dict into a structured summary.

    Args:
        tree_dict:  A dict from ``finder.routes.dict_with_extra()``.

    Returns:
        Dict with ``is_solved``, ``n_reactions``, ``precursors``, ``reactions``, ``depth``.
    """
    from aizynthfinder.reactiontree import ReactionTree

    tree = ReactionTree.from_dict(tree_dict)
    info: Dict[str, Any] = {
        "is_solved": tree.is_solved,
        "n_reactions": len(list(tree.reactions())),
        "n_molecules": len(list(tree.molecules())),
        "depth": tree.depth,
    }
    info["precursors"] = [leaf.smiles for leaf in tree.leafs()]
    reactions = []
    for rxn in tree.reactions():
        rxn_info: Dict[str, Any] = {}
        if hasattr(rxn, "smiles"):
            rxn_info["smiles"] = rxn.smiles
        if hasattr(rxn, "metadata"):
            rxn_info["metadata"] = _serialisable(dict(rxn.metadata))
        reactions.append(rxn_info)
    info["reactions"] = reactions
    return info


# ==========================  VISUALISATION  ==================================
def plot_route_image(tree_dict: Dict, output_file: str) -> str:
    """Generate a PNG image of one synthesis route.

    Args:
        tree_dict:  Serialised route-tree dict.
        output_file:  Destination PNG path.

    Returns:
        The output file path.
    """
    from aizynthfinder.reactiontree import ReactionTree

    tree = ReactionTree.from_dict(tree_dict)
    img = tree.to_image()
    img.save(output_file)
    logging.info("Route image saved to %s", output_file)
    return output_file


def plot_route_scores(results: List[Dict], output_file: str) -> str:
    """Bar chart showing search time and solve status per molecule.

    Args:
        results:  Batch result list.
        output_file:  Destination PNG path.

    Returns:
        The output file path.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(14, max(4, len(results) * 0.45)))

    # --- Panel 1: solve counts ---
    solved = sum(1 for r in results if r.get("is_solved"))
    unsolved = len(results) - solved
    axes[0].bar(["Solved", "Unsolved"], [solved, unsolved],
                color=["#2ecc71", "#e74c3c"])
    axes[0].set_title("Retrosynthesis Success Rate")
    axes[0].set_ylabel("Count")
    for i, v in enumerate([solved, unsolved]):
        axes[0].text(i, v + 0.1, str(v), ha="center", fontweight="bold")

    # --- Panel 2: search time per molecule ---
    ok = [r for r in results if "error" not in r]
    times = [r.get("search_time", 0) for r in ok]
    labels = [r.get("smiles", "")[:25] for r in ok]
    colours = ["#2ecc71" if r.get("is_solved") else "#e74c3c" for r in ok]

    if times:
        axes[1].barh(range(len(times)), times, color=colours)
        axes[1].set_yticks(range(len(times)))
        axes[1].set_yticklabels(labels, fontsize=7)
        axes[1].invert_yaxis()
    axes[1].set_xlabel("Search Time (s)")
    axes[1].set_title("Search Time per Molecule")

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close()
    logging.info("Scores plot saved to %s", output_file)
    return output_file


def plot_search_summary(results: List[Dict], output_file: str) -> str:
    """Four-panel summary figure for a batch retrosynthesis run.

    Args:
        results:  Batch result list.
        output_file:  Destination PNG path.

    Returns:
        The output file path.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = summarize_batch_results(results)
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # 1. Solve-rate pie
    sizes = [summary["solved"], summary["unsolved"], summary["errors"]]
    labels = ["Solved", "Unsolved", "Errors"]
    colours = ["#2ecc71", "#e74c3c", "#95a5a6"]
    nonzero = [(l, s, c) for l, s, c in zip(labels, sizes, colours) if s > 0]
    if nonzero:
        l, s, c = zip(*nonzero)
        axes[0, 0].pie(s, labels=l, colors=c, autopct="%1.1f%%", startangle=90)
    axes[0, 0].set_title("Solve Rate")

    # 2. Search-time histogram
    ok = [r for r in results if "error" not in r]
    times = [r.get("search_time", 0) for r in ok]
    if times:
        axes[0, 1].hist(times, bins=min(20, len(times)), color="#3498db", edgecolor="w")
    axes[0, 1].set_xlabel("Search Time (s)")
    axes[0, 1].set_ylabel("Count")
    axes[0, 1].set_title("Search Time Distribution")

    # 3. Route-count histogram
    rcounts = [r.get("n_routes", 0) for r in ok]
    if rcounts and max(rcounts) > 0:
        axes[1, 0].hist(rcounts, bins=min(20, max(rcounts) + 1),
                        color="#9b59b6", edgecolor="w")
    axes[1, 0].set_xlabel("Number of Routes")
    axes[1, 0].set_ylabel("Count")
    axes[1, 0].set_title("Routes Found per Molecule")

    # 4. Summary text
    axes[1, 1].axis("off")
    txt = (
        f"Batch Summary\n"
        f"{'=' * 30}\n"
        f"Total molecules:  {summary['total_molecules']}\n"
        f"Solved:           {summary['solved']} ({summary['solve_rate']:.1%})\n"
        f"Unsolved:         {summary['unsolved']}\n"
        f"Errors:           {summary['errors']}\n\n"
        f"Timing\n{'=' * 30}\n"
        f"Avg search time:  {summary['avg_search_time']:.1f}s\n"
        f"Max search time:  {summary['max_search_time']:.1f}s\n"
        f"Total time:       {summary['total_search_time']:.1f}s\n\n"
        f"Routes\n{'=' * 30}\n"
        f"Avg routes/mol:   {summary['avg_routes']:.1f}"
    )
    axes[1, 1].text(0.05, 0.95, txt, transform=axes[1, 1].transAxes,
                    fontfamily="monospace", fontsize=11, verticalalignment="top")

    plt.suptitle("Retrosynthesis Batch Analysis", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close()
    logging.info("Search summary saved to %s", output_file)
    return output_file



# =====================  INTERACTIVE HTML REPORT  =============================

_ATOM_MAP_COLORS = [
    (0.25, 0.40, 0.95),   # blue
    (0.95, 0.30, 0.30),   # red
    (0.20, 0.80, 0.45),   # green
    (0.95, 0.60, 0.15),   # orange
    (0.65, 0.25, 0.85),   # purple
    (0.15, 0.75, 0.75),   # teal
    (0.95, 0.25, 0.60),   # pink
    (0.55, 0.55, 0.15),   # olive
    (0.40, 0.70, 0.95),   # light blue
    (0.85, 0.45, 0.20),   # dark orange
]


def _mol_to_svg(smiles: str, width: int = 300, height: int = 200,
                highlight_atoms=None, highlight_colors=None) -> str:
    """Render a molecule SMILES as an inline SVG string using RDKit."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return (f'<svg width="{width}" height="{height}" '
                f'xmlns="http://www.w3.org/2000/svg">'
                f'<rect width="100%" height="100%" fill="#f0f0f0" rx="8"/>'
                f'<text x="50%" y="50%" text-anchor="middle" fill="#999" '
                f'font-size="11">Cannot parse</text></svg>')
    AllChem.Compute2DCoords(mol)
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = drawer.drawOptions()
    opts.clearBackground = False
    opts.bondLineWidth = 2.0
    opts.additionalAtomLabelPadding = 0.1
    if highlight_atoms and highlight_colors:
        drawer.DrawMolecule(mol, highlightAtoms=highlight_atoms,
                            highlightAtomColors=highlight_colors)
    else:
        drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    return svg.replace("<?xml version='1.0' encoding='iso-8859-1'?>\n", "")


def _fig_to_b64(fig) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    import base64
    from io import BytesIO

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="#1a1d27", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode()


def _build_route_trees_html(trees: List[Dict], max_routes: int = 5) -> str:
    """Build HTML for molecule-rendered route tree panels with tab switching."""
    panels: List[str] = []
    for idx, tree in enumerate(trees[:max_routes]):
        target_svg = _mol_to_svg(tree["smiles"], width=420, height=300)

        children_html = ""
        if "children" in tree:
            for rxn in tree["children"]:
                meta = rxn.get("metadata", {})
                policy = meta.get("policy_name", "unknown")
                prob = meta.get("policy_probability", 0)
                template_code = meta.get("template_code", "?")
                lib_occ = meta.get("library_occurence", 0)

                precursor_cards: List[str] = []
                for child in rxn.get("children", []):
                    cs = child["smiles"]
                    in_stock = child.get("in_stock", False)
                    sc = "in-stock" if in_stock else "not-in-stock"
                    sl = "In ZINC Stock" if in_stock else "Not in Stock"
                    badge_icon = "&#x2705;" if in_stock else "&#x274C;"
                    child_svg = _mol_to_svg(cs, width=360, height=250)
                    cs_disp = cs if len(cs) <= 55 else cs[:52] + "..."
                    precursor_cards.append(
                        f'<div class="tree-node {sc}">'
                        f'<div class="mol-render">{child_svg}</div>'
                        f'<div class="node-badge {sc}">{badge_icon} {sl}</div>'
                        f'<div class="smiles-line">{cs_disp}</div></div>'
                    )

                children_html = (
                    '<div class="connector-line"></div>'
                    '<div class="rxn-badge-box">'
                    '<div class="rxn-glyph">&#x2697;&#xFE0F;</div>'
                    f'<div class="rxn-info"><strong>{policy}</strong> &middot; '
                    f'p = {prob:.1%}</div>'
                    f'<div class="rxn-sub">template #{template_code} &middot; '
                    f'{lib_occ:,} lit. occurrences</div></div>'
                    '<div class="connector-line"></div>'
                    '<div class="precursors-row">'
                    f'{"".join(precursor_cards)}</div>'
                )

        score = tree.get("scores", {}).get("state score", 0)
        solved = tree.get("metadata", {}).get("is_solved", False)
        sb = "solved" if solved else "unsolved"
        badge_txt = "&#x2713; Solved" if solved else "&#x2717; Unsolved"
        display = "" if idx == 0 else "display:none;"

        panels.append(
            f'<div class="route-panel" id="route-{idx}" style="{display}">'
            f'<div class="route-title-bar">'
            f'<span class="rt-title">Route {idx}</span>'
            f'<span class="rt-score">Score: {score:.4f}</span>'
            f'<span class="rt-badge {sb}">{badge_txt}</span></div>'
            f'<div class="tree-flow">'
            f'<div class="tree-node target-node">'
            f'<div class="mol-render">{target_svg}</div>'
            f'<div class="node-badge target">&#x1F3AF; Target</div></div>'
            f'{children_html}</div></div>'
        )

    tabs = "".join(
        f'<div class="rtab {"on" if i == 0 else ""}" '
        f'data-route="{i}">Route {i}</div>'
        for i in range(len(panels))
    )
    return f'<div class="route-tabs">{tabs}</div>{"".join(panels)}'


def _build_atom_maps_html(trees: List[Dict], max_maps: int = 3) -> str:
    """Build HTML for atom-mapped reaction diagrams with colored correspondence."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    cards: List[str] = []
    for route_idx, tree in enumerate(trees[:max_maps]):
        parsed = parse_route_tree(tree)
        for rxn in parsed.get("reactions", []):
            mapped = rxn.get("metadata", {}).get("mapped_reaction_smiles", "")
            if not mapped or ">>" not in mapped:
                continue
            parts = mapped.split(">>")
            if len(parts) != 2:
                continue
            reactants_str, products_str = parts

            # Highlight product atoms by atom-map number
            product_mol = Chem.MolFromSmiles(products_str)
            product_svg = ""
            if product_mol:
                AllChem.Compute2DCoords(product_mol)
                p_hl, p_col = [], {}
                for atom in product_mol.GetAtoms():
                    mn = atom.GetAtomMapNum()
                    if mn > 0:
                        p_hl.append(atom.GetIdx())
                        c = _ATOM_MAP_COLORS[mn % len(_ATOM_MAP_COLORS)]
                        p_col[atom.GetIdx()] = c
                product_svg = _mol_to_svg(products_str, 420, 300, p_hl, p_col)

            # Highlight each reactant's atoms the same way
            reactant_svgs: List[str] = []
            for r_smi in reactants_str.split("."):
                r_mol = Chem.MolFromSmiles(r_smi)
                if r_mol:
                    AllChem.Compute2DCoords(r_mol)
                    r_hl, r_col = [], {}
                    for atom in r_mol.GetAtoms():
                        mn = atom.GetAtomMapNum()
                        if mn > 0:
                            r_hl.append(atom.GetIdx())
                            c = _ATOM_MAP_COLORS[mn % len(_ATOM_MAP_COLORS)]
                            r_col[atom.GetIdx()] = c
                    reactant_svgs.append(
                        _mol_to_svg(r_smi, 350, 250, r_hl, r_col))

            policy = rxn.get("metadata", {}).get("policy_name", "")
            prob = rxn.get("metadata", {}).get("policy_probability", 0)
            r_inner = ('</div><div class="plus">+</div>'
                       '<div class="r-card">').join(
                f'<div class="mol-render">{svg}</div>'
                for svg in reactant_svgs
            )
            arrow_id = f"ah{route_idx}_{len(cards)}"
            cards.append(
                f'<div class="atom-map-card">'
                f'<div class="am-header">Route {route_idx} &mdash; '
                f'<strong>{policy}</strong> (p = {prob:.1%})</div>'
                f'<div class="am-layout">'
                f'<div class="am-side"><div class="am-label">PRODUCT</div>'
                f'<div class="am-mol">{product_svg}</div></div>'
                f'<div class="am-arrow">'
                f'<svg width="60" height="40" viewBox="0 0 60 40"><defs>'
                f'<marker id="{arrow_id}" markerWidth="8" markerHeight="6" '
                f'refX="8" refY="3" orient="auto" fill="#818cf8">'
                f'<polygon points="0 0,8 3,0 6"/></marker></defs>'
                f'<line x1="5" y1="20" x2="48" y2="20" stroke="#818cf8" '
                f'stroke-width="2.5" marker-end="url(#{arrow_id})"/></svg>'
                f'<span class="am-arrow-label">retro</span></div>'
                f'<div class="am-side reactants">'
                f'<div class="am-label">PRECURSORS</div>'
                f'<div class="am-reactants">'
                f'<div class="r-card">{r_inner}</div></div></div></div>'
                f'<div class="am-footnote">Matching colors show atom-to-atom '
                f'correspondence across the disconnection</div></div>'
            )
    return "".join(cards)


def _build_convergence_network(trees: List[Dict]) -> str:
    """Build convergence network chart from route trees; return base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.offsetbox import OffsetImage, AnnotationBbox
    import networkx as nx
    from collections import defaultdict
    from rdkit import Chem
    from rdkit.Chem import AllChem, Draw

    G = nx.DiGraph()
    node_route_count: Dict[str, set] = defaultdict(set)

    def _add(node, parent=None, ridx=0):
        ntype = node.get("type", "mol")
        smiles = node.get("smiles", "")
        if ntype == "mol":
            nid = smiles
            if nid not in G:
                G.add_node(nid, type="mol",
                           in_stock=node.get("in_stock", False),
                           smiles=smiles)
            node_route_count[nid].add(ridx)
            if parent:
                G.add_edge(parent, nid)
            for ch in node.get("children", []):
                _add(ch, nid, ridx)
        elif ntype == "reaction":
            tc = node.get("metadata", {}).get("template_code", "?")
            nid = f"rxn_{ridx}_{tc}"
            G.add_node(nid, type="reaction",
                       policy=node.get("metadata", {}).get("policy_name", ""),
                       prob=node.get("metadata", {}).get(
                           "policy_probability", 0))
            if parent:
                G.add_edge(parent, nid)
            for ch in node.get("children", []):
                _add(ch, nid, ridx)

    for i, t in enumerate(trees):
        _add(t, ridx=i)

    if G.number_of_nodes() == 0:
        return ""

    fig, ax = plt.subplots(figsize=(16, 11))
    ax.set_facecolor("#1a1d27")
    pos = nx.spring_layout(G, k=3.5, iterations=150, seed=42)

    mol_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "mol"]
    rxn_nodes = [n for n, d in G.nodes(data=True)
                 if d.get("type") == "reaction"]

    nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#4a4d5a", width=1.8,
                           arrows=True, arrowsize=15, alpha=0.6,
                           connectionstyle="arc3,rad=0.08")
    mol_colors = ["#34d399" if G.nodes[n].get("in_stock") else "#f87171"
                  for n in mol_nodes]
    mol_sizes = [250 + len(node_route_count.get(n, set())) * 250
                 for n in mol_nodes]
    nx.draw_networkx_nodes(G, pos, nodelist=mol_nodes, ax=ax,
                           node_color=mol_colors, node_size=mol_sizes,
                           edgecolors="white", linewidths=2, alpha=0.9)
    nx.draw_networkx_nodes(G, pos, nodelist=rxn_nodes, ax=ax,
                           node_color="#6366f1", node_size=120,
                           node_shape="D", edgecolors="#a5b4fc",
                           linewidths=1.5, alpha=0.85)

    # Overlay RDKit molecule images at key nodes (target, in-stock, shared)
    target_smiles = trees[0]["smiles"] if trees else ""
    for node in mol_nodes:
        n_routes = len(node_route_count.get(node, set()))
        is_key = (node == target_smiles
                  or G.nodes[node].get("in_stock", False)
                  or n_routes >= 2)
        if not is_key:
            continue
        try:
            mol = Chem.MolFromSmiles(node)
            if mol is None:
                continue
            AllChem.Compute2DCoords(mol)
            img = Draw.MolToImage(mol, size=(220, 160))
            x, y = pos[node]
            imagebox = OffsetImage(img, zoom=0.55)
            border = ("#fbbf24" if node == target_smiles else
                      "#34d399" if G.nodes[node].get("in_stock")
                      else "#f87171")
            ab = AnnotationBbox(
                imagebox, (x, y), frameon=True,
                bboxprops=dict(boxstyle="round,pad=0.12",
                               facecolor="white",
                               edgecolor=border, linewidth=3),
                pad=0.15)
            ax.add_artist(ab)
        except Exception:
            pass

    legend_els = [
        mpatches.Patch(facecolor="#fbbf24", edgecolor="white",
                       label="Target Molecule"),
        mpatches.Patch(facecolor="#34d399", edgecolor="white",
                       label="In ZINC Stock"),
        mpatches.Patch(facecolor="#f87171", edgecolor="white",
                       label="Not in Stock"),
        mpatches.Patch(facecolor="#6366f1", edgecolor="#a5b4fc",
                       label="Reaction Step"),
    ]
    ax.legend(handles=legend_els, loc="upper left", fontsize=11,
              facecolor="#232733", edgecolor="#2d3140", labelcolor="#e4e6eb")
    ax.set_title("Multi-Route Convergence Network\n"
                 "Node size proportional to number of routes through molecule",
                 fontsize=16, color="#e4e6eb", fontweight="bold", pad=20)
    ax.axis("off")
    return _fig_to_b64(fig)


def _build_complexity_cascade(tree: Dict) -> str:
    """Build molecular complexity cascade chart; return base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    def _desc(smiles, label):
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        return {
            "label": label, "smiles": smiles,
            "MW": round(Descriptors.MolWt(mol), 1),
            "HeavyAtoms": mol.GetNumHeavyAtoms(),
            "Rings": rdMolDescriptors.CalcNumRings(mol),
            "RotBonds": Descriptors.NumRotatableBonds(mol),
            "TPSA": round(Descriptors.TPSA(mol), 1),
            "HBA": Descriptors.NumHAcceptors(mol),
        }

    descriptors: List[Dict] = []
    td = _desc(tree["smiles"], "Target")
    if td:
        descriptors.append(td)
    if "children" in tree:
        for rxn in tree["children"]:
            for ci, child in enumerate(rxn.get("children", [])):
                stock_tag = " (stock)" if child.get("in_stock") else ""
                d = _desc(child["smiles"],
                          f"Precursor {ci + 1}{stock_tag}")
                if d:
                    descriptors.append(d)

    if not descriptors:
        return ""

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    fig.patch.set_facecolor("#1a1d27")
    fig.suptitle("Molecular Complexity Cascade: Target to Precursors",
                 fontsize=16, color="#e4e6eb", fontweight="bold", y=0.98)

    metrics = ["MW", "HeavyAtoms", "Rings", "RotBonds", "TPSA", "HBA"]
    titles = ["Molecular Weight (Da)", "Heavy Atom Count", "Ring Count",
              "Rotatable Bonds", "TPSA (A^2)", "H-Bond Acceptors"]
    colors = ["#6366f1", "#22d3ee", "#34d399", "#fbbf24", "#f87171",
              "#a78bfa"]
    labels = [d["label"] for d in descriptors]

    for idx_m, (metric, mtitle, color) in enumerate(
            zip(metrics, titles, colors)):
        ax = axes[idx_m // 3][idx_m % 3]
        ax.set_facecolor("#232733")
        vals = [d[metric] for d in descriptors]
        bars = ax.bar(range(len(labels)), vals, color=color, alpha=0.85,
                      edgecolor="white", linewidth=0.5, width=0.55)
        for bar, v in zip(bars, vals):
            fmt = (f"{v:.0f}" if isinstance(v, int) or v == int(v)
                   else f"{v:.1f}")
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(vals) * 0.02,
                    fmt, ha="center", va="bottom", color="#e4e6eb",
                    fontsize=10, fontweight="bold")
        ax.set_title(mtitle, color="#e4e6eb", fontsize=11, fontweight="600")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8,
                           color="#9ca3af")
        ax.tick_params(colors="#9ca3af")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        for spine in ["bottom", "left"]:
            ax.spines[spine].set_color("#2d3140")
        ax.yaxis.grid(True, color="#2d3140", alpha=0.5)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return _fig_to_b64(fig)


def _build_search_radar(stats: Dict) -> str:
    """Build MCTS search efficiency radar chart; return base64 PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    prof = stats.get("profiling", {})
    cat_labels = ["Routes\nFound", "Stock\nCoverage", "Search\nEfficiency",
                  "Expansion\nDensity", "Template\nDiversity"]

    n_routes = stats.get("number_of_routes", 0)
    n_prec = max(stats.get("number_of_precursors", 1), 1)
    n_prec_stock = stats.get("number_of_precursors_in_stock", 0)
    stock_cov = n_prec_stock / n_prec
    iters = max(prof.get("iterations", 1), 1)
    search_eff = min(n_routes / iters * 50, 1)
    exp_dens = prof.get("expansion_calls", 0) / iters
    n_policies = len(stats.get("policy_used_counts", {}))
    tmpl_div = min(n_policies / 3, 1)

    vals = [min(n_routes / 10, 1), stock_cov, search_eff,
            exp_dens, tmpl_div]
    angles = np.linspace(0, 2 * np.pi, len(cat_labels),
                         endpoint=False).tolist()
    vals_c = vals + [vals[0]]
    angles_c = angles + [angles[0]]

    fig, ax = plt.subplots(figsize=(8, 8),
                           subplot_kw=dict(projection="polar"))
    fig.patch.set_facecolor("#1a1d27")
    ax.set_facecolor("#232733")
    ax.plot(angles_c, vals_c, "o-", linewidth=2.5, color="#6366f1",
            markersize=8)
    ax.fill(angles_c, vals_c, alpha=0.2, color="#6366f1")
    ax.set_xticks(angles)
    ax.set_xticklabels(cat_labels, fontsize=11, color="#e4e6eb")
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["25%", "50%", "75%", "100%"], fontsize=8,
                       color="#9ca3af")
    ax.grid(color="#2d3140", linewidth=0.8)
    ax.spines["polar"].set_color("#2d3140")
    ax.set_title("MCTS Search Efficiency", fontsize=16, color="#e4e6eb",
                 fontweight="bold", pad=30)
    return _fig_to_b64(fig)


def _report_css() -> str:
    """Return the complete CSS stylesheet for the interactive report."""
    return (
        ":root{"
        "--bg:#0f1117;--s1:#1a1d27;--s2:#232733;--brd:#2d3140;"
        "--t1:#e4e6eb;--t2:#9ca3af;--acc:#6366f1;--acc2:#818cf8;"
        "--grn:#34d399;--red:#f87171;--amb:#fbbf24;--cyn:#22d3ee;}"
        "*{margin:0;padding:0;box-sizing:border-box;}"
        "body{background:var(--bg);color:var(--t1);"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "line-height:1.6;}"
        ".wrap{max-width:1400px;margin:0 auto;padding:32px;}"
        ".hero{text-align:center;padding:48px 0 24px;}"
        ".hero h1{font-size:2.2rem;"
        "background:linear-gradient(135deg,#818cf8,#22d3ee,#34d399);"
        "-webkit-background-clip:text;-webkit-text-fill-color:transparent;}"
        ".hero p{color:var(--t2);max-width:750px;margin:8px auto 0;}"
        ".pills{display:flex;gap:10px;justify-content:center;"
        "margin-top:16px;flex-wrap:wrap;}"
        ".pill{padding:5px 14px;border-radius:20px;font-size:.78rem;"
        "font-weight:600;}"
        ".pill.a{background:rgba(99,102,241,.12);color:var(--acc2);"
        "border:1px solid rgba(99,102,241,.3);}"
        ".pill.b{background:rgba(34,211,238,.12);color:var(--cyn);"
        "border:1px solid rgba(34,211,238,.3);}"
        ".pill.c{background:rgba(52,211,153,.12);color:var(--grn);"
        "border:1px solid rgba(52,211,153,.3);}"
        ".pill.d{background:rgba(251,191,36,.12);color:var(--amb);"
        "border:1px solid rgba(251,191,36,.3);}"
        ".sec{margin:48px 0;}"
        ".sec-head{display:flex;align-items:center;gap:12px;"
        "padding-bottom:14px;border-bottom:2px solid var(--brd);"
        "margin-bottom:20px;}"
        ".sec-head h2{font-size:1.45rem;font-weight:700;}"
        ".sec-num{width:36px;height:36px;border-radius:10px;"
        "background:var(--acc);color:#fff;display:flex;"
        "align-items:center;justify-content:center;font-weight:700;"
        "font-size:1.1rem;flex-shrink:0;}"
        ".sec-desc{color:var(--t2);font-size:.92rem;margin-bottom:20px;}"
        ".route-tabs{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap;}"
        ".rtab{padding:8px 18px;background:var(--s2);"
        "border:1px solid var(--brd);border-radius:8px;color:var(--t2);"
        "cursor:pointer;font-size:.85rem;font-weight:500;"
        "transition:all .2s;}"
        ".rtab:hover{border-color:var(--acc);color:var(--t1);}"
        ".rtab.on{background:rgba(99,102,241,.15);"
        "border-color:var(--acc);color:var(--acc2);}"
        ".route-panel{background:var(--s1);border:1px solid var(--brd);"
        "border-radius:16px;padding:28px;margin-bottom:20px;}"
        ".route-title-bar{display:flex;align-items:center;gap:12px;"
        "margin-bottom:24px;}"
        ".rt-title{font-size:1.15rem;font-weight:700;}"
        ".rt-score{background:rgba(99,102,241,.12);color:var(--acc2);"
        "padding:4px 12px;border-radius:10px;font-size:.8rem;"
        "font-weight:600;}"
        ".rt-badge{padding:4px 12px;border-radius:10px;font-size:.8rem;"
        "font-weight:600;}"
        ".rt-badge.solved{background:rgba(52,211,153,.12);"
        "color:var(--grn);}"
        ".rt-badge.unsolved{background:rgba(248,113,113,.12);"
        "color:var(--red);}"
        ".tree-flow{display:flex;flex-direction:column;align-items:center;}"
        ".tree-node{background:var(--s2);border:2.5px solid var(--brd);"
        "border-radius:14px;padding:14px;text-align:center;"
        "max-width:440px;transition:transform .2s;}"
        ".tree-node:hover{transform:scale(1.02);}"
        ".tree-node.target-node{border-color:var(--amb);"
        "box-shadow:0 0 24px rgba(251,191,36,.12);}"
        ".tree-node.in-stock{border-color:var(--grn);"
        "box-shadow:0 0 20px rgba(52,211,153,.1);}"
        ".tree-node.not-in-stock{border-color:var(--red);"
        "box-shadow:0 0 16px rgba(248,113,113,.08);}"
        ".mol-render{background:#fff;border-radius:10px;padding:6px;"
        "overflow:hidden;}"
        ".mol-render svg{width:100%;height:auto;display:block;}"
        ".node-badge{margin-top:8px;font-weight:600;font-size:.88rem;}"
        ".node-badge.target{color:var(--amb);}"
        ".node-badge.in-stock{color:var(--grn);}"
        ".node-badge.not-in-stock{color:var(--red);}"
        ".smiles-line{font-family:'JetBrains Mono',monospace;"
        "font-size:.7rem;color:var(--cyn);margin-top:4px;"
        "word-break:break-all;opacity:.75;}"
        ".connector-line{width:2.5px;height:28px;background:var(--acc);"
        "opacity:.5;}"
        ".rxn-badge-box{display:flex;flex-direction:column;"
        "align-items:center;padding:14px 28px;"
        "background:rgba(99,102,241,.08);"
        "border:1px solid rgba(99,102,241,.25);border-radius:14px;}"
        ".rxn-glyph{font-size:1.6rem;}"
        ".rxn-info{color:var(--acc2);font-size:.9rem;margin-top:2px;}"
        ".rxn-sub{color:var(--t2);font-size:.75rem;}"
        ".precursors-row{display:flex;gap:24px;justify-content:center;"
        "flex-wrap:wrap;margin-top:4px;}"
        ".atom-map-card{background:var(--s1);border:1px solid var(--brd);"
        "border-radius:16px;padding:28px;margin-bottom:20px;}"
        ".am-header{font-size:1rem;color:var(--acc2);"
        "margin-bottom:18px;}"
        ".am-layout{display:flex;align-items:center;"
        "justify-content:center;gap:20px;flex-wrap:wrap;}"
        ".am-side{text-align:center;}"
        ".am-label{font-size:.72rem;color:var(--t2);font-weight:700;"
        "text-transform:uppercase;letter-spacing:1.5px;"
        "margin-bottom:8px;}"
        ".am-mol{background:#fff;border-radius:10px;padding:6px;"
        "display:inline-block;}"
        ".am-mol svg{width:100%;height:auto;display:block;}"
        ".am-arrow{display:flex;flex-direction:column;align-items:center;"
        "gap:2px;}"
        ".am-arrow-label{font-size:.72rem;color:var(--acc2);"
        "font-weight:700;text-transform:uppercase;letter-spacing:1px;}"
        ".am-reactants{display:flex;align-items:center;gap:8px;"
        "flex-wrap:wrap;justify-content:center;}"
        ".r-card{display:inline-block;}"
        ".r-card .mol-render{background:#fff;border-radius:10px;"
        "padding:6px;display:inline-block;}"
        ".plus{font-size:1.6rem;color:var(--t2);padding:0 4px;}"
        ".am-footnote{margin-top:14px;text-align:center;font-size:.8rem;"
        "color:var(--t2);}"
        ".reactants{max-width:700px;}"
        ".viz-img{background:var(--s1);border:1px solid var(--brd);"
        "border-radius:16px;overflow:hidden;margin-bottom:20px;}"
        ".viz-img img{width:100%;height:auto;display:block;}"
        ".viz-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;}"
        "@media(max-width:900px){.viz-grid{grid-template-columns:1fr;}}"
    )


def generate_interactive_report(
    result: Dict[str, Any],
    output_file: str = "/output/retrosynthesis_report.html",
    title: str = "Retrosynthesis Analysis Report",
    max_routes: int = 5,
    max_atom_maps: int = 3,
    include_network: bool = True,
    include_complexity: bool = True,
    include_radar: bool = True,
) -> Dict[str, str]:
    """Generate a self-contained interactive HTML report with all visualizations.

    Produces a single HTML file with embedded SVG molecules, base64-encoded
    charts, and interactive JavaScript.  No external dependencies needed.

    Visualizations included:
      1. Molecule-rendered route trees (RDKit 2D structures at every node)
      2. Atom-mapped reaction diagrams (colored atom correspondence)
      3. Multi-route convergence network (overlaid graph of all routes)
      4. Molecular complexity cascade (descriptor waterfall chart)
      5. MCTS search efficiency radar chart

    Args:
        result:  Output dict from ``run_retrosynthesis()``.  Must contain
                 ``trees`` (list of route-tree dicts) and ``stats`` (search
                 statistics dict).
        output_file:  Path for the HTML file
                 (default ``/output/retrosynthesis_report.html``).
        title:  Report title displayed in the header.
        max_routes:  Max number of routes in tree panels (default 5).
        max_atom_maps:  Max atom-mapped reactions to render (default 3).
        include_network:  Include the convergence network chart.
        include_complexity:  Include the complexity cascade chart.
        include_radar:  Include the search radar chart.

    Returns:
        Dict mapping output names to file paths, e.g.
        ``{"report": "/output/retrosynthesis_report.html"}``.

    Example::

        result = run_retrosynthesis(smiles, search_params={...})
        files = generate_interactive_report(result,
            title="Imatinib Retrosynthesis")
        # => {"report": "/output/retrosynthesis_report.html"}
    """
    trees = result.get("trees", [])
    stats = result.get("stats", {})
    smiles = result.get("smiles", "unknown")

    if not trees:
        logging.warning("No route trees found -- generating minimal report")

    sections: List[str] = []

    # --- Section 1: Route Trees ---
    if trees:
        logging.info("Generating molecule-rendered route trees...")
        route_html = _build_route_trees_html(trees, max_routes)
        sections.append(
            '<div class="sec">'
            '<div class="sec-head"><div class="sec-num">1</div>'
            '<h2>Molecule-Rendered Route Trees</h2></div>'
            '<p class="sec-desc">Every node shows the actual 2D molecular '
            'structure rendered by RDKit. Borders indicate stock '
            'availability: '
            '<span style="color:var(--grn)">green = in ZINC</span>, '
            '<span style="color:var(--red)">red = not available</span>, '
            '<span style="color:var(--amb)">amber = target</span>. '
            'Reaction badges show policy, probability, and template '
            'provenance.</p>'
            f'{route_html}</div>'
        )

    # --- Section 2: Atom-Mapped Reactions ---
    if trees:
        logging.info("Generating atom-mapped reaction diagrams...")
        atom_html = _build_atom_maps_html(trees, max_atom_maps)
        if atom_html:
            sections.append(
                '<div class="sec">'
                '<div class="sec-head"><div class="sec-num">2</div>'
                '<h2>Atom-Mapped Reaction Diagrams</h2></div>'
                '<p class="sec-desc">Atoms highlighted by mapping index '
                '-- matching colors between product and precursors '
                'reveal which atoms correspond across the retrosynthetic '
                'disconnection.</p>'
                f'{atom_html}</div>'
            )

    # --- Section 3: Convergence Network ---
    if include_network and trees:
        logging.info("Generating convergence network...")
        net_b64 = _build_convergence_network(trees)
        if net_b64:
            n_trees = min(len(trees), max_routes)
            sections.append(
                '<div class="sec">'
                '<div class="sec-head"><div class="sec-num">3</div>'
                '<h2>Multi-Route Convergence Network</h2></div>'
                f'<p class="sec-desc">All {n_trees} routes overlaid into '
                'a single directed graph. Shared intermediates are merged. '
                'Node size reflects how many routes pass through each '
                'molecule. Green = in stock, red = not available, '
                'purple diamond = reaction steps.</p>'
                '<div class="viz-img">'
                f'<img src="data:image/png;base64,{net_b64}" '
                f'alt="Convergence Network"></div></div>'
            )

    # --- Section 4: Complexity + Radar ---
    cascade_b64 = ""
    radar_b64 = ""
    if include_complexity and trees:
        logging.info("Generating complexity cascade...")
        cascade_b64 = _build_complexity_cascade(trees[0])
    if include_radar and stats:
        logging.info("Generating search radar...")
        radar_b64 = _build_search_radar(stats)

    if cascade_b64 or radar_b64:
        if cascade_b64 and radar_b64:
            inner = (
                '<div class="viz-grid">'
                '<div class="viz-img">'
                f'<img src="data:image/png;base64,{cascade_b64}" '
                f'alt="Complexity Cascade"></div>'
                '<div class="viz-img">'
                f'<img src="data:image/png;base64,{radar_b64}" '
                f'alt="Search Radar"></div></div>'
            )
        elif cascade_b64:
            inner = (
                '<div class="viz-img">'
                f'<img src="data:image/png;base64,{cascade_b64}" '
                f'alt="Complexity Cascade"></div>'
            )
        else:
            inner = (
                '<div class="viz-img">'
                f'<img src="data:image/png;base64,{radar_b64}" '
                f'alt="Search Radar"></div>'
            )
        sections.append(
            '<div class="sec">'
            '<div class="sec-head"><div class="sec-num">4</div>'
            '<h2>Molecular Complexity Analysis</h2></div>'
            '<p class="sec-desc">Tracking how molecular complexity '
            'changes from target to precursors. A successful '
            'retrosynthetic step should reduce MW, atom count, ring '
            'systems, and polar surface area. The radar chart summarises '
            'MCTS search efficiency.</p>'
            f'{inner}</div>'
        )

    # --- Assemble full HTML ---
    n_routes_found = result.get("n_routes", len(trees))
    is_solved = result.get("is_solved", False)
    search_time = result.get("search_time", 0)
    pill_items = [
        f'<span class="pill a">{n_routes_found} routes found</span>',
        (f'<span class="pill {"c" if is_solved else "d"}">'
         f'{"Solved" if is_solved else "Unsolved"}</span>'),
        f'<span class="pill b">{search_time:.1f}s search time</span>',
    ]

    smiles_disp = smiles if len(smiles) <= 60 else smiles[:57] + "..."
    css = _report_css()
    js = ("function showR(i){"
          "document.querySelectorAll('.route-panel').forEach("
          "(e,j)=>e.style.display=j===i?'block':'none');"
          "document.querySelectorAll('.rtab').forEach("
          "(e,j)=>e.classList.toggle('on',j===i));}"
          "document.querySelectorAll('.rtab').forEach("
          "(t,i)=>t.addEventListener('click',()=>showR(i)));")

    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,'
        'initial-scale=1">'
        f'<title>{title}</title><style>{css}</style></head>'
        '<body><div class="wrap">'
        f'<div class="hero"><h1>{title}</h1>'
        f'<p>Target: <code>{smiles_disp}</code></p>'
        f'<div class="pills">{"".join(pill_items)}</div></div>'
        f'{"".join(sections)}'
        '<div style="text-align:center;padding:40px 0 16px;'
        'color:var(--t2);font-size:.82rem;">'
        '<p>Auto-generated by AiZynthFinder + RDKit + NetworkX '
        '+ Matplotlib</p>'
        '<p style="opacity:.5;margin-top:4px;">'
        'Microsoft Discovery Platform</p></div></div>'
        f'<script>{js}</script></body></html>'
    )

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as fh:
        fh.write(html)
    logging.info("Interactive report saved to %s (%d KB)",
                 output_file, len(html) // 1024)
    return {"report": output_file}



# =========================  CHECKPOINT I/O  =================================
def _load_checkpoint(path: str) -> Tuple[List[Dict], set]:
    """Load a JSONL checkpoint; return (results_list, smiles_set)."""
    if not os.path.exists(path):
        return [], set()
    results: List[Dict] = []
    smiles_done: set = set()
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                results.append(data)
                smiles_done.add(data.get("smiles", ""))
        logging.info("Loaded checkpoint: %d molecules", len(results))
    except (json.JSONDecodeError, KeyError) as exc:
        logging.warning("Corrupt checkpoint -- starting fresh: %s", exc)
        return [], set()
    return results, smiles_done


def _save_checkpoint(path: str, result: Dict) -> None:
    """Append one result to the JSONL checkpoint (trees excluded)."""
    slim = {k: v for k, v in result.items() if k != "trees"}
    with open(path, "a") as fh:
        fh.write(json.dumps(slim, default=str) + "\n")


def _save_incremental_results(results: List[Dict]) -> None:
    """Write a partial-results JSON (trees excluded) to OUTPUT_DIR."""
    slim = [{k: v for k, v in r.items() if k != "trees"} for r in results]
    path = os.path.join(OUTPUT_DIR, "results_partial.json")
    with open(path, "w") as fh:
        json.dump(slim, fh, indent=2, default=str)


# ============================  HELPERS  ======================================
def _select_policy(policy_obj: Any, name: Optional[str], required: bool = True) -> None:
    """Select a named policy on a PolicyCollection, or fall back to first available."""
    available = list(policy_obj.items)
    if name:
        policy_obj.select(name)
    elif available:
        policy_obj.select(available[0])
    elif required:
        logging.warning("No policies available for %s", type(policy_obj).__name__)


def _select_stock(stock_obj: Any, name: Optional[Union[str, List[str]]]) -> None:
    """Select stock(s) by name, or all available."""
    available = list(stock_obj.items)
    if name:
        stock_obj.select(name if isinstance(name, list) else [name])
    elif available:
        stock_obj.select(available)


def _error_result(smiles: str, error_msg: str) -> Dict[str, Any]:
    """Standard error-result dict."""
    return {
        "smiles": smiles,
        "error": error_msg,
        "is_solved": False,
        "search_time": 0,
        "stats": {},
        "routes": [],
        "stock_info": {},
        "trees": [],
        "n_routes": 0,
        "n_solved_routes": 0,
    }


def _serialisable(obj: Any) -> Any:
    """Best-effort conversion to JSON-serialisable types."""
    if isinstance(obj, dict):
        return {str(k): _serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialisable(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6) if obj == obj else None  # NaN guard
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


# ============================  CLEANUP  ======================================
def cleanup(deep: bool = False) -> None:
    """Remove temporary files.  ``deep=True`` also clears scratch dir."""
    if deep:
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
            logging.info("Cleared %d scratch files", cleared)
