#!/usr/bin/env python3
"""metric_classes.py -- the metric-class contract for chip tool envelopes.

WHY THIS EXISTS
---------------
An envelope reports many numbers, and until now they were undifferentiated. That
conflation caused two distinct, repeatedly-observed failures:

  1. A number that could NOT be measured was emitted as a confident value (or as
     a bare 0), and a gate closed on it. The 2026-09-02 `_as_number` defect is the
     canonical case: a DENOMINATOR was read as a measurement, so a fully-covered
     metric reported a 96-point gap -- and reported the SAME 96.0 at 0% and 100%
     coverage, which read downstream as a CONVERGED metric rather than a broken
     one. A wrong-but-plausible number is worse than a missing one, because
     nothing rejects it.

  2. Context that was never expected to change (a mode, a file count) sat in the
     same namespace as the gate, so a constant that plateaued was indistinguishable
     from a stalled gate. That ambiguity is what forced the name-based
     `_VIOLATION_HINTS` heuristic elsewhere in the framework.

So every reported quantity declares WHAT KIND OF CLAIM IT IS:

  gating         -- deterministic, parsed from tool output, FAIL-CLOSED. This and
                    only this may close or block a gate. `None` means NOT
                    ASSESSED and must never be read as zero.
  diagnostic     -- measured, non-gating. The debug surface: names, locations,
                    counterexamples. Safe to be incomplete.
  descriptive    -- configuration/context expected to hold steady (mode, depth,
                    input counts). NOT a progress signal; a flat value here is
                    normal, not a stall.
  model_authored -- an LLM's reading of the run. ADVISORY ONLY. Never a gate.

THE LOAD-BEARING RULE
---------------------
*** A MODEL-AUTHORED VALUE MAY NEVER BE THE BASIS OF A GATING METRIC. ***
Not because models are unreliable in general, but because the failure modes
INVERT. A broken parser fails LOUDLY-NULL and validators catch the absence. A
model asked "how many properties failed?" WILL ANSWER A NUMBER EVEN WHEN IT
CANNOT TELL. A plausible-but-wrong count entering a gate is exactly the failure
class above, re-introduced from the other direction.

Where a model also states a quantity the parser measures, the two are
CROSS-CHECKED and any disagreement is RECORDED, never auto-resolved: the two
causes (a stale parser vs. a confabulated count) need opposite fixes, so
picking a winner automatically would be guessing.

This module is deliberately dependency-free and side-effect-free so it can be
used by validators, tests, and tools alike.
"""

SCHEMA = "metric-classes/1"

GATING = "gating"
DIAGNOSTIC = "diagnostic"
DESCRIPTIVE = "descriptive"
MODEL_AUTHORED = "model_authored"

CLASSES = (GATING, DIAGNOSTIC, DESCRIPTIVE, MODEL_AUTHORED)

# Only these may close or block a gate.
CLOSING_CLASSES = (GATING,)

# A `basis` string that indicates a human/model narrated the value rather than a
# tool emitting it. Matched as a substring, case-insensitively.
MODEL_AUTHORED_BASIS_MARKERS = (
    "agent_", "model_", "llm", "narrat", "inferred_by", "assert_by_caller",
    "caller_asserted", "self_reported",
)

# Stages that have ADOPTED the contract. Kept explicit so adoption is a tracked,
# reviewable fact rather than something inferred from whatever a tool happens to
# emit -- and so a stage cannot silently DROP the contract once it has one.
ADOPTED_STAGES = (
    "formal",
    "codecov",
    "sta",
    "lec",
    "rtl",
    "lint",
    "assertions",
    "cdc",
    "funccov",
    "funcverif",
    "spec",
    "synthesis",
    "constraints",
    "testbench",
)


def is_model_authored_basis(basis):
    """True when `basis` claims a model/caller produced the value."""
    if not isinstance(basis, str):
        return False
    low = basis.lower()
    return any(m in low for m in MODEL_AUTHORED_BASIS_MARKERS)


def label_interpretation(interp, basis=None):
    """Return the model-authored block with its class/basis label guaranteed.

    Exists because the obvious idiom is WRONG:

        params.get("interpretation") or {"class": ..., "basis": "not_provided"}

    That labels the block only when the agent supplied NOTHING -- so the one case
    that actually needs the label, a real model-authored reading, ships unlabelled
    and reads as an unclassified quantity. Observed on a live formal run
    2026-09-02 and caught by `check_metric_classes`.

    A caller-supplied `basis` is preserved: the agent may know more precisely
    what produced its reading than the tool does.
    """
    if not isinstance(interp, dict) or not interp:
        return {
            "class": MODEL_AUTHORED,
            "basis": "not_provided",
            "note": ("optional agent interpretation; ADVISORY ONLY -- never "
                     "gating, never the source of a count"),
        }
    out = dict(interp)
    out.setdefault("basis", basis or "agent_authored")
    out["class"] = MODEL_AUTHORED       # never caller-overridable
    return out


