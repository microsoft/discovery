#!/usr/bin/env python3
"""
logic_synthesis_utils.py -- real Yosys logic-synthesis logic for the
chip-logic-synthesis tool.

Scenarios:
  generic_synth    -- elaborate + generic (technology-independent) optimization.
  technology_map   -- map RTL to the active PDK Liberty via ABC; extract QoR.
  retime           -- register retiming; report before/after estimated Fmax.

The tool shells out to the real `yosys` binary and parses its `stat` report. Node
constants (Liberty, don't-use list) are consumed from the PDK binding in the
params, never hard-coded. Results conform to the Common Design Envelope.
"""
import json
import math
import os
import re
import shutil
import subprocess
import time

TOOL = "logic-synthesis"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


def _is_ident(s):
    """True if *s* is a safe HDL/Tcl identifier -- blocks script injection via
    user-supplied module names interpolated into Yosys scripts."""
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
        progress = results.get("progress") or {}
        validation = results.get("validation") or {}
        if (progress.get("alignment_severity") == "blocking"
                and validation.get("verdict") in ("pass", "pass_with_caveats")):
            results.setdefault("signoff_evidence", {})["unclosed_acceptance_contract"] = dict(progress)
            validation["execution_verdict_before_acceptance_check"] = validation["verdict"]
            validation["verdict"] = "not_assessable"
            validation["acceptance_reason"] = (
                "Native mapping executed, but the declared acceptance/evidence "
                "contract is not closed: " + str(progress.get("alignment_detail")))
            results["validation"] = validation
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


