from __future__ import annotations

import math

import pytest

from discovery_physics.benchmarks.cases import forward_step_bundle, nozzle_bundle
from discovery_physics.benchmarks.faults import EXTRA, FAULTS, planted, scientific_verdict
from discovery_physics.benchmarks.quasi1d import Nozzle1D
from discovery_physics.core.checks import assess
from discovery_physics.core.hashing import sha256_json
from discovery_physics.core.models import Assessment, CaseBundle, Contract, Evidence, Verdict
from discovery_physics.core.policy import Proposal, rule
from discovery_physics.openfoam.extract import FATAL
from discovery_physics.openfoam.monitors import instrument_control_dict
from discovery_physics.openfoam.safety import validate_files

TUT = {
    "system/fvSchemes": "fluxScheme Kurganov;\n",
    "system/fvSolution": "solvers {}\n",
    "constant/physicalProperties": "thermoType {}\n",
    "constant/momentumTransport": "simulationType laminar;\n",
}


def healthy_metrics(contract: Contract) -> dict:
    """Evidence that satisfies every check of the forward-step benchmark contract."""
    values = {
        "solver.completed": True, "solver.fatal_error": False, "mesh.check_ok": True,
        "mesh.dimension_matches": True, "mesh.stage_clean": True, "mesh.cell_count_matches": True,
        "mesh.expected_patches_present": True, "mesh.cyclic_patch_count": 0, "mesh.planar_patch_present": True,
        "setup.reference_files_match": True, "setup.case_hash_matches": True, "fields.finite_all_saved": True,
        "fields.positive_all_saved": True, "fields.positive_every_step": True,
        "solver.courant_finite_positive": True, "flow.inlet_mach_min": 2.000006,
        "setup.initial_state_max_rel_error": 0.0, "conservation.impermeable_flux_max_rel": 0.0,
        "conservation.mass_closure_max_rel": 5.7e-11, "conservation.restart_seams_continuous": True,
        "compression.front_measurable": True, "compression.p_ratio": 5.2, "compression.rho_ratio": 2.9,
        "compression.T_ratio": 1.8, "solver.reached_target_time": True,
    }
    assert {c.metric for c in contract.checks} <= set(values)
    return {k: {"value": v, "unit": "1", "source": "fixture", "status": "measured"} for k, v in values.items()}


@pytest.fixture()
def step():
    bundle = CaseBundle.model_validate(forward_step_bundle(TUT))
    ev = Evidence(run_id="t", origin="native", solver_invoked=True, contract_sha256=sha256_json(bundle.contract),
                  case_sha256="x", metrics=healthy_metrics(bundle.contract))
    return bundle, ev


def test_healthy_step_accepts(step):
    bundle, ev = step
    a = assess(bundle.contract, ev)
    assert a.verdict == Verdict.ACCEPT and a.live_acceptance


@pytest.mark.parametrize("fault", FAULTS, ids=lambda f: f.name)
def test_every_planted_fault_is_rejected_by_its_check(step, fault):
    bundle, ev = step
    a = scientific_verdict(bundle.contract, planted(ev, fault))
    assert a.verdict == Verdict.REJECT
    failed = {c.id for c in a.checks if c.state == "FAIL"}
    assert fault.expected_check in failed


@pytest.mark.parametrize("fault", EXTRA, ids=lambda f: f.name)
def test_missing_or_malformed_evidence_never_accepts(step, fault):
    bundle, ev = step
    a = scientific_verdict(bundle.contract, planted(ev, fault))
    assert a.verdict in (Verdict.INCONCLUSIVE, Verdict.REJECT)


def test_synthetic_evidence_cannot_be_live(step):
    bundle, ev = step
    a = assess(bundle.contract, Evidence.model_validate({**ev.model_dump(), "origin": "synthetic"}))
    assert not a.live_acceptance and a.verdict != Verdict.ACCEPT


def test_contract_swap_detected(step):
    bundle, ev = step
    looser = bundle.contract.model_copy(update={"title": "relaxed copy of the contract"})
    assert assess(looser, ev).verdict == Verdict.INCONCLUSIVE


def test_incomplete_horizon_requests_rerun(step):
    bundle, ev = step
    ev.metrics["solver.reached_target_time"].value = False
    assert assess(bundle.contract, ev).verdict == Verdict.CORRECT_AND_RERUN


def test_hard_failure_outranks_incomplete(step):
    bundle, ev = step
    ev.metrics["solver.reached_target_time"].value = False
    ev.metrics["conservation.mass_closure_max_rel"].value = 1e-3
    assert assess(bundle.contract, ev).verdict == Verdict.REJECT


