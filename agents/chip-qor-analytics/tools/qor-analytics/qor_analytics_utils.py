#!/usr/bin/env python3
"""qor_analytics_utils.py -- cross-run QoR aggregation and anomaly detection for
the chip-qor-analytics tool.

Consumes Common Design Envelopes only (never re-runs a flow stage). Every
aggregated point references a source CDE hash. Anomalies are flagged against an
explicit baseline using a percent/sigma threshold. Node-agnostic. Results conform
to the CDE.
"""
import json
import os
import statistics

import qor_stats

TOOL = "qor-analytics"
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
    if results.get("signoff_evidence", {}).get("dataset") == "qor_dataset.json":
        results["signoff_evidence"]["dataset"] = "results/qor_dataset.json"
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


def _cde(objective, status, results=None, signoff=None, qor=None, assumptions=None,
         validation=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "qor-analytics", "version": TOOL_VERSION}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "statistics"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "envelope aggregation"},
    }
    if error:
        env["error"] = error
    return env


#: Canonical metric families: name -> (dimension, canonical unit, aliases). A
#: requested metric resolves to its family by its unit-stripped name, and is then
#: looked up under every alias in priority order. Pre-layout ESTIMATES
#: (estimated_wns/tns/fmax) are deliberately NOT aliases of the signoff metric --
#: mixing them into one series fabricates a trend (synthesis estimated_wns 9.46 ns
#: -> STA wns 0.0 reads as "degrading"); request them by exact name. Aliases are
#: matched only on a KNOWN, convertible unit -- a value whose unit cannot be
#: established is skipped (and the skip recorded), never assumed.
_METRIC_FAMILIES = {
    "cell_area": ("area", "um2", ("cell_area", "design_area", "area",
                                  "stdcell_area", "std_cell_area",
                                  "instance_area", "total_cell_area")),
    "setup_wns": ("time", "ns", ("wns", "setup_wns", "worst_slack",
                                 "worst_negative_slack", "setup_worst_slack",
                                 "setup_slack")),
    "setup_tns": ("time", "ns", ("tns", "setup_tns", "total_negative_slack")),
    "hold_wns": ("time", "ns", ("hold_wns", "hold_worst_slack", "hold_slack",
                                "worst_hold_slack")),
    "hold_tns": ("time", "ns", ("hold_tns", "hold_total_negative_slack")),
    "utilization": ("ratio", "fraction", ("utilization", "achieved_utilization",
                                          "core_utilization",
                                          "placement_utilization",
                                          "design_utilization")),
    "total_power": ("power", "w", ("total_power", "power")),
    "dynamic_power": ("power", "w", ("dynamic_power",)),
    "leakage_power": ("power", "w", ("leakage_power", "leakage")),
    "internal_power": ("power", "w", ("internal_power",)),
    "switching_power": ("power", "w", ("switching_power",)),
    "drc_violations": ("count", None, ("drc_violations", "drc_count",
                                       "drc_errors", "routing_drc_violations")),
    "routing_congestion": ("ratio", "pct", ("routing_congestion", "congestion",
                                            "congestion_usage")),
    "clock_skew": ("time", "ns", ("clock_skew", "skew", "max_skew",
                                  "worst_skew")),
    "insertion_delay": ("time", "ns", ("clock_insertion_delay",
                                       "insertion_delay", "clock_latency")),
    "cell_count": ("count", None, ("cell_count", "instance_count", "num_cells",
                                   "num_instances", "std_cell_count")),
    "wirelength": ("length", "um", ("wirelength", "wire_length",
                                    "total_wirelength", "routed_wirelength")),
    "fmax": ("freq", "mhz", ("fmax", "max_frequency")),
    "ir_drop": ("voltage", "v", ("worst_ir_drop", "ir_drop", "worst_ir",
                                 "max_ir_drop")),
}
_ALIAS_TO_FAMILY = {a: f for f, (_d, _u, al) in _METRIC_FAMILIES.items()
                    for a in al + (f,)}
