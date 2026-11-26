#!/usr/bin/env python3
"""rtl_design_utils.py -- real Yosys RTL-hygiene logic for the chip-rtl-design tool.

Scenarios:
  elaborate     -- read + hierarchy -check; confirm the design elaborates and
                   report the top module and its port surface.
  lint_hygiene  -- elaborate, then screen for inferred latches ($dlatch),
                   undriven/multiply-driven nets, and `check` problems. Fails
                   closed if inferred latches or driver problems are present.
  cdc_scan      -- structurally enumerate clock domains (edge-sensitive clocks)
                   and flag potential crossings for downstream CDC/RDC signoff.

The tool shells out to the real `yosys` binary. It is node-agnostic: no PDK,
Liberty, or corners. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

import rtl_frontend
import reset_hygiene
import synchronizer_hygiene

TOOL = "rtl-design"
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

    moves = {}
    for entry in list(os.listdir(root)):
        full = os.path.join(root, entry)
        if not os.path.isfile(full):
            continue
        dest = _classify(entry)
        if dest is None:
            continue
        target = os.path.join(root, dest, entry)
        if os.path.exists(target):
            raise FileExistsError("refusing to overwrite artifact: " + target)
        os.replace(full, target)
        moves[entry] = dest + "/" + entry
        moves[full] = target
    return moves


def _relocate_output_refs(value, moves):
    if isinstance(value, str):
        return moves.get(value, value)
    if isinstance(value, dict):
        return {key: _relocate_output_refs(item, moves) for key, item in value.items()}
    if isinstance(value, list):
        return [_relocate_output_refs(item, moves) for item in value]
    return value



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
    results = _relocate_output_refs(results, _organize_output())
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


# ---------------------------------------------------------------- CDE helper
def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    An envelope that stamps no `stage` resolves to no registry entry, reports NO
    METRIC, and a missing metric is indistinguishable downstream from a closed
    gate. The tool names its own gate rather than leaving it to the caller.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "rtl"
    except Exception:
        return "rtl"


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
        base.setdefault("basis", "agent_read_of_elaboration_log" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_elaboration_log")


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


def _cde(objective, status, results=None, signoff=None, qor=None, vplan=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         margin=None, error=None):
    env = {
        "tool": TOOL,
        "stage": _canonical_stage(),
        "status": status,  # completed | failed
        "objective": objective,
        "tools_used": [{"name": "Yosys", "version": _yosys_version()}],
        "pdk_binding": "none",
        "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {},
        "vplan": vplan or "not_applicable",
        "results": results or {},
        "qor_metrics": qor or {},
        "signoff_evidence": signoff or {},
        "margin": margin or {"method": "structural_elaboration",
                             "note": "RTL hygiene is technology-independent"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _yosys_version():
    try:
        out = subprocess.run(["yosys", "-V"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip().split("\n")[0]
    except Exception:
        return "unknown"


# ---------------------------------------------------------------- RTL staging
def _stage_rtl(params):
    """Return (list of Verilog file paths, combined RTL text)."""
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "design.v")
        with open(p, "w") as f:
            f.write(params["rtl"])
        files.append(p)
    for rf in params.get("rtl_files", []):
        if not os.path.isfile(rf):
            raise FileNotFoundError("RTL source not found: " + str(rf))
        files.append(rf)
    if not files:
        raise ValueError("no RTL provided: supply 'rtl' (inline) or 'rtl_files'")
    text = ""
    for f in files:
        with open(f) as stream:
            text += stream.read() + "\n"
    return files, text


def _run_yosys(script, tolerate_failure=False):
    script_path = os.path.join(_OUTPUT_DIR, "rtl.ys")
    with open(script_path, "w") as f:
        f.write(script)
    t0 = time.time()
    _save_run_command(["yosys", "-s", script_path])
    proc = subprocess.run(["yosys", "-s", script_path], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    log_path = os.path.join(_OUTPUT_DIR, "yosys.log")
    with open(log_path, "w") as f:
        f.write("=== STDOUT ===\n" + proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0 and not tolerate_failure:
        raise RuntimeError(f"yosys failed (rc={proc.returncode}); see yosys.log:\n"
                           + proc.stderr[-2000:])
    return proc.stdout, proc.stderr, proc.returncode, elapsed


def _count_cell_type(stat_text, cell_regex):
    total = 0
    for m in re.finditer(cell_regex + r"\s+(\d+)", stat_text):
        total += int(m.group(1))
    return total


def _parse_check_problems(check_text):
    """Return (problem_count, has_undriven, has_multidriven)."""
    count = 0
    m = re.search(r"found (\d+) problems? in this check", check_text)
    if m:
        count = int(m.group(1))
    lowered = check_text.lower()
    has_undriven = "undriven" in lowered or "used but not driven" in lowered
    has_multidriven = ("multiple conflicting drivers" in lowered
                       or "multiple drivers" in lowered
                       or "multiply driven" in lowered)
    return count, has_undriven, has_multidriven


# ---------------------------------------------------------------- scenarios
def _elaborate(params):
    top = params["top"]
    files, _ = _stage_rtl(params)
    reads = rtl_frontend.yosys_read_block(files, top, params)
    script = f"""{reads}
