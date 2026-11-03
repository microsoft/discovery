"""Classical and space-filling design-of-experiments generators.

Every generator returns points in **native units** for the supplied
:class:`~space.ParameterSpace`, so designs can be handed straight to an
experimentalist or used to seed a Bayesian optimization loop.

Design families
---------------
* Screening / factorial: full factorial, 2-level fractional factorial,
  Plackett-Burman.
* Response surface: central composite (CCD), Box-Behnken.
* Space filling: Latin hypercube (maximin), Sobol, maximin-augmented random.
* Mixture: simplex lattice, simplex centroid, extreme-vertices, constrained
  space-filling on the bounded simplex.
"""

from __future__ import annotations

import itertools
from typing import Optional, Sequence

import numpy as np

from space import ParameterSpace

__all__ = [
    "doe_full_factorial",
    "doe_fractional_factorial",
    "doe_plackett_burman",
    "doe_central_composite",
    "doe_box_behnken",
    "doe_latin_hypercube",
    "doe_sobol",
    "doe_simplex_lattice",
    "doe_simplex_centroid",
    "doe_extreme_vertices",
    "doe_mixture_space_filling",
    "generate_design",
    "design_diagnostics",
]


# --------------------------------------------------------------------------
# Factorial / screening designs
# --------------------------------------------------------------------------
def doe_full_factorial(space: ParameterSpace, levels: int | Sequence[int] = 2,
                       center_points: int = 0) -> np.ndarray:
    """Full factorial design.

    Args:
        space: Box parameter space.
        levels: Number of levels per factor (int, or one int per factor).
        center_points: Replicated centre points appended to the design.

    Returns:
        ``(n, d)`` array of runs in native units.
    """
    _require_box(space, "full factorial")
    d = space.dim
    lv = [levels] * d if isinstance(levels, int) else list(levels)
    if len(lv) != d:
        raise ValueError("levels must be an int or one entry per factor")
    grids = [np.linspace(0.0, 1.0, n) for n in lv]
    U = np.array(list(itertools.product(*grids)), dtype=float)
    if center_points:
        U = np.vstack([U, np.full((center_points, d), 0.5)])
    return space.from_unit(U)


def doe_fractional_factorial(space: ParameterSpace, resolution_fraction: int = 1,
                             center_points: int = 0) -> np.ndarray:
    """Two-level fractional factorial :math:`2^{k-p}` design.

    Generators are selected by an explicit **minimum-aberration search**: every
    admissible assignment of the ``p`` added factors to interactions of the base
    factors is enumerated, the full defining relation is expanded, and the
    design maximizing resolution (then minimizing aberration -- the count of
    shortest defining words) is returned.

    This matters. A tempting heuristic is to alias each added factor with the
    highest-order interaction available; it is wrong. For :math:`2^{6-2}` that
    heuristic yields ``E=ABCD, F=ABC``, whose defining relation contains the
    3-letter word ``DEF`` and is therefore resolution III, while the classical
    ``E=ABC, F=BCD`` is resolution IV. The search below finds the latter.

    Args:
        space: Box parameter space with ``k`` factors.
        resolution_fraction: ``p`` in :math:`2^{k-p}` (1 = half fraction).
        center_points: Replicated centre points appended to the design.

    Returns:
        ``(n, k)`` array of runs in native units.
    """
    _require_box(space, "fractional factorial")
    k = space.dim
    p = int(resolution_fraction)
    if not 0 <= p < k:
        raise ValueError("resolution_fraction must satisfy 0 <= p < n_factors")
    base_k = k - p
    base = np.array(list(itertools.product([-1.0, 1.0], repeat=base_k)), dtype=float)
    cols = [base[:, j] for j in range(base_k)]
    if p:
        for gen in _best_generators(base_k, p):
            cols.append(np.prod(base[:, list(gen)], axis=1))
    D = np.column_stack(cols)
    U = (D + 1.0) / 2.0
    if center_points:
        U = np.vstack([U, np.full((center_points, k), 0.5)])
    return space.from_unit(U)


