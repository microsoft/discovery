"""Parameter space definitions for Bayesian optimization and design of experiments.

Supports two families of spaces:

* **Box spaces** -- independent continuous / integer / categorical factors bounded
  by a hyper-rectangle. Used for classical DoE and standard BO.
* **Mixture spaces** -- component fractions constrained to sum to a constant
  (``total``), optionally with per-component lower/upper bounds. This is the
  natural geometry for formulation problems (resins, alloys, blends, media).

All optimizers and designs in this package operate on a :class:`ParameterSpace`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import numpy as np

__all__ = [
    "Parameter",
    "ParameterSpace",
    "make_space",
    "make_mixture_space",
]


@dataclass
class Parameter:
    """A single design factor.

    Args:
        name: Factor name.
        low: Lower bound (continuous / integer factors).
        high: Upper bound (continuous / integer factors).
        kind: ``"continuous"``, ``"integer"`` or ``"categorical"``.
        categories: Allowed values when ``kind == "categorical"``.
        log: If True the factor is modelled on a log10 scale.
    """

    name: str
    low: float = 0.0
    high: float = 1.0
    kind: str = "continuous"
    categories: Optional[Sequence] = None
    log: bool = False

    def __post_init__(self):
        if self.kind not in ("continuous", "integer", "categorical"):
            raise ValueError(f"unknown parameter kind: {self.kind}")
        if self.kind == "categorical":
            if not self.categories:
                raise ValueError(f"categorical parameter '{self.name}' needs categories")
            self.low, self.high = 0.0, float(len(self.categories) - 1)
        elif self.high <= self.low:
            raise ValueError(f"parameter '{self.name}': high must exceed low")
        if self.log and self.low <= 0:
            raise ValueError(f"parameter '{self.name}': log scaling requires low > 0")


@dataclass
class ParameterSpace:
    """A design space over which designs are generated and acquisitions optimized.

    Args:
        parameters: Ordered list of :class:`Parameter`.
        mixture: If True the parameters are mixture components constrained to
            sum to ``total``.
        total: Mixture total (e.g. ``1.0`` for fractions, ``10.0`` for
            parts-of-ten, ``100.0`` for percentages).
    """

    parameters: list[Parameter]
    mixture: bool = False
    total: float = 1.0
    _rng: np.random.Generator = field(default=None, repr=False, compare=False)

    # ---------------------------------------------------------------- basics
    def __len__(self) -> int:
        return len(self.parameters)

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.parameters]

    @property
    def bounds(self) -> np.ndarray:
        """``(2, d)`` array of lower / upper bounds in native units."""
        return np.array([[p.low for p in self.parameters],
                         [p.high for p in self.parameters]], dtype=float)

    @property
    def dim(self) -> int:
        return len(self.parameters)

    def rng(self, seed: Optional[int] = None) -> np.random.Generator:
        if seed is not None:
            return np.random.default_rng(seed)
        if self._rng is None:
            self._rng = np.random.default_rng()
        return self._rng

    # ------------------------------------------------------------- transform
    def to_unit(self, X: np.ndarray) -> np.ndarray:
        """Map native-unit points into the unit cube ``[0, 1]^d``."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        lo, hi = self.bounds
        out = np.empty_like(X)
        for j, p in enumerate(self.parameters):
            if p.log:
                out[:, j] = (np.log10(X[:, j]) - np.log10(p.low)) / (
                    np.log10(p.high) - np.log10(p.low))
            else:
                out[:, j] = (X[:, j] - lo[j]) / (hi[j] - lo[j])
        return np.clip(out, 0.0, 1.0)

    def from_unit(self, U: np.ndarray) -> np.ndarray:
        """Map unit-cube points back to native units (with rounding/snapping)."""
        U = np.atleast_2d(np.asarray(U, dtype=float))
        lo, hi = self.bounds
        out = np.empty_like(U)
        for j, p in enumerate(self.parameters):
            if p.log:
                out[:, j] = 10 ** (np.log10(p.low) + U[:, j] *
                                   (np.log10(p.high) - np.log10(p.low)))
            else:
                out[:, j] = lo[j] + U[:, j] * (hi[j] - lo[j])
            if p.kind in ("integer", "categorical"):
                out[:, j] = np.round(out[:, j])
        return out

    def decode(self, X: np.ndarray) -> list[dict]:
        """Turn a native-unit array into a list of readable parameter dicts."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        rows = []
        for row in X:
            d = {}
            for j, p in enumerate(self.parameters):
                if p.kind == "categorical":
                    d[p.name] = p.categories[int(np.clip(round(row[j]), 0,
                                                         len(p.categories) - 1))]
                elif p.kind == "integer":
                    d[p.name] = int(round(row[j]))
                else:
                    d[p.name] = float(row[j])
            rows.append(d)
        return rows

    # ------------------------------------------------------------ validation
    def is_feasible(self, X: np.ndarray, tol: float = 1e-6) -> np.ndarray:
        """Boolean mask of which rows satisfy bounds (and the mixture sum)."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        lo, hi = self.bounds
        ok = np.all((X >= lo - tol) & (X <= hi + tol), axis=1)
        if self.mixture:
            ok &= np.abs(X.sum(axis=1) - self.total) <= max(tol, 1e-6 * self.total)
        return ok

    def snap(self, X: np.ndarray) -> np.ndarray:
        """Round integer and categorical factors to their allowed values."""
        X = np.atleast_2d(np.asarray(X, dtype=float)).copy()
        lo, hi = self.bounds
        for j, p in enumerate(self.parameters):
            if p.kind in ("integer", "categorical"):
                X[:, j] = np.clip(np.round(X[:, j]), np.ceil(lo[j]), np.floor(hi[j]))
        return X

    def repair(self, X: np.ndarray) -> np.ndarray:
        """Project points into the feasible region.

        For box spaces this clips to the bounds. For mixture spaces it performs
        an iterative clip-and-rescale projection onto the bounded simplex.
        """
        X = np.atleast_2d(np.asarray(X, dtype=float)).copy()
        lo, hi = self.bounds
        X = np.clip(X, lo, hi)
        if not self.mixture:
            return X
        for _ in range(200):
            s = X.sum(axis=1, keepdims=True)
            gap = self.total - s
            if np.all(np.abs(gap) <= 1e-9 * max(self.total, 1.0)):
                break
            # Distribute the deficit/surplus over components with slack.
            room = np.where(gap > 0, hi - X, X - lo)
            room_sum = room.sum(axis=1, keepdims=True)
            room_sum[room_sum == 0] = 1.0
            X = X + gap * room / room_sum
            X = np.clip(X, lo, hi)
        return X

    # -------------------------------------------------------------- sampling
    def sample(self, n: int, seed: Optional[int] = None) -> np.ndarray:
        """Draw ``n`` uniformly distributed feasible points in native units."""
        rng = self.rng(seed)
        if not self.mixture:
            U = rng.random((n, self.dim))
            return self.from_unit(U)
        return self._sample_simplex(n, rng)

    def _sample_simplex(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """Rejection + repair sampling on the bounded simplex."""
        lo, hi = self.bounds
        accepted: list[np.ndarray] = []
        # Direct uniform sampling on the simplex, then keep in-bounds draws.
        for _ in range(64):
            need = n - sum(len(a) for a in accepted)
            if need <= 0:
                break
            draw = rng.dirichlet(np.ones(self.dim), size=max(need * 4, 64)) * self.total
            keep = draw[np.all((draw >= lo - 1e-9) & (draw <= hi + 1e-9), axis=1)]
            if len(keep):
                accepted.append(keep[:need])
        pts = np.vstack(accepted) if accepted else np.empty((0, self.dim))
        if len(pts) < n:  # tight bounds -- fall back to repair projection
            extra = rng.dirichlet(np.ones(self.dim), size=(n - len(pts))) * self.total
            pts = np.vstack([pts, self.repair(extra)]) if len(pts) else self.repair(extra)
        return pts[:n]


# --------------------------------------------------------------------------
# Convenience constructors
# --------------------------------------------------------------------------
def make_space(bounds, names: Optional[Iterable[str]] = None,
               kinds: Optional[Iterable[str]] = None,
               log: Optional[Iterable[bool]] = None) -> ParameterSpace:
    """Build a box-constrained :class:`ParameterSpace`.

    Args:
        bounds: ``(d, 2)`` sequence of ``(low, high)`` pairs, or a dict mapping
            name -> ``(low, high)``.
        names: Factor names (ignored when ``bounds`` is a dict).
        kinds: Per-factor kind strings, default ``"continuous"``.
        log: Per-factor log-scaling flags.

    Returns:
        ParameterSpace: A box space.

    Example:
        >>> space = make_space({"temp": (60, 120), "time": (1, 24)})
        >>> space.sample(3).shape
        (3, 2)
    """
    if isinstance(bounds, dict):
        names = list(bounds.keys())
        pairs = [tuple(v) for v in bounds.values()]
    else:
        pairs = [tuple(b) for b in bounds]
        names = list(names) if names is not None else [f"x{i+1}" for i in range(len(pairs))]
    kinds = list(kinds) if kinds is not None else ["continuous"] * len(pairs)
    log = list(log) if log is not None else [False] * len(pairs)
    params = [Parameter(name=n, low=float(b[0]), high=float(b[1]), kind=k, log=lg)
              for n, b, k, lg in zip(names, pairs, kinds, log)]
    return ParameterSpace(parameters=params, mixture=False)


def make_mixture_space(names: Sequence[str], total: float = 1.0,
                       lower: Optional[Sequence[float]] = None,
                       upper: Optional[Sequence[float]] = None) -> ParameterSpace:
    """Build a mixture space whose components sum to ``total``.

    Args:
        names: Component names, e.g. ``["PUDA", "IBOA", "EHMA", "MAA"]``.
        total: Constant the components must sum to (1.0 fractions, 10.0 parts,
            100.0 percent).
        lower: Optional per-component lower bounds (default 0).
        upper: Optional per-component upper bounds (default ``total``).

    Returns:
        ParameterSpace: A mixture space.

    Example:
        >>> sp = make_mixture_space(["A", "B", "C"], total=10.0)
        >>> np.allclose(sp.sample(5).sum(axis=1), 10.0)
        True
    """
    d = len(names)
    lower = [0.0] * d if lower is None else [float(v) for v in lower]
    upper = [float(total)] * d if upper is None else [float(v) for v in upper]
    if sum(lower) > total + 1e-9:
        raise ValueError("mixture lower bounds sum above the total -- infeasible")
    if sum(upper) < total - 1e-9:
        raise ValueError("mixture upper bounds sum below the total -- infeasible")
    params = [Parameter(name=n, low=lo, high=max(hi, lo + 1e-9))
              for n, lo, hi in zip(names, lower, upper)]
    return ParameterSpace(parameters=params, mixture=True, total=float(total))
