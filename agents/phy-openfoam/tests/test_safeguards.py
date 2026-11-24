"""P0/P1 safeguards: lint, baseline, integrity/tamper, gating, fail-closed limits, studies, GCI."""

from __future__ import annotations

import json
import math
import subprocess
import threading
import time

import pytest

from discovery_physics.benchmarks.cases import forward_step_bundle, nozzle_bundle
from discovery_physics.core import integrity
from discovery_physics.core.design import latin_hypercube, quadratic_surrogate
from discovery_physics.core.gci import gci
from discovery_physics.core.hashing import sha256_json
from discovery_physics.core.lint import inject_baseline, lint
from discovery_physics.core.models import CaseBundle, Command
from discovery_physics.core.slots import QueueTimeout, slot
from discovery_physics.openfoam import runner
from discovery_physics.openfoam.catalog import BASELINE, known_metrics
from discovery_physics.openfoam.estimate import block_cells
from discovery_physics.openfoam.extract import Metrics, _residuals
from discovery_physics.openfoam.safety import validate_files

from test_core import TUT, healthy_metrics


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("DISCOVERY_PHYSICS_KEY_FILE", str(tmp_path / "keys" / "journal.key"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", raising=False)
    monkeypatch.delenv("DISCOVERY_PHYSICS_IN_CONTAINER", raising=False)
    return tmp_path


def _contract(bundle: dict):
    return CaseBundle.model_validate(bundle).contract


def _errors(bundle: dict):
    b = CaseBundle.model_validate(bundle)
    return lint(inject_baseline(b.contract, BASELINE), known_metrics(b.diagnostics))


# --------------------------------------------------------------------------- lint and baseline


@pytest.mark.parametrize("make", [lambda: forward_step_bundle(TUT), lambda: nozzle_bundle()], ids=["step", "nozzle"])
def test_benchmark_contracts_lint_clean(make):
    errors, _ = _errors(make())
    assert errors == []


def _with_check(bundle: dict, **check) -> dict:
    c = {"id": "extra", "metric": "solver.steps", "operator": "gt", "threshold": 1, "unit": "1",
         "category": "execution", "rationale": "an added test check", **check}
    bundle["contract"]["checks"].append(c)
    bundle["contract"]["objectives"][0]["check_ids"].append("extra")
    return bundle


@pytest.mark.parametrize("check,needle", [
    ({"metric": "quantity.missing"}, "not produced"),
    ({"metric": "fields.p.final_max", "unit": "Pa"}, "differs from the metric's unit"),
    ({"metric": "fields.p.final_max", "category": "reference"}, "single-cell extreme"),
    ({"metric": "solver.completed", "operator": "gt"}, "boolean"),
    ({"metric": "solver.steps", "operator": "true", "threshold": None}, "numeric"),
    ({"failure": "incomplete"}, "only horizon/stationarity"),
])
def test_lint_refuses_bad_checks(check, needle):
    errors, _ = _errors(_with_check(forward_step_bundle(TUT), **check))
    assert any(needle in e for e in errors), errors


def test_lint_requires_reference_source_and_rejects_single_run_mesh_independence():
    b = _with_check(forward_step_bundle(TUT), category="reference")
    b["contract"]["reference"] = "No external validation claimed."
    assert any("cite their source" in e for e in _errors(b)[0])
    b = forward_step_bundle(TUT)
    b["contract"]["objectives"].append({"id": "mi", "claim": "mesh_independence", "description": "grid study",
                                        "check_ids": [b["contract"]["checks"][0]["id"]]})
    errors = _errors(b)[0]
    assert any("study gci criterion" in e for e in errors)
    assert any("has no ['discretization'] check" in e for e in errors)


def test_baseline_injected_once_and_hash_stable():
    b = forward_step_bundle(TUT)
    b["contract"]["checks"] = [c for c in b["contract"]["checks"] if c["metric"] != "mesh.stage_clean"]
    for o in b["contract"]["objectives"]:
        o["check_ids"] = [i for i in o["check_ids"] if i in {c["id"] for c in b["contract"]["checks"]}]
    c = inject_baseline(_contract(b), BASELINE)
    assert "baseline_mesh_stage_clean" in {x.id for x in c.checks}
    assert inject_baseline(c, BASELINE) == c
    frozen1, _ = runner.freeze(b)
    frozen2, _ = runner.freeze(b)
    assert sha256_json(frozen1.contract) == sha256_json(frozen2.contract)


def test_derived_operands_and_comment_banners_are_linted():
    """Held-out regressions: CLIO wasted 13 solves on these before lint caught them."""
    b = forward_step_bundle(TUT)
    b["diagnostics"]["quantities"] = [{"name": "p_in", "function": "surfaceFieldValue", "column": "areaAverage(p)",
                                       "settings": {"patch": "inlet", "operation": "areaAverage", "fields": "(p)"}}]
    b["diagnostics"]["derived"] = [
        {"name": "bare", "op": "scale", "a": "p_in"},
        {"name": "num", "op": "abs_rel_error_pct", "a": "0.76"},
        {"name": "fwd", "op": "ratio", "a": "derived.later", "b": "quantity.p_in"},
        {"name": "later", "op": "scale", "a": "quantity.p_in"},
    ]
    b["files"]["system/fvSchemes"] = "/*---- banner never closed\n" + b["files"]["system/fvSchemes"]
    r = runner.lint_bundle(b)
    text = " | ".join(r["errors"])
    assert not r["ok"]
    assert "did you mean 'quantity.p_in'" in text
    assert "'0.76' is not a produced metric" in text and "nonzero reference" in text
    assert "operand 'derived.later'" in text  # forward reference refused
    assert "unterminated /* comment" in text
    b2 = forward_step_bundle(TUT)
    b2["diagnostics"]["quantities"] = b["diagnostics"]["quantities"]
    b2["diagnostics"]["derived"] = [{"name": "ok", "op": "scale", "a": "quantity.p_in", "factor": 2.0}]
    assert runner.lint_bundle(b2)["ok"]


def test_command_argument_allowlist():
    Command(executable="snappyHexMesh", args=["-overwrite"])
    Command(executable="blockMesh", args=["-dict", "system/blockMeshDict.bg"])
    for bad in (["-case", "/etc"], ["-dict", "/etc/passwd"], ["&&", "rm"]):
        with pytest.raises(ValueError):
            Command(executable="blockMesh", args=bad)


def test_safety_allowlist():
    ok = {"system/controlDict": "solver fluid;\n", "constant/physicalProperties.water": "x 1;",
          "constant/geometry/body.stl": "solid a\nendsolid a\n", "0/U": "#include \"include/ic\"\n",
          "0/include/ic": "v 1;"}
    assert validate_files(ok) == []
    bad = {**ok, "system/evil": "x;", "constant/polyMesh/points": "()", "0/p": "#neg x\n",
           "constant/geometry/a.exe": "x"}
    f = " | ".join(validate_files(bad))
    assert "system/evil" in f and "polyMesh" in f and "#neg" in f and "a.exe" in f


def test_block_cell_estimate():
    assert block_cells("blocks ( hex (0 1 2 3 4 5 6 7) (10 20 1) simpleGrading (1 1 1)\n"
                       "hex (1 2 3 4 5 6 7 8) b2 (5 5 2) simpleGrading (1 1 1) );") == 250
    assert block_cells("blocks ( hex (0 1 2 3 4 5 6 7) ($nx 20 1) simpleGrading (1 1 1) );") is None


def test_residual_and_continuity_parsing():
    log = ("Time = 1\nsmoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.01, No Iterations 2\n"
           "GAMG:  Solving for p, Initial residual = 0.5, Final residual = 0.001, No Iterations 4\n"
           "GAMG:  Solving for p, Initial residual = 0.2, Final residual = 0.001, No Iterations 4\n"
           "time step continuity errors : sum local = 1e-05, global = 1e-19, cumulative = 1e-19\n"
           "Time = 2\nsmoothSolver:  Solving for Ux, Initial residual = 0.001, Final residual = 1e-5, No Iterations 2\n"
           "GAMG:  Solving for p, Initial residual = 0.0005, Final residual = 1e-6, No Iterations 4\n"
           "time step continuity errors : sum local = 2e-07, global = 1e-19, cumulative = 1e-19\n")
    m = Metrics()
    _residuals(m, log)
    v = {k: x.value for k, x in m.values.items()}
    assert v["solver.residual_initial_last_max"] == 0.001
    assert math.isclose(v["solver.residual_drop_orders_min"], 3.0)
    assert v["solver.continuity_local_last"] == 2e-07 and v["solver.continuity_local_max"] == 1e-05


# --------------------------------------------------------------------------- integrity and gating


def _fake_execute(run_id: str, bundle: dict, mutate=None) -> dict:
    """Stand-in for the container: write worker evidence, then use the real assessment path."""
    path = runner.run_dir(run_id)
    contract = runner.verified(run_id)["bundle"].contract
    metrics = healthy_metrics(contract) if not mutate else mutate(healthy_metrics(contract))
    metrics["solver.exit_code"] = {"value": 0, "unit": "1", "source": "fixture", "status": "measured"}
    metrics["solver.final_time"] = {"value": 4.0, "unit": "1", "source": "fixture", "status": "measured"}
    raw = {"metrics": metrics, "errors": [], "runtime": {}}
    out = path / "output"
    (out / "case").mkdir(parents=True)
    (out / "case" / "log.foamRun.01").write_text("End\n", encoding="utf-8")
    (out / "evidence.json").write_text(json.dumps(raw), encoding="utf-8")
    (out / "evidence.sha256").write_text(sha256_json(raw), encoding="utf-8")
    integrity.append(path, "execution_started", image="fixture", runtime="fixture", executor="fixture")
    return runner._assess_run(path, runner.verified(run_id)["plan"], 0, 1.0, "sha256:fixture", "fixture")


def _healthy_run():
    b = forward_step_bundle(TUT)
    rid = runner.prepare(b)["run_id"]
    return rid, b, _fake_execute(rid, b)


def test_full_lifecycle_verifies():
    rid, _, s = _healthy_run()
    assert s["verdict"] == "ACCEPT"
    assert runner.verify(rid)["ok"]
    assert runner.propose(rid, {"action": "ACCEPT", "rationale": "all checks pass here"})["approved"]
    assert runner.finalize(rid)["final_verdict"] == "ACCEPT"
    with pytest.raises(RuntimeError):
        runner.propose(rid, {"action": "ACCEPT", "rationale": "second ruling attempt"})


def test_assessment_preserves_raw_worker_bytes_through_reassessment_and_decisions(monkeypatch):
    bundle = forward_step_bundle(TUT)
    bundle["diagnostics"]["derived"] = [{"name": "twice_final", "op": "scale",
        "a": "solver.final_time", "factor": 2.0, "unit": "1"}]
    rid = runner.prepare(bundle)["run_id"]
    path = runner.run_dir(rid)
    raw_path = path / "output/evidence.json"
    host_path = path / "evidence.json"
    packets = []
    original_write = runner._write

    def capture_host_write(destination, data):
        if destination.name == "evidence.json":
            assert destination == host_path
            packets.append((raw_path.read_bytes(), (path / "output/evidence.sha256").read_bytes()))
        original_write(destination, data)

    monkeypatch.setattr(runner, "_write", capture_host_write)
    assert _fake_execute(rid, bundle)["verdict"] == "ACCEPT"
    assert len(packets) == 1
    raw_bytes, digest_bytes = packets[0]
    raw = json.loads(raw_bytes)
    enriched = json.loads(host_path.read_text(encoding="utf-8"))
    assert "run_id" not in raw and enriched["run_id"] == rid
    assert "derived.twice_final" not in raw["metrics"]
    assert enriched["metrics"]["derived.twice_final"]["value"] == 8.0
    assert enriched["runtime"]["image_id"] == "sha256:fixture"
    pinned = integrity.last(integrity.verify_journal(path), "assessed")
    assert pinned["raw_evidence_sha256"] == integrity.file_sha256(raw_path)
    assert runner.verify(rid)["ok"] and runner.summary(rid)["verdict"] == "ACCEPT"
    assert runner.reassess(rid)["verdict"] == "ACCEPT"
    assert len(packets) == 2 and packets[1] == packets[0]
    # The host convenience copy is not verification input.
    host_path.write_text('{"edited":"convenience only"}', encoding="utf-8")
    assert runner.verify(rid)["ok"] and runner.summary(rid)["verdict"] == "ACCEPT"
    assert runner.propose(rid, {"action": "ACCEPT", "rationale": "verified raw worker packet is unchanged"})["approved"]
    assert runner.finalize(rid)["final_verdict"] == "ACCEPT"
    assert runner.verify(rid)["ok"]
    assert raw_path.read_bytes() == raw_bytes
    assert (path / "output/evidence.sha256").read_bytes() == digest_bytes


def test_editing_convenience_copies_changes_nothing():
    rid, _, _ = _healthy_run()
    path = runner.run_dir(rid)
    a = json.loads((path / "assessment.json").read_text())
    a["verdict"] = "REJECT"
    (path / "assessment.json").write_text(json.dumps(a))
    (path / "ruling.json").write_text(json.dumps({"approved": True, "terminal_verdict": "REJECT"}))
    assert runner.summary(rid)["verdict"] == "ACCEPT"


@pytest.mark.parametrize("target", ["evidence", "journal_edit", "journal_forge", "bundle", "plan", "journal_drop"])
def test_tampering_is_detected(target):
    def fail_one(m):
        m["conservation.mass_closure_max_rel"]["value"] = 1.0
        return m

    b = forward_step_bundle(TUT)
    rid = runner.prepare(b)["run_id"]
    _fake_execute(rid, b, fail_one)
    path = runner.run_dir(rid)
    if target == "evidence":
        raw = json.loads((path / "output" / "evidence.json").read_text())
        raw["metrics"]["conservation.mass_closure_max_rel"]["value"] = 1e-12
        (path / "output" / "evidence.json").write_text(json.dumps(raw))
        (path / "output" / "evidence.sha256").write_text(sha256_json(raw))
    elif target in ("journal_edit", "journal_forge", "journal_drop"):
        lines = (path / "journal.jsonl").read_text().splitlines()
        rec = json.loads(lines[-1])
        if target == "journal_drop":
            lines = lines[:-1]
        else:
            rec["verdict"] = "ACCEPT"
            if target == "journal_forge":  # recompute the hash without the key
                body = {k: v for k, v in rec.items() if k not in ("hash", "mac")}
                rec["hash"] = integrity.sha256_text(integrity.canonical_json(body))
            lines[-1] = json.dumps(rec)
        (path / "journal.jsonl").write_text("\n".join(lines) + "\n")
    elif target == "bundle":
        bd = json.loads((path / "bundle.json").read_text())
        bd["contract"]["checks"] = [c for c in bd["contract"]["checks"] if c["id"] != "transient_continuity"]
        (path / "bundle.json").write_text(json.dumps(bd))
    elif target == "plan":
        pl = json.loads((path / "plan.json").read_text())
        pl["budget"]["max_attempts"] = 8
        (path / "plan.json").write_text(json.dumps(pl))
    if target == "journal_drop":
        # Dropping the last record hides the assessment; the run then looks un-executed but started.
        st = runner.verified(rid)
        assert st["assessed"] is None and st["started"]
        with pytest.raises(RuntimeError):
            runner.propose(rid, {"action": "ACCEPT", "rationale": "accept after dropping the record"})
        return
    assert not runner.verify(rid)["ok"]
    with pytest.raises(integrity.IntegrityError):
        runner.propose(rid, {"action": "ACCEPT", "rationale": "accept after tampering"})


def test_input_edit_after_prepare_blocks_execution():
    rid = runner.prepare(forward_step_bundle(TUT))["run_id"]
    (runner.run_dir(rid) / "input" / "case" / "system" / "fvSchemes").write_text("tampered;\n")
    with pytest.raises(integrity.IntegrityError):
        runner.execute(rid)


def test_wrong_key_rejects(store, monkeypatch):
    rid, _, _ = _healthy_run()
    monkeypatch.setenv("DISCOVERY_PHYSICS_KEY_FILE", str(store / "other.key"))
    assert not runner.verify(rid)["ok"]


def test_assumptions_gate_execution():
    b = forward_step_bundle(TUT)
    b["contract"]["assumptions"].append({"parameter": "wall_temperature", "value": 300, "unit": "K",
                                         "source": "needs_confirmation", "justification": "not stated by user"})
    rid = runner.prepare(b)["run_id"]
    with pytest.raises(PermissionError, match="confirmation"):
        runner.execute(rid)
    with pytest.raises(ValueError):
        runner.confirm(rid, [{"parameter": "other", "decision": "confirmed", "confirmed_by": "user"}])
    out = runner.confirm(rid, [{"parameter": "wall_temperature", "decision": "confirmed", "confirmed_by": "J. User"}])
    assert out["still_pending"] == []


class _Proc:
    def __init__(self, rc, err=""):
        self.returncode, self.stdout, self.stderr = rc, "", err


def test_resource_limits_fail_closed(monkeypatch):
    rid = runner.prepare(forward_step_bundle(TUT))["run_id"]
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if "run" in argv:
            return _Proc(125, "Error: crun: opening file `memory.max` for writing: No such file")
        return _Proc(0)

    monkeypatch.setattr(runner, "container_runtime", lambda: "podman")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="cannot enforce"):
        runner.execute(rid)
    assert not (runner.run_dir(rid) / "output").exists()
    assert integrity.last(integrity.verify_journal(runner.run_dir(rid)), "execution_refused")
    assert len([c for c in calls if "run" in c]) == 1

    monkeypatch.setenv("DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", "1")
    calls.clear()
    s = runner.execute(rid)
    runs = [c for c in calls if "run" in c]
    assert len(runs) == 2 and "--memory" not in runs[1]
    assert "UNENFORCED" in s["runtime"]["resource_limits"]
    assert s["verdict"] != "ACCEPT"  # no worker evidence was produced by the fake


def test_concurrency_slot_cap(tmp_path):
    held = threading.Event()
    release = threading.Event()

    def holder():
        with slot(tmp_path / "slots", 1, 5):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(5)
    t0 = time.monotonic()
    with pytest.raises(QueueTimeout):
        with slot(tmp_path / "slots", 1, 0.5, poll_s=0.1):
            pass
    assert time.monotonic() - t0 >= 0.5
    release.set()
    t.join()
    with slot(tmp_path / "slots", 1, 1):
        pass


# --------------------------------------------------------------------------- GCI, design, studies


def test_gci_recovers_exact_order_and_limit():
    p, exact = 1.7, 2.0
    h = [0.1, 0.13, 0.2]
    phi = [exact - 0.3 * x ** p for x in h]
    r = gci(h, phi)
    assert r.status == "monotonic"
    assert math.isclose(r.order, p, rel_tol=1e-8)
    assert math.isclose(r.extrapolated, exact, rel_tol=1e-10)
    # GCI_fine is a 1.25-safety-factor band around the true fine-grid error.
    true_err = abs(phi[0] - exact) / abs(phi[0]) * 100
    assert math.isclose(r.gci_fine_pct, 1.25 * true_err, rel_tol=1e-6)
    # In the asymptotic range GCI_32 / (r21^p GCI_21) ~ 1 (not exact: errors are normalized by phi1 vs phi2).
    assert math.isclose(r.asymptotic_ratio, 1.0, rel_tol=1e-2)


def test_gci_classifies_oscillatory_and_divergent():
    assert gci([1, 2, 4], [1.0, 1.1, 0.95]).status == "oscillatory"
    assert gci([1, 2, 4], [1.0, 1.5, 1.6]).status == "divergent"
    assert gci([1, 1.05, 2], [1, 2, 3]).status == "invalid"


def test_latin_hypercube_is_stratified_and_deterministic():
    pts = latin_hypercube({"a": (0, 1), "b": (10, 20)}, 8, seed=3)
    assert pts == latin_hypercube({"a": (0, 1), "b": (10, 20)}, 8, seed=3)
    for k, lo, hi in (("a", 0, 1), ("b", 10, 20)):
        bins = sorted(int((p[k] - lo) / (hi - lo) * 8) for p in pts)
        assert bins == list(range(8))


def test_surrogate_finds_quadratic_minimum():
    pts = latin_hypercube({"x": (0, 4), "y": (-2, 2)}, 12, seed=1)
    vals = [(p["x"] - 1.5) ** 2 + 2 * (p["y"] + 0.5) ** 2 + 3 for p in pts]
    s = quadratic_surrogate(pts, vals, {"x": (0, 4), "y": (-2, 2)})
    assert s["ok"] and s["advisory"] and s["loo_rmse"] < 1e-8
    assert abs(s["predicted_optimum"]["x"] - 1.5) <= 0.1 and abs(s["predicted_optimum"]["y"] + 0.5) <= 0.1


def _study_spec(values: dict[str, float], hs: dict[str, float], criteria: list[dict], kind="refinement"):
    members = []
    for name, h in hs.items():
        members.append({"name": name, "bundle": forward_step_bundle(TUT, name=f"m_{name}"), "h": h,
                        "parameters": {"h": h}})
    return {"id": "grid_study", "title": "grid study test", "requested_prompt": "is the ratio grid independent?",
            "kind": kind, "members": members, "criteria": [
                {"id": "all", "kind": "all_accept", "rationale": "every member healthy"}, *criteria]}


def _run_study(spec, values):
    from discovery_physics.openfoam import study

    prep = study.prepare(spec)
    for m in spec["members"]:
        rid = prep["members"][m["name"]]

        def mutate(metrics, v=values[m["name"]]):
            metrics["compression.p_ratio"]["value"] = v
            return metrics

        _fake_execute(rid, m["bundle"], mutate)
        runner.propose(rid, {"action": "ACCEPT", "rationale": "member checks pass"})
        runner.finalize(rid)
    return study.assess(prep["study_id"])


def test_refinement_study_gci_pass_and_fail():
    hs = {"fine": 1.0, "medium": 2.0, "coarse": 4.0}
    vals = {k: 5.0 + 0.01 * h ** 2 for k, h in hs.items()}
    crit = [{"id": "gci_p", "kind": "gci", "metric": "compression.p_ratio", "max_gci_pct": 1.0,
             "rationale": "grid error under one percent"}]
    res = _run_study(_study_spec(vals, hs, crit), vals)
    assert res["verdict"] == "ACCEPT", res
    g = next(c for c in res["criteria"] if c["id"] == "gci_p")["detail"]
    assert math.isclose(g["order"], 2.0, rel_tol=1e-8)
    vals2 = {k: 5.0 + 0.3 * h ** 2 for k, h in hs.items()}
    res2 = _run_study(_study_spec(vals2, hs, crit), vals2)
    assert res2["verdict"] == "REJECT"


def test_candidate_selection_needs_margin_beyond_uncertainty():
    hs = {"a": 1.0, "b": 1.0, "c": 1.0}
    crit = [{"id": "best", "kind": "best", "metric": "compression.p_ratio", "goal": "maximize",
             "uncertainty_pct": 1.0, "rationale": "pick the strongest compression"}]
    close = {"a": 5.00, "b": 5.02, "c": 4.0}
    res = _run_study(_study_spec(close, hs, crit, kind="candidates"), close)
    assert res["verdict"] == "INCONCLUSIVE"
    clear = {"a": 5.00, "b": 5.6, "c": 4.0}
    res = _run_study(_study_spec(clear, hs, crit, kind="candidates"), clear)
    best = next(c for c in res["criteria"] if c["id"] == "best")
    assert res["verdict"] == "ACCEPT" and best["detail"]["best"] == "b"


def test_study_with_rejected_member_cannot_accept():
    from discovery_physics.openfoam import study

    hs = {"fine": 1.0, "medium": 2.0, "coarse": 4.0}
    spec = _study_spec({}, hs, [{"id": "gci_p", "kind": "gci", "metric": "compression.p_ratio", "max_gci_pct": 5,
                                 "rationale": "grid error bound"}])
    prep = study.prepare(spec)
    for i, m in enumerate(spec["members"]):
        rid = prep["members"][m["name"]]

        def mutate(metrics, bad=i == 0):
            if bad:
                metrics["fields.finite_all_saved"]["value"] = False
            return metrics

        _fake_execute(rid, m["bundle"], mutate)
        runner.propose(rid, {"action": "FAIL_SAFELY" if i == 0 else "ACCEPT", "rationale": "member decision"})
        runner.finalize(rid)
    res = study.assess(prep["study_id"])
    assert res["verdict"] == "REJECT"
    assert next(c for c in res["criteria"] if c["id"] == "gci_p")["state"] == "UNKNOWN"
