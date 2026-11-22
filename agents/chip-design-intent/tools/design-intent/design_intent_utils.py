#!/usr/bin/env python3
"""design_intent_utils.py -- design intent / requirements normalization.

No external engine: this is deterministic structured spec authoring. Two
scenarios:
  * normalize -- take raw requirement statements + target metrics and emit a
    normalized, machine-checkable design specification (unique IDs, categories,
    measurable acceptance criteria, traceability), flagging non-measurable or
    duplicate requirements.
  * ppa_budget -- take top-level PPA targets (frequency/area/power) and an
    optional block breakdown, allocate a consistent per-block budget, and check
    that the allocation closes against the top-level target.

Node-agnostic. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import time

import req_identity
import units

TOOL = "design-intent"
TOOL_VERSION = "1.2.0"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


# --- production hardening (migrate_production_hardening.py) ---------------
_PRODUCTION_HARDENING_V1 = True


def _env_dir(default, *names):
    """Return the first non-empty env var in *names*, else *default*."""
    for _n in names:
        _v = os.environ.get(_n)
        if _v:
            return _v
    return default


def _hash_input_file(path):
    try:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as _f:
            for _chunk in iter(lambda: _f.read(65536), b""):
                h.update(_chunk)
        return {"sha256": h.hexdigest(), "bytes": os.path.getsize(path)}
    except Exception:
        return None


_CDE_REQUIRED_FIELDS = (
    "tool", "status", "objective", "tools_used", "pdk_binding", "assumptions",
    "inputs_ref", "vplan", "results", "qor_metrics", "signoff_evidence",
    "margin", "validation", "provenance",
)


def _finalize_envelope(results):
    """(3) CDE self-validation + (4) provenance stamping. Never raises."""
    if not isinstance(results, dict):
        return results
    try:
        # Make the CDE contract invariant: a required field that is legitimately
        # EMPTY for this stage (a node-agnostic / pre-physical tool has no QoR or
        # margin, a spec/RTL stage has no signoff_evidence, etc.) is defaulted to
        # a typed-empty value rather than omitted, so downstream readers can rely
        # on the field existing. Content-bearing fields (objective/results/
        # validation/provenance) are NOT fabricated -- their absence stays a warning.
        _EMPTY_DEFAULTS = {
            "tools_used": [], "assumptions": [], "qor_metrics": {},
            "signoff_evidence": {}, "inputs_ref": {}, "margin": {},
            "vplan": "shared_artifact", "pdk_binding": "none",
        }
        _defaulted = []
        for _k, _dv in _EMPTY_DEFAULTS.items():
            if _k not in results:
                results[_k] = list(_dv) if isinstance(_dv, list) else \
                    (dict(_dv) if isinstance(_dv, dict) else _dv)
                _defaulted.append(_k)
        missing = [k for k in _CDE_REQUIRED_FIELDS if k not in results]
        warns = results.get("envelope_warnings")
        if not isinstance(warns, list):
            warns = []
        if _defaulted:
            warns.append("CDE auto-defaulted empty required field(s): "
                         + ", ".join(sorted(_defaulted)))
        if missing:
            warns.append("CDE missing required field(s): " + ", ".join(missing))
        if warns:
            results["envelope_warnings"] = warns
    except Exception as _e:
        print("[" + str(TOOL) + "] CDE self-check skipped: " + str(_e), flush=True)
    try:
        import datetime
        prov = results.get("provenance")
        if not isinstance(prov, dict):
            prov = {} if prov in (None, "") else {"note": str(prov)}
        prov.setdefault(
            "finished_utc", datetime.datetime.utcnow().isoformat() + "Z")
        prov.setdefault("run_output_dir", _OUTPUT_DIR)
        _hashes = {}

        def _walk(node):
            if isinstance(node, str):
                if os.path.isfile(node):
                    _h = _hash_input_file(node)
                    if _h:
                        _hashes[os.path.basename(node)] = _h
            elif isinstance(node, dict):
                for _x in node.values():
                    _walk(_x)
            elif isinstance(node, (list, tuple)):
                for _x in node:
                    _walk(_x)

        _walk(results.get("inputs_ref"))
        # Always record the input-hash provenance key (even when empty) so the
        # audit chain is explicit rather than a silent gap. An empty map when
        # inputs_ref carried paths means those inputs were not hashable at
        # finalize time (e.g. a container mount no longer present).
        prov.setdefault("input_hashes", _hashes)
        results["provenance"] = prov
    except Exception as _e:
        print("[" + str(TOOL) + "] provenance stamp skipped: " + str(_e), flush=True)

    # --- runtime + peak-memory capture (migrate_runtime_capture.py) --------
    # _CDE_RUNTIME_CAPTURED_V1
    # Cost hints (slot-minutes) and `peak_ram_hint` were expert GUESSES: an audit
    # of 130 real CDEs found only 3 recording any runtime and none recording
    # memory, so every effort budget was calibrated against nothing. This records
    # what the run actually cost.
    #
    # Peak RSS of CHILDREN is the number that matters -- the heavy memory lives
    # in the yosys/openroad/eqy subprocesses, not in this wrapper. Repeated
    # exit-137 OOM kills in this campaign (LEC combine ~23GB; routing 2.18GB
    # against a then-2GB VM) were each diagnosed only forensically, after the
    # kill. Recording the peak on EVERY run makes the next one predictable.
    # Bookkeeping must never fail a design run, so nothing here is fatal.
    try:
        import datetime as _dt
        import time as _time
        _rt = {}
        _start_age = None
        try:
            # Process age on Linux, from the kernel's own accounting.
            #
            # NOT /proc/self mtime -- that looks like process start time but the
            # kernel refreshes it, so it reads ~0s for any run (verified in a
            # real container: a 2s sleep measured 0.006s). Use field 22 of
            # /proc/self/stat (`starttime`, in clock ticks since boot) against
            # /proc/uptime instead. comm (field 2) may itself contain spaces and
            # parentheses, so split after the LAST ')' -- index 19 of that tail
            # is field 22.
            with open("/proc/self/stat", "rb") as _f:
                _tail = _f.read().decode("utf-8", "replace").rsplit(")", 1)[1]
            _ticks = float(_tail.split()[19])
            _hz = float(os.sysconf("SC_CLK_TCK")) or 100.0
            with open("/proc/uptime", "rb") as _f:
                _up = float(_f.read().split()[0])
            _start_age = max(0.0, _up - (_ticks / _hz))
        except Exception:
            _start_age = None
        if _start_age is not None:
            _rt["started_utc"] = _dt.datetime.utcfromtimestamp(
                _time.time() - _start_age).isoformat() + "Z"
            _rt["elapsed_seconds"] = round(_start_age, 3)
            # the effort cost model is denominated in slot-minutes
            _rt["slot_minutes"] = round(_start_age / 60.0, 4)
            _rt["measurement"] = "proc_self_stat_starttime"
        else:
            # Honest absence beats a fabricated zero: a 0.0 here would silently
            # price a real run as free and understate campaign burn.
            _rt["measurement"] = "unavailable"
        try:
            import resource as _res
            # ru_maxrss is KILOBYTES on Linux (bytes on macOS -- containers here
            # are Linux). RUSAGE_CHILDREN covers children that have been waited
            # for, which is exactly how every EDA engine here is invoked
            # (subprocess.run / check_output).
            _self_kb = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss
            _kid_kb = _res.getrusage(_res.RUSAGE_CHILDREN).ru_maxrss
            _rt["peak_rss_mb_self"] = round(_self_kb / 1024.0, 1)
            _rt["peak_rss_mb_children"] = round(_kid_kb / 1024.0, 1)
            _rt["peak_rss_mb"] = round(max(_self_kb, _kid_kb) / 1024.0, 1)
        except Exception:
            pass
        _prov = results.get("provenance")
        if isinstance(_prov, dict):
            _prov.setdefault("runtime", _rt)
    except Exception as _e:
        print("[" + str(TOOL) + "] runtime capture skipped: " + str(_e),
              flush=True)
    # --- end runtime + peak-memory capture ---------------------------------
    # --- normalized progress contract (migrate_cde_progress.py) -------------
    # Emits the stable `progress` block (residual / verdict_normalized /
    # alignment) that effort budgets, stall detection and QoR analytics read.
    # Freeform `results` keys are NOT stable across attempts, so this mapping is
    # what makes any metric-driven decision possible. Never fatal.
    try:
        import cde_progress as _cde_progress   # _CDE_PROGRESS_STAMPED_V1
        _cde_progress.stamp_progress(results, results.get("stage") or TOOL)
    except Exception as _e:
        print("[" + str(TOOL) + "] progress stamp skipped: " + str(_e), flush=True)
    # --- end normalized progress contract ----------------------------------

    return results
# --- end production hardening --------------------------------------------


def _save_run_command(cmd, name="run_command.txt"):
    try:
        with open(os.path.join(_OUTPUT_DIR, name), "a", encoding="utf-8") as f:
            f.write(str(cmd) + "\n")
    except Exception as _e:
        print("[" + str(TOOL) + "] run-command capture skipped: " + str(_e), flush=True)


def quick_setup(output_dir="/output", work_dir="/workdir"):
    global _OUTPUT_DIR, _WORK_DIR
    _OUTPUT_DIR, _WORK_DIR = output_dir, work_dir
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)


def _report_fmt_val(v):
    if isinstance(v, dict):
        if "value" in v:
            return (str(v["value"]) + " " + str(v.get("unit", ""))).strip()
        return None
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        if v and all(not isinstance(x, (dict, list)) for x in v):
            return ", ".join(str(x) for x in v)
        return None
    return v


def _report_kv_rows(d):
    rows = []
    for k, v in d.items():
        fv = _report_fmt_val(v)
        if fv is None or fv == "":
            continue
        rows.append("| " + str(k) + " | " + str(fv) + " |")
    return rows


def _render_report_md(r):
    tool = r.get("tool", "tool")
    status = str(r.get("status", "unknown"))
    L = ["# " + tool + " \u2014 human summary", ""]
    L.append("- **Status:** " + status.upper())
    if r.get("objective"):
        L.append("- **Objective:** " + str(r["objective"]))
    val = r.get("validation") or {}
    if isinstance(val, dict) and val.get("verdict"):
        note = (" \u2014 " + str(val["note"])) if val.get("note") else ""
        L.append("- **Verdict:** " + str(val["verdict"]) + note)
    if r.get("error"):
        L += ["", "> **Error:** " + str(r["error"])]
    for title, key in (("Key metrics", "qor_metrics"),
                       ("Results", "results"),
                       ("Evidence", "signoff_evidence")):
        d = r.get(key)
        if isinstance(d, dict) and d:
            rows = _report_kv_rows(d)
            if rows:
                L += ["", "## " + title, "", "| Metric | Value |", "| --- | --- |"] + rows
    L += ["", "_Full machine-readable envelope: `common_design_envelope.json`._", ""]
    return "\n".join(L)


def _write_report_md(results):
    path = os.path.join(_OUTPUT_DIR, "REPORT.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render_report_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def _organize_output():
    root = _OUTPUT_DIR
    for d in ("results", "reports", "logs"):
        os.makedirs(os.path.join(root, d), exist_ok=True)

    def _classify(name):
        if name.startswith("."):
            return None
        low = name.lower()
        if low in ("common_design_envelope.json", "final_results.json", "summary.md"):
            return None
        if (low.endswith(".rpt") or low.endswith(".md")
                or low.endswith("_report.json") or low.endswith(".csv")):
            return "reports"
        if low.endswith((".log", ".txt")) or low == "run_command.txt":
            return "logs"
        return "results"

    for entry in list(os.listdir(root)):
        full = os.path.join(root, entry)
        if not os.path.isfile(full):
            continue
        dest = _classify(entry)
        if dest is None:
            continue
        target = os.path.join(root, dest, entry)
        try:
            if os.path.exists(target):
                os.remove(target)
            os.replace(full, target)
        except Exception as _e:
            print("[" + str(TOOL) + "] organize: could not move " + entry + ": " + str(_e), flush=True)


def _render_summary_md(r):
    tool = r.get("tool", "tool")
    status = str(r.get("status", "unknown"))
    val = r.get("validation") or {}
    verdict = str(val.get("verdict", "")) if isinstance(val, dict) else ""
    L = ["# " + tool + " \u2014 run summary", ""]
    head = "**" + status.upper() + "**"
    if verdict:
        head += " \u00b7 verdict: **" + verdict + "**"
    L += [head, ""]
    if r.get("objective"):
        L += ["## What was done", "", str(r["objective"]), ""]
    if isinstance(val, dict) and val.get("note"):
        L += ["## Verdict", "", (verdict + " \u2014 " if verdict else "") + str(val["note"]), ""]
    if r.get("error"):
        L += ["> **Error:** " + str(r["error"]), ""]
    merged = {}
    for key in ("qor_metrics", "results", "signoff_evidence"):
        d = r.get(key)
        if isinstance(d, dict):
            for k, v in d.items():
                merged.setdefault(k, v)
    if merged:
        rows = _report_kv_rows(merged)
        if rows:
            L += ["## Key results", "", "| Metric | Value |", "| --- | --- |"] + rows + [""]
    L += ["## Where to find more", "",
          "- `common_design_envelope.json` \u2014 full machine-readable envelope (this dir)",
          "- `reports/` \u2014 the normalized specification / PPA budget", ""]
    return "\n".join(L)


def _write_summary_md(results):
    return  # option b: SUMMARY.md removed (tool emits REPORT.md; agent emits EXECUTIVE_SUMMARY.md)
    path = os.path.join(_OUTPUT_DIR, "SUMMARY.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render_summary_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def save_final_results(results):
    results = _finalize_envelope(results)
    path = os.path.join(_OUTPUT_DIR, "common_design_envelope.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    for fn, lbl in ((_write_report_md, "report"), (_write_summary_md, "summary")):
        try:
            fn(results)
        except Exception as _e:
            print("[" + str(TOOL) + "] " + lbl + " generation skipped: " + str(_e), flush=True)
    try:
        _organize_output()
    except Exception as _e:
        print("[" + str(TOOL) + "] output organize skipped: " + str(_e), flush=True)


def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    An envelope that stamps no `stage` resolves to no registry entry, reports NO
    METRIC, and a missing metric is indistinguishable downstream from a closed
    gate. The tool names its own gate rather than leaving it to the caller.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "spec"
    except Exception:
        return "spec"


# --- metric-class helpers (_METRIC_CLASS_HELPERS_V1) -------------------------------------
# Generated by catalog/migrate_metric_class_helpers.py. Do not hand-edit: the
# shared logic lives in catalog/tools/metric_classes.py so a fix reaches every
# tool at once.
def _labelled_interpretation(interp):
    """Stamp the model-authored class/basis via the shared vendored module.

    NOT a bare `or` default: an agent-SUPPLIED block must still be labelled, and
    the naive idiom labels only the ABSENT case -- so the one reading that
    actually needs the label ships unclassified.
    """
    try:
        import metric_classes
    except Exception:
        base = dict(interp) if isinstance(interp, dict) and interp else {}
        base.setdefault("basis", "agent_read_of_requirements_matrix" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_requirements_matrix")


def _crosscheck_interpretation(interp, measured, key):
    """Compare a model-authored count against the measured one; never decide.

    A disagreement is RECORDED, not resolved: a stale parser and a confabulated
    count need opposite fixes. An unavailable module is RECORDED too -- a
    cross-check that did not run must not read as one that passed.
    """
    try:
        import metric_classes
    except Exception as exc:
        return {"checked": False,
                "reason": "metric_classes module unavailable (%s); the "
                          "cross-check did NOT run" % exc}
    return metric_classes.crosscheck_interpretation(interp, measured, key)
# --- end metric-class helpers --------------------------------------------


def _cde(objective, status, results=None, signoff=None, assumptions=None,
         validation=None, provenance=None, inputs_ref=None, qor=None, error=None):
    env = {
        "tool": TOOL, "stage": _canonical_stage(),
        "status": status, "objective": objective,
        "tools_used": [{"name": TOOL, "version": TOOL_VERSION}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "spec_authoring"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


_MEASURABLE = re.compile(
    r"(\d+(\.\d+)?\s*(ghz|mhz|khz|hz|ns|ps|us|ms|mw|uw|nw|w|um2|mm2|um\^2|"
    r"mm\^2|um|mm|nm|gbps|mbps|kb|mb|gb|bit|bits|%|x|celsius|c|v|mv))|"
    r"((<=|>=|<|>|=)\s*\d)", re.I)

# The unit-bearing half of _MEASURABLE, WITHOUT the bare-comparison alternative.
# Used to tell "< 5 ns" from "< 5": the second satisfies the measurability gate
# while stating no dimension at all.
_UNIT_BEARING = re.compile(
    r"\d+(\.\d+)?\s*(ghz|mhz|khz|hz|ns|ps|us|ms|mw|uw|nw|w|um2|mm2|um\^2|"
    r"mm\^2|um|mm|nm|gbps|mbps|kb|mb|gb|bit|bits|%|x|celsius|c|v|mv)", re.I)

_CATEGORIES = {
    "performance": ["frequency", "ghz", "mhz", "throughput", "latency", "bandwidth",
                    "ips", "gbps", "cycles"],
    "power": ["power", "mw", "watt", "energy", "leakage", "dynamic"],
    "area": ["area", "um2", "mm2", "gates", "cells", "die", "utilization"],
    "reliability": ["reliability", "temperature", "aging", "em", "ir-drop", "esd"],
    "functional": ["shall", "must", "support", "implement", "protocol", "interface",
                   "instruction", "mode"],
    "verification": ["coverage", "assert", "testbench", "verify", "regression"],
    "test": ["scan", "atpg", "bist", "dft", "coverage", "fault"],
}


def _categorize(text):
    low = text.lower()
    best, hits = "functional", 0
    for cat, kws in _CATEGORIES.items():
        n = sum(1 for k in kws if k in low)
        if n > hits:
            best, hits = cat, n
    return best


def _normalize(params):
    reqs = params.get("requirements") or params.get("reqs")
    if not reqs:
        return _cde(objective="normalize requirements", status="failed",
                    error="no `requirements` provided (list of strings or objects)",
                    validation={"verdict": "fail"})
    if isinstance(reqs, str):
        reqs = [r.strip() for r in reqs.splitlines() if r.strip()]
    prefix = str(params.get("id_prefix") or "REQ")

    # IDENTITY IS RESOLVED BEFORE ANYTHING ELSE, AND IS NEVER POSITIONAL.
    # This was `"id": "%s-%03d" % (prefix, i)` over `enumerate(reqs, 1)` --
    # ordinals over INPUT LIST ORDER. Inserting a requirement in the middle
    # silently re-pointed every later identifier at a different requirement,
    # with nothing erroring because all the ids stayed well-formed and all still
    # resolved. A caller-supplied id is now authoritative; only an absent one is
    # derived, from content.
    _assign, _id_findings = req_identity.assign(reqs, prefix)
    _identity = req_identity.summary(_assign, _id_findings)
    _ids = {a["index"]: a for a in _assign}

    normalized, seen = [], {}
    dup, nonmeasurable = 0, 0
    unitless_thresholds = []
    for i, raw in enumerate(reqs):
        if isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("statement") or "")
            cat = raw.get("category") or _categorize(text)
        else:
            text, cat = str(raw), _categorize(str(raw))
        key = re.sub(r"\s+", " ", text.strip().lower())
        is_dup = key in seen
        if is_dup:
            dup += 1
        else:
            seen[key] = True
        measurable = bool(_MEASURABLE.search(text))
        if not measurable:
            nonmeasurable += 1
        # A THRESHOLD WITH NO UNIT. `_MEASURABLE` accepts a bare comparison
        # (`(<=|>=|<|>|=)\s*\d`), so "Latency shall be < 5." counts as
        # measurable -- less than five WHAT? Reported as ADVISORY, not gating,
        # because genuinely dimensionless requirements exist (counts, ratios,
        # error budgets); a reviewer must decide which this is.
        unitless = measurable and not _UNIT_BEARING.search(text)
        if unitless:
            unitless_thresholds.append(text.strip())
        _a = _ids[i]
        normalized.append({
            "id": _a["id"],
            "id_source": _a["source"],
            "text": text.strip(),
            "category": cat,
            "measurable": measurable,
            "duplicate_of": next((v for v in [None] if not is_dup), None)
            if not is_dup else "earlier requirement with identical text",
            "acceptance_criteria": text.strip() if measurable else
            "NEEDS MEASURABLE CRITERION",
        })
    spec_path = os.path.join(_OUTPUT_DIR, "specification.json")
    with open(spec_path, "w") as f:
        json.dump({"prefix": prefix, "requirements": normalized,
                   "identity": _identity}, f, indent=2)
    total = len(normalized)
    by_cat = {}
    for n in normalized:
        by_cat[n["category"]] = by_cat.get(n["category"], 0) + 1
    _id_gating = _identity["gating_findings"]
    if _id_gating:
        verdict = "fail"
    elif (nonmeasurable == 0 and dup == 0 and not _identity["derived"]
          and not unitless_thresholds):
        verdict = "pass"
    else:
        verdict = "pass_with_caveats"
    return _cde(
        objective="normalize %d requirement(s) into a design specification" % total,
        status="completed",
        # (A) GATING -- deterministic defect counts over the normalized set. Both
        # must reach zero. `requirements` is the POPULATION and is deliberately
        # NOT gating: declaring it would peg the residual at the requirement
        # count forever, and it is higher-is-better besides.
        results={"requirements": {
                     "value": total, "unit": "count",
                     "class": "diagnostic", "basis": "deterministic_normalization",
                     "note": ("POPULATION, not a residual. It is the denominator "
                              "for the defect counts below; declaring it as the "
                              "gate would make it unclosable by construction.")},
                 "non_measurable": {
                     "value": nonmeasurable, "unit": "count",
                     "class": "gating", "basis": "deterministic_normalization",
                     "closes_at": "== 0",
                     "note": ("A requirement with no measurable acceptance "
                              "criterion cannot be verified, so nothing "
                              "downstream can ever close against it.")},
                 "duplicates": {
                     "value": dup, "unit": "count",
                     "class": "gating", "basis": "deterministic_normalization",
                     "closes_at": "== 0"},
                 "identity_defects": {
                     "value": _id_gating, "unit": "count",
                     "class": "gating",
                     "basis": "caller_supplied_else_content_derived",
                     "closes_at": "== 0",
                     "note": ("Two requirements sharing an identifier, or an "
                              "identifier with no resolvable shape. An id is a "
                              "PROMISE that the name keeps pointing at the same "
                              "requirement; a collision makes every citation of "
                              "it ambiguous. Never auto-renamed -- renaming "
                              "would silently re-point one of them, which is the "
                              "defect this gate exists to catch.")},
                 "tool_assigned_ids": {
                     "value": _identity["derived"], "unit": "count",
                     "class": "diagnostic",
                     "basis": "caller_supplied_else_content_derived",
                     "note": ("Requirements that arrived with NO identifier, so "
                              "the tool derived one from their text. Adopt these "
                              "into the spec document: an id that lives only in "
                              "a tool output is not yet a stable name, and it "
                              "will change if the requirement text is edited.")},
                 "unitless_thresholds": {
                     "value": len(unitless_thresholds), "unit": "count",
                     "class": "diagnostic", "basis": "deterministic_normalization",
                     "note": ("Requirements stating a threshold with NO unit "
                              "(e.g. 'latency shall be < 5' -- less than five "
                              "WHAT). These satisfy the measurability gate, so "
                              "without this count they are invisible. "
                              "ADVISORY rather than gating: genuinely "
                              "dimensionless requirements exist (counts, "
                              "ratios, error budgets), and only a reviewer can "
                              "say which this is.")}},
        qor={"requirements": total, "non_measurable": nonmeasurable,
             "duplicates": dup, "by_category": by_cat},
        signoff={"requirements": total, "non_measurable": nonmeasurable,
                 "duplicates": dup, "by_category": by_cat,
                 "specification": "results/specification.json",
                 "identity": _identity,
                 "unitless_thresholds": unitless_thresholds or None,
                 # (B) DIAGNOSTIC -- measured, non-gating. The category spread is
                 # the authoring surface: it says WHERE the spec is thin.
                 "diagnostics": {
                     "class": "diagnostic", "basis": "deterministic_normalization",
                     "by_category": by_cat,
                     "requirements_total": total,
                     "non_measurable": nonmeasurable, "duplicates": dup,
                     "population_note": ("requirements_total is the denominator. "
                                         "Diagnostic, not descriptive: DELETING a "
                                         "troublesome requirement shrinks it and "
                                         "drops the defect count without the spec "
                                         "getting any better.")},
                 # (C) DESCRIPTIVE -- configuration, expected to hold steady.
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "prefix": prefix, "category_count": len(by_cat),
                     "engine": "deterministic normalization (no external tool)"},
                 # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), nonmeasurable,
                     "non_measurable")},
        inputs_ref={"requirement_count": total},
        assumptions=["measurability detected via units / comparison operators; "
                     "category inferred from keywords when not supplied"],
        validation={"verdict": verdict,
                    "note": ("all requirements measurable and unique"
                             if verdict == "pass" else
                             "%d non-measurable, %d duplicate requirement(s) flagged"
                             % (nonmeasurable, dup))},
        provenance={"specification": "results/specification.json"},
    )


def _ppa_budget(params):
    targets = params.get("targets") or {}
    blocks = params.get("blocks")
    if not targets:
        return _cde(objective="PPA budget", status="failed",
                    error="no `targets` provided (e.g. {area_um2, power_mw, freq_mhz})",
                    validation={"verdict": "fail"})
    if not blocks:
        return _cde(objective="PPA budget", status="failed",
                    error="no `blocks` provided (list of {name, weight?} or names)",
                    validation={"verdict": "fail"})
    if isinstance(blocks, str):
        blocks = [b.strip() for b in re.split(r"[,\n]", blocks) if b.strip()]
    norm_blocks = []
    weight_findings = []
    for b in blocks:
        if isinstance(b, dict):
            name = str(b.get("name"))
            try:
                w = float(b.get("weight", 1.0))
            except (TypeError, ValueError):
                weight_findings.append(
                    "block %r has non-numeric weight %r" % (name, b.get("weight")))
                w = 0.0
            # A NEGATIVE weight produced a NEGATIVE budget that still summed to
            # the target, so the closure check passed: measured, block 'b' was
            # allocated -500 um2 with verdict `pass`. A block cannot occupy
            # negative area or burn negative power.
            if w < 0:
                weight_findings.append(
                    "block %r has negative weight %g, which allocates a "
                    "negative budget; the closure check cannot catch it because "
                    "the parts still sum to the target" % (name, w))
            norm_blocks.append({"name": name, "weight": w})
        else:
            norm_blocks.append({"name": str(b), "weight": 1.0})
    raw_wsum = sum(b["weight"] for b in norm_blocks)
    if raw_wsum <= 0 and not weight_findings:
        weight_findings.append(
            "block weights sum to %g; there is no meaningful split to make"
            % raw_wsum)
    wsum = raw_wsum or 1.0

    # DIMENSIONAL PARSING. Was `_num(targets.get("area_um2") or ...)`, a regex
    # that grabbed the first number and discarded the rest -- so "12 mm2" was
    # recorded as 12 um2 (off by 1e6) and "1.2 GHz" as 1.2 MHz, both with
    # verdict `pass`. A field name records an intention, not a fact.
    tvals, unit_findings = units.parse_targets(targets, {
        "area_um2": ["area_um2", "area_mm2", "area"],
        "power_mw": ["power_mw", "power_w", "power"],
        "freq_mhz": ["freq_mhz", "freq_ghz", "frequency_mhz", "freq",
                     "frequency"],
    })
    unit_errors = [f for f in unit_findings if f["severity"] == "gating"]
    area = tvals["area_um2"]["value"] if "area_um2" in tvals else None
    power = tvals["power_mw"]["value"] if "power_mw" in tvals else None
    freq = tvals["freq_mhz"]["value"] if "freq_mhz" in tvals else None
    if unit_errors and area is None and power is None and freq is None:
        return _cde(
            objective="PPA budget", status="failed",
            error="no target could be parsed: " + "; ".join(
                f["detail"] for f in unit_errors),
            validation={"verdict": "fail"})
    # --- INTEGRATION RESERVE -------------------------------------------------
    # 100% of the top-level budget was previously handed to the blocks, so the
    # allocation ALWAYS closed exactly -- by construction. But a chip is not the
    # sum of its blocks: top-level interconnect, glue logic, clock tree, PDN and
    # spacing all consume area and power that no block owns. A budget with no
    # reserve is one every block can meet while the chip still misses.
    #
    # The reserve is CALLER-DECLARED and never defaulted: inventing, say, 10%
    # would silently shrink every block's budget by a number nobody chose. When
    # it is absent the allocation still proceeds, and the omission is reported.
    reserve_findings = []
    reserve_pct = params.get("integration_reserve_pct")
    if reserve_pct is None:
        reserve_pct = 0.0
        reserve_declared = False
        reserve_findings.append(
            "no integration_reserve_pct declared: 100% of the top-level budget "
            "is allocated to blocks, leaving nothing for top-level interconnect, "
            "glue logic, clock tree or PDN. Every block can then meet its budget "
            "while the chip misses.")
    else:
        reserve_declared = True
        try:
            reserve_pct = float(reserve_pct)
        except (TypeError, ValueError):
            return _cde(objective="PPA budget", status="failed",
                        error=f"integration_reserve_pct is not a number: "
                              f"{params.get('integration_reserve_pct')!r}",
                        validation={"verdict": "fail"})
        if not (0.0 <= reserve_pct < 100.0):
            return _cde(objective="PPA budget", status="failed",
                        error=f"integration_reserve_pct={reserve_pct} is outside "
                              f"[0, 100); a reserve of 100% leaves the blocks "
                              f"nothing",
                        validation={"verdict": "fail"})
    _dist = 1.0 - reserve_pct / 100.0
    reserve = {}
    if area is not None:
        reserve["area_um2"] = round(area * reserve_pct / 100.0, 3)
    if power is not None:
        reserve["power_mw"] = round(power * reserve_pct / 100.0, 4)
    allocation = []
    alloc_area = alloc_power = 0.0
    for b in norm_blocks:
        frac = b["weight"] / wsum
        row = {"name": b["name"], "fraction": round(frac, 4)}
        if area is not None:
            row["area_um2"] = round(area * _dist * frac, 3)
            alloc_area += row["area_um2"]
        if power is not None:
            row["power_mw"] = round(power * _dist * frac, 4)
            alloc_power += row["power_mw"]
        if freq is not None:
            row["freq_mhz"] = freq  # shared top-level constraint
        allocation.append(row)
    budget_path = os.path.join(_OUTPUT_DIR, "ppa_budget.json")
    with open(budget_path, "w") as f:
        json.dump({"targets": targets,
                   "targets_parsed": tvals,
                   "integration_reserve_pct": reserve_pct,
                   "integration_reserve": reserve,
                   "allocation": allocation}, f, indent=2)
    closes = True
    notes = []
    # Blocks + reserve must reconstitute the target.
    if area is not None:
        _tot_a = alloc_area + reserve.get("area_um2", 0.0)
        if abs(_tot_a - area) > 1e-6 * max(1.0, area):
            closes = False
            notes.append("area allocation %.3f + reserve %.3f != target %.3f"
                         % (alloc_area, reserve.get("area_um2", 0.0), area))
    if power is not None:
        _tot_p = alloc_power + reserve.get("power_mw", 0.0)
        if abs(_tot_p - power) > 1e-6 * max(1.0, power):
            closes = False
            notes.append("power allocation %.4f + reserve %.4f != target %.4f"
                         % (alloc_power, reserve.get("power_mw", 0.0), power))
    for f_ in unit_errors:
        notes.append(f_["detail"])
    notes.extend(weight_findings)
    notes.extend(reserve_findings)
    # Closure alone was never sufficient: a mis-scaled target and a negative
    # weight both CLOSE perfectly, because closure only checks that the parts
    # sum to the whole -- not that the whole was the right number.
    if not closes or unit_errors or weight_findings:
        verdict = "fail"
    elif not reserve_declared:
        # The split is arithmetically sound but reserves nothing for the parts of
        # the chip that belong to no block. Not a fabricated failure; a stated
        # gap the caller must close.
        verdict = "review"
    else:
        verdict = "pass"
    return _cde(
        objective="allocate PPA budget across %d block(s)" % len(norm_blocks),
        status="completed",
        results={"blocks": {"value": len(norm_blocks), "unit": "count"},
                 "target_defects": {
                     "value": len(unit_errors) + len(weight_findings),
                     "unit": "count", "class": "gating",
                     "basis": "dimensional_parse", "closes_at": "== 0",
                     "note": ("A target whose unit cannot be reconciled with "
                              "its field, or a weight that allocates a "
                              "negative budget. Both CLOSE additively, so the "
                              "closure check cannot detect either: a number "
                              "wrong by 1e6 looks exactly like a number that "
                              "is right.")},
                 "allocated_area_um2": {"value": round(alloc_area, 3), "unit": "um2"}
                 if area is not None else {"value": "n/a", "unit": "-"},
                 "allocated_power_mw": {"value": round(alloc_power, 4), "unit": "mw"}
                 if power is not None else {"value": "n/a", "unit": "-"}},
        qor={"blocks": len(norm_blocks), "closes": closes,
             "target_freq_mhz": freq,
             "integration_reserve_pct": reserve_pct,
             "integration_reserve_declared": reserve_declared},
        signoff={"allocation": allocation, "closes": closes,
                 "budget": "results/ppa_budget.json",
                 "integration_reserve_pct": reserve_pct,
                 "integration_reserve": reserve,
                 "integration_reserve_declared": reserve_declared,
                 "integration_reserve_note": (
                     "the reserve covers top-level interconnect, glue logic, "
                     "clock tree and PDN -- everything that belongs to no block. "
                     "It is never defaulted, because an invented percentage "
                     "would silently shrink every block's budget."),
                 "targets_parsed": tvals,
                 "unit_findings": unit_findings or None,
                 "weight_findings": weight_findings or None,
                 "units_note": ("Every target is parsed into an explicit "
                                "(magnitude, unit) pair and converted to the "
                                "field's canonical unit. A unit of the wrong "
                                "dimension, a value with no unit in a field "
                                "whose name states none, or a string holding "
                                "more than one number is REFUSED rather than "
                                "coerced.")},
        inputs_ref={"targets": targets, "block_count": len(norm_blocks)},
        assumptions=["area/power split additively by block weight; frequency is a "
                     "shared top-level constraint applied to every block",
                     "every target is parsed dimensionally and converted to a "
                     "canonical unit (um2 / mW / MHz); a unit of the wrong "
                     "dimension is refused rather than coerced"],
        validation={"verdict": verdict,
                    # A `review` verdict must say WHY. Reporting "budget closes"
                    # whenever the arithmetic worked hid every non-arithmetic
                    # finding behind a reassuring sentence.
                    "note": ("; ".join(notes) if notes
                             else "budget closes against top-level targets, with "
                                  "an explicit integration reserve")},
        provenance={"budget": "results/ppa_budget.json"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("normalize", "requirements", "spec"):
        return _normalize(params)
    if s in ("ppa_budget", "budget", "ppa"):
        return _ppa_budget(params)
    return _cde(objective="design intent", status="failed",
                error="unknown scenario '%s'; supported: normalize, ppa_budget" % s,
                validation={"verdict": "fail"})


# --- attempt capture (BEGIN) -- vendored by catalog/migrate_attempt_capture.py
# Records WHAT THE STAGE WAS ASKED TO DO alongside what it measured, so that an
# attempt chain (stage.1 -> stage.N) can be mined for which knob actually moved the
# residual. Without it a CDE says the residual fell from 102 to 9 but not why, and
# the causal knowledge is lost the moment the run ends.
#
# Hooked as wrappers rather than edits to dispatch()/save_final_results() so this
# migration never has to understand tool-specific code.
_ATTEMPT_CAPTURE = {}

#: Substrings that mark a value as secret. Envelopes are committed to git, so a
#: credential that reaches one is durable and public. Narrow on purpose: a broad
#: "key" match would redact legitimate EDA parameters (`clock_key`, `map_key`).
_CAPTURE_SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key",
                         "apikey", "credential", "private_key", "auth")

_CAPTURE_MAX_STR = 512
_CAPTURE_MAX_SEQ = 64
_CAPTURE_MAX_DEPTH = 6


def _capture_digest(obj):
    import hashlib
    import json as _json
    try:
        blob = _json.dumps(obj, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = repr(obj)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def _capture_head(value, limit=120):
    """Truncate an excerpt on a LINE boundary so it never ends mid-token.

    A raw byte slice cuts wherever the count lands, and 120 bytes into this
    campaign's RTL lands inside `campaigns/.../spec.3/reports/bsum16.md`, leaving
    `campaigns/.../spec.3/repor`. The publication citation scanner reads any
    path-shaped string as a citation, so the excerpt turns a real reference into a
    dangling one and blocks the whole publication transaction -- a provenance
    failure manufactured entirely by the truncation.
    """
    if len(value) <= limit:
        return value
    window = value[:limit]
    cut = window.rfind("\n")
    if cut <= 0:
        cut = max(window.rfind(" "), window.rfind("\t"))
    if cut <= 0:
        # One unbroken token wider than the window: nothing to cut back to.
        return window
    return window[:cut]


def _capture_normalize(value, depth=0):
    """Bound the size of a captured value without losing change-detection.

    Elision keeps a sha256 of the ELIDED PART, so a parameter that changed between
    two attempts still shows a different hash even when its content is too big to
    store. Silently dropping it would make the delta look empty -- i.e. would
    report "nothing changed" for a run that changed something.
    """
    if depth > _CAPTURE_MAX_DEPTH:
        return {"_elided": "depth", "sha256": _capture_digest(value)}
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _CAPTURE_MAX_STR:
            return {"_elided": "str", "chars": len(value),
                    "sha256": _capture_digest(value),
                    "head": _capture_head(value)}
        return value
    if isinstance(value, dict):
        out = {}
        for key in list(value)[:_CAPTURE_MAX_SEQ]:
            low = str(key).lower()
            if any(hint in low for hint in _CAPTURE_SECRET_HINTS):
                out[key] = {"_redacted": "secret-like key"}
                continue
            out[key] = _capture_normalize(value[key], depth + 1)
        if len(value) > _CAPTURE_MAX_SEQ:
            out["_elided"] = {"keys": len(value), "sha256": _capture_digest(value)}
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > _CAPTURE_MAX_SEQ:
            return {"_elided": "list", "len": len(value),
                    "sha256": _capture_digest(value),
                    "head": [_capture_normalize(v, depth + 1) for v in value[:8]]}
        return [_capture_normalize(v, depth + 1) for v in value]
    return {"_elided": type(value).__name__, "sha256": _capture_digest(value)}


def _capture_params(params):
    import datetime
    if not isinstance(params, dict):
        return
    intent = params.get("attempt_intent")
    _ATTEMPT_CAPTURE.clear()
    _ATTEMPT_CAPTURE.update({
        "schema": "attempt-capture/1",
        # Hash the RAW params, before elision -- see _capture_normalize.
        "parameters_sha256": _capture_digest(params),
        "parameters": _capture_normalize(params),
        "intent": intent or None,
        "intent_missing": not bool(intent),
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


try:
    _dispatch_undecorated = dispatch

    def dispatch(params):  # noqa: F811
        _capture_params(params)
        return _dispatch_undecorated(params)
except NameError:  # pragma: no cover - a tool without dispatch()
    pass


try:
    _save_final_results_undecorated = save_final_results

    def save_final_results(results):  # noqa: F811
        if isinstance(results, dict):
            # Fall back to the fail-closed path's own copy: run.py sets
            # `input_parameters` when it fails BEFORE dispatch, which is exactly
            # when _ATTEMPT_CAPTURE would otherwise be empty.
            if not _ATTEMPT_CAPTURE and isinstance(
                    results.get("input_parameters"), dict):
                _capture_params(results["input_parameters"])
            if _ATTEMPT_CAPTURE:
                results.setdefault("attempt_capture", dict(_ATTEMPT_CAPTURE))
        return _save_final_results_undecorated(results)
except NameError:  # pragma: no cover - a tool without save_final_results()
    pass
# --- attempt capture (END) ---
