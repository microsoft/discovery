"""Bounded design exploration: space-filling samples and an advisory quadratic surrogate.

The surrogate never decides anything. Its predicted optimum is a suggestion that
must be verified by a new, contract-checked run before any design claim.
"""

from __future__ import annotations

import itertools

import numpy as np


def latin_hypercube(bounds: dict[str, tuple[float, float]], n: int, seed: int = 0) -> list[dict[str, float]]:
    if not 2 <= n <= 64:
        raise ValueError("between 2 and 64 samples")
    if not 1 <= len(bounds) <= 6:
        raise ValueError("between 1 and 6 parameters")
    for k, (lo, hi) in bounds.items():
        if not (np.isfinite(lo) and np.isfinite(hi) and lo < hi):
            raise ValueError(f"invalid bounds for {k}")
    rng = np.random.default_rng(seed)
    names = sorted(bounds)
    pts = []
    cols = {k: (rng.permutation(n) + rng.uniform(size=n)) / n for k in names}
    for i in range(n):
        pts.append({k: float(bounds[k][0] + cols[k][i] * (bounds[k][1] - bounds[k][0])) for k in names})
    return pts


def _features(x: np.ndarray) -> np.ndarray:
    n, d = x.shape
    cols = [np.ones(n), *x.T]
    cols += [x[:, i] * x[:, j] for i, j in itertools.combinations_with_replacement(range(d), 2)]
    return np.column_stack(cols)


def quadratic_surrogate(points: list[dict[str, float]], values: list[float], bounds: dict[str, tuple[float, float]],
                        goal: str = "minimize", grid: int = 41) -> dict:
    names = sorted(bounds)
    lo = np.array([bounds[k][0] for k in names])
    span = np.array([bounds[k][1] - bounds[k][0] for k in names])
    x = (np.array([[p[k] for k in names] for p in points]) - lo) / span
    y = np.asarray(values, dtype=float)
    nfeat = _features(x[:1]).shape[1]
    if len(y) < nfeat + 1:
        return {"ok": False, "reason": f"need at least {nfeat + 1} accepted points for a quadratic in {len(names)} "
                                        "parameters (one more than coefficients, for leave-one-out error)"}
    loo = []
    for i in range(len(y)):
        mask = np.arange(len(y)) != i
        coef, *_ = np.linalg.lstsq(_features(x[mask]), y[mask], rcond=None)
        loo.append(float((_features(x[i:i + 1]) @ coef)[0] - y[i]))
    coef, *_ = np.linalg.lstsq(_features(x), y, rcond=None)
    axes = [np.linspace(0, 1, grid if len(names) <= 2 else 11)] * len(names)
    cand = np.array(list(itertools.product(*axes)))
    pred = _features(cand) @ coef
    i = int(np.argmin(pred) if goal == "minimize" else np.argmax(pred))
    best = {k: float(lo[j] + cand[i, j] * span[j]) for j, k in enumerate(names)}
    rmse = float(np.sqrt(np.mean(np.square(loo))))
    sampled_best = float(np.min(y) if goal == "minimize" else np.max(y))
    return {"ok": True, "advisory": True, "predicted_optimum": best, "predicted_value": float(pred[i]),
            "loo_rmse": rmse, "best_sampled_value": sampled_best,
            "on_boundary": bool(np.any((cand[i] == 0) | (cand[i] == 1))),
            "next_step": "add a study member at predicted_optimum and run it; only that run's checked "
                         "evidence can support a design claim"}
