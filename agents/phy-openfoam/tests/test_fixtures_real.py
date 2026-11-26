"""Extractors against real Foundation-14 text in tests/example-input-files/channel.

The fixture is a 6,000-cell laminar channel run for 3 s (scripts/fixture_probe.py), so the
flow is still developing; physics assertions use tolerances that hold for that state.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from discovery_physics.core.models import Diagnostics
from discovery_physics.openfoam import foamio
from discovery_physics.openfoam.extract import Metrics, _conservation, _quantities

CASE = Path(__file__).parent / "example-input-files" / "channel"
INLET_AREA = 1e-5  # 0.01 m x 0.001 m, recorded in the surfaceFieldValue header


def last(name: str, column: str) -> float:
    t, v, _ = foamio.read_quantity(CASE, name, column)
    assert t[-1] == 3.0
    return float(v[-1])


def test_every_function_object_type_parses():
    expect = {
        "q_p_in": {"areaAverage(p)"},
        "q_u_max": {"max(U).x", "max(U).mag"},
        "q_wall_force": {"forces.total.x", "forces.viscous.x", "forces.pressure.x", "moments.total.z"},
        "q_wall_coeffs": {"Cd", "Cl", "Cm", "Cl(f)", "Cl(r)"},
        "q_yplus": {"walls/average", "walls/min", "walls/max"},
        "q_probe_mid": {"0"},
    }
    for name, cols in expect.items():
        _, _, available = foamio.read_quantity(CASE, name, next(iter(cols)))
        assert cols <= set(available), (name, available)


def test_total_force_is_sum_of_parts():
    assert math.isclose(last("q_wall_force", "forces.total.x"),
                        last("q_wall_force", "forces.pressure.x") + last("q_wall_force", "forces.viscous.x"),
                        rel_tol=1e-12)


def test_momentum_balance_wall_shear_vs_pressure_drop():
    # Steady channel: wall shear force = (p_in - p_out) * A. At t = 3 s the flow is still
    # developing, so allow 5 %; a wrong column, sign, or component would be off by orders.
    drop_force = last("q_p_in", "areaAverage(p)") * INLET_AREA
    shear = last("q_wall_force", "forces.viscous.x")
    assert shear > 0 and abs(shear / drop_force - 1) < 0.05


def test_drag_coefficient_matches_force_definition():
    # Cd = F_x / (0.5 rho U^2 A_ref) with rhoInf 1, magUInf 0.01, Aref 5e-4 (fixture settings).
    cd = last("q_wall_coeffs", "Cd")
    fx = last("q_wall_force", "forces.total.x")
    assert math.isclose(cd, fx / (0.5 * 1.0 * 0.01 ** 2 * 5e-4), rel_tol=1e-9)


def test_yplus_and_vector_magnitude_are_consistent():
    lo, avg, hi = (last("q_yplus", f"walls/{k}") for k in ("min", "average", "max"))
    assert 0 < lo <= avg <= hi < 5  # laminar, well-resolved wall
    ux, uy, uz, mag = (last("q_u_max", f"max(U).{k}") for k in ("x", "y", "z", "mag"))
    assert math.isclose(mag, math.sqrt(ux * ux + uy * uy + uz * uz), rel_tol=1e-12)
    assert 0.01 < ux < 0.02  # centreline exceeds the 0.01 m/s bulk velocity, below 2x (parabolic limit 1.5x)


def test_quantity_extractor_reports_value_or_missing():
    d = Diagnostics.model_validate({
        "fields": [{"name": "p"}], "target_time": 3.0, "patches": ["inlet", "outlet", "walls"],
        "quantities": [
            {"name": "wall_force", "function": "forces", "column": "forces.total.x", "unit": "N"},
            {"name": "yplus", "function": "yPlus", "column": "walls/average"},
            {"name": "probe_mid", "function": "probes", "column": "0", "unit": "m^2/s^2"},
        ]})
    m = Metrics()

    class Data:
        case = CASE

    _quantities(m, Data(), d)
    assert m.values["quantity.wall_force"].status == "measured"
    assert m.values["quantity.wall_force"].unit == "N"
    assert m.values["quantity.yplus"].value == pytest.approx(last("q_yplus", "walls/average"))
    assert m.values["quantity.probe_mid"].value == pytest.approx(last("q_probe_mid", "0"))
    # Wrong column on real output -> missing, and the error lists the real columns.
    m = Metrics()
    bad = d.model_copy(update={"quantities": [d.quantities[0].model_copy(update={"column": "total_x"})]})
    _quantities(m, Data(), bad)
    assert m.values["quantity.wall_force"].status == "missing"
    assert any("total_x" in e and "forces.total.x" in e for e in m.errors)
    # Function object that produced no output -> missing.
    m = Metrics()
    d2 = Diagnostics.model_validate({"fields": [{"name": "p"}], "target_time": 3.0, "quantities": [
        {"name": "absent", "function": "forces", "column": "forces.total.x"}]})
    _quantities(m, Data(), d2)
    assert m.values["quantity.absent"].status == "missing" and any("no output" in e for e in m.errors)


@pytest.mark.parametrize("text", ["0 (1 2", "0 1 2)"])
def test_malformed_rows_are_refused(tmp_path, text):
    f = tmp_path / "x.dat"
    f.write_text("# Time a\n" + text + "\n")
    with pytest.raises(foamio.FoamFormatError):
        foamio.read_quantity_table(f)


def test_declared_empty_patch_does_not_break_flux_balance():
    """Held-out H01 regression: a declared 2-D `empty` patch has no flux monitor output."""
    import json

    case = Path(__file__).parent / "example-input-files" / "channel2d_empty"
    d = Diagnostics.model_validate(json.loads((case / "diagnostics.json").read_text(encoding="utf-8")))
    assert "frontAndBack" in d.patches

    class Data:
        pass

    data = Data()
    data.case = case
    data.boundary = foamio.read_boundary(case / "constant" / "polyMesh")
    m = Metrics()
    _conservation(m, data, d)
    assert m.values["conservation.final_net_flux_rel"].value < 1e-10
    assert m.values["stationarity.flux_mismatch_max"].status == "measured"
    # A declared patch that is not in the mesh is still refused.
    bad = d.model_copy(update={"patches": [*d.patches, "ghost"]})
    with pytest.raises(ValueError, match="absent from the mesh"):
        _conservation(Metrics(), data, bad)
