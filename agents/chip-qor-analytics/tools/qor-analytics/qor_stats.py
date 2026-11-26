"""Metric polarity, ordered trajectories, and comparability for cross-run QoR.

THE DEFECT THIS EXISTS TO REMOVE
--------------------------------
Anomaly detection was `abs(pct) >= threshold`. With no notion of which
DIRECTION is good, a 6% slack IMPROVEMENT and a 6% area REGRESSION were both
emitted into a field the envelope labels "QoR regressions detected", and both
failed the gate. Telling an engineer their improvement is a regression is worse
than staying silent: it trains them to disregard the whole report, and the real
regression sitting next to it goes with it.

Polarity is not a nicety on top of the statistics. It is what makes a delta
MEAN anything at all. Without it the tool can only say a number moved.

WHAT IS DERIVABLE VS WHAT MUST BE DECLARED
------------------------------------------
Polarity for well-known silicon metrics (area, power, slack, coverage, DRC
violations) is genuinely knowable and is resolved from the table below. For a
metric this module does NOT recognise, polarity is NOT guessed: the change is
reported as `unclassified` and drives a separate gating count, because a change
that cannot be classified might be a regression and must not read as clean.
Every resolution records HOW it was made so a reader can audit it.
"""

import math
import re

# Canonical polarity for metrics this catalog actually emits.
# "min" = lower is better. "max" = higher is better.
#
# The subtle ones, worth stating because getting them backwards silently
# inverts every verdict built on them:
#   * wns/tns/slack -- MAXIMIZE. Slack is negative when timing fails, so a
#     LARGER (less negative) value is the better one. Treating slack as
#     lower-is-better inverts timing closure completely.
#   * skew/insertion delay -- MINIMIZE.
#   * yield/coverage/frequency -- MAXIMIZE.
_EXACT = {
    # timing
    "wns": "max", "tns": "max", "slack": "max", "worst_slack": "max",
    "worst_negative_slack": "max", "total_negative_slack": "max",
    "setup_wns": "max", "hold_wns": "max", "fmax": "max", "fmax_mhz": "max",
    "frequency": "max", "frequency_mhz": "max", "period": "min",
    "clock_period": "min", "insertion_delay": "min", "skew": "min",
    "clock_skew": "min", "latency": "min",
    # area / utilisation
    "area": "min", "area_um2": "min", "die_area": "min", "core_area": "min",
    "cell_count": "min", "instance_count": "min", "gate_count": "min",
    "utilization": None, "density": None,   # target-band, NOT monotone
    # power
    "power": "min", "power_mw": "min", "total_power": "min",
    "dynamic_power": "min", "leakage_power": "min", "leakage": "min",
    "switching_power": "min", "internal_power": "min", "ir_drop": "min",
    "worst_ir_drop": "min",
    # quality / correctness
    "violations": "min", "drc_violations": "min", "lvs_errors": "min",
    "antenna_violations": "min", "errors": "min", "warnings": "min",
    "shorts": "min", "opens": "min", "congestion": "min", "overflow": "min",
    "wirelength": "min", "wire_length": "min", "via_count": "min",
    # verification
    "coverage": "max", "line_coverage": "max", "branch_coverage": "max",
    "toggle_coverage": "max", "functional_coverage": "max", "yield": "max",
    "yield_percent": "max", "pass_rate": "max",
    # names the stage CDEs actually emit (results.* / qor_metrics.*), so a
    # trajectory over real envelopes is classifiable without a declaration
    "cell_area": "min", "design_area": "min", "stdcell_area": "min",
    "estimated_wns": "max", "estimated_tns": "max", "setup_tns": "max",
    "setup_worst_slack": "max", "hold_worst_slack": "max",
    "hold_slack": "max", "hold_tns": "max", "estimated_fmax": "max",
    "routing_congestion": "min", "congestion_usage": "min",
    "congestion_overflow": "min", "clock_insertion_delay": "min",
    "worst_ir": "min", "drc_count": "min",
    "achieved_utilization": None,
}

#: Unit suffixes stripped before the table lookup, so `total_power_mw`,
#: `wns_ns` and `cell_area_um2` resolve like their unit-free names.
_UNIT_SUFFIX_RE = re.compile(
    r"_(um2|mm2|pct|percent|mhz|ghz|khz|ns|ps|us|mw|uw|nw|mv|um|mm|nm|w|v)$")

