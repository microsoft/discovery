#!/usr/bin/env python3
"""janus_utils.py — Discovery-platform wrapper around the JANUS genetic algorithm.

Provides a clean, reproducible API on top of janus-ga 1.0.3 (Aspuru-Guzik group) for
SELFIES-based de novo molecule generation guided by user-supplied fitness functions.

License (wrapper): MIT (governed by repository top-level LICENSE).
License (janus-ga upstream): Apache-2.0. See THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import pickle
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# ============= module-level constants (overridden by quick_setup) =============
INPUT_DIR: str = "/input"
OUTPUT_DIR: str = "/output"
WORK_DIR: str = "/workdir"

# Standard PFAS exclusion SMARTS. We treat any structure containing -CF3, -CF2-CF2-,
# or perfluorocarboxylic-acid head groups as PFAS for the purposes of this filter.
# This is intentionally CONSERVATIVE — borderline structures are rejected.
PFAS_SMARTS_PATTERNS: Tuple[str, ...] = (
    "[CX4](F)(F)F",                      # any -CF3
    "[CX4](F)(F)[CX4](F)(F)",            # -CF2-CF2-
    "C(F)(F)C(=O)O",                     # perfluorocarboxylic head
    "[SX4](=O)(=O)C(F)(F)F",             # perfluorosulfonyl
)

# Logger
logger = logging.getLogger("janus_utils")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# ============= setup / lifecycle =============

def quick_setup(
    input_dir: str = "/input",
    output_dir: str = "/output",
    work_dir: str = "/workdir",
) -> None:
    """Initialize logging, create directories, set module globals.

    Discovery convention. Always pass all three explicitly.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    logger.info("janus_utils initialized")
    logger.info("  INPUT_DIR=%s", INPUT_DIR)
    logger.info("  OUTPUT_DIR=%s", OUTPUT_DIR)
    logger.info("  WORK_DIR=%s", WORK_DIR)


