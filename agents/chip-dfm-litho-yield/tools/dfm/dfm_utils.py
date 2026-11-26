#!/usr/bin/env python3
"""dfm_utils.py -- DFM / lithography / yield screening for the chip-dfm tool.

Screens recommended-rule (DFM) findings (via redundancy, density windows), flags
litho hotspots, and estimates critical-area yield with a Poisson defect model
Y = exp(-sum(A_i * D_i)). DFM is distinct from mandatory DRC. Node-aware. Results
conform to the Common Design Envelope.
"""
import json
import math
import os

import layout_geometry

TOOL = "dfm"
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


def quick_setup(output_dir="/output", work_dir="/workdir"):
    global _OUTPUT_DIR, _WORK_DIR
    output_dir = _env_dir(output_dir, "CHIP_OUTPUT_DIR", "OUTPUT_DIR")
    work_dir = _env_dir(work_dir, "CHIP_WORK_DIR", "WORK_DIR")
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
    L = ["# " + tool + " — human summary", ""]
    L.append("- **Status:** " + status.upper())
    if r.get("objective"):
        L.append("- **Objective:** " + str(r["objective"]))
    val = r.get("validation") or {}
    if isinstance(val, dict) and val.get("verdict"):
        note = (" — " + str(val["note"])) if val.get("note") else ""
        L.append("- **Verdict:** " + str(val["verdict"]) + note)
    if r.get("error"):
        L += ["", "> **Error:** " + str(r["error"])]
    for title, key in (("Key metrics", "qor_metrics"),
                       ("Results", "results"),
                       ("Signoff evidence", "signoff_evidence")):
        d = r.get(key)
        if isinstance(d, dict) and d:
            rows = _report_kv_rows(d)
            if rows:
                L += ["", "## " + title, "", "| Metric | Value |", "| --- | --- |"] + rows
    tu = r.get("tools_used")
    if isinstance(tu, list) and tu:
        names = []
        for t in tu:
            if isinstance(t, dict):
                names.append((str(t.get("name", "?")) + " " + str(t.get("version", ""))).strip())
            else:
                names.append(str(t))
        L += ["", "## Tools", "", ", ".join(names)]
    prov = r.get("provenance") or {}
    if isinstance(prov, dict) and prov.get("runtime_s") is not None:
        L += ["", "_Runtime: " + str(prov["runtime_s"]) + " s_"]
    L += ["", "_Full machine-readable envelope: `common_design_envelope.json`._", ""]
    return "\n".join(L)


def _write_report_md(results):
    path = os.path.join(_OUTPUT_DIR, "REPORT.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render_report_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def _organize_output():
    """Split the flat /output dir into the skill's results/reports/logs layout,
    in-container, so every run is born conformant (no external post-processing).

    - final_results.json stays at the attempt root (downstream + skill expect it).
    - reports/  <- *.rpt, *.md (REPORT/EXECUTIVE_SUMMARY/TOOL_REPORT), *_report.json, *.csv
    - logs/     <- *.log, *.tcl, *.ys, *.sp, *.sh, *.do, run_command.txt, *.txt
    - results/  <- everything else (*.def, *.spef, netlists, *.lef, *.lib, *.gds,
                  *.sdf, *.upf, *.sv, *.py, data *.json, ...)  == next-stage inputs
    Idempotent: re-running finds only final_results.json + the 3 subdirs at root."""
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
                or low.endswith("_report.json") or low == "verify_report.json"
                or low.endswith(".csv")):
            return "reports"
        if (low.endswith((".log", ".tcl", ".ys", ".sp", ".sh", ".do"))
                or low == "run_command.txt" or low.endswith(".txt")):
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
    """Read-me-first summary for the stage-version root: what was done, the verdict,
    key results, insights/caveats, provenance, and where to find detail. Built from
    the Common Design Envelope the tool already produced."""
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
    tu = r.get("tools_used")
    if isinstance(tu, list) and tu:
        names = []
        for t in tu:
            if isinstance(t, dict):
                names.append((str(t.get("name", "?")) + " " + str(t.get("version", ""))).strip())
            else:
                names.append(str(t))
        L += ["_Tools:_ " + ", ".join(names), ""]
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
    insights = []
    for k in ("key_insights", "insights", "findings", "caveats", "assumptions", "notes"):
        v = r.get(k)
        if isinstance(v, list):
            insights += [str(x) for x in v if x]
        elif isinstance(v, str) and v.strip():
            insights.append(v.strip())
    if insights:
        L += ["## Key insights & caveats", ""] + ["- " + s for s in insights] + [""]
    prov = r.get("provenance") or {}
    plines = []
    if isinstance(prov, dict) and prov.get("runtime_s") is not None:
        plines.append("- Runtime: " + str(prov["runtime_s"]) + " s")
    pb = r.get("pdk_binding")
    if pb and pb != "none":
        plines.append("- PDK binding: " + (str(pb) if not isinstance(pb, dict) else str(pb.get("pdk", pb))))
    iref = r.get("inputs_ref")
    if isinstance(iref, dict) and iref:
        plines.append("- Upstream inputs: " + ", ".join(sorted(str(k) for k in iref.keys())))
    if plines:
        L += ["## Provenance", ""] + plines + [""]
    L += ["## Where to find more", "",
          "- `common_design_envelope.json` \u2014 full machine-readable envelope (this dir)",
          "- `results/` \u2014 machine artifacts consumed by the next stage",
          "- `reports/` \u2014 detailed reports (`REPORT.md`, tables, `*.rpt`)",
          "- `logs/` \u2014 verbatim tool logs and the exact run command", ""]
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
    try:
        _write_report_md(results)
    except Exception as _rep_e:
        print("[" + str(TOOL) + "] report generation skipped: " + str(_rep_e), flush=True)
    try:
        _write_summary_md(results)
    except Exception as _sum_e:
        print("[" + str(TOOL) + "] summary generation skipped: " + str(_sum_e), flush=True)
    try:
        _organize_output()
    except Exception as _org_e:
        print("[" + str(TOOL) + "] output organize skipped: " + str(_org_e), flush=True)


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         assumptions=None, validation=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "dfm-screen", "version": "1.0.0"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "screening"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic DFM/yield screen"},
    }
    if error:
        env["error"] = error
    return env