_UNIT_SCALE = {
    "time": {"ns": 1.0, "ps": 1e-3, "us": 1e3},
    "power": {"w": 1.0, "mw": 1e-3, "uw": 1e-6, "nw": 1e-9},
    "area": {"um2": 1.0, "mm2": 1e6},
    "length": {"um": 1.0, "mm": 1e3, "nm": 1e-3},
    "voltage": {"v": 1.0, "mv": 1e-3},
    "ratio": {"fraction": 1.0, "pct": 0.01},
    "freq": {"mhz": 1.0, "ghz": 1e3, "khz": 1e-3},
    "count": {"count": 1.0},
}
_UNIT_DIM = {u: d for d, m in _UNIT_SCALE.items() for u in m}
_UNIT_NORMALIZE = {"um^2": "um2", "µm^2": "um2", "um²": "um2", "mm^2": "mm2",
                   "percent": "pct", "%": "pct", "percent_of_tracks": "pct",
                   "frac": "fraction", "violations": "count", "cells": "count"}
#: key suffixes recognised as units (longest first so `_um2` beats `_um`)
_UNIT_SUFFIXES = ("um2", "mm2", "pct", "mhz", "ghz", "khz", "ns", "ps", "us",
                  "mw", "uw", "nw", "mv", "um", "mm", "nm", "w", "v")
_PATH_KEYS = ("path", "file", "cde", "cde_path", "cde_file", "envelope",
              "source_cde")
_ORDER_FIELDS = ("order", "index", "attempt", "timestamp", "finished_utc")


def _norm_unit(u):
    if u is None:
        return None
    u = str(u).strip().lower()
    u = _UNIT_NORMALIZE.get(u, u)
    return u if u in _UNIT_DIM else None


def _split_unit(name):
    """'cell_area_um2' -> ('cell_area', 'um2'); 'wns' -> ('wns', None)."""
    n = str(name).strip().lower()
    for s in _UNIT_SUFFIXES:
        if n.endswith("_" + s) and len(n) > len(s) + 1:
            return n[:-(len(s) + 1)], s
    return n, None


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def _cde_candidates(cde):
    """Every numeric value a CDE carries, as candidate metric sources:
    results.<k>.value (unit from the entry), results.<k> scalars, and
    qor_metrics.<k> (scalar or {value, unit}); unit else from the key suffix."""
    cands = []
    for sect in ("results", "qor_metrics"):
        d = cde.get(sect)
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            unit = None
            if isinstance(v, dict):
                if "value" not in v:
                    continue
                unit, v = v.get("unit"), v.get("value")
            if not _is_num(v):
                continue
            base, sfx = _split_unit(k)
            cands.append({"key": f"{sect}.{k}", "name": str(k).lower(),
                          "orig": str(k),
                          "base": base, "value": v,
                          "unit": _norm_unit(unit) or sfx,
                          "unit_basis": ("entry" if _norm_unit(unit) else
                                         "key_suffix" if sfx else None)})
    return cands


def _inline_candidates(metrics):
    cands = []
    for k, v in (metrics or {}).items():
        if not _is_num(v):
            continue
        base, sfx = _split_unit(k)
        cands.append({"key": f"metrics.{k}", "name": str(k).lower(),
                      "orig": str(k),
                      "base": base, "value": v, "unit": sfx,
                      "unit_basis": "key_suffix" if sfx else None})
    return cands