hierarchy -check -top {top}
proc
stat
tee -o {os.path.join(_OUTPUT_DIR, 'rtl_stat.rpt')} stat
"""
    out, _err, _rc, elapsed = _run_yosys(script)
    return _cde(
        objective=f"elaborate {top}",
        status="completed",
        results={"synthesizable": {"value": True, "unit": "bool"}},
        signoff={"stage": "elaboration", "top": top,
                 "native_exit_codes": {"yosys": _rc}},
        inputs_ref={"rtl_files": files},
        validation={"verdict": "pass", "note": "elaborated without error"},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "yosys.log"},
    )


def _reset_hygiene(params, files, top):
    """Structural reset-hygiene analysis via a Yosys JSON netlist.

    Kept separate from the main lint script so a failure here degrades to
    not_assessable instead of taking the whole hygiene run down with it.

    MUST FLATTEN BEFORE ANALYSIS. `reset_hygiene.analyze()` only looks at the
    cells of the TOP module (see its `targets = {top: mods[top]}` branch), so
    without `flatten` a reset driven from top into a child instance's `rst_n`
    port is just a top-level cell CONNECTION named "rst_n" -- not an
    `$adff`/`$sdff` reset pin, because the real flops live one level down in
    the (still-hierarchical) child module. That connection then falls through
    the reset-pin exclusion set `{ARST, SRST, CLR, SET, CLK, Q, ALOAD}` (none
    of those match an arbitrary child port name) and gets counted as ordinary
    "data", producing a false `reset_used_as_data`. Flattening inlines every
    submodule's flops into the top module so the real $adff/$sdff cells --
    and their genuine reset pins -- are what gets examined.
    """
    jpath = os.path.join(_OUTPUT_DIR, "rtl_netlist.json")
    reads = rtl_frontend.yosys_read_block(files, top, params)
    script = f"""{reads}
hierarchy -check -top {top}
proc
flatten
opt -purge
write_json {jpath}
"""
    try:
        _run_yosys(script, tolerate_failure=True)
        nl = reset_hygiene.load(jpath)
        return reset_hygiene.analyze(nl, top)
    except reset_hygiene.NetlistUnavailable as e:
        return {"assessable": False, "findings": None, "note": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"assessable": False, "findings": None,
                "note": "reset hygiene analysis failed: %s" % e}


def _synchronizer_hygiene(top):
    """Synchronizer-shape analysis on the flattened netlist `_reset_hygiene` wrote.

    Reuses that netlist rather than re-elaborating: flattening is what makes a
    child module's flops visible as real $dff cells instead of a port connection.
    """
    jpath = os.path.join(_OUTPUT_DIR, "rtl_netlist.json")
    try:
        with open(jpath) as fh:
            nl = json.load(fh)
        return synchronizer_hygiene.analyze(nl, top)
    except (OSError, ValueError) as e:
        return {"assessable": False, "findings": None,
                "note": "synchronizer analysis could not read the netlist: %s" % e}
    except Exception as e:  # noqa: BLE001
        return {"assessable": False, "findings": None,
                "note": "synchronizer hygiene analysis failed: %s" % e}


def _lint_hygiene(params):
    top = params["top"]
    files, _ = _stage_rtl(params)
    reads = rtl_frontend.yosys_read_block(files, top, params)
    # Elaborate to a coarse gate/word-level netlist, then inspect.
    script = f"""{reads}
