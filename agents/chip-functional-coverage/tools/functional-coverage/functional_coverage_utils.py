#!/usr/bin/env python3
"""functional_coverage_utils.py -- functional-coverage logic (covergroups, bins,
crosses, cover properties) for the chip-functional-coverage tool.

Scenarios:
  model_coverage        -- register/validate a functional coverage model.
  measure_rtl_coverage  -- **THE SIGNOFF SCENARIO.** Compile and RUN the supplied
                           RTL under cocotb + Verilator ``--coverage`` across
                           seeds, merge the native per-seed ``coverage.dat``,
                           sample covergroups from values the SIMULATION emitted,
                           measure assertion cover properties, and emit an
                           actual-measurement-basis reachability proof.
  measure_coverage      -- model-only scoring of CALLER-SUPPLIED sample labels.
                           **NOT signoff evidence** -- see the warning below.
  merge_coverage        -- union of coverage databases across seeds.

*** WHY measure_rtl_coverage EXISTS (read before touching this file) ***
`measure_coverage` scores `params["samples"]`: a list of dicts the CALLER asserts.
It never compiled, ran, or observed anything. That is a legitimate model-scoring
utility, but it is NOT measurement -- an agent can hand it a hit for a bin the
design cannot reach and it will score 100%. The packaged image has always shipped
Verilator 5.036, cocotb 2.0.1, cocotb_coverage and reachability_proof.py; the tool
simply never invoked any of them, so a functional-coverage gate had no way to
close on real evidence and the stage failed closed (correctly) instead.
Every signoff-grade run MUST use `measure_rtl_coverage`, whose samples come from
a simulation THIS TOOL executed. `measure_coverage` now stamps
`basis: caller_asserted_samples` + `signoff_eligible: false` into its envelope so
it can never be mistaken for measured evidence.

Node-agnostic. Reports against a supplied goal when present, else without an
invented threshold. Results conform to the CDE.
"""
import glob
import itertools
import json
import os
import random
import shutil
import subprocess

TOOL = "functional-coverage"
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