def _resolve_metric(requested, cands):
    """Pick one value for *requested* from *cands*. Exact key name first
    (verbatim, converted only when both units are known), then family aliases
    in priority order with a known, convertible unit. Returns (value, source)
    or (None, {"skipped": [...]})."""
    req = str(requested).strip().lower()
    base, target = _split_unit(req)
    fam = _ALIAS_TO_FAMILY.get(base) or _ALIAS_TO_FAMILY.get(req)
    dim, canon = (_METRIC_FAMILIES[fam][:2] if fam else (None, None))
    target = target or canon
    pref = {"metrics": 0, "results": 1, "qor_metrics": 2}
    ordered = sorted(cands, key=lambda c: pref.get(c["key"].split(".")[0], 9))

    def _convert(c):
        su = c["unit"]
        if su and target and _UNIT_DIM.get(su) == _UNIT_DIM.get(target):
            sc = _UNIT_SCALE[_UNIT_DIM[su]]
            return c["value"] * sc[su] / sc[target], target
        return None, None

    for c in ordered:
        if c["name"] == req:
            v, u = _convert(c)
            src = {"key": c["key"], "match": "exact", "raw_value": c["value"],
                   "source_unit": c["unit"]}
            if v is not None:
                src.update(unit=u, converted=c["unit"] != u)
                return round(v, 12), src
            src.update(unit=c["unit"], converted=False)
            return c["value"], src
    if not fam:
        return None, {"skipped": [], "note": "no exact key and no known alias "
                                             "family for '%s'" % requested}
    skipped = []
    for alias in _METRIC_FAMILIES[fam][2] + (fam,):
        for c in ordered:
            if c["base"] != alias and c["name"] != alias:
                continue
            if dim == "count" and (c["unit"] in (None, "count")):
                return c["value"], {"key": c["key"], "match": "alias",
                                    "family": fam, "raw_value": c["value"],
                                    "source_unit": c["unit"], "unit": "count",
                                    "converted": False}
            v, u = _convert(c)
            if v is None:
                skipped.append({"key": c["key"], "reason":
                                "unit %r not convertible to %r" % (c["unit"],
                                                                   target)})
                continue
            return round(v, 12), {"key": c["key"], "match": "alias",
                                  "family": fam, "raw_value": c["value"],
                                  "source_unit": c["unit"],
                                  "unit_basis": c["unit_basis"], "unit": u,
                                  "converted": c["unit"] != u}
    return None, {"skipped": skipped}


def _requested_metrics(params):
    m = params.get("metrics")
    if m:
        return list(m)
    if isinstance(params.get("baseline"), dict) and params["baseline"]:
        return sorted(params["baseline"])
    return None


def _file_sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_path(s):
    return isinstance(s, str) and (s.lower().endswith(".json")
                                   or "/" in s or "\\" in s)


def _load_cde_file(path):
    if not os.path.isfile(str(path)):
        # A silently dropped envelope skews every aggregate that follows (and a
        # trajectory over the survivors misstates n); fail loudly instead.
        raise ValueError("envelope path '%s' does not exist (CDE files must be "
                         "mounted, e.g. /input/cde/<stage>.json)" % path)
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as _e:
        raise ValueError("envelope '%s' is not valid JSON: %s"
                         % (os.path.basename(str(path)), _e))
    if not isinstance(d, dict):
        raise ValueError("envelope '%s' is not a JSON object" % path)
    return d


def _load_envelopes(params):
    """Normalise `envelopes` into {id, hash, metrics, metric_sources, ...}.

    Accepted entries: an inline {id, metrics:{...}} dict; a CDE FILE PATH
    string; or a dict naming a file via path/file/cde/cde_path/envelope (or a
    `hash` that is itself a .json path, as agents do). A file is LOADED and the
    requested metrics are extracted from results.<k>.value / results.<k> and
    qor_metrics.<k> with family aliasing + unit conversion; every value records
    the key it came from. Previously a path string loaded only qor_metrics under
    the exact requested name, and a {id, hash:"/input/cde/x.json"} dict loaded
    nothing at all -- 7 real CDEs yielded n_used=0 for every metric."""
    requested = _requested_metrics(params)
    envs = []
    for idx, e in enumerate(params.get("envelopes", []) or []):
        entry = dict(e) if isinstance(e, dict) else {}
        path = None
        if isinstance(e, str):
            path = e
        elif isinstance(e, dict):
            for k in _PATH_KEYS:
                if isinstance(e.get(k), str) and e[k]:
                    path = e[k]
                    break
            if path is None and not e.get("metrics") \
                    and _looks_like_path(e.get("hash")):
                path = e["hash"]
        else:
            raise ValueError("envelope #%d must be a CDE path or an object, "
                             "got %s" % (idx + 1, type(e).__name__))
        if path is None and not entry.get("id"):
            raise ValueError("each envelope needs an 'id' referencing its "
                             "source CDE (or a CDE file path)")
        cands = _inline_candidates(entry.get("metrics"))
        env = {k: v for k, v in entry.items()
               if k not in ("metrics",) + _PATH_KEYS}
        env["list_position"] = idx + 1
        if path is not None:
            cde = _load_cde_file(path)
            cands += _cde_candidates(cde)
            env.setdefault("id", os.path.splitext(os.path.basename(
                str(path)))[0])
            env["source_cde"] = str(path)
            if not env.get("hash") or _looks_like_path(env.get("hash")):
                env["hash"] = "sha256:" + _file_sha256(path)
            env["cde_tool"] = cde.get("tool")
            env["cde_status"] = cde.get("status")
            env["cde_verdict"] = (cde.get("validation") or {}).get("verdict")
            # recorded for audit, NOT used for ordering (list order is)
            env["cde_finished_utc"] = (cde.get("provenance") or {}).get(
                "finished_utc")
            pb = cde.get("pdk_binding")
            if isinstance(pb, dict) and pb.get("pdk") and "pdk" not in env:
                env["pdk"] = pb["pdk"]
        env.setdefault("hash", None)
        names = requested if requested is not None else sorted(
            {c["orig"] for c in cands})
        metrics, sources, unresolved = {}, {}, {}
        for m in names:
            v, src = _resolve_metric(m, cands)
            if v is None:
                unresolved[m] = src
            else:
                metrics[m] = v
                sources[m] = src
        env["metrics"] = metrics
        env["metric_sources"] = sources
        env["unresolved_metrics"] = sorted(unresolved)
        env["_unresolved_detail"] = unresolved
        env["_from_file"] = path is not None
        envs.append(env)
    return envs


