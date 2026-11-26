"""Cross-run units bind before staging and fail closed at assessment; no CFD."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from discovery_physics.benchmarks.cases import forward_step_bundle
from discovery_physics.core.models import Metric, Verdict
from discovery_physics.openfoam import runner, study

from test_core import TUT
from test_safeguards import _fake_execute


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("DISCOVERY_PHYSICS_KEY_FILE", str(tmp_path / "keys/journal.key"))
    monkeypatch.setenv("DISCOVERY_PHYSICS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("DISCOVERY_PHYSICS_IN_CONTAINER", raising=False)
    return tmp_path


def criterion(kind):
    result = {"id": "cross", "kind": kind, "metric": "quantity.pressure",
              "rationale": "Compare only commensurate recorded member quantities."}
    result.update({
        "gci": {"max_gci_pct": 10.0},
        "range": {"bounds": [0.0, 1000.0]},
        "monotonic": {"parameter": "h", "direction": "increasing"},
        "best": {"goal": "minimize"},
    }[kind])
    return result


def spec_for(kind="range", units=("Pa", "Pa", "Pa")):
    members = []
    for i, unit in enumerate(units):
        bundle = forward_step_bundle(TUT, name=f"member_{i}")
        bundle["diagnostics"]["quantities"] = [{
            "name": "pressure", "function": "surfaceFieldValue", "column": "areaAverage(p)",
            "settings": {"select": "patch", "patch": "inlet", "operation": "areaAverage", "fields": "(p)"},
            "unit": unit,
        }]
        members.append({"name": f"m{i}", "bundle": bundle, "h": float(2**i),
                        "parameters": {"h": float(2**i)}})
    return {"id": "unit_study", "title": "Cross-run unit binding", "requested_prompt": "Compare measured pressure consistently.",
            "kind": "refinement" if kind == "gci" else "candidates" if kind == "best" else "sweep",
            "members": members,
            "criteria": [{"id": "health", "kind": "all_accept", "rationale": "Require finalized accepted members."}, criterion(kind)]}


@pytest.mark.parametrize("kind", ["gci", "range", "monotonic", "best"])
@pytest.mark.parametrize("bad_unit", ["kPa", "1", "", " "])
def test_prepare_refuses_incompatible_or_blank_units_before_staging(kind, bad_unit, monkeypatch, isolated_store):
    spec = spec_for(kind, ("Pa", "Pa", bad_unit))
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: pytest.fail("No member may be staged before unit validation."))
    with pytest.raises(ValueError, match="unit"):
        study.prepare(spec)
    assert not (isolated_store / "runs").exists()
    assert not (isolated_store / "studies").exists()


@pytest.mark.parametrize("kind", ["gci", "range", "monotonic", "best"])
def test_prepare_requires_metric_in_every_member(kind, monkeypatch, isolated_store):
    spec = spec_for(kind)
    spec["members"][-1]["bundle"]["diagnostics"]["quantities"] = []
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: pytest.fail("Incomplete metric binding must stage nothing."))
    with pytest.raises(ValueError, match="numeric metric"):
        study.prepare(spec)
    assert not (isolated_store / "runs").exists()


def test_prepare_rejects_boolean_cross_run_metric(monkeypatch):
    spec = spec_for()
    spec["criteria"][-1]["metric"] = "solver.completed"
    monkeypatch.setattr(runner, "prepare", lambda *a, **k: pytest.fail("Boolean metric must stage nothing."))
    with pytest.raises(ValueError, match="numeric metric"):
        study.prepare(spec)


def synthetic_leaves(spec, units=None, values=None):
    units = units or ["Pa"] * len(spec["members"])
    values = values or [100.01, 100.04, 100.16]
    leaves = {}
    for i, member in enumerate(spec["members"]):
        leaves[f"run-{i}"] = {
            "evidence": SimpleNamespace(metrics={"quantity.pressure": Metric(
                value=values[i], unit=units[i], source="synthetic cross-run unit test")}),
            "final": {"final_verdict": "ACCEPT", "live_acceptance": True},
            "assessment": SimpleNamespace(verdict=Verdict.ACCEPT),
            "plan": {"run_id": f"run-{i}"}, "started": True,
        }
    return leaves


def assess_synthetic(spec, monkeypatch, tmp_path, leaves=None):
    model = study.Study.model_validate(spec)
    leaves = leaves or synthetic_leaves(spec)
    monkeypatch.setattr(study, "_verified_study", lambda _: (
        tmp_path, model, {m.name: f"run-{i}" for i, m in enumerate(model.members)}))
    monkeypatch.setattr(study, "_leaf", lambda rid: leaves[rid])
    monkeypatch.setattr(study.integrity, "append", lambda *a, **k: None)
    return study.assess("synthetic-study")


@pytest.mark.parametrize("kind", ["gci", "range", "monotonic", "best"])
def test_assessment_does_not_compare_recorded_unit_mismatches(kind, monkeypatch, tmp_path):
    spec = spec_for(kind)
    leaves = synthetic_leaves(spec, units=["Pa", "kPa", "Pa"])
    monkeypatch.setattr(study, "gci", lambda *a: pytest.fail("Incompatible values must not reach GCI."))
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    cross = result["criteria"][-1]
    assert cross["state"] == "UNKNOWN" and result["verdict"] == "INCONCLUSIVE"
    assert cross["unit"] == "Pa" and "unit mismatch" in cross["detail"]["issue"]
    assert "ranking" not in cross["detail"]


@pytest.mark.parametrize("kind", ["gci", "range", "monotonic", "best"])
def test_legacy_study_declaration_mismatch_fails_closed(kind, monkeypatch, tmp_path):
    spec = spec_for(kind, ("Pa", "kPa", "Pa"))
    result = assess_synthetic(spec, monkeypatch, tmp_path)
    assert result["verdict"] == "INCONCLUSIVE"
    assert "unit mismatch" in result["criteria"][-1]["detail"]["issue"]


@pytest.mark.parametrize("kind", ["gci", "range", "monotonic", "best"])
@pytest.mark.parametrize("problem", ["missing", "invalid", "bool", "nonfinite"])
def test_unusable_member_metric_is_unknown_not_numeric_error(kind, problem, monkeypatch, tmp_path):
    spec = spec_for(kind)
    leaves = synthetic_leaves(spec)
    metrics = leaves["run-1"]["evidence"].metrics
    if problem == "missing":
        metrics.clear()
    else:
        value = {"invalid": None, "bool": True, "nonfinite": float("inf")}[problem]
        metrics["quantity.pressure"] = Metric.model_construct(
            value=value, unit="Pa", source="malformed synthetic control",
            status="invalid" if problem == "invalid" else "measured")
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["criteria"][-1]["state"] == "UNKNOWN"


@pytest.mark.parametrize("kind", ["gci", "range", "monotonic", "best"])
def test_same_unit_comparisons_pass_and_preserve_units(kind, monkeypatch, tmp_path):
    spec = spec_for(kind)
    result = assess_synthetic(spec, monkeypatch, tmp_path)
    assert result["verdict"] == "ACCEPT"
    assert result["criteria"][-1]["state"] == "PASS"
    assert result["criteria"][-1]["unit"] == "Pa"
    assert "Recorded comparison unit: `Pa`." in (tmp_path / "study_report.md").read_text(encoding="utf-8")


def test_gci_checks_extra_members_not_only_selected_three(monkeypatch, tmp_path):
    spec = spec_for("gci", ("Pa", "Pa", "Pa", "Pa"))
    leaves = synthetic_leaves(spec, units=["Pa", "Pa", "Pa", "kPa"], values=[1.0, 1.1, 1.4, 2.6])
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    assert result["verdict"] == "INCONCLUSIVE"
    assert "m3" in result["criteria"][-1]["detail"]["recorded_units"]


def test_dimensionless_metrics_keep_recorded_label(monkeypatch, tmp_path):
    spec = spec_for("range", ("1", "1", "1"))
    leaves = synthetic_leaves(spec, units=["1", "1", "1"])
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    assert result["verdict"] == "ACCEPT" and result["criteria"][-1]["unit"] == "1"


def test_best_with_tolerated_failed_member_uses_only_valid_accepted_pool(monkeypatch, tmp_path):
    spec = spec_for("best")
    spec["criteria"][0]["min_accepted"] = 2
    leaves = synthetic_leaves(spec, units=["Pa", "Pa", "kPa"])
    leaves["run-2"]["final"] = {"final_verdict": "REJECT", "live_acceptance": False}
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    assert result["verdict"] == "ACCEPT"
    detail = result["criteria"][-1]["detail"]
    assert detail["excluded_not_accepted"] == ["m2"]
    assert len(detail["ranking"]) == 2


def test_best_without_accepted_members_remains_unknown(monkeypatch, tmp_path):
    spec = spec_for("best")
    spec["criteria"][0]["min_accepted"] = 1
    leaves = synthetic_leaves(spec)
    for state in leaves.values():
        state["final"] = {"final_verdict": "REJECT", "live_acceptance": False}
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    assert result["verdict"] == "REJECT"
    assert result["criteria"][-1]["state"] == "UNKNOWN"


def test_unit_mismatch_never_reaches_advisory_surrogate(monkeypatch, tmp_path):
    spec = spec_for("best")
    spec["design_bounds"] = {"h": [1.0, 4.0]}
    leaves = synthetic_leaves(spec, units=["Pa", "kPa", "Pa"])
    monkeypatch.setattr(study, "quadratic_surrogate", lambda *a: pytest.fail("Do not train on incompatible units."))
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["surrogate"]["ok"] is False


def test_signed_member_can_pass_own_contract_but_study_rejects_its_unchecked_wrong_unit():
    spec = spec_for("range")
    prepared = study.prepare(spec)
    for i, member in enumerate(spec["members"]):
        rid = prepared["members"][member["name"]]

        def mutate(metrics, index=i):
            metrics["quantity.pressure"] = {"value": 100.0 + index,
                "unit": "kPa" if index == 1 else "Pa", "source": "synthetic unchecked quantity", "status": "measured"}
            return metrics

        assert _fake_execute(rid, member["bundle"], mutate)["verdict"] == "ACCEPT"
        runner.propose(rid, {"action": "ACCEPT", "rationale": "Only the member's registered checks passed."})
        runner.finalize(rid)
        assert runner.verify(rid)["ok"]
    result = study.assess(prepared["study_id"])
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["criteria"][-1]["detail"]["issue"] == "recorded metric unit mismatch"


def test_frozen_study_itself_binds_units_without_new_sidecar(monkeypatch):
    spec = spec_for("range")
    prepared = study.prepare(spec)
    _, model, _ = study._verified_study(prepared["study_id"])
    assert model.members[0].bundle["diagnostics"]["quantities"][0]["unit"] == "Pa"
    changed = copy.deepcopy(spec)
    changed["members"][1]["bundle"]["diagnostics"]["quantities"][0]["unit"] = "kPa"
    assert changed != model.model_dump(mode="json")