def _tool_version(command):
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    An envelope that stamps no `stage` resolves to no registry entry, reports NO
    METRIC, and a missing metric is indistinguishable downstream from a closed
    gate. The tool names its own gate rather than leaving it to the caller.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "funccov"
    except Exception:
        return "funccov"


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
        base.setdefault("basis", "agent_read_of_coverage_report" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_coverage_report")


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


def _cde(objective, status, results=None, signoff=None, qor=None, assumptions=None,
         validation=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "stage": _canonical_stage(),
        "status": status, "objective": objective,
        "tools_used": [
            {"name": "functional-coverage", "version": "1.0.0"},
            {"name": "Verilator", "version": _tool_version(["verilator", "--version"])},
            {"name": "cocotb", "version": _tool_version(
                ["python3", "-c", "import cocotb; print(cocotb.__version__)"]
            )},
        ],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "shared_artifact",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "set_coverage"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic set-coverage"},
    }
    if error:
        env["error"] = error
    return env


def _goal(pct, goal):
    if goal is None:
        return {"verdict": "review", "note": "no goal supplied; reported without compliance verdict"}
    return {"verdict": "pass" if pct >= goal else "fail",
            "goal_percent": goal, "measured_percent": pct}


def _validate_model(model):
    groups = {k: v for k, v in model.items() if k != "crosses"}
    if not groups:
        raise ValueError("coverage_model has no covergroups")
    for g, spec in groups.items():
        if not spec.get("bins"):
            raise ValueError(f"covergroup '{g}' has no bins")
    return groups, model.get("crosses", [])


def _model(params):
    groups, crosses = _validate_model(params["coverage_model"])
    total_bins = sum(len(g["bins"]) for g in groups.values())
    cross_bins = sum(
        len(list(itertools.product(*[groups[c]["bins"] for c in cr])))
        for cr in crosses
    )
    return _cde(objective="register functional coverage model", status="completed",
                results={"covergroups": {"value": len(groups), "unit": "count"},
                         "total_bins": {"value": total_bins, "unit": "count"},
                         "cross_bins": {"value": cross_bins, "unit": "count"}},
                signoff={"groups": list(groups), "crosses": crosses},
                validation={"verdict": "pass"})


def _measure(params):
    groups, crosses = _validate_model(params["coverage_model"])
    samples = params.get("samples", [])
    per_group = {}
    holes = []
    for g, spec in groups.items():
        bins = spec["bins"]
        hit = {b: False for b in bins}
        for s in samples:
            if s.get(g) in hit:
                hit[s[g]] = True
        covered = sum(hit.values())
        pct = round(100.0 * covered / len(bins), 2)
        per_group[g] = {"value": pct, "unit": "percent"}
        for b, h in hit.items():
            if not h:
                holes.append({"group": g, "bin": b, "cause": "never sampled"})
    per_cross = {}
    for cr in crosses:
        combos = list(itertools.product(*[groups[c]["bins"] for c in cr]))
        hitset = set()
        for s in samples:
            key = tuple(s.get(c) for c in cr)
            if all(k in groups[cr[i]]["bins"] for i, k in enumerate(key)):
                hitset.add(key)
        pct = round(100.0 * len(hitset) / len(combos), 2) if combos else 0.0
        per_cross["x".join(cr)] = {"value": pct, "unit": "percent"}
        for combo in combos:
            if combo not in hitset:
                holes.append({"cross": "x".join(cr), "combo": list(combo),
                              "cause": "cross never sampled"})
    all_pcts = [v["value"] for v in list(per_group.values()) + list(per_cross.values())]
    overall = round(sum(all_pcts) / len(all_pcts), 2) if all_pcts else 0.0
    _gc = _goal(overall, params.get("goal_percent"))
    # This scenario scored labels the CALLER asserted -- nothing was compiled,
    # run, or observed. Stamp that basis into the envelope so a downstream gate
    # cannot mistake it for measurement. Signoff MUST use measure_rtl_coverage.
    _val = dict(_gc)
    _val["note"] = ((_val.get("note", "") + " ") if _val.get("note") else "") + (
        "NOT SIGNOFF EVIDENCE: scored caller-asserted samples; no simulation was "
        "executed. Use scenario=measure_rtl_coverage for a measured basis.")
    return _cde(
        objective="score functional coverage model against caller-supplied samples",
        status="completed",
        results={"overall_functional_coverage": {"value": overall, "unit": "percent"},
                 "per_group": per_group, "per_cross": per_cross},
        qor={"overall_percent": overall, "holes": len(holes)},
        signoff={"coverage_holes": holes,
                 "basis": "caller_asserted_samples",
                 "signoff_eligible": False,
                 "goal_compliance": _gc,
                 "samples": len(samples)},
        inputs_ref={"model_groups": list(groups), "crosses": crosses},
        validation=_val,
    )


def _merge(params):
    dbs = params.get("coverage_dbs", [])
    union = {}
    skipped = []
    for db in dbs:
        if os.path.exists(db):
            try:
                for k, v in json.load(open(db)).items():
                    union[k] = union.get(k, False) or bool(v)
            except Exception as _e:
                skipped.append({"db": os.path.basename(str(db)), "error": str(_e)})
                print("[" + str(TOOL) + "] coverage DB skipped (unparseable): "
                      + str(db) + ": " + str(_e), flush=True)
        else:
            skipped.append({"db": os.path.basename(str(db)), "error": "not found"})
    covered = sum(1 for v in union.values() if v)
    pct = round(100.0 * covered / len(union), 2) if union else None
    return _cde(objective="merge functional coverage", status="completed",
                results={"merged_coverage": {"value": pct, "unit": "percent"}},
                qor={"bins": len(union), "covered": covered},
                signoff={"goal_compliance": _goal(pct, params.get("goal_percent")),
                         "dbs_skipped": skipped},
                inputs_ref={"coverage_dbs": dbs})


# =========================================================================
# REAL RTL EXECUTION  --  measure_rtl_coverage
# =========================================================================
# Everything below actually compiles, runs, and reads back a simulation. The
# governing rule is that a sample is only admissible as evidence if THIS TOOL
# produced it: caller-supplied hit labels are never merged into a measured run.

class _ToolError(Exception):
    """Fail-closed error carrying a remediation hint for the CDE."""

    def __init__(self, msg, hint=""):
        super().__init__(msg)
        self.hint = hint


def _run(cmd, cwd, log_path, timeout=1800, env=None):
    """Run a command, tee stdout+stderr to *log_path*, return (rc, output).

    Every invocation is logged verbatim so a run is reproducible from the
    attempt directory alone -- `exit 0` is not evidence, the log is.
    """
    printable = " ".join(str(c) for c in cmd)
    print("[" + TOOL + "] $ " + printable, flush=True)
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env)
        out = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
    except subprocess.TimeoutExpired as e:
        out = "TIMEOUT after %ss\n%s" % (timeout, e.stdout or "")
        rc = 124
    except FileNotFoundError as e:
        out = "COMMAND NOT FOUND: %s" % e
        rc = 127
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("$ " + printable + "\n" + out + "\n[exit %s]\n\n" % rc)
    except Exception:
        pass
    return rc, out