def fractional_factorial_resolution(base_k: int,
                                    generators: Sequence[Sequence[int]]) -> int:
    """Resolution of a :math:`2^{k-p}` design given its generators.

    The resolution is the length of the shortest word in the defining relation,
    i.e. the minimum over all non-empty subsets of generators of the length of
    their product word.

    Args:
        base_k: Number of base factors.
        generators: For each added factor, the base-factor indices it is
            aliased with.

    Returns:
        The resolution (3 = main effects aliased with 2-factor interactions,
        4 = 2-factor interactions aliased with each other, and so on).
    """
    gens = [frozenset(g) for g in generators]
    p = len(gens)
    if p == 0:
        return base_k + 1
    best = base_k + p + 1
    for r in range(1, p + 1):
        for combo in itertools.combinations(range(p), r):
            sym: set[int] = set()
            for i in combo:
                sym ^= gens[i]
            best = min(best, len(sym) + r)
    return best


def _aberration(base_k: int, generators: Sequence[Sequence[int]]) -> tuple:
    """Word-length count vector, ordered shortest-first, for aberration ranking."""
    gens = [frozenset(g) for g in generators]
    p = len(gens)
    counts: dict[int, int] = {}
    for r in range(1, p + 1):
        for combo in itertools.combinations(range(p), r):
            sym: set[int] = set()
            for i in combo:
                sym ^= gens[i]
            length = len(sym) + r
            counts[length] = counts.get(length, 0) + 1
    max_len = base_k + p
    return tuple(counts.get(i, 0) for i in range(1, max_len + 1))


def _best_generators(base_k: int, p: int,
                     max_combinations: int = 200_000) -> list[tuple]:
    """Search for minimum-aberration generators for a :math:`2^{k-p}` design.

    Candidates are all interactions of at least two base factors. The search is
    exhaustive when the number of combinations is manageable and falls back to a
    randomized search otherwise, so behaviour degrades gracefully for large ``p``
    rather than failing.
    """
    candidates = [c for r in range(2, base_k + 1)
                  for c in itertools.combinations(range(base_k), r)]
    if p > len(candidates):
        raise ValueError(f"cannot build a 2^({base_k + p}-{p}) design: "
                         f"only {len(candidates)} distinct generators exist")

    def score(gens):
        # Higher resolution first, then fewer short words (lower aberration).
        return (fractional_factorial_resolution(base_k, gens),
                tuple(-c for c in _aberration(base_k, gens)))

    from math import comb
    total = comb(len(candidates), p)
    best, best_score = None, None
    if total <= max_combinations:
        for gens in itertools.combinations(candidates, p):
            s = score(gens)
            if best_score is None or s > best_score:
                best, best_score = gens, s
    else:                                   # randomized fallback
        rng = np.random.default_rng(0)
        for _ in range(20_000):
            idx = rng.choice(len(candidates), size=p, replace=False)
            gens = tuple(candidates[i] for i in sorted(idx))
            s = score(gens)
            if best_score is None or s > best_score:
                best, best_score = gens, s
    return list(best)


def doe_plackett_burman(space: ParameterSpace) -> np.ndarray:
    """Plackett-Burman screening design (main effects only, N a multiple of 4).

    Built from cyclic generators for N in {12, 20, 24}; otherwise falls back to
    a resolution-III fractional factorial of matching size.
    """
    _require_box(space, "Plackett-Burman")
    k = space.dim
    N = 4 * int(np.ceil((k + 1) / 4))
    generators = {
        12: "++-+++---+-",
        20: "++--++++-+-+----++-",
        24: "+++++-+-++--++--+-+----",
    }
    if N not in generators:
        p = max(0, k - int(np.ceil(np.log2(N))))
        return doe_fractional_factorial(space, resolution_fraction=p)
    row = np.array([1.0 if c == "+" else -1.0 for c in generators[N]])
    D = np.array([np.roll(row, i) for i in range(N - 1)])
    D = np.vstack([D, -np.ones(N - 1)])
    U = (D[:, :k] + 1.0) / 2.0
    return space.from_unit(U)