# Suffix/substring rules, applied ONLY when the exact table misses. Each is
# unambiguous on its own; anything matching BOTH polarities is left unknown
# rather than resolved by precedence, since a coin-flip here silently inverts a
# verdict.
_MIN_HINTS = (r"violation", r"error", r"_drop\b", r"leakage", r"\bpower\b",
              r"\barea\b", r"count\b", r"wirelength", r"congestion",
              r"overflow", r"skew", r"latency")
_MAX_HINTS = (r"coverage", r"\byield\b", r"\bslack\b", r"\bwns\b", r"\btns\b",
              r"fmax", r"pass_rate")

# Metrics with a target BAND rather than a monotone direction. Calling a
# utilization change "better" or "worse" without the target is meaningless --
# 90% is not an improvement on 70% if the target was 70%.
_NON_MONOTONE = {"utilization", "density", "target_density", "aspect_ratio"}


def resolve_polarity(metric, declared=None):
    """Return {'polarity': 'min'|'max'|None, 'basis': ..., 'note': ...}.

    A caller-DECLARED polarity always wins: the catalog cannot know every
    project-specific metric, and a declaration is evidence while a guess is not.
    """
    name = str(metric).strip().lower()
    if declared and metric in declared:
        d = declared[metric]
        if d in ("min", "max"):
            return {"polarity": d, "basis": "caller_declared"}
        return {"polarity": None, "basis": "caller_declared_invalid",
                "note": "declared polarity %r is not 'min' or 'max'" % (d,)}

    _stem = _UNIT_SUFFIX_RE.sub("", name)
    if name not in _EXACT and name not in _NON_MONOTONE and _stem != name:
        name = _stem
    if name in _NON_MONOTONE:
        return {"polarity": None, "basis": "non_monotone_metric",
                "note": ("'%s' has a TARGET BAND, not a direction: a move toward "
                         "or away from the target cannot be judged without the "
                         "target, so no improvement/regression is claimed"
                         % metric)}

    if name in _EXACT:
        p = _EXACT[name]
        if p is None:
            return {"polarity": None, "basis": "non_monotone_metric",
                    "note": "'%s' is a target-band metric" % metric}
        return {"polarity": p, "basis": "known_silicon_metric"}

    hits_min = any(re.search(p, name) for p in _MIN_HINTS)
    hits_max = any(re.search(p, name) for p in _MAX_HINTS)
    if hits_min and not hits_max:
        return {"polarity": "min", "basis": "name_heuristic"}
    if hits_max and not hits_min:
        return {"polarity": "max", "basis": "name_heuristic"}
    if hits_min and hits_max:
        return {"polarity": None, "basis": "ambiguous_name",
                "note": ("'%s' matches BOTH lower-is-better and higher-is-better "
                         "patterns; refusing to pick one, because guessing "
                         "backwards inverts every verdict built on it" % metric)}
    return {"polarity": None, "basis": "unknown_metric",
            "note": ("polarity of '%s' is unknown to this tool. Declare it via "
                     "`metric_polarity` -- it is NOT guessed, so this change is "
                     "reported as unclassified rather than as an improvement or "
                     "a regression" % metric)}


def classify_change(metric, value, baseline, declared=None):
    """Classify a change as improvement / regression / unclassified.

    Returns None when there is nothing to compare, so a caller can tell "no
    change worth reporting" from "changed but we cannot say which way".
    """
    if not isinstance(value, (int, float)) or not isinstance(baseline, (int, float)):
        return None
    if baseline == 0:
        # Percent change against a zero baseline is undefined, not infinite.
        # Reported as an absolute move so a 0 -> 5 violation jump is still seen.
        pol = resolve_polarity(metric, declared)
        delta = value - baseline
        if delta == 0:
            return None
        direction = ("regression" if (pol["polarity"] == "min" and delta > 0)
                     or (pol["polarity"] == "max" and delta < 0)
                     else "improvement" if pol["polarity"] else "unclassified")
        return {"metric": metric, "value": value, "baseline": baseline,
                "delta_absolute": delta, "delta_percent": None,
                "polarity": pol["polarity"], "polarity_basis": pol["basis"],
                "direction": direction,
                "note": ("baseline is zero, so percent change is undefined; "
                         "reported as an absolute move")}

    pct = 100.0 * (value - baseline) / abs(baseline)
    pol = resolve_polarity(metric, declared)
    if pol["polarity"] is None:
        direction = "unclassified"
    elif pct == 0:
        direction = "unchanged"
    elif pol["polarity"] == "min":
        direction = "regression" if pct > 0 else "improvement"
    else:
        direction = "regression" if pct < 0 else "improvement"

    out = {"metric": metric, "value": value, "baseline": baseline,
           "delta_percent": round(pct, 2), "delta_absolute": value - baseline,
           "polarity": pol["polarity"], "polarity_basis": pol["basis"],
           "direction": direction}
    if pol.get("note"):
        out["polarity_note"] = pol["note"]
    return out