def _require(cond, msg, hint=""):
    if not cond:
        raise _ToolError(msg, hint)


def _abs_inputs(files, label):
    """Resolve input paths and REQUIRE every one to exist (fail closed)."""
    out, missing = [], []
    for f in files or []:
        cands = [f]
        if not os.path.isabs(f):
            cands += [os.path.join("/input", f), os.path.join(_WORK_DIR, f)]
        hit = next((c for c in cands if os.path.isfile(c)), None)
        (out.append(os.path.abspath(hit)) if hit else missing.append(f))
    _require(not missing,
             "%s not found: %s" % (label, ", ".join(missing)),
             "mount the files and pass paths under /input, or absolute paths")
    return out


def _verilator_version():
    rc, out = _run(["verilator", "--version"], _WORK_DIR, os.devnull)
    return out.strip() if rc == 0 else "unavailable"


def _write_sampler(work, model):
    """Emit the cocotb-side sampler the DUT test imports.

    The testbench calls ``sample(**kwargs)`` for each observed transaction; the
    module appends to ``functional_samples.json`` in the run directory. The tool
    reads that file back AFTER the simulation exits, so every sample is tied to
    an executed run rather than asserted by a caller.
    """
    path = os.path.join(work, "chip_fcov_sampler.py")
    groups = [g for g in model if g != "crosses"]
    src = '''"""chip_fcov_sampler -- emitted by chip-functional-coverage.

The DUT testbench imports this and calls sample(**values) per transaction.
Samples land in functional_samples.json next to the run, which the tool reads
back after the simulation exits.
"""
import json
import os

_GROUPS = %r
_PATH = os.environ.get("CHIP_FCOV_SAMPLES", "functional_samples.json")
_BUF = []


def sample(**values):
    """Record one observation. Unknown keys are ignored (model is authoritative)."""
    rec = {k: values[k] for k in _GROUPS if k in values}
    if rec:
        _BUF.append(rec)
        flush()
    return rec


def cover(name, hit=True):
    """Record an assertion/cover-property observation."""
    _BUF.append({"__cover__": str(name), "__hit__": bool(hit)})
    flush()


def flush():
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_BUF, f)
    os.replace(tmp, _PATH)
''' % (groups,)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    return path