def crosscheck_interpretation(interp, measured, key):
    """Compare a model-authored count against the deterministically measured one.

    Returns a RECORD, never a decision. A disagreement is SURFACED, not resolved:
    either the tool-side measurement has gone stale against a new engine version
    (this repo has hit that in chip-logic-synthesis, chip-sta and chip-lec) or the
    model has confabulated a plausible number. Those need OPPOSITE fixes, so an
    automatic tie-break would be guessing.

    ``key`` is the field the model uses for its count, which differs per stage
    (`failing_properties` for formal, `reachable_unhit` for coverage).

    NOTE the deliberate asymmetry when the tool measured nothing: the model's
    number is NOT promoted to fill the gap. An unmeasured gate must stay
    unmeasured -- filling it with a narrated value is precisely the laundering
    the class contract exists to prevent.
    """
    if not isinstance(interp, dict):
        return {"checked": False, "reason": "no model interpretation supplied"}
    claimed = interp.get(key)
    if claimed is None:
        return {"checked": False, "reason": "model offered no count to cross-check"}
    try:
        claimed_i = int(claimed)
    except (TypeError, ValueError):
        return {"checked": False, "reason": "model count is not an integer"}
    if measured is None:
        return {"checked": False, "measured": None, "model": claimed_i,
                "reason": "tool did not assess a count; nothing to compare "
                          "(the model claim is NOT promoted to fill the gap)"}
    agree = (claimed_i == measured)
    return {"checked": True, "measured": measured, "model": claimed_i,
            "agree": agree,
            "note": None if agree else
            "DISAGREEMENT: the deterministic measurement governs. Investigate "
            "BOTH possibilities -- a stale tool-side measurement (engine drift) "
            "or a confabulated model count. Do NOT auto-resolve."}


def declares_any_class(envelope):
    """True if the envelope labels ANY quantity with a metric class.

    `check_metric_classes` only validates blocks that DECLARE a class, so an
    envelope from an adopted stage that labels NOTHING passes it trivially. That
    is the "mandatory convention nothing verifies" trap, so the absence is made
    detectable here rather than left implicit.

    Kept SEPARATE from the violation check because a run can legitimately declare
    no gating metric -- an instrumentation-only coverage run measures nothing and
    has nothing to gate. So this is a signal for a report to weigh, not a
    violation on its own.
    """
    if not isinstance(envelope, dict):
        return False
    for key in ("results", "signoff_evidence", "signoff"):
        block = envelope.get(key)
        if not isinstance(block, dict):
            continue
        for val in block.values():
            if isinstance(val, dict) and val.get("class") in CLASSES:
                return True
    return False


def check_metric_classes(envelope):
    """Return a list of contract violations for one envelope. Never raises.

    An empty list means the envelope is consistent with the contract. This does
    NOT judge whether the numbers are correct -- only whether each claim is
    labelled honestly and whether anything unlabelled is being used as a gate.
    """
    problems = []
    if not isinstance(envelope, dict):
        return ["envelope is not an object"]

    results = envelope.get("results")
    results = results if isinstance(results, dict) else {}
    signoff = (envelope.get("signoff_evidence")
               or envelope.get("signoff") or {})
    signoff = signoff if isinstance(signoff, dict) else {}

    def _classed(block, where):
        for name, val in block.items():
            if not isinstance(val, dict) or "class" not in val:
                continue
            yield where, name, val

    for where, name, val in list(_classed(results, "results")) + \
            list(_classed(signoff, "signoff")):
        cls = val.get("class")
        if cls not in CLASSES:
            problems.append(
                "%s.%s declares unknown class %r (expected one of %s)"
                % (where, name, cls, "|".join(CLASSES)))
            continue

        if cls == GATING:
            basis = val.get("basis")
            if not basis:
                problems.append(
                    "%s.%s is class=gating but declares no `basis` -- a gating "
                    "metric must say what produced it" % (where, name))
            elif is_model_authored_basis(basis):
                problems.append(
                    "%s.%s is class=gating with a model-authored basis %r -- a "
                    "narrated value must never close or block a gate"
                    % (where, name, basis))
            # A gating metric living in the signoff/advisory surface is a
            # mislabel: gates belong in `results`, where consumers look.
            if where == "signoff":
                problems.append(
                    "signoff.%s is class=gating but sits in the advisory "
                    "surface -- gating metrics belong in `results`" % name)

        if cls == MODEL_AUTHORED and where == "results":
            problems.append(
                "results.%s is class=model_authored but sits in the gating "
                "surface -- advisory values belong in signoff evidence" % name)

    # If a model stated a quantity, the disagreement record must exist. Its
    # ABSENCE is the dangerous state: it means nobody compared the narrated
    # number to the measured one.
    interp = signoff.get("interpretation")
    if isinstance(interp, dict):
        numeric = [k for k, v in interp.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if numeric and not isinstance(signoff.get("interpretation_crosscheck"),
                                      dict):
            problems.append(
                "signoff.interpretation states %s but there is no "
                "`interpretation_crosscheck` -- a narrated quantity must be "
                "compared against the measured one"
                % ", ".join(sorted(numeric)))
        if not interp.get("basis"):
            problems.append(
                "signoff.interpretation declares no `basis` -- an advisory "
                "reading must record who/what produced it")

    xc = signoff.get("interpretation_crosscheck")
    if isinstance(xc, dict) and xc.get("checked") and not xc.get("agree"):
        if not xc.get("note"):
            problems.append(
                "signoff.interpretation_crosscheck records a DISAGREEMENT with "
                "no `note` -- the divergence must be explained, not silently "
                "carried")

    return problems
