#!/usr/bin/env python3
"""power_analysis_utils.py -- real OpenROAD power + PSM static IR-drop.

Reads node LEF/Liberty + a routed DEF (+ optional SDC/SPEF), runs report_power and
PSM `analyze_power_grid` on the VDD net, and reports the power breakdown and worst
IR drop vs the node budget. Node-aware. Results conform to the Common Design Envelope.
"""
import csv
import json
import math
import os
import re
import shutil
import subprocess
import time

TOOL = "power-analysis"
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
    """Persist the exact tool invocation (argv) for provenance / debug review.

    Captures the command whether the tool runs a generated script (e.g. `openroad
    -exit /output/cts.tcl`) or a direct command with inline args (e.g. a verilator
    lint line). Written next to the results so the Engine or a human can see exactly
    what was submitted to the solver."""
    try:
        import shlex
        if isinstance(cmd, (list, tuple)):
            line = " ".join(shlex.quote(str(c)) for c in cmd)
        else:
            line = str(cmd)
        with open(os.path.join(_OUTPUT_DIR, name), "w", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as _e:
        print("[" + str(TOOL) + "] run-command capture skipped: " + str(_e), flush=True)



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


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         margin=None, assumptions=None, validation=None, provenance=None,
         inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD PSM", "version": "openroad"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": margin or {"method": "ir_analysis"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _specialnets_via_stats(def_path):
    """Return (via_count, stripe_layers) from the SPECIALNETS section of a DEF.
    Count routed-point via placements, not VIAS definitions. Also retain the
    explicit '+ VIA' spelling. Returns (None, []) if the DEF cannot be read."""
    try:
        with open(def_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None, []
    section = re.search(r"\bSPECIALNETS\s+\d+\s*;(.*?)\bEND\s+SPECIALNETS\b",
                        text, re.S)
    if section is None:
        return 0, []
    text = re.sub(r"#[^\n]*", "", section.group(1))
    layers = set(re.findall(r"\b(?:ROUTED|NEW)\s+([^\s()+;]+)\s+\d+", text))
    point = r"\(\s*(?:-?\d+|\*)\s+(?:-?\d+|\*)(?:\s+(?:-?\d+|\*))?\s*\)"
    following = re.findall(point + r"\s+([^\s()+;]+)", text)
    keywords = {"NEW", "MASK", "STYLE", "SHAPE", "RECT", "POLYGON",
                "VIRTUAL", "DO", "STEP", "TAPER", "TAPERRULE"}
    vias = sum(token.upper() not in keywords for token in following)
    vias += len(re.findall(r"\+\s+VIA\s+[^\s()+;]+", text))
    return vias, sorted(layers)


def _specialnets_layer_widths(def_path):
    """Return {layer: min_width_um} for PDN wires in the SPECIALNETS section.

    DEF special wiring carries its width explicitly ('ROUTED met4 1600', 'NEW met1
    480') in DEF database units, so the conductor width an EM screen needs is
    recoverable from the same DEF PSM analysed. The MINIMUM width seen on a layer
    is kept because it yields the smallest (most conservative) current limit for
    that layer; the width actually used is reported so a reviewer can see it.
    Returns {} if the DEF cannot be read -- an empty map makes routing-layer EM
    not_assessable rather than clean."""
    widths = {}
    try:
        units = None
        in_sn = False
        with open(def_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip()
                if units is None:
                    m = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", s)
                    if m:
                        units = float(m.group(1))
                if s.startswith("SPECIALNETS"):
                    in_sn = True
                    continue
                if s.startswith("END SPECIALNETS"):
                    break
                if not in_sn:
                    continue
                for lyr, w in re.findall(r"(?:ROUTED|NEW)\s+(\w+)\s+(\d+)", line):
                    if not units:
                        continue
                    um = int(w) / units
                    if um <= 0:
                        continue
                    widths[lyr] = min(widths.get(lyr, um), um)
    except OSError:
        return {}
    return widths


def _lef_layer_stack(tech_lef):
    """Return the ordered tech-LEF layer stack as a list of dicts.

    Each entry is {name, type, dc_ma}: 'type' is ROUTING/CUT/other and 'dc_ma' is
    the LEF DCCURRENTDENSITY AVERAGE value -- mA/um on a ROUTING layer, mA per via
    on a CUT layer. FILE ORDER IS PRESERVED because it is what identifies the cut
    layer sitting between two routing layers; the via layer is therefore DERIVED
    from the binding's own stack rather than hard-coded per node (a name table
    like met1->'via' is a node constant and would silently mis-resolve on any
    other PDK). Returns [] if the LEF cannot be read."""
    stack = []
    try:
        with open(tech_lef, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return []
    for m in re.finditer(r"^\s*LAYER\s+(\S+)\s*$(.*?)^\s*END\s+\1\s*$",
                         text, re.S | re.M):
        name, body = m.group(1), m.group(2)
        tm = re.search(r"^\s*TYPE\s+(\w+)\s*;", body, re.M)
        dm = re.search(r"^\s*DCCURRENTDENSITY\s+AVERAGE\s+([0-9.eE+-]+)\s*;", body, re.M)
        stack.append({"name": name,
                      "type": (tm.group(1).upper() if tm else "UNKNOWN"),
                      "dc_ma": (float(dm.group(1)) if dm else None)})
    return stack


def _cut_layer_between(stack, a, b):
    """Return the name of the single CUT layer between routing layers a and b.

    Returns None when the stack does not resolve exactly one cut layer between
    them, so an ambiguous stack yields not_assessable instead of a guessed via."""
    idx = {e["name"]: i for i, e in enumerate(stack)}
    if a not in idx or b not in idx:
        return None
    lo, hi = sorted((idx[a], idx[b]))
    cuts = [e["name"] for e in stack[lo + 1:hi] if e["type"] == "CUT"]
    return cuts[0] if len(cuts) == 1 else None


def _screen_em(em_rpt, tech_lef, def_path):
    """Screen the PSM EM report against the node's LEF current limits.

    OpenROAD PSM writes a CSV of per-segment CURRENT IN AMPERES with the layer at
    each end and NO conductor width, so a current-density number is not derivable
    from this report alone. The screen is therefore performed in AMPERES: the LEF
    limit is converted into a per-segment current limit using the conductor width
    for routing layers (mA/um * um) and used directly for vias (mA per via).

    A layer whose limit or width cannot be resolved is reported not_assessable and
    NEVER folded into the clean count, because dropping an unresolvable layer
    would shrink the violation set and raise the reported margin."""
    res = {"status": "not_assessable", "report": os.path.basename(em_rpt),
           "segments": 0, "violations": 0, "worst_utilization": None,
           "max_current_a": None, "per_layer": [], "unresolved_layers": [],
           "limit_basis": "LEF DCCURRENTDENSITY AVERAGE (Iavg, DC)",
           "note": None}
    try:
        with open(em_rpt, encoding="utf-8", errors="ignore") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error, UnicodeError):
        # A malformed report must degrade to not_assessable, never crash the stage
        # and never be mistaken for a clean screen.
        res["note"] = "EM was requested but the PSM EM report could not be read"
        return res
    if not rows:
        res["note"] = "PSM EM report is empty; nothing was screened"
        return res
    stack = _lef_layer_stack(tech_lef)
    if not stack:
        res["note"] = ("tech LEF layer stack unreadable; no EM current limit could "
                       "be resolved")
        res["segments"] = len(rows)
        return res
    dc = {e["name"]: e["dc_ma"] for e in stack}
    kind = {e["name"]: e["type"] for e in stack}
    widths = _specialnets_layer_widths(def_path)
    agg = {}
    for r in rows:
        try:
            a = (r.get("Node0 Layer") or "").strip()
            b = (r.get("Node1 Layer") or "").strip()
            cur = abs(float(r.get("Current")))
        except (TypeError, ValueError):
            continue
        res["segments"] += 1
        res["max_current_a"] = max(res["max_current_a"] or 0.0, cur)
        key = a if a == b else (_cut_layer_between(stack, a, b) or f"{a}->{b}")
        e = agg.setdefault(key, {"layer": key, "segments": 0, "max_current_a": 0.0,
                                 "via": a != b})
        e["segments"] += 1
        e["max_current_a"] = max(e["max_current_a"], cur)
    for key, e in sorted(agg.items()):
        lim_ma = dc.get(key)
        if lim_ma is None:
            e["limit_a"] = None
            e["reason"] = ("no DCCURRENTDENSITY AVERAGE for this layer in the tech "
                           "LEF" if key in dc or key in kind else
                           "layer not resolved in the tech LEF stack")
            res["unresolved_layers"].append(key)
        elif kind.get(key) == "CUT":
            # mA per via -> an absolute per-segment current limit; no width needed.
            e["limit_a"] = lim_ma / 1000.0
            e["width_um"] = None
        else:
            w = widths.get(key)
            if w is None:
                e["limit_a"] = None
                e["reason"] = ("no conductor width for this routing layer in DEF "
                               "SPECIALNETS; mA/um limit cannot be converted to a "
                               "current limit")
                res["unresolved_layers"].append(key)
            else:
                e["limit_a"] = lim_ma * w / 1000.0
                e["width_um"] = w
        if e.get("limit_a"):
            e["utilization"] = e["max_current_a"] / e["limit_a"]
            e["violated"] = e["utilization"] > 1.0
            if e["violated"]:
                res["violations"] += 1
            res["worst_utilization"] = max(res["worst_utilization"] or 0.0,
                                           e["utilization"])
        else:
            e["utilization"] = None
            e["violated"] = None
        res["per_layer"].append(e)
    if res["violations"]:
        res["status"] = "fail"
        res["note"] = (f"{res['violations']} layer(s) exceed the node EM current "
                       f"limit (worst utilization "
                       f"{res['worst_utilization']:.2f}x)")
    elif res["unresolved_layers"]:
        res["status"] = "not_assessable"
        res["note"] = ("EM limits unresolved for: "
                       + ", ".join(sorted(set(res["unresolved_layers"])))
                       + "; screened layers are within limit but the run is NOT "
                         "EM-clean")
    elif not res["per_layer"] or res["worst_utilization"] is None:
        # Rows were present but none yielded a layer with a resolved limit (a
        # truncated or malformed report). Zero segments compared is NOT a clean
        # screen -- reporting "pass" here would be a check that cannot fail.
        res["status"] = "not_assessable"
        res["note"] = ("no EM segment could be compared against a limit; the PSM "
                       "report parsed to zero usable rows")
    else:
        res["status"] = "pass"
        res["note"] = (f"all {len(res['per_layer'])} conductor layers within the "
                       f"node EM current limit (worst utilization "
                       f"{res['worst_utilization']:.2f}x)")
    return res


def _parse_power_table(out):
    """Parse the OpenROAD report_power table into a per-group power breakdown.

    report_power prints Internal / Switching / Leakage / Total watts per group
    (Sequential, Combinational, Clock, Macro, Pad) plus a Total row. Capturing
    only the 4th column of the Total row discards the entire breakdown -- and the
    breakdown is what makes a power number actionable (leakage-dominated and
    switching-dominated designs need opposite fixes). Returns {} when the table
    is absent."""
    bd = {}
    for m in re.finditer(r"^\s*(Sequential|Combinational|Clock|Macro|Pad|Total)\s+"
                         r"([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+"
                         r"([0-9.eE+-]+)(?:\s+([0-9.]+)%)?\s*$", out, re.M):
        try:
            row = {"internal_w": float(m.group(2)), "switching_w": float(m.group(3)),
                   "leakage_w": float(m.group(4)), "total_w": float(m.group(5))}
        except ValueError:
            continue
        if m.group(6) is not None:
            row["percent_of_total"] = float(m.group(6))
        bd[m.group(1).lower()] = row
    return bd


def _normalize_saif(saif_path):
    """Return a path to a SAIF whose top token is the IEEE-standard '(SAIFILE'.

    A common generator mistake writes the header token as '(SAIFFILE' (double F),
    which OpenSTA's read_saif rejects with STA-0169 (malformed SAIF), aborting an
    otherwise-clean activity annotation (observed in DX-35). If the supplied SAIF
    uses the misspelling, write a corrected copy into the work dir and return it;
    otherwise return the original path unchanged. Fails soft: on any read/write
    error the original path is returned so OpenSTA still surfaces the real error."""
    try:
        with open(saif_path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return saif_path
    if "(SAIFFILE" not in text:
        return saif_path
    fixed = re.sub(r"\(SAIFFILE\b", "(SAIFILE", text)
    try:
        os.makedirs(_WORK_DIR, exist_ok=True)
        out_path = os.path.join(_WORK_DIR, "_normalized.saif")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(fixed)
        return out_path
    except OSError:
        return saif_path


def _power_ir(params):
    if not shutil.which("openroad"):
        return _cde(objective="power/IR", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    top, def_file = params.get("top"), params.get("def_file")
    binding = params.get("pdk_binding") or {}
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    libs = _as_list(params.get("liberty") or binding.get("liberty"))
    sdc, spef = params.get("sdc"), params.get("spef")
    vdd_net = params.get("vdd_net", "VDD")
    vdd_v = float(params.get("vdd_voltage") or binding.get("vdd_voltage") or 1.8)
    ir_budget = ((binding.get("ir_limits") or {}).get("max_drop_fraction"))
    # Total-power budget. Power was measured and reported but never compared to
    # anything, so a design far over its power budget still closed this stage on
    # the strength of its IR number alone.
    power_budget_w = params.get("power_budget_w")
    if power_budget_w is None:
        power_budget_w = (binding.get("power_limits") or {}).get("max_total_w")
    power_budget_w = float(power_budget_w) if power_budget_w is not None else None
    for n, v in (("top", top), ("def_file", def_file), ("tech_lef", tech_lef)):
        if not v:
            return _cde(objective="power/IR", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}'", validation={"verdict": "fail"})
    for p in [def_file, tech_lef] + cell_lefs + libs:
        if not os.path.exists(str(p)):
            return _cde(objective="power/IR", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    lef_reads = "\n".join([f"read_lef {tech_lef}"] + [f"read_lef {c}" for c in cell_lefs])
    lib_reads = "\n".join(f"read_liberty {l}" for l in libs)
    # A SUPPLIED-but-missing SDC/SPEF must not be silently dropped. Both change the
    # headline numbers (SPEF supplies the interconnect RC that dynamic power and IR
    # are computed over), so quietly analysing without them returns an optimistic
    # result under the caller's belief that parasitics were applied.
    for _n, _p in (("sdc", sdc), ("spef", spef),
                   ("vcd", params.get("vcd")), ("saif", params.get("saif"))):
        if _p and not os.path.exists(str(_p)):
            return _cde(objective="power/IR", status="failed", pdk_binding=binding or "none",
                        error=(f"'{_n}' was supplied as {_p} but does not exist; refusing "
                               f"to analyse without it because the result would be "
                               f"reported as if it had been applied"),
                        validation={"verdict": "fail"})
    sdc_line = f"read_sdc {sdc}" if sdc else ""
    spef_line = f"read_spef {spef}" if spef else ""
    parasitics_basis = "spef" if spef else "none"
    volt_rpt = os.path.join(_OUTPUT_DIR, "ir.rpt")
    # Switching-activity source for dynamic (vector-based) power. A VCD or SAIF
    # gives real toggle activity; otherwise an optional global activity factor,
    # else the tool's static default.
    _vcd = params.get("vcd")
    _saif = params.get("saif")
    _act_line = ""
    _power_mode = "default_activity"
    if _vcd and os.path.exists(str(_vcd)):
        _scope = params.get("activity_scope")
        _act_line = f"read_vcd {'-scope ' + _scope + ' ' if _scope else ''}{_vcd}"
        _power_mode = "vcd"
    elif _saif and os.path.exists(str(_saif)):
        _saif = _normalize_saif(str(_saif))
        _act_line = f"read_saif {_saif}"
        _power_mode = "saif"
    else:
        _af = params.get("activity_factor")
        if _af is not None:
            _act_line = f"set_power_activity -global -activity {_af}"
            _power_mode = f"global_activity={_af}"
    # IR-analysis levers. source_type models the supply source (FULL/BUMPS/
    # STRAPS); enable_em additionally screens electromigration current density.
    _apg_opts = ""
    _src_type = params.get("source_type")
    if _src_type:
        _apg_opts += f" -source_type {_src_type}"
    _em_rpt = os.path.join(_OUTPUT_DIR, "em.rpt")
    _enable_em = str(params.get("enable_em", "")).lower() in ("1", "true", "yes")
    if _enable_em:
        _apg_opts += f" -enable_em -em_outfile {_em_rpt}"
    script = f"""{lib_reads}
{lef_reads}
read_def {def_file}
{sdc_line}
{spef_line}
{_act_line}
puts "__POWER__"
report_power
report_power > {os.path.join(_OUTPUT_DIR, "power.rpt")}
puts "__IR__"
set_pdnsim_net_voltage -net {vdd_net} -voltage {vdd_v}
puts "__PGCHECK__"
if {{[catch {{check_power_grid -net {vdd_net}}} _pg]}} {{ puts "__PG_ERR__ $_pg" }} else {{ puts "__PG_OK__" }}
analyze_power_grid -net {vdd_net} -error_file {volt_rpt}{_apg_opts}
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "power.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command(["openroad", "-exit", sp])
    proc = subprocess.run(["openroad", "-exit", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "power.log"), "w").write(out)
    if proc.returncode != 0 and "__POWER__" not in out:
        return _cde(objective=f"power/IR of {top}", status="failed", pdk_binding=binding or "none",
                    error="OpenROAD power/IR failed; see power.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "power.log"})

    def _num(pat):
        m = re.search(pat, out)
        return float(m.group(1)) if m else None

    total_power = _num(r"[Tt]otal\s+[0-9.eE+-]+\s+[0-9.eE+-]+\s+[0-9.eE+-]+\s+([0-9.eE+-]+)")
    # Full per-group Internal/Switching/Leakage/Total breakdown, not just the one
    # Total-row cell the headline number comes from.
    power_breakdown = _parse_power_table(out)
    if total_power is None and "total" in power_breakdown:
        total_power = power_breakdown["total"]["total_w"]
    # OpenROAD PSM prints the worst IR as "Worstcase IR drop: <v> V" (and older
    # builds "Worst-case IR drop" / "Worst IR Drop"); the [-\s]*(?:case)? span
    # accepts all three spellings. A regex that required "Worst IR Drop" with a
    # literal space missed the real output and blocked a clean run (DX-35).
    worst_ir = _num(r"[Ww]orst[-\s]*(?:case)?\s*IR\s+[Dd]rop\s*[:=]?\s*([0-9.eE+-]+)")
    if worst_ir is None:
        worst_ir = _num(r"[Mm]ax\s+voltage\s+drop\s*[:=]?\s*([0-9.eE+-]+)")
    ir_frac = (worst_ir / vdd_v) if (worst_ir is not None and vdd_v) else None
    within = None
    if ir_frac is not None and ir_budget is not None:
        within = ir_frac <= ir_budget
    # PSM connectivity diagnosis. When analyze_power_grid yields no IR number,
    # the usual cause is a disconnected power grid (PSM-0069 and related): PDN
    # stripe layers exist but no SPECIALNETS vias stitch them together. Emit
    # machine-readable evidence so the blocked verdict is self-explaining and
    # never mistaken for a clean pass.
    pg_errors = re.findall(r"__PG_ERR__\s+(.+)", out)
    # Not every PSM-#### line is an error. PSM emits informational notes with the
    # same code prefix -- notably PSM-0040 "All shapes on net ... are connected",
    # which is a SUCCESS message. Treating it as an error spuriously flagged the
    # power grid disconnected on a clean run (DX-35). Filter benign INFO codes.
    _BENIGN_PSM = {"PSM-0040"}
    psm_codes = sorted(c for c in set(re.findall(r"PSM-\d+", out)) if c not in _BENIGN_PSM)
    sn_vias, stripe_layers = _specialnets_via_stats(def_file)
    via_gap = (sn_vias == 0 and len(stripe_layers) >= 2)
    pdn_connectivity_ok = (not pg_errors) and (not psm_codes) and (not via_gap)
    root_cause = None
    if not pdn_connectivity_ok:
        if via_gap:
            root_cause = (f"PDN layers isolated: {len(stripe_layers)} stripe layers "
                          f"({', '.join(stripe_layers)}) but 0 SPECIALNETS vias in the "
                          f"routed DEF. Fix is upstream (pdn/routing add_pdn_connect), "
                          f"not power-ir.")
        elif psm_codes or pg_errors:
            root_cause = ("PSM reported a power-grid error ("
                          + ", ".join(psm_codes or ["see power.log"])
                          + "); grid connectivity must be repaired upstream (pdn/routing).")
    measurements_ok = all(
        value is not None and math.isfinite(value) and value >= 0
        for value in (total_power, worst_ir, ir_frac))
    functional_ok = (proc.returncode == 0 and measurements_ok
                     and "__PG_OK__" in out and pdn_connectivity_ok)
    if not functional_ok:
        # IR is not assessable because the grid is disconnected upstream. Block,
        # do not pass. verdict=review keeps signoff honest (fail-closed).
        verdict = "review"
    else:
        verdict = "fail" if within is False else "pass"
    ir_status = ("not_assessable" if not functional_ok else
                 ("not_gating" if ir_budget is None else
                  ("pass" if within else "fail")))
    # --- EM screen. Previously this stage reported `em_screened: <the flag the
    # caller passed in>`: asking for EM was recorded as having done EM, the
    # em.rpt PSM wrote was never opened, and no current limit was ever read. Now
    # the report is parsed and compared against the node's own LEF limits.
    em = None
    if _enable_em:
        em = _screen_em(_em_rpt, tech_lef, def_file)
        if em["status"] == "fail":
            verdict = "fail"
        elif em["status"] == "not_assessable" and verdict == "pass":
            # EM was requested and could not be established. Do not let an IR pass
            # stand in for an EM result the run does not have.
            verdict = "review"
    # --- Total power vs budget.
    power_within = None
    if power_budget_w is not None and total_power is not None:
        power_within = total_power <= power_budget_w
        if power_within is False:
            verdict = "fail"
    elif power_budget_w is not None and total_power is None:
        # A budget was declared but power could not be parsed -- unmeasured, so
        # it cannot be reported as met.
        if verdict == "pass":
            verdict = "review"
    # SAIF annotation hygiene. read_saif can parse a well-formed SAIF yet annotate
    # ZERO pins when its (INSTANCE ...) hierarchy path does not match the loaded
    # design (wrong top scope / divider). OpenSTA then silently powers the design
    # with vectorless defaults, so a "saif" power_mode is not proof the activity
    # was actually applied. Detect it and flag so provenance is not overstated.
    saif_annotated = None
    saif_activity_effective = None
    if _power_mode == "saif":
        _m = re.search(r"[Aa]nnotated\s+([0-9]+)\s+pin", out)
        if _m:
            saif_annotated = int(_m.group(1))
            saif_activity_effective = saif_annotated > 0
        else:
            # No annotation line at all -> cannot confirm the SAIF took effect.
            saif_activity_effective = False
        if saif_activity_effective is False and verdict == "pass":
            # The gate closed but the claimed activity source did not apply.
            # Downgrade to review so the provenance gap is adjudicated, not hidden.
            verdict = "review"
    power_status = ("not_assessable" if not measurements_ok else
                    ("not_gating" if power_budget_w is None else
                     ("pass" if power_within else "fail")))
    open_items = []
    for metric, budget in (("ir_drop_fraction", ir_budget),
                           ("total_power_w", power_budget_w)):
        if budget is None:
            open_items.append({"metric": metric, "owner": "design-owner",
                               "action": "Declare applicable signoff intent; no budget invented."})
    if _power_mode not in ("vcd", "saif"):
        open_items.append({"metric": "representative_activity", "owner": "verification-owner",
                           "action": "Supply and qualify representative workload activity before power signoff."})
    if not em or em["status"] not in ("pass", "fail"):
        open_items.append({"metric": "em", "owner": "pdk-binding-owner",
                           "action": "Provide applicable EM limits and a compared screen before EM signoff."})
    return _cde(
        objective=f"power and IR-drop analysis of {top}",
        status="completed",
        pdk_binding=binding or "none",
        results={"total_power": {"value": total_power, "unit": "W"},
                 "functional_analysis": {
                     "value": functional_ok, "class": "gating", "closes_at": "== true",
                     "basis": "native_exit_and_parsed_power_ir_grid"},
                 "ir_compliance": {
                     "value": within, "class": "gating" if ir_budget is not None else "diagnostic",
                     "closes_at": "== true" if ir_budget is not None else None,
                     "status": ir_status},
                 "power_compliance": {
                     "value": power_within,
                     "class": "gating" if power_budget_w is not None else "diagnostic",
                     "closes_at": "== true" if power_budget_w is not None else None,
                     "status": power_status},
                 "requested_em_compared": {
                     "value": bool(em and em["status"] == "pass") if _enable_em else None,
                     "class": "gating" if _enable_em else "diagnostic",
                     "closes_at": "== true" if _enable_em else None},
                 "supplied_saif_effective": {
                     "value": saif_activity_effective,
                     "class": "gating" if _power_mode == "saif" else "diagnostic",
                     "closes_at": "== true" if _power_mode == "saif" else None},
                 "power_breakdown": power_breakdown,
                 "worst_ir_drop": {"value": worst_ir, "unit": "V"},
                 "ir_drop_fraction": {"value": ir_frac, "unit": "fraction"},
                 "em_max_current": {"value": (em or {}).get("max_current_a"),
                                    "unit": "A"}},
        qor={"total_power_w": total_power, "worst_ir_v": worst_ir,
             "ir_budget_fraction": ir_budget,
             "internal_power_w": (power_breakdown.get("total") or {}).get("internal_w"),
             "switching_power_w": (power_breakdown.get("total") or {}).get("switching_w"),
             "leakage_power_w": (power_breakdown.get("total") or {}).get("leakage_w"),
             "power_budget_w": power_budget_w,
             "power_within_budget": power_within,
             "em_worst_utilization": (em or {}).get("worst_utilization"),
             "em_violations": (em or {}).get("violations")},
        signoff={"vdd_net": vdd_net, "vdd_voltage_v": vdd_v,
                 "ir_within_budget": within, "ir_report": "ir.rpt", "report": "power.log",
                 "ir_budget_status": ir_status,
                 "power_budget_status": power_status,
                 "functional_analysis_ok": functional_ok,
                 "power_signoff_claimed": False,
                 "open_items": open_items,
                 "power_activity_mode": _power_mode,
                 "saif_annotated_pins": saif_annotated,
                 "saif_activity_effective": saif_activity_effective,
                 "parasitics_basis": parasitics_basis,
                 "power_budget_w": power_budget_w,
                 "power_within_budget": power_within,
                 "em_requested": _enable_em,
                 # True only when the EM report was actually parsed and compared
                 # against a resolved node limit -- not when EM was merely asked for.
                 "em_screened": bool(em and em["status"] in ("pass", "fail")),
                 "em_status": (em or {}).get("status", "not_run"),
                 "em_detail": em,
                 "em_report": "em.rpt" if _enable_em else None,
                 "source_type": _src_type or "default",
                 "pdn_connectivity_ok": pdn_connectivity_ok,
                 "psm_error_codes": psm_codes,
                 "specialnets_via_count": sn_vias,
                 "pdn_stripe_layers": stripe_layers,
                 "ir_blocked_upstream": (worst_ir is None and not pdn_connectivity_ok),
                 "root_cause": root_cause},
        inputs_ref={"def_file": def_file, "sdc": sdc, "spef": spef,
                    "tech_lef": tech_lef, "cell_lef": cell_lefs, "liberty": libs},
        margin={"method": "static IR vs node budget; EM current vs LEF Iavg limit",
                "ir_budget_fraction": ir_budget,
                "power_budget_w": power_budget_w,
                "em_worst_utilization": (em or {}).get("worst_utilization")},
        assumptions=["static IR on the supplied VDD net; dynamic IR needs an activity "
                     "waveform; power uses default activity unless activity is supplied",
                     "stage pass means functional analysis and declared checks, not "
                     "power/IR/EM signoff; measured metrics without budgets are not_gating",
                     f"interconnect parasitics basis: {parasitics_basis}",
                     "EM screen is DC average current (LEF DCCURRENTDENSITY AVERAGE) "
                     "only; PSM reports per-segment current with no conductor width, "
                     "so current DENSITY is not computed and RMS/AC self-heating, "
                     "aging/BTI/HCI and ESD are NOT screened by this stage"],
        validation={"verdict": verdict,
                    "checks": {"functional_analysis": "pass" if functional_ok else "not_assessable",
                               "ir_budget": ir_status, "power_budget": power_status},
                    "note": ((root_cause or "Native analysis, measured power/IR, or connected-grid proof missing")
                             if not functional_ok
                             else ("SAIF parsed but annotated 0 pin activities (hierarchy "
                                   "mismatch); power used vectorless defaults -- verify the "
                                   "SAIF (INSTANCE ...) scope matches the design"
                                   if saif_activity_effective is False
                                   else ("total power exceeds the declared budget "
                                         f"({total_power} W > {power_budget_w} W)"
                                   if power_within is False
                                   else ((em or {}).get("note")
                                   if em and em["status"] in ("fail", "not_assessable")
                                   else ("IR within node budget" if within
                                   else ("IR exceeds node budget" if within is False
                                         else "functional analysis completed; IR is not_gating "
                                              "without a declared budget; no signoff claimed"))))))},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3), "log": "power.log"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s == "power_ir":
        return _power_ir(params)
    return _cde(objective="power/IR", status="failed",
                error=f"unknown scenario '{s}'; supported: power_ir",
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
