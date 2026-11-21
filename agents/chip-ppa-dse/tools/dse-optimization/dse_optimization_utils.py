#!/usr/bin/env python3
"""dse_optimization_utils.py -- deterministic PPA design-space exploration.

Computes a Pareto front over supplied flow-run points, ranks knob sensitivity, and
recommends a within-budget recipe. Every point must reference a source CDE (no
invented data; no learned surrogate). Node-aware. Results conform to the CDE.
"""
import json
import os

TOOL = "dse-optimization"
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
         assumptions=None, validation=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "dse", "version": "1.0.0"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "pareto"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic Pareto search"},
    }
    if error:
        env["error"] = error
    return env


def _dominates(a, b, objectives):
    better_any = False
    for o in objectives:
        m, goal = o["metric"], o["goal"]
        av, bv = a["metrics"].get(m), b["metrics"].get(m)
        if av is None or bv is None:
            return False
        if goal == "max":
            if av < bv:
                return False
            if av > bv:
                better_any = True
        else:
            if av > bv:
                return False
            if av < bv:
                better_any = True
    return better_any


def _explore(params):
    import hashlib
    import math

    points = params.get("points", [])
    objectives = params.get("objectives", [])
    if not points or not objectives:
        return _cde(objective="PPA design-space exploration", status="failed",
                    error="need 'points' and 'objectives'", validation={"verdict": "fail"})
    missing = [i for i, p in enumerate(points) if not p.get("source_cde")]
    if missing:
        return _cde(objective="PPA design-space exploration", status="failed",
                    error="every point must reference a source_cde (indices: "
                          + ",".join(map(str, missing)) + ")",
                    validation={"verdict": "fail"})
    rejected = []
    verified = []
    required = {o["metric"] for o in objectives} | set(params.get("budget", {}))
    for index, point in enumerate(points):
        source = point["source_cde"]
        record = {"point": index, "source_cde": source}
        try:
            with open(source, "rb") as stream:
                data = stream.read()
            digest = hashlib.sha256(data).hexdigest()
            if not point.get("source_cde_sha256") or point["source_cde_sha256"] != digest:
                record.update(kind="integrity", reason="source CDE file SHA256 absent or mismatched")
                rejected.append(record)
                continue
            cde = json.loads(data)
        except Exception as error:
            record.update(kind="unavailable", reason="source CDE cannot be loaded: " + str(error))
            rejected.append(record)
            continue
        progress = cde.get("progress") or {}
        if (cde.get("status") != "completed"
                or cde.get("validation", {}).get("verdict") != "pass"
                or progress.get("gate_closed") is not True
                or progress.get("alignment_severity") == "blocking"):
            record.update(kind="upstream_gate", reason="upstream acceptance is not validated/closed",
                          source_status=cde.get("status"),
                          source_verdict=cde.get("validation", {}).get("verdict"),
                          source_progress=progress)
            rejected.append(record)
            continue
        metrics = point.get("metrics") or {}
        problems = []
        for metric in required | set(metrics):
            actual = cde.get("qor_metrics", {}).get(metric)
            node = cde.get("results", {}).get(metric, {})
            if actual is None:
                key = {"cell_area_um2": "cell_area"}.get(metric, metric)
                node = cde.get("results", {}).get(key, {})
                actual = node.get("value") if isinstance(node, dict) else node
            claimed = metrics.get(metric)
            if (isinstance(actual, bool) or not isinstance(actual, (int, float))
                    or not math.isfinite(actual) or isinstance(claimed, bool)
                    or not isinstance(claimed, (int, float))
                    or not math.isfinite(claimed) or actual != claimed):
                problems.append(metric + ": claimed metric is missing/nonfinite or differs from source CDE")
            elif metric.startswith("estimated_") or (
                    isinstance(node, dict) and node.get("basis") in
                    ("synthesis_internal_estimate", "analytic_model", "model_authored")):
                problems.append(metric + ": estimate/model output is not a measured objective")
        if problems:
            record.update(kind="metrics", reason="; ".join(problems))
            rejected.append(record)
        else:
            verified.append(dict(point=index, source_cde=source, source_cde_sha256=digest,
                                 source_gate_closed=True, measured_metrics=dict(metrics)))
    if rejected:
        verdict = "fail" if any(r["kind"] in ("integrity", "metrics") for r in rejected) else "not_assessable"
        return _cde(
            objective="source-validated PPA design-space exploration", status="completed",
            pdk_binding=params.get("pdk_binding", "none"),
            qor={"recommended_recipe": None, "recommended_metrics": None,
                 "recommendation_feasible": False, "within_budget": False},
            signoff={"rejected_sources": rejected, "verified_sources": verified,
                     "recommended": None},
            inputs_ref={"source_cdes": [p["source_cde"] for p in points]},
            validation={"verdict": verdict,
                        "note": "Search/recommendation blocked: every source must be loaded, hash-matched, acceptance-closed and metric-matched."})
    pareto = []
    for p in points:
        if not any(_dominates(q, p, objectives) for q in points if q is not p):
            pareto.append(p)
    # budget filter for the recommendation
    budget = params.get("budget", {})

    def within(p):
        for k, v in budget.items():
            mv = p["metrics"].get(k)
            # treat budget as a min target for max-goal metrics, else a max cap
            goal = next((o["goal"] for o in objectives if o["metric"] == k), "max")
            if mv is None:
                return False
            if goal == "max" and mv < v:
                return False
            if goal == "min" and mv > v:
                return False
        return True

    feasible = [p for p in pareto if within(p)]
    primary = objectives[0]
    # A point that never MEASURED the primary objective cannot be ranked on it.
    # Substituting a sentinel (0 for a max goal, 1e30 for a min goal) is not
    # merely conservative -- for a metric that can go negative, such as SLACK,
    # a missing value of 0 OUTRANKS a real -5 ns, so the unmeasured point wins
    # and gets recommended. Exclude and report instead.
    _pm = primary["metric"]

    def _ranked(pool):
        return [p for p in pool if isinstance(p["metrics"].get(_pm), (int, float))]

    unranked = [p["source_cde"] for p in pareto
                if not isinstance(p["metrics"].get(_pm), (int, float))]
    # Recommend only from the FEASIBLE set. Falling back to `feasible or pareto`
    # silently returned an over-budget point in the same field, with the same
    # shape, as a compliant one.
    rec_pool = _ranked(feasible)
    recommendation_feasible = bool(rec_pool)
    pool = rec_pool
    recommended = None
    if pool:
        recommended = (max(pool, key=lambda p: p["metrics"][_pm])
                       if primary["goal"] == "max"
                       else min(pool, key=lambda p: p["metrics"][_pm]))
    # knob sensitivity: range of each objective across distinct knob values
    sensitivity = {}
    knobs = {k for p in points for k in p.get("config", {})}
    for knob in knobs:
        groups = {}
        for p in points:
            groups.setdefault(p["config"].get(knob), []).append(
                p["metrics"].get(primary["metric"]))
        spread = [max(v) - min(v) for v in groups.values() if len(v) > 1 and None not in v]
        sensitivity[knob] = round(max(spread), 4) if spread else 0.0
    open(os.path.join(_OUTPUT_DIR, "pareto.json"), "w").write(json.dumps(pareto, indent=2))
    if not feasible:
        _verdict = "fail"
        _note = "NO validated point meets the budget; no recipe is recommended."
    elif recommended is None:
        _verdict = "fail"
        _note = (f"no explored point reports the primary objective '{_pm}', so "
                 f"nothing can be ranked or recommended")
    elif not recommendation_feasible:
        _verdict = "fail"
        _note = (f"NO point meets the budget. The reported recipe is the best "
                 f"Pareto point available and is OVER BUDGET -- it is not a "
                 f"recommendation that satisfies the request.")
    elif unranked:
        _verdict = "pass_with_caveats"
        _note = (f"{len(unranked)} Pareto point(s) never measured '{_pm}' and were "
                 f"excluded from ranking; the recommendation is drawn only from "
                 f"the points that did")
    else:
        _verdict = "pass"
        _note = "recommendation within budget"
    return _cde(
        objective="deterministic PPA design-space exploration",
        status="completed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"explored": {"value": len(points), "unit": "count"},
                 "pareto_size": {"value": len(pareto), "unit": "count"},
                 "feasible_points": {"value": len(feasible), "unit": "count"}},
        qor={"recommended_recipe": (recommended or {}).get("config"),
             "recommended_metrics": (recommended or {}).get("metrics"),
             "within_budget": bool(feasible),
             "recommendation_feasible": recommendation_feasible,
             "unranked_points": len(unranked),
             "primary_objective": _pm},
        signoff={"pareto_front": [{"config": p["config"], "metrics": p["metrics"],
                                   "source_cde": p["source_cde"]} for p in pareto],
                 "knob_sensitivity": sensitivity,
                 "verified_sources": verified,
                 "recommendation_feasible": recommendation_feasible,
                 "unranked_points": unranked,
                 "unranked_reason": (
                     f"these points do not report the primary objective '{_pm}'; "
                     f"they are excluded from ranking rather than being given a "
                     f"sentinel value, because a sentinel can OUTRANK a real "
                     f"measurement for a metric that goes negative (e.g. slack)"
                     if unranked else None),
                 "recommended": ({"config": recommended["config"],
                                  "source_cde": recommended["source_cde"],
                                  "feasible": recommendation_feasible}
                                 if recommended else None)},
        inputs_ref={"source_cdes": [p["source_cde"] for p in points]},
        assumptions=["deterministic search over supplied real run points; no learned "
                     "surrogate (Tier 3, out of scope)",
                     "a point missing the primary objective is excluded from "
                     "ranking, never substituted with a sentinel"],
        validation={"verdict": _verdict, "note": _note},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("sweep", "pareto_search", "sensitivity"):
        return _explore(params)
    return _cde(objective="dse", status="failed",
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