def _extraction_summary(envs, metrics):
    """Per-metric point counts and per-run source keys (audit trail)."""
    per_metric = {m: sum(1 for e in envs if m in e.get("metrics", {}))
                  for m in (metrics or [])}
    runs = []
    for e in envs:
        runs.append({"id": e["id"], "source_cde": e.get("source_cde"),
                     "hash": e.get("hash"), "cde_status": e.get("cde_status"),
                     "sources": {m: s.get("key") for m, s in
                                 e.get("metric_sources", {}).items()},
                     "conversions": {m: "%s %s -> %s %s" % (
                         s.get("raw_value"), s.get("source_unit"),
                         e["metrics"][m], s.get("unit"))
                         for m, s in e.get("metric_sources", {}).items()
                         if s.get("converted")},
                     "unresolved": e.get("unresolved_metrics", []),
                     "skipped_candidates": {
                         m: d.get("skipped") for m, d in
                         (e.get("_unresolved_detail") or {}).items()
                         if d.get("skipped")}})
    return {"points_per_metric": per_metric,
            "files_loaded": sum(1 for e in envs if e.get("_from_file")),
            "runs": runs}


def _aggregate(params):
    envs = _load_envelopes(params)
    if not envs:
        return _cde(objective="aggregate QoR", status="failed",
                    error="no envelopes supplied", validation={"verdict": "fail"})
    _comp = qor_stats.comparability(envs)
    metrics = params.get("metrics") or sorted({k for e in envs for k in e.get("metrics", {})})
    dataset = []
    for e in envs:
        row = {"id": e["id"], "source_cde": e.get("hash"),
               "source_file": e.get("source_cde")}
        for m in metrics:
            row[m] = e.get("metrics", {}).get(m)
            _src = e.get("metric_sources", {}).get(m)
            if _src:
                row[m + "__source"] = _src.get("key")
        dataset.append(row)
    open(os.path.join(_OUTPUT_DIR, "qor_dataset.json"), "w").write(json.dumps(dataset, indent=2))
    stats = {}
    for m in metrics:
        vals = [r[m] for r in dataset if isinstance(r.get(m), (int, float))]
        if vals:
            stats[m] = {"mean": round(statistics.mean(vals), 4),
                        "min": min(vals), "max": max(vals),
                        "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
                        # N IS PER METRIC, NOT THE RUN TOTAL. Runs missing a
                        # metric are silently skipped above, so reporting only
                        # `runs` made a mean over 5 of 10 runs indistinguishable
                        # from a mean over 10 -- and a stdev that shrank because
                        # FEWER RUNS REPORTED looked like improving consistency.
                        "n_used": len(vals), "n_runs": len(dataset),
                        "polarity": qor_stats.resolve_polarity(
                            m, params.get("metric_polarity")).get("polarity")}
    _missing = [m for m in metrics if m not in stats]
    return _cde(objective="aggregate cross-run QoR", status="completed",
                results={"runs": {"value": len(envs), "unit": "count",
                                  "class": "descriptive",
                                  "basis": "supplied_envelopes",
                                  "note": ("Total envelopes pooled. Per-metric "
                                           "sample size is `n_used` in each qor "
                                           "entry and is often smaller.")}},
                qor=stats,
                signoff={"dataset": "qor_dataset.json", "metrics": metrics,
                         "comparability": _comp,
                         "pooled_statistics_assessable": _comp.get("comparable") is True and not _missing and bool(stats),
                         "metric_extraction": _extraction_summary(envs, metrics),
                         "all_points_reference_source": all("id" in e for e in envs)},
                inputs_ref={"runs": [e["id"] for e in envs]},
                assumptions=[
                    "per-metric n_used is reported alongside every statistic; a "
                    "metric absent from a run is excluded, never treated as zero",
                    "comparability across design/corner/PDK/tool-version is "
                    "checked, and reported as not_assessable when the envelopes "
                    "carry no context fields to check"],
                validation={"verdict": ("not_assessable" if not stats or _missing
                                        else "fail" if _comp.get("comparable") is False
                                        else "not_assessable"
                                        if _comp.get("comparable") is not True
                                        else "completed"),
                            "note": _comp.get("note")})


