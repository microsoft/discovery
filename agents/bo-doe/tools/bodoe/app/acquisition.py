"""Acquisition functions for single- and multi-objective Bayesian optimization.

Conventions
-----------
All acquisitions are written for **maximization of the acquisition value**, and
the underlying objectives are internally converted to a *minimization* problem
(``minimize=True`` objectives are used as-is, ``maximize`` objectives are
negated by the optimizer before reaching this module).

Single objective
    ``ei`` (expected improvement), ``logei`` (numerically stable log-EI),
    ``pi`` (probability of improvement), ``ucb`` (lower confidence bound for
    minimization), ``poi_thresh`` (probability of beating a target).

Multi objective
    ``parego`` (augmented-Chebyshev random scalarization; works with any
    backend) and ``ehvi`` (expected hypervolume improvement, exact increment
    for 2 objectives, Monte-Carlo otherwise). ``qnehvi``/``qehvi`` are accepted
    as aliases of this package's ``ehvi``; for BoTorch's own qLogNEHVI call
    BoTorch directly. Multi-objective names are only valid through
    :class:`optimize.BayesianOptimizer`.

Batches are built by the optimizer, which penalizes candidates near earlier
picks of the same batch.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

import numpy as np
from scipy.stats import norm

__all__ = [
    "expected_improvement",
    "log_expected_improvement",
    "probability_of_improvement",
    "lower_confidence_bound",
    "probability_below_threshold",
    "acquisition",
    "rank_normalize",
    "ACQUISITIONS",
    "pareto_mask",
    "pareto_front",
    "hypervolume",
    "hypervolume_improvement",
    "expected_hypervolume_improvement",
    "chebyshev_scalarization",
    "random_weights",
]

_EPS = 1e-12


# --------------------------------------------------------------------------
# Composition primitive
# --------------------------------------------------------------------------
def rank_normalize(scores: np.ndarray) -> np.ndarray:
    """Map arbitrary acquisition values onto ``(0, 1]`` by rank.

    This is the composition primitive used throughout the optimizer.
    Acquisitions live on wildly different scales -- log-EI is negative, EI is a
    tiny positive number, UCB is in objective units -- so combining them with
    feasibility probabilities or diversity penalties by multiplication is
    **unsafe**: multiplying a negative score by a factor in ``(0, 1)`` makes it
    larger, silently inverting the ranking. That defect really did collapse
    every suggested batch onto a single point during development.

    Rank-normalizing first makes composition safe for *any* acquisition, present
    or future, because the result is strictly positive and the transform is
    monotone: scaling by a constant can never reorder candidates.

    Ties receive their average rank; non-finite values rank last.

    Args:
        scores: ``(n,)`` acquisition values, larger meaning better.

    Returns:
        ``(n,)`` values in ``(0, 1]``, order-preserving with respect to input.
    """
    s = np.asarray(scores, dtype=float).ravel()
    n = len(s)
    if n == 0:
        return s
    clean = np.where(np.isfinite(s), s, -np.inf)
    order = np.argsort(clean, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    uniq, inv = np.unique(clean, return_inverse=True)
    if len(uniq) < n:                      # average ranks within tied groups
        sums = np.bincount(inv, weights=ranks)
        counts = np.bincount(inv)
        ranks = (sums / counts)[inv]
    return ranks / n


#: Registry of every single-objective acquisition.
#:
#: ``needs_best``  -- an incumbent value is required.
#: ``stochastic``  -- must be given an explicit RNG to stay reproducible.
#: ``scale``       -- how the value composes with probability factors:
#:                    ``"nonneg"``  already a non-negative utility;
#:                    ``"log"``     a log-utility (exponentiate to compose);
#:                    ``"unbounded"`` arbitrary sign/units (rank-normalize).
ACQUISITIONS = {
    "ei": {"needs_best": True, "stochastic": False, "scale": "nonneg"},
    "logei": {"needs_best": True, "stochastic": False, "scale": "log"},
    "pi": {"needs_best": True, "stochastic": False, "scale": "nonneg"},
    "ucb": {"needs_best": False, "stochastic": False, "scale": "unbounded"},
    "thompson": {"needs_best": False, "stochastic": True, "scale": "unbounded"},
    "poi_thresh": {"needs_best": False, "stochastic": False, "scale": "nonneg"},
    "mean": {"needs_best": False, "stochastic": False, "scale": "unbounded"},
    "std": {"needs_best": False, "stochastic": False, "scale": "nonneg"},
    # Multi-objective acquisitions share the registry so composition is uniform.
    "parego": {"needs_best": False, "stochastic": True, "scale": "log"},
    "ehvi": {"needs_best": False, "stochastic": True, "scale": "log"},
}

#: Aliases accepted from users, mapped to canonical registry keys.
_ALIASES = {
    "expected_improvement": "ei", "log_ei": "logei",
    "probability_of_improvement": "pi", "lcb": "ucb",
    "confidence_bound": "ucb", "ts": "thompson",
    "feasibility": "poi_thresh", "greedy": "mean",
    "explore": "std", "uncertainty": "std",
    "qehvi": "ehvi", "qnehvi": "ehvi", "qparego": "parego",
}


def to_utility(values: np.ndarray, scale: str) -> np.ndarray:
    """Convert raw acquisition values into a composable non-negative utility.

    Probability factors (feasibility, success, batch diversity) may only be
    multiplied into a **non-negative** quantity. Multiplying them into a raw
    score that can be negative -- as log-EI almost always is -- inverts the
    ranking, because scaling a negative number by a factor in ``(0, 1)`` makes
    it larger. That defect collapsed every suggested batch onto one point during
    development, so composition now always goes through this function.

    Args:
        values: Raw acquisition values, larger meaning better.
        scale: ``"nonneg"``, ``"log"`` or ``"unbounded"`` (see
            :data:`ACQUISITIONS`).

    Returns:
        Non-negative utilities, order-preserving with respect to ``values``.

        * ``"nonneg"``   -- clipped at zero; magnitude preserved exactly.
        * ``"log"``      -- ``exp(v - max(v))``; **magnitude preserved** in the
          sense that ratios of utilities equal ratios of the underlying
          quantity. This matters: rank-normalizing log-EI would flatten a
          :math:`10^{300}` difference in expected improvement into a difference
          of a few rank steps, letting a modest feasibility penalty overturn it.
        * ``"unbounded"`` -- rank-normalized into ``(0, 1]``, the only safe
          option when the values carry no natural zero.
    """
    v = np.asarray(values, dtype=float)
    if scale == "nonneg":
        return np.clip(np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0), 0.0, None)
    if scale == "log":
        finite = v[np.isfinite(v)]
        if len(finite) == 0:
            return np.zeros_like(v)
        return np.exp(np.clip(v - finite.max(), -700.0, 0.0)) * np.isfinite(v)
    if scale == "unbounded":
        return rank_normalize(v)
    raise ValueError(f"unknown acquisition scale '{scale}'")


def canonical_acquisition(name: str) -> str:
    """Resolve an acquisition alias to its canonical key, or raise."""
    key = str(name).lower().strip()
    key = _ALIASES.get(key, key)
    if key not in ACQUISITIONS:
        raise ValueError(f"unknown acquisition '{name}'. "
                         f"Options: {sorted(ACQUISITIONS)}")
    return key


# --------------------------------------------------------------------------
# Single-objective acquisitions (minimization of the objective)
# --------------------------------------------------------------------------
def expected_improvement(mu: np.ndarray, sd: np.ndarray, best: float,
                         xi: float = 0.01) -> np.ndarray:
    """Expected improvement below the incumbent ``best`` (minimization).

    Args:
        mu: Posterior means.
        sd: Posterior standard deviations.
        best: Best (lowest) observed objective value.
        xi: Exploration margin added to the incumbent.
    """
    sd = np.maximum(np.asarray(sd, dtype=float), _EPS)
    imp = (best - xi) - np.asarray(mu, dtype=float)
    z = imp / sd
    return imp * norm.cdf(z) + sd * norm.pdf(z)


def log_expected_improvement(mu: np.ndarray, sd: np.ndarray, best: float,
                             xi: float = 0.01) -> np.ndarray:
    """Log of expected improvement -- avoids vanishing gradients late in a run."""
    return np.log(np.maximum(expected_improvement(mu, sd, best, xi), 1e-300))


def probability_of_improvement(mu: np.ndarray, sd: np.ndarray, best: float,
                               xi: float = 0.01) -> np.ndarray:
    """Probability the objective falls below ``best - xi`` (minimization)."""
    sd = np.maximum(np.asarray(sd, dtype=float), _EPS)
    return norm.cdf(((best - xi) - np.asarray(mu, dtype=float)) / sd)


def lower_confidence_bound(mu: np.ndarray, sd: np.ndarray, beta: float = 2.0
                           ) -> np.ndarray:
    """Negated LCB so that larger is better (minimization of the objective)."""
    return -(np.asarray(mu, dtype=float) - beta * np.asarray(sd, dtype=float))


def probability_below_threshold(mu: np.ndarray, sd: np.ndarray, threshold: float
                                ) -> np.ndarray:
    """Probability the objective is below a hard specification threshold."""
    sd = np.maximum(np.asarray(sd, dtype=float), _EPS)
    return norm.cdf((threshold - np.asarray(mu, dtype=float)) / sd)


def acquisition(name: str, mu: np.ndarray, sd: np.ndarray,
                best: Optional[float] = None, beta: float = 2.0,
                xi: float = 0.01, threshold: Optional[float] = None,
                rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """Dispatch a single-objective acquisition by name (larger is better).

    Args:
        name: Acquisition name or alias (see :data:`ACQUISITIONS`).
        mu: Posterior means in the internal minimization orientation.
        sd: Posterior standard deviations.
        best: Incumbent (lowest observed) value; required by EI/logEI/PI.
        beta: UCB exploration coefficient.
        xi: EI/PI exploration margin.
        threshold: Specification limit for ``poi_thresh``.
        rng: Generator for stochastic acquisitions (Thompson). Passing an
            explicit generator keeps a single ``ask()`` reproducible.
    """
    key = canonical_acquisition(name)
    if ACQUISITIONS[key]["needs_best"] and best is None:
        raise ValueError(f"acquisition '{key}' requires an incumbent 'best' value")
    if key == "ei":
        return expected_improvement(mu, sd, best, xi)
    if key == "logei":
        return log_expected_improvement(mu, sd, best, xi)
    if key == "pi":
        return probability_of_improvement(mu, sd, best, xi)
    if key == "ucb":
        return lower_confidence_bound(mu, sd, beta)
    if key == "thompson":
        gen = rng if rng is not None else np.random.default_rng()
        return -(np.asarray(mu) + np.asarray(sd) * gen.standard_normal(len(mu)))
    if key == "poi_thresh":
        if threshold is None:
            raise ValueError("poi_thresh acquisition requires a threshold")
        return probability_below_threshold(mu, sd, threshold)
    if key == "mean":
        return -np.asarray(mu, dtype=float)
    if key == "std":
        return np.asarray(sd, dtype=float)
    raise ValueError(f"'{key}' is a multi-objective acquisition; use it through "
                     "BayesianOptimizer with two or more objectives")


# --------------------------------------------------------------------------
# Multi-objective utilities (all objectives minimized)
# --------------------------------------------------------------------------
def pareto_mask(Y: np.ndarray) -> np.ndarray:
    """Boolean mask of non-dominated rows of ``Y`` (all objectives minimized)."""
    Y = np.atleast_2d(np.asarray(Y, dtype=float))
    n = len(Y)
    mask = np.ones(n, dtype=bool)
    for i in range(n):
        if not mask[i]:
            continue
        dominated = np.all(Y <= Y[i], axis=1) & np.any(Y < Y[i], axis=1)
        if np.any(dominated):
            mask[i] = False
    return mask


def pareto_front(Y: np.ndarray, X: Optional[np.ndarray] = None):
    """Return the non-dominated objective rows (and matching inputs, if given)."""
    m = pareto_mask(Y)
    Yp = np.atleast_2d(np.asarray(Y, dtype=float))[m]
    order = np.argsort(Yp[:, 0])
    if X is None:
        return Yp[order]
    Xp = np.atleast_2d(np.asarray(X, dtype=float))[m][order]
    return Yp[order], Xp


def hypervolume(Y: np.ndarray, ref_point: Sequence[float],
                mc_samples: int = 200_000, seed: Optional[int] = 0) -> float:
    """Dominated hypervolume w.r.t. ``ref_point`` (all objectives minimized).

    Exact for 1 and 2 objectives via a sweep; Monte-Carlo estimated for 3+.
    """
    Y = np.atleast_2d(np.asarray(Y, dtype=float))
    ref = np.asarray(ref_point, dtype=float)
    Y = Y[np.all(Y <= ref, axis=1)]
    if len(Y) == 0:
        return 0.0
    Y = pareto_front(Y)
    m = Y.shape[1]
    if m == 1:
        return float(ref[0] - Y[:, 0].min())
    if m == 2:
        order = np.argsort(Y[:, 0])
        Ys = Y[order]
        hv, prev_y = 0.0, ref[1]
        for x, y in Ys:
            if y < prev_y:
                hv += (ref[0] - x) * (prev_y - y)
                prev_y = y
        return float(hv)
    rng = np.random.default_rng(seed)
    lo = Y.min(axis=0)
    box = np.prod(ref - lo)
    if box <= 0:
        return 0.0
    pts = rng.uniform(lo, ref, size=(mc_samples, m))
    dominated = np.any(np.all(pts[:, None, :] >= Y[None, :, :], axis=2), axis=1)
    return float(box * dominated.mean())


def hypervolume_improvement(Y_ref: np.ndarray, y_new: np.ndarray,
                            ref_point: Sequence[float]) -> float:
    """Hypervolume gained by adding ``y_new`` to the set ``Y_ref``."""
    base = hypervolume(Y_ref, ref_point)
    aug = hypervolume(np.vstack([np.atleast_2d(Y_ref), np.atleast_2d(y_new)]), ref_point)
    return float(max(aug - base, 0.0))


def _ehvi_2d(mus: np.ndarray, sds: np.ndarray, front: np.ndarray,
             ref: np.ndarray, mc_samples: int,
             rng: np.random.Generator) -> np.ndarray:
    """Fully vectorized exact-increment EHVI for two minimized objectives.

    For a bi-objective problem the hypervolume improvement contributed by a
    single new point ``y`` has a closed form. Sort the front by the first
    objective and build the staircase of cells that the front does *not*
    dominate; the improvement is the total area of the parts of those cells that
    ``y`` dominates:

    .. math::

        \\mathrm{HVI}(y) = \\sum_c \\max(0, x^{hi}_c - \\max(y_1, x^{lo}_c))
                                 \\cdot \\max(0, z^{hi}_c - \\max(y_2, z^{lo}_c))

    Evaluating this over all candidates and all posterior samples at once turns
    what was an O(candidates x samples) loop of full hypervolume computations
    into two array operations. The previous implementation called
    :func:`hypervolume` once per posterior sample per candidate, which made
    EHVI unusable at realistic candidate-pool sizes.

    Common random numbers (one shared block of standard normals) keep the
    estimate a pointwise function of each candidate and reduce comparison
    variance.
    """
    order = np.argsort(front[:, 0])
    F = front[order]
    # Staircase cells of the region dominated by the front but not yet counted.
    xs = np.concatenate([[-np.inf], F[:, 0]])
    x_hi = np.concatenate([F[:, 0], [ref[0]]])
    y_bound = np.concatenate([[ref[1]], np.minimum.accumulate(F[:, 1])])
    keep = (x_hi > xs) & (y_bound > -np.inf)
    x_lo, x_hi, y_hi = xs[keep], x_hi[keep], y_bound[keep]
    x_lo = np.where(np.isfinite(x_lo), x_lo, -1e300)

    Z = rng.standard_normal((mc_samples, 2))
    out = np.empty(len(mus))
    for i in range(len(mus)):
        s = np.minimum(mus[i] + sds[i] * Z, ref)          # (mc, 2)
        w = np.clip(x_hi[None, :] - np.maximum(s[:, 0:1], x_lo[None, :]), 0, None)
        h = np.clip(y_hi[None, :] - s[:, 1:2], 0, None)
        out[i] = float((w * h).sum(axis=1).mean())
    return out


def expected_hypervolume_improvement(mus: np.ndarray, sds: np.ndarray,
                                     Y_obs: np.ndarray, ref_point: Sequence[float],
                                     mc_samples: int = 64,
                                     seed: Optional[int] = 0,
                                     hv_mc_samples: int = 8192) -> np.ndarray:
    """Monte-Carlo expected hypervolume improvement for candidate points.

    Two regimes:

    * **2 objectives** -- the hypervolume is exact and cheap, so EHVI is the
      average exact improvement over posterior samples.
    * **3+ objectives** -- a single *shared* Monte-Carlo grid over the region
      between the front's ideal point and ``ref_point`` is drawn once. Points
      already dominated by the front are removed, and each posterior sample only
      has to count how many of the *remaining* points it dominates. This turns
      an O(candidates x samples x grid x front) computation into a vectorized
      one and makes EHVI usable beyond two objectives.

    Args:
        mus: ``(n_cand, n_obj)`` posterior means (minimization orientation).
        sds: ``(n_cand, n_obj)`` posterior standard deviations.
        Y_obs: ``(n_obs, n_obj)`` observed objectives.
        ref_point: Reference point dominated by all objectives of interest.
        mc_samples: Posterior samples per candidate.
        seed: RNG seed.
        hv_mc_samples: Size of the shared MC grid used when ``n_obj >= 3``.

    Returns:
        ``(n_cand,)`` array of EHVI estimates (larger is better).
    """
    rng = np.random.default_rng(seed)
    mus = np.atleast_2d(np.asarray(mus, dtype=float))
    sds = np.atleast_2d(np.asarray(sds, dtype=float))
    ref = np.asarray(ref_point, dtype=float)
    front = pareto_front(Y_obs)
    n_obj = mus.shape[1]

    if n_obj <= 2:
        return _ehvi_2d(mus, sds, front, ref, mc_samples, rng)

    # --- shared-grid estimator for 3+ objectives -------------------------
    # The integration region is derived from the observed front and the
    # reference point ONLY -- never from the candidate batch. If the grid
    # depended on the candidates, EHVI would stop being a pointwise function of
    # x: the same candidate would score differently depending on what it was
    # evaluated alongside, and any local refinement of it would be meaningless.
    lo = np.minimum(front.min(axis=0), ref)
    span = ref - lo                     # >= 0; zero when no front point beats ref
    volume = float(np.prod(span))
    grid = rng.uniform(lo, ref, size=(hv_mc_samples, n_obj))
    dominated = np.any(np.all(grid[:, None, :] >= front[None, :, :], axis=2), axis=1)
    free = grid[~dominated]
    cell = volume / hv_mc_samples
    Z = rng.standard_normal((mc_samples, n_obj))   # common random numbers
    out = np.zeros(len(mus))
    for i in range(len(mus)):
        draws = np.minimum(mus[i] + sds[i] * Z, ref)   # beyond ref counts for 0
        # The part of a draw's box [s, ref] lying outside [lo, ref] (some
        # coordinate below the front's ideal point) cannot be dominated by the
        # front, so it is all improvement and has a closed form. The grid only
        # has to estimate the part inside [lo, ref].
        outside = (np.prod(ref - draws, axis=1)
                   - np.prod(ref - np.maximum(draws, lo), axis=1))
        inside = (np.all(free[None, :, :] >= draws[:, None, :], axis=2).sum(axis=1)
                  * cell if len(free) else 0.0)
        out[i] = float(np.mean(outside + inside))
    return out


def chebyshev_scalarization(Y: np.ndarray, weights: np.ndarray, rho: float = 0.05,
                            y_min: Optional[np.ndarray] = None,
                            y_max: Optional[np.ndarray] = None) -> np.ndarray:
    """Augmented Chebyshev scalarization used by ParEGO (minimization).

    Objectives are min-max normalized before scalarization so that weights are
    scale free.
    """
    Y = np.atleast_2d(np.asarray(Y, dtype=float))
    y_min = Y.min(axis=0) if y_min is None else np.asarray(y_min, dtype=float)
    y_max = Y.max(axis=0) if y_max is None else np.asarray(y_max, dtype=float)
    rng_ = np.where(y_max - y_min > _EPS, y_max - y_min, 1.0)
    Z = (Y - y_min) / rng_
    w = np.asarray(weights, dtype=float)
    wz = w * Z
    return wz.max(axis=1) + rho * wz.sum(axis=1)


def random_weights(n_obj: int, rng: np.random.Generator) -> np.ndarray:
    """Draw a random simplex weight vector for ParEGO scalarization."""
    w = rng.dirichlet(np.ones(n_obj))
    return w


def batch_via_liar(select_one: Callable[[np.ndarray, np.ndarray], int],
                   candidates: np.ndarray, mu: np.ndarray, sd: np.ndarray,
                   batch_size: int, penalty_radius: float = 0.05) -> list[int]:
    """Greedy batch selection with local-penalization (constant-liar variant).

    After each pick the acquisition is suppressed within ``penalty_radius`` of
    the selected candidate, which prevents a batch from collapsing onto a single
    mode without refitting the GP.
    """
    chosen: list[int] = []
    active = np.ones(len(candidates), dtype=bool)
    for _ in range(batch_size):
        idx_pool = np.flatnonzero(active)
        if len(idx_pool) == 0:
            break
        local = select_one(mu[idx_pool], sd[idx_pool])
        pick = int(idx_pool[local])
        chosen.append(pick)
        d = np.linalg.norm(candidates - candidates[pick], axis=1)
        active &= d > penalty_radius
        active[pick] = False
    return chosen