hierarchy -check -top {top}
proc
opt -purge
stat
check
"""
    out, err, rc, elapsed = _run_yosys(script, tolerate_failure=True)
    if rc != 0:
        return _cde(
            objective=f"RTL hygiene lint of {top}",
            status="failed",
            inputs_ref={"rtl_files": files},
            error="elaboration/proc failed; see yosys.log",
            signoff={"yosys_stderr_tail": err[-1000:],
                     "native_exit_codes": {"yosys": rc}},
            validation={"verdict": "fail", "reason": "does not elaborate"},
            provenance={"yosys": _yosys_version(), "log": "yosys.log"},
        )

    latches = _count_cell_type(out, r"\$_?dlatch\w*")
    check_problems, has_undriven, has_multidriven = _parse_check_problems(out)

    # RESET HYGIENE -- previously absent entirely. Reset defects are
    # intermittent, survive most functional simulation (which applies one clean
    # reset at time zero) and surface on silicon as a rare failure-to-start.
    _rst = _reset_hygiene(params, files, top)
    _rst_gating = _rst.get("gating_findings") if _rst.get("assessable") else None

    # SYNCHRONIZER SHAPE -- previously absent entirely. A multi-bit payload given
    # one 2-flop chain per bit passes every check above (it has no latch, no
    # undriven net and clean reset style) and is still wrong, so it reached a
    # blessed RTL attempt and was caught only by the downstream CDC gate.
    _syn = _synchronizer_hygiene(top)
    _syn_gating = _syn.get("gating_findings") if _syn.get("assessable") else None

    findings = []
    if latches:
        findings.append(f"{latches} inferred latch(es) ($dlatch)")
    if has_undriven:
        findings.append("undriven net(s) detected")
    if has_multidriven:
        findings.append("multiply-driven net(s) detected")
    if check_problems:
        findings.append(f"{check_problems} structural check problem(s)")
    for f in (_rst.get("findings") or []):
        if f["severity"] == "gating":
            findings.append("reset: %s on '%s'" % (f["kind"], f["net"]))
    for f in (_syn.get("findings") or []):
        if f["severity"] == "gating":
            findings.append("synchronizer: %s on '%s'" % (f["kind"], f["net"]))

    # Advisory findings are listed too, PREFIXED so they cannot be mistaken for
    # failures. They are excluded from the gate, not from the report: an
    # unsynchronized async reset does not block this stage, but a reader who
    # sees only "no hygiene issues found" will never hear about it. A headline
    # of "no issues" beside a non-empty advisory list is its own small lie.
    _advisories = ["advisory -- reset: %s%s" % (
        f["kind"], (" on '%s'" % f["net"]) if f.get("net") else "")
        for f in (_rst.get("findings") or []) if f["severity"] != "gating"]
    _advisories += ["advisory -- synchronizer: %s%s" % (
        f["kind"], (" on '%s'" % f["net"]) if f.get("net") else "")
        for f in (_syn.get("findings") or []) if f["severity"] != "gating"]

    clean = not (latches or has_undriven or has_multidriven or check_problems
                 or _rst_gating or _syn_gating)
    status = "completed" if clean else "failed"
    # A NULL RESET RESULT IS NOT A CLEAN ONE.
    # `_rst_gating` is None when the netlist could not be examined, and `not
    # (... or None)` is True -- so without this branch a design whose resets
    # were never looked at returned a flat `pass`. That is the fail-open shape
    # this whole module exists to remove: "we could not check" silently became
    # "there is nothing wrong". The defect counts are still clean, so it is not
    # a failure either; it is a pass with a named, unmeasured gap.
    if clean and not (_rst.get("assessable") and _syn.get("assessable")):
        verdict = "not_assessable"
    else:
        verdict = "pass" if clean else "fail"

    return _cde(
        objective=f"RTL hygiene lint of {top}",
        status=status,
        # (A) GATING -- each defect count is parsed from yosys stat/check output
        # and must reach zero. `synthesizable` is the boolean roll-up of them.
        results={
            "synthesizable": {
                "value": clean, "unit": "bool",
                "class": "gating", "basis": "parsed_yosys_check_output",
                "closes_at": "== true",
                "note": ("Roll-up of the defect counts below. A null means NOT "
                         "ASSESSED (elaboration failed) and must never read as "
                         "true -- see the rc != 0 path above.")},
            "inferred_latch_count": {
                "value": latches, "unit": "count",
                "class": "gating", "basis": "parsed_yosys_stat_output",
                "closes_at": "== 0",
                "note": "counted $dlatch cells; an inferred latch is a design defect"},
            "check_problems": {
                "value": check_problems, "unit": "count",
                "class": "gating", "basis": "parsed_yosys_check_output",
                "closes_at": "== 0"},
            "reset_hygiene_violations": {
                "value": _rst_gating, "unit": "count",
                "class": "gating", "basis": _rst.get("basis", "not_assessed"),
                "closes_at": "== 0",
                "note": ("Structurally provable reset defects: one net used "
                         "both async and sync, one net used at both "
                         "polarities, or a reset also sampled as data. Read "
                         "from Yosys cell TYPES and PARAMETERS, not from "
                         "source spelling. NULL means the netlist could not be "
                         "examined -- never that the resets are clean. "
                         "Naming-convention and de-assertion-synchronizer "
                         "findings are ADVISORY and deliberately excluded from "
                         "this count, because neither is provable from "
                         "structure alone.")},
            "synchronizer_hygiene_violations": {
                "value": _syn_gating, "unit": "count",
                "class": "gating", "basis": _syn.get("basis", "not_assessed"),
                "closes_at": "== 0",
                "note": ("Multi-bit input ports whose every bit is captured by an "
                         "UNENABLED register feeding a second register stage -- a "
                         "per-bit 2-flop synchronizer on a bus. A 2-flop "
                         "synchronizer resolves ONE bit; per-bit on a payload the "
                         "resolved bits need never have coexisted at the source, "
                         "and more stages do not fix it. Read from Yosys cell TYPES "
                         "and the EN pin, not from signal spelling. A capture "
                         "register with a real shared enable is the correct shape "
                         "and is counted in qualified_capture_buses instead. NULL "
                         "means the netlist could not be examined -- never that the "
                         "synchronizers are clean.")},
        },
        signoff={
            "native_exit_codes": {"yosys": rc},
            "inferred_latch_count": latches,
            "undriven_nets": has_undriven,
            "multidriven_nets": has_multidriven,
            "check_problems": check_problems,
            "findings": (findings + _advisories) or ["no hygiene issues found"],
            "advisories": _advisories,
            "reset_hygiene": _rst,
            "synchronizer_hygiene": _syn,
            # (B) DIAGNOSTIC -- measured, non-gating. The named findings are the
            # repair surface; the booleans say WHICH defect class is open.
            "diagnostics": {
                "class": "diagnostic", "basis": "parsed_yosys_check_output",
                "findings": (findings + _advisories) or ["no hygiene issues found"],
                "advisories": _advisories,
                "undriven_nets": has_undriven,
                "multidriven_nets": has_multidriven,
                "inferred_latches": latches,
                "check_problems": check_problems},
            # (C) DESCRIPTIVE -- configuration, expected to hold steady across
            # attempts. Kept separate so a constant is not read as convergence.
            "descriptive": {
                "class": "descriptive", "basis": "run_configuration",
                "top": top, "rtl_file_count": len(files),
                "engine": "yosys", "elapsed_s": round(elapsed, 3)},
            # (D) MODEL-AUTHORED -- advisory only, never closes or moves a gate.
            "interpretation": _labelled_interpretation(
                params.get("interpretation")),
            "interpretation_crosscheck": _crosscheck_interpretation(
                params.get("interpretation"), latches, "inferred_latch_count"),
        },
        inputs_ref={"rtl_files": files},
        assumptions=[
            "hygiene is technology-independent; node mapping owned by the Logic "
            "Synthesis agent",
            "reset hygiene is read from the ELABORATED netlist (cell types and "
            "parameters), not from source text; naming-convention and "
            "de-assertion-synchronizer findings are advisory because neither is "
            "provable from structure alone",
        ],
        validation={"verdict": verdict,
                    "latch_free": latches == 0,
                    "reset_hygiene_assessed": _rst.get("assessable", False),
                    "note": (None if _rst.get("assessable") else
                             ("reset hygiene was NOT assessed (%s); the other "
                              "hygiene checks are clean but the reset "
                              "architecture is unverified, not verified clean"
                              % _rst.get("note", "reason unrecorded"))),
                    "driver_clean": not (has_undriven or has_multidriven)},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "yosys.log"},
    )


def _structural_crossings(netlist_json, top):
    """Derive REAL clock-domain crossings from the elaborated netlist.

    The previous enumeration took every clock name matched by a regex over the
    SOURCE TEXT and emitted the full cartesian product of pairs. That is not a
    measurement: two entirely independent clock domains that never exchange a
    signal were reported as a crossing requiring signoff, while the actual
    question -- does a net produced in one domain get sampled in another --
    was never asked. The count was therefore N*(N-1)/2 regardless of the design.

    Here a crossing is only reported when a net DRIVEN by a flop on clock A is
    READ by a flop on clock B. Returns (crossings, domains, assessable, reason).
    """
    try:
        design = json.loads(netlist_json)
    except Exception as exc:
        return [], [], False, f"netlist JSON unreadable: {exc}"
    mods = design.get("modules") or {}
    mod = mods.get(top) or (list(mods.values())[0] if mods else None)
    if not mod:
        return [], [], False, "no module found in the elaborated netlist"
    cells = mod.get("cells") or {}
    # bit -> clock domain of the flop that DRIVES it
    driver_domain, flop_inputs, domains = {}, [], set()
    for cname, c in cells.items():
        ctype = str(c.get("type") or "")
        if "dff" not in ctype.lower() and "dlatch" not in ctype.lower():
            continue
        conns = c.get("connections") or {}
        clk_bits = conns.get("CLK") or conns.get("C") or []
        if not clk_bits:
            continue
        dom = str(clk_bits[0])
        domains.add(dom)
        for b in (conns.get("Q") or []):
            driver_domain[b] = dom
        for b in (conns.get("D") or []):
            flop_inputs.append((b, dom, cname))
    if not domains:
        return [], [], False, ("no clocked sequential cells in the elaborated "
                               "netlist, so no clock domain could be resolved")
    # Map each clock bit back to a readable net name.
    bit_names = {}
    for nname, n in (mod.get("netnames") or {}).items():
        for b in (n.get("bits") or []):
            bit_names.setdefault(str(b), nname)
    seen, crossings = set(), []
    for bit, dst_dom, cell in flop_inputs:
        src_dom = driver_domain.get(bit)
        # A bit with no flop driver is combinational or a primary input; it has
        # no source domain, so it is not a crossing this analysis can claim.
        if src_dom is None or src_dom == dst_dom:
            continue
        key = (src_dom, dst_dom)
        if key in seen:
            continue
        seen.add(key)
        crossings.append({
            "from": bit_names.get(src_dom, f"clk_bit_{src_dom}"),
            "to": bit_names.get(dst_dom, f"clk_bit_{dst_dom}"),
            "example_destination_cell": cell,
            "status": "requires_cdc_signoff",
            "basis": "structural: a net driven in the source domain is sampled "
                     "by a flop in the destination domain",
        })
    named = sorted({bit_names.get(d, f"clk_bit_{d}") for d in domains})
    return crossings, named, True, None


def _cdc_scan(params):
    top = params["top"]
    files, text = _stage_rtl(params)
    reads = rtl_frontend.yosys_read_block(files, top, params)
    njson = os.path.join(_WORK_DIR, "cdc_netlist.json")
    script = f"""{reads}