def _trajectory(params):
    """Fit each metric's trend across ORDERED runs.

    This scenario previously did not exist: `trajectory` was an ALIAS for
    `aggregate`, which treats the envelopes as an unordered SET. Mean, min, max
    and stdev are all order-invariant, so the question "is this getting better
    or worse?" was not merely unanswered -- it was unanswerable, while the
    agent's description claimed to "track a metric's trajectory over ordered
    runs".
    """
    envs = _load_envelopes(params)
    if not envs:
        return _cde(objective="QoR trajectory", status="failed",
                    error="no envelopes supplied", validation={"verdict": "fail"})
    _comp = qor_stats.comparability(envs)
    metrics = params.get("metrics") or sorted({k for e in envs
                                               for k in e.get("metrics", {})})
    rows = []
    for e in envs:
        row = {"id": e["id"], "list_position": e.get("list_position")}
        for f in _ORDER_FIELDS:
            if e.get(f) is not None:
                row[f] = e[f]
        _ok = params.get("order_key")
        if _ok and e.get(_ok) is not None:
            row[_ok] = e[_ok]
        row.update({m: e.get("metrics", {}).get(m) for m in metrics})
        row["_sources"] = {m: s.get("key") for m, s in
                           e.get("metric_sources", {}).items()}
        rows.append(row)

    declared = params.get("metric_polarity")
    # CDE files carry no sequence field of their own, so a list of paths is
    # ordered AS SUPPLIED (stage order) rather than by a natural sort of file
    # stems, which would put chip-cts before chip-floorplanning.
    _fallback = ("list_order" if any(e.get("_from_file") for e in envs)
                 else "natural_id")
    trends = {m: qor_stats.trajectory(rows, m, params.get("order_key"), declared,
                                      fallback=_fallback)
              for m in metrics}
    for t in trends.values():
        key = t["order"].get("key")
        order_values = [r.get(key) for r in rows] if key else []
        order_ready = (t["order"]["basis"] in ("explicit_order_key", "inferred_order_field")
                       and len({str(v) for v in order_values}) == len(rows))
        reasons = []
        if not order_ready:
            reasons.append("an explicit, distinct order field is required on every run")
        if _comp.get("comparable") is not True:
            reasons.append(_comp["note"])
        if t.get("direction") == "unclassified":
            reasons.append("requested polarity is unavailable")
        if reasons:
            t["diagnostic_fit"] = {k: t.get(k) for k in
                                   ("slope_per_run", "intercept", "r_squared", "direction", "fit_quality")}
            t.update({"assessable": False, "slope_per_run": None,
                      "r_squared": None, "direction": None,
                      "note": "; ".join(reasons)})

    assessable = [t for t in trends.values() if t.get("assessable")]
    degrading = [t for t in assessable
                 if t.get("direction") == "degrading"
                 and t.get("fit_quality") == "strong"]
    unclassified = [t for t in trends.values()
                    if t.get("direction") == "unclassified"
                    or t.get("diagnostic_fit", {}).get("direction") == "unclassified"]

    if _comp.get("comparable") is False:
        verdict, note = "fail", _comp["note"]
    elif not assessable:
        verdict, note = "not_assessable", (
            "no requested metric met all trend prerequisites (3 ordered, "
            "comparable points with classifiable direction); "
            "nothing about the direction of travel is established (points per "
            "metric: %s)" % ", ".join("%s=%d" % (m, t.get("n_used", 0))
                                      for m, t in trends.items()))
    elif degrading:
        verdict, note = "fail", (
            "%d metric(s) are on a strong DEGRADING trend: %s"
            % (len(degrading), ", ".join(sorted(t["metric"] for t in degrading))))
    elif unclassified or len(assessable) != len(trends) or _comp.get("comparable") is not True:
        verdict, note = "not_assessable", (
            "trend gate remains open: unclassified/insufficient metrics or "
            "unassessable comparability; " + _comp["note"])
    else:
        verdict, note = "pass", (
            "no strongly degrading trend among %d fitted metric(s)" % len(assessable))

    return _cde(
        objective="QoR trajectory over ordered runs", status="completed",
        results={
            "runs": {"value": len(envs), "unit": "count", "class": "descriptive",
                     "basis": "supplied_envelopes"},
            "degrading_trends": {
                "value": len(degrading), "unit": "count", "class": "gating",
                "closes_at": "== 0", "basis": "least_squares_fit_over_ordered_runs",
                "note": ("Metrics moving in the BAD direction (per polarity) with "
                         "a strong fit. A weak fit is deliberately not counted: "
                         "scattered runs are noise, and gating on noise would "
                         "make the stage unclosable for reasons unrelated to QoR.")},
            "unclassified_trends": {
                "value": len(unclassified), "unit": "count", "class": "gating",
                "closes_at": "== 0", "basis": "polarity_resolution",
                "note": ("Metrics that MOVED but whose polarity is unknown, so "
                         "improvement and regression cannot be told apart. "
                         "Gating because an unclassifiable change may be a "
                         "regression; declare `metric_polarity` to resolve it.")},
            "metrics_fitted": {
                "value": len(assessable), "unit": "count", "class": "diagnostic",
                "basis": "least_squares_fit_over_ordered_runs"}},
        qor={m: {k: t.get(k) for k in
                 ("slope_per_run", "r_squared", "direction", "net_change",
                  "n_used", "n_runs")}
             for m, t in trends.items()},
        signoff={"trajectories": trends, "comparability": _comp,
                 "metric_extraction": _extraction_summary(envs, metrics),
                 "order_basis": (list(trends.values())[0]["order"]
                                 if trends else None)},
        inputs_ref={"runs": [e["id"] for e in envs]},
        assumptions=[
            "a trajectory is a claim about a SEQUENCE, so runs are explicitly "
            "ordered and the ordering basis is recorded with the result",
            "at least 3 points are required; two points always fit a line with "
            "R^2 = 1 and would masquerade as the strongest possible evidence"],
        validation={"verdict": verdict, "note": note})