def test_uncovered_objective_is_inconclusive():
    bundle = CaseBundle.model_validate(forward_step_bundle(TUT, sensitivity_request=True))
    ev = Evidence(run_id="t", origin="native", solver_invoked=True, contract_sha256=sha256_json(bundle.contract),
                  case_sha256="x", metrics=healthy_metrics(bundle.contract))
    a = assess(bundle.contract, ev)
    assert a.verdict == Verdict.INCONCLUSIVE
    assert any("mesh_sensitivity" in u for u in a.unresolved)


def test_proposed_contract_cannot_accept(step):
    bundle, ev = step
    c = bundle.contract.model_copy(update={"authority": "proposed"})
    ev2 = Evidence.model_validate({**ev.model_dump(), "contract_sha256": sha256_json(c)})
    assert assess(c, ev2).verdict == Verdict.INCONCLUSIVE


def _rule(a: Assessment, **p):
    return rule(a, Proposal(rationale="test rationale", **p), attempts_used=1, max_attempts=4, final_time=2.0,
                max_end_time=4.0, cells=16128, max_cells=200000, dimensions=2, known_evidence=set())


def test_gate_refuses_accept_unless_verdict_accepts(step):
    bundle, ev = step
    ev.metrics["solver.reached_target_time"].value = False
    a = assess(bundle.contract, ev)
    r = _rule(a, action="ACCEPT")
    assert not r.approved and r.terminal_verdict == Verdict.INCONCLUSIVE


def test_gate_bounds_continuation(step):
    bundle, ev = step
    ev.metrics["solver.reached_target_time"].value = False
    a = assess(bundle.contract, ev)
    assert _rule(a, action="CONTINUE_RUN", end_time=4.0).approved
    assert not _rule(a, action="CONTINUE_RUN", end_time=8.0).approved
    assert not _rule(a, action="CONTINUE_RUN", end_time=1.0).approved


def test_gate_refuses_continuation_of_broken_run(step):
    bundle, ev = step
    ev.metrics["conservation.mass_closure_max_rel"].value = 1.0
    a = assess(bundle.contract, ev)
    assert not _rule(a, action="CONTINUE_RUN", end_time=4.0).approved
    r = _rule(a, action="FAIL_SAFELY")
    assert r.approved and r.terminal_verdict == Verdict.REJECT


def test_gate_refuses_fabricated_citation(step):
    bundle, ev = step
    a = assess(bundle.contract, ev)
    assert not _rule(a, action="ACCEPT", evidence_cited=["made.up.metric"]).approved


def test_fatal_detector_ignores_sigfpe_banner():
    banner = "sigFpe : Enabling floating point exception trapping (FOAM_SIGFPE)."
    assert not FATAL.search(banner)
    for real in ("--> FOAM FATAL ERROR:", "#0  Foam::sigFpe::sigHandler(int) at ??:?",
                 "Floating point exception (core dumped)", "--> FOAM FATAL IO ERROR:"):
        assert FATAL.search(real)


@pytest.mark.parametrize("snippet", [
    "#codeStream { code #{ system(\"rm -rf /\"); #}; }", "type codedFixedValue;", "type systemCall;",
    "#include \"/etc/passwd\"", "#include \"../../secret\"", "libs (\"/tmp/evil.so\");", "#calc \"1+1\";",
])
def test_safety_rejects_code_execution(snippet):
    files = {"system/controlDict": "solver shockFluid;\nendTime 1;\n", "system/fvSchemes": snippet,
             "system/fvSolution": ""}
    assert validate_files(files)


def test_safety_rejects_paths_and_user_functions():
    base = {"system/fvSchemes": "", "system/fvSolution": ""}
    assert validate_files({**base, "system/controlDict": "solver x;\nfunctions { }\n"})
    assert validate_files({**base, "system/controlDict": "solver x;\n", "../escape": ""})
    assert validate_files({**base, "system/controlDict": "solver x;\n", "constant/polyMesh/points": ""})
    assert not validate_files({**base, "system/controlDict": "solver x;\nendTime 1;\n"})


def test_benchmarks_pass_safety_and_schema():
    for b in (forward_step_bundle(TUT), nozzle_bundle()):
        assert not validate_files(b["files"])
        CaseBundle.model_validate(b)


def test_time_precision_never_overflows():
    from discovery_physics.openfoam.monitors import time_precision

    assert time_precision(4.0) == 14 and time_precision(0.006) == 15
    assert time_precision(240.0) == 12 and time_precision(1e6) == 12


