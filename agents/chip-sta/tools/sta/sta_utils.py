#!/usr/bin/env python3
"""sta_utils.py -- real OpenSTA static timing analysis for the chip-sta tool.

Generates an OpenSTA Tcl script (read_liberty per corner + read_verilog/read_def +
link + read_sdc + optional read_spef + report_wns/report_tns/report_checks), runs
`sta -exit`, and parses WNS/TNS and worst paths. Liberty and corners come from the
PDK binding. Node-aware. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "sta"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


def _is_ident(s):
    """True if *s* is a safe design identifier -- blocks script injection via
    user-supplied top-module names interpolated into OpenSTA Tcl scripts."""
    return bool(s) and bool(re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", str(s)))


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


def _sta_bin(needs_tech=True):
    """Choose the STA engine, honouring what each one can actually LINK.

    *** NOT INTERCHANGEABLE, AND THE WRONG PICK FAILS VACUOUSLY. *** The two
    binaries differ in exactly the way that matters here:

      * `openroad` (OpenROAD-embedded STA) can read DEF, but its `link_design`
        REQUIRES a technology. With a Verilog netlist and no LEF it aborts with
        `[ERROR ORD-2010] no technology has been read` -- so it analyzes nothing.
      * `sta` (standalone OpenSTA) links a Verilog netlist from Liberty ALONE and
        needs no technology, but cannot read DEF.

    MEASURED 2026-09-02: the old order was a flat `("openroad", "sta")` preference,
    so a gate-level Verilog + Liberty run -- the ordinary post-synthesis STA case --
    picked `openroad`, hit ORD-2010, and produced a VACUOUS run on a design that
    standalone OpenSTA (present in the same image, v3.1.0) analyzes fine.

    The fail-closed logic correctly refused to call that `pass`, so nothing was
    laundered -- but the stage could never close either, and the cause looked like
    a design/input problem rather than an engine-selection one. Failing closed
    stops a false pass; it does not excuse an avoidable false FAIL.

    `needs_tech=False` means "this input can be linked without a technology"
    (Verilog netlist, no LEF supplied) and prefers standalone OpenSTA.
    """
    order = ("openroad", "sta") if needs_tech else ("sta", "openroad")
    for b in order:
        if shutil.which(b):
            return b
    return None


def _sta_version(binname):
    try:
        out = subprocess.run([binname, "-version"], capture_output=True, text=True, timeout=30)
        return (out.stdout + out.stderr).strip().split("\n")[0]
    except Exception:
        return "unknown"


def _worst_corner_name(per_corner, key):
    """Name the corner holding the worst (most negative) slack, or None.

    Diagnostic only. Returns the NAME so a repair can be aimed at the corner that
    actually fails, instead of re-deriving it from the per-corner table by hand.
    """
    worst_name, worst_val = None, None
    for name, vals in (per_corner or {}).items():
        v = (vals or {}).get(key)
        if v is None:
            continue
        if worst_val is None or v < worst_val:
            worst_name, worst_val = name, v
    return worst_name


def _labelled_interpretation(interp):
    """Stamp the model-authored class/basis via the shared vendored module."""
    try:
        import metric_classes
    except Exception:
        base = dict(interp) if isinstance(interp, dict) and interp else {}
        base.setdefault("basis", "agent_read_of_sta_report"
                        if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(
        interp, basis="agent_read_of_sta_report")


def _crosscheck_interpretation(interp, measured, key):
    """Cross-check a model-authored count against the measured one.

    Recorded, never auto-resolved: a stale parser and a confabulated count need
    opposite fixes. A missing shared module is RECORDED rather than swallowed --
    a cross-check that never ran must not look like one that passed.
    """
    try:
        import metric_classes
    except Exception as exc:
        return {"checked": False,
                "reason": "metric_classes module unavailable (%s); the "
                          "cross-check did NOT run" % exc}
    return metric_classes.crosscheck_interpretation(interp, measured, key)


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         assumptions=None, margin=None, validation=None, provenance=None,
         inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenSTA", "version": provenance.get("sta") if provenance else "unknown"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {},
        "margin": margin or {"method": "corner_analysis"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _liberty_list(params):
    lib = params.get("liberty") or (params.get("pdk_binding") or {}).get("liberty")
    if lib is None:
        return None
    return lib if isinstance(lib, list) else [lib]


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, (list, tuple)) else [v]


def _resolve_lefs(params):
    """All LEFs to read: the TECHNOLOGY LEF plus the CELL LEFs.

    Three call sites previously each wrote their own `lef or tech_lef or
    binding.lef or binding.tech_lef` chain. Every one of those chains is an
    `or`, so it stops at the FIRST hit and `cell_lef` was never read at all --
    even though the comment above each said "tech + cell". A standard
    pdk_binding carrying tech_lef AND cell_lef therefore loaded the technology
    with no cell masters, and a DEF referencing those cells died with
    `[WARNING ODB-0099] error: netlist component (_423_) is not defined`
    repeated per instance. Reproduced on crc16_ccitt routed.def with the
    canonical sky130 binding.

    Precedence:
      * an explicit `params.lef` is a COMPLETE caller-supplied list and wins
        outright -- it is the escape hatch, so it must not be merged into;
      * otherwise tech_lef comes first (LEF requires the technology before any
        MACRO that uses its layers), then cell_lef.
    Sources are merged params-first, then pdk_binding, and de-duplicated with
    order preserved so reading the same LEF twice cannot redefine a MACRO.
    """
    explicit = _as_list(params.get("lef"))
    if explicit:
        return list(dict.fromkeys(explicit))
    b = params.get("pdk_binding") or {}
    if not isinstance(b, dict):
        b = {}
    out = (_as_list(params.get("tech_lef")) + _as_list(b.get("tech_lef"))
           + _as_list(params.get("cell_lef")) + _as_list(b.get("cell_lef"))
           + _as_list(b.get("lef")))
    return list(dict.fromkeys(out))


def _parse_annotation(out):
    """Parse the __ANN_BEFORE__/__ANN_AFTER__ report_parasitic_annotation pair.

    Real OpenSTA wording (measured, OpenSTA 3.1.0):
        Found 294 unannotated drivers.
        Found 0 partially unannotated drivers.

    The BEFORE report runs with no parasitics loaded, so every driver is
    unannotated and its count is the total driver count -- the denominator.
    Returns None if either marker is missing, so a parse failure degrades to
    "not measured" rather than to a fabricated 0 that would look like a pass.
    """
    def _count(seg):
        m = re.search(r"Found\s+(\d+)\s+unannotated\s+drivers", seg)
        return int(m.group(1)) if m else None

    if "__ANN_BEFORE__" not in out or "__ANN_AFTER__" not in out:
        return None
    pre = out.split("__ANN_BEFORE__", 1)[1].split("__ANN_AFTER__", 1)[0]
    post = out.split("__ANN_AFTER__", 1)[1]
    before, after = _count(pre), _count(post)
    if before is None or after is None or before <= 0:
        return None
    annotated = before - after
    return {"before": before, "after": after, "annotated": annotated,
            "coverage_pct": round(100.0 * annotated / before, 2)}


def _rc_extra_opts(params):
    """report_checks refinements shared by single- and multi-corner paths:
    report_fields adds columns; from/through/to_pins restrict reported paths."""
    ex = ""
    _rf = params.get("report_fields")
    if _rf:
        ex += " -fields {" + " ".join(_as_list(_rf)) + "}"
    for opt, _v in (("-from", params.get("from_pins")),
                    ("-through", params.get("through_pins")),
                    ("-to", params.get("to_pins"))):
        if _v:
            for pin in _as_list(_v):
                ex += f" {opt} {pin}"
    return ex


# --------------------------------------------------------------------------
# DRV / design-rule + non-path timing checks (report_check_types)
#
# WHY THIS LIVES IN THE TOOL AND NOT IN A SIDECAR RUN:
# The STA gate mandates "max-transition/max-cap clean", but for a long time this
# tool only evaluated setup/hold.  Anyone who wanted DRV had to launch a SECOND,
# hand-written OpenROAD container -- which means the finding landed OUTSIDE the
# instrumented path: outside `qor_metrics`, outside `progress.families`, and
# therefore outside the effort ledger that drives autonomous rung-1/rung-2
# remediation.  Observed live on DX-85: 261 real DRV violations were found by a
# sidecar run, the CDE was amended by hand, but the ledger row still said
# `gate_closed: true` -- so `effort_control.decide()` short-circuited to COMPLETE
# and the pre-authorized auto-reopen (EFFORT-AUTO-RUNG2-001) could never fire.
# Folding these checks into THIS run makes the gate single-sourced: one CDE, one
# ledger row, one verdict.
#
# CHECK SET IS PDK-DERIVED, NOT ASPIRATIONAL.  Each check below is emitted only
# when the bound Liberty actually characterizes it; an uncharacterized check is
# reported as `not_characterized` and NEVER as a clean `0`, because "we did not
# look" and "we looked and it was clean" must not be the same value in the CDE.
# --------------------------------------------------------------------------

# marker -> the Liberty construct that makes the corresponding check meaningful.
_LIB_CAPABILITY_MARKERS = {
    "max_transition": b"max_transition",
    "max_capacitance": b"max_capacitance",
    "max_fanout": b"max_fanout",
    "min_pulse_width": b"min_pulse_width",
    "min_period": b"minimum_period",
    "max_skew": b"max_skew",
    "recovery": b"recovery_",
    "removal": b"removal_",
    "clock_gating": b"clock_gating_integrated_cell",
    # CCS noise / propagated-noise models.  sky130 ships NEITHER, so signal-integrity
    # (crosstalk/noise) analysis is genuinely unavailable on that node -- it must be
    # reported as unsupported, never silently skipped or claimed clean.
    "noise": b"ccsn_first_stage",
}

# check name -> (report_check_types flag, capability marker it depends on)
_DRV_CHECKS = (
    ("max_slew", "-max_slew", "max_transition"),
    ("max_capacitance", "-max_capacitance", "max_capacitance"),
    # max_fanout is routinely NOT a Liberty attribute (sky130 has zero) and comes
    # from the SDC instead (`set_max_fanout`).  So it is capability-gated on the
    # SDC, not the Liberty -- handled specially in _drv_capabilities().
    ("max_fanout", "-max_fanout", None),
    ("min_pulse_width", "-min_pulse_width", "min_pulse_width"),
    ("min_period", "-min_period", "min_period"),
    ("max_skew", "-max_skew", "max_skew"),
    ("recovery", "-recovery", "recovery"),
    ("removal", "-removal", "removal"),
    ("clock_gating_setup", "-clock_gating_setup", "clock_gating"),
    ("clock_gating_hold", "-clock_gating_hold", "clock_gating"),
)


def _scan_liberty_capabilities(paths):
    """Chunked binary scan of the bound Liberty for check-enabling constructs.

    Binary + chunked so a 12 MB (x N corner) Liberty costs well under a second and
    never materialises in memory.  Overlap the chunk boundary by the longest marker
    so a construct split across a read boundary is still found.
    """
    found = set()
    longest = max(len(m) for m in _LIB_CAPABILITY_MARKERS.values())
    for path in paths:
        try:
            with open(path, "rb") as fh:
                tail = b""
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    buf = tail + chunk
                    for name, marker in _LIB_CAPABILITY_MARKERS.items():
                        if name not in found and marker in buf:
                            found.add(name)
                    if len(found) == len(_LIB_CAPABILITY_MARKERS):
                        return found
                    tail = buf[-(longest - 1):] if longest > 1 else b""
        except OSError:
            # An unreadable Liberty is not "no capabilities" -- it is unknown.  Report
            # nothing rather than fabricating a clean capability set.
            continue
    return found


def _read_sdc_closure(sdc_path, _depth=0, _seen=None):
    """SDC text INCLUDING everything it `source`s (transitively).

    An SDC is routinely split: a mode overlay `source`s a mode-agnostic base and
    adds only its own exceptions. The design limits (`set_max_fanout`, ...) live
    in the base. Reading only the top-level file therefore MISSES them and the
    corresponding check is skipped -- while OpenSTA, which does follow `source`,
    would have found real violations. Observed on the DX-85 inputs: the mission
    overlay contains no `set_max_*` at all; every limit comes from the base it
    sources, so a top-level-only scan silently dropped the max_fanout check that
    reports 4 violators.

    Container paths (`/input/...`) are remapped to the sibling directory of the
    referring file, so the closure resolves both inside the container and on the
    host.
    """
    if _seen is None:
        _seen = set()
    real = os.path.realpath(sdc_path)
    if _depth > 8 or real in _seen:        # cycle / runaway guard
        return ""
    _seen.add(real)
    try:
        with open(sdc_path, "r", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    here = os.path.dirname(os.path.abspath(sdc_path))
    for m in re.finditer(r"^\s*source\s+(?:-\S+\s+)*([^\s;]+)", text, re.M):
        ref = m.group(1).strip('"\'{}')
        for cand in (ref, os.path.join(here, os.path.basename(ref)),
                     os.path.join(here, ref)):
            if os.path.exists(cand):
                text += "\n" + _read_sdc_closure(cand, _depth + 1, _seen)
                break
    return text


def _parse_constraint_coverage(out):
    """Parse OpenSTA `check_setup` into a constraint-coverage report.

    WNS and TNS are computed over the CONSTRAINED path population. If the SDC
    constrains a fraction of the design, STA reports an excellent slack for that
    fraction and says nothing at all about the rest -- the number is not wrong,
    it simply does not cover what a reader assumes it covers. Measured on a real
    campaign netlist: 82 unconstrained endpoints, 14 input ports with no
    set_input_delay and 49 outputs with no set_output_delay, while WNS looked
    healthy.

    OpenSTA 3.1.0 prints, verbatim:

        Warning: There are 14 input ports missing set_input_delay.
        Warning: There are 49 output ports missing set_output_delay.
        Warning: There are 82 unconstrained endpoints.
          crc[0]
          crc[10]

    Returns None when no check_setup section is present, so an old log reads as
    NOT MEASURED rather than as fully constrained."""
    seg = out
    m = re.search(r"__CHECK_SETUP__(.*)$", out, re.S)
    if m:
        seg = m.group(1)
    elif "check_setup" not in out.lower() and "unconstrained endpoints" not in out.lower():
        return None

    def _count(pat):
        mm = re.search(pat, seg, re.I)
        return int(mm.group(1)) if mm else None

    unconstrained = _count(r"There are (\d+) unconstrained endpoints")
    no_in = _count(r"There are (\d+) input ports? missing set_input_delay")
    no_out = _count(r"There are (\d+) output ports? missing set_output_delay")
    # UNCLOCKED REGISTERS -- the most consequential category, and the one this
    # parser used to miss entirely.
    #
    # The pattern here was `pins? missing (?:a )?clock`, which matches nothing
    # OpenSTA 3.1.0 actually prints. Captured verbatim from the engine in our
    # image:
    #     Warning: There are 32 unclocked register/latch pins.
    # so `pins_missing_clock` came back None, was skipped by the `total_gaps`
    # sum (which only adds ints), and never appeared in the constraint note --
    # i.e. a design with 32 registers missing a clock reported the same
    # coverage as one with none.
    #
    # That matters because an unclocked register is not merely unconstrained,
    # it is NOT ANALYZED. Measured on crc16_ccitt routed.def by disabling the
    # clock root: 32 unclocked pins, unconstrained endpoints 2 -> 129, and
    # setup slack stayed 14.39 ns while HOLD slack IMPROVED from 0.40 to
    # 1.01 ns. Dropping a third of the design from analysis made the timing
    # report look better.
    #
    # Both wordings are accepted, newest first. Deliberately NOT written as
    # `a or b`: a legitimate 0 is falsy and would fall through to the second
    # pattern and then to None, turning "measured, none found" into "not
    # measured".
    no_clk = _count(r"There are (\d+) unclocked (?:register/latch )?pins?")
    if no_clk is None:
        no_clk = _count(r"There are (\d+) (?:register/latch )?pins? missing (?:a )?clock")
    mult_clk = _count(r"There are (\d+) (?:register/latch )?pins? with multiple clocks")
    loops = _count(r"There are (\d+) combinational loops?")
    gen_clk = _count(r"There are (\d+) generated clocks?")
    if all(v is None for v in (unconstrained, no_in, no_out, no_clk,
                               mult_clk, loops, gen_clk)):
        # check_setup ran and reported nothing: genuinely clean.
        if "__CHECK_SETUP__" not in out:
            return None
        return {"measured": True, "unconstrained_endpoints": 0,
                "inputs_missing_input_delay": 0, "outputs_missing_output_delay": 0,
                "pins_missing_clock": 0, "pins_multiple_clocks": 0,
                "combinational_loops": 0, "endpoint_names": [],
                "fully_constrained": True,
                "note": "check_setup reported no constraint gaps"}
    # ABSENT IS ZERO, NOT UNKNOWN -- but only when check_setup demonstrably ran.
    #
    # OpenSTA prints a category only when its count is non-zero, so once the
    # marker is present an absent category means "measured, none found". The
    # all-clean branch above already returned 0 for every category; this branch
    # used to leave the absent ones as None, so a run reporting 2 unconstrained
    # endpoints and no unclocked pins rendered as "None register/latch pin(s)
    # with NO CLOCK" -- indistinguishable from the not-measured state the
    # verdict deliberately downgrades on. The two branches now agree.
    #
    # Without the marker the wording was matched loosely out of an arbitrary
    # log, so absence proves nothing and None (unknown) is kept.
    if "__CHECK_SETUP__" in out:
        unconstrained = 0 if unconstrained is None else unconstrained
        no_in = 0 if no_in is None else no_in
        no_out = 0 if no_out is None else no_out
        no_clk = 0 if no_clk is None else no_clk
        mult_clk = 0 if mult_clk is None else mult_clk
        loops = 0 if loops is None else loops
    names = re.findall(r"^\s{2,}(\S+)\s*$", seg, re.M)
    total = sum(v for v in (unconstrained, no_in, no_out, no_clk, loops)
                if isinstance(v, int))
    return {
        "measured": True,
        "unconstrained_endpoints": unconstrained,
        "inputs_missing_input_delay": no_in,
        "outputs_missing_output_delay": no_out,
        "pins_missing_clock": no_clk,
        "pins_multiple_clocks": mult_clk,
        "combinational_loops": loops,
        "generated_clocks": gen_clk,
        "endpoint_names": names[:200],
        "endpoint_names_truncated": len(names) > 200,
        "total_gaps": total,
        "fully_constrained": total == 0,
        "note": ("WNS/TNS are computed over the CONSTRAINED population only; "
                 "these endpoints and ports were NOT analysed by the slack "
                 "numbers in this envelope"),
    }


def _parse_signoff_population(out, expected_timing_endpoints=None,
                              expected_input_startpoints=None,
                              expected_constrained_objects=None,
                              expected_unconstrained=None):
    """Parse explicit endpoint/startpoint and propagated-clock instrumentation.

    Missing markers are unexecuted evidence, not zero-valued measurements.

    Timing endpoints and constrained input startpoints are intentionally separate
    populations. OpenSTA timing endpoints are register data pins plus output
    ports; input ports launch paths and are covered independently by check_setup's
    missing-input-delay check. The broader constrained-object population is their
    sum and must agree with both declarations.
    """
    clock = re.search(
        r"__CLOCK_PROPAGATION__\s+clocks=(\d+)\s+status=executed", out)
    endpoints = re.search(
        r"__ENDPOINT_COVERAGE__\s+sequential=(\d+)\s+outputs=(\d+)"
        r"\s+timing_total=(\d+)\s+input_startpoints=(\d+)"
        r"\s+constrained_total=(\d+)", out)
    coverage = _parse_constraint_coverage(out)
    if not clock or not endpoints or coverage is None:
        return None
    sequential, outputs, timing_total, input_startpoints, constrained_total = (
        int(endpoints.group(i)) for i in range(1, 6))
    unconstrained = coverage.get("unconstrained_endpoints")
    if not isinstance(unconstrained, int):
        return None
    return {
        "measured": True,
        "propagated_clock_command_executed": True,
        "clock_count": int(clock.group(1)),
        "sequential_endpoints": sequential,
        "output_endpoints": outputs,
        "timing_endpoint_count": timing_total,
        "expected_timing_endpoint_count": expected_timing_endpoints,
        "input_startpoint_count": input_startpoints,
        "expected_input_startpoint_count": expected_input_startpoints,
        "constrained_object_count": constrained_total,
        "expected_constrained_object_count": expected_constrained_objects,
        "unconstrained_endpoint_count": unconstrained,
        "expected_unconstrained_endpoint_count": expected_unconstrained,
        "timing_endpoint_count_matches": (
            expected_timing_endpoints is not None
            and timing_total == expected_timing_endpoints),
        "input_startpoint_count_matches": (
            expected_input_startpoints is not None
            and input_startpoints == expected_input_startpoints),
        "constrained_object_count_matches": (
            expected_constrained_objects is not None
            and constrained_total == expected_constrained_objects),
        "population_identity_matches": (
            timing_total + input_startpoints == constrained_total),
        "unconstrained_count_matches": (
            expected_unconstrained is not None
            and unconstrained == expected_unconstrained),
    }


def _signoff_population_blocker(population):
    if population is None:
        return ("signoff population/propagated-clock instrumentation did not "
                "execute or produced an empty/unparseable block")
    if population["clock_count"] <= 0:
        return "set_propagated_clock executed with an empty clock population"
    if (not population["timing_endpoint_count_matches"]
            or not population["input_startpoint_count_matches"]
            or not population["constrained_object_count_matches"]
            or not population["population_identity_matches"]
            or not population["unconstrained_count_matches"]):
        return (
            "SIGNOFF POPULATION MISMATCH: measured %s/%s timing endpoints, "
            "%s/%s input startpoints, %s/%s constrained objects, and %s/%s "
            "unconstrained endpoints; propagated clocks=%s"
            % (population["timing_endpoint_count"],
               population["expected_timing_endpoint_count"],
               population["input_startpoint_count"],
               population["expected_input_startpoint_count"],
               population["constrained_object_count"],
               population["expected_constrained_object_count"],
               population["unconstrained_endpoint_count"],
               population["expected_unconstrained_endpoint_count"],
               population["clock_count"]))
    return None


def _parse_disabled_edges(out):
    """Parse `report_disabled_edges` into benign vs. material categories.

    A disabled timing arc removes paths through it from analysis, so slack is
    computed over a SMALLER population without the number itself looking any
    different -- the same failure shape as an unannotated SPEF.

    The count alone is not a usable gate. Measured on crc16_ccitt routed.def
    with its own SDC, a perfectly healthy design already reports 113 disabled
    edges, EVERY ONE of them constant propagation through the tie cell:

        TIEOFF_zero_/LO _331_/B constant LO=0 B=0

    Those are how a tie-off is supposed to behave, so a "must be zero" gate
    would fail every real design. What is material is an arc disabled for any
    OTHER reason -- `set_disable_timing`, a broken cell arc, a timing loop --
    which prints without the `constant` marker:

        _458_ CLK Q constraint

    Adding `set_disable_timing [get_cells _458_]` moved the totals 113 -> 114
    with exactly one non-constant entry, so the two categories separate
    cleanly. Returns None when the section is absent, so an old log reads as
    NOT MEASURED rather than as zero.
    """
    m = re.search(r"__DISABLED_EDGES__(.*?)(?:__[A-Z_]+__|\Z)", out, re.S)
    if not m:
        return None
    lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
    # Defensive: ignore any engine chatter that is not an edge record.
    lines = [l for l in lines if not re.match(r"(Warning|Error|\[)", l)]
    const = [l for l in lines if re.search(r"\bconstant\b", l)]
    arcs = [l for l in lines if not re.search(r"\bconstant\b", l)]
    return {
        "measured": True,
        "total": len(lines),
        "constant_propagation": len(const),
        "disabled_arcs": len(arcs),
        "disabled_arc_names": arcs[:100],
        "disabled_arc_names_truncated": len(arcs) > 100,
        "note": ("constant-propagation edges are normal tie-off behaviour; "
                 "any OTHER disabled arc removes real paths from the slack "
                 "population reported here"),
    }


def _drv_capabilities(corners_spec, sdc_path):
    """Resolve which checks are RUNNABLE against this PDK + these constraints."""
    libs = [c.get("liberty") for c in corners_spec if c.get("liberty")]
    lib_caps = _scan_liberty_capabilities(libs)
    sdc_text = _read_sdc_closure(sdc_path)

    caps = {}
    for name, _flag, marker in _DRV_CHECKS:
        if name == "max_fanout":
            # Liberty attribute OR an SDC-declared design limit makes it checkable.
            ok = ("max_fanout" in lib_caps) or ("set_max_fanout" in sdc_text)
            basis = ("liberty" if "max_fanout" in lib_caps
                     else ("sdc:set_max_fanout" if ok else None))
        else:
            ok = marker in lib_caps
            basis = "liberty:" + str(marker) if ok else None
        caps[name] = {"checkable": bool(ok), "basis": basis}
    # Noise/crosstalk is reported explicitly so its ABSENCE is visible evidence
    # rather than a silent omission a reviewer has to notice.
    caps["noise"] = {
        "checkable": "noise" in lib_caps,
        "basis": "liberty:ccsn_first_stage" if "noise" in lib_caps else None,
        "note": ("CCS noise / propagated_noise models are absent from the bound "
                 "Liberty, so signal-integrity (crosstalk) analysis is NOT "
                 "available on this node and is neither run nor claimed clean."),
    }
    return caps


def _parse_drv_violators(segment):
    """Count violators and return the worst SLACK in a `report_check_types` block.

    RETURNS (count, worst_slack, assessed). `assessed=False` means the block could
    not be interpreted at all, which is NOT the same as clean and must never be
    recorded as 0 -- see the `min_pulse_width` case below.

    `report_check_types` EMITS TWO DIFFERENT SHAPES and the caller cannot tell
    which it will get, so both must be handled here.

    (A) PIN-BASED -- max_slew / max_capacitance / max_fanout:
            Pin                          Limit    Slew   Slack
            ---------------------------------------------------
            scan_en                       0.75    3.12   -2.37 (VIOLATED)
        Every row carries an explicit `(VIOLATED)` marker.

    (B) GROUP-BASED -- recovery / removal / clock_gating_setup / clock_gating_hold:
            Group                          Slack
            ------------------------------------
            asynchronous                   -0.18
        There is NO `(VIOLATED)` marker at all; a clean run prints the header and
        then `No paths found.`

    INCIDENT THIS FIXES (DX-484, myTop3_core sta_postdft.1, 2026-09-01). This
    function previously counted ONLY rows containing `(VIOLATED)`, so every
    shape-(B) check silently scored 0 violators / status "clean". The run's own
    `timing_summary.json` therefore reported
        drv.removal_cell_check = {violators: 0, status: "clean"}
        drv.recovery           = {violators: 0, status: "clean"}
    while the raw log for the very same run printed
        __DRV__ss_100C_1v60__removal__ -> asynchronous  -0.18   (twice)
    i.e. a REAL removal violation on the reset synchroniser was reported as clean.
    Five of the ten checks -- recovery, removal, clock_gating_setup,
    clock_gating_hold, min_pulse_width -- were invisible to the old parser, so the
    DRV rollup could only ever UNDER-report. A false clean on a timing check is
    the worst failure mode this tool has.

    Traps deliberately avoided in shape (A):
      * the pin name itself contains digits (`_198_/Y` yields a bogus `198`), so
        the first whitespace-delimited field is dropped before scanning;
      * picking the second-to-last token returns the measured VALUE (slew/cap),
        not the slack -- which reads as a plausible number and is therefore the
        kind of error that survives review (observed: 4.09 reported where the
        true worst slack was -14.83).
    """
    if segment is None or not segment.strip():
        # An EMPTY block is "the check produced no output", not "the check passed".
        # Observed live: min_pulse_width emitted nothing at all. Reporting 0 here
        # would manufacture a clean result out of silence.
        return 0, None, False
    num = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")

    # --- shape (A): explicit per-pin (VIOLATED) rows --------------------------
    rows = [ln for ln in segment.splitlines() if "(VIOLATED)" in ln]
    if rows:
        worst = None
        for ln in rows:
            parts = ln.split(None, 1)
            if len(parts) < 2:
                continue
            nums = num.findall(parts[1])      # drop the pin/instance name
            if not nums:
                continue
            try:
                slack = float(nums[-1])       # slack is the last column
            except ValueError:
                continue
            worst = slack if worst is None else min(worst, slack)
        return len(rows), worst, True

    # --- shape (B): `Group / Slack` table, no marker --------------------------
    if re.search(r"^\s*Group\s+Slack\s*$", segment, re.M):
        if re.search(r"^\s*No paths found\.?\s*$", segment, re.M):
            return 0, None, True             # genuinely clean, and it did run
        worst, count = None, 0
        for ln in segment.splitlines():
            s = ln.strip()
            if (not s or s.startswith("-") or s.startswith("__")
                    or re.match(r"^Group\s+Slack$", s)
                    or s.startswith("No paths found")):
                continue
            parts = s.rsplit(None, 1)         # "<group name>   <slack>"
            if len(parts) != 2:
                continue
            try:
                slack = float(parts[1])
            except ValueError:
                continue
            # The command was invoked with `-violators`, so every listed path is a
            # violation; the slack sign is corroboration, not the selector.
            count += 1
            worst = slack if worst is None else min(worst, slack)
        return count, worst, True

    # A block in neither shape (e.g. an unrecognised header or a tool message) is
    # NOT assessable. Fail loud in the CDE rather than quietly scoring it clean.
    if re.search(r"^\s*No paths found\.?\s*$", segment, re.M):
        return 0, None, True
    return 0, None, False


def _parse_drv_affirmative_evidence(measurement_segment, violator_segment):
    """Parse paired OpenSTA evidence for mandatory post-route checks.

    OpenSTA 3.1.0 emits an empty block for a clean
    ``report_check_types -violators`` invocation. Silence alone cannot prove the
    command ran or the check was supported. The producer therefore also requests
    one unrestricted numeric row. A clean zero is accepted only when that row is
    well formed and marked ``(MET)`` and the paired violator command executed.
    """
    if measurement_segment is None or not measurement_segment.strip():
        return 0, None, False
    if violator_segment is None:
        return 0, None, False

    numeric_rows = [
        line for line in measurement_segment.splitlines()
        if re.search(r"\((?:MET|VIOLATED)\)\s*$", line)
    ]
    if len(numeric_rows) != 1:
        return 0, None, False

    parts = numeric_rows[0].split(None, 1)
    if len(parts) < 2:
        return 0, None, False
    nums = re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", parts[1])
    if not nums:
        return 0, None, False
    try:
        measured_slack = float(nums[-1])
    except ValueError:
        return 0, None, False

    violated_measurement = "(VIOLATED)" in numeric_rows[0]
    count, worst_slack, assessed = _parse_drv_violators(violator_segment)
    if not assessed:
        # Empty is the documented clean shape for -violators, but only the
        # affirmative numeric row can authorize interpreting it as zero.
        if violator_segment.strip():
            return 0, None, False
        count, worst_slack, assessed = 0, None, True
    if violated_measurement and count == 0:
        return 0, None, False
    if not violated_measurement and count != 0:
        return 0, None, False
    return (
        count,
        worst_slack if worst_slack is not None else measured_slack,
        assessed,
    )


def _drv_verdict_note(setup_ok, hold_ok, drv_clean, drv_total, drv,
                      pre_layout=False, deferred=None):
    """Name every OPEN family explicitly; a verdict a human cannot act on is a
    verdict that gets ignored."""
    if setup_ok and hold_ok and drv_clean:
        checked = [n for n, d in drv.items() if d.get("checkable")]
        skipped = [n for n, d in drv.items() if not d.get("checkable")]
        note = ("all corners meet setup, hold, and every characterized DRV check "
                "(%s)" % ", ".join(sorted(checked)))
        if skipped:
            note += ("; NOT characterized by the bound Liberty and therefore not "
                     "checked: %s" % ", ".join(sorted(skipped)))
        return note
    open_families = []
    if not setup_ok:
        open_families.append("setup")
    if not hold_ok:
        open_families.append("hold")
    for name, d in drv.items():
        if d.get("status") == "violated":
            open_families.append("%s(%d)" % (name, d.get("violators") or 0))
    if pre_layout and setup_ok:
        deferred = deferred or []
        return (
            "pre-layout setup gate CLOSED; DEFERRED, NOT WAIVED to post-CTS/"
            "post-route STA: %s. Measured observations: %d DRV violation(s); "
            "open families: %s"
            % (", ".join(deferred) or "none", drv_total,
               ", ".join(open_families) or "none"))
    return ("gate OPEN -- %d DRV violation(s); open families: %s"
            % (drv_total, ", ".join(open_families)))


def _timing_metric_class(pre_layout, check):
    """Return the metric class at this STA flow position.

    Setup is actionable and gating everywhere. Before placement/CTS, hold and
    DRV are measured diagnostics with a downstream obligation; after that they
    become gating. Keeping the raw metric-class metadata aligned with the
    normalized progress contract prevents a future class-aware consumer from
    reintroducing the DX-57/DX-58 failure through a second code path.
    """
    if pre_layout and check in ("hold", "drv"):
        return "diagnostic"
    return "gating"


#: Flow positions at which a clock tree exists, so ideal clocks would be wrong.
_POST_CTS_STAGES = ("post_cts", "postcts", "cts", "post_route", "postroute",
                    "route", "routed", "signoff", "post_route_signoff")


def _clock_mode(params, has_spef, default_propagated=False):
    """Resolve ideal vs propagated clocks. Returns (propagated: bool, source).

    Explicit `propagated_clock` true/false always wins. Otherwise propagated is
    the default when SPEF is supplied (parasitics only exist after routing, so a
    clock tree exists) or when `stage` names a post-CTS position. A pre-CTS SDC
    carries no set_propagated_clock, so without this a post-route run reports
    "clock network delay (ideal)" -- zero clock latency/skew on a routed tree.
    """
    raw = params.get("propagated_clock")
    if raw is not None and str(raw).strip().lower() not in ("", "auto"):
        return str(raw).strip().lower() in ("1", "true", "yes", "on"), "caller"
    stage = str(params.get("stage") or params.get("sta_stage") or "").strip().lower()
    stage = stage.replace("-", "_").replace(" ", "_")
    if has_spef:
        return True, "default(spef supplied => post-route)"
    if stage in _POST_CTS_STAGES:
        return True, f"default(stage={stage})"
    if default_propagated:
        return True, "default(multi-corner path always propagates)"
    return False, "default(pre-CTS: no spef and stage is not post_cts/post_route)"


def _clock_mode_tcl(propagated):
    if propagated:
        return ("set _clk_all [all_clocks]\n"
                "if {[llength $_clk_all]} { set_propagated_clock $_clk_all }\n"
                "puts \"__CLOCK_MODE__ propagated clocks=[llength $_clk_all]\"\n")
    return "puts \"__CLOCK_MODE__ ideal clocks=[llength [all_clocks]]\"\n"


def _parse_clock_mode(out, propagated, source):
    """What the reports actually used, cross-checked against what was asked."""
    marker = re.search(r"__CLOCK_MODE__ (ideal|propagated) clocks=(\d+)", out)
    ideal_lines = len(re.findall(r"clock network delay \(ideal\)", out))
    prop_lines = len(re.findall(r"clock network delay \(propagated\)", out))
    requested = "propagated" if propagated else "ideal"
    mismatch = marker is None or (propagated and ideal_lines > 0 and prop_lines == 0)
    if marker is None:
        note = "clock mode NOT measured (no __CLOCK_MODE__ marker in sta.log)"
    elif mismatch:
        note = ("propagated clocks were requested but every reported path still "
                "shows 'clock network delay (ideal)'")
    elif propagated:
        note = "clocks propagated (set_propagated_clock [all_clocks]) -- %s" % source
    else:
        note = ("IDEAL clocks: zero clock-network latency/skew; correct only before "
                "CTS -- %s" % source)
    return {"clock_mode": requested if marker else "not_measured",
            "requested": requested, "source": source,
            "clock_count": int(marker.group(2)) if marker else None,
            "report_lines_ideal": ideal_lines,
            "report_lines_propagated": prop_lines,
            "mismatch": mismatch, "note": note}


def _mcmm_timing_report(params, binname, top, netlist, sdc, analysis,
                        max_paths, rc_extra, corners_spec):
    """Multi-corner (MCMM) OpenSTA run: one Liberty (+ optional SPEF) per named
    corner, per-corner WNS/TNS/path reports in a single invocation."""
    # Validate corner spec + input files up front (fail-closed).
    names = []
    for c in corners_spec:
        nm = c.get("name")
        lib = c.get("liberty")
        if not nm or not lib:
            return _cde(objective="STA", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error="each corner needs 'name' and 'liberty'",
                        validation={"verdict": "fail"})
        if not os.path.exists(str(lib)):
            return _cde(objective="STA", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"corner '{nm}' Liberty not found: {lib}",
                        validation={"verdict": "fail"})
        sp = c.get("spef")
        if sp and not os.path.exists(str(sp)):
            return _cde(objective="STA", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"corner '{nm}' SPEF not found: {sp}",
                        validation={"verdict": "fail"})
        names.append(nm)
    if not os.path.exists(str(netlist)) or not os.path.exists(str(sdc)):
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="netlist or SDC not found", validation={"verdict": "fail"})

    define = "define_corners " + " ".join(names)
    lib_reads = "\n".join(
        f"read_liberty -corner {c['name']} {c['liberty']}" for c in corners_spec)
    is_def = str(netlist).endswith(".def")
    # Resolve optional LEFs (tech + cell). A DEF REQUIRES them; a Verilog netlist
    # does NOT under standalone OpenSTA, but the openroad-embedded STA still needs a
    # technology (read_lef) before read_verilog or it aborts with ORD-2010. So read
    # LEFs whenever they are available, for BOTH readers.
    lefs = _resolve_lefs(params)
    lef_reads = ""
    if is_def and not lefs:
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="DEF-based STA requires a LEF",
                    validation={"verdict": "fail"})
    if lefs:
        lef_reads = "\n".join(f"read_lef {l}" for l in lefs) + "\n"
    reader = (f"{lef_reads}read_def {netlist}" if is_def
              else f"{lef_reads}read_verilog {netlist}\nlink_design {top}")
    spef_reads = "\n".join(
        f"read_spef -corner {c['name']} {c['spef']}"
        for c in corners_spec if c.get("spef"))
    post_route = all(c.get("spef") for c in corners_spec)
    expected_timing_endpoints = params.get("expected_timing_endpoint_count")
    expected_input_startpoints = params.get("expected_input_startpoint_count")
    expected_constrained_objects = params.get("expected_constrained_object_count")
    expected_unconstrained = params.get("expected_unconstrained_endpoints")
    # SIGNOFF vs NON-SIGNOFF. A post-route signoff claim needs the caller's
    # declared endpoint/startpoint population to compare against. When those
    # declarations are omitted the run is NOT stopped any more (an agent would
    # otherwise have to ask for numbers it cannot know before running STA): it
    # runs as NON-SIGNOFF post-route STA, measures everything, and caps the
    # verdict at `review`. It can never close a signoff gate this way.
    signoff_declared = all(isinstance(v, int) and not isinstance(v, bool) for v in (
        expected_timing_endpoints, expected_input_startpoints,
        expected_constrained_objects, expected_unconstrained))
    non_signoff = post_route and not signoff_declared
    if (post_route and signoff_declared
            and expected_timing_endpoints + expected_input_startpoints
            != expected_constrained_objects):
        return _cde(
            objective="STA", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            error=("declared constrained-object population must equal timing "
                   "endpoints plus input startpoints"),
            validation={"verdict": "fail"})

    sta_rpt = os.path.join(_OUTPUT_DIR, "sta.rpt")
    per_corner = ""
    file_reports = f"report_checks -path_delay max -group_path_count {max_paths} > {sta_rpt}\n"
    for nm in names:
        # Per-corner slack is derived from report_checks -corner (OpenSTA's
        # report_wns/report_tns/report_worst_slack do not accept -corner); the
        # worst path's "slack (MET|VIOLATED) <val>" line gives the corner slack.
        if analysis in ("setup", "both"):
            per_corner += (f'puts "__SETUP__{nm}__"\n'
                           f"report_checks -corner {nm} -path_delay max "
                           f"-group_path_count {max_paths}{rc_extra}\n")
        if analysis in ("hold", "both"):
            per_corner += (f'puts "__HOLD__{nm}__"\n'
                           f"report_checks -corner {nm} -path_delay min "
                           f"-group_path_count {max_paths}{rc_extra}\n")
        # `puts "..." >> file` is INVALID Tcl -- OpenSTA implements `>`/`>>`
        # redirection for its OWN report commands, not for the Tcl builtin, so
        # this raised `wrong # args: should be "puts ?-nonewline? ?channelId?
        # string"` and ABORTED the script at the first marker. The per-corner
        # sections of sta.rpt were therefore never written (recorded in this
        # campaign's CDE as the truncated-sta.rpt defect). Write the marker
        # through a real append channel instead, then let OpenSTA append its own
        # report to the same file.
        file_reports += (f"set _fh [open {sta_rpt} a]\n"
                         f"puts $_fh \"__CORNER__{nm}__\"\n"
                         f"close $_fh\n"
                         f"report_checks -corner {nm} -path_delay max "
                         f"-group_path_count {max_paths} >> {sta_rpt}\n")
    # Overall worst-of-corners WNS/TNS (global forms, no -corner).
    propagated, clock_src = _clock_mode(params, post_route, default_propagated=True)
    if propagated:
        clock_setup = (
            'set _signoff_clocks [all_clocks]\n'
            'set_propagated_clock $_signoff_clocks\n'
            'puts "__CLOCK_PROPAGATION__ clocks=[llength $_signoff_clocks] '
            'status=executed"\n'
            'puts "__CLOCK_MODE__ propagated clocks=[llength $_signoff_clocks]"\n')
    else:
        # Explicit propagated_clock=false: no __CLOCK_PROPAGATION__ marker, so
        # a post-route signoff population check cannot pass on ideal clocks.
        clock_setup = _clock_mode_tcl(False)
    signoff_setup = (
        clock_setup +
        'set _sequential_endpoints [llength [all_registers -data_pins]]\n'
        'set _output_endpoints [llength [all_outputs]]\n'
        'set _timing_endpoint_total [expr {$_sequential_endpoints + '
        '$_output_endpoints}]\n'
        'set _input_startpoints [llength [all_inputs]]\n'
        'set _constrained_object_total [expr {$_timing_endpoint_total + '
        '$_input_startpoints}]\n'
        'puts "__ENDPOINT_COVERAGE__ sequential=$_sequential_endpoints '
        'outputs=$_output_endpoints timing_total=$_timing_endpoint_total '
        'input_startpoints=$_input_startpoints '
        'constrained_total=$_constrained_object_total"\n')
    per_corner += 'puts "__OVERALL__"\nreport_wns\nreport_tns\n'
    # --- DISABLED TIMING ARCS (see _parse_disabled_edges) ---------------------
    # A disabled arc removes paths through it from the slack population without
    # changing how the slack number looks. Emitted BEFORE __CHECK_SETUP__ on
    # purpose: _parse_constraint_coverage takes everything AFTER its marker to
    # end-of-output, so anything appended after it lands inside that segment.
    per_corner += 'puts "__DISABLED_EDGES__"\nreport_disabled_edges\n'
    # --- CONSTRAINT COVERAGE (see _parse_constraint_coverage) -----------------
    # WNS/TNS are computed over the CONSTRAINED path population only. A design
    # whose SDC constrains one flop reports a beautiful WNS while the other
    # thousands of endpoints are simply not analysed, and nothing in a slack
    # number reveals that. check_setup enumerates them.
    per_corner += ('puts "__CHECK_SETUP__"\n'
                   'check_setup -unconstrained_endpoints -no_input_delay '
                   '-no_output_delay -no_clock -multiple_clock -loops '
                   '-generated_clocks -verbose\n')

    # --- DRV / non-path checks, IN THIS RUN (see _DRV_CHECKS rationale) --------
    # Emitted per corner: a transition/cap limit is corner-dependent (slow corner
    # degrades slew), so a single-corner DRV sweep would under-report.
    drv_caps = _drv_capabilities(corners_spec, sdc)
    mandatory_signoff_checks = {
        "max_slew", "max_capacitance", "max_fanout", "min_pulse_width"}
    signoff_blockers = []
    if post_route:
        missing_caps = sorted(
            name for name in mandatory_signoff_checks
            if not drv_caps.get(name, {}).get("checkable"))
        if missing_caps and non_signoff:
            # Non-signoff run: the uncharacterized checks are already reported
            # as not_characterized (never a clean 0); record why this run could
            # not be signoff instead of stopping it.
            signoff_blockers.append(
                "mandatory check(s) not assessable from the bound Liberty/SDC: "
                + ", ".join(missing_caps))
        elif missing_caps:
            return _cde(
                objective="STA", status="failed",
                pdk_binding=params.get("pdk_binding", "none"),
                error=("post-route signoff cannot assess mandatory check(s): "
                       + ", ".join(missing_caps)
                       + "; bind characterized Liberty/SDC limits rather than "
                         "fabricating zero violations"),
                validation={"verdict": "fail"})
    drv_script = ""
    for nm in names:
        for cname, flag, _marker in _DRV_CHECKS:
            if not drv_caps.get(cname, {}).get("checkable"):
                continue
            if cname in mandatory_signoff_checks:
                drv_script += (
                    f'puts "__DRV_MEASURE__{nm}__{cname}__"\n'
                    f"report_check_types {flag} -corner {nm} -max_count 1\n"
                    f'puts "__DRV_VIOLATORS__{nm}__{cname}__"\n'
                    f"report_check_types {flag} -violators -corner {nm} "
                    "-max_count 1000000\n")
            else:
                drv_script += (
                    f'puts "__DRV__{nm}__{cname}__"\n'
                    f"report_check_types {flag} -violators -corner {nm}\n")
    drv_script += 'puts "__DRV_END__"\n'

    # --- SDF emission (per corner) --------------------------------------------
    # SDF is the ONLY artifact that carries per-instance/per-arc delays out of STA
    # and into a gate-level simulator. Without it, GLS is zero-delay: it can prove
    # X-propagation and reset hygiene, but it CANNOT see a glitch, a race, or an
    # at-speed failure -- exactly the class of bug that survives LEC (which is
    # logical, 2-state, and delay-blind) and survives STA (which is static and
    # never applies a vector). OpenLane emits SDF from `STAPostPNR` for the same
    # reason.
    #
    # Written per CORNER on purpose: delays are corner-dependent, so a single SDF
    # would silently pin GLS to one PVT. The consumer picks the corner that
    # matches the question being asked (slow for setup/at-speed, fast for
    # hold/race).
    write_sdf = bool(params.get("write_sdf"))
    sdf_files = {}
    sdf_script = ""
    if write_sdf:
        sdf_digits = params.get("sdf_digits")
        sdf_corners = _as_list(params.get("sdf_corners")) or names
        unknown = [c for c in sdf_corners if c not in names]
        if unknown:
            return _cde(objective="STA", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error="sdf_corners names not in the corner set: %s"
                              % ", ".join(unknown),
                        validation={"verdict": "fail"})
        for nm in sdf_corners:
            path = os.path.join(_OUTPUT_DIR, "%s.%s.sdf" % (top, nm))
            opts = " -corner %s" % nm
            if sdf_digits is not None:
                opts += " -digits %s" % sdf_digits
            # -no_timestamp keeps the artifact byte-reproducible, so its sha256 is
            # a function of the DESIGN and not of when the run happened.
            opts += " -no_timestamp"
            sdf_script += "write_sdf%s {%s}\n" % (opts, path)
            sdf_files[nm] = os.path.basename(path)

    script = f"""{define}
{lib_reads}
{reader}
read_sdc {sdc}
{spef_reads}
{signoff_setup}
{per_corner}
{drv_script}
{sdf_script}{file_reports}
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "sta.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command([binname, "-exit", sp])
    proc = subprocess.run([binname, "-exit", sp], capture_output=True, text=True,
                          cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "sta.log"), "w").write(out)

    # Parse per-corner worst setup/hold slack from the delimited path reports.
    # report_checks prints the worst path first; its "slack (MET|VIOLATED) <val>"
    # line is the corner's worst slack.
    def _first_slack(segment):
        m = re.search(r"(-?[0-9.eE+]+)\s+slack\s+\((?:MET|VIOLATED)\)", segment)
        return float(m.group(1)) if m else None

    def _segment(marker):
        parts = out.split(marker, 1)
        if len(parts) < 2:
            return ""
        # cut at the next delimiter
        return re.split(
            r"__(?:SETUP|HOLD|OVERALL|CORNER|DRV|DRV_MEASURE|"
            r"DRV_VIOLATORS|DRV_END)__",
            parts[1],
        )[0]

    per_corner_results = {}
    worst_wns = None
    worst_hold = None
    for nm in names:
        w = _first_slack(_segment(f"__SETUP__{nm}__")) if analysis in ("setup", "both") else None
        h = _first_slack(_segment(f"__HOLD__{nm}__")) if analysis in ("hold", "both") else None
        per_corner_results[nm] = {"setup_slack_ns": w, "hold_slack_ns": h}
        if w is not None:
            worst_wns = w if worst_wns is None else min(worst_wns, w)
        if h is not None:
            worst_hold = h if worst_hold is None else min(worst_hold, h)
    # Overall worst-of-corners WNS/TNS.
    _ov = out.split("__OVERALL__")[-1] if "__OVERALL__" in out else ""
    _mw = re.search(r"wns\s+\w+\s+(-?[0-9.eE+]+)", _ov)
    _mt = re.search(r"tns\s+\w+\s+(-?[0-9.eE+]+)", _ov)
    overall_wns = float(_mw.group(1)) if _mw else worst_wns
    overall_tns = float(_mt.group(1)) if _mt else None

    if proc.returncode != 0 and not per_corner_results:
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="OpenSTA MCMM run failed; see sta.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"sta": _sta_version(binname), "log": "sta.log"})

    setup_ok = worst_wns is None or worst_wns >= 0
    hold_ok = worst_hold is None or worst_hold >= 0

    # --- FAIL CLOSED ON A VACUOUS RUN (MANDATORY) -----------------------------
    # A run that analyzed NOTHING must never report `pass`. The prior code took
    # `worst_wns is None` to mean "no violation" and returned `pass` -- recorded
    # in this campaign's own CDE as the sta.1 metric defect ("FALSELY reported
    # verdict=pass on a vacuous run"). Absence of measurement is not evidence of
    # closure: it is a FAILED run.
    #
    # Two distinct triggers, deliberately NOT collapsed into "any Error string":
    #   * SETUP errors -- the design, library, or CONSTRAINTS failed to load
    #     (e.g. the SDC `source`s a base file that is not mounted). Analysis then
    #     proceeds unconstrained and every check trivially reports 0 violators, so
    #     this is fatal EVEN IF some slack was printed;
    #   * nothing analyzed -- no endpoint produced a slack value at all.
    # A late/reporting error AFTER the measurements are captured (a malformed
    # report redirection, a truncated .rpt) must NOT discard a genuine analysis --
    # treating it as vacuous would throw away real violations and is its own kind
    # of false verdict. Those are recorded in provenance instead.
    all_errors = re.findall(r"^\s*Error:.*$", out, re.M)
    _FATAL = re.compile(
        r"couldn't read file|no such file|cannot open|link_design|ORD-2010|"
        r"failed to read|unable to open|syntax error in", re.I)
    fatal_errors = [e.strip() for e in all_errors if _FATAL.search(e)][:10]
    other_errors = [e.strip() for e in all_errors if not _FATAL.search(e)][:10]
    analyzed_nothing = worst_wns is None and worst_hold is None
    vacuous = bool(fatal_errors) or analyzed_nothing

    # --- DRV results: worst-of-corners per check ------------------------------
    # A violator on ANY corner is a violator, so the per-check count is the max
    # across corners (not a sum -- the same pin violating on 3 corners is ONE
    # design defect, and summing would inflate the residual 3x and corrupt the
    # cross-attempt trend the effort ledger reads).
    drv = {}
    drv_total = 0
    for cname, _flag, _marker in _DRV_CHECKS:
        cap = drv_caps.get(cname, {})
        if not cap.get("checkable"):
            drv[cname] = {"checkable": False, "basis": None,
                          "violators": None, "status": "not_characterized"}
            continue
        if vacuous:
            # Do NOT record 0: the check did not meaningfully run.
            drv[cname] = {"checkable": True, "basis": cap.get("basis"),
                          "violators": None, "status": "not_analyzed"}
            continue
        worst_count, worst_slack, per_corner_counts = 0, None, {}
        per_corner_measurements = {}
        unassessed = []
        for nm in names:
            if cname in mandatory_signoff_checks:
                measure_marker = f"__DRV_MEASURE__{nm}__{cname}__"
                violator_marker = f"__DRV_VIOLATORS__{nm}__{cname}__"
                measure_segment = _segment(measure_marker)
                violator_present = violator_marker in out
                violator_segment = (
                    _segment(violator_marker) if violator_present else None)
                cnt, ws, assessed = _parse_drv_affirmative_evidence(
                    measure_segment, violator_segment)
            else:
                cnt, ws, assessed = _parse_drv_violators(
                    _segment(f"__DRV__{nm}__{cname}__"))
            if not assessed:
                # The block produced no interpretable output on this corner. That
                # is "we did not look", which must not be averaged in with clean
                # corners -- record it and refuse to call the check clean.
                unassessed.append(nm)
                continue
            per_corner_counts[nm] = cnt
            per_corner_measurements[nm] = {
                "violators": cnt,
                "worst_slack": ws,
                "measured": True,
            }
            worst_count = max(worst_count, cnt)
            if ws is not None:
                worst_slack = ws if worst_slack is None else min(worst_slack, ws)
        if unassessed:
            # Every signoff corner must yield a readable result. Partial evidence
            # is not enough to characterize a worst-of-corners verdict.
            drv[cname] = {"checkable": True, "basis": cap.get("basis"),
                          "violators": None, "status": "not_assessable",
                          "per_corner": per_corner_counts,
                          "per_corner_measurements": per_corner_measurements,
                          "unassessed_corners": unassessed,
                          "note": ("paired affirmative measurement and violator "
                                   "evidence was missing, partial, malformed, or "
                                   "inconsistent for at least one required "
                                   "corner; scoring it 0/clean would fabricate "
                                   "evidence")}
            continue
        drv[cname] = {"checkable": True, "basis": cap.get("basis"),
                      "violators": worst_count, "worst_slack": worst_slack,
                      "per_corner": per_corner_counts,
                      "per_corner_measurements": per_corner_measurements,
                      "status": "clean" if worst_count == 0 else "violated"}
        if unassessed:
            drv[cname]["unassessed_corners"] = unassessed
        drv_total += worst_count
    drv["noise"] = dict(drv_caps.get("noise", {}), violators=None,
                        status="unsupported_by_pdk")
    # A check that could not be assessed does NOT contribute to drv_total (it has
    # no count), so it must be excluded from `clean` explicitly -- otherwise an
    # unreadable check block would silently read as a clean one, which is the
    # exact defect `_parse_drv_violators` was fixed for.
    _not_assessable = [n for n, d in drv.items()
                       if d.get("status") == "not_assessable"]
    drv_clean = (not vacuous) and drv_total == 0 and not _not_assessable

    if vacuous:
        return _cde(
            objective=f"multi-corner static timing analysis of {top}",
            status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            results={"timing_mode": "not_analyzed", "drv_clean": None,
                     "drv_violations": None},
            qor={"wns_ns": None, "tns_ns": None, "hold_slack_ns": None,
                 "drv_violations": None, "drv_detail": drv},
            signoff={"setup_met": None, "hold_met": None, "drv_met": None,
                     "corners": names, "analysis": analysis,
                     "drv_checks": drv, "drv_capabilities": drv_caps,
                     "report": "sta.log"},
            inputs_ref={"netlist": netlist, "sdc": sdc, "corners": corners_spec},
            validation={
                "verdict": "fail",
                "note": ("VACUOUS RUN -- fail-closed. %s Nothing usable was "
                         "analyzed, so neither timing nor DRV can be claimed "
                         "clean. Absence of measurement is NOT evidence of "
                         "closure."
                         % ("OpenSTA setup error(s): " + " | ".join(fatal_errors)
                            if fatal_errors
                            else "No endpoint produced a slack value.")),
            },
            provenance={"sta": _sta_version(binname), "runtime_s": round(elapsed, 3),
                        "log": "sta.log", "fatal_errors": fatal_errors,
                        "other_errors": other_errors},
        )

    # Pre-layout vs post-route honesty: a corner is signoff-grade only if it carries
    # SPEF. If NO corner has SPEF the whole run is an ideal-interconnect pre-layout
    # estimate (optimistic, not signoff); if some but not all do, flag it as mixed.
    #
    # Computed BEFORE the verdict because the verdict is now STAGE-AWARE and needs it.
    _spef_corners = [c["name"] for c in corners_spec if c.get("spef")]
    if len(_spef_corners) == len(names) and names:
        timing_mode, interconnect = "post_route_signoff", "SPEF parasitics (all corners)"
    elif _spef_corners:
        timing_mode = "mixed"
        interconnect = ("SPEF on %d/%d corners; corners without SPEF are ideal "
                        "(pre-layout, optimistic)" % (len(_spef_corners), len(names)))
    else:
        timing_mode = "pre_layout_estimate"
        interconnect = "ideal (no SPEF on any corner) -- pre-layout estimate, optimistic, not signoff"

    # The gate is setup AND hold AND DRV.  Reporting `pass` on clean setup/hold
    # while DRV is dirty is precisely the defect this tool had.
    #
    # ...but that rule is only CORRECT where DRV and hold are physically
    # assessable. This tool previously applied ONE verdict rule at EVERY flow
    # position. max_transition/max_capacitance are functions of net RC, and hold
    # depends on real clock skew -- NEITHER exists before placement and CTS. A
    # pre-layout run has no SPEF on any corner, so its DRV numbers describe
    # unbuffered nets that placement `repair_design` and CTS have not yet touched,
    # and its hold numbers describe a clock tree that does not yet exist.
    #
    # So the verdict is now STAGE-AWARE, keyed on the timing_mode the tool already
    # derives from SPEF presence:
    #   * pre_layout_estimate -> gate on setup + constraint completeness only;
    #     DRV and hold are MEASURED, REPORTED, and carried in the CDE, but do not
    #     close the gate at a position where they are not assessable.
    #   * mixed / post_route_signoff -> the full original rule, unchanged. This is
    #     where the original defect fix still applies and still bites.
    #
    # NOTHING IS DROPPED. `verdict_full` below always carries the strict answer,
    # every DRV/hold number is still emitted, and the post-route signoff gate
    # (which requires timing_mode="post_route_signoff") still enforces all of it.
    # Authority: AMEND-PRELAYOUT-STA-SCOPE-001.
    verdict_full = "pass" if (setup_ok and hold_ok and drv_clean) else "fail"
    verdict_timing = "pass" if setup_ok else "fail"
    pre_layout = timing_mode == "pre_layout_estimate"
    verdict = verdict_timing if pre_layout else verdict_full
    # --- CONSTRAINT COVERAGE GATE -------------------------------------------
    # A slack number describes only the paths the SDC actually constrained.
    # Endpoints with no clock, and ports with no I/O delay, are not slow -- they
    # are UNANALYSED, and a clean WNS over a partial population is the most
    # convincing way to close timing on a design that was never timed. This
    # never turns a fail into a pass; it only prevents an incomplete analysis
    # from being reported as a complete one.
    coverage = _parse_constraint_coverage(out)
    population = _parse_signoff_population(
        out, expected_timing_endpoints, expected_input_startpoints,
        expected_constrained_objects, expected_unconstrained)
    if coverage is None:
        constraint_note = ("constraint coverage NOT measured (no check_setup "
                           "section in this log)")
        if verdict == "pass":
            verdict = "not_assessable"
    elif not coverage.get("fully_constrained"):
        constraint_note = (
            "INCOMPLETE CONSTRAINTS: %s unconstrained endpoint(s), %s input "
            "port(s) with no set_input_delay, %s output port(s) with no "
            "set_output_delay, %s register/latch pin(s) with NO CLOCK. "
            "WNS/TNS above cover only the constrained paths."
            % (coverage.get("unconstrained_endpoints"),
               coverage.get("inputs_missing_input_delay"),
               coverage.get("outputs_missing_output_delay"),
               coverage.get("pins_missing_clock")))
        if verdict == "pass":
            verdict = "not_assessable"
    else:
        constraint_note = "every endpoint is constrained"
    if post_route and non_signoff:
        signoff_blockers.insert(0, (
            "NON-SIGNOFF post-route STA: expected_timing_endpoint_count / "
            "expected_input_startpoint_count / expected_constrained_object_count / "
            "expected_unconstrained_endpoints were not all declared, so the "
            "measured population (signoff_population) is reported but not "
            "verified"))
    elif post_route:
        population_blocker = _signoff_population_blocker(population)
        if population_blocker:
            constraint_note = population_blocker
            if verdict == "pass":
                verdict = "not_assessable"
    clock_info = _parse_clock_mode(out, propagated, clock_src)
    if clock_info["mismatch"] and verdict == "pass":
        verdict = "not_assessable"
    if non_signoff and verdict in ("pass", "pass_with_caveats"):
        # Capped, never promoted: fail / not_assessable stay as measured.
        verdict = "review"
    # --- DISABLED TIMING ARCS ------------------------------------------------
    # Disclosed, not gated. `set_disable_timing` is a legitimate deliberate act
    # (breaking a timing loop, a known-bad library arc), so a disabled arc is
    # not by itself a defect -- but it silently shrinks the population the
    # slack number describes, so a reader must be told. Constant propagation
    # through tie cells is excluded from the material count: a healthy
    # crc16_ccitt already shows 113 of them.
    disabled = _parse_disabled_edges(out)
    disabled_note = None
    if disabled is None:
        disabled_note = ("disabled timing arcs NOT measured (no "
                         "report_disabled_edges section in this log)")
    elif disabled["disabled_arcs"]:
        disabled_note = (
            "%d timing arc(s) are DISABLED beyond normal tie-off constant "
            "propagation (%d constant edges ignored). Paths through a disabled "
            "arc are not analysed, so WNS/TNS describe a reduced population: %s"
            % (disabled["disabled_arcs"], disabled["constant_propagation"],
               ", ".join(disabled["disabled_arc_names"][:5])))
    deferred_to_post_cts = []
    if pre_layout:
        if not hold_ok:
            deferred_to_post_cts.append("hold")
        if not drv_clean:
            deferred_to_post_cts.append("drv")

    # A requested SDF that was NOT produced is a failure, not a footnote: a
    # downstream timing GLS would silently fall back to zero-delay simulation and
    # report a clean run that proved nothing about glitches or at-speed behaviour.
    sdf_emitted, sdf_missing = {}, []
    for nm, fname in sdf_files.items():
        full = os.path.join(_OUTPUT_DIR, fname)
        if os.path.isfile(full) and os.path.getsize(full) > 0:
            sdf_emitted[nm] = fname
        else:
            sdf_missing.append(nm)
    if sdf_missing:
        return _cde(
            objective=f"multi-corner static timing analysis of {top}",
            status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            qor={"wns_ns": overall_wns, "tns_ns": overall_tns,
                 "hold_slack_ns": worst_hold, "drv_violations": drv_total},
            signoff={"corners": names, "sdf_files": sdf_emitted,
                     "sdf_missing": sdf_missing, "report": "sta.log"},
            inputs_ref={"netlist": netlist, "sdc": sdc, "corners": corners_spec},
            validation={"verdict": "fail",
                        "note": ("write_sdf was requested but produced no SDF for "
                                 "corner(s) %s. A downstream timing GLS would "
                                 "silently degrade to ZERO-DELAY simulation and "
                                 "report a clean run that proves nothing about "
                                 "glitches or at-speed behaviour, so this fails "
                                 "closed." % ", ".join(sdf_missing))},
            provenance={"sta": _sta_version(binname), "runtime_s": round(elapsed, 3),
                        "log": "sta.log", "other_errors": other_errors})
    return _cde(
        objective=f"multi-corner static timing analysis of {top}",
        status="completed",
        pdk_binding=params.get("pdk_binding", "none"),
        # --- METRIC CLASSES (catalog/tools/metric_classes.py) -----------------
        # STA is the first adopter with MULTIPLE metric families. At post-route
        # signoff, setup/hold slack [ns] and DRV violators [count] all gate and
        # are never combined. At pre-layout, only setup gates; hold and DRV are
        # diagnostic measurements carrying a downstream obligation.
        #
        # `None` means NOT ASSESSED, never "clean": a vacuous run returns earlier
        # with all of these null and verdict=fail, so a null here can only mean
        # the quantity genuinely was not measured at this flow position.
        results={"wns": {"value": overall_wns, "unit": "ns",
                         "class": "gating", "basis": "parsed_opensta_report_wns",
                         "closes_at": "slack >= 0"},
                 "tns": {"value": overall_tns, "unit": "ns",
                         # TNS is DIAGNOSTIC, not gating: the gate is WNS >= 0.
                         # TNS measures how MUCH work remains (and is the better
                         # progress signal), but a design closes on worst slack.
                         "class": "diagnostic",
                         "basis": "parsed_opensta_report_tns"},
                 "hold_worst_slack": {"value": worst_hold, "unit": "ns",
                                      "class": _timing_metric_class(
                                          pre_layout, "hold"),
                                      "basis": "parsed_opensta_hold_slack",
                                      "closes_at": "slack >= 0",
                                      "gates_at": (
                                          "post_cts_post_route_sta"
                                          if pre_layout else "current_sta_stage")},
                 "drv_violations": {"value": drv_total, "unit": "violations",
                                    "class": _timing_metric_class(
                                        pre_layout, "drv"),
                                    "basis": "counted_opensta_drv_reports",
                                    "closes_at": "== 0",
                                    "gates_at": (
                                        "post_cts_post_route_sta"
                                        if pre_layout else "current_sta_stage")},
                 "drv_clean": drv_clean,
                 "timing_mode": timing_mode, "interconnect": interconnect,
                 "clock_mode": clock_info["clock_mode"],
                 "signoff_mode": ("non_signoff" if non_signoff else
                                  "signoff" if post_route else "pre_signoff")},
        # Flat, canonically-named DRV counts sit at the TOP of qor_metrics because
        # that is what cde_progress reads to build progress.families.  The names
        # here are the contract: they must stay in lockstep with the `sta` spec in
        # catalog/tools/cde_progress.py and with residual_class_map in
        # catalog/policy/reopen-repertoire.json, or a real violation becomes
        # invisible to the autonomous reopen path.
        qor={"wns_ns": overall_wns, "tns_ns": overall_tns,
             "hold_slack_ns": worst_hold, "per_corner": per_corner_results,
             "drv_violations": drv_total,
             "max_transition_violations": drv["max_slew"]["violators"],
             "max_capacitance_violations": drv["max_capacitance"]["violators"],
             "max_fanout_violations": drv["max_fanout"]["violators"],
             "min_pulse_width_violations": drv["min_pulse_width"]["violators"],
             "min_period_violations": drv["min_period"]["violators"],
             "max_skew_violations": drv["max_skew"]["violators"],
             "recovery_violations": drv["recovery"]["violators"],
             "removal_violations": drv["removal"]["violators"],
             "clock_gating_setup_violations": drv["clock_gating_setup"]["violators"],
             "clock_gating_hold_violations": drv["clock_gating_hold"]["violators"],
             "drv_detail": drv,
             # Analysis-coverage metrics: how much of the design the slack
             # numbers above actually describe.
             "unclocked_register_pins": (coverage or {}).get("pins_missing_clock"),
             "unconstrained_endpoints": (coverage or {}).get("unconstrained_endpoints"),
             "disabled_timing_arcs": (disabled or {}).get("disabled_arcs")},
        signoff={"setup_met": setup_ok, "hold_met": hold_ok,
                 "drv_met": drv_clean, "drv_violations": drv_total,
                 # CONSTRAINT COVERAGE: which endpoints the slack numbers above
                 # actually cover. A WNS over a partially-constrained design is
                 # not wrong, it is narrower than a reader assumes.
                 "constraint_coverage": coverage,
                 "constraint_coverage_note": constraint_note,
                 "signoff_population": population,
                 "signoff_mode": ("non_signoff" if non_signoff else
                                  "signoff" if post_route else "pre_signoff"),
                 "signoff_blockers": signoff_blockers or None,
                 "clock_mode": clock_info["clock_mode"],
                 "clock_propagation": clock_info,
                 "fully_constrained": (coverage or {}).get("fully_constrained"),
                 # DISABLED TIMING ARCS: paths removed from the slack
                 # population. Constant propagation through tie cells is
                 # normal; anything else narrows the analysis.
                 "disabled_edges": disabled,
                 "disabled_edges_note": disabled_note,
                 # STAGE-AWARE VERDICT (AMEND-PRELAYOUT-STA-SCOPE-001).
                 # `verdict_full` is ALWAYS the strict setup+hold+DRV answer, so a
                 # reviewer can never lose the unrelaxed result. `verdict` is what
                 # closes the gate AT THIS FLOW POSITION. When they disagree,
                 # `deferred_to_post_cts` names exactly which checks were deferred
                 # and `deferral_obligation` states that they still must be gated
                 # downstream -- a deferral is never a drop.
                 "verdict_full": verdict_full,
                 "verdict_timing": verdict_timing,
                 "deferred_to_post_cts": deferred_to_post_cts or None,
                 "deferral_obligation": (
                     ("DEFERRED, NOT WAIVED: %s measured and reported here but not "
                      "gated pre-layout (no SPEF on any corner => net RC and clock "
                      "skew do not yet exist). MUST be gated at post-CTS/post-route "
                      "STA, which requires timing_mode='post_route_signoff'."
                      % ", ".join(deferred_to_post_cts))
                     if deferred_to_post_cts else None),
                 "drv_checks": drv, "drv_capabilities": drv_caps,
                 "corners": names, "analysis": analysis,
                 "timing_mode": timing_mode, "interconnect": interconnect,
                 "per_corner": per_corner_results, "report": "sta.log",
                 # (B) DIAGNOSTIC -- measured, non-gating: WHICH corner and WHICH
                 # check is worst, so a repair can be aimed without re-running.
                 "diagnostics": {
                     "class": "diagnostic",
                     "basis": "parsed_opensta_reports",
                     "worst_setup_corner": _worst_corner_name(
                         per_corner_results, "setup_slack_ns"),
                     "worst_hold_corner": _worst_corner_name(
                         per_corner_results, "hold_slack_ns"),
                     "per_corner_slack_ns": per_corner_results,
                     "drv_violations_by_check": {
                         k: v.get("violators") for k, v in drv.items()
                         if isinstance(v, dict)},
                     "not_assessable_checks": _not_assessable or None,
                     "deferred_to_post_cts": deferred_to_post_cts or None,
                 },
                 # (C) DESCRIPTIVE -- context EXPECTED to hold steady across
                 # attempts. Corner count and timing_mode plateauing is NORMAL and
                 # must not be read by the stall machinery as a stalled gate.
                 "descriptive": {
                     "class": "descriptive",
                     "basis": "run_configuration",
                     "corner_count": len(names),
                     "analysis": analysis,
                     "timing_mode": timing_mode,
                     "spef_corners": len(_spef_corners),
                     "elapsed_s": round(elapsed, 2),
                     "note": ("configuration/context, not a gate and not a "
                              "progress signal"),
                 },
                 # (D) MODEL-AUTHORED -- advisory only, cross-checked, never gating.
                 # Keyed on `drv_violations`: it is the only COUNT here, and a
                 # slack is a continuous measurement an equality cross-check would
                 # mis-handle (float compare), so the count is what gets verified.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), drv_total, "drv_violations"),
                 "sta_report": "sta.rpt",
                 "sdf_files": sdf_emitted or None,
                 "sdf_basis": (
                     ("per-corner delays on the %s basis; back-annotate into GLS "
                      "with $sdf_annotate for glitch/at-speed checking"
                      % interconnect) if sdf_emitted else None)},
        inputs_ref={"netlist": netlist, "sdc": sdc, "corners": corners_spec},
        assumptions=["worst-corner slack is the min across the supplied corners",
                     ("pre-layout: no SPEF on any corner; net RC is ideal, slack is "
                      "optimistic and NOT signoff" if timing_mode == "pre_layout_estimate"
                      else "SPEF-based parasitic timing on %d/%d corners"
                      % (len(_spef_corners), len(names))),
                     ("DRV per-check violator count is the WORST corner, not the sum "
                      "across corners (one pin violating on N corners is one defect)"),
                     ("checks absent from the bound Liberty are reported "
                      "not_characterized, never as a clean 0")],
        margin={"method": "worst-of-corners slack", "wns_ns": worst_wns},
        validation={"verdict": verdict,
                    "note": _drv_verdict_note(
                        setup_ok, hold_ok, drv_clean, drv_total, drv,
                        pre_layout=pre_layout,
                        deferred=deferred_to_post_cts)
                    + ("; " + clock_info["note"] if clock_info["mismatch"] else "")
                    + ("; verdict capped at review: " + "; ".join(signoff_blockers)
                       if non_signoff else "")},
        provenance={"sta": _sta_version(binname), "runtime_s": round(elapsed, 3),
                    "log": "sta.log",
                    # Non-fatal (post-measurement) errors are surfaced, never
                    # silently dropped -- they did not invalidate the analysis but
                    # a reviewer must still see them.
                    "other_errors": other_errors},
    )