def _rule_windows(params):
    """Resolve DFM windows from the PDK BINDING, never from a default.

    design-policy.yaml declares `missing_decks: block`, and the tool previously
    could not honour that because it never opened a deck: the thresholds were
    two literals in the source (via redundancy 0.9, density 0.2-0.7) labelled
    "illustrative". An illustrative threshold that gates a manufacturability
    result is a number the foundry never agreed to.
    """
    b = params.get("pdk_binding") or {}
    if not isinstance(b, dict):
        return None, "pdk_binding is not an object"
    rules = (b.get("dfm_rules") or b.get("recommended_rules")
             or params.get("dfm_rules"))
    if not rules:
        return None, ("no dfm_rules/recommended_rules in the PDK binding. The "
                      "node's density window and via-redundancy target are NOT "
                      "defaulted -- screening against an invented window would "
                      "report compliance with a rule that does not exist")
    return rules, None


def _dfm_check(params):
    rules, why = _rule_windows(params)
    if rules is None:
        return _cde(objective="DFM / recommended-rule screen", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="missing DFM rule deck: %s" % why,
                    results={"findings": {
                        "value": None, "unit": "count", "class": "gating",
                        "basis": "not_assessed", "closes_at": "== 0",
                        "note": ("NULL because no deck was available. Absence of "
                                 "findings here means nothing was checked.")}},
                    validation={"verdict": "fail",
                                "note": ("design-policy declares missing_decks: "
                                         "block, and this run has no deck")})

    dens_win = rules.get("density_window") or {}
    dmin, dmax = dens_win.get("min"), dens_win.get("max")
    win_um = dens_win.get("window_um")
    via_target = rules.get("via_redundancy_min")

    findings, measured, notes = [], {}, []
    layout = params.get("layout") or params.get("gds")

    # --- DENSITY: measured from the layout when one is supplied -------------
    if layout and dmin is not None and dmax is not None and win_um:
        try:
            ly = layout_geometry.load(layout)
            for spec in (rules.get("layers") or []):
                lname = spec.get("name", str(spec.get("layer")))
                d = layout_geometry.windowed_density(
                    ly, spec["layer"], win_um, step_um=dens_win.get("step_um"),
                    datatype=spec.get("datatype", 0))
                measured[lname] = d
                if not d.get("assessable"):
                    notes.append("%s: %s" % (lname, d.get("note")))
                    continue
                for w in d["windows"]:
                    if w["density"] is None:
                        continue
                    if w["density"] < dmin or w["density"] > dmax:
                        findings.append({
                            "layer": lname, "rule": "pattern_density",
                            "value": w["density"],
                            "at_um": [w["x_um"], w["y_um"]],
                            "recommended": "%s-%s in a %sum window"
                                           % (dmin, dmax, win_um),
                            "basis": "klayout_windowed_density",
                            "disposition": "adjust fill in this window"})
        except layout_geometry.LayoutUnavailable as e:
            return _cde(objective="DFM / recommended-rule screen", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error="layout could not be read: %s" % e,
                        validation={"verdict": "fail",
                                    "note": "no geometry, so nothing was screened"})

    # --- VIA REDUNDANCY: from supplied counts, labelled as supplied ---------
    metrics = params.get("metrics", {})
    for layer, m in (metrics or {}).items():
        if via_target is None:
            break
        sv, rv = m.get("single_via_count"), m.get("redundant_via_count")
        if sv is None or rv is None:
            continue
        total = sv + rv
        if not total:
            continue
        ratio = rv / total
        if ratio < float(via_target):
            findings.append({"layer": layer, "rule": "via_redundancy",
                             "value": round(ratio, 3),
                             "recommended": ">= %s" % via_target,
                             "basis": "caller_supplied_counts",
                             "disposition": "add redundant vias"})

    # A finding is dispositioned when it CARRIES a disposition -- previously
    # `"dispositioned": True` was a hardcoded literal asserting that every
    # finding had been dealt with, while nothing dispositioned anything.
    undispositioned = [f for f in findings if not f.get("disposition")]
    density_assessed = bool(measured) and any(
        v.get("assessable") for v in measured.values())
    assessed = density_assessed or bool(metrics)

    if notes:
        verdict, vnote = "not_assessable", (
            "required density layers were not screened: " + "; ".join(notes))
    elif not assessed:
        verdict, vnote = "not_assessable", (
            "a rule deck was resolved, but no layout and no metrics were "
            "supplied, so NOTHING was screened")
    elif findings:
        verdict, vnote = "pass_with_caveats", (
            "%d recommended-rule finding(s); these are DFM recommendations, "
            "distinct from mandatory DRC" % len(findings))
    else:
        verdict, vnote = "pass", "no recommended-rule findings in what was screened"

    return _cde(objective="DFM / recommended-rule screen",
                status="completed" if assessed else "failed",
                pdk_binding=params.get("pdk_binding", "none"),
                results={
                    "findings": {
                        "value": len(findings) if assessed else None,
                        "unit": "count", "class": "gating", "closes_at": "== 0",
                        "basis": ("klayout_windowed_density" if density_assessed
                                  else "caller_supplied_metrics" if metrics
                                  else "not_assessed"),
                        "note": ("Recommended-rule findings. NULL means nothing "
                                 "was screened, which is not the same as zero.")},
                    "undispositioned_findings": {
                        "value": len(undispositioned) if assessed else None,
                        "unit": "count", "class": "gating", "closes_at": "== 0",
                        "basis": "per_finding_disposition_field",
                        "note": ("design-policy declares disposition_every_finding. "
                                 "Counted from the disposition actually attached "
                                 "to each finding, not asserted.")}},
                signoff={"dfm_findings": findings,
                         "undispositioned": undispositioned,
                         "density_measured": measured or None,
                         "rules_source": "pdk_binding",
                         "rules_applied": {"density_window": dens_win,
                                           "via_redundancy_min": via_target},
                         "unscreened": notes or None,
                         "note": "recommended rules; distinct from mandatory DRC"},
                assumptions=[
                    "density windows and the via-redundancy target come from the "
                    "PDK binding and are never defaulted",
                    "density is measured PER WINDOW from the layout: a die-average "
                    "can sit mid-window while individual windows are far outside it",
                    "via redundancy is computed from caller-supplied counts and is "
                    "labelled as such, not measured from geometry"],
                validation={"verdict": verdict, "note": vnote})


