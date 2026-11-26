"""Deterministic STA violating-path clustering, dominance ranking and
perturbation scoring for the signoff ECO stage.

This module is PURE ANALYSIS: it parses OpenSTA ``report_checks`` text, groups
violating paths by shared structure, and scores candidate fix sites. It never
edits a netlist, never invokes a tool, and has no third-party dependencies, so
it is testable standalone against captured STA reports.

The reasoning agent consumes this output to choose a fix set, a batch breadth
(``repair_timing -repair_tns``) and a transform-aggression level. The split is
deliberate: everything here is reproducible graph work, and everything the
agent decides is judgement that graph work cannot settle.

Key ideas
---------
dominance
    How many violating paths run through a given instance. A high-dominance
    instance is the "one fix resolves many violations" case.

perturbation
    How much collateral a fix at that instance risks. Measured from the
    *currently-passing* paths through the same instance and how close to zero
    their slack already is.

leverage
    ``dominance / (1 + perturbation)`` -- fix many, break few. This is the
    ranking the agent should read first.

concentration
    What fraction of all violating paths the top-N instances cover. This is the
    PRIMARY entry discriminator: a clustered 300-violation design is a better
    ECO candidate than a diffuse 30-violation one.

frozen
    An instance the ECO is FORBIDDEN to modify -- typically inside a hardened
    macro, the pad/IO ring, or vendor hard IP whose signoff evidence closed
    independently of this run.

    This matters because a **timing-transparent** hierarchical flow (one where
    the top level reads each macro's routed netlist + SPEF because no Liberty
    abstraction exists) puts macro-INTERNAL instances directly into the
    top-level timing report. Left unmarked, a hot instance inside a macro ranks
    as the highest-leverage fix in the design -- and it is precisely the one
    edit that would silently invalidate that macro's own closed signoff.

    Frozen candidates are SEPARATED, never silently dropped: an unfixable
    dominant cluster is exactly the evidence that says "escalate to that
    macro's own flow", so it has to stay visible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict

# --- Provisional entry-gate thresholds -------------------------------------
# These are priors from general practice, NOT calibrated against this flow,
# sky130, or these designs. They are deliberately CONSERVATIVE because the cost
# is asymmetric: a wrongly-rejected ECO costs one rung-2 reopen, while a
# wrongly-accepted ECO burns the whole wave budget AND THEN costs the reopen.
# Recalibrate from real converged/plateaued outcomes and drop the "provisional"
# marker only once there is evidence behind each number.
DEFAULT_THRESHOLDS = {
    # Hard-reject screen: above these, skip cluster analysis entirely and
    # escalate straight to a rung-2 reopen.
    "hard_reject_endpoint_fraction": 0.10,
    "hard_reject_wns_fraction_of_period": 0.20,
    # A violating path with no fixable instance is unrepairable AT THIS LEVEL,
    # so past this fraction the wave budget cannot close the gate no matter how
    # it is spent. Deliberately strict: unlike the bands below, this is not a
    # judgement about difficulty, it is an arithmetic fact about reachability.
    "hard_reject_no_fixable_fraction": 0.50,
    # Advisory bands used to annotate the assessment for the agent.
    "endpoint_fraction_comfortable": 0.01,
    "endpoint_fraction_marginal": 0.05,
    "wns_fraction_comfortable": 0.05,
    "wns_fraction_marginal": 0.15,
    # A collateral path counts as "at risk" when its slack is below this
    # fraction of the clock period. Falls back to an absolute value in ns when
    # no clock period is supplied.
    "at_risk_slack_fraction_of_period": 0.05,
    "at_risk_slack_abs_ns": 0.10,
    # How many top instances define the concentration ratio.
    "concentration_top_n": 5,
    "provisional": True,
}

_RE_STARTPOINT = re.compile(r"^\s*Startpoint:\s*(\S+)(.*)$")
_RE_ENDPOINT = re.compile(r"^\s*Endpoint:\s*(\S+)(.*)$")
_RE_PATH_GROUP = re.compile(r"^\s*Path Group:\s*(\S+)")
_RE_PATH_TYPE = re.compile(r"^\s*Path Type:\s*(\S+)")
_RE_CLOCKED_BY = re.compile(r"clocked by\s+([^\s)]+)")
_RE_SLACK = re.compile(r"^\s*(-?[\d.]+)\s+slack\s+\((MET|VIOLATED)\)")
# A timing-arc row, e.g.
#     0.29    0.53 v u_core/u_alu/_123_/Y (sky130_fd_sc_hd__nand2_1)
# The pin must be hierarchical (contain '/') so clock-network prose rows and
# "data arrival time" summary rows are not mistaken for cell arcs.
_RE_STAGE = re.compile(
    r"^\s*-?[\d.]+\s+-?[\d.]+\s+[\^v]?\s*(\S*/\S+)\s+\(([^)]+)\)\s*$"
)


def _instance_of(pin):
    """``u_core/u_alu/_123_/Y`` -> ``u_core/u_alu/_123_``."""
    return pin.rsplit("/", 1)[0] if "/" in pin else pin


def _frozen_by(instance, frozen_prefixes):
    """Return the frozen scope owning *instance*, or None.

    A prefix matches on a HIERARCHY BOUNDARY only: ``u_crc16`` matches
    ``u_crc16/_hot_`` but not ``u_crc16_shim/_g_``. Matching on a bare string
    prefix would freeze unrelated sibling logic whose name merely starts the
    same way, which would silently shrink the fixable set.
    """
    for pref in frozen_prefixes or ():
        p = str(pref).rstrip("/")
        if instance == p or instance.startswith(p + "/"):
            return p
    return None


def parse_report_checks(text):
    """Parse OpenSTA ``report_checks`` output into structured path records.

    Returns a list of dicts with ``startpoint``, ``endpoint``, ``path_group``,
    ``path_type`` (``max`` for setup / ``min`` for hold), ``launch_clock``,
    ``slack``, ``violated`` and ``stages`` (ordered instance/cell records).

    Unparseable or truncated blocks are skipped rather than guessed at -- a
    path with no slack line never becomes a silent zero.
    """
    paths = []
    cur = None

    for line in text.splitlines():
        m = _RE_STARTPOINT.match(line)
        if m:
            # A new Startpoint abandons any block that never reached a slack
            # line (truncated report); we do not emit partial paths.
            clk = _RE_CLOCKED_BY.search(m.group(2) or "")
            cur = {
                "startpoint": m.group(1),
                "endpoint": None,
                "path_group": None,
                "path_type": None,
                "launch_clock": clk.group(1) if clk else None,
                "slack": None,
                "violated": None,
                "stages": [],
            }
            continue

        if cur is None:
            continue

        m = _RE_ENDPOINT.match(line)
        if m:
            cur["endpoint"] = m.group(1)
            continue

        m = _RE_PATH_GROUP.match(line)
        if m:
            cur["path_group"] = m.group(1)
            continue

        m = _RE_PATH_TYPE.match(line)
        if m:
            cur["path_type"] = m.group(1)
            continue

        m = _RE_SLACK.match(line)
        if m:
            cur["slack"] = float(m.group(1))
            cur["violated"] = m.group(2) == "VIOLATED"
            paths.append(cur)
            cur = None
            continue

        m = _RE_STAGE.match(line)
        if m:
            pin = m.group(1)
            cur["stages"].append(
                {"pin": pin, "instance": _instance_of(pin), "cell": m.group(2)}
            )

    return paths


def _at_risk_threshold(clock_period_ns, thresholds):
    if clock_period_ns:
        return clock_period_ns * thresholds["at_risk_slack_fraction_of_period"]
    return thresholds["at_risk_slack_abs_ns"]


def analyze(paths, clock_period_ns=None, thresholds=None, frozen_prefixes=None):
    """Cluster violating paths and score candidate fix sites.

    ``paths`` is the output of :func:`parse_report_checks`. Setup (``max``) and
    hold (``min``) paths are analysed separately downstream by the caller
    filtering ``path_type``; this function analyses whatever it is given, so the
    caller controls the check class.

    ``frozen_prefixes`` names hierarchy scopes the ECO may not modify (hardened
    macro instances, the pad/IO ring, vendor hard IP). Candidates inside them
    are moved to ``frozen_candidates`` rather than ranked as fix targets.
    """
    thresholds = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    at_risk_slack = _at_risk_threshold(clock_period_ns, thresholds)

    violating = [p for p in paths if p["violated"]]
    passing = [p for p in paths if p["violated"] is False]

    # --- dominance: violating paths through each instance ------------------
    dom_paths = defaultdict(int)
    dom_cell = {}
    for p in violating:
        for inst in {s["instance"] for s in p["stages"]}:
            dom_paths[inst] += 1
        for s in p["stages"]:
            dom_cell.setdefault(s["instance"], s["cell"])

    # --- collateral: currently-passing paths through each instance ---------
    col_count = defaultdict(int)
    col_min_slack = {}
    col_at_risk = defaultdict(int)
    for p in passing:
        for inst in {s["instance"] for s in p["stages"]}:
            col_count[inst] += 1
            prev = col_min_slack.get(inst)
            if prev is None or p["slack"] < prev:
                col_min_slack[inst] = p["slack"]
            if p["slack"] < at_risk_slack:
                col_at_risk[inst] += 1

    candidates = []
    for inst, dom in dom_paths.items():
        at_risk = col_at_risk.get(inst, 0)
        collateral = col_count.get(inst, 0)
        # Transparent, deliberately simple: paths already near zero dominate
        # the risk, with a small weight on sheer collateral breadth. Documented
        # rather than tuned -- the agent reads the raw components too.
        perturbation = at_risk + 0.1 * collateral
        owner = _frozen_by(inst, frozen_prefixes)
        candidates.append(
            {
                "instance": inst,
                "cell": dom_cell.get(inst),
                "dominance": dom,
                "dominance_fraction": (dom / len(violating)) if violating else 0.0,
                "collateral_paths": collateral,
                "collateral_at_risk": at_risk,
                "collateral_min_slack": col_min_slack.get(inst),
                "perturbation_score": round(perturbation, 4),
                "leverage": round(dom / (1.0 + perturbation), 4),
                "frozen": owner is not None,
                "frozen_by": owner,
            }
        )

    candidates.sort(key=lambda c: (-c["leverage"], -c["dominance"], c["instance"]))

    # A frozen instance is NOT a fix target, but it is high-value DIAGNOSIS: a
    # dominant frozen cluster is the evidence that says "this is not fixable at
    # this level, escalate to that block's own flow". So it is separated and
    # kept, never silently dropped.
    frozen_candidates = [c for c in candidates if c["frozen"]]
    candidates = [c for c in candidates if not c["frozen"]]

    # --- concentration: do a few instances cover most violations? ----------
    # Computed over ALL instances, frozen included. Excluding frozen logic here
    # would understate how clustered the failure really is and mis-screen entry.
    top_n = thresholds["concentration_top_n"]
    _all = sorted(candidates + frozen_candidates, key=lambda c: -c["dominance"])
    by_dominance = _all[:top_n]
    covered = set()
    top_instances = {c["instance"] for c in by_dominance}
    for i, p in enumerate(violating):
        if {s["instance"] for s in p["stages"]} & top_instances:
            covered.add(i)
    concentration = (len(covered) / len(violating)) if violating else 0.0

    # --- unfixable-at-this-level detection ---------------------------------
    # A violating path whose every stage sits in frozen logic cannot be repaired
    # here AT ALL -- no amount of wave budget will touch it. That is the precise,
    # mechanical form of "structurally un-ECO-able cluster": it does not need
    # judgement, it needs escalation to the owning block's own flow.
    frozen_names = {c["instance"] for c in frozen_candidates}
    no_fixable = 0
    touching_frozen = 0
    for p in violating:
        insts = {s["instance"] for s in p["stages"]}
        if not insts:
            continue
        if insts & frozen_names:
            touching_frozen += 1
        if insts and insts <= frozen_names:
            no_fixable += 1
    nv = len(violating)

    # --- secondary groupings the agent uses to spot global causes ----------
    def _tally(key):
        t = defaultdict(int)
        for p in violating:
            if p.get(key):
                t[p[key]] += 1
        return dict(sorted(t.items(), key=lambda kv: -kv[1]))

    slacks = [p["slack"] for p in violating]
    return {
        "thresholds": thresholds,
        "at_risk_slack_ns": round(at_risk_slack, 6),
        "path_counts": {
            "total_parsed": len(paths),
            "violating": len(violating),
            "passing": len(passing),
        },
        "wns_ns": min(slacks) if slacks else None,
        "tns_ns": round(sum(slacks), 6) if slacks else 0.0,
        "concentration": {
            "top_n": top_n,
            "instances": [c["instance"] for c in by_dominance],
            "coverage_fraction": round(concentration, 4),
        },
        "by_startpoint": _tally("startpoint"),
        # Violations are counted PER ENDPOINT, so this is the tally churn is
        # measured against -- an endpoint that stops violating is a genuine
        # closure, and one that starts violating is genuine collateral.
        "by_endpoint": _tally("endpoint"),
        "by_launch_clock": _tally("launch_clock"),
        "by_path_group": _tally("path_group"),
        "candidates": candidates,
        # Ranked but NOT fixable here. A dominant entry in this list is the
        # mechanical form of "un-ECO-able cluster" -- escalate to the owning
        # block's own flow rather than spending wave budget.
        "frozen_candidates": frozen_candidates,
        "frozen": {
            "prefixes": [str(p).rstrip("/") for p in (frozen_prefixes or [])],
            "instances": len(frozen_candidates),
            "paths_touching_frozen": touching_frozen,
            "paths_with_no_fixable_instance": no_fixable,
            "no_fixable_fraction": round(no_fixable / nv, 4) if nv else 0.0,
            "note": ("A path with no fixable instance cannot be repaired at this "
                     "level at all; it needs a reopen of the owning block's flow. "
                     "Frozen scopes appear in a top-level timing report whenever "
                     "macros are integrated timing-transparently (routed netlist "
                     "+ SPEF, no Liberty abstraction)."),
        },
    }


def entry_screen(analysis, total_endpoints=None, clock_period_ns=None,
                 thresholds=None):
    """Apply the cheap hard-reject screen and annotate the advisory bands.

    Returns ``verdict`` of ``hard_reject`` (escalate to rung-2 without running
    an ECO) or ``assess`` (the agent decides from concentration + magnitude).
    A missing input is reported as ``unavailable`` and never silently treated
    as passing the screen.
    """
    thresholds = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    violating = analysis["path_counts"]["violating"]
    wns = analysis["wns_ns"]

    endpoint_fraction = (
        violating / total_endpoints if total_endpoints else None
    )
    wns_fraction = (
        abs(wns) / clock_period_ns if (wns is not None and clock_period_ns) else None
    )

    reasons = []
    unavailable = []
    if endpoint_fraction is None:
        unavailable.append("total_endpoints not supplied")
    elif endpoint_fraction > thresholds["hard_reject_endpoint_fraction"]:
        reasons.append(
            "violating endpoints %.2f%% exceed the %.2f%% hard-reject ceiling"
            % (endpoint_fraction * 100,
               thresholds["hard_reject_endpoint_fraction"] * 100)
        )
    if wns_fraction is None:
        unavailable.append("clock_period_ns not supplied")
    elif wns_fraction > thresholds["hard_reject_wns_fraction_of_period"]:
        reasons.append(
            "WNS is %.1f%% of the clock period, above the %.1f%% ceiling -- "
            "this is a structural miss, not an ECO target"
            % (wns_fraction * 100,
               thresholds["hard_reject_wns_fraction_of_period"] * 100)
        )

    # Reachability, not difficulty: these paths have NO instance this level is
    # permitted to modify, so no wave can close them.
    _fz = analysis.get("frozen") or {}
    _nf = _fz.get("no_fixable_fraction") or 0.0
    if _nf > thresholds["hard_reject_no_fixable_fraction"]:
        reasons.append(
            "%.0f%% of violating paths have NO fixable instance (every stage is "
            "inside frozen scope %s) -- they are unrepairable at this level and "
            "need a reopen of the owning block's own flow, not an ECO"
            % (_nf * 100, ", ".join(_fz.get("prefixes") or []) or "(none declared)")
        )

    def _band(value, comfortable, marginal):
        if value is None:
            return "unavailable"
        if value <= comfortable:
            return "comfortable"
        if value <= marginal:
            return "marginal"
        return "adverse"

    return {
        "verdict": "hard_reject" if reasons else "assess",
        "reasons": reasons,
        "unavailable_inputs": unavailable,
        "violating_endpoints": violating,
        "endpoint_fraction": (
            round(endpoint_fraction, 6) if endpoint_fraction is not None else None
        ),
        "endpoint_band": _band(
            endpoint_fraction,
            thresholds["endpoint_fraction_comfortable"],
            thresholds["endpoint_fraction_marginal"],
        ),
        "wns_fraction_of_period": (
            round(wns_fraction, 6) if wns_fraction is not None else None
        ),
        "wns_band": _band(
            wns_fraction,
            thresholds["wns_fraction_comfortable"],
            thresholds["wns_fraction_marginal"],
        ),
        "concentration_fraction": analysis["concentration"]["coverage_fraction"],
        "no_fixable_fraction": _nf,
        "frozen_prefixes": _fz.get("prefixes") or [],
        "thresholds_provisional": thresholds.get("provisional", False),
        "note": (
            "Concentration is the primary discriminator: a clustered many-violation "
            "design is a better ECO candidate than a diffuse few-violation one. "
            "Thresholds are provisional and pending calibration."
        ),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cluster STA violating paths and score ECO fix candidates."
    )
    ap.add_argument("report", help="OpenSTA report_checks text file")
    ap.add_argument("--clock-period", type=float, default=None,
                    help="clock period in ns (enables period-relative bands)")
    ap.add_argument("--total-endpoints", type=int, default=None,
                    help="total timing endpoints in the design")
    ap.add_argument("--path-type", choices=["max", "min"], default=None,
                    help="restrict to setup (max) or hold (min) paths")
    ap.add_argument("--top", type=int, default=10,
                    help="how many ranked candidates to emit")
    ap.add_argument("--frozen-prefix", action="append", default=[],
                    metavar="SCOPE",
                    help="hierarchy scope this level may NOT modify (hardened "
                         "macro, pad ring, hard IP); repeatable")
    args = ap.parse_args(argv)

    with open(args.report, "r", encoding="utf-8", errors="replace") as fh:
        paths = parse_report_checks(fh.read())

    if args.path_type:
        paths = [p for p in paths if p["path_type"] == args.path_type]

    analysis = analyze(paths, clock_period_ns=args.clock_period,
                       frozen_prefixes=args.frozen_prefix)
    screen = entry_screen(
        analysis,
        total_endpoints=args.total_endpoints,
        clock_period_ns=args.clock_period,
    )
    analysis["candidates"] = analysis["candidates"][: args.top]
    analysis["frozen_candidates"] = analysis["frozen_candidates"][: args.top]
    json.dump({"entry_screen": screen, "analysis": analysis},
              sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