# --------------------------------------------------------------------------
# Response-surface designs
# --------------------------------------------------------------------------
def doe_central_composite(space: ParameterSpace, alpha: str | float = "rotatable",
                          center_points: int = 4, face: str = "inscribed") -> np.ndarray:
    """Central composite design (CCD) for quadratic response surfaces.

    The space bounds are treated as hard limits, so the design is always
    returned **inscribed** (CCI): the axial points sit on the bounds and the
    factorial cube is shrunk by ``1/alpha`` inside them. A circumscribed design
    (CCC), whose axial points lie beyond the factorial range, would violate the
    bounds; to get one, widen the bounds to the axial range and use this design.

    Args:
        space: Box parameter space.
        alpha: ``"rotatable"`` (:math:`(2^k)^{1/4}`), ``"orthogonal"``,
            ``"face"`` (= 1, i.e. face-centred) or an explicit float.
        center_points: Number of replicated centre runs.
        face: Only ``"inscribed"`` is supported (see above).
    """
    _require_box(space, "central composite")
    if face != "inscribed":
        raise ValueError("only face='inscribed' is supported: the space bounds "
                         "are hard limits, so axial points cannot lie beyond "
                         "them. Widen the bounds to the axial range instead.")
    k = space.dim
    cube = np.array(list(itertools.product([-1.0, 1.0], repeat=k)), dtype=float)
    if alpha == "rotatable":
        a = (2 ** k) ** 0.25
    elif alpha == "face":
        a = 1.0
    elif alpha == "orthogonal":
        # Orthogonal-blocking alpha: (F * Q / 4) ** (1/4), with
        # Q = (sqrt(F + 2k + n0) - sqrt(F)) ** 2 (Myers & Montgomery).
        nf = 2 ** k
        q = (np.sqrt(nf + 2 * k + center_points) - np.sqrt(nf)) ** 2
        a = float((nf * q / 4.0) ** 0.25)
    else:
        a = float(alpha)
    axial = np.zeros((2 * k, k))
    for j in range(k):
        axial[2 * j, j] = a
        axial[2 * j + 1, j] = -a
    D = np.vstack([cube, axial, np.zeros((center_points, k))])
    U = 0.5 + 0.5 * D / max(a, 1.0)
    return space.from_unit(U)


def doe_box_behnken(space: ParameterSpace, center_points: int = 3) -> np.ndarray:
    """Box-Behnken design -- 3-level, no extreme corner runs (>= 3 factors)."""
    _require_box(space, "Box-Behnken")
    k = space.dim
    if k < 3:
        raise ValueError("Box-Behnken requires at least 3 factors")
    rows = []
    for i, j in itertools.combinations(range(k), 2):
        for a, b in itertools.product([-1.0, 1.0], repeat=2):
            r = np.zeros(k)
            r[i], r[j] = a, b
            rows.append(r)
    D = np.vstack([np.array(rows), np.zeros((center_points, k))])
    return space.from_unit(0.5 + 0.5 * D)


# --------------------------------------------------------------------------
# Space-filling designs
# --------------------------------------------------------------------------
def doe_latin_hypercube(space: ParameterSpace, n: int, seed: Optional[int] = None,
                        criterion: str = "maximin", iterations: int = 200) -> np.ndarray:
    """Latin hypercube design, optionally optimized for the maximin criterion.

    Args:
        space: Box or mixture space (mixture spaces are repaired onto the simplex).
        n: Number of runs.
        seed: RNG seed.
        criterion: ``"maximin"`` (default), ``"corr"`` (minimum correlation) or
            ``"random"``.
        iterations: Number of candidate LHS draws to score.
    """
    rng = np.random.default_rng(seed)
    d = space.dim

    def draw() -> np.ndarray:
        U = np.empty((n, d))
        for j in range(d):
            perm = rng.permutation(n)
            U[:, j] = (perm + rng.random(n)) / n
        return U

    best, best_score = None, -np.inf
    reps = 1 if criterion == "random" else max(1, iterations)
    for _ in range(reps):
        U = draw()
        if criterion == "maximin":
            score = _min_pairwise_distance(U)
        elif criterion == "corr":
            c = np.corrcoef(U, rowvar=False)
            score = -np.max(np.abs(c - np.eye(d)))
        else:
            score = 0.0
        if score > best_score:
            best, best_score = U, score
    X = space.from_unit(best)
    return space.repair(X) if space.mixture else X


def doe_sobol(space: ParameterSpace, n: int, seed: Optional[int] = None,
              scramble: bool = True) -> np.ndarray:
    """Scrambled Sobol' quasi-random sequence (low-discrepancy space filling)."""
    from scipy.stats import qmc
    sampler = qmc.Sobol(d=space.dim, scramble=scramble, seed=seed)
    U = sampler.random(n)
    X = space.from_unit(U)
    return space.repair(X) if space.mixture else X