def _build_and_run_seed(params, work, rtl, top, tb_module, tb_dir, seed, logp):
    """Verilate + build + run ONE seed with coverage enabled.

    Returns (run_dir, coverage_dat_path_or_None, sim_ok, tests_total, tests_failed).
    """
    rundir = os.path.join(work, "seed_%s" % seed)
    os.makedirs(rundir, exist_ok=True)
    samples_path = os.path.join(rundir, "functional_samples.json")

    env = dict(os.environ)
    env["CHIP_FCOV_SAMPLES"] = samples_path
    env["COCOTB_RANDOM_SEED"] = str(seed)
    env["RANDOM_SEED"] = str(seed)
    pypath = [work, tb_dir] + [os.path.dirname(r) for r in rtl]
    env["PYTHONPATH"] = os.pathsep.join(
        [p for p in pypath if p] + [env.get("PYTHONPATH", "")]).strip(os.pathsep)

    # cocotb 2.x runner: build with coverage, then test.
    runner_py = os.path.join(rundir, "_run_cocotb.py")
    with open(runner_py, "w", encoding="utf-8") as f:
        f.write(
            "import os, sys, json\n"
            "from cocotb_tools.runner import get_runner\n"
            "rtl = %r\n"
            "top = %r\n"
            "tb  = %r\n"
            "build_dir = %r\n"
            "r = get_runner('verilator')\n"
            "r.build(verilog_sources=rtl, hdl_toplevel=top, build_dir=build_dir,\n"
            "        always=True,\n"
            "        build_args=['--coverage','--trace','-Wno-fatal','--timing'])\n"
            "r.test(hdl_toplevel=top, test_module=tb, build_dir=build_dir,\n"
            "       test_dir=%r, results_xml='results.xml')\n"
            % (rtl, top, tb_module, os.path.join(rundir, "build"), rundir))

    rc, out = _run(["python3", "-u", runner_py], rundir, logp, env=env)

    # cocotb returns non-zero on test failure; that is a RESULT, not a tool error.
    xml = os.path.join(rundir, "results.xml")
    total = failed = 0
    if os.path.isfile(xml):
        try:
            import xml.etree.ElementTree as ET
            root = ET.parse(xml).getroot()
            for tc in root.iter("testcase"):
                total += 1
                if list(tc.iter("failure")) or list(tc.iter("error")):
                    failed += 1
        except Exception:
            pass

    dat = None
    for cand in (os.path.join(rundir, "coverage.dat"),
                 os.path.join(rundir, "build", "coverage.dat")):
        if os.path.isfile(cand) and os.path.getsize(cand) > 0:
            dat = cand
            break
    if dat is None:
        found = glob.glob(os.path.join(rundir, "**", "coverage.dat"),
                          recursive=True)
        dat = next((p for p in found if os.path.getsize(p) > 0), None)

    return rundir, dat, (rc == 0), total, failed, samples_path


def _merge_coverage_dats(dats, work, logp):
    """Merge per-seed native coverage.dat with verilator_coverage."""
    if not dats:
        return None
    merged = os.path.join(work, "coverage_merged.dat")
    rc, _ = _run(["verilator_coverage", "--write", merged] + list(dats),
                 work, logp)
    if rc != 0 or not os.path.isfile(merged):
        # Single-seed runs need no merge; fall back to the one file.
        return dats[0] if len(dats) == 1 else None
    return merged


def _load_samples(paths):
    """Read back samples the SIMULATION wrote. Returns (samples, covers)."""
    samples, covers = [], {}
    for p in paths:
        if not (p and os.path.isfile(p)):
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception as _e:
            print("[" + TOOL + "] unreadable sample file %s: %s" % (p, _e),
                  flush=True)
            continue
        for rec in data if isinstance(data, list) else []:
            if not isinstance(rec, dict):
                continue
            if "__cover__" in rec:
                nm = rec["__cover__"]
                covers[nm] = covers.get(nm, False) or bool(rec.get("__hit__"))
            else:
                samples.append(rec)
    return samples, covers


