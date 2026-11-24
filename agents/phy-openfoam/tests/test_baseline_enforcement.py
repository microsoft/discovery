"""Canonical baseline enforcement, using only in-memory contracts and evidence."""

from __future__ import annotations

import pytest

from discovery_physics.benchmarks.cases import forward_step_bundle
from discovery_physics.core.checks import assess
from discovery_physics.core.hashing import sha256_json
from discovery_physics.core.lint import ContractRejected, inject_baseline, lint
from discovery_physics.core.models import (
    Check,
    Contract,
    Diagnostics,
    Evidence,
    FieldSpec,
    Metric,
    Objective,
    Verdict,
)
from discovery_physics.openfoam.catalog import BASELINE, known_metrics

_KNOWN = known_metrics(Diagnostics(fields=[FieldSpec(name="U", components=3)], target_time=1.0))
_RATIONALE = "An independently worded rationale for the same mandatory predicate."


def _changed(check: Check, **updates) -> Check:
    return Check.model_validate({**check.model_dump(), **updates})


def _steps(check_id: str = "authored_steps") -> Check:
    return Check(id=check_id, metric="solver.steps", operator="ge", threshold=1,
                 category="execution", rationale="At least one solver step is required.")


def _contract(checks: list[Check] | None = None, *,
              objectives: list[Objective] | None = None) -> Contract:
    if checks is None:
        checks = [_steps()]
    if objectives is None:
        objectives = [Objective(id="requested", claim="custom", description="The author's objective.",
                                check_ids=[c.id for c in checks])]
    return Contract(id="baseline_regression", title="Baseline enforcement regression",
                    requested_prompt="Check mandatory baseline enforcement without running a solver.",
                    regime="transient", authority="frozen", checks=checks, objectives=objectives)


def _evidence(contract: Contract) -> Evidence:
    """Native-shaped assessment fixture only; no solver or evidence store is used."""
    metrics = {
        c.metric: Metric(value=True if c.operator == "true" else c.threshold,
                         unit=c.unit, source="in-memory baseline regression")
        for c in BASELINE
    }
    metrics["solver.steps"] = Metric(value=10, source="in-memory baseline regression")
    return Evidence(run_id="in_memory", origin="native", solver_invoked=True,
                    contract_sha256=sha256_json(contract), case_sha256="in_memory", metrics=metrics)


def _conflicting(check: Check, change: str) -> Check:
    expected = check.operator == "true" or check.threshold is True
    changes = {
        "inverted": {"operator": "eq", "threshold": not expected},
        # Python considers True == 1 and False == 0; baseline matching must not.
        "numeric_threshold": {"operator": "eq", "threshold": int(expected)},
        "string_threshold": {"operator": "eq", "threshold": str(expected)},
        "numeric_predicate": {"operator": "ge", "threshold": 0},
        "unit": {"unit": "s"},
        "category": {"category": "reference"},
        "failure": {"failure": "hard" if check.failure == "incomplete" else "incomplete"},
    }
    return _changed(check, **changes[change])


@pytest.mark.parametrize("canonical", BASELINE, ids=lambda c: c.id)
@pytest.mark.parametrize("use_alias", [False, True], ids=["reserved_id", "metric_alias"])
@pytest.mark.parametrize("change", [
    "inverted", "numeric_threshold", "string_threshold", "numeric_predicate",
    "unit", "category", "failure",
])
def test_incompatible_baseline_definitions_are_rejected(canonical, use_alias, change):
    candidate = _conflicting(canonical, change)
    if use_alias:
        candidate = _changed(candidate, id="authored_alias")
    contract = _contract([candidate])
    before = contract.model_dump()
    with pytest.raises(ContractRejected) as caught:
        inject_baseline(contract, BASELINE)
    message = str(caught.value)
    assert candidate.id in message and canonical.id in message and canonical.metric in message
    assert all(field in message for field in ("predicate", "unit", "category", "failure"))
    assert caught.value.errors
    assert contract.model_dump() == before


@pytest.mark.parametrize("canonical", BASELINE, ids=lambda c: c.id)
@pytest.mark.parametrize("bad_first", [False, True])
def test_compatible_check_does_not_hide_a_conflicting_alias(canonical, bad_first):
    bad = _changed(_conflicting(canonical, "inverted"), id="conflicting_alias")
    checks = [bad, canonical] if bad_first else [canonical, bad]
    with pytest.raises(ContractRejected, match="conflicting_alias"):
        inject_baseline(_contract(checks), BASELINE)


@pytest.mark.parametrize("canonical", BASELINE, ids=lambda c: c.id)
@pytest.mark.parametrize("include_good_alias", [False, True])
def test_reserved_id_cannot_be_reused_for_another_metric(canonical, include_good_alias):
    checks = [_steps(canonical.id)]
    if include_good_alias:
        checks.append(_changed(canonical, id="compatible_alias"))
    with pytest.raises(ContractRejected) as caught:
        inject_baseline(_contract(checks), BASELINE)
    assert canonical.id in str(caught.value) and canonical.metric in str(caught.value)


