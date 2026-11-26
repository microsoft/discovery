"""The action gate rules on model proposals; it never relaxes a frozen criterion."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .models import Assessment, Record, Verdict

Action = Literal[
    "ACCEPT", "CONTINUE_RUN", "REFINE_MESH", "REDUCE_MAX_CO", "REBUILD_CASE",
    "FAIL_SAFELY", "REQUEST_CLARIFICATION", "REJECT_UNSUPPORTED",
]
STOPS = {"FAIL_SAFELY", "REQUEST_CLARIFICATION", "REJECT_UNSUPPORTED"}
NUMERICAL = {"execution", "admissibility"}


class Proposal(Record):
    action: Action
    rationale: str = Field(min_length=10, max_length=4000)
    diagnosis: str = Field(default="UNSPECIFIED", max_length=64)
    end_time: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    refinement_factor: float | None = Field(default=None, gt=1, le=2, allow_inf_nan=False)
    evidence_cited: list[str] = Field(default_factory=list, max_length=64)


class Ruling(Record):
    approved: bool
    reasons: list[str]
    terminal_verdict: Annotated[Verdict | None, Field(strict=False)] = None


def rule(assessment: Assessment, proposal: Proposal, *, attempts_used: int, max_attempts: int,
         final_time: float | None, max_end_time: float, cells: int | None, max_cells: int,
         dimensions: int, known_evidence: set[str]) -> Ruling:
    """Approve or refuse one proposal; return the terminal verdict when the session stops."""
    v = assessment.verdict
    by = {c.id: c for c in assessment.checks}
    hard = [c for c in assessment.checks if c.state == "FAIL" and c.failure == "hard"]
    incomplete = [c for c in assessment.checks if c.state == "FAIL" and c.failure == "incomplete"]
    unknown_ids = {c for c in proposal.evidence_cited if c not in by and c not in known_evidence}
    reasons: list[str] = []
    if unknown_ids:
        reasons.append(f"cited evidence does not exist: {sorted(unknown_ids)}")
    remaining = attempts_used < max_attempts
    a = proposal.action

    if a == "ACCEPT":
        if v != Verdict.ACCEPT:
            reasons.append(f"scientific verdict is {v.value}; ACCEPT requires every registered check "
                           "to pass and every objective to be covered")
        return Ruling(approved=not reasons, reasons=reasons or ["consistent with deterministic verdict"],
                      terminal_verdict=Verdict.ACCEPT if not reasons else Verdict.INCONCLUSIVE)
    if a in STOPS:
        if v == Verdict.ACCEPT:
            terminal = Verdict.INCONCLUSIVE  # a healthy, accepted result was declined, not rejected
        elif v == Verdict.CORRECT_AND_RERUN:
            terminal = Verdict.INCONCLUSIVE if remaining else Verdict.REJECT
        else:
            terminal = v
        return Ruling(approved=True, reasons=["stopping is always permitted"], terminal_verdict=terminal)
    if not remaining:
        reasons.append(f"attempt budget exhausted ({attempts_used}/{max_attempts})")
    if a == "CONTINUE_RUN":
        if hard:
            reasons.append("hard failures cannot be fixed by more physical time: "
                           + ", ".join(c.id for c in hard))
        if v != Verdict.CORRECT_AND_RERUN or not incomplete:
            reasons.append("no failing development/horizon check to correct")
        if proposal.end_time is None:
            reasons.append("end_time is required")
        elif final_time is not None and proposal.end_time <= final_time:
            reasons.append(f"end_time {proposal.end_time} does not advance past {final_time}")
        elif proposal.end_time > max_end_time * (1 + 1e-12):
            reasons.append(f"end_time {proposal.end_time} exceeds frozen limit {max_end_time}")
    elif a == "REFINE_MESH":
        if hard:
            reasons.append("refinement requires a healthy current solution")
        f = proposal.refinement_factor
        if f is None:
            reasons.append("refinement_factor is required")
        elif cells is not None and cells * f ** dimensions > max_cells:
            reasons.append(f"refined mesh would exceed {max_cells} cells")
    elif a == "REDUCE_MAX_CO":
        if not any(c.category in NUMERICAL for c in hard):
            reasons.append("time-step reduction is justified only by a numerical/admissibility failure")
    elif a == "REBUILD_CASE":
        if not hard and v != Verdict.INCONCLUSIVE:
            reasons.append("rebuild requires a setup defect or unresolved evidence")
    approved = not reasons
    return Ruling(approved=approved, reasons=reasons or ["within frozen correction policy"])