def _yield_analysis(params):
    ca = params.get("critical_area_um2", {})
    dd = (params.get("pdk_binding") or {}).get("defect_density", {})
    if not ca or not dd:
        return _cde(objective="yield analysis", status="failed",
                    error="need critical_area_um2 and pdk_binding.defect_density",
                    validation={"verdict": "fail"})
    # Convert um^2 to cm^2: 1 um^2 = 1e-8 cm^2. D in defects/cm^2.
    #
    # *** A DROPPED TERM RAISES THE REPORTED YIELD. ***
    # This loop used to `continue` past any defect size with no density, which
    # shrinks lambda -- and since Y = exp(-lambda), a SMALLER lambda is a HIGHER
    # yield. Missing data therefore made the design look better, silently, with
    # a "completed" verdict and no indication that anything had been skipped.
    # Unpriced sizes are now collected and gated on instead.
    lam = 0.0
    terms = []
    unpriced = []
    for size, area_um2 in ca.items():
        d = dd.get(size)
        if d is None:
            unpriced.append({"defect_size_um": size,
                             "critical_area_um2": area_um2,
                             "why": ("no defect density for this size in the PDK "
                                     "binding, so its contribution to lambda is "
                                     "UNKNOWN -- omitting it would raise the "
                                     "reported yield")})
            continue
        a_cm2 = float(area_um2) * 1e-8
        t = a_cm2 * float(d)
        lam += t
        terms.append({"defect_size_um": size, "critical_area_um2": area_um2,
                      "defect_density_per_cm2": d, "lambda_term": t})
    y = math.exp(-lam)

    if unpriced:
        verdict, vnote, status = "not_assessable", (
            "%d of %d defect size(s) have critical area but NO defect density, "
            "so lambda is a LOWER BOUND and the yield below is an UPPER BOUND, "
            "not an estimate: %s"
            % (len(unpriced), len(ca),
               ", ".join(str(u["defect_size_um"]) for u in unpriced))), "failed"
    elif not terms:
        verdict, vnote, status = "not_assessable", (
            "no defect size could be priced; nothing was computed"), "failed"
    else:
        verdict, vnote, status = "completed", (
            "all %d supplied defect size(s) priced" % len(terms)), "completed"

    return _cde(objective="critical-area yield estimation", status=status,
                pdk_binding=params.get("pdk_binding", "none"),
                results={
                    "yield": {
                        "value": round(100.0 * y, 3), "unit": "percent",
                        "class": "diagnostic",
                        "basis": "poisson_critical_area_model",
                        "note": ("UPPER BOUND, not an estimate, whenever "
                                 "unpriced_defect_sizes is non-zero: every "
                                 "missing term can only increase lambda and so "
                                 "only decrease the true yield."
                                 if unpriced else
                                 "all supplied defect sizes contributed a term")},
                    "lambda": {"value": round(lam, 6), "unit": "defects",
                               "class": "diagnostic",
                               "basis": "poisson_critical_area_model"},
                    "unpriced_defect_sizes": {
                        "value": len(unpriced), "unit": "count",
                        "class": "gating", "closes_at": "== 0",
                        "basis": "defect_density_lookup",
                        "note": ("Defect sizes with a critical area but no "
                                 "density. Gating because dropping a term "
                                 "RAISES the reported yield -- missing data "
                                 "must never make a design look better.")}},
                qor={"yield_percent": round(100.0 * y, 3)},
                signoff={"method": "Poisson critical-area model Y=exp(-sum(A_i*D_i))",
                         "terms": terms,
                         "unpriced": unpriced or None,
                         "yield_is_upper_bound": bool(unpriced)},
                assumptions=["Poisson defect model; critical areas and defect "
                             "densities supplied per defect size",
                             "a defect size with no density is reported as "
                             "unpriced and gates the run; it is never dropped, "
                             "because dropping it would raise the yield"],
                validation={"verdict": verdict, "note": vnote})