# --------------------------------------------------------------------------
# Mixture designs
# --------------------------------------------------------------------------
def doe_simplex_lattice(space: ParameterSpace, degree: int = 3,
                        augment_centroid: bool = True) -> np.ndarray:
    """Scheffe simplex-lattice design ``{q, m}`` for mixture spaces.

    Args:
        space: Mixture space with ``q`` components.
        degree: Lattice degree ``m``; component levels are ``0, 1/m, ..., 1``.
        augment_centroid: Append the overall centroid.

    Returns:
        Runs in native units (each row sums to ``space.total``). Points that
        violate component bounds are dropped.
    """
    _require_mixture(space, "simplex lattice")
    q, m = space.dim, int(degree)
    rows = [np.array(c, dtype=float) / m
            for c in _compositions(m, q)]
    X = np.array(rows) * space.total
    if augment_centroid:
        X = np.vstack([X, np.full((1, q), space.total / q)])
    return _filter_bounds(space, X)


def doe_simplex_centroid(space: ParameterSpace, max_blend_size: Optional[int] = None
                         ) -> np.ndarray:
    """Scheffe simplex-centroid design: all equal-proportion blends of subsets."""
    _require_mixture(space, "simplex centroid")
    q = space.dim
    kmax = q if max_blend_size is None else int(max_blend_size)
    rows = []
    for r in range(1, kmax + 1):
        for combo in itertools.combinations(range(q), r):
            row = np.zeros(q)
            row[list(combo)] = space.total / r
            rows.append(row)
    return _filter_bounds(space, np.array(rows))


def doe_extreme_vertices(space: ParameterSpace, include_centroids: bool = True,
                         max_points: int = 400) -> np.ndarray:
    """Extreme-vertices design for a mixture region with component bounds.

    Enumerates the vertices of the bounded simplex (each vertex has all but one
    component at a bound) and optionally adds edge/face centroids plus the
    overall centroid.
    """
    _require_mixture(space, "extreme vertices")
    q = space.dim
    lo, hi = space.bounds
    verts = []
    for free in range(q):
        others = [j for j in range(q) if j != free]
        for pattern in itertools.product([0, 1], repeat=q - 1):
            row = np.zeros(q)
            for j, bit in zip(others, pattern):
                row[j] = hi[j] if bit else lo[j]
            row[free] = space.total - row[others].sum()
            if lo[free] - 1e-9 <= row[free] <= hi[free] + 1e-9:
                verts.append(row)
    if not verts:
        return space.sample(min(max_points, 20), seed=0)
    V = _unique_rows(np.array(verts))
    out = [V]
    if include_centroids and len(V) > 1:
        edges = [(V[i] + V[j]) / 2 for i, j in itertools.combinations(range(len(V)), 2)]
        if edges:
            out.append(_unique_rows(np.array(edges))[: max_points - len(V)])
        out.append(V.mean(axis=0, keepdims=True))
    X = _unique_rows(np.vstack(out))
    return _filter_bounds(space, X)[:max_points]