def _score_model(groups, crosses, samples):
    """Identical set math to _measure, but over MEASURED samples."""
    per_group, holes = {}, []
    for g, spec in groups.items():
        bins = spec["bins"]
        hit = {b: False for b in bins}
        for s in samples:
            if s.get(g) in hit:
                hit[s[g]] = True
        covered = sum(hit.values())
        per_group[g] = {"value": round(100.0 * covered / len(bins), 2),
                        "unit": "percent", "hit": covered, "total": len(bins)}
        holes += [{"group": g, "bin": b, "cause": "never sampled"}
                  for b, h in hit.items() if not h]
    per_cross = {}
    for cr in crosses:
        combos = list(itertools.product(*[groups[c]["bins"] for c in cr]))
        hitset = set()
        for s in samples:
            key = tuple(s.get(c) for c in cr)
            if all(k in groups[cr[i]]["bins"] for i, k in enumerate(key)):
                hitset.add(key)
        pct = round(100.0 * len(hitset) / len(combos), 2) if combos else 0.0
        per_cross["x".join(cr)] = {"value": pct, "unit": "percent",
                                   "hit": len(hitset), "total": len(combos)}
        holes += [{"cross": "x".join(cr), "combo": list(c),
                   "cause": "cross never sampled"}
                  for c in combos if c not in hitset]
    return per_group, per_cross, holes


