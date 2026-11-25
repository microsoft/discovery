"""A ranking's GCI dependency is independent of authored criterion order; no CFD."""

from __future__ import annotations

import copy
import itertools

import pytest

from discovery_physics.openfoam import runner, study

from test_safeguards import _fake_execute
from test_study_units import assess_synthetic, spec_for, synthetic_leaves


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    for name, suffix in (("DISCOVERY_PHYSICS_RUNS", "runs"), ("DISCOVERY_PHYSICS_HOME", "home"),
                         ("DISCOVERY_PHYSICS_KEY_FILE", "keys/journal.key"), ("LOCALAPPDATA", "app")):
        monkeypatch.setenv(name, str(tmp_path / suffix))
    monkeypatch.delenv("DISCOVERY_PHYSICS_IN_CONTAINER", raising=False)


def dependent_spec(order=("health", "best", "grid")):
    spec = spec_for("gci")
    grid = {**spec["criteria"][-1], "id": "grid", "max_gci_pct": 1.0}
    best = {"id": "best", "kind": "best", "metric": "quantity.pressure", "goal": "minimize",
            "uncertainty_from": "grid", "rationale": "Separate candidates using the registered GCI uncertainty."}
    criteria = {"health": spec["criteria"][0], "best": best, "grid": grid}
    spec["criteria"] = [criteria[name] for name in order]
    return spec


@pytest.mark.parametrize("order", list(itertools.permutations(("health", "best", "grid"))))
def test_gci_dependency_is_independent_of_criterion_order(order, tmp_path, monkeypatch):
    spec = dependent_spec(order)
    original = copy.deepcopy(spec)
    calls = []
    real = study.gci

    def once(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(study, "gci", once)
    result = assess_synthetic(spec, monkeypatch, tmp_path)
    assert result["verdict"] == "ACCEPT"
    assert [c["id"] for c in result["criteria"]] == list(order)
    by_id = {c["id"]: c for c in result["criteria"]}
    assert by_id["grid"]["state"] == by_id["best"]["state"] == "PASS"
    assert by_id["best"]["detail"]["uncertainty_pct"] == by_id["grid"]["detail"]["gci_fine_pct"]
    assert by_id["best"]["detail"]["best"] == "m0"
    assert len(calls) == 1 and spec == original


@pytest.mark.parametrize("order", [("best", "grid", "health"), ("grid", "health", "best")])
@pytest.mark.parametrize("problem", ["missing", "failed", "oscillatory"])
def test_unavailable_or_failed_gci_never_becomes_zero_uncertainty(order, problem, tmp_path, monkeypatch):
    spec = dependent_spec(order)
    grid = next(c for c in spec["criteria"] if c["id"] == "grid")
    leaves = synthetic_leaves(spec)
    if problem == "missing":
        grid["metric"] = "solver.steps"  # Declared numeric, but intentionally absent in the evidence.
    elif problem == "failed":
        grid["max_gci_pct"] = 1e-8
    else:
        for state, value in zip(leaves.values(), [100.01, 100.04, 100.02]):
            state["evidence"].metrics["quantity.pressure"].value = value
    result = assess_synthetic(spec, monkeypatch, tmp_path, leaves)
    by_id = {c["id"]: c for c in result["criteria"]}
    assert by_id["best"]["state"] == "UNKNOWN"
    assert result["verdict"] == ("REJECT" if problem == "failed" else "INCONCLUSIVE")


def test_shared_gci_dependency_is_evaluated_once(tmp_path, monkeypatch):
    spec = dependent_spec()
    spec["criteria"].insert(0, {**spec["criteria"][1], "id": "second_best", "goal": "maximize"})
    calls = []
    real = study.gci

    def count(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(study, "gci", count)
    result = assess_synthetic(spec, monkeypatch, tmp_path)
    assert result["verdict"] == "ACCEPT" and len(calls) == 1
    assert [c["id"] for c in result["criteria"]] == [c["id"] for c in spec["criteria"]]


def test_signed_study_accepts_forward_gci_reference_without_reordering_frozen_spec():
    spec = dependent_spec()
    prepared = study.prepare(spec)
    _, frozen, _ = study._verified_study(prepared["study_id"])
    before = frozen.model_dump(mode="json")
    for index, member in enumerate(spec["members"]):
        rid = prepared["members"][member["name"]]

        def measured(metrics, i=index):
            metrics["quantity.pressure"] = {"value": [100.01, 100.04, 100.16][i], "unit": "Pa",
                                            "source": "synthetic dependency control", "status": "measured"}
            return metrics

        assert _fake_execute(rid, member["bundle"], measured)["verdict"] == "ACCEPT"
        runner.propose(rid, {"action": "ACCEPT", "rationale": "The synthetic member passed its own checks."})
        runner.finalize(rid)
    result = study.assess(prepared["study_id"])
    assert result["verdict"] == "ACCEPT"
    assert [c["id"] for c in result["criteria"]] == ["health", "best", "grid"]
    assert study._verified_study(prepared["study_id"])[1].model_dump(mode="json") == before