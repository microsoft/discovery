"""Contract linter: refuse criteria that cannot honestly support their claim.

Runs at freeze time, before any solver executes. Errors block preparation;
warnings are recorded with the run and surfaced in the report.
"""

from __future__ import annotations

import re

from .models import Check, Contract, Objective

# Objective claim -> check categories at least one of which must back it.
CLAIM_CATEGORIES: dict[str, set[str]] = {
    "numerical_health": {"execution", "admissibility", "mesh"},
    "conservation": {"conservation"},
    "stationarity": {"stationarity"},
    "reference_agreement": {"reference"},
    "physical_validation": {"validation"},
    "mesh_independence": {"discretization"},
}
INCOMPLETE_CATEGORIES = {"horizon", "stationarity"}
QUANTITATIVE = {"reference", "validation", "discretization"}
_EXTREME = re.compile(r"^fields\.[^.]+\.final_(min|max)$")
_BASELINE_OBJECTIVE_ID = "baseline_run_health"
_BASELINE_OBJECTIVE_DESCRIPTION = "Mandatory run-health checks applied to every contract."


class ContractRejected(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _baseline_semantics(check: Check) -> tuple[object, ...]:
    """Ignore author labels, but never equate a boolean threshold with a number."""
    operator, threshold = check.operator, check.threshold
    if operator == "true" and threshold is None:
        operator, threshold = "eq", True
    return (check.metric, operator, type(threshold), threshold,
            check.unit, check.category, check.failure)


def inject_baseline(contract: Contract, baseline: list[Check]) -> Contract:
    """Verify mandatory definitions by ID and metric, then add any missing checks.

    Compatible metric aliases retain their IDs and rationales. Every definition
    on a baseline metric must agree, even when another compatible check exists.
    """
    by_id = {c.id: c for c in baseline}
    by_metric = {c.metric: c for c in baseline}
    satisfied: set[str] = set()
    errors: list[str] = []
    for check in contract.checks:
        canonical = by_id.get(check.id)
        if canonical is None and check.id.startswith("baseline_"):
            errors.append(f"check id '{check.id}' is reserved: unknown mandatory baseline ID")
            continue
        if canonical is None:
            canonical = by_metric.get(check.metric)
        if canonical is None:
            continue
        if _baseline_semantics(check) != _baseline_semantics(canonical):
            errors.append(
                f"check '{check.id}' on metric '{check.metric}' conflicts with mandatory baseline "
                f"'{canonical.id}': expected metric '{canonical.metric}', "
                f"predicate '{canonical.operator}' with threshold {canonical.threshold!r}, "
                f"unit '{canonical.unit}', category '{canonical.category}', "
                f"failure '{canonical.failure}'")
        else:
            satisfied.add(canonical.id)

    extra = [c for c in baseline if c.id not in satisfied]
    ids = {c.id for c in contract.checks}
    for objective in contract.objectives:
        if objective.id != _BASELINE_OBJECTIVE_ID:
            continue
        # A previous injection is recognizable after serialization without a
        # hidden marker. An unrelated objective cannot occupy this namespace.
        if (extra or objective.claim != "numerical_health"
                or objective.description != _BASELINE_OBJECTIVE_DESCRIPTION
                or not objective.check_ids
                or len(objective.check_ids) != len(set(objective.check_ids))
                or not set(objective.check_ids).issubset(by_id.keys() & ids)):
            errors.append(f"objective id '{_BASELINE_OBJECTIVE_ID}' is reserved")
    if errors:
        raise ContractRejected(errors)
    if not extra:
        return contract
    objective = Objective(id=_BASELINE_OBJECTIVE_ID, claim="numerical_health",
                          description=_BASELINE_OBJECTIVE_DESCRIPTION,
                          check_ids=[c.id for c in extra])
    objectives = list(contract.objectives)
    return contract.model_copy(update={"checks": [*contract.checks, *extra], "objectives": [*objectives, objective]})


def lint(contract: Contract, known: dict[str, tuple[str, str]], *, study_member: bool = False) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). ``known`` maps metric -> (bool|number, unit)."""
    errors: list[str] = []
    warnings: list[str] = []
    checks = {c.id: c for c in contract.checks}
    for c in contract.checks:
        spec = known.get(c.metric)
        if spec is None:
            errors.append(f"check '{c.id}': metric '{c.metric}' is not produced for this case "
                          "(declare it as a quantity/derived metric or fix the name)")
            continue
        kind, unit = spec
        if unit != c.unit:
            errors.append(f"check '{c.id}': unit '{c.unit}' differs from the metric's unit '{unit}'")
        if kind == "bool" and c.operator not in ("true", "eq"):
            errors.append(f"check '{c.id}': '{c.metric}' is boolean; use operator 'true' or 'eq'")
        if kind == "number" and c.operator == "true":
            errors.append(f"check '{c.id}': '{c.metric}' is numeric; 'true' needs a boolean metric")
        if kind == "bool" and c.operator == "eq" and not isinstance(c.threshold, bool):
            errors.append(f"check '{c.id}': boolean metric compared with a non-boolean threshold")
        if c.failure == "incomplete" and c.category not in INCOMPLETE_CATEGORIES:
            errors.append(f"check '{c.id}': only horizon/stationarity checks may be 'incomplete'")
        if c.category in QUANTITATIVE and _EXTREME.match(c.metric):
            errors.append(f"check '{c.id}': a single-cell extreme ('{c.metric}') is not an engineering "
                          "quantity; declare a quantity (e.g. surfaceFieldValue areaAverage) instead")
    for o in contract.objectives:
        if not o.check_ids:
            # Fail-closed at assessment: an uncovered objective forces INCONCLUSIVE, never ACCEPT.
            warnings.append(f"objective '{o.id}' has no checks; the verdict will be INCONCLUSIVE")
            continue
        missing = [cid for cid in o.check_ids if cid not in checks]
        if missing:
            errors.append(f"objective '{o.id}' references unknown checks {missing}")
        need = CLAIM_CATEGORIES.get(o.claim)
        cats = {checks[cid].category for cid in o.check_ids if cid in checks}
        if need and not cats & need:
            errors.append(f"objective '{o.id}' claims '{o.claim}' but has no {sorted(need)} check")
        if o.claim == "mesh_independence":
            errors.append(f"objective '{o.id}': mesh independence is established by a study gci criterion "
                          "(discovery-physics study-prepare), not by a single run's contract")
        if o.claim == "quantity" and not any(checks[cid].metric.startswith(("quantity.", "derived."))
                                             for cid in o.check_ids if cid in checks):
            warnings.append(f"objective '{o.id}' claims a quantity but checks no quantity/derived metric")
    if any(c.category in ("reference", "validation") for c in contract.checks) and \
            contract.reference.strip() == "No external validation claimed.":
        errors.append("reference/validation checks require the contract 'reference' to cite their source")
    if contract.regime == "steady" and not any(c.category == "stationarity" for c in contract.checks):
        warnings.append("steady regime without a stationarity/convergence check")
    if not any(c.category == "horizon" for c in contract.checks):
        warnings.append("no horizon check: an early stop could be judged as a finished run")
    used = {c.metric for c in contract.checks}
    for name in sorted(k for k in known if k.startswith(("quantity.", "derived.")) and k not in used):
        warnings.append(f"declared output '{name}' is reported but not checked")
    return errors, warnings