def _anomaly(params):
    envs = _load_envelopes(params)
    baseline = params.get("baseline", {})
    if not baseline:
        return _cde(objective="anomaly detection", status="failed",
                    error="anomaly_detect requires an explicit 'baseline'",
                    validation={"verdict": "fail"})
    if not envs:
        return _cde("anomaly detection", "failed", error="no envelopes supplied",
                    validation={"verdict": "fail"})
    comp = qor_stats.comparability(envs)
    metrics = params.get("metrics") or sorted(baseline)
    # NAMING: this is a PERCENT threshold, not a number of standard deviations.
    # The parameter was called `sigma` while being compared against a percent
    # change, so `sigma=3` meant "3 percent", not "3 sigma" -- a reader budgeting
    # a 3-sigma tolerance was actually getting a hair-trigger. `threshold_percent`
    # is now the real name; `sigma` is still accepted so existing callers keep
    # working, and which one was used is recorded in the output.
    _sigma_legacy = params.get("sigma")
    _thr = params.get("threshold_percent", _sigma_legacy)
    threshold = max(float(_thr if _thr is not None else 5.0), 5.0)
    declared = params.get("metric_polarity")

    regressions, improvements, unclassified = [], [], []
    for e in envs:
        for m in metrics:
            c = qor_stats.classify_change(
                m, e.get("metrics", {}).get(m), baseline.get(m), declared)
            if c is None:
                continue
            pct = c.get("delta_percent")
            if pct is not None and abs(pct) < threshold:
                continue
            c["id"] = e["id"]
            c["source_cde"] = e.get("hash")
            if c["direction"] == "regression":
                regressions.append(c)
            elif c["direction"] == "improvement":
                improvements.append(c)
            elif c["direction"] == "unclassified":
                unclassified.append(c)

    extraction = _extraction_summary(envs, metrics)
    missing = [m for m, n in extraction["points_per_metric"].items()
               if n != len(envs) or not _is_num(baseline.get(m))]
    if missing:
        verdict, note = "not_assessable", "no comparable measurements for: " + ", ".join(missing)
    elif comp.get("comparable") is False:
        verdict, note = "fail", comp["note"]
    elif comp.get("comparable") is not True:
        verdict, note = "not_assessable", comp["note"]
    elif regressions:
        verdict = "fail"
        note = ("%d QoR REGRESSION(S) vs baseline (moves in the bad direction "
                "for the metric's polarity); %d improvement(s) also seen and "
                "NOT counted against the design"
                % (len(regressions), len(improvements)))
    elif unclassified:
        verdict = "not_assessable"
        note = ("comparability: %s; no classifiable regression, but %d metric(s) moved whose "
                "polarity is unknown, so improvement and regression cannot be "
                "told apart: %s. Declare `metric_polarity` to resolve."
                % (comp["note"], len(unclassified),
                   ", ".join(sorted({c["metric"] for c in unclassified}))))
    else:
        verdict = "pass"
        note = ("no regressions vs baseline (%d improvement(s) observed)"
                % len(improvements))

    return _cde(objective="QoR anomaly/regression detection", status="completed",
                results={
                    "runs": {"value": len(envs), "unit": "count",
                             "class": "descriptive", "basis": "supplied_envelopes"},
                    "regressions": {
                        "value": len(regressions), "unit": "count",
                        "class": "gating", "closes_at": "== 0",
                        "basis": "polarity_aware_comparison_to_baseline",
                        "note": ("Moves in the BAD direction only. Previously "
                                 "this count was |percent change|, with no "
                                 "notion of direction, so a slack IMPROVEMENT "
                                 "and an area REGRESSION were both reported as "
                                 "regressions and both failed the gate.")},
                    "improvements": {
                        "value": len(improvements), "unit": "count",
                        "class": "diagnostic",
                        "basis": "polarity_aware_comparison_to_baseline",
                        "note": "Reported, and never counted against the design."},
                    "unclassified_changes": {
                        "value": len(unclassified), "unit": "count",
                        "class": "gating", "closes_at": "== 0",
                        "basis": "polarity_resolution",
                        "note": ("Changes whose direction could not be judged "
                                 "because the metric's polarity is unknown. "
                                 "Gating: an unclassifiable change may be a "
                                 "regression and must not read as clean.")}},
                signoff={"regressions": regressions,
                         "improvements": improvements,
                         "unclassified_changes": unclassified,
                         "baseline": baseline,
                         "threshold_percent": threshold,
                         "threshold_parameter_used": (
                             "threshold_percent" if params.get("threshold_percent")
                             is not None else "sigma (legacy alias for percent)"
                             if _sigma_legacy is not None else "default 5%"),
                         "comparability": comp,
                         "metric_extraction": _extraction_summary(envs, metrics)},
                inputs_ref={"runs": [e["id"] for e in envs]},
                assumptions=[
                    "a change is a regression only when it moves in the bad "
                    "direction FOR THAT METRIC; polarity is resolved from a "
                    "known-metric table or caller declaration, never guessed",
                    "the threshold is a PERCENT change, not a standard deviation"],
                validation={"verdict": verdict, "note": note})


def dispatch(params):
    s = params.get("scenario")
    if s in ("aggregate", "baseline_update"):
        return _aggregate(params)
    if s == "trajectory":
        return _trajectory(params)
    if s == "anomaly_detect":
        return _anomaly(params)
    return _cde(objective="qor analytics", status="failed",
                error=(f"unknown scenario '{s}'; supported: aggregate, "
                       "trajectory, anomaly_detect, baseline_update"),
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
