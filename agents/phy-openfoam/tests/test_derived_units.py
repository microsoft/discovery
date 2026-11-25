"""Derived-output registration and evidence arithmetic enforce units before use."""

from __future__ import annotations

import copy

import pytest

from discovery_physics.benchmarks.cases import forward_step_bundle
from discovery_physics.core.derived import compute
from discovery_physics.core.models import Derived, Diagnostics, Metric
from discovery_physics.openfoam import runner
from discovery_physics.openfoam.catalog import known_metrics

from test_core import TUT


def derived(**changes):
    return Derived.model_validate({"name": "result", "op": "difference", "a": "quantity.a",
                                   "b": "quantity.b", "unit": "Pa", **changes})


@pytest.mark.parametrize("op,unit,extra", [
    ("difference", "Pa", {}), ("ratio", "1", {}), ("scale", "K", {}),
    ("abs_rel_error_pct", "%", {"reference": 300.0, "reference_unit": "K"}),
])
def test_incompatible_arithmetic_never_becomes_measured(op, unit, extra):
    d = derived(op=op, unit=unit, **extra)
    metrics = {"quantity.a": Metric(value=10.0, unit="Pa", source="synthetic pressure"),
               "quantity.b": Metric(value=300.0, unit="K", source="synthetic temperature")}
    result = compute([d], metrics)["derived.result"]
    assert result.status == "invalid" and result.value is None
    assert "unit validation" in result.source


@pytest.mark.parametrize("bad_unit", ["K", "kPa", "", " ", "degC"])
def test_freeze_and_catalog_refuse_false_difference_unit(bad_unit):
    bundle = forward_step_bundle(TUT)
    bundle["diagnostics"]["quantities"] = [{"name": name, "function": "probes", "settings": {"fields": "(p)", "probeLocations": "((0 0 0))"},
                                            "column": "p.0", "unit": unit}
                                           for name, unit in (("a", "Pa"), ("b", bad_unit))]
    bundle["diagnostics"]["derived"] = [derived().model_dump(mode="json")]
    parsed = Diagnostics.model_validate(bundle["diagnostics"])
    assert "derived.result" not in known_metrics(parsed)
    with pytest.raises(ValueError, match="unit"):
        runner.freeze(bundle)


@pytest.mark.parametrize("a_unit,factor_unit,out_unit,value,factor,expected", [
    ("m2/s2", "kg/m3", "Pa", 2.0, 998.2, 1996.4),
    ("m^2/s^2", "kg/m^3", "Pa", 2.0, 1.2, 2.4),
    ("N", "1/m", "N/m", 0.02, 1000.0, 20.0),
    ("1", "N/m", "N/m", 2.0, 0.0015, 0.003),
    ("Pa", "kPa/Pa", "kPa", 2000.0, 0.001, 2.0),
    ("opaque", "1", "opaque", 4.0, 2.0, 8.0),
])
def test_explicit_dimensional_scaling(a_unit, factor_unit, out_unit, value, factor, expected):
    d = derived(op="scale", b=None, factor=factor, factor_unit=factor_unit, unit=out_unit)
    result = compute([d], {"quantity.a": Metric(value=value, unit=a_unit, source="synthetic")})["derived.result"]
    assert result.status == "measured" and result.value == pytest.approx(expected)


def test_dimensional_scale_cannot_infer_factor_units_from_output_label():
    d = derived(op="scale", b=None, factor=998.2, unit="Pa")
    result = compute([d], {"quantity.a": Metric(value=2.0, unit="m2/s2", source="synthetic")})["derived.result"]
    assert result.status == "invalid"


@pytest.mark.parametrize("a_unit,b_unit,out_unit,expected", [
    ("N", "m2", "Pa", 3.0), ("Pa", "Pa", "1", 3.0),
    ("opaque", "opaque", "1", 3.0), ("m", "s", "m/s", 3.0),
])
def test_ratio_dimensions_are_preserved(a_unit, b_unit, out_unit, expected):
    d = derived(op="ratio", unit=out_unit)
    m = {"quantity.a": Metric(value=6.0, unit=a_unit, source="synthetic"),
         "quantity.b": Metric(value=2.0, unit=b_unit, source="synthetic")}
    assert compute([d], m)["derived.result"].value == expected


def test_reference_numeric_value_is_bound_to_operand_unit_unless_explicit():
    m = {"quantity.a": Metric(value=3.0, unit="Pa", source="synthetic")}
    good = derived(op="abs_rel_error_pct", b=None, reference=2.5, unit="%")
    assert compute([good], m)["derived.result"].value == pytest.approx(20.0)
    bad = good.model_copy(update={"reference_unit": "kPa"})
    assert compute([bad], m)["derived.result"].status == "invalid"


def test_invalid_derived_chain_cannot_restore_validity_by_relabeling():
    records = [derived(), derived(name="second", op="scale", a="derived.result", b=None, unit="Pa")]
    m = {"quantity.a": Metric(value=10.0, unit="Pa", source="synthetic"),
         "quantity.b": Metric(value=300.0, unit="K", source="synthetic")}
    original = copy.deepcopy(m)
    result = compute(records, m)
    assert all(value.status != "measured" for value in result.values())
    assert m == original


def test_evidence_units_are_rechecked_even_after_valid_declaration():
    d = derived()
    assert compute([d], {"quantity.a": Metric(value=2.0, unit="Pa", source="a"),
                         "quantity.b": Metric(value=1.0, unit="Pa", source="b")})["derived.result"].value == 1.0
    assert compute([d], {"quantity.a": Metric(value=2.0, unit="Pa", source="a"),
                         "quantity.b": Metric(value=1.0, unit="kPa", source="b")})["derived.result"].status == "invalid"


@pytest.mark.parametrize("label", ["Pa/", "Pa//s", "degC*1", "degC/s", "Pa**2", "m^100", "m/(s)"])
def test_malformed_or_offset_units_cannot_be_smuggled_as_matching_opaque_labels(label):
    d = derived(op="scale", b=None, unit=label)
    out = compute([d], {"quantity.a": Metric(value=2.0, unit=label, source="synthetic")})
    assert out["derived.result"].status == "invalid"