def _measure_rtl(params):
    """THE SIGNOFF SCENARIO: compile, run, and measure real RTL.

    Fails closed on every missing capability or artifact -- it never falls back
    to scoring caller-supplied labels, because a silent downgrade from measured
    to asserted coverage is precisely the defect this scenario exists to remove.
    """
    work = os.path.join(_WORK_DIR, "fcov")
    os.makedirs(work, exist_ok=True)
    logp = os.path.join(_OUTPUT_DIR, "functional_coverage_run.log")

    try:
        groups, crosses = _validate_model(params["coverage_model"])
    except KeyError:
        raise _ToolError("coverage_model is required for measure_rtl_coverage",
                         "supply covergroups with bins (and optional crosses)")

    rtl = _abs_inputs(params.get("rtl_files"), "rtl_files")
    _require(rtl, "rtl_files is required and must be a non-empty ordered list",
             "pass the design's real RTL, dependency-ordered")
    top = params.get("top")
    _require(top, "top (HDL module name) is required",
             "top is the MODULE/ENTITY name, not a filename")

    tb_module = params.get("cocotb_module") or params.get("test_module")
    _require(tb_module, "cocotb_module is required",
             "name the python test module (no .py) that drives the DUT")
    tb_files = _abs_inputs(params.get("cocotb_files") or [], "cocotb_files")
    tb_dir = (os.path.dirname(tb_files[0]) if tb_files
              else params.get("cocotb_test_dir") or "/input")
    _require(os.path.isdir(tb_dir), "cocotb test dir not found: %s" % tb_dir)

    # Capability preflight -- prove the engines exist BEFORE claiming a basis.
    vver = _verilator_version()
    _require(vver != "unavailable", "verilator not available in this image",
             "rebuild the chip-functional-coverage image")
    rc, _ = _run(["python3", "-c", "import cocotb, cocotb_tools.runner"],
                 work, logp)
    _require(rc == 0, "cocotb (with cocotb_tools.runner) not importable",
             "rebuild the image; cocotb 2.x is required for the runner API")

    _write_sampler(work, params["coverage_model"])

    seeds = params.get("seeds")
    if not seeds:
        n = int(params.get("seed_count", 1) or 1)
        base = int(params.get("base_seed", 1))
        seeds = [base + i for i in range(max(1, n))]

    dats, sample_paths, per_seed = [], [], []
    tests_total = tests_failed = 0
    for sd in seeds:
        rundir, dat, ok, tot, fail, spath = _build_and_run_seed(
            params, work, rtl, top, tb_module, tb_dir, sd, logp)
        tests_total += tot
        tests_failed += fail
        if dat:
            dats.append(dat)
        sample_paths.append(spath)
        evidence = os.path.join(_OUTPUT_DIR, "simulation_evidence", "seed_%s" % sd)
        os.makedirs(evidence, exist_ok=True)
        for source in (spath, os.path.join(rundir, "results.xml")):
            if os.path.isfile(source):
                shutil.copyfile(source, os.path.join(evidence, os.path.basename(source)))
        per_seed.append({"seed": sd, "sim_exit_ok": ok, "tests": tot,
                         "failed": fail, "coverage_dat": bool(dat)})

    _require(tests_total > 0,
             "no cocotb testcases executed (positive-work check failed)",
             "the run produced no results.xml testcases; check the test module "
             "name and that the DUT elaborates")

    samples, covers = _load_samples(sample_paths)
    _require(samples,
             "simulation produced ZERO functional samples",
             "the testbench must import chip_fcov_sampler and call "
             "sample(**values) per transaction; caller-supplied samples are "
             "NOT accepted by this scenario")

    per_group, per_cross, holes = _score_model(groups, crosses, samples)

    # Assertion / cover-property measurement (optional but measured when asked).
    want_covers = params.get("cover_properties") or []
    cover_rows, cover_missing = [], []
    for nm in want_covers:
        hit = bool(covers.get(nm))
        cover_rows.append({"name": nm, "hit": hit})
        if not hit:
            cover_missing.append(nm)

    merged = _merge_coverage_dats(dats, work, logp)
    _require(merged,
             "no native Verilator coverage.dat was produced",
             "the build must pass --coverage; check the run log")
    shutil.copyfile(merged, os.path.join(_OUTPUT_DIR, "coverage_merged.dat"))

    # Reachability proof on the ACTUAL measurement basis.
    proof = None
    try:
        import reachability_proof as _rp
        pts, basis = _rp._parse_verilator_dat(merged), "verilator_coverage.dat"
        ov = _rp._load_overrides(params.get("reachability_overrides"))
        proof = _rp.build_proof(pts, basis, ov)
        rpath = os.path.join(_OUTPUT_DIR, "code_coverage_reachability.json")
        with open(rpath, "w", encoding="utf-8") as f:
            json.dump(proof, f, indent=2)
    except Exception as _e:
        raise _ToolError("reachability proof could not be built: %s" % _e,
                         "the proof is mandatory evidence for this gate")

    all_pcts = [v["value"] for v in list(per_group.values()) + list(per_cross.values())]
    overall = round(sum(all_pcts) / len(all_pcts), 2) if all_pcts else 0.0
    goal = params.get("goal_percent")

    reach_unhit = proof["summary"]["reachable_unhit_total"] if proof else None
    ok = (not holes and not cover_missing and tests_failed == 0
          and (goal is None or overall >= goal)
          and (reach_unhit == 0))
    note_bits = []
    if holes:
        note_bits.append("%d functional hole(s)" % len(holes))
    if cover_missing:
        note_bits.append("%d cover property never hit" % len(cover_missing))
    if tests_failed:
        note_bits.append("%d test failure(s)" % tests_failed)
    if reach_unhit:
        note_bits.append("%d reachable_unhit code point(s)" % reach_unhit)

    return _cde(
        objective="measure functional coverage from executed RTL simulation",
        status="completed",
        # (A) GATING -- all three must close. A PERCENTAGE alone is not the gate:
        # 100% of the wrong population closes nothing, which is why
        # reachable_unhit (counted against a reachability proof) gates too.
        results={"overall_functional_coverage": {
                     "value": overall, "unit": "percent",
                     "class": "gating", "basis": "measured_simulation_samples",
                     "closes_at": ">= goal_percent",
                     "note": ("Mean over covergroups and crosses measured from "
                              "samples THIS TOOL's sampler emitted. A percentage "
                              "is not sufficient on its own -- see "
                              "reachable_unhit.")},
                 "per_group": per_group, "per_cross": per_cross,
                 "cover_properties": cover_rows,
                 "samples_measured": {
                     "value": len(samples), "unit": "count",
                     "class": "diagnostic", "basis": "measured_simulation_samples",
                     "note": "POPULATION and higher-is-better; never a residual"},
                 "tests_run": {
                     "value": tests_total, "unit": "count",
                     "class": "diagnostic", "basis": "measured_simulation_samples",
                     "note": "POPULATION and higher-is-better; never a residual"},
                 "tests_failed": {
                     "value": tests_failed, "unit": "count",
                     "class": "gating", "basis": "measured_simulation_samples",
                     "closes_at": "== 0",
                     "note": ("A failing test invalidates the coverage it "
                              "contributed; coverage measured under failure is "
                              "not evidence of function.")},
                 "reachable_unhit": {
                     "value": reach_unhit, "unit": "count",
                     "class": "gating", "basis": "counted_from_reachability_proof",
                     "closes_at": "== 0",
                     "note": ("Points PROVED reachable that the regression never "
                              "hit. A null means NOT ASSESSED and must never read "
                              "as zero -- the proof is mandatory evidence here.")}},
        qor={"overall_percent": overall, "holes": len(holes),
             "tests_failed": tests_failed, "reachable_unhit": reach_unhit},
        signoff={"basis": "executed_simulation",
                 "signoff_eligible": True,
                 "measurement": "cocotb+verilator --coverage, native coverage.dat",
                 "verilator_version": vver,
                 "seeds": per_seed,
                 "coverage_holes": holes,
                 "cover_properties_missing": cover_missing,
                 "reachability_proof": "reports/code_coverage_reachability.json",
                 "goal_compliance": _goal(overall, goal),
                 # (B) DIAGNOSTIC -- the repair surface: WHICH bins/crosses/cover
                 # properties are open is what targets the next stimulus.
                 "diagnostics": {
                     "class": "diagnostic", "basis": "measured_simulation_samples",
                     "coverage_holes": holes,
                     "cover_properties_missing": cover_missing,
                     "hole_count": len(holes),
                     "per_seed": per_seed,
                     "population_note": ("samples_measured / tests_run are the "
                                         "denominator. Diagnostic, not descriptive: "
                                         "REMOVING a covergroup or bin shrinks the "
                                         "population and raises the percentage "
                                         "while covering strictly less.")},
                 # (C) DESCRIPTIVE -- configuration, expected to hold steady.
                 # Deliberately EXCLUDES the sample/test counts (see above).
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "top": top, "verilator_version": vver,
                     "group_count": len(groups), "cross_count": len(crosses),
                     "goal_percent": goal,
                     "measurement": "cocotb+verilator --coverage"},
                 # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), reach_unhit,
                     "reachable_unhit")},
        inputs_ref={"rtl_files": rtl, "top": top, "cocotb_module": tb_module,
                    "model_groups": list(groups), "crosses": crosses},
        validation={"verdict": "pass" if ok else "fail",
                    "note": ("all covergroups/crosses closed on measured samples; "
                             "reachable_unhit == 0")
                    if ok else "; ".join(note_bits)},
    )


