"""Grid convergence: Richardson extrapolation and the Grid Convergence Index.

Procedure of Celik et al. (2008), "Procedure for Estimation and Reporting of
Uncertainty Due to Discretization in CFD Applications", J. Fluids Eng. 130(7).
Grids are ordered fine (1) -> coarse (3) by representative cell size h.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass
class GCIResult:
    status: str  # "monotonic", "oscillatory", "divergent", "converged", "invalid"
    order: float | None
    extrapolated: float | None
    rel_error_fine: float | None
    gci_fine_pct: float | None
    gci_coarse_pct: float | None
    asymptotic_ratio: float | None
    convergence_ratio: float | None
    r21: float
    r32: float
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def gci(h: list[float], phi: list[float], safety_factor: float = 1.25) -> GCIResult:
    """Three-grid GCI. ``h`` and ``phi`` in any order; sorted fine -> coarse internally."""
    if len(h) != 3 or len(phi) != 3:
        raise ValueError("GCI needs exactly three grids")
    if any(not math.isfinite(x) for x in (*h, *phi)) or min(h) <= 0:
        raise ValueError("cell sizes must be positive and values finite")
    (h1, f1), (h2, f2), (h3, f3) = sorted(zip(h, phi))
    r21, r32 = h2 / h1, h3 / h2
    base = dict(r21=r21, r32=r32)
    if min(r21, r32) < 1.1:
        return GCIResult("invalid", None, None, None, None, None, None, None,
                         note="refinement ratio below 1.1 (Celik recommends > 1.3)", **base)
    e21, e32 = f2 - f1, f3 - f2
    if e21 == 0 and e32 == 0:
        return GCIResult("converged", None, f1, 0.0, 0.0, 0.0, None, 0.0, note="identical on all grids", **base)
    if e32 == 0:
        return GCIResult("divergent", None, None, None, None, None, None, math.inf,
                         note="coarse pair identical but fine pair differs", **base)
    ratio = e21 / e32
    if ratio < 0:
        return GCIResult("oscillatory", None, None, None, None, None, None, ratio,
                         note="oscillatory convergence: Richardson extrapolation is not applicable", **base)
    if ratio >= 1:
        return GCIResult("divergent", None, None, None, None, None, None, ratio,
                         note="solution changes grow with refinement", **base)
    if e21 == 0:
        return GCIResult("converged", None, f1, 0.0, 0.0, None, None, 0.0,
                         note="fine pair identical; order undefined", **base)
    s = 1.0 if e32 / e21 > 0 else -1.0
    p, q = 1.0, 0.0
    for _ in range(200):
        p_new = abs(math.log(abs(e32 / e21)) + q) / math.log(r21)
        q = math.log((r21 ** p_new - s) / (r32 ** p_new - s))
        if abs(p_new - p) < 1e-12:
            p = p_new
            break
        p = p_new
    ext = (r21 ** p * f1 - f2) / (r21 ** p - 1)
    if f1 == 0:
        return GCIResult("monotonic", p, ext, None, None, None, None, ratio,
                         note="fine value is zero; relative GCI undefined", **base)
    ea21 = abs((f1 - f2) / f1)
    ea32 = abs((f2 - f3) / f2) if f2 else math.inf
    g21 = safety_factor * ea21 / (r21 ** p - 1)
    g32 = safety_factor * ea32 / (r32 ** p - 1)
    asym = g32 / (r21 ** p * g21) if g21 > 0 else None
    return GCIResult("monotonic", p, ext, ea21, 100 * g21, 100 * g32, asym, ratio, **base)