def _timing_report(params):
    # Pick the engine from what the INPUT can be linked with, not a fixed
    # preference: a Verilog netlist with no LEF cannot be linked by the
    # openroad-embedded STA at all (ORD-2010). See _sta_bin.
    _nl = str(params.get("netlist") or params.get("def") or "")
    _has_lef = bool(_resolve_lefs(params))
    binname = _sta_bin(needs_tech=_nl.endswith(".def") or _has_lef)
    if binname is None:
        return _cde(objective="STA", status="failed",
                    error="OpenSTA/openroad not found on PATH",
                    validation={"verdict": "fail"})
    top = params.get("top")
    netlist = params.get("netlist")
    sdc = params.get("sdc")
    libs = _liberty_list(params)
    for name, val in (("top", top), ("netlist", netlist), ("sdc", sdc)):
        if not val:
            return _cde(objective="STA", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"missing required field '{name}'",
                        validation={"verdict": "fail"})
    if not _is_ident(top):
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=f"invalid 'top' identifier: {top!r}",
                    validation={"verdict": "fail"})
    # Multi-corner (MCMM) dispatch: when params.corners is a non-empty list, the
    # per-corner Liberty comes from each corner entry, so the top-level Liberty
    # requirement below does not apply.
    corners_spec = params.get("corners")
    # Incompatible inputs: a top-level single-corner `liberty` and a multi-corner
    # `corners` list select two different analysis modes. If the CALLER set both,
    # fail closed rather than silently discarding the single-corner Liberty.
    if (params.get("liberty") is not None
            and isinstance(corners_spec, list) and corners_spec):
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="single-corner `liberty` and multi-corner `corners` are "
                          "mutually exclusive; provide one analysis mode",
                    validation={"verdict": "fail"})
    if isinstance(corners_spec, list) and corners_spec:
        analysis = params.get("analysis", "both")
        max_paths = int(params.get("max_paths", 10))
        return _mcmm_timing_report(params, binname, top, netlist, sdc,
                                   analysis, max_paths, _rc_extra_opts(params),
                                   corners_spec)
    if not libs:
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="missing Liberty: provide params.liberty or pdk_binding.liberty",
                    validation={"verdict": "fail"})
    for p in [netlist, sdc] + libs:
        if not os.path.exists(str(p)):
            return _cde(objective="STA", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"input file not found: {p}",
                        validation={"verdict": "fail"})
    spef = params.get("spef")
    # A REQUESTED SPEF THAT DOES NOT EXIST IS AN ERROR, NOT A DOWNGRADE.
    #
    # This path used to write `read_spef {spef} if os.path.exists(...) else ""`,
    # so a typo'd or unmounted SPEF path silently produced an ideal-interconnect
    # run. The multi-corner path next door has always hard-failed on the same
    # condition ("corner '<n>' SPEF not found"), so the two entry points
    # disagreed about whether missing parasitics is fatal. It is fatal: the
    # caller asked for a parasitic-aware analysis and must not be handed an
    # optimistic one under a different label.
    if spef and not os.path.exists(str(spef)):
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=(f"SPEF requested but not found: {spef}. Refusing to "
                           f"silently fall back to ideal interconnect -- that "
                           f"would report OPTIMISTIC slack from a run the "
                           f"caller asked to be parasitic-aware. Fix the path, "
                           f"or omit `spef` to request a pre-layout estimate "
                           f"deliberately."),
                    validation={"verdict": "fail"})
    analysis = params.get("analysis", "both")
    max_paths = int(params.get("max_paths", 10))

    # Optional report_checks refinements (apply to every path report):
    #   report_fields : extra columns (slew, capacitance, input_pins, nets, fanout)
    #   from/through/to_pins : restrict reported paths to a pin set
    rc_extra = _rc_extra_opts(params)

    # Multi-corner (MCMM) support. When params.corners is a non-empty list of
    # {name, liberty, spef?} entries, we define OpenSTA corners, load a Liberty
    # (and optional SPEF) per corner, and report per-corner WNS/TNS/paths in a
    # single run -- the historical single-corner path is used otherwise.
    corners_spec = params.get("corners")
    if isinstance(corners_spec, list) and corners_spec:
        return _mcmm_timing_report(params, binname, top, netlist, sdc,
                                   analysis, max_paths, rc_extra, corners_spec)

    reads = "\n".join(f"read_liberty {l}" for l in libs)
    is_def = netlist.endswith(".def")
    # Resolve optional LEFs (tech + cell). A DEF REQUIRES them; a Verilog netlist
    # does NOT under standalone OpenSTA, but the openroad-embedded STA still needs a
    # technology (read_lef) before read_verilog or it aborts with ORD-2010. So read
    # LEFs whenever they are available, for BOTH readers.
    lefs = _resolve_lefs(params)
    lef_reads = ""
    if is_def and not lefs:
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="DEF-based STA requires a LEF: provide params.lef "
                          "or pdk_binding.tech_lef", validation={"verdict": "fail"})
    if lefs:
        lef_reads = "\n".join(f"read_lef {l}" for l in lefs) + "\n"
    # For a DEF, read_def loads the design directly -- do NOT call link_design
    # again (OpenROAD would try to link the top as a liberty cell and fail).
    reader = (f"{lef_reads}read_def {netlist}" if is_def
              else f"{lef_reads}read_verilog {netlist}\nlink_design {top}")

    spef_line = f"read_spef {spef}" if spef else ""
    propagated, clock_src = _clock_mode(params, bool(spef))
    clock_tcl = _clock_mode_tcl(propagated)
    # PROVE THE SPEF ACTUALLY LANDED ON THIS NETLIST.
    #
    # read_spef succeeds even when the SPEF describes a DIFFERENT netlist: net
    # names that match nothing are simply ignored, and the run continues with
    # ideal RC on those nets while still calling itself signoff. Measured on
    # crc16_ccitt (routed.def + its own extracted SPEF):
    #     no SPEF        -> 294 unannotated drivers   (294 = the total)
    #     correct SPEF   ->   4 unannotated drivers
    #     corrupted SPEF ->  20 unannotated drivers
    # and ALL THREE produced a normal-looking timing report. The count is the
    # discriminator; the timing number is not.
    #
    # Both reports run in ONE OpenSTA session, so the pre-read call costs a
    # report and no re-analysis, and it supplies the DENOMINATOR: with no
    # parasitics loaded every driver is unannotated, i.e. the "before" count IS
    # the total driver count.
    #
    # Note the floor is NOT zero. With a correct SPEF four drivers remain
    # unannotated on this design -- TIEOFF_zero_/HI and clkload0..2/Y, a tie
    # cell and three dangling clock loads that legitimately carry no net RC. A
    # `== 0` gate would fail a healthy design, so the gate below keys on
    # "annotated nothing at all", which is provable.
    _ann_probe = ""
    if spef_line:
        _ann_probe = ("puts \"__ANN_BEFORE__\"\nreport_parasitic_annotation\n")
        spef_line = (_ann_probe + spef_line
                     + "\nputs \"__ANN_AFTER__\"\nreport_parasitic_annotation")
    checks = ""
    if analysis in ("setup", "both"):
        checks += (f"puts \"__SETUP__\"\nreport_wns\nreport_tns\n"
                   f"report_checks -path_delay max -group_path_count {max_paths} -format full_clock_expanded{rc_extra}\n")
    if analysis in ("hold", "both"):
        checks += (f"puts \"__HOLD__\"\nreport_worst_slack -min\n"
                   f"report_checks -path_delay min -group_path_count {max_paths}{rc_extra}\n")
    # ANALYSIS-COVERAGE PROBES on the single-corner path.
    #
    # The multi-corner path has emitted check_setup for a while; this one never
    # did, so a single-corner run reported WNS/TNS with NO statement about how
    # much of the design those numbers covered -- and `_parse_constraint_coverage`
    # returns None for such a log, which is the "not measured" state the
    # multi-corner verdict deliberately downgrades on. The two entry points now
    # gather the same evidence.
    #
    # Order matters: __DISABLED_EDGES__ must precede __CHECK_SETUP__ because
    # the coverage parser consumes everything after its own marker to the end
    # of the log.
    checks += ('puts "__DISABLED_EDGES__"\nreport_disabled_edges\n'
               'puts "__CHECK_SETUP__"\n'
               'check_setup -unconstrained_endpoints -no_input_delay '
               '-no_output_delay -no_clock -multiple_clock -loops '
               '-generated_clocks -verbose\n')
    # Persist the native OpenSTA timing report as its own file (in addition to the
    # parsed stdout log) for human / Engine review.
    sta_rpt = os.path.join(_OUTPUT_DIR, "sta.rpt")
    file_reports = ""
    if analysis in ("setup", "both"):
        file_reports += (f"report_wns > {sta_rpt}\nreport_tns >> {sta_rpt}\n"
                         f"report_checks -path_delay max -group_path_count {max_paths} "
                         f"-format full_clock_expanded{rc_extra} >> {sta_rpt}\n")
    if analysis in ("hold", "both"):
        redir = ">" if analysis == "hold" else ">>"
        file_reports += (f"report_worst_slack -min {redir} {sta_rpt}\n"
                         f"report_checks -path_delay min -group_path_count {max_paths}{rc_extra} >> {sta_rpt}\n")
    script = f"""{reads}
{reader}
read_sdc {sdc}
{clock_tcl}{spef_line}
{checks}
{file_reports}
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "sta.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command([binname, "-exit", sp])
    proc = subprocess.run([binname, "-exit", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "sta.log"), "w").write(out)

    def _num(pat):
        m = re.search(pat, out)
        return float(m.group(1)) if m else None

    # OpenSTA prints e.g. "wns max 0.00", "tns max 0.00", "worst slack min 0.30"
    wns = _num(r"wns\s+\w+\s+(-?[0-9.eE+]+)")
    tns = _num(r"tns\s+\w+\s+(-?[0-9.eE+]+)")
    hold_slack = _num(r"worst slack\s+\w+\s+(-?[0-9.eE+]+)")
    if proc.returncode != 0 and wns is None:
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="OpenSTA failed; see sta.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"sta": _sta_version(binname), "log": "sta.log"})

    # Annotation coverage, read from the bracketed pair emitted above.
    _ann = _parse_annotation(out) if spef else None
    if _ann and _ann.get("annotated") == 0:
        return _cde(objective="STA", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=(f"SPEF read but it annotated NOTHING: "
                           f"{_ann['before']} of {_ann['before']} drivers are "
                           f"still unannotated after read_spef {spef}. The SPEF "
                           f"parsed, so this is not a syntax error -- its net "
                           f"names do not match this netlist, which usually "
                           f"means it belongs to a different design or a "
                           f"different stage of this one. Every delay would "
                           f"come from IDEAL interconnect while the run "
                           f"reported itself as parasitic-aware."),
                    validation={"verdict": "fail"},
                    qor={"unannotated_drivers": _ann["after"],
                         "total_drivers": _ann["before"],
                         "annotation_coverage_pct": 0.0},
                    provenance={"sta": _sta_version(binname), "log": "sta.log"})

    setup_ok = wns is None or wns >= 0
    hold_ok = hold_slack is None or hold_slack >= 0
    verdict = "pass" if setup_ok and hold_ok else "fail"

    # --- ANALYSIS COVERAGE (mirrors the multi-corner gate) -------------------
    # A slack number describes only the paths that were actually analysed. An
    # unclocked register is not slow, it is INVISIBLE. Measured on crc16_ccitt
    # by disabling the clock root: 32 unclocked pins, unconstrained endpoints
    # 2 -> 129, setup slack UNCHANGED at 14.39 ns and hold slack IMPROVED from
    # 0.40 to 1.01 ns. Losing a third of the design made timing look better.
    # As on the multi-corner path this never turns a fail into a pass; it only
    # stops an incomplete analysis being reported as a complete one.
    _cov = _parse_constraint_coverage(out)
    _cov_note = None
    if _cov is None:
        _cov_note = ("constraint coverage NOT measured (no check_setup section "
                     "in this log)")
        if verdict == "pass":
            verdict = "not_assessable"
    elif not _cov.get("fully_constrained"):
        _cov_note = (
            "INCOMPLETE CONSTRAINTS: %s unconstrained endpoint(s), %s input "
            "port(s) with no set_input_delay, %s output port(s) with no "
            "set_output_delay, %s register/latch pin(s) with NO CLOCK. "
            "WNS/TNS above cover only the constrained paths."
            % (_cov.get("unconstrained_endpoints"),
               _cov.get("inputs_missing_input_delay"),
               _cov.get("outputs_missing_output_delay"),
               _cov.get("pins_missing_clock")))
        if verdict == "pass":
            verdict = "not_assessable"
    else:
        _cov_note = "every endpoint is constrained"

    _dis = _parse_disabled_edges(out)
    _dis_note = None
    if _dis is None:
        _dis_note = ("disabled timing arcs NOT measured (no "
                     "report_disabled_edges section in this log)")
    elif _dis["disabled_arcs"]:
        _dis_note = (
            "%d timing arc(s) are DISABLED beyond normal tie-off constant "
            "propagation (%d constant edges ignored). Paths through a disabled "
            "arc are not analysed, so WNS/TNS describe a reduced population: %s"
            % (_dis["disabled_arcs"], _dis["constant_propagation"],
               ", ".join(_dis["disabled_arc_names"][:5])))

    _clk = _parse_clock_mode(out, propagated, clock_src)
    if _clk["mismatch"] and verdict == "pass":
        verdict = "not_assessable"

    # Pre-layout vs post-route honesty: with no SPEF the net RC is ideal (zero), so
    # it explicitly so a downstream reader / gate never mistakes an ideal-interconnect
    # run for a parasitic-aware signoff STA.
    has_spef = bool(spef)
    timing_mode = "post_route_signoff" if has_spef else "pre_layout_estimate"
    interconnect = "SPEF parasitics" if has_spef else \
        "ideal (no SPEF) -- pre-layout estimate, optimistic, not signoff"
    # Partial annotation is not fatal -- a tie cell and dangling clock loads
    # legitimately carry no net RC -- but it IS material, because every
    # unannotated driver is timed with optimistic ideal interconnect. Disclose
    # it rather than hiding it behind the "post_route_signoff" label.
    _ann_note = None
    if _ann and _ann["after"] > 0:
        _ann_note = (
            "%d of %d drivers (%.2f%%) carry SPEF parasitics; the remaining %d "
            "are timed with IDEAL interconnect (optimistic). Tie cells and "
            "dangling loads legitimately have no net RC; a larger residue "
            "means the SPEF does not fully match this netlist."
            % (_ann["annotated"], _ann["before"], _ann["coverage_pct"],
               _ann["after"]))
        interconnect += " (%.2f%% of drivers annotated)" % _ann["coverage_pct"]

    corner = (params.get("pdk_binding") or {}).get("corners")
    return _cde(
        objective=f"static timing analysis of {top}",
        status="completed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"wns": {"value": wns, "unit": "ns"},
                 "tns": {"value": tns, "unit": "ns"},
                 "hold_worst_slack": {"value": hold_slack, "unit": "ns"},
                 "timing_mode": timing_mode, "interconnect": interconnect,
                 "clock_mode": _clk["clock_mode"]},
        qor={"wns_ns": wns, "tns_ns": tns, "hold_slack_ns": hold_slack,
             "clock_mode": _clk["clock_mode"],
             # Measured, not asserted: proof that the SPEF landed on THIS
             # netlist. None when no SPEF was requested.
             "annotation_coverage_pct": (_ann or {}).get("coverage_pct"),
             "unannotated_drivers": (_ann or {}).get("after"),
             "total_drivers": (_ann or {}).get("before"),
             # How much of the design the slack numbers above describe.
             "unclocked_register_pins": (_cov or {}).get("pins_missing_clock"),
             "unconstrained_endpoints": (_cov or {}).get("unconstrained_endpoints"),
             "disabled_timing_arcs": (_dis or {}).get("disabled_arcs")},
        signoff={"setup_met": setup_ok, "hold_met": hold_ok,
                 "corners": corner, "analysis": analysis,
                 "timing_mode": timing_mode, "interconnect": interconnect,
                 "parasitic_annotation": _ann,
                 "parasitic_annotation_caveat": _ann_note,
                 "constraint_coverage": _cov,
                 "constraint_coverage_note": _cov_note,
                 "fully_constrained": (_cov or {}).get("fully_constrained"),
                 "disabled_edges": _dis,
                 "disabled_edges_note": _dis_note,
                 "clock_mode": _clk["clock_mode"],
                 "clock_propagation": _clk,
                 "report": "sta.log"},
        inputs_ref={"netlist": netlist, "sdc": sdc, "liberty": libs, "spef": spef},
        assumptions=["single-run corner set from the binding; MCMM requires a "
                     "Liberty per corner",
                     ("pre-layout: no SPEF loaded; net RC is ideal, slack is "
                      "optimistic and NOT signoff" if not has_spef
                      else "post-route: SPEF parasitics loaded"),
                     _clk["note"]],
        margin={"method": "worst-corner slack", "wns_ns": wns},
        validation={"verdict": verdict,
                    "note": ("setup and hold met" if verdict == "pass"
                             else "timing violation (setup or hold)")
                    + ("; " + _clk["note"] if _clk["mismatch"] else "")},
        provenance={"sta": _sta_version(binname), "runtime_s": round(elapsed, 3),
                    "log": "sta.log"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s == "timing_report":
        return _timing_report(params)
    return _cde(objective="STA", status="failed",
                error=f"unknown scenario '{s}'; supported: timing_report",
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