def doe_mixture_space_filling(space: ParameterSpace, n: int, seed: Optional[int] = None,
                              iterations: int = 60) -> np.ndarray:
    """Maximin space-filling design on a bounded simplex.

    Uses a large feasible candidate pool and greedy maximin selection, which is
    robust for tightly constrained formulation regions where lattice designs
    become infeasible.
    """
    _require_mixture(space, "mixture space filling")
    rng = np.random.default_rng(seed)
    pool = space.sample(max(40 * n, 2000), seed=int(rng.integers(1 << 31)))
    pool = pool[space.is_feasible(pool)]
    if len(pool) <= n:
        return pool
    return _greedy_maximin(pool, n, rng, restarts=max(1, iterations // 20))


# --------------------------------------------------------------------------
# Dispatcher and diagnostics
# --------------------------------------------------------------------------
_DESIGN_DISPATCH = {
    "full_factorial": doe_full_factorial,
    "fractional_factorial": doe_fractional_factorial,
    "plackett_burman": doe_plackett_burman,
    "ccd": doe_central_composite,
    "central_composite": doe_central_composite,
    "box_behnken": doe_box_behnken,
    "lhs": doe_latin_hypercube,
    "latin_hypercube": doe_latin_hypercube,
    "sobol": doe_sobol,
    "simplex_lattice": doe_simplex_lattice,
    "simplex_centroid": doe_simplex_centroid,
    "extreme_vertices": doe_extreme_vertices,
    "mixture_space_filling": doe_mixture_space_filling,
}


def generate_design(space: ParameterSpace, design: str, **kwargs) -> np.ndarray:
    """Generate a design by name.

    Args:
        space: Parameter space.
        design: One of ``full_factorial``, ``fractional_factorial``,
            ``plackett_burman``, ``ccd``, ``box_behnken``, ``lhs``, ``sobol``,
            ``simplex_lattice``, ``simplex_centroid``, ``extreme_vertices``,
            ``mixture_space_filling``.
        **kwargs: Forwarded to the specific generator.
    """
    key = design.lower().strip()
    if key not in _DESIGN_DISPATCH:
        raise ValueError(f"unknown design '{design}'. Options: "
                         f"{sorted(_DESIGN_DISPATCH)}")
    return _DESIGN_DISPATCH[key](space, **kwargs)


def design_diagnostics(space: ParameterSpace, X: np.ndarray) -> dict:
    """Summary quality metrics for a design matrix.

    Returns a dict with the number of runs, minimum pairwise distance
    (maximin), maximum absolute off-diagonal correlation, D-efficiency of a
    first-order model (the Scheffe linear model for mixture spaces), and the
    fraction of feasible runs.
    """
    X = np.atleast_2d(np.asarray(X, dtype=float))
    U = space.to_unit(X)
    n, d = U.shape
    with np.errstate(invalid="ignore"):
        corr = np.corrcoef(U, rowvar=False) if n > 2 else np.eye(d)
    corr = np.nan_to_num(corr, nan=0.0)
    if space.mixture:
        # Scheffe linear mixture model (no intercept): an intercept column is
        # an exact linear combination of the components, so the usual
        # first-order information matrix is singular for every mixture design.
        M = X / space.total
    else:
        M = np.column_stack([np.ones(n), U - 0.5])
    try:
        det = float(np.linalg.det(M.T @ M))
        d_eff = max(det, 0.0) ** (1.0 / M.shape[1]) / n
    except np.linalg.LinAlgError:
        d_eff = float("nan")
    return {
        "n_runs": int(n),
        "n_factors": int(d),
        "min_pairwise_distance": float(_min_pairwise_distance(U)),
        "max_abs_correlation": float(np.max(np.abs(corr - np.eye(d)))) if d > 1 else 0.0,
        "d_efficiency_first_order": d_eff,
        "feasible_fraction": float(np.mean(space.is_feasible(X))),
    }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _require_box(space: ParameterSpace, what: str) -> None:
    if space.mixture:
        raise ValueError(
            f"{what} designs require a box space; this is a mixture space. "
            "Use simplex_lattice, simplex_centroid, extreme_vertices or "
            "mixture_space_filling instead.")


def _require_mixture(space: ParameterSpace, what: str) -> None:
    if not space.mixture:
        raise ValueError(f"{what} designs require a mixture space "
                         "(see make_mixture_space).")


def _compositions(total: int, parts: int):
    """All non-negative integer vectors of length ``parts`` summing to ``total``."""
    if parts == 1:
        yield (total,)
        return
    for first in range(total + 1):
        for rest in _compositions(total - first, parts - 1):
            yield (first,) + rest


def _min_pairwise_distance(U: np.ndarray) -> float:
    if len(U) < 2:
        return float("inf")
    diff = U[:, None, :] - U[None, :, :]
    dist = np.sqrt((diff ** 2).sum(-1))
    np.fill_diagonal(dist, np.inf)
    return float(dist.min())


def _unique_rows(X: np.ndarray, decimals: int = 8) -> np.ndarray:
    _, idx = np.unique(np.round(X, decimals), axis=0, return_index=True)
    return X[np.sort(idx)]


def _filter_bounds(space: ParameterSpace, X: np.ndarray) -> np.ndarray:
    keep = space.is_feasible(X)
    out = X[keep]
    if len(out) == 0:  # bounds exclude the lattice -- repair instead of failing
        out = space.repair(X)
        out = out[space.is_feasible(out)]
    return _unique_rows(out)


def _greedy_maximin(pool: np.ndarray, n: int, rng: np.random.Generator,
                    restarts: int = 3) -> np.ndarray:
    best, best_score = None, -np.inf
    for _ in range(restarts):
        idx = [int(rng.integers(len(pool)))]
        d2 = ((pool - pool[idx[0]]) ** 2).sum(axis=1)
        for _ in range(n - 1):
            nxt = int(np.argmax(d2))
            idx.append(nxt)
            d2 = np.minimum(d2, ((pool - pool[nxt]) ** 2).sum(axis=1))
        sel = pool[idx]
        score = _min_pairwise_distance(sel)
        if score > best_score:
            best, best_score = sel, score
    return best
