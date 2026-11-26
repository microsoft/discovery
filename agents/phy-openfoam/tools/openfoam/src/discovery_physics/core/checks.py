"""Deterministic acceptance. A model may propose; only this module decides.

Every check fails closed: missing, invalid, non-finite, or wrongly typed evidence
is UNKNOWN, never PASS. Objectives without checks cannot be accepted.
"""

from __future__ import annotations

import math

from .hashing import sha256_json
from .models import Assessment, Check, CheckResult, Contract, Evidence, Verdict

_NUMERIC = {"lt", "le", "gt", "ge", "between"}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def evaluate_check(check: Check, evidence: Evidence) -> CheckResult:
    base = dict(id=check.id, metric=check.metric, unit=check.unit, threshold=check.threshold,
                category=check.category, failure=check.failure)
    metric = evidence.metrics.get(check.metric)
    if metric is None:
        return CheckResult(state="UNKNOWN", reason="metric absent from evidence", **base)
    if metric.status != "measured" or metric.value is None:
        return CheckResult(state="UNKNOWN", value=None, reason=f"metric {metric.status}", **base)
    if metric.unit != check.unit:
        return CheckResult(state="UNKNOWN", value=metric.value,
                           reason=f"unit mismatch: evidence {metric.unit!r}, contract {check.unit!r}", **base)
    value = metric.value
    if check.operator == "true":
        if not isinstance(value, bool):
            return CheckResult(state="UNKNOWN", value=value, reason="boolean evidence required", **base)
        ok = value
    elif check.operator == "eq":
        if isinstance(value, bool) != isinstance(check.threshold, bool):
            return CheckResult(state="UNKNOWN", value=value, reason="type mismatch", **base)
        ok = value == check.threshold
    else:
        x = _number(value)
        if x is None:
            return CheckResult(state="UNKNOWN", value=value if not isinstance(value, float) else None,
                               reason="finite numeric evidence required", **base)
        t = check.threshold
        ok = {
            "lt": lambda: x < t, "le": lambda: x <= t, "gt": lambda: x > t, "ge": lambda: x >= t,
            "between": lambda: t[0] < x < t[1],
        }[check.operator]()
    return CheckResult(state="PASS" if ok else "FAIL", value=value,
                       reason="criterion satisfied" if ok else "criterion violated", **base)


def assess(contract: Contract, evidence: Evidence) -> Assessment:
    """Return a verdict whose precedence is hard failure > unknown > incomplete > accept."""
    contract_hash = sha256_json(contract)
    unresolved: list[str] = []
    if evidence.contract_sha256 != contract_hash:
        unresolved.append("evidence was produced under a different contract")
    if evidence.origin != "native" or not evidence.solver_invoked:
        unresolved.append(f"evidence origin '{evidence.origin}' cannot support live acceptance")
    unresolved.extend(f"extraction error: {e}" for e in evidence.errors)

    results = [evaluate_check(c, evidence) for c in contract.checks]
    by_id = {r.id: r for r in results}
    for objective in contract.objectives:
        if not objective.check_ids:
            unresolved.append(f"objective '{objective.id}' has no registered check")
        for cid in objective.check_ids:
            if cid not in by_id:
                unresolved.append(f"objective '{objective.id}' references unknown check '{cid}'")
    if contract.authority == "proposed":
        unresolved.append("contract was not approved before execution")

    hard_fail = [r for r in results if r.state == "FAIL" and r.failure == "hard"]
    incomplete = [r for r in results if r.state == "FAIL" and r.failure == "incomplete"]
    # A development check (e.g. a stationarity window) may be unmeasurable only because the run is
    # still short of its horizon; that is incompleteness, not missing evidence. Hard checks never are.
    horizon_short = any(r.category == "horizon" and r.state == "FAIL" for r in incomplete)
    unknown = [r for r in results if r.state == "UNKNOWN"
               and not (horizon_short and r.failure == "incomplete")]

    if hard_fail:
        verdict = Verdict.REJECT
    elif unknown or unresolved:
        verdict = Verdict.INCONCLUSIVE
    elif incomplete:
        verdict = Verdict.CORRECT_AND_RERUN
    else:
        verdict = Verdict.ACCEPT
    live = verdict == Verdict.ACCEPT and evidence.origin == "native" and evidence.solver_invoked
    return Assessment(
        run_id=evidence.run_id, verdict=verdict, evidence_origin=evidence.origin,
        solver_invoked=evidence.solver_invoked, live_acceptance=live, contract_sha256=contract_hash,
        checks=results, unresolved=unresolved, limitations=list(contract.limitations),
    )