def _measure_rtl_guarded(params):
    """Fail-closed wrapper: a capability/artifact gap is a FAILED run, never a
    downgrade to caller-asserted scoring."""
    try:
        return _measure_rtl(params)
    except _ToolError as e:
        return _cde(objective="measure functional coverage from executed RTL",
                    status="failed", error=str(e),
                    signoff={"basis": "none", "signoff_eligible": False,
                             "remediation": e.hint},
                    validation={"verdict": "fail", "note": str(e)})
    except Exception as e:  # unexpected -- still fail closed, with the type
        return _cde(objective="measure functional coverage from executed RTL",
                    status="failed", error="%s: %s" % (type(e).__name__, e),
                    signoff={"basis": "none", "signoff_eligible": False},
                    validation={"verdict": "fail"})


_SCENARIOS = {"model_coverage": _model, "measure_coverage": _measure,
              "measure_rtl_coverage": _measure_rtl_guarded,
              "merge_coverage": _merge}


def dispatch(params):
    s = params.get("scenario")
    if s not in _SCENARIOS:
        return _cde(objective="functional coverage", status="failed",
                    error=f"unknown scenario '{s}'; supported: " + ", ".join(_SCENARIOS),
                    validation={"verdict": "fail"})
    return _SCENARIOS[s](params)


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