def _litho(params):
    """Geometric litho-risk screen on the real layout.

    THIS REPLACES THE PUREST FAIL-OPEN IN THE CATALOG. The previous body was:

        hotspots = params.get("hotspots", [])
        "opc_ready": len(hotspots) == 0
        verdict = "pass" if not hotspots

    -- supply no hotspots, and the tool declared the design OPC-ready and passed
    the gate. Not a check that silently passed: A CLAIM MANUFACTURED FROM THE
    ABSENCE OF INPUT.

    `opc_ready` is now not emitted at all, by any code path. OPC-readiness is
    established by comparing a SIMULATED PRINTED IMAGE against intent, which
    needs a calibrated optical and resist model. Screening drawn geometry cannot
    establish it, so the honest report is the hotspot list plus an explicit
    statement of what was not evaluated.
    """
    layout = params.get("layout") or params.get("gds")
    binding = params.get("pdk_binding") or {}
    decks = (binding.get("litho_decks") or binding.get("litho_rules")
             or params.get("litho_rules"))

    if not layout:
        return _cde(
            objective="lithography hotspot screen", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            error=("no layout supplied: litho screening requires GEOMETRY. "
                   "Hotspots are measured from the layout, never accepted as a "
                   "caller-supplied list"),
            results={"litho_hotspots": {
                "value": None, "unit": "count", "class": "gating",
                "closes_at": "== 0", "basis": "not_assessed",
                "note": "NULL: no layout was examined."}},
            signoff={"out_of_scope": layout_geometry.OUT_OF_SCOPE},
            validation={"verdict": "fail",
                        "note": "nothing was screened"})
    if not decks:
        return _cde(
            objective="lithography hotspot screen", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            error=("no litho_decks in the PDK binding. Printability limits are "
                   "node constants and are never defaulted -- an invented limit "
                   "would declare the design clean against a number the foundry "
                   "never specified"),
            results={"litho_hotspots": {
                "value": None, "unit": "count", "class": "gating",
                "closes_at": "== 0", "basis": "not_assessed",
                "note": "NULL: no printability limits were available."}},
            signoff={"out_of_scope": layout_geometry.OUT_OF_SCOPE},
            validation={"verdict": "fail",
                        "note": ("design-policy declares missing_decks: block")})

    try:
        ly = layout_geometry.load(layout)
    except layout_geometry.LayoutUnavailable as e:
        return _cde(objective="lithography hotspot screen", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=str(e),
                    signoff={"out_of_scope": layout_geometry.OUT_OF_SCOPE},
                    validation={"verdict": "fail",
                                "note": "no geometry, so nothing was screened"})

    per_layer, total, unscreened = [], 0, []
    for spec in (decks.get("layers") if isinstance(decks, dict) else decks) or []:
        res = layout_geometry.screen_litho_patterns(
            ly, spec["layer"], spec.get("rules", spec),
            datatype=spec.get("datatype", 0))
        per_layer.append(res)
        if res.get("assessable"):
            total += res["hotspot_count"]
        else:
            unscreened.append({"layer": spec.get("layer"),
                               "why": res.get("note")})

    screened_any = any(r.get("assessable") for r in per_layer)
    if not screened_any:
        verdict, vnote, value = "not_assessable", (
            "no layer could be screened; a hotspot count of zero here would "
            "mean 'nothing was examined', not 'nothing is wrong'"), None
    elif unscreened:
        verdict, vnote, value = "pass_with_caveats" if not total else "fail", (
            "%d hotspot(s) on the layers screened; %d layer(s) were NOT "
            "screened and are unknown" % (total, len(unscreened))), total
    elif total:
        verdict, vnote, value = "fail", (
            "%d geometric litho-risk pattern(s) found" % total), total
    else:
        verdict, vnote, value = "pass", (
            "no geometric litho-risk patterns on any screened layer"), 0

    return _cde(
        objective="lithography hotspot screen",
        status="completed" if screened_any else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={
            "litho_hotspots": {
                "value": value, "unit": "count", "class": "gating",
                "closes_at": "== 0",
                "basis": "klayout_geometric_pattern_screen",
                "note": ("Measured from the layout: features narrower than the "
                         "printability limit, gaps below the resolution limit, "
                         "notches, isolated features. NULL means nothing was "
                         "screened.")},
            "unscreened_layers": {
                "value": len(unscreened), "unit": "count",
                "class": "gating", "closes_at": "== 0",
                "basis": "per_layer_screen_status",
                "note": ("Layers absent from the layout or with no supplied "
                         "limits. Gating: an unscreened layer is unknown, and "
                         "must not be carried as clean.")}},
        signoff={"per_layer": per_layer,
                 "unscreened": unscreened or None,
                 "out_of_scope": layout_geometry.OUT_OF_SCOPE,
                 "note": ("Geometric (drawn-pattern) screening only. This tool "
                          "does NOT emit an OPC-readiness verdict: OPC is "
                          "verified against a simulated printed image, which "
                          "requires a calibrated optical and resist model.")},
        assumptions=[
            "hotspots are MEASURED from layout geometry; a caller-supplied "
            "hotspot list is not accepted as evidence",
            "printability limits come from the PDK binding and are never "
            "defaulted",
            "aerial-image, resist, process-window and OPC/RET verification are "
            "OUT OF SCOPE and are reported as such, never as clean"],
        validation={"verdict": verdict, "note": vnote})


def dispatch(params):
    s = params.get("scenario")
    if s == "dfm_check":
        return _dfm_check(params)
    if s == "yield_analysis":
        return _yield_analysis(params)
    if s == "litho_hotspot":
        return _litho(params)
    return _cde(objective="dfm", status="failed",
                error=f"unknown scenario '{s}'", validation={"verdict": "fail"})


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
                    "sha256": _capture_digest(value), "head": value[:120]}
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