@pytest.mark.parametrize("canonical", BASELINE, ids=lambda c: c.id)
def test_reserved_id_and_baseline_metric_must_agree(canonical):
    other = BASELINE[(BASELINE.index(canonical) + 1) % len(BASELINE)]
    with pytest.raises(ContractRejected, match=other.id):
        inject_baseline(_contract([_changed(canonical, id=other.id)]), BASELINE)


@pytest.mark.parametrize("check_id", ["baseline_unknown", "baseline_solver_completd"])
def test_unknown_baseline_prefixed_check_ids_are_reserved(check_id):
    with pytest.raises(ContractRejected, match="reserved"):
        inject_baseline(_contract([_steps(check_id), *BASELINE]), BASELINE)


@pytest.mark.parametrize("use_aliases", [False, True])
@pytest.mark.parametrize("boolean_eq", [False, True])
def test_compatible_ids_rationales_and_boolean_predicates_survive(use_aliases, boolean_eq):
    checks = [_steps()]
    for index, canonical in enumerate(BASELINE):
        updates = {"rationale": _RATIONALE}
        if use_aliases:
            updates["id"] = f"authored_health_{index}"
        if boolean_eq and canonical.operator == "true":
            updates.update(operator="eq", threshold=True)
        checks.append(_changed(canonical, **updates))
    contract = _contract(checks)
    assert inject_baseline(contract, BASELINE) is contract
    assert len(contract.checks) == len(BASELINE) + 1
    assert lint(contract, _KNOWN)[0] == []


@pytest.mark.parametrize("canonical", BASELINE, ids=lambda c: c.id)
def test_partial_aliases_keep_their_ids_and_missing_baselines_are_injected(canonical):
    alias = _changed(canonical, id="authored_health", rationale=_RATIONALE)
    contract = _contract([_steps(), alias])
    before = contract.model_dump()
    injected = inject_baseline(contract, BASELINE)
    missing = [c for c in BASELINE if c.metric != canonical.metric]
    assert injected.checks == [*contract.checks, *missing]
    assert injected.objectives[0] == contract.objectives[0]
    assert injected.objectives[-1].id == "baseline_run_health"
    assert injected.objectives[-1].check_ids == [c.id for c in missing]
    assert contract.model_dump() == before
    assert lint(injected, _KNOWN)[0] == []
    restored = Contract.model_validate_json(injected.model_dump_json())
    assert inject_baseline(restored, BASELINE) is restored
    assert sha256_json(restored) == sha256_json(injected)


def test_missing_baselines_are_all_added_once_without_mutating_input():
    contract = _contract()
    before = contract.model_dump()
    injected = inject_baseline(contract, BASELINE)
    assert injected.checks == [*contract.checks, *BASELINE]
    assert injected.objectives[-1].check_ids == [c.id for c in BASELINE]
    assert inject_baseline(injected, BASELINE) is injected
    assert contract.model_dump() == before


def test_forward_step_benchmark_aliases_do_not_gain_duplicate_checks():
    tutorial = {name: "fixture dictionary" for name in (
        "system/fvSchemes", "system/fvSolution", "constant/physicalProperties",
        "constant/momentumTransport",
    )}
    contract = Contract.model_validate(forward_step_bundle(tutorial)["contract"])
    assert inject_baseline(contract, BASELINE) is contract


@pytest.mark.parametrize("already_complete", [False, True])
def test_reserved_health_objective_cannot_hide_an_authored_objective(already_complete):
    checks = [_steps(), *(BASELINE if already_complete else [])]
    objective = Objective(id="baseline_run_health", claim="custom",
                          description="An unrelated authored objective.", check_ids=[checks[0].id])
    with pytest.raises(ContractRejected, match="objective id 'baseline_run_health' is reserved"):
        inject_baseline(_contract(checks, objectives=[objective]), BASELINE)


@pytest.mark.parametrize("updates", [
    {"claim": "custom"},
    {"description": "A different purpose for the reserved objective."},
    {"check_ids": []},
    {"check_ids": ["authored_steps"]},
    {"check_ids": ["unregistered_check"]},
    {"check_ids": [BASELINE[0].id, BASELINE[0].id]},
], ids=["claim", "description", "empty", "unrelated", "unknown", "duplicate"])
def test_only_the_generated_objective_shape_can_be_reused(updates):
    injected = inject_baseline(_contract(), BASELINE)
    objective = Objective.model_validate({**injected.objectives[-1].model_dump(), **updates})
    altered = injected.model_copy(update={"objectives": [injected.objectives[0], objective]})
    with pytest.raises(ContractRejected, match="objective id 'baseline_run_health' is reserved"):
        inject_baseline(altered, BASELINE)