def test_instrumentation_pins_precision_and_monitors():
    b = CaseBundle.model_validate(forward_step_bundle(TUT))
    text = instrument_control_dict(b.files["system/controlDict"], b.diagnostics)
    assert "writePrecision 17;" in text and "writePrecision 6;" not in text
    assert "flux_obstacle" in text and "domain_mass" in text and "extrema" in text


def test_quasi1d_matches_published_reference():
    q = Nozzle1D(0.0326, 200000.0, 300.0)
    p, t, u, m = q.state(0.0354, supersonic=True)
    # Paper Table 7 theory column: M 1.5044, p 54.13 kPa, T 206.52 K, U 433.36 m/s, mdot 1.558 kg/s.
    assert math.isclose(m, 1.5044, abs_tol=5e-4)
    assert math.isclose(p / 1000, 54.13, abs_tol=0.01)
    assert math.isclose(t, 206.52, abs_tol=0.01)
    assert math.isclose(u, 433.36, abs_tol=0.05)
    assert math.isclose(q.choked_mass_flow(), 1.558, abs_tol=5e-4)


def test_derived_metrics_fail_closed():
    from discovery_physics.core.derived import compute
    from discovery_physics.core.models import Derived, Metric

    m = {"quantity.p_in": Metric(value=3.0, unit="Pa", source="t"),
         "quantity.p_out": Metric(value=1.0, unit="Pa", source="t")}
    out = compute([Derived(name="dp", op="difference", a="quantity.p_in", b="quantity.p_out", unit="Pa"),
                   Derived(name="err", op="abs_rel_error_pct", a="derived.dp", reference=2.5, unit="%"),
                   Derived(name="bad", op="ratio", a="quantity.p_in", b="quantity.missing")], m)
    assert out["derived.dp"].value == 2.0
    assert abs(out["derived.err"].value - 20.0) < 1e-12
    assert out["derived.bad"].status == "missing"


def test_unmeasurable_window_before_horizon_is_incomplete():
    b = CaseBundle.model_validate(nozzle_bundle())
    c = b.contract
    vals = {ch.metric: (ch.threshold[0] + ch.threshold[1]) / 2 if ch.operator == "between" else
            (True if ch.operator == "true" else (ch.threshold if ch.operator == "eq" else
             (ch.threshold * 0.5 if ch.operator in ("lt", "le") else ch.threshold * 2)))
            for ch in c.checks}
    vals["solver.reached_target_time"] = False
    vals.pop("stationarity.field_change_max")
    ev = Evidence(run_id="t", origin="native", solver_invoked=True, contract_sha256=sha256_json(c),
                  case_sha256="x", metrics={k: {"value": v, "unit": next(x.unit for x in c.checks if x.metric == k),
                                                "source": "t"} for k, v in vals.items()})
    assert assess(c, ev).verdict == Verdict.CORRECT_AND_RERUN
    vals["solver.reached_target_time"] = True  # at horizon, missing evidence is inconclusive
    ev.metrics["solver.reached_target_time"].value = True
    assert assess(c, ev).verdict == Verdict.INCONCLUSIVE


def test_mesh_sensitivity_without_tolerance_is_refused():
    """Paper S8: both grids healthy, but no registered cross-grid tolerance -> INCONCLUSIVE."""
    b = CaseBundle.model_validate(forward_step_bundle(TUT, sensitivity_request=True))
    ev = Evidence(run_id="t", origin="native", solver_invoked=True, contract_sha256=sha256_json(b.contract),
                  case_sha256="x", metrics=healthy_metrics(b.contract))
    a = assess(b.contract, ev)
    assert a.verdict == Verdict.INCONCLUSIVE
    assert _rule(a, action="REFINE_MESH", refinement_factor=2.0).approved
    r = _rule(a, action="ACCEPT")
    assert not r.approved and r.terminal_verdict == Verdict.INCONCLUSIVE


def test_fabricated_accept_is_refused_for_every_fault(step):
    """Forced-ACCEPT proposer: enforcement never exercised by the paper's model."""
    bundle, ev = step
    for fault in FAULTS:
        a = scientific_verdict(bundle.contract, planted(ev, fault))
        assert not _rule(a, action="ACCEPT").approved, fault.name


def test_forward_step_cell_count_matches_paper():
    assert forward_step_bundle(TUT)["diagnostics"]["expected_cells"] == 16128
    assert forward_step_bundle(TUT, nx=120, ny=40, mach=3.0)["diagnostics"]["expected_cells"] == 4032
    assert nozzle_bundle()["diagnostics"]["expected_cells"] == 2112