hierarchy -check -top {top}
proc
stat
write_json {njson}
"""
    out, _err, _rc, elapsed = _run_yosys(script)
    dff = _count_cell_type(out, r"\$_?[ds]dffe?\w*|\$dff\w*")

    # Clock names as they appear in the source, kept for reporting only. These
    # are NOT the basis of the crossing analysis; see _structural_crossings.
    src_clocks = sorted(set(re.findall(r"@\s*\(\s*(?:pos|neg)edge\s+(\w+)", text)))
    resets = sorted({c for c in src_clocks
                     if re.search(r"rst|reset|clr|clear", c, re.IGNORECASE)})
    text_clock_domains = [c for c in src_clocks if c not in resets]

    crossings, clock_domains, assessable, reason = [], [], False, None
    if os.path.exists(njson):
        try:
            crossings, clock_domains, assessable, reason = _structural_crossings(
                open(njson, encoding="utf-8", errors="ignore").read(), top)
        except OSError as exc:
            reason = f"netlist JSON could not be read: {exc}"
    else:
        reason = "yosys did not emit a netlist JSON, so no structural crossing "\
                 "analysis was possible"
    if not assessable:
        # NOT a clean "no crossings": the analysis did not run. Falling back to
        # the source-text list here would re-introduce the fabricated count.
        clock_domains = text_clock_domains
    verdict = ("not_assessable" if not assessable
               else ("pass" if not crossings else "review"))
    note = (f"structural CDC analysis unavailable: {reason}" if not assessable
            else ("no net crosses a clock domain boundary" if not crossings
                  else f"{len(crossings)} structural crossing(s) enumerated for "
                       f"CDC signoff"))

    return _cde(
        objective=f"clock-domain enumeration for {top}",
        status="completed",
        results={
            "clock_domains": {"value": len(clock_domains), "unit": "count"},
            "potential_crossings": {"value": len(crossings) if assessable else None,
                                    "unit": "count"},
            "flip_flops": {"value": dff, "unit": "count"},
        },
        vplan={"clocks": clock_domains, "resets": resets,
               "crossings": crossings},
        signoff={"clock_domains": clock_domains, "resets": resets,
                 "crossings": crossings,
                 "crossing_analysis": ("structural_netlist" if assessable
                                       else "unavailable"),
                 "crossing_analysis_reason": reason,
                 "source_text_clock_names": text_clock_domains,
                 "note": ("a crossing is reported only where a net DRIVEN by a "
                          "flop on one clock is SAMPLED by a flop on another; "
                          "two independent domains that never exchange a signal "
                          "are not a crossing. Synchronizer verification is "
                          "owned by the CDC/RDC Signoff agent")},
        inputs_ref={"rtl_files": files},
        assumptions=[
            "clock domains are resolved from the CLK connection of each "
            "sequential cell in the ELABORATED netlist, not from clock names "
            "matched in the source text",
            "gated/derived clocks appear as distinct domains unless the netlist "
            "resolves them to the same net",
        ],
        validation={"verdict": verdict, "note": note},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "yosys.log"},
    )


_VERILOG_FORMAT_EXTS = {".v", ".sv", ".vh", ".svh"}


def _formatter_binary():
    """Locate the verible-verilog-format binary (mirrors rtl-lint's `_bin`)."""
    name = "verible-verilog-format"
    for c in (name, "/usr/local/bin/" + name, "/usr/bin/" + name):
        if shutil.which(c) or os.path.exists(c):
            return shutil.which(c) or c
    return None


def _format_proposal_name(source, used_names=None):
    """Return a flat proposal name that keeps a valid HDL extension.

    Two DIFFERENT source files hash to the SAME sha256 prefix only when their
    CONTENT is identical -- but distinct files (e.g. same basename in sibling
    directories) with identical content still need distinct proposal names so
    neither overwrites the other. The hash-based disambiguation collapses in
    exactly that case, so a numeric suffix is the final tiebreaker that
    guarantees uniqueness.
    """
    used_names = used_names if used_names is not None else set()
    base = os.path.basename(source)
    stem, suffix = os.path.splitext(base)
    candidate = stem + ".formatted" + suffix if suffix else base + ".formatted"
    if candidate in used_names:
        source_hash = (_hash_input_file(source) or {}).get("sha256", "unknown")[:12]
        base = stem + "." + source_hash
        candidate = base + ".formatted" + suffix
        index = 2
        while candidate in used_names:
            candidate = base + "." + str(index) + ".formatted" + suffix
            index += 1
    used_names.add(candidate)
    return candidate


def _normalize_authored_inline(rtl_text, top):
    """Run agent-authored inline RTL through verible-verilog-format BEFORE it is
    hygiene-checked or saved, so what gets examined and persisted is always
    canonical text -- never whatever whitespace the agent happened to author.
    """
    evidence = {"mode": "normalize_agent_authored_inline",
                "changed": False, "verified_canonical": False}
    b = _formatter_binary()
    if not b:
        evidence["error"] = "verible-verilog-format not found on PATH"
        return rtl_text, evidence
    try:
        src_path = os.path.join(_WORK_DIR, "%s.authored.pre_format.v" % top)
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(rtl_text)
        cmd = [b, src_path]
        _save_run_command(cmd, "run_command_format_authored.txt")
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
        evidence["format_exit"] = proc.returncode
        if proc.returncode != 0:
            evidence["error"] = ("verible-verilog-format exited "
                                  + str(proc.returncode))
            return rtl_text, evidence
        canonical = proc.stdout
        evidence["changed"] = canonical != rtl_text
        verify_path = os.path.join(_WORK_DIR, "%s.authored.post_format.v" % top)
        with open(verify_path, "w", encoding="utf-8") as f:
            f.write(canonical)
        vcmd = [b, "--verify", verify_path]
        _save_run_command(vcmd, "run_command_format_authored_verify.txt")
        vproc = subprocess.run(vcmd, capture_output=True, text=True, cwd=_WORK_DIR)
        evidence["verify_exit"] = vproc.returncode
        evidence["verified_canonical"] = vproc.returncode == 0
        if vproc.returncode != 0:
            evidence["error"] = "normalized RTL failed formatter verification"
        return canonical, evidence
    except OSError as e:
        evidence["error"] = "could not normalize authored RTL: %s" % e
        return rtl_text, evidence


def _verify_files_without_mutation(rtl_files):
    """Check supplied RTL files' canonical format WITHOUT touching them -- the
    source the caller pointed at is evidence and must survive unchanged. Any
    file found not canonical gets a formatted PROPOSAL written to _OUTPUT_DIR
    instead, verified re-canonical, and reported. VHDL files are outside
    verible-verilog-format's scope and are reported separately, never formatted.
    """
    checked = []
    vhdl_skipped = []
    unformatted = []
    proposals = []
    proposal_errors = []
    native_exits = {}
    used_names = set()
    evidence = {"mode": "verify_files_without_mutation"}
    b = _formatter_binary()
    if not b:
        evidence.update({
            "checked_files": [], "vhdl_files_not_applicable": [],
            "error": "verible-verilog-format not found on PATH",
        })
        return evidence, 0
    for rf in rtl_files:
        ext = os.path.splitext(rf)[1].lower()
        if ext not in _VERILOG_FORMAT_EXTS:
            vhdl_skipped.append(os.path.basename(rf))
            continue
        checked.append(os.path.basename(rf))
        vcmd = [b, "--verify", rf]
        _save_run_command(vcmd, "run_command_format_verify.txt")
        vproc = subprocess.run(vcmd, capture_output=True, text=True, cwd=_WORK_DIR)
        native_exits[rf] = {"verify": vproc.returncode}
        if vproc.returncode == 0:
            continue
        unformatted.append(os.path.basename(rf))
        fcmd = [b, rf]
        _save_run_command(fcmd, "run_command_format_proposal.txt")
        fproc = subprocess.run(fcmd, capture_output=True, text=True, cwd=_WORK_DIR)
        native_exits[rf]["proposal"] = fproc.returncode
        if fproc.returncode != 0:
            proposal_errors.append(
                os.path.basename(rf) + " formatter exited "
                + str(fproc.returncode) + " while creating a proposal")
            continue
        canonical = fproc.stdout
        proposal_name = _format_proposal_name(rf, used_names)
        fp = os.path.join(_OUTPUT_DIR, proposal_name)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(canonical)
        verify_cmd = [b, "--verify", fp]
        _save_run_command(verify_cmd, "run_command_format_proposal_verify.txt")
        vpproc = subprocess.run(verify_cmd, capture_output=True, text=True, cwd=_WORK_DIR)
        native_exits[rf]["proposal_verify"] = vpproc.returncode
        proposals.append({
            "source": rf,
            "proposal": "results/" + proposal_name,
            "source_hash": _hash_input_file(rf),
            "proposal_hash": _hash_input_file(fp),
            "verified_canonical": vpproc.returncode == 0,
        })
    evidence.update({
        "checked_files": checked,
        "vhdl_files_not_applicable": vhdl_skipped,
        "unformatted_files": unformatted,
        "format_proposals": proposals,
        "proposal_errors": proposal_errors,
        "native_exit_codes": native_exits,
    })
    return evidence, len(unformatted)


def _check_authored(params):
    """Verify RTL the AGENT authored, and persist it only once it is checked.

    WHY THIS SCENARIO EXISTS
    ------------------------
    The agent's description claimed it "authors and reviews" RTL, but the tool
    had only three read-only analyses; there was no authoring path anywhere.
    The honest split is not to bolt a template generator onto this tool -- an
    algorithm cannot write the RTL a specification implies, and a generator that
    pretended to would produce code that elaborates and does the wrong thing.
    Authoring is the AGENT's job, where the judgement and the specification are.

    What was genuinely missing is the other half: nothing forced authored RTL
    through a check before it was handed on. This scenario closes that. It takes
    the RTL the agent just wrote, runs the SAME hygiene and reset analysis used
    on external RTL, and writes the file out only after it has been examined --
    so "the agent wrote some RTL" can never be reported as "the RTL is good".
    """
    top = params.get("top")
    if not top:
        return _cde(objective="check authored RTL", status="failed",
                    error="missing required field 'top'",
                    validation={"verdict": "fail"})
    if not params.get("rtl") and not params.get("rtl_files"):
        return _cde(
            objective="check authored RTL", status="failed",
            error=("no RTL supplied: pass the authored source as `rtl` "
                   "(inline) or `rtl_files`"),
            validation={"verdict": "fail",
                        "reason": ("this scenario CHECKS authored RTL; it does "
                                   "not generate any. The agent authors from "
                                   "the specification, then calls this to prove "
                                   "the result elaborates and is hygienic.")})

    # Canonical formatting is enforced at this authoring boundary, BEFORE
    # hygiene ever sees the text: inline RTL is normalized in place (there is
    # no external "source" for it to diverge from), while file-supplied RTL is
    # only ever verified -- the caller's file is evidence and must not be
    # mutated, so a non-canonical file gets a separate formatted PROPOSAL
    # instead of an in-place rewrite.
    effective_params = params
    canonical_format = {}
    unformatted_count = 0
    if params.get("rtl"):
        canonical_rtl, canonical_format = _normalize_authored_inline(
            params["rtl"], top)
        effective_params = dict(params)
        effective_params["rtl"] = canonical_rtl
    elif params.get("rtl_files"):
        canonical_format, unformatted_count = _verify_files_without_mutation(
            params["rtl_files"])

    if canonical_format.get("error"):
        return _cde(
            objective="check authored RTL", status="failed",
            error=canonical_format["error"],
            signoff={"canonical_format": canonical_format},
            validation={"verdict": "fail",
                        "reason": "canonical formatting could not be established"})
    res = _lint_hygiene(effective_params)

    # Persist the authored source next to its evidence, so the artifact and the
    # verdict that judged it travel together and a reviewer can see exactly
    # which text was checked. The NORMALIZED text is what gets saved -- saving
    # the pre-normalization original would let "the agent wrote some RTL" pass
    # as canonical when the file on disk is not.
    saved_name = None
    if effective_params.get("rtl"):
        saved_name = "%s.authored.v" % top
        saved_path = os.path.join(_OUTPUT_DIR, saved_name)
        with open(saved_path, "w", encoding="utf-8") as f:
            f.write(effective_params["rtl"])

    res["objective"] = "check agent-authored RTL for %s" % top
    sign = res.setdefault("signoff_evidence", {})
    sign["canonical_format"] = canonical_format
    sign["authored_rtl"] = {
        "saved_as": ("results/" + saved_name) if saved_name else None,
        "source": "agent_authored" if params.get("rtl") else "supplied_files",
        "note": ("Authoring is the agent's; this tool only VERIFIES. The verdict "
                 "beside this field is the hygiene result for exactly this "
                 "text -- authored RTL that has not been checked has no verdict "
                 "at all."),
    }
    res.setdefault("assumptions", []).append(
        "this scenario verifies agent-authored RTL; it never generates RTL, and "
        "a passing hygiene result attests to synthesizability and hygiene only, "
        "NOT to functional correctness against the specification")

    if unformatted_count:
        res.setdefault("results", {})["unformatted_files"] = {
            "value": unformatted_count, "unit": "count"}
        res["validation"] = {
            "verdict": "fail",
            "reason": (str(unformatted_count) + " file(s) not canonically "
                       "formatted; see signoff_evidence.canonical_format."
                       "format_proposals for verified proposals"),
        }
    return res


_SCENARIOS = {
    "elaborate": _elaborate,
    "lint_hygiene": _lint_hygiene,
    "cdc_scan": _cdc_scan,
    "check_authored": _check_authored,
}


def dispatch(params):
    scenario = params.get("scenario")
    if scenario not in _SCENARIOS:
        return _cde(objective="rtl design", status="failed",
                    error=f"unknown scenario '{scenario}'; supported: "
                          + ", ".join(_SCENARIOS),
                    validation={"verdict": "fail", "reason": "unknown scenario"})
    if not shutil.which("yosys"):
        return _cde(objective="rtl design", status="failed",
                    error="yosys not found on PATH (container build issue)",
                    validation={"verdict": "fail", "reason": "engine unavailable"})
    return _SCENARIOS[scenario](params)


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


# Pre-recovery image behavior retained for audit and rollback.
def _check_authored_image_legacy(params):
    """Verify RTL the AGENT authored, and persist it only once it is checked.

    WHY THIS SCENARIO EXISTS
    ------------------------
    The agent's description claimed it "authors and reviews" RTL, but the tool
    had only three read-only analyses; there was no authoring path anywhere.
    The honest split is not to bolt a template generator onto this tool -- an
    algorithm cannot write the RTL a specification implies, and a generator that
    pretended to would produce code that elaborates and does the wrong thing.
    Authoring is the AGENT's job, where the judgement and the specification are.

    What was genuinely missing is the other half: nothing forced authored RTL
    through a check before it was handed on. This scenario closes that. It takes
    the RTL the agent just wrote, runs the SAME hygiene and reset analysis used
    on external RTL, and writes the file out only after it has been examined --
    so "the agent wrote some RTL" can never be reported as "the RTL is good".
    """
    top = params.get("top")
    if not top:
        return _cde(objective="check authored RTL", status="failed",
                    error="missing required field 'top'",
                    validation={"verdict": "fail"})
    if not params.get("rtl") and not params.get("rtl_files"):
        return _cde(
            objective="check authored RTL", status="failed",
            error=("no RTL supplied: pass the authored source as `rtl` "
                   "(inline) or `rtl_files`"),
            validation={"verdict": "fail",
                        "reason": ("this scenario CHECKS authored RTL; it does "
                                   "not generate any. The agent authors from "
                                   "the specification, then calls this to prove "
                                   "the result elaborates and is hygienic.")})

    res = _lint_hygiene(params)

    # Persist the authored source next to its evidence, so the artifact and the
    # verdict that judged it travel together and a reviewer can see exactly
    # which text was checked.
    saved = None
    if params.get("rtl"):
        saved = os.path.join(_OUTPUT_DIR, "%s.authored.v" % top)
        try:
            with open(saved, "w", encoding="utf-8") as f:
                f.write(params["rtl"])
        except OSError as e:
            saved = None
            print("[" + str(TOOL) + "] could not save authored RTL: "
                  + str(e), flush=True)

    res["objective"] = "check agent-authored RTL for %s" % top
    sign = res.setdefault("signoff_evidence", {})
    sign["authored_rtl"] = {
        "saved_as": saved,
        "source": "agent_authored" if params.get("rtl") else "supplied_files",
        "note": ("Authoring is the agent's; this tool only VERIFIES. The verdict "
                 "beside this field is the hygiene result for exactly this "
                 "text -- authored RTL that has not been checked has no verdict "
                 "at all."),
    }
    res.setdefault("assumptions", []).append(
        "this scenario verifies agent-authored RTL; it never generates RTL, and "
        "a passing hygiene result attests to synthesizability and hygiene only, "
        "NOT to functional correctness against the specification")
    return res