def test_unrelated_stricter_checks_are_retained_and_enforced():
    stricter = _changed(_steps("more_steps"), threshold=20, rationale="Require more solver steps.")
    contract = inject_baseline(_contract([_steps(), stricter]), BASELINE)
    assert contract.checks[1] == stricter
    assert lint(contract, _KNOWN)[0] == []
    assert assess(contract, _evidence(contract)).verdict == Verdict.REJECT


def test_unrelated_failure_policy_is_not_rewritten_or_exempted_from_lint():
    invalid = _changed(_steps(), failure="incomplete")
    contract = inject_baseline(_contract([invalid]), BASELINE)
    assert contract.checks[0] == invalid
    assert any("only horizon/stationarity" in error for error in lint(contract, _KNOWN)[0])


def test_healthy_baselines_can_accept():
    contract = inject_baseline(_contract(), BASELINE)
    result = assess(contract, _evidence(contract))
    assert result.verdict == Verdict.ACCEPT and not result.unresolved


@pytest.mark.parametrize("canonical", BASELINE, ids=lambda c: c.id)
def test_baseline_hard_and_incomplete_failure_semantics_are_unchanged(canonical):
    contract = inject_baseline(_contract(), BASELINE)
    evidence = _evidence(contract)
    evidence.metrics[canonical.metric].value = not evidence.metrics[canonical.metric].value
    result = assess(contract, evidence)
    expected = Verdict.CORRECT_AND_RERUN if canonical.failure == "incomplete" else Verdict.REJECT
    assert result.verdict == expected and not result.live_acceptance
    failed = next(check for check in result.checks if check.id == canonical.id)
    assert failed.state == "FAIL" and failed.failure == canonical.failure


@pytest.mark.parametrize("canonical", BASELINE, ids=lambda c: c.id)
@pytest.mark.parametrize("problem", ["absent", "invalid", "unit", "type"])
def test_missing_or_malformed_baseline_evidence_is_still_unknown(canonical, problem):
    contract = inject_baseline(_contract(), BASELINE)
    evidence = _evidence(contract)
    if problem == "absent":
        del evidence.metrics[canonical.metric]
    elif problem == "invalid":
        evidence.metrics[canonical.metric].status = "invalid"
    elif problem == "unit":
        evidence.metrics[canonical.metric].unit = "s"
    else:
        evidence.metrics[canonical.metric].value = int(evidence.metrics[canonical.metric].value)
    result = assess(contract, evidence)
    assert result.verdict == Verdict.INCONCLUSIVE and not result.live_acceptance
    assert next(check for check in result.checks if check.id == canonical.id).state == "UNKNOWN"


@pytest.mark.parametrize("check_ids", [[], ["unregistered_check"]], ids=["uncovered", "unresolved"])
def test_injection_does_not_resolve_an_uncovered_or_unknown_authored_objective(check_ids):
    objective = Objective(id="requested", claim="custom", description="An unresolved user objective.",
                          check_ids=check_ids)
    contract = inject_baseline(_contract(objectives=[objective]), BASELINE)
    assert contract.objectives[0] == objective
    errors, warnings = lint(contract, _KNOWN)
    assert any("objective 'requested'" in message for message in [*errors, *warnings])
    result = assess(contract, _evidence(contract))
    assert result.verdict == Verdict.INCONCLUSIVE and not result.live_acceptance
    assert any("objective 'requested'" in message for message in result.unresolved)


@pytest.mark.parametrize("health", ["healthy", "failed", "missing"])
def test_hard_failure_and_unknown_precedence_over_incomplete_is_unchanged(health):
    contract = inject_baseline(_contract(), BASELINE)
    evidence = _evidence(contract)
    evidence.metrics["solver.reached_target_time"].value = False
    if health == "failed":
        evidence.metrics["fields.finite_all_saved"].value = False
    elif health == "missing":
        del evidence.metrics["fields.finite_all_saved"]
    expected = {"healthy": Verdict.CORRECT_AND_RERUN, "failed": Verdict.REJECT,
                "missing": Verdict.INCONCLUSIVE}
    assert assess(contract, evidence).verdict == expected[health]


@pytest.mark.parametrize("target_reached", [False, True])
def test_unknown_development_check_keeps_existing_short_horizon_semantics(target_reached):
    window = Check(id="window", metric="solver.final_time", operator="ge", threshold=2,
                   category="stationarity", failure="incomplete",
                   rationale="A separate development window must be available.")
    contract = inject_baseline(_contract([_steps(), window]), BASELINE)
    assert lint(contract, _KNOWN)[0] == []
    evidence = _evidence(contract)
    evidence.metrics["solver.reached_target_time"].value = target_reached
    expected = Verdict.INCONCLUSIVE if target_reached else Verdict.CORRECT_AND_RERUN
    assert assess(contract, evidence).verdict == expected