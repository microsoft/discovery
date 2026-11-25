"""Extraction logic on synthetic OpenFOAM monitor files (no solver)."""

from __future__ import annotations

from pathlib import Path

from discovery_physics.core.models import Diagnostics
from discovery_physics.openfoam.extract import Metrics, _mass_closure


class _Data:
    def __init__(self, case: Path):
        self.case = case


def _write(case: Path, name: str, start: float, rows: list[tuple[float, float]]) -> None:
    d = case / "postProcessing" / name / repr(start)
    d.mkdir(parents=True, exist_ok=True)
    kind = "volFieldValue" if name == "domain_mass" else "surfaceFieldValue"
    (d / f"{kind}.dat").write_text("# Time value\n" + "".join(f"{t!r} {v!r}\n" for t, v in rows))


def _segment(case: Path, start: float, n: int, m0: float, dt: float, jump: float = 0.0):
    """Exact discrete balance: dM/dt = phi_in_abs - phi_out = 0.1."""
    t = [start + i * dt for i in range(n)]
    mass = [m0 + jump + 0.1 * (ti - start) for ti in t]
    _write(case, "domain_mass", start, list(zip(t, mass)))
    _write(case, "flux_inlet", start, [(ti, -1.0) for ti in t])
    _write(case, "flux_outlet", start, [(ti, 0.9) for ti in t])
    return t[-1], mass[-1]


def _run(tmp_path: Path, jump: float):
    d = Diagnostics(fields=[{"name": "rho", "positive": True}], patches=["inlet", "outlet"], inlet="inlet",
                    outlet="outlet", target_time=1.0, mass_balance=True)
    t1, m1 = _segment(tmp_path, 0.0, 6, 1.0, 0.1)
    _segment(tmp_path, t1, 6, m1, 0.1, jump)
    from discovery_physics.openfoam.extract import _flux_series

    m = Metrics()
    _mass_closure(m, _Data(tmp_path), d, _flux_series(_Data(tmp_path), d.patches))
    return {k: v.value for k, v in m.values.items()}


def test_restart_closure_is_round_off(tmp_path):
    out = _run(tmp_path, 0.0)
    assert out["conservation.mass_closure_max_rel"] < 1e-12
    assert out["conservation.restart_seams_continuous"] is True
    assert out["conservation.restart_segments"] == 2


def test_discontinuous_restart_is_caught_without_differencing_seam(tmp_path):
    out = _run(tmp_path, 1e-3)
    # within-segment residuals stay clean (the paper's pre-fix false alarm cannot occur) ...
    assert out["conservation.mass_closure_max_rel"] < 1e-12
    # ... but the discontinuity itself is detected
    assert out["conservation.restart_seams_continuous"] is False