# ---------------------------------------------------------------- CDE helper
def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    An envelope that stamps no `stage` resolves to no registry entry, reports NO
    METRIC, and a missing metric is indistinguishable downstream from a closed
    gate. The tool names its own gate rather than leaving it to the caller.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "synthesis"
    except Exception:
        return "synthesis"


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
        base.setdefault("basis", "agent_read_of_synthesis_log" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_synthesis_log")


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


def _cde(objective, status, results=None, signoff=None, qor=None,
         assumptions=None, pdk_binding=None, validation=None, provenance=None,
         inputs_ref=None, margin=None, error=None):
    env = {
        "tool": TOOL,
        "stage": _canonical_stage(),
        "status": status,  # completed | failed
        "objective": objective,
        "tools_used": [{"name": "Yosys", "version": _yosys_version()}],
        "pdk_binding": pdk_binding or "none",
        "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {},
        "vplan": "not_applicable",
        "results": results or {},
        "qor_metrics": qor or {},
        "signoff_evidence": signoff or {},
        "margin": margin or {"method": "synthesis_estimate",
                             "note": "signoff timing owned by STA agent"},
        "validation": validation or {"verdict": "review",
                                     "note": "estimated QoR, not signoff"},
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
    """Return a list of RTL file paths under the work dir (Verilog and/or VHDL)."""
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "design.v")
        with open(p, "w") as f:
            f.write(params["rtl"])
        files.append(p)
    for rf in params.get("rtl_files", []):
        if os.path.exists(rf):
            files.append(rf)
    if not files:
        raise ValueError("no RTL provided: supply 'rtl' (inline) or 'rtl_files'")
    return files


def _is_vhdl(path):
    return str(path).lower().endswith((".vhd", ".vhdl"))


def _read_block(files, top, params=None):
    """Build the Yosys read-in commands for a mixed Verilog/VHDL source set.

    Verilog/SystemVerilog sources use `read_verilog`. VHDL sources use the GHDL
    Yosys frontend, which is NOT auto-loaded -- so we load the plugin explicitly
    (`plugin -i ghdl`) and elaborate the top with `ghdl`. This makes VHDL ingest
    a first-class tool capability instead of forcing callers to hand-run a raw
    ghdl container (which fails with 'No such command: ghdl' when the plugin is
    unloaded)."""
    params = params or {}
    vhdl = [f for f in files if _is_vhdl(f)]
    verilog = [f for f in files if not _is_vhdl(f)]
    lines = []
    for f in verilog:
        lines.append(f"read_verilog {f}")
    if vhdl:
        std = str(params.get("vhdl_std", "08")).strip() or "08"
        # Load the GHDL plugin explicitly; a bare `ghdl` command fails otherwise.
        lines.append("plugin -i ghdl")
        lines.append(f"ghdl --std={std} " + " ".join(vhdl) + f" -e {top}")
    return "\n".join(lines)


def _run_yosys(script, timeout_s=None):
    """Run Yosys with a STREAMING log and a wall-clock timeout.

    Two reliability fixes learned from a decode-table synth that hung invisibly:
      * Stream stdout/stderr to /output/yosys.log live (line-buffered) so the
        current pass is observable WHILE the run is in flight, instead of only
        after the process returns. A caller/agent can tail the log to see
        progress ("Executing OPT_REDUCE pass ...") rather than guessing.
      * Enforce a wall-clock timeout (default 1800 s, override via the tool
        param `yosys_timeout_s`). A pass that blows up on a pathological cone
        (e.g. a huge PowerISA decode mux tree) now FAILS HONESTLY with the last
        observed pass recorded, instead of hanging past the turn budget with no
        output. 0/None disables the cap.
    """
    script_path = os.path.join(_OUTPUT_DIR, "synth.ys")
    with open(script_path, "w") as f:
        f.write(script)
    log_path = os.path.join(_OUTPUT_DIR, "yosys.log")
    t0 = time.time()
    _save_run_command(["yosys", "-s", script_path])
    # Line-buffered streaming so the log reflects live progress.
    with open(log_path, "w", buffering=1) as logf:
        proc = subprocess.Popen(
            ["yosys", "-l", log_path, "-s", script_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, cwd=_WORK_DIR)
        try:
            proc.wait(timeout=(timeout_s if timeout_s else None))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            elapsed = time.time() - t0
            # Recover the last executed pass from the streamed log for a precise,
            # actionable failure instead of a blind "hung".
            last_pass = "(unknown)"
            try:
                _passes = re.findall(r"Executing ([A-Z_0-9]+) pass", open(log_path).read())
                if _passes:
                    last_pass = _passes[-1]
            except OSError:
                pass
            raise RuntimeError(
                f"yosys exceeded the {timeout_s}s wall-clock cap and was killed "
                f"during the '{last_pass}' pass (elapsed {elapsed:.0f}s). This is "
                f"typically a pathological optimization cone (e.g. a large decode "
                f"mux tree). Consider hierarchy_mode=hierarchical (avoid -flatten), "
                f"raising yosys_timeout_s, or decomposing the offending module. "
                f"See yosys.log.")
    elapsed = time.time() - t0
    try:
        out = open(log_path).read()
    except OSError:
        out = ""
    if proc.returncode != 0:
        raise RuntimeError(f"yosys failed (rc={proc.returncode}); see yosys.log:\n"
                           + out[-2000:])
    return out, elapsed


def _parse_stat(text):
    """Parse a Yosys `stat` report for cell count and chip area.

    READ THE LAST STAT, NEVER THE FIRST. A technology_map run prints `stat`
    MORE THAN ONCE -- once over generic/unmapped cells and again after
    dfflibmap+abc+opt_clean. `re.search` returns the FIRST match, i.e. the
    PRE-MAPPING generic count, which is not the netlist anyone ships. Measured
    on crc16_ccitt: the log carried [108, 269, 269] and the envelope reported
    108 while the emitted netlist and synth_stat.rpt both had 269 real sky130
    instances. Chip area has only ONE occurrence (it is printed with -liberty),
    so area came from the FINAL stat -- the envelope therefore paired a
    pre-mapping cell count with a post-mapping area and was internally
    inconsistent, which is exactly what made it unblessable.
    Same defect class as the chip-routing DRC extractor that reported
    TritonRoute's iteration-1 violation count instead of the converged final.
    """
    cells = None
    area = None
    _c = re.findall(r"Number of cells:\s+(\d+)", text)
    if _c:
        cells = int(_c[-1])
    _a = re.findall(r"Chip area for module.*:\s+([0-9.]+)", text)
    if _a:
        area = float(_a[-1])
    return cells, area


def _parse_abc_delay_ps(text):
    """Extract ABC's mapped critical-path delay (picoseconds) from the yosys log.

    Yosys' `abc -liberty` pass forwards ABC's post-mapping summary, which reports
    the static critical-path delay against the Liberty cell timing, e.g.:

        ABC RESULTS:              Delay =  4970.00 ps
        ... Delay =  4970.00 ps ...

    This is a REAL cell-level Liberty delay (the same STA ABC uses to honor `-D`),
    NOT a structural proxy -- but it is a PRE-LAYOUT estimate: it carries no layout
    RC (wireload per the Liberty, typically `none` on sky130). Returns the LAST
    reported delay (the final mapped result) in ps, or None if no delay line is
    present (fail-honest -- the caller then records measurement:"unavailable", never
    a fabricated 0).
    """
    if not text:
        return None
    vals = re.findall(r"Delay\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*ps", text)
    if not vals:
        return None
    try:
        return float(vals[-1])
    except (TypeError, ValueError):
        return None


def _icg_cell_types(map_file):
    """Technology cells an ICG techmap file maps ONTO.

    A Yosys map file DEFINES replacement modules (`module \\$_DFFE_PP_ ...`) and
    INSTANTIATES the node's clock-gating cell inside them. The instantiated names
    that are not themselves defined in the file are the technology cells to look
    for in the mapped netlist.
    """
    try:
        with open(map_file, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return set()
    text = re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.S)
    defined = set(re.findall(r"\bmodule\s+([\\]?[\w$.]+)", text))
    instantiated = set(re.findall(r"^\s*([A-Za-z_][\w$]*)\s+[\\]?[\w$.]+\s*\(",
                                  text, re.M))
    keywords = {
        "module", "endmodule", "input", "output", "inout", "wire", "reg",
        "assign", "always", "initial", "parameter", "localparam", "generate",
        "endgenerate", "begin", "end", "if", "else", "case", "endcase",
        "function", "endfunction", "task", "endtask", "integer", "genvar",
        "supply0", "supply1", "tri", "logic", "signed", "unsigned", "for",
    }
    return {c for c in instantiated - defined if c.lower() not in keywords}


def _positive_finite_float(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def _target_period_ps(target_freq_mhz):
    target = _positive_finite_float(target_freq_mhz)
    if target is None:
        raise ValueError("target frequency must be positive and finite")
    return int(round(1.0e6 / target))


def _resolve_timing_target(params):
    """Resolve the ABC delay target, failing closed when timing intent is absent.

    Returns ``(target_freq_mhz, derivation, error)``.  An untimed map is legal only
    when explicitly requested with ``optimize: "area"``; omission defaults to a
    timing-driven map and therefore needs either ``target_freq_mhz`` or
    ``sdc_constants``.
    """
    params = params or {}
    optimize = str(params.get("optimize", "timing")).strip().lower()
    deriv = {
        "source": None,
        "clock_period_ns": None,
        "effective_period_ns": None,
        "deductions_ns": {},
        "note": "",
    }

    explicit = _positive_finite_float(params.get("target_freq_mhz"))
    if explicit is not None:
        period = round(1000.0 / explicit, 4)
        deriv.update({
            "source": "explicit target_freq_mhz",
            "clock_period_ns": period,
            "effective_period_ns": period,
            "note": ("explicit target_freq_mhz used as stated; sdc_constants, "
                     "if present, do not narrow an explicitly supplied target"),
        })
        return explicit, deriv, None
    if "target_freq_mhz" in params and params.get("target_freq_mhz") is not None:
        return None, deriv, (
            "target_freq_mhz must be a positive finite MHz value; supply a valid "
            "target_freq_mhz, provide sdc_constants, or set optimize='area' for "
            "an explicitly untimed map")

    sdc = params.get("sdc_constants")
    if not isinstance(sdc, dict):
        if optimize == "area":
            deriv.update({
                "source": "explicit optimize=area",
                "note": "explicit area optimization requested; no timing target resolved",
            })
            return None, deriv, None
        return None, deriv, (
            "technology_map defaults to optimize='timing' and requires timing "
            "intent. Provide target_freq_mhz or sdc_constants, or set "
            "optimize='area' for an explicitly untimed map")

    clock = sdc.get("clock") if isinstance(sdc.get("clock"), dict) else {}
    period_ns = _positive_finite_float(clock.get("period_ns"))
    if period_ns is None:
        freq = _positive_finite_float(clock.get("frequency_mhz"))
        if freq is not None:
            period_ns = 1000.0 / freq
    if period_ns is None:
        return None, deriv, (
            "sdc_constants must include clock.period_ns or clock.frequency_mhz "
            "as a positive finite value; otherwise no target_freq_mhz can be "
            "derived")

    deductions = {}
    unc = sdc.get("clock_uncertainty_ns")
    if isinstance(unc, dict):
        setup = _positive_finite_float(unc.get("setup"))
        if setup is not None:
            deductions["setup_uncertainty"] = setup
    io = sdc.get("io_delay_ns")
    if isinstance(io, dict):
        for key in ("input_max", "output_max"):
            val = _positive_finite_float(io.get(key))
            if val is not None:
                deductions[key] = val

    effective = period_ns - sum(deductions.values())
    clock_period = round(period_ns, 4)
    effective_period = round(effective, 4)
    deriv.update({
        "source": "sdc_constants",
        "clock_period_ns": clock_period,
        "deductions_ns": {k: round(v, 4) for k, v in deductions.items()},
        "effective_period_ns": effective_period,
    })
    if effective <= 0:
        return None, deriv, (
            "sdc_constants consume the whole clock period; no positive budget "
            "remains for internal logic after setup uncertainty and I/O delay")

    if deductions:
        deriv["note"] = (
            "derived from sdc_constants clock period minus term-by-term setup "
            "uncertainty and I/O delay deductions")
    else:
        deriv["note"] = (
            "sdc_constants supplied no setup uncertainty or I/O budget, so the "
            "full clock period is used; this is optimistic if external budgets "
            "exist but were not provided")
    return 1000.0 / effective, deriv, None


def _estimate_timing(out, params, target_freq_mhz=None):
    """Pre-layout setup-timing estimate for the mapped netlist.

    Combines the ABC critical-path delay (cell-level Liberty timing at the mapping
    corner) with the target clock period to produce a genuine synthesis-grade
    estimate the downstream gate can key on. Distinct from signoff STA (chip-sta,
    which loads real per-corner SPEF); this is the shift-left check that catches a
    logic-depth timing wall while it is still an in-place resynthesis (rung-1) fix.

    A slow (ss) corner Liberty SHOULD be used for the mapping when a setup estimate
    is wanted -- the corner is recorded so a tt-corner estimate is never mistaken
    for a slow-corner signoff.

    Returns a dict (always -- never raises); estimated_wns_ns is None with
    measurement:"unavailable" when ABC printed no parseable delay.
    """
    delay_ps = _parse_abc_delay_ps(out)
    # Target clock period (ns) from target_freq_mhz; None when not timing-driven.
    period_ns = None
    tf = target_freq_mhz if target_freq_mhz is not None else params.get("target_freq_mhz")
    try:
        tf_val = _positive_finite_float(tf)
        if tf_val is not None:
            period_ns = 1.0e3 / tf_val  # MHz -> ns
    except (TypeError, ValueError):
        period_ns = None
    # Optional user-supplied wireload derate (>1.0 adds pre-layout pessimism for
    # the RC the netlist does not yet carry). Never fabricated; defaults to 1.0.
    try:
        derate = float(params.get("wireload_derate", 1.0))
        if derate <= 0:
            derate = 1.0
    except (TypeError, ValueError):
        derate = 1.0

    corner = params.get("corner")
    lib = params.get("liberty") or (params.get("pdk_binding") or {}).get("liberty")
    lib_name = os.path.basename(lib) if isinstance(lib, str) else None
    is_slow = bool(lib_name and ("ss_" in lib_name or "slow" in lib_name.lower())) \
        or bool(corner and ("ss" in str(corner).lower() or "slow" in str(corner).lower()))

    if delay_ps is None:
        return {
            "measurement": "unavailable",
            "note": "ABC printed no parseable critical-path delay; timing estimate "
                    "not produced (fail-honest, not fabricated).",
            "corner": corner, "corner_is_slow": is_slow,
        }

    delay_ns = (delay_ps / 1000.0) * derate
    fmax_mhz = (1000.0 / delay_ns) if delay_ns > 0 else None
    wns_ns = (period_ns - delay_ns) if period_ns is not None else None
    return {
        "measurement": "synthesis_estimate",
        "engine": "ABC (Liberty cell-delay static timing)",
        "critical_path_delay_ns": round(delay_ns, 4),
        "critical_path_delay_ps_raw": round(delay_ps, 2),
        "wireload_derate": derate,
        "wireload_model": "per-Liberty (sky130 hd Liberty carries none; cell-delay only)",
        "target_period_ns": (round(period_ns, 4) if period_ns is not None else None),
        "estimated_wns_ns": (round(wns_ns, 4) if wns_ns is not None else None),
        "estimated_fmax_mhz": (round(fmax_mhz, 4) if fmax_mhz is not None else None),
        "setup_nonneg": (bool(wns_ns >= 0) if wns_ns is not None else None),
        "corner": corner,
        "corner_liberty": lib_name,
        "corner_is_slow": is_slow,
        "basis": "pre-layout, no SPEF/RC; propagated-ideal clock implied by ABC. "
                 "Signoff-grade SDC-aware STA (real clock period + uncertainty + I/O "
                 "delays, multi-corner, SPEF) is owned by the chip-sta agent, which "
                 "runs as a dedicated pre-layout STA stage right after synthesis.",
    }


def _timeout_from(params):
    """Resolve the Yosys wall-clock cap (seconds) from params; default 1800.
    `yosys_timeout_s: 0` disables the cap."""
    v = (params or {}).get("yosys_timeout_s", 1800)
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 1800
    return v if v > 0 else None


# ---------------------------------------------------------------- scenarios
def _generic_synth(params):
    top = params["top"]
    files = _stage_rtl(params)
    reads = _read_block(files, top, params)
    # hierarchy_mode steers whether module boundaries are dissolved. `flat`
    # (default) matches the historical behavior (flatten for best QoR); on
    # `hierarchical` we preserve boundaries so downstream hierarchical
    # assembly / block-level flows can keep their partitions.
    _hier = str(params.get("hierarchy_mode", "flat")).strip().lower()
    _flatten_line = "proc; flatten; opt" if _hier != "hierarchical" else "proc; opt"
    script = f"""{reads}
hierarchy -check -top {top}
{_flatten_line}
synth -top {top}
stat
tee -o {os.path.join(_OUTPUT_DIR, 'synth_stat.rpt')} stat
write_json {os.path.join(_OUTPUT_DIR, 'netlist_generic.json')}
"""
    out, elapsed = _run_yosys(script, timeout_s=_timeout_from(params))
    cells, area = _parse_stat(out)
    return _cde(
        objective=f"generic synthesis of {top}",
        status="completed",
        results={"cell_count": {"value": cells, "unit": "count"}},
        qor={"cell_count": cells},
        signoff={"stage": "pre-map generic", "netlist": "netlist_generic.json"},
        inputs_ref={"rtl_files": files},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "yosys.log"},
        assumptions=["technology-independent estimate; not mapped to a library"],
    )


def _scan_stitch(netlist_v, scan_v, top, lib_path, params):
    """Swap non-scan D-flops for their scan-equivalent master and STITCH balanced
    scan chains on an already-mapped netlist, emitting a scan-ready netlist. Same
    method as the chip-dft scan_insert primitive: the functional CLK/D/Q pins are
    identical across the swap, so only the scan data/enable pins are added and
    wired (scan-data <- prev Q / scan_in_<c>, tail Q -> scan_out_<c>, all
    scan-enable <- scan_enable). Runs Yosys write_json -> Python stitch ->
    read_json + write_verilog. Returns a metrics dict, or raises RuntimeError on
    failure (fail-closed).

    NODE CONSTANTS ARE NOT DEFAULTED. This function previously fell back to
    `sky130_fd_sc_hd__dfxtp_1` / `__sdfxtp_1` with pins `SCD`/`SCE` -- the same
    silent-default defect as `chip-dft._scan_mappings`, and just as dangerous:
    correct on sky130, and on nangate45 (`DFF_X1` -> `SDFF_X1`, pins `SI`/`SE`)
    it silently stitches nothing while reporting success. Scan masters and scan
    pin names come from the hashed binding or an explicit caller parameter, or
    the stage fails closed.
    """
    _bind = params.get("pdk_binding") or {}
    if not isinstance(_bind, dict):
        _bind = {}
    # A binding-supplied mapping is the preferred source: it is the same object
    # chip-dft consumes, so the two stages cannot disagree about the node.
    _mapping = {}
    _raw = _bind.get("scan_cell_mappings")
    if isinstance(_raw, list) and _raw and isinstance(_raw[0], dict):
        _mapping = _raw[0]
    from_cell = (params.get("scan_from_cell")
                 or _mapping.get("from_cell"))
    to_cell = (params.get("scan_to_cell")
               or _mapping.get("to_cell")
               or _bind.get("scan_cell"))
    scd_pin = params.get("scan_data_pin") or _mapping.get("scan_data_pin")
    sce_pin = params.get("scan_enable_pin") or _mapping.get("scan_enable_pin")
    q_pin = params.get("ff_q_pin") or _mapping.get("q_pin")
    _absent = [name for name, value in (
        ("scan_from_cell", from_cell), ("scan_to_cell", to_cell),
        ("scan_data_pin", scd_pin), ("scan_enable_pin", sce_pin),
        ("ff_q_pin", q_pin)) if not value]
    if _absent:
        raise RuntimeError(
            "scan stitch is unresolved: missing %s. Scan-cell masters and scan "
            "pin names are NODE constants (sky130 uses SCD/SCE, nangate45 uses "
            "SI/SE) and must come from the hashed PDK binding "
            "(`scan_cell_mappings`) or an explicit caller parameter. This tool "
            "no longer defaults them, because on a non-sky130 node a defaulted "
            "value stitches nothing while reporting success."
            % ", ".join(_absent))
    _ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
    for _id in (top, from_cell, to_cell, scd_pin, sce_pin, q_pin):
        if not _ident.match(str(_id)):
            raise RuntimeError(f"invalid identifier for scan insertion: {_id!r}")
    js = os.path.join(_WORK_DIR, "scan_pre.json")
    pre = (f"read_liberty -lib {lib_path}\n"
           f"read_verilog {netlist_v}\n"
           f"hierarchy -check -top {top}\nflatten\nwrite_json {js}\n")
    _run_yosys(pre, timeout_s=_timeout_from(params))
    net = json.load(open(js))
    modname = top if top in net["modules"] else next(iter(net["modules"]))
    mod = net["modules"][modname]
    cells = mod.get("cells", {})
    mod.setdefault("ports", {})
    mod.setdefault("netnames", {})
    max_bit = [1]

    def _walk_bits(node):
        if isinstance(node, list):
            for b in node:
                if isinstance(b, int) and b > max_bit[0]:
                    max_bit[0] = b
        elif isinstance(node, dict):
            for v in node.values():
                _walk_bits(v)
    for c in cells.values():
        _walk_bits(c.get("connections", {}))
    for pr in mod["ports"].values():
        _walk_bits(pr.get("bits", []))
    _next = [max_bit[0] + 1]

    def _new_net():
        b = _next[0]
        _next[0] += 1
        return b
    # Mutual-exclusion guard: refuse to double-insert if the mapped netlist already
    # carries scan cells (a prior scan pass). Scan insertion must happen once.
    _pre = [n for n, c in cells.items()
            if c.get("type") == to_cell
            or re.search(r"__s[a-z]*df[a-z]*tp", str(c.get("type", "")).lower())]
    if _pre:
        raise RuntimeError(
            f"mapped netlist already contains {len(_pre)} scan cells; refusing to "
            "double-insert (scan insertion must happen exactly once — disable one of "
            "the synthesis-fused or DFT-stage scan paths).")
    scan_cells = sorted(n for n, c in cells.items()
                        if c.get("type") == from_cell)
    if not scan_cells:
        raise RuntimeError(
            f"no '{from_cell}' flops in mapped netlist; nothing to stitch "
            "(is dfflibmap producing a different flop master?)")
    import math
    try:
        n_chains = max(1, int(params.get("scan_chains", 0)))
    except (TypeError, ValueError):
        n_chains = 0
    if not n_chains:
        n_chains = max(1, math.ceil(len(scan_cells) / 800.0))
    n_chains = min(n_chains, len(scan_cells))
    sce_net = _new_net()
    mod["ports"]["scan_enable"] = {"direction": "input", "bits": [sce_net]}
    mod["netnames"]["scan_enable"] = {"hide_name": 0, "bits": [sce_net],
                                      "attributes": {}}
    chains = [[] for _ in range(n_chains)]
    for i, cname in enumerate(scan_cells):
        chains[i % n_chains].append(cname)
    swapped, max_len = 0, 0
    for ci, chain in enumerate(chains):
        if not chain:
            continue
        max_len = max(max_len, len(chain))
        si_net = _new_net()
        mod["ports"][f"scan_in_{ci}"] = {"direction": "input", "bits": [si_net]}
        mod["netnames"][f"scan_in_{ci}"] = {"hide_name": 0, "bits": [si_net],
                                            "attributes": {}}
        prev_src, last_q = si_net, None
        for cname in chain:
            c = cells[cname]
            c["type"] = to_cell
            conn = c.setdefault("connections", {})
            conn[scd_pin] = [prev_src]
            conn[sce_pin] = [sce_net]
            pd = c.setdefault("port_directions", {})
            pd[scd_pin] = "input"
            pd[sce_pin] = "input"
            qbits = conn.get(q_pin)
            if not qbits:
                raise RuntimeError(f"flop {cname!r} has no '{q_pin}' pin; cannot stitch")
            prev_src = qbits[0]
            last_q = qbits[0]
            swapped += 1
        mod["ports"][f"scan_out_{ci}"] = {"direction": "output", "bits": [last_q]}
    js2 = os.path.join(_WORK_DIR, "scan_post.json")
    json.dump(net, open(js2, "w"))
    # The pre-scan JSON already carries every Liberty cell as a blackbox module,
    # so it is self-contained — do NOT re-read Liberty on emit (Yosys would error
    # "Re-definition of module <scan cell>").
    post = (f"read_json {js2}\nhierarchy -check -top {modname}\n"
            f"write_verilog -noattr {scan_v}\nstat\n")
    _run_yosys(post, timeout_s=_timeout_from(params))
    if not os.path.exists(scan_v) or os.path.getsize(scan_v) == 0:
        raise RuntimeError("scan netlist did not emit")
    emitted = open(scan_v, "r", encoding="utf-8", errors="replace").read()
    emitted_scan_cells = len(re.findall(r"\b" + re.escape(to_cell) + r"\b", emitted))
    if emitted_scan_cells < swapped or swapped < 1:
        raise RuntimeError(
            f"scan netlist has {emitted_scan_cells} scan cells; expected >= {swapped}")
    return {"flops_swapped": swapped, "scan_chains": n_chains,
            "max_chain_length": max_len, "scan_from_cell": from_cell,
            "scan_to_cell": to_cell, "scan_data_pin": scd_pin,
            "scan_enable_pin": sce_pin,
            "scan_cells_in_emitted_netlist": emitted_scan_cells,
            "scan_netlist": os.path.basename(scan_v),
            "scan_ports": ["scan_enable"]
            + [f"scan_in_{i}" for i in range(n_chains)]
            + [f"scan_out_{i}" for i in range(n_chains)]}


def _technology_map(params):
    top = params["top"]
    liberty = params.get("liberty") or (params.get("pdk_binding") or {}).get("liberty")
    if not liberty:
        return _cde(
            objective=f"technology map of {top}",
            status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            error="missing Liberty: technology_map requires a PDK-binding Liberty "
                  "reference (params.liberty or pdk_binding.liberty)",
            validation={"verdict": "fail", "reason": "no node Liberty"},
        )
    # Liberty may be inline text or a path.
    lib_path = liberty
    if "\n" in liberty or liberty.strip().startswith("library"):
        lib_path = os.path.join(_WORK_DIR, "node.lib")
        with open(lib_path, "w") as f:
            f.write(liberty)
    if not os.path.exists(lib_path):
        return _cde(objective=f"technology map of {top}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=f"Liberty not found: {lib_path}",
                    validation={"verdict": "fail", "reason": "Liberty missing"})

    files = _stage_rtl(params)
    reads = _read_block(files, top, params)
    netlist = os.path.join(_OUTPUT_DIR, "netlist_mapped.v")
    # `optimize` steers ABC technology mapping. Omission is timing-driven and
    # therefore MUST resolve a delay target; an untimed map is reachable only via
    # explicit `optimize: "area"`.
    optimize = str(params.get("optimize", "timing")).strip().lower()
    _resolved_target, _target_deriv, _target_error = _resolve_timing_target(
        dict(params, optimize=optimize))
    if _target_error:
        return _cde(
            objective=f"technology map of {top}", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            error=_target_error,
            validation={"verdict": "fail", "reason": "timing target unresolved"},
            signoff={"optimize": optimize, "timing_target_derivation": _target_deriv},
        )
    _abc = f"abc -liberty {lib_path}"
    _abc_note = "explicit area ABC mapping (untimed, node-validated)"
    if optimize != "area":
        _period_ps = _target_period_ps(_resolved_target)  # MHz -> ps clock period
        # Delay-driven map that ALSO prints ABC's Liberty static-timing summary
        # ("... Delay = <ps> ...") via `stime`, so the tool can report a real
        # pre-layout critical-path estimate. The script is QUOTED so yosys passes
        # it to abc as one token (the `;` are abc command separators, not yosys
        # ones). `topo` only reorders (no logic change); `stime` only reports.
        _abc = (f'abc -liberty {lib_path} '
                f'-script "+strash;dch;map;topo;stime" -D {_period_ps}')
        _abc_note = (f"delay-targeted ABC mapping (-D {_period_ps} ps) "
                     f"with stime critical-path report; target source: "
                     f"{_target_deriv.get('source')}")
    # Advanced ABC passthroughs (opt-in). `abc_script` supplies a custom ABC
    # command script (file path or "+cmd;cmd" inline form); `abc_constr`
    # supplies an ABC timing-constraint file. Both override/augment the levers
    # above and are recorded for provenance.
    _abc_script = params.get("abc_script")
    if _abc_script:
        _abc = f"{_abc} -script {_abc_script}"
        _abc_note += f"; custom abc_script={_abc_script}"
    _abc_constr = params.get("abc_constr")
    if _abc_constr:
        _abc = f"{_abc} -constr {_abc_constr}"
        _abc_note += f"; abc_constr={_abc_constr}"
    # hierarchy_mode: `flat` (default) flattens for best mapped QoR;
    # `hierarchical` preserves module boundaries for block-level / SoC flows.
    _hier = str(params.get("hierarchy_mode", "flat")).strip().lower()
    _synth_line = (f"synth -top {top} -flatten" if _hier != "hierarchical"
                   else f"synth -top {top}")
    # --- CLOCK-GATE INFERENCE (opt-in) ---------------------------------------
    # Folds enable-driven registers behind an integrated clock-gating cell, so the
    # clock stops toggling for a register bank that is not being written. This is
    # the single largest DYNAMIC-power lever available at synthesis: clock nets
    # switch every cycle by definition, and the clock tree is typically the
    # highest-activity net in the design.
    #
    # *** MECHANISM, VERIFIED AGAINST THE BOUND ENGINE, NOT ASSUMED. *** The bound
    # Yosys (0.36+42) has NO `clkgate`/`clockgate` pass -- both were probed inside
    # the packaged image and report "No such command". The only working route is a
    # techmap MAP FILE that rewrites gated-enable flops onto the node's ICG cell,
    # which is exactly what ORFS drives via `CLKGATE_MAP_FILE`. So the map file is
    # REQUIRED rather than optional: there is no library-inference fallback to
    # degrade to, and emitting a non-existent command would fail the whole run.
    #
    # Deliberately OFF by default. Gating rewrites the clock structure, so it must
    # sit behind the post-synthesis LEC checkpoint the flow already runs.
    _clkgate_line = ""
    _clkgate_info = None
    if str(params.get("infer_clock_gates", "")).lower() in ("1", "true", "yes", "on"):
        _icg_map = (params.get("clock_gate_map_file")
                    or (params.get("pdk_binding") or {}).get("clock_gate_map_file"))
        if not _icg_map:
            return _cde(
                objective=f"technology map of {top}", status="failed",
                pdk_binding=params.get("pdk_binding", "none"),
                error=("infer_clock_gates requires 'clock_gate_map_file' -- a Yosys "
                       "techmap map file that rewrites enable-gated flops onto the "
                       "node's integrated clock-gating cell. The bound Yosys "
                       "(0.36) has no clkgate/clockgate pass, so there is no "
                       "library-inference fallback; without the map file this "
                       "would report a power optimization it never performed."),
                validation={"verdict": "fail", "reason": "no ICG techmap file"})
        if not os.path.exists(str(_icg_map)):
            return _cde(objective=f"technology map of {top}", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"clock_gate_map_file not found: {_icg_map}",
                        validation={"verdict": "fail"})
        _clkgate_line = "techmap -map %s\n" % _icg_map
        _clkgate_info = {"method": "yosys techmap -map (ICG rewrite)",
                         "map_file": str(_icg_map),
                         "verify": ("post-synthesis LEC must prove the gated "
                                    "netlist equivalent to RTL -- clock gating "
                                    "changes the clock structure")}
    script = f"""{reads}
hierarchy -check -top {top}
{_synth_line}
{_clkgate_line}dfflibmap -liberty {lib_path}
{_abc}
opt_clean
stat -liberty {lib_path}
tee -o {os.path.join(_OUTPUT_DIR, 'synth_stat.rpt')} stat -liberty {lib_path}
write_verilog {netlist}
"""
    out, elapsed = _run_yosys(script, timeout_s=_timeout_from(params))
    cells, area = _parse_stat(out)

    # Pre-layout setup-timing estimate: ABC Liberty cell-delay critical path vs the
    # target clock period. This is a shift-left sanity number (no SDC uncertainty/IO,
    # no SPEF) that catches a logic-depth timing wall while it is still a rung-1
    # resynthesis fix. The AUTHORITATIVE SDC-aware pre-layout STA runs as a dedicated
    # chip-sta stage right after synthesis. Emits estimated_wns / estimated_fmax, or
    # measurement:"unavailable" (never a fabricated 0).
    timing = _estimate_timing(out, params, target_freq_mhz=_resolved_target)

    # OPTIONAL: fold scan insertion into synthesis so the mapped netlist is BORN
    # scan-ready (scan_insert: true). Swaps dfflibmap's D-flops for the scan master
    # + stitches chains, emitting netlist_mapped.scan.v; downstream then consumes a
    # scan-inserted netlist directly (no separate insertion pass). Fail-closed: any
    # stitch error fails the stage rather than silently shipping a non-scan netlist.
    scan_info = None
    scan_error = None
    if str(params.get("scan_insert", "")).lower() in ("1", "true", "yes", "on"):
        scan_v = os.path.join(_OUTPUT_DIR, "netlist_mapped.scan.v")
        try:
            scan_info = _scan_stitch(netlist, scan_v, top, lib_path, params)
        except Exception as _se:
            scan_error = str(_se)
    dont_use = params.get("dont_use") or (params.get("pdk_binding") or {}).get("dont_use") or []
    violations = []
    if dont_use and os.path.exists(netlist):
        netlist_text = open(netlist).read()
        for cell in dont_use:
            if re.search(r"\b" + re.escape(cell) + r"\b", netlist_text):
                violations.append(cell)

    # A `techmap -map` that matches nothing runs cleanly and changes nothing. So
    # COUNT the ICG cells that actually reached the netlist instead of reporting
    # the request as though it were an outcome -- otherwise the envelope claims a
    # power optimization the run never performed.
    if _clkgate_info and os.path.exists(netlist):
        icg_types = _icg_cell_types(_clkgate_info["map_file"])
        text = open(netlist, encoding="utf-8", errors="replace").read()
        counts = {c: len(re.findall(r"\b%s\b\s+[\\\w]" % re.escape(c), text))
                  for c in icg_types}
        counts = {c: n for c, n in counts.items() if n}
        total = sum(counts.values())
        _clkgate_info["icg_cells_inserted"] = total
        _clkgate_info["icg_cell_types"] = counts or None
        _clkgate_info["applied"] = bool(total)
        if not total:
            # Not a failure: a design with no enable-gated flops legitimately
            # gets zero. But it must never read as "clock gating was applied".
            _clkgate_info["note"] = (
                "clock gating was REQUESTED but NO ICG cell reached the netlist "
                "(candidate cells from the map file: %s). Either the design has "
                "no enable-gated flops, or the map file does not match this "
                "design's flop patterns. Treat this run as UNGATED."
                % (", ".join(sorted(icg_types)) or "none identifiable"))

    # VERDICT. `pass_with_caveats` is deliberately NOT a blessable verdict
    # (gen_campaign_versions PASSING_VERDICTS = {pass, waived, not_applicable}),
    # so emitting it UNCONDITIONALLY -- as this function used to -- made the
    # synthesis gate STRUCTURALLY UNCLOSABLE: no input, however clean, could ever
    # produce a blessable result. That is not conservatism, it is a deadlock, and
    # it is indistinguishable from a real caveat to everyone downstream.
    # So: enumerate the caveats EXPLICITLY. No caveats => plain `pass`. Any caveat
    # => `pass_with_caveats` AND the reason is recorded, so a human can see WHY it
    # is not blessable instead of guessing.
    caveats = []
    if timing.get("measurement") == "unavailable":
        caveats.append(
            "pre-layout timing estimate unavailable (%s); synthesis QoR carries "
            "no timing number -- the authoritative check is the chip-sta stage"
            % (timing.get("reason") or "no ABC delay data"))
    if _clkgate_info and not _clkgate_info.get("applied"):
        caveats.append(
            "clock gating was requested but no ICG cell reached the netlist; "
            "treat this run as UNGATED")
    if cells is None or area is None:
        caveats.append(
            "could not parse final cell count and/or chip area from the Yosys "
            "stat report -- QoR numbers are incomplete")

    status = "completed"
    verdict = "pass" if not caveats else "pass_with_caveats"
    if violations:
        status = "failed"
        verdict = "fail"
    # A requested scan insertion that failed to stitch/emit fails the stage — never
    # silently ship a non-scan netlist when scan was asked for.
    if scan_error:
        status = "failed"
        verdict = "fail"

    target = _resolved_target
    _est_wns = timing.get("estimated_wns_ns")
    _est_fmax = timing.get("estimated_fmax_mhz")
    return _cde(
        objective=f"technology map of {top} to node library",
        status=status,
        pdk_binding=params.get("pdk_binding", "none"),
        # (A) GATING -- `dont_use_violations` is the ONE gate this tool owns and
        # measures itself: a banned cell found in the emitted netlist must reach
        # zero. The PPA numbers below are deliberately NOT gating.
        results={
            "dont_use_violations": {
                "value": len(violations), "unit": "count",
                "class": "gating", "basis": "counted_from_emitted_netlist",
                "closes_at": "== 0",
                "note": ("Banned cells found in netlist_mapped.v. Counted from "
                         "the EMITTED netlist, not from the request. A null "
                         "means NOT ASSESSED and must never read as zero.")},
            "cell_area": {
                "value": area, "unit": "um^2",
                "class": "diagnostic", "basis": "parsed_yosys_stat_output",
                "note": "PPA outcome, not a gate; budget adjudication is elsewhere"},
            "cell_count": {
                "value": cells, "unit": "count",
                "class": "diagnostic", "basis": "parsed_yosys_stat_output",
                "note": ("Read from the FINAL stat emission, not the first: a "
                         "technology_map run prints stat three times and the "
                         "first is the PRE-MAPPING generic count.")},
            "estimated_wns": {
                "value": _est_wns, "unit": "ns",
                "class": "diagnostic", "basis": "synthesis_internal_estimate",
                "note": ("PRE-LAYOUT -- this tool uses only the resolved target "
                         "budget and no parasitics. It is a sanity number, NEVER "
                         "signoff. Gating on it would launder a timing claim "
                         "the run cannot support; chip-sta is the authoritative "
                         "owner.")},
            "estimated_fmax": {
                "value": _est_fmax, "unit": "MHz",
                "class": "diagnostic", "basis": "synthesis_internal_estimate",
                "note": "same SDC-unaware caveat as estimated_wns"},
        },
        qor={"cell_area_um2": area, "cell_count": cells,
             "target_freq_mhz": target,
             "estimated_wns_ns": _est_wns, "estimated_fmax_mhz": _est_fmax},
        signoff={
            "netlist": "netlist_mapped.v",
            "liberty": os.path.basename(lib_path),
            "corner": params.get("corner"),
            "optimize": optimize,
            "optimize_effect": _abc_note,
            "hierarchy_mode": _hier,
            "dont_use_violations": violations,
            "timing_estimate": timing,
            "timing_target_derivation": _target_deriv,
            # (B) DIAGNOSTIC -- measured, non-gating. Names WHICH banned cells
            # appeared and what the run actually did, which is the repair surface.
            "diagnostics": {
                "class": "diagnostic", "basis": "counted_from_emitted_netlist",
                "dont_use_cells_found": violations,
                "cell_count": cells, "cell_area_um2": area,
                "caveats": caveats,
                "clock_gating_applied": bool(
                    (_clkgate_info or {}).get("applied")),
                "scan_error": scan_error},
            # (C) DESCRIPTIVE -- run configuration, expected to hold steady.
            "descriptive": {
                "class": "descriptive", "basis": "run_configuration",
                "top": top, "liberty": os.path.basename(lib_path),
                "corner": params.get("corner"), "optimize": optimize,
                "hierarchy_mode": _hier, "target_freq_mhz": target,
                "requested_target_freq_mhz": params.get("target_freq_mhz"),
                "engine": "yosys+abc"},
            # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
            "interpretation": _labelled_interpretation(
                params.get("interpretation")),
            "interpretation_crosscheck": _crosscheck_interpretation(
                params.get("interpretation"), len(violations),
                "dont_use_violations"),
            "scan_insert_requested": bool(
                str(params.get("scan_insert", "")).lower()
                in ("1", "true", "yes", "on")),
            "scan_insertion": scan_info,
            "scan_netlist": (scan_info or {}).get("scan_netlist") if scan_info else None,
            "scan_error": scan_error,
            "clock_gating": _clkgate_info,
            # A pass_with_caveats verdict must NAME its caveats. An unexplained
            # caveat is indistinguishable from a tool defect and blocks blessing
            # with no actionable reason.
            "caveats": caveats,
        },
        inputs_ref={"rtl_files": files, "liberty": lib_path},
        assumptions=[
            "wireload/no-parasitics: pre-layout estimate",
            "estimated timing is a synthesis estimate; signoff STA owned by the "
            "Static Timing Analysis agent",
        ],
        margin=timing,
        validation={"verdict": verdict,
                    "caveats": caveats,
                    "dont_use_respected": not violations},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "yosys.log"},
    )


def _retime(params):
    top = params["top"]
    liberty = params.get("liberty") or (params.get("pdk_binding") or {}).get("liberty")
    files = _stage_rtl(params)
    reads = _read_block(files, top, params)
    # Retiming in Yosys is performed by ABC (`abc -dff`) on a mapped netlist, NOT
    # by a `synth -retime` flag (that flag does not exist in the packaged Yosys).
    # With a Liberty we map to the library and let ABC do sequential/retiming
    # optimization; without one we fall back to a generic synth and report that
    # true retiming was not performed (fail-honest, no fabricated "retimed" claim).
    lib_path = liberty if liberty and os.path.exists(str(liberty)) else None
    if lib_path:
        script = f"""{reads}
hierarchy -check -top {top}
synth -top {top} -flatten
dfflibmap -liberty {lib_path}
abc -liberty {lib_path} -dff
opt_clean
stat -liberty {lib_path}
"""
        retimed = True
    else:
        script = f"""{reads}
hierarchy -check -top {top}
synth -top {top} -flatten
stat
"""
        retimed = False
    out, elapsed = _run_yosys(script, timeout_s=_timeout_from(params))
    cells, area = _parse_stat(out)
    assumptions = ["retiming moves registers; verify equivalence with the LEC agent"]
    if not retimed:
        assumptions.append(
            "no Liberty supplied: reported a generic synth estimate; true "
            "sequential retiming (abc -dff) requires a PDK-binding Liberty")
    return _cde(
        objective=f"retiming of {top}",
        status="completed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"cell_count": {"value": cells, "unit": "count"},
                 "cell_area": {"value": area, "unit": "um^2"}},
        qor={"cell_count": cells, "cell_area_um2": area, "retimed": retimed},
        inputs_ref={"rtl_files": files},
        assumptions=assumptions,
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "yosys.log"},
    )


_SCENARIOS = {
    "generic_synth": _generic_synth,
    "technology_map": _technology_map,
    "retime": _retime,
}


def dispatch(params):
    scenario = params.get("scenario")
    if scenario not in _SCENARIOS:
        return _cde(objective="logic synthesis", status="failed",
                    error=f"unknown scenario '{scenario}'; supported: "
                          + ", ".join(_SCENARIOS),
                    validation={"verdict": "fail", "reason": "unknown scenario"})
    if not shutil.which("yosys"):
        return _cde(objective="logic synthesis", status="failed",
                    error="yosys not found on PATH (container build issue)",
                    validation={"verdict": "fail", "reason": "engine unavailable"})
    _top = params.get("top")
    if not _is_ident(_top):
        return _cde(objective="logic synthesis", status="failed",
                    error=f"invalid or missing 'top' identifier: {_top!r}",
                    validation={"verdict": "fail", "reason": "invalid top"})
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