def quick_finish() -> None:
    """Copy /workdir artifacts into /output. Discovery convention."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    for entry in Path(WORK_DIR).iterdir():
        target = Path(OUTPUT_DIR) / entry.name
        try:
            if entry.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(entry, target)
            else:
                shutil.copy(entry, target)
        except Exception as exc:                           # noqa: BLE001
            logger.warning("Could not copy %s -> %s: %s", entry, target, exc)
    logger.info("Workdir contents copied to %s", OUTPUT_DIR)


def save_final_results(
    results: Dict[str, Any],
    output_files: Optional[Dict[str, str]] = None,
    file_descriptions: Optional[Dict[str, str]] = None,
    status: str = "completed",
) -> str:
    """Write final_results.json into OUTPUT_DIR. MANDATORY before quick_finish()."""
    payload: Dict[str, Any] = {"status": status, "summary": results}
    if output_files:
        payload["output_files"] = output_files
    if file_descriptions:
        payload["file_descriptions"] = file_descriptions
    out = Path(OUTPUT_DIR) / "final_results.json"
    out.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote %s", out)
    return str(out)


# ============= chemistry helpers =============

def _rdkit():
    """Lazy import of RDKit so utils can be imported without it (for unit tests)."""
    from rdkit import Chem                                  # type: ignore
    from rdkit.Chem import AllChem                          # type: ignore
    return Chem, AllChem


def validate_smiles(smiles: str) -> bool:
    """Return True if *smiles* parses to a valid molecule under RDKit."""
    Chem, _ = _rdkit()
    try:
        mol = Chem.MolFromSmiles(smiles)
        return mol is not None and mol.GetNumAtoms() > 0
    except Exception:                                       # noqa: BLE001
        return False


def canonicalize_smiles(smiles: str) -> Optional[str]:
    """Return RDKit canonical SMILES, or None if parsing fails."""
    Chem, _ = _rdkit()
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        return Chem.MolToSmiles(mol, canonical=True)
    except Exception:                                       # noqa: BLE001
        return None


def validate_smiles_list(smiles_iter: Iterable[str]) -> List[str]:
    """Filter to valid, canonicalized, deduplicated SMILES preserving input order."""
    seen: set = set()
    out: List[str] = []
    for s in smiles_iter:
        canon = canonicalize_smiles(s)
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def has_pfas_substructure(
    smiles: str,
    smarts_patterns: Sequence[str] = PFAS_SMARTS_PATTERNS,
) -> bool:
    """True if *smiles* matches ANY pattern in *smarts_patterns*."""
    Chem, _ = _rdkit()
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return False
    for patt in smarts_patterns:
        sm = Chem.MolFromSmarts(patt)
        if sm is not None and mol.HasSubstructMatch(sm):
            return True
    return False


class PfasFilter:
    """Picklable PFAS-rejection filter for JANUS's ``custom_filter`` slot.

    Returns True (KEEP) for molecules that parse and do NOT match any PFAS
    SMARTS pattern. Returns False (REJECT) for invalid SMILES or any PFAS hit.

    Implemented as a top-level class (not a closure) so it can be pickled and
    passed to multiprocessing workers in sharded ``run_janus`` runs.
    """

    __slots__ = ("smarts_patterns",)

    def __init__(self, smarts_patterns: Sequence[str] = PFAS_SMARTS_PATTERNS) -> None:
        self.smarts_patterns = tuple(smarts_patterns)

    def __call__(self, smiles: str) -> bool:
        if not validate_smiles(smiles):
            return False
        try:
            return not has_pfas_substructure(smiles, self.smarts_patterns)
        except Exception:                                   # noqa: BLE001
            return False

    def __repr__(self) -> str:
        return f"PfasFilter(n_patterns={len(self.smarts_patterns)})"


def make_pfas_filter(
    smarts_patterns: Sequence[str] = PFAS_SMARTS_PATTERNS,
) -> "PfasFilter":
    """Return a picklable callable(smiles) -> bool for JANUS's ``custom_filter`` slot.

    JANUS calls custom_filter(smiles) and KEEPS the molecule when it returns True,
    so this returns False on PFAS hits and on unparseable SMILES.

    The returned object is an instance of :class:`PfasFilter` (a top-level
    callable class), which means it survives pickling and can be passed to
    multiprocessing workers in sharded runs.
    """
    return PfasFilter(smarts_patterns)


def post_filter_scored(
    scored: Sequence[Dict[str, Any]],
    custom_filter: Callable[[str], bool],
) -> List[Dict[str, Any]]:
    """Apply *custom_filter* to a ``scored`` list and drop rejected molecules.

    Use this on ``run_janus`` output when the filter encodes a HARD constraint
    (e.g. regulatory PFAS-free requirement). The internal ``_FilterGuard``
    eventually accepts molecules unconditionally to prevent infinite loops on
    over-strict filters, so the returned ``scored`` list is NOT a guaranteed
    constraint-satisfying set on its own. Post-filtering closes that gap.

    Parameters
    ----------
    scored
        The ``scored`` list from ``run_janus``: ``[{smiles, score}, ...]``.
    custom_filter
        Same callable contract as JANUS: True = keep, False = reject.

    Returns
    -------
    List of entries from *scored* for which ``custom_filter`` returned True.
    """
    out: List[Dict[str, Any]] = []
    for row in scored:
        try:
            if custom_filter(row["smiles"]):
                out.append(row)
        except Exception:                                   # noqa: BLE001
            continue
    return out


# ============= seed handling =============

def write_start_population(
    smiles: Sequence[str],
    path: str,
) -> str:
    """Write a JANUS start_population file: one SMILES per line.

    Returns the absolute path written.
    """
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    valid = validate_smiles_list(smiles)
    if not valid:
        raise ValueError("write_start_population: no valid SMILES in input")
    Path(abs_path).write_text("\n".join(valid) + "\n")
    logger.info("Wrote %d seed SMILES to %s", len(valid), abs_path)
    return abs_path


# ============= scoring helpers =============

def score_property_target(
    smiles: str,
    descriptor_fn: Callable[[str], float],
    target: float,
    tolerance: float = 1.0,
) -> float:
    """Generic 'closer to target = higher score' fitness in [0, 1].

    score = 1 / (1 + ((value - target) / tolerance) ** 2)

    Returns 0.0 on any exception (so JANUS doesn't crash on a single bad mol).
    """
    try:
        value = float(descriptor_fn(smiles))
    except Exception:                                       # noqa: BLE001
        return 0.0
    return 1.0 / (1.0 + ((value - target) / max(tolerance, 1e-9)) ** 2)


def molecular_weight(smiles: str) -> float:
    """RDKit exact molecular weight (Da). Returns NaN on parse failure."""
    Chem, _ = _rdkit()
    from rdkit.Chem import Descriptors                      # type: ignore
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return float("nan")
    return float(Descriptors.MolWt(mol))


# ============= SELFIES alphabet / element constraints =============

def _apply_element_constraints(
    allowed_elements: Dict[str, int],
) -> List[str]:
    """Restrict the SELFIES alphabet to only produce molecules with *allowed_elements*.

    Parameters
    ----------
    allowed_elements : dict
        Mapping of element symbol to maximum bond order.
        Example: ``{'C': 4, 'O': 2, 'Si': 4, 'H': 1}``
        Hydrogen is implicitly added if not present (max_bonds=1).

    Returns
    -------
    list of str
        The restricted SELFIES alphabet (tokens that only reference the
        allowed elements). Includes structural tokens (Branch, Ring, Expl=Ring).

    Side Effects
    ------------
    Calls ``selfies.set_semantic_constraints(bond_constraints)`` which
    modifies SELFIES global state. Caller is responsible for restoring
    defaults afterward via ``selfies.set_semantic_constraints('default')``.
    """
    import selfies as sf

    # Ensure H is always present (SELFIES needs it for [Hexpl] tokens).
    constraints = dict(allowed_elements)
    if "H" not in constraints:
        constraints["H"] = 1
    # The '?' key is REQUIRED by selfies — it sets the default max bonds for
    # any element NOT explicitly listed. Setting it to 1 (minimum allowed)
    # means unlisted elements can only form single bonds. We then filter
    # them out of the alphabet below so they never appear in mutations.
    constraints["?"] = 1

    # Apply constraints — SELFIES will only decode molecules with these elements.
    sf.set_semantic_constraints(constraints)
    logger.info(
        "SELFIES semantic constraints set: %s",
        {k: v for k, v in sorted(constraints.items())},
    )

    # Now derive the restricted alphabet by querying the constrained grammar.
    full_alphabet = sf.get_semantic_robust_alphabet()

    # Additionally filter out tokens referencing elements NOT in our set.
    # The robust alphabet after set_semantic_constraints should already be
    # limited, but we double-check by parsing token element references.
    element_symbols = set(constraints.keys())

    # Map element symbols to the patterns they produce in SELFIES tokens.
    # Token format: [<bond_prefix><Element><charge_suffix>]
    # Examples: [C], [=C], [#C], [C+1expl], [=O+1expl], [Si], [=Si]
    # Structural tokens: [Branch1_1], [Ring1], [Expl=Ring1], [Hexpl]
    structural_prefixes = ("Branch", "Ring", "Expl=Ring")

    def _is_allowed_token(token: str) -> bool:
        inner = token.strip("[]")
        # Structural tokens are always allowed.
        if any(inner.startswith(p) for p in structural_prefixes):
            return True
        # [Hexpl] — explicit hydrogen.
        if inner == "Hexpl":
            return "H" in element_symbols
        # Element tokens: strip bond prefix (=, #) and charge suffix (+N, -N, expl).
        stripped = inner.lstrip("=#")
        # Extract the element symbol (1-2 uppercase+lowercase chars).
        m = re.match(r"([A-Z][a-z]?)", stripped)
        if m:
            return m.group(1) in element_symbols
        return False

    restricted = [t for t in full_alphabet if _is_allowed_token(t)]
    logger.info(
        "Restricted SELFIES alphabet: %d tokens (from %d full). Elements: %s",
        len(restricted), len(full_alphabet), sorted(element_symbols),
    )
    return restricted


def _restore_selfies_defaults() -> None:
    """Restore SELFIES to its default (unconstrained) semantic constraints."""
    import selfies as sf
    # selfies 1.0.3 does not accept the string "default"; we must pass
    # a dict with the '?' wildcard key. Use the well-known organic defaults.
    default_constraints = {
        "?": 8,
        "H": 1, "F": 1, "Cl": 1, "Br": 1, "I": 1,
        "O": 2, "S": 6,
        "N": 3, "P": 5,
        "C": 4, "Si": 4,
    }
    sf.set_semantic_constraints(default_constraints)
    logger.info("SELFIES semantic constraints restored to defaults.")


# ============= FilterGuard (timeout protection) =============

class _FilterGuard:
    """Wraps a user-supplied ``custom_filter`` with a consecutive-rejection cap.

    JANUS calls ``custom_filter(smiles)`` inside a tight ``while`` loop that
    has **no upper bound**.  If the filter rejects nearly everything (e.g.
    atom-type restriction without ``allowed_elements``), the loop runs for
    tens of thousands of iterations, burning compute indefinitely.

    ``_FilterGuard`` counts consecutive rejections.  After
    ``max_consecutive_rejects`` (default: ``generation_size * 100``) the guard
    switches to **accept-all mode** for the remainder of the current burst.
    Accepted molecules reset the counter, so a healthy filter never triggers
    the cap.

    Behaviour in accept-all mode:
      - The candidate is accepted regardless of the inner filter's verdict.
      - A warning is logged once per burst (not per candidate).
      - The fitness function still scores the molecule, so bad candidates
        receive low scores and are selected out in the next generation.
      - All per-generation result files are written normally.

    This is strictly safer than raising an exception because:
      1. The JANUS generation completes, writing population/fitness files.
      2. The result-collection code in ``_run_janus`` runs and gathers data.
      3. Partial results are never lost.

    Parameters
    ----------
    inner_filter : callable or None
        The user's original ``custom_filter(smiles) -> bool``.
        ``None`` means accept-all (no wrapping needed, but harmless).
    max_consecutive_rejects : int
        Cap before switching to accept-all.  Default: 50000.
    """

    def __init__(
        self,
        inner_filter: Optional[Callable[[str], bool]],
        max_consecutive_rejects: int = 50_000,
    ) -> None:
        self._inner = inner_filter
        self._max = max_consecutive_rejects
        self._consecutive = 0
        self._tripped = False          # True once per burst
        self._trip_count = 0           # total number of times the cap fired
        self._total_calls = 0
        self._total_rejects = 0
        self._total_accepts = 0
        self._accept_all_accepts = 0   # accepted only because of cap
        # JANUS's save_hyperparameters() calls v.__name__ on callables.
        # Provide one so it doesn't crash.
        self.__name__ = (
            f"FilterGuard({inner_filter.__name__ if inner_filter and hasattr(inner_filter, '__name__') else 'None'})"
        )

    def __call__(self, smiles: str) -> bool:
        self._total_calls += 1

        # If there is no inner filter, always accept.
        if self._inner is None:
            self._total_accepts += 1
            self._consecutive = 0
            return True

        # Delegate to the inner filter.
        try:
            passed = self._inner(smiles)
        except Exception:                                   # noqa: BLE001
            passed = False

        if passed:
            self._total_accepts += 1
            self._consecutive = 0
            self._tripped = False      # reset burst flag on any accept
            return True

        # Rejection path.
        self._total_rejects += 1
        self._consecutive += 1

        if self._consecutive >= self._max:
            if not self._tripped:
                self._tripped = True
                self._trip_count += 1
                logger.warning(
                    "FilterGuard: %d consecutive rejections reached cap (%d). "
                    "Accepting unfiltered candidates until next natural accept. "
                    "(trip #%d, total calls so far: %d)",
                    self._consecutive, self._max,
                    self._trip_count, self._total_calls,
                )
            self._total_accepts += 1
            self._accept_all_accepts += 1
            return True                # accept despite filter rejection

        return False

    @property
    def stats(self) -> Dict[str, Any]:
        """Summary dict for inclusion in run results."""
        return {
            "total_calls": self._total_calls,
            "total_accepts": self._total_accepts,
            "total_rejects": self._total_rejects,
            "cap_triggered_times": self._trip_count,
            "cap_forced_accepts": self._accept_all_accepts,
            "max_consecutive_rejects": self._max,
        }


# ============= single-instance runner (internal) =============

def _run_janus(
    seed_smiles: Sequence[str],
    fitness_function: Callable[[str], float],
    *,
    work_dir: Optional[str] = None,
    custom_filter: Optional[Callable[[str], bool]] = None,
    allowed_elements: Optional[Dict[str, int]] = None,
    generations: int = 10,
    generation_size: int = 200,
    num_workers: Optional[int] = None,
    use_classifier: bool = False,
    use_fragments: bool = False,
    top_mols: int = 1,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Run a single JANUS instance. Internal — use ``run_janus`` instead.

    Parameters
    ----------
    seed_smiles
        Initial population. Will be validated and canonicalized.
    fitness_function
        Callable(smiles) -> float. Higher = better. Raise-safe (errors -> 0.0).
    work_dir
        Working directory for JANUS scratch files. Defaults to module WORK_DIR.
    custom_filter
        Callable(smiles) -> bool. Return False to REJECT a molecule. None = accept all.
    allowed_elements
        Optional dict mapping element symbols to max bond orders.
        When provided, restricts SELFIES mutations to only produce molecules
        containing these elements. Example: ``{'C': 4, 'O': 2, 'Si': 4}``
        Hydrogen is added implicitly. Mutually exclusive with relying on
        the default full alphabet.
    generations
        Number of GA generations. Smoke tests use 5-10; production runs use 50-200.
    generation_size
        Population size per generation. Increase for harder fitness landscapes.
    num_workers
        multiprocessing workers for fitness evaluation. None = JANUS picks (cpu_count).
    use_classifier
        If True, JANUS trains a torch DNN per generation to bias the exploit branch.
        SLOW but more sample-efficient on hard problems. Smoke tests should use False.
    use_fragments
        If True, JANUS uses fragment-based mutations. Slightly slower setup,
        often produces more chemistry-realistic structures.
    top_mols
        Per-generation top-N to track in the verbose output.
    verbose
        Pass through to JANUS's verbose_out flag.

    Returns
    -------
    dict with keys:
        seed_count           : int
        valid_seed_count     : int
        generations          : int
        generation_size      : int
        work_dir             : str
        all_smiles           : List[str] — every UNIQUE valid molecule produced
        scored               : List[Dict[str, Any]] — [{smiles, score}] sorted desc
        best                 : Dict[str, Any]    — top scorer
        elapsed_seconds      : float
    """

    from janus import JANUS                                 # type: ignore

    Chem, _ = _rdkit()

    if work_dir is None:
        work_dir = WORK_DIR
    work_dir = os.path.abspath(work_dir)
    os.makedirs(work_dir, exist_ok=True)

    # Validate + canonicalize seeds; write a one-per-line file for JANUS.
    valid_seeds = validate_smiles_list(seed_smiles)
    # JANUS requires len(start_population) >= generation_size.
    # Pad by recycling seeds if needed (the GA will diversify quickly).
    if len(valid_seeds) < generation_size:
        original_len = len(valid_seeds)
        while len(valid_seeds) < generation_size:
            valid_seeds = valid_seeds + valid_seeds[:generation_size - len(valid_seeds)]
        valid_seeds = valid_seeds[:generation_size]
        logger.info(
            "Padded seed population from %d to %d (JANUS requires seeds >= generation_size)",
            original_len, len(valid_seeds),
        )

    if len(valid_seeds) < 1:
        raise ValueError("_run_janus: no valid seed SMILES")
    # Write the (possibly padded, with duplicates) seed file directly.
    # We bypass write_start_population here because it deduplicates, which would
    # undo the padding. JANUS needs len(file_lines) >= generation_size.
    seed_path = os.path.join(work_dir, "seeds.txt")
    Path(seed_path).write_text("\n".join(valid_seeds) + "\n")
    logger.info("Wrote %d seed lines to %s (unique: %d)", len(valid_seeds), seed_path, len(set(valid_seeds)))

    logger.info(
        "JANUS run: gens=%d, pop=%d, seeds=%d, classifier=%s, fragments=%s, allowed_elements=%s",
        generations, generation_size, len(valid_seeds), use_classifier, use_fragments,
        allowed_elements,
    )

    # ---- Startup banner (stdout) for easy debugging in job logs ----
    print(f"\n{'='*70}")
    print(f"  JANUS janus_utils v1.2.0 — run configuration")
    print(f"{'='*70}")
    print(f"  generations:       {generations}")
    print(f"  generation_size:   {generation_size}")
    print(f"  seeds (unique):    {len(set(valid_seeds))}")
    print(f"  seeds (padded):    {len(valid_seeds)}")
    print(f"  use_classifier:    {use_classifier}")
    print(f"  use_fragments:     {use_fragments}")
    print(f"  num_workers:       {num_workers if num_workers is not None else '(auto)'}")
    print(f"  work_dir:          {work_dir}")
    print(f"  allowed_elements:  {allowed_elements}")
    print(f"  custom_filter:     {custom_filter.__name__ if custom_filter and hasattr(custom_filter, '__name__') else repr(custom_filter)}")
    print(f"  FilterGuard:       ACTIVE (cap = {generation_size * 10} consecutive rejects)")
    print(f"{'='*70}\n")

    # Apply element constraints if requested, otherwise derive alphabet from seeds.
    import selfies as sf                                    # type: ignore

    if allowed_elements is not None:
        alphabet = _apply_element_constraints(allowed_elements)
    else:
        # Discover the SELFIES alphabet from seeds (avoids JANUS yelling about unknown tokens).
        alphabet = list(sf.get_alphabet_from_selfies(
            sf.encoder(s) for s in valid_seeds if sf.encoder(s) is not None
        ))

    if num_workers is None:
        num_workers = max(1, (multiprocessing.cpu_count() or 2) - 1)

    # Wrap the user's custom_filter in a FilterGuard to prevent infinite loops.
    # FIX 2: Lowered cap from generation_size*100 to generation_size*10.
    # 50K consecutive rejections is never useful; 5K is generous enough for
    # a healthy filter while catching starvation 10x faster.
    guard = _FilterGuard(
        inner_filter=custom_filter,
        max_consecutive_rejects=generation_size * 10,
    )
    logger.info(
        "FilterGuard active: cap=%d consecutive rejects (generation_size=%d x 10)",
        generation_size * 10, generation_size,
    )

    t0 = time.time()
    try:
        agent = JANUS(
            work_dir=work_dir,
            fitness_function=fitness_function,
            start_population=seed_path,
            custom_filter=guard,
            alphabet=alphabet,
            use_gpu=False,                # CPU-only platform
            num_workers=num_workers,
            generations=generations,
            generation_size=generation_size,
            use_fragments=use_fragments,
            use_classifier=use_classifier,
            top_mols=top_mols,
            verbose_out=verbose,
        )
        agent.run()
    finally:
        # Always restore SELFIES defaults if we changed them.
        if allowed_elements is not None:
            _restore_selfies_defaults()

    elapsed = time.time() - t0
    logger.info("JANUS finished in %.1fs", elapsed)
    logger.info("FilterGuard stats: %s", guard.stats)

    # Collect results — JANUS writes population_explore.txt / population_local_search.txt
    # per generation in work_dir. Aggregate everything we can find.
    all_seen: Dict[str, float] = {}
    score_files = sorted(Path(work_dir).glob("**/fitness_*.txt"))
    smiles_files = sorted(Path(work_dir).glob("**/population_*.txt"))
    # Pair each population file with its sibling fitness file by name suffix.
    for pop_file in smiles_files:
        fit_file = pop_file.with_name(pop_file.name.replace("population_", "fitness_"))
        if not fit_file.exists():
            continue
        try:
            # JANUS writes SMILES one-per-line, but fitness values may be
            # space-separated on a single line OR one-per-line. Handle both.
            smis = [s.strip() for s in pop_file.read_text().splitlines() if s.strip()]
            raw_fit = fit_file.read_text().strip()
            # Try splitting on whitespace first (space-separated single line)
            fit_tokens = raw_fit.split()
            fits = [float(x) for x in fit_tokens]
            for s, f in zip(smis, fits):
                canon = canonicalize_smiles(s)
                if canon is None:
                    continue
                # Keep the BEST observed score per unique molecule.
                if canon not in all_seen or f > all_seen[canon]:
                    all_seen[canon] = f
        except Exception as exc:                            # noqa: BLE001
            logger.warning("Could not parse %s / %s: %s", pop_file, fit_file, exc)

    if not all_seen:
        # Fallback: re-score the seed population so we always return something usable.
        for s in valid_seeds:
            try:
                all_seen[s] = float(fitness_function(s))
            except Exception:                               # noqa: BLE001
                all_seen[s] = 0.0

    scored: List[Dict[str, Any]] = sorted(
        ({"smiles": s, "score": float(f)} for s, f in all_seen.items()),
        key=lambda d: d["score"],
        reverse=True,
    )

    return {
        "seed_count": len(seed_smiles),
        "valid_seed_count": len(valid_seeds),
        "generations": generations,
        "generation_size": generation_size,
        "work_dir": work_dir,
        "all_smiles": [d["smiles"] for d in scored],
        "scored": scored,
        "best": scored[0] if scored else None,
        "elapsed_seconds": elapsed,
        "n_unique_generated": len(scored),
        "n_score_files": len(score_files),
        "filter_guard_stats": guard.stats,
    }



# ============= sharded runner (multi-instance parallelism) =============


def _shard_worker(kwargs: Dict[str, Any], result_path: str) -> None:
    """Run a single JANUS shard in a child Process and write results to disk.

    This function is the ``target`` of a ``multiprocessing.Process``.
    Unlike ``Pool`` workers, raw ``Process`` objects are **non-daemonic** by
    default, which means JANUS can freely create its own inner
    ``multiprocessing.Pool`` for fitness evaluation without hitting the
    "daemonic processes are not allowed to have children" assertion.

    Results are serialized to *result_path* as JSON so the parent can read
    them after ``join()`` without needing a ``Queue`` (avoids large-object
    pickle and is more robust on unexpected worker death).

    JANUS internally does ``os.mkdir(f"./{self.work_dir}")`` using a path
    relative to CWD.  When work_dir is absolute (e.g. ``/workdir/shard_00``),
    the ``./`` prefix produces ``.//workdir/shard_00`` which only resolves
    when CWD is ``/``.  We chdir to ``/`` before calling ``_run_janus``.
    """
    os.chdir("/")
    t0 = time.time()
    try:
        result = _run_janus(**kwargs)
        result["shard_elapsed_seconds"] = time.time() - t0
        result["shard_error"] = None
    except Exception:
        result = {
            "shard_elapsed_seconds": time.time() - t0,
            "shard_error": traceback.format_exc(),
            "scored": [],
            "all_smiles": [],
            "best": None,
            "n_unique_generated": 0,
        }
        logger.exception("Shard worker failed")
    # Write result to disk (JSON).  The parent reads this after join().
    Path(result_path).write_text(json.dumps(result, indent=2, default=str))

    # FIX 3: Also flush to /output/ immediately so partial results survive
    # cancellation even if other shards are still running or stuck.
    shard_name = Path(result_path).parent.name  # e.g. "shard_00"
    output_copy = Path(OUTPUT_DIR) / f"{shard_name}_results.json"
    try:
        output_copy.write_text(json.dumps(result, indent=2, default=str))
        logger.info("Shard %s results flushed to %s (%d unique mols)",
                     shard_name, output_copy, result.get("n_unique_generated", 0))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not flush shard results to output: %s", exc)


def run_janus(
    seed_smiles: Sequence[str],
    fitness_function: Callable[[str], float],
    *,
    work_dir: Optional[str] = None,
    custom_filter: Optional[Callable[[str], bool]] = None,
    allowed_elements: Optional[Dict[str, int]] = None,
    generations: int = 10,
    generation_size: int = 200,
    shards: Optional[int] = None,
    cpus_per_shard: int = 24,
    use_classifier: bool = False,
    use_fragments: bool = False,
    top_mols: int = 1,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Run the JANUS genetic algorithm with automatic multi-instance sharding.

    The primary entry point for JANUS molecule generation. On multi-core SKUs
    (>= 48 vCPUs by default), runs N independent JANUS instances in parallel,
    each with its own seed slice, work directory, and classifier. Results are
    merged by canonical SMILES, keeping the best (max) fitness per molecule.

    On small SKUs (<= 24 vCPUs with default ``cpus_per_shard``), ``shards``
    collapses to 1 and the function delegates to a single JANUS instance --
    identical to running the algorithm directly.

    Parameters
    ----------
    seed_smiles : Sequence[str]
        Initial population. Will be validated and canonicalized.
    fitness_function : Callable[[str], float]
        Callable(smiles) -> float. Higher = better. Must be picklable
        (module-level function or callable class) when ``shards > 1``.
        On single-shard runs, lambdas and closures work fine — the
        picklability check is only enforced when sharding is actually used.
    work_dir : str or None
        Working directory for JANUS scratch files. Defaults to module WORK_DIR.
    custom_filter : Callable[[str], bool] or None
        Callable(smiles) -> bool. Return False to REJECT a molecule.
        Must be picklable when ``shards > 1`` (use :class:`PfasFilter` /
        :func:`make_pfas_filter` or a top-level function/callable class).
        ``None`` = accept all.
    allowed_elements : dict or None
        Restrict SELFIES mutations to only produce molecules containing these
        elements. Keys are element symbols (e.g. ``'C'``, ``'Si'``, ``'O'``),
        values are the maximum number of bonds that element can form.
        Example: ``{'C': 4, 'O': 2, 'Si': 4}``
        Hydrogen is added implicitly. When ``None`` (default), the full
        SELFIES alphabet is used (all organic elements).
        **Use this when your custom_filter restricts atom types** -- it
        prevents the GA from wasting iterations generating molecules that
        will be immediately rejected by the filter.
    generations : int
        Number of GA generations per shard.
    generation_size : int
        Population size per generation per shard.
    shards : int or None
        Number of independent JANUS instances. ``None`` (default) auto-sizes
        from ``multiprocessing.cpu_count() // cpus_per_shard``.
    cpus_per_shard : int
        Target vCPU count per shard. Default 24.
    use_classifier : bool
        If True, JANUS trains a DNN per generation to bias the exploit branch.
    use_fragments : bool
        If True, JANUS uses fragment-based mutations.
    top_mols : int
        Per-generation top-N to track in the verbose output.
    verbose : bool
        Pass through to JANUS's verbose_out flag.

    Returns
    -------
    dict with keys:
        seed_count, valid_seed_count, generations, generation_size, work_dir,
        all_smiles, scored, best, elapsed_seconds, n_unique_generated,
        shards, cpus_per_shard, per_shard_elapsed_seconds.
    """
    # --- Resolve work_dir ---
    if work_dir is None:
        work_dir = WORK_DIR
    work_dir = os.path.abspath(work_dir)
    os.makedirs(work_dir, exist_ok=True)

    # --- Validate + canonicalize seeds ---
    valid_seeds = validate_smiles_list(seed_smiles)
    if len(valid_seeds) < 1:
        raise ValueError("run_janus: no valid seed SMILES")

    # --- Determine shard count ---
    if shards is None:
        shards = max(1, (multiprocessing.cpu_count() or 1) // cpus_per_shard)
    # Each shard needs at least 1 unique seed (padding handles generation_size).
    # If the user asked for more shards than we have unique seeds, cap to the
    # seed count rather than silently duplicating seed groups across shards
    # (duplication would converge the GA on the same scaffolds and waste cores).
    if shards > len(valid_seeds):
        logger.info(
            "Requested shards=%d exceeds unique seed count=%d; capping to %d. "
            "To utilise more cores, supply additional diverse seeds.",
            shards, len(valid_seeds), len(valid_seeds),
        )
        shards = len(valid_seeds)
    shards = max(shards, 1)

    # --- Picklability gate (only enforced when sharding is actually used) ---
    # On a single-shard run we delegate directly to ``_run_janus`` in-process,
    # so lambdas and closures work fine. Only pickle when shards > 1.
    if shards > 1:
        try:
            pickle.dumps(fitness_function)
        except (pickle.PicklingError, AttributeError, TypeError) as exc:
            raise ValueError(
                f"fitness_function is not picklable ({exc}). "
                "Required for multi-shard runs (shards > 1). "
                "Define it as a module-level function or callable class, "
                "or pass shards=1 to keep using a lambda/closure."
            ) from exc
        if custom_filter is not None:
            try:
                pickle.dumps(custom_filter)
            except (pickle.PicklingError, AttributeError, TypeError) as exc:
                raise ValueError(
                    f"custom_filter is not picklable ({exc}). "
                    "Required for multi-shard runs (shards > 1). "
                    "Use make_pfas_filter()/PfasFilter or a top-level "
                    "callable class, or pass shards=1."
                ) from exc

    # --- Short-circuit: single shard -> delegate directly ---
    if shards == 1:
        logger.info(
            "JANUS sharded run: shards=1 (SKU <= %d vCPUs or single seed group). "
            "Delegating to _run_janus.",
            cpus_per_shard,
        )
        t0 = time.time()
        result = _run_janus(
            seed_smiles=seed_smiles,
            fitness_function=fitness_function,
            work_dir=work_dir,
            custom_filter=custom_filter,
            allowed_elements=allowed_elements,
            generations=generations,
            generation_size=generation_size,
            num_workers=max(1, (multiprocessing.cpu_count() or 2) - 1),
            use_classifier=use_classifier,
            use_fragments=use_fragments,
            top_mols=top_mols,
            verbose=verbose,
        )
        elapsed = time.time() - t0
        result["shards"] = 1
        result["cpus_per_shard"] = cpus_per_shard
        result["per_shard_elapsed_seconds"] = [elapsed]
        result["elapsed_seconds"] = elapsed
        return result

    # --- Partition seeds round-robin ---
    seed_groups: List[List[str]] = [[] for _ in range(shards)]
    for idx, smi in enumerate(valid_seeds):
        seed_groups[idx % shards].append(smi)

    # --- Build per-shard kwargs and result paths ---
    shard_kwargs: List[Dict[str, Any]] = []
    result_paths: List[str] = []
    for i, seeds_i in enumerate(seed_groups):
        shard_dir = os.path.join(work_dir, f"shard_{i:02d}")
        os.makedirs(shard_dir, exist_ok=True)
        result_path = os.path.join(shard_dir, "_shard_result.json")
        result_paths.append(result_path)
        logger.info(
            "JANUS shard %02d/%02d: seeds=%d work_dir=%s cpus=%d",
            i, shards, len(seeds_i), shard_dir, cpus_per_shard,
        )
        shard_kwargs.append(
            dict(
                seed_smiles=seeds_i,
                fitness_function=fitness_function,
                work_dir=shard_dir,
                custom_filter=custom_filter,
                allowed_elements=allowed_elements,
                generations=generations,
                generation_size=generation_size,
                num_workers=cpus_per_shard,
                use_classifier=use_classifier,
                use_fragments=use_fragments,
                top_mols=top_mols,
                verbose=verbose,
            )
        )

    # --- Launch shards as non-daemonic Processes ---
    # We use explicit multiprocessing.Process objects (NOT Pool) because:
    #  - Pool workers are daemonic and cannot spawn child processes.
    #  - JANUS internally creates its own multiprocessing.Pool for fitness
    #    evaluation, which requires the worker to be non-daemonic.
    #  - Raw Process objects are non-daemonic by default, so JANUS's inner
    #    Pool works without restriction.
    # We use fork context (Linux only) so child processes inherit the parent's
    # memory, including fitness_function and custom_filter references.
    # Results are passed through JSON files (one per shard work_dir) to avoid
    # Queue serialization issues with large result dicts.
    t0 = time.time()
    ctx = multiprocessing.get_context("fork")
    processes: List[multiprocessing.Process] = []
    for kw, rp in zip(shard_kwargs, result_paths):
        p = ctx.Process(target=_shard_worker, args=(kw, rp))
        p.start()
        processes.append(p)

    # Wait for all shards to finish.
    # FIX 4: Add a timeout so stuck shards don't block the parent forever.
    # 4 hours is generous — a 25-gen x 500-pop shard with classifier typically
    # finishes in 2-3 hours. If a shard exceeds this, it is almost certainly stuck.
    SHARD_TIMEOUT = 4 * 3600  # seconds
    for i, p in enumerate(processes):
        p.join(timeout=SHARD_TIMEOUT)
        if p.is_alive():
            logger.warning(
                "Shard %d (PID %d) still alive after %ds timeout. Terminating.",
                i, p.pid, SHARD_TIMEOUT,
            )
            p.terminate()
            p.join(timeout=30)
            if p.is_alive():
                logger.error("Shard %d (PID %d) did not terminate. Killing.", i, p.pid)
                p.kill()
                p.join(timeout=10)

    wall_elapsed = time.time() - t0

    # --- Read shard results from disk ---
    shard_results: List[Dict[str, Any]] = []
    for i, rp in enumerate(result_paths):
        try:
            shard_results.append(json.loads(Path(rp).read_text()))
        except Exception as exc:
            logger.error("Failed to read shard %d result from %s: %s", i, rp, exc)
            shard_results.append({"scored": [], "shard_elapsed_seconds": 0.0,
                                  "shard_error": str(exc)})

    # Log any shard errors
    for i, sr in enumerate(shard_results):
        if sr.get("shard_error"):
            logger.error("Shard %d failed:\n%s", i, sr["shard_error"])

    # --- Merge results: union by canonical SMILES, keep max score ---
    merged: Dict[str, float] = {}
    for sr in shard_results:
        for entry in sr.get("scored", []):
            smi = entry["smiles"]
            score = entry["score"]
            if smi not in merged or score > merged[smi]:
                merged[smi] = score

    scored: List[Dict[str, Any]] = sorted(
        [{"smiles": s, "score": float(f)} for s, f in merged.items()],
        key=lambda d: d["score"],
        reverse=True,
    )

    per_shard_elapsed = [sr.get("shard_elapsed_seconds", 0.0) for sr in shard_results]
    max_shard_time = max(per_shard_elapsed) if per_shard_elapsed else 0.0

    # Aggregate FilterGuard stats across shards so callers can see whether
    # the cap was triggered (i.e. whether any forced accepts polluted the
    # output and a hard post-filter is needed).
    agg_stats: Dict[str, int] = {
        "total_calls": 0,
        "total_accepts": 0,
        "total_rejects": 0,
        "cap_triggered_times": 0,
        "cap_forced_accepts": 0,
        "max_consecutive_rejects": 0,
    }
    per_shard_guard: List[Dict[str, Any]] = []
    for sr in shard_results:
        stats = sr.get("filter_guard_stats") or {}
        per_shard_guard.append(stats)
        for key in ("total_calls", "total_accepts", "total_rejects",
                    "cap_triggered_times", "cap_forced_accepts"):
            agg_stats[key] += int(stats.get(key, 0) or 0)
        agg_stats["max_consecutive_rejects"] = max(
            agg_stats["max_consecutive_rejects"],
            int(stats.get("max_consecutive_rejects", 0) or 0),
        )

    if agg_stats["cap_triggered_times"] > 0:
        logger.warning(
            "FilterGuard cap fired %d time(s) across shards (forced accepts: %d). "
            "Output may include molecules the custom_filter would reject; "
            "use post_filter_scored() to enforce hard constraints.",
            agg_stats["cap_triggered_times"], agg_stats["cap_forced_accepts"],
        )

    logger.info(
        "JANUS sharded run finished: %d shards, max shard %.1fs, "
        "total wall %.1fs, unique mols %d",
        shards, max_shard_time, wall_elapsed, len(scored),
    )

    return {
        "seed_count": len(seed_smiles),
        "valid_seed_count": len(valid_seeds),
        "generations": generations,
        "generation_size": generation_size,
        "work_dir": work_dir,
        "all_smiles": [d["smiles"] for d in scored],
        "scored": scored,
        "best": scored[0] if scored else None,
        "elapsed_seconds": wall_elapsed,
        "n_unique_generated": len(scored),
        "shards": shards,
        "cpus_per_shard": cpus_per_shard,
        "per_shard_elapsed_seconds": per_shard_elapsed,
        "filter_guard_stats": agg_stats,
        "per_shard_filter_guard_stats": per_shard_guard,
    }


# ============= convenience =============

def write_results_csv(scored: Sequence[Dict[str, Any]], path: str) -> str:
    """Write a [(smiles, score)] table to *path* (CSV)."""
    import csv
    abs_path = os.path.abspath(path)
    with open(abs_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["smiles", "score"])
        for row in scored:
            writer.writerow([row["smiles"], f'{row["score"]:.6f}'])
    logger.info("Wrote %d rows to %s", len(scored), abs_path)
    return abs_path