# --------------------------------------------------------------------------
# Ordering and trajectory
# --------------------------------------------------------------------------

def _natural_key(s):
    """Split digits so run.10 sorts AFTER run.2, not before it.

    Plain lexicographic sorting of run identifiers puts attempt 10 between 1 and
    2, which silently scrambles the very axis a trajectory is measured along.
    """
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", str(s))]


def order_runs(rows, order_key=None, fallback="natural_id"):
    """Order runs along a real axis and RECORD which axis was used.

    A trajectory is a claim about a SEQUENCE, so the sequence has to be
    established rather than assumed. The previous implementation treated the
    envelopes as an unordered set, which makes "trend over ordered runs"
    unanswerable no matter what statistics follow.
    """
    if order_key:
        keyed = [r for r in rows if r.get(order_key) is not None]
        if len(keyed) == len(rows):
            return (sorted(rows, key=lambda r: r[order_key]),
                    {"basis": "explicit_order_key", "key": order_key})
        return (list(rows),
                {"basis": "as_supplied",
                 "note": ("order_key '%s' is missing on %d of %d runs, so it "
                          "cannot order them; using the order supplied"
                          % (order_key, len(rows) - len(keyed), len(rows)))})

    for cand in ("order", "index", "attempt", "timestamp", "finished_utc"):
        if all(r.get(cand) is not None for r in rows):
            return (sorted(rows, key=lambda r: r[cand]),
                    {"basis": "inferred_order_field", "key": cand})

    if fallback == "list_order":
        return (list(rows),
                {"basis": "as_supplied_list_order",
                 "note": ("no order_key and no order field on every run; runs "
                          "were taken in the order the envelopes were LISTED. "
                          "Supply `order` per envelope or `order_key` if the "
                          "list is not already in sequence")})
    if all(r.get("id") for r in rows):
        return (sorted(rows, key=lambda r: _natural_key(r["id"])),
                {"basis": "natural_sort_of_id",
                 "note": ("no explicit order field; runs were ordered by a "
                          "NATURAL sort of their ids (so run.10 follows run.2). "
                          "If ids do not encode sequence, supply `order_key` -- "
                          "the trend is only as meaningful as this axis")})
    return (list(rows), {"basis": "as_supplied",
                         "note": "no order field and no ids; using supplied order"})


def _linfit(xs, ys):
    """Least-squares slope/intercept plus R^2. Returns None if degenerate."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 if syy == 0 else max(0.0, min(1.0, (sxy ** 2) / (sxx * syy)))
    return slope, intercept, r2


def trajectory(rows, metric, order_key=None, declared=None,
               fallback="natural_id"):
    """Fit a metric's trend across ORDERED runs.

    Reports the slope in metric-units-per-run, the fit quality, and -- via
    polarity -- whether that trend is improving or degrading. Returns an
    explicitly not-assessable result rather than a flat or absent trend whenever
    the data cannot support one.
    """
    ordered, order_basis = order_runs(rows, order_key, fallback)
    pts = [(i, r.get(metric)) for i, r in enumerate(ordered)]
    used = [(i, v) for i, v in pts if isinstance(v, (int, float))]

    # N is PER METRIC, never the run total: a trend over 3 of 10 runs must not
    # be presented with the authority of 10.
    result = {"metric": metric, "n_used": len(used), "n_runs": len(ordered),
              "order": order_basis,
              "series": [dict({"run": ordered[i].get("id", i), "value": v},
                              **({"source": ordered[i]["_sources"][metric]}
                                 if (ordered[i].get("_sources") or {}).get(metric)
                                 else {}))
                         for i, v in used]}

    if len(used) < 3:
        result.update({
            "assessable": False, "slope_per_run": None, "r_squared": None,
            "direction": None,
            "note": ("only %d run(s) report '%s'; a trajectory needs at least 3 "
                     "points. Two points are a delta, not a trend -- fitting a "
                     "line through them always yields R^2 = 1 and would look "
                     "like the strongest possible evidence."
                     % (len(used), metric))})
        return result

    fit = _linfit([u[0] for u in used], [u[1] for u in used])
    if fit is None:
        result.update({"assessable": False, "slope_per_run": None,
                       "r_squared": None, "direction": None,
                       "note": "degenerate fit (no variation along the run axis)"})
        return result

    slope, intercept, r2 = fit
    pol = resolve_polarity(metric, declared)
    if pol["polarity"] is None or slope == 0:
        direction = "flat" if slope == 0 else "unclassified"
    elif pol["polarity"] == "min":
        direction = "improving" if slope < 0 else "degrading"
    else:
        direction = "improving" if slope > 0 else "degrading"

    first, last = used[0][1], used[-1][1]
    result.update({
        "assessable": True,
        "slope_per_run": round(slope, 6),
        "intercept": round(intercept, 6),
        "r_squared": round(r2, 4),
        "first": first, "last": last,
        "net_change": round(last - first, 6),
        "polarity": pol["polarity"], "polarity_basis": pol["basis"],
        "direction": direction,
        "fit_quality": ("strong" if r2 >= 0.7 else
                        "weak" if r2 >= 0.3 else "none"),
        "note": ("slope is in %s-units per run over %d ordered points; R^2=%.3f "
                 "%s" % (metric, len(used), r2,
                         "means the trend explains most of the variation"
                         if r2 >= 0.7 else
                         "is LOW -- the runs scatter more than they trend, so "
                         "do not read this slope as a trajectory"))})
    return result


# --------------------------------------------------------------------------
# Comparability
# --------------------------------------------------------------------------

# Fields that must agree before runs may be aggregated. Averaging design_A at
# the tt corner with design_B at ff produces a number with no referent -- it is
# not a noisy measurement of anything, it is a category error.
_COMPARABILITY_FIELDS = ("design", "block", "top", "corner", "pdk",
                         "pdk_version", "tool_version", "units")


def comparability(envs):
    """Check that the runs describe the same thing before pooling them."""
    seen = {}
    for e in envs:
        for f in _COMPARABILITY_FIELDS:
            v = e.get(f) if f in e else (e.get("context") or {}).get(f)
            if v is not None:
                seen.setdefault(f, set()).add(str(v))

    conflicts = {f: sorted(vs) for f, vs in seen.items() if len(vs) > 1}
    declared = sorted(seen)
    if not declared:
        return {"assessable": False, "comparable": None, "conflicts": {},
                "declared_fields": [],
                "note": ("no design/corner/PDK/tool-version fields were carried "
                         "on any envelope, so COMPARABILITY COULD NOT BE "
                         "CHECKED. This is not evidence that the runs are "
                         "comparable -- pooling them may be mixing designs or "
                         "corners.")}
    if conflicts:
        return {"assessable": True, "comparable": False, "conflicts": conflicts,
                "declared_fields": declared,
                "note": ("runs disagree on %s. Aggregating across them produces "
                         "a statistic with no referent; separate the cohorts or "
                         "state why the difference is immaterial."
                         % ", ".join(sorted(conflicts)))}
    missing = {}
    for i, e in enumerate(envs):
        context = e.get("context") or {}
        absent = [f for f in declared if e.get(f, context.get(f)) is None]
        if absent:
            missing[str(e.get("id", i))] = absent
    required_missing = []
    if not any(f in seen for f in ("design", "block", "top")):
        required_missing.append("design/block/top")
    required_missing += [f for f in ("corner", "pdk") if f not in seen]
    if missing or required_missing:
        return {"assessable": False, "comparable": None, "conflicts": {},
                "declared_fields": declared, "missing_by_run": missing,
                "required_context_missing": required_missing,
                "note": ("cohort comparability unavailable: identity, corner and "
                         "PDK context are required, and every declared context "
                         "field must be present on every run")}
    return {"assessable": True, "comparable": True, "conflicts": {},
            "declared_fields": declared,
            "note": "all declared context fields agree across runs"}
