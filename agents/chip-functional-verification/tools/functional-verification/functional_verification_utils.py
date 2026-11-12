#!/usr/bin/env python3
"""functional_verification_utils.py -- real Icarus Verilog simulation.

Compiles RTL + a testbench with `iverilog`, runs the compiled object with `vvp`,
parses the run for pass/fail markers and an optional VCD, and reports the
simulation verdict. Node-agnostic. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

import rtl_frontend
import simulator_select

TOOL = "functional-verification"
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
        import shlex
        line = (" ".join(shlex.quote(str(c)) for c in cmd)
                if isinstance(cmd, (list, tuple)) else str(cmd))
        with open(os.path.join(_OUTPUT_DIR, name), "a", encoding="utf-8") as f:
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
                       ("Signoff evidence", "signoff_evidence")):
        d = r.get(key)
        if isinstance(d, dict) and d:
            rows = _report_kv_rows(d)
            if rows:
                L += ["", "## " + title, "", "| Metric | Value |", "| --- | --- |"] + rows
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
        if (low.endswith((".log", ".tcl", ".ys", ".sh", ".do", ".vvp"))
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
    prov = r.get("provenance") or {}
    plines = []
    if isinstance(prov, dict) and prov.get("runtime_s") is not None:
        plines.append("- Runtime: " + str(prov["runtime_s"]) + " s")
    if plines:
        L += ["## Provenance", ""] + plines + [""]
    L += ["## Where to find more", "",
          "- `common_design_envelope.json` \u2014 full machine-readable envelope (this dir)",
          "- `results/` \u2014 VCD waveform (if dumped)",
          "- `logs/` \u2014 verbatim iverilog/vvp log and the exact run command", ""]
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
    for fn, lbl in ((_write_report_md, "report"), (_write_summary_md, "summary")):
        try:
            fn(results)
        except Exception as _e:
            print("[" + str(TOOL) + "] " + lbl + " generation skipped: " + str(_e), flush=True)
    try:
        _organize_output()
    except Exception as _e:
        print("[" + str(TOOL) + "] output organize skipped: " + str(_e), flush=True)


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def _iverilog_version():
    try:
        out = subprocess.run(["iverilog", "-V"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return txt.splitlines()[0] if txt else "iverilog"
    except Exception:
        return "iverilog"


def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    Measured on the live corpus: this tool's envelopes carried THREE different
    `stage` values -- "simulation", "verification", and no `stage` key at all --
    because the tool never stamped one and each caller wrote its own. An
    unrecognized (or absent) stage resolves to no registry entry, which reports
    NO METRIC, and downstream a missing metric is indistinguishable from a
    closed gate. So the tool names its own gate rather than leaving it to the
    caller. Resolved through the registry so the constant lives in ONE place.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "funcverif"
    except Exception:
        return "funcverif"


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
        base.setdefault("basis", "agent_read_of_sim_log" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_sim_log")


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
         validation=None, provenance=None, inputs_ref=None, qor=None, error=None,
         vplan="shared_artifact"):
    env = {
        "tool": TOOL, "stage": _canonical_stage(), "status": status,
        "objective": objective,
        "tools_used": [{"name": "Icarus Verilog", "version": _iverilog_version()}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": vplan,
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "simulation"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _stage_rtl(params):
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "dut.v")
        open(p, "w").write(params["rtl"])
        files.append(p)
    for source in params.get("rtl_files", []):
        if not os.path.isfile(source):
            raise FileNotFoundError("RTL source not found: " + str(source))
        files.append(source)
    if params.get("testbench"):
        p = os.path.join(_WORK_DIR, "tb.v")
        open(p, "w").write(params["testbench"])
        files.append(p)
    for source in params.get("testbench_files", []):
        if not os.path.isfile(source):
            raise FileNotFoundError("testbench source not found: " + str(source))
        files.append(source)
    return files


def _ghdl_version():
    try:
        out = subprocess.run(["ghdl", "--version"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return txt.splitlines()[0] if txt else "ghdl"
    except Exception:
        return "ghdl"


def _cocotb_version():
    try:
        import cocotb  # noqa: WPS433 (runtime probe)
        return getattr(cocotb, "__version__", "cocotb")
    except Exception:
        return "absent"


def _is_cocotb_run(params, files):
    """Detect a cocotb (Python) verification methodology.

    True when the task explicitly asks for cocotb (`sim_backend`/`methodology`),
    names a cocotb test module (`cocotb_module`/`test_module`/`cocotb_tests`), or
    supplies a Python testbench file. A pure HDL testbench (`.v`/`.sv`/`.vhd`)
    stays on the native Icarus/GHDL paths.
    """
    backend = str(params.get("sim_backend") or params.get("methodology") or "").lower()
    if backend == "cocotb":
        return True
    if any(params.get(k) for k in ("cocotb_module", "test_module", "cocotb_tests")):
        return True
    return any(str(f).endswith(".py") for f in files)


def _cocotb_modules(params, files):
    """Resolve the cocotb test module name(s) + the dir(s) to import them from."""
    mods, dirs = [], []
    explicit = (params.get("cocotb_module") or params.get("test_module")
                or params.get("cocotb_tests"))
    for m in _as_list(explicit):
        mods.append(str(m))
    for f in files:
        if str(f).endswith(".py"):
            d = os.path.dirname(os.path.abspath(str(f))) or _WORK_DIR
            dirs.append(d)
            name = os.path.splitext(os.path.basename(str(f)))[0]
            if name not in mods:
                mods.append(name)
    # de-dup preserving order
    return list(dict.fromkeys(mods)), list(dict.fromkeys(dirs))


def _get_cocotb_runner(sim):
    """Return a cocotb runner, tolerating the cocotb 1.x/2.x module split."""
    try:
        from cocotb_tools.runner import get_runner  # cocotb >= 2.0
        return get_runner(sim)
    except Exception:
        from cocotb.runner import get_runner  # cocotb < 2.0
        return get_runner(sim)


def _parse_junit(path):
    """Parse a cocotb JUnit results.xml -> (tests, failures, errors, skipped).

    Counts <testcase> elements directly (cocotb 2.x does not populate the
    testsuite `tests`/`failures` count attributes), classifying each by its
    child <failure>/<error>/<skipped> tag. Falls back to the testsuite count
    attributes only when there are no testcase elements.
    """
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(path).getroot()
        cases = list(root.iter("testcase"))
        if cases:
            t = len(cases)
            f = e = s = 0
            for c in cases:
                if c.find("failure") is not None:
                    f += 1
                elif c.find("error") is not None:
                    e += 1
                elif c.find("skipped") is not None:
                    s += 1
            return t, f, e, s
        # Fallback: sum testsuite attributes.
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        t = f = e = s = 0
        for su in suites:
            t += int(su.get("tests", 0) or 0)
            f += int(su.get("failures", 0) or 0)
            e += int(su.get("errors", 0) or 0)
            s += int(su.get("skipped", 0) or 0)
        return t, f, e, s
    except Exception:
        return None


def _run_sim_cocotb(params, files):
    """Run a cocotb (Python) regression, elaborating VHDL with GHDL (or Verilog
    with Icarus) via the cocotb runner API.

    This is the cocotb-methodology path for the functional-verification tool:
    the DUT is real HDL (VHDL routed to the GHDL backend, Verilog to Icarus) and
    the tests are cocotb Python coroutines. A JUnit results.xml is parsed for the
    pass/fail tally; no waiver, exclusion, or smoke verdict is invented here.
    """
    if _cocotb_version() == "absent":
        return _cde(objective="functional simulation (cocotb)", status="failed",
                    error="cocotb is not installed in this image (required for the cocotb methodology)",
                    validation={"verdict": "fail"},
                    provenance={"ghdl": _ghdl_version(), "cocotb": "absent"})
    top = params.get("hdl_toplevel") or params.get("toplevel") or params.get("top")
    if not top:
        return _cde(objective="functional simulation (cocotb)", status="failed",
                    error="cocotb run requires 'hdl_toplevel' (or 'top'/'toplevel') = the DUT entity/module",
                    validation={"verdict": "fail"})
    mods, mod_dirs = _cocotb_modules(params, files)
    if not mods:
        return _cde(objective="functional simulation (cocotb)", status="failed",
                    error="cocotb run requires a Python test module ('cocotb_module'/'test_module' or a .py testbench file)",
                    validation={"verdict": "fail"})
    vhdl_srcs = [f for f in files if rtl_frontend.is_vhdl(f)]
    verilog_srcs = [f for f in files
                    if str(f).endswith((".v", ".sv", ".vh", ".svh"))]
    if vhdl_srcs and verilog_srcs:
        return _cde(
            objective="functional simulation (cocotb)", status="failed",
            error=("mixed VHDL+Verilog DUT is not supported by a single cocotb backend; "
                   "provide a single-language DUT set. " + rtl_frontend.language_note(files)),
            validation={"verdict": "fail"})
    is_vhdl = bool(vhdl_srcs)
    std = str(params.get("vhdl_std", params.get("std", "08"))).strip() or "08"
    # A hard-coded default can be a simulator that cannot PARSE this DUT: Icarus 11.0
    # rejects `localparam reg [15:0]` under every -g flag while Verilator accepts the
    # same file. Probe, then record the choice so a substitution is disclosed.
    # A caller-supplied `sim` is a PREFERENCE, not an override: it is probed too, so
    # naming a simulator that cannot read the DUT reports that fact instead of failing.
    sim_choice = simulator_select.select(
        [str(f) for f in (vhdl_srcs if is_vhdl else verilog_srcs)],
        top=top, preferred=params.get("sim"), is_vhdl=is_vhdl, std=std)
    sim = sim_choice["selected"]

    # Single shared sim dir: GHDL-mcode elaborates from the dir holding its `work`
    # library, and cocotb imports the Python test module from the same dir, so
    # keeping build_dir == test_dir == this dir (with the .py tests copied in)
    # makes both the HDL work library and the Python module resolve together.
    sim_build = os.path.join(_WORK_DIR, "sim_build")
    os.makedirs(sim_build, exist_ok=True)
    for f in files:
        if str(f).endswith(".py"):
            try:
                shutil.copyfile(str(f), os.path.join(sim_build, os.path.basename(str(f))))
            except Exception:
                pass

    # Make the Python test modules importable (belt-and-suspenders alongside the copy).
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [sim_build] + mod_dirs + [env.get("PYTHONPATH", "")]).strip(os.pathsep)

    t0 = time.time()
    try:
        runner = _get_cocotb_runner(sim)
        build_kwargs = {"hdl_toplevel": top, "always": True,
                        "build_dir": sim_build}
        if is_vhdl:
            build_kwargs["vhdl_sources"] = vhdl_srcs
            # GHDL: the --std must match on BOTH analyze (build) AND elaborate
            # (test); a mismatch makes GHDL "cannot find entity" at elaboration.
            build_kwargs["build_args"] = [f"--std={std}"] + list(params.get("build_args") or [])
        else:
            build_kwargs["verilog_sources"] = verilog_srcs
            build_kwargs["build_args"] = list(params.get("build_args") or [])
        runner.build(**build_kwargs)
        test_kwargs = {"hdl_toplevel": top, "test_module": mods,
                       "build_dir": sim_build, "test_dir": sim_build,
                       "extra_env": env}
        if is_vhdl:
            test_kwargs["hdl_toplevel_lang"] = "vhdl"
            # Pass the same --std to the elaborate/run step (test_args) so the
            # elaborated unit matches the analyzed one.
            test_kwargs["test_args"] = [f"--std={std}"] + list(params.get("test_args") or [])
        results_xml = runner.test(**test_kwargs)
    except Exception as exc:  # real tool failure -> fail closed, no invented verdict
        elapsed = time.time() - t0
        log = os.path.join(_OUTPUT_DIR, "cocotb_run.log")
        try:
            open(log, "w").write(f"cocotb runner exception ({sim}):\n{exc}")
        except Exception:
            pass
        return _cde(
            objective=f"functional simulation of {top} (cocotb/{sim})", status="failed",
            error=f"cocotb runner ({sim}) failed: {exc}",
            inputs_ref={"files": files},
            validation={"verdict": "fail"},
            provenance={"ghdl": _ghdl_version(), "cocotb": _cocotb_version(),
                        "runtime_s": round(elapsed, 3), "simulator": sim})
    elapsed = time.time() - t0

    # Persist the JUnit result next to the outputs.
    xml_out = os.path.join(_OUTPUT_DIR, "results.xml")
    try:
        if results_xml and os.path.exists(str(results_xml)):
            shutil.copyfile(str(results_xml), xml_out)
    except Exception:
        pass
    tally = _parse_junit(xml_out if os.path.exists(xml_out) else str(results_xml or ""))
    if tally is None:
        return _cde(
            objective=f"functional simulation of {top} (cocotb/{sim})", status="failed",
            error="cocotb produced no parseable results.xml; treating as fail-closed (no verdict invented)",
            inputs_ref={"files": files}, validation={"verdict": "fail"},
            provenance={"ghdl": _ghdl_version(), "cocotb": _cocotb_version(),
                        "runtime_s": round(elapsed, 3), "simulator": sim})
    tests, failures, errors, skipped = tally
    ran = tests - skipped
    verdict = "pass" if (ran > 0 and failures == 0 and errors == 0) else "fail"
    return _cde(
        objective=f"functional simulation of {top} (cocotb/{sim})",
        status="completed",
        # (A) GATING -- parsed from cocotb's own JUnit XML. `failures` and
        # `errors` must reach zero, and `sim_passed` additionally requires that
        # tests actually RAN: a regression where everything skipped reports zero
        # failures, and zero-of-zero must never read as a pass.
        results={"sim_passed": {
                     "value": verdict == "pass", "unit": "bool",
                     "class": "gating", "basis": "parsed_cocotb_junit_xml",
                     "closes_at": "== true",
                     "note": ("Requires ran > 0 AND failures == 0 AND errors == 0. "
                              "A null means NOT ASSESSED (no parseable results.xml) "
                              "and must never read as true -- see the fail-closed "
                              "path above.")},
                 "tests": {
                     "value": tests, "unit": "count",
                     "class": "diagnostic", "basis": "parsed_cocotb_junit_xml",
                     "note": ("POPULATION and higher-is-better. Never a residual: "
                              "declaring it would make ADDING tests look like "
                              "regression.")},
                 "failures": {
                     "value": failures, "unit": "count",
                     "class": "gating", "basis": "parsed_cocotb_junit_xml",
                     "closes_at": "== 0"},
                 "errors": {
                     "value": errors, "unit": "count",
                     "class": "gating", "basis": "parsed_cocotb_junit_xml",
                     "closes_at": "== 0",
                     "note": ("An ERROR is a test that could not run to a verdict; "
                              "it is not a pass and not a failure -- it is absence "
                              "of evidence.")},
                 "skipped": {
                     "value": skipped, "unit": "count",
                     "class": "diagnostic", "basis": "parsed_cocotb_junit_xml",
                     "note": ("Load-bearing: skipped tests SHRINK the effective "
                              "population, so a rising skip count can make a "
                              "failing suite look clean.")}},
        qor={"sim_verdict": verdict, "tests": tests, "failures": failures,
             "errors": errors},
        signoff={"verdict": verdict, "results_xml": "results.xml",
                 "language": "vhdl" if is_vhdl else "verilog",
                 "vhdl_std": std if is_vhdl else None,
                 "simulator": sim, "methodology": "cocotb",
                 "simulator_selection": sim_choice,
                 "test_modules": mods,
                 # (B) DIAGNOSTIC -- measured, non-gating: the tally that tells
                 # you WHICH way the suite is open (ran vs failed vs skipped).
                 "diagnostics": {
                     "class": "diagnostic", "basis": "parsed_cocotb_junit_xml",
                     "tests_total": tests, "tests_ran": ran,
                     "failures": failures, "errors": errors, "skipped": skipped,
                     "test_modules": mods,
                     "population_note": ("tests_total is the denominator and is "
                                         "diagnostic, not descriptive: REMOVING or "
                                         "skipping a test shrinks it and can make a "
                                         "failing regression read as closed.")},
                 # (C) DESCRIPTIVE -- configuration, expected to hold steady.
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "top": top, "simulator": sim, "methodology": "cocotb",
                     "language": "vhdl" if is_vhdl else "verilog",
                     "vhdl_std": std if is_vhdl else None,
                     "elapsed_s": round(elapsed, 3)},
                 # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), failures, "failures")},
        inputs_ref={"files": files},
        assumptions=[f"cocotb regression on the {sim} backend; "
                     + rtl_frontend.language_note(files)],
        validation={"verdict": verdict,
                    "note": f"{ran} test(s) ran, {failures} failure(s), {errors} error(s)"},
        provenance={"ghdl": _ghdl_version(), "cocotb": _cocotb_version(),
                    "iverilog": _iverilog_version() if not is_vhdl else None,
                    "runtime_s": round(elapsed, 3), "simulator": sim,
                    "logs": ["results.xml"]},
    )


def _run_sim_ghdl(params, files):
    """Native VHDL simulation with GHDL (analyze -> elaborate -> run).

    Used when the staged source/testbench set is pure VHDL. Standalone GHDL
    simulation does not require the ghdl-yosys-plugin. The elaboration unit is the
    VHDL testbench top (`tb_top`/`top`); a `.vcd` is captured when produced.
    """
    if not shutil.which("ghdl"):
        return _cde(objective="functional simulation", status="failed",
                    error="ghdl not found on PATH (VHDL simulation requires GHDL)",
                    validation={"verdict": "fail"})
    tb_top = params.get("tb_top") or params.get("top")
    if not tb_top:
        return _cde(objective="functional simulation", status="failed",
                    error="VHDL simulation requires 'tb_top' (or 'top') = the VHDL testbench entity",
                    validation={"verdict": "fail"})
    std = str(params.get("vhdl_std", params.get("std", "08"))).strip() or "08"
    stdflag = f"--std={std}"
    vhdl_files = [f for f in files if rtl_frontend.is_vhdl(f)]
    t0 = time.time()
    a_cmd = ["ghdl", "-a", stdflag] + vhdl_files
    _save_run_command(a_cmd)
    a = subprocess.run(a_cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    alog = a.stdout + "\n" + a.stderr
    open(os.path.join(_OUTPUT_DIR, "ghdl_analyze.log"), "w").write(alog)
    if a.returncode != 0:
        return _cde(objective="functional simulation", status="failed",
                    error="ghdl -a (analyze) failed; see ghdl_analyze.log:\n" + alog[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"ghdl": _ghdl_version(), "log": "ghdl_analyze.log"})
    e_cmd = ["ghdl", "-e", stdflag, tb_top]
    _save_run_command(e_cmd)
    e = subprocess.run(e_cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elog = e.stdout + "\n" + e.stderr
    open(os.path.join(_OUTPUT_DIR, "ghdl_elaborate.log"), "w").write(elog)
    if e.returncode != 0:
        return _cde(objective="functional simulation", status="failed",
                    error="ghdl -e (elaborate) failed; see ghdl_elaborate.log:\n" + elog[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"ghdl": _ghdl_version(), "log": "ghdl_elaborate.log"})
    vcd_name = "sim.vcd"
    r_cmd = ["ghdl", "-r", stdflag, tb_top, f"--vcd={os.path.join(_OUTPUT_DIR, vcd_name)}"]
    stop_time = params.get("stop_time")
    if stop_time:
        r_cmd.append(f"--stop-time={stop_time}")
    r_cmd += [str(x) for x in (params.get("plusargs") or [])]
    _save_run_command(r_cmd)
    r = subprocess.run(r_cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    rlog = r.stdout + "\n" + r.stderr
    open(os.path.join(_OUTPUT_DIR, "ghdl_run.log"), "w").write(rlog)
    vcd = vcd_name if os.path.exists(os.path.join(_OUTPUT_DIR, vcd_name)) else None
    low = rlog.lower()
    has_pass = bool(re.search(r"\b(pass(ed)?|all tests passed|test ok|success)\b", low))
    has_fail = bool(re.search(r"(assertion (failure|error)|\bfailure\b|\berror\b|mismatch|\bfail(ed)?\b)", low))
    errors = len(re.findall(r"\berror\b", low))
    if r.returncode != 0 or (has_fail and not has_pass):
        verdict = "fail"
    elif has_pass:
        verdict = "pass"
    else:
        verdict = "review"
    return _cde(
        objective=f"functional simulation of {tb_top} (VHDL/GHDL)",
        status="completed",
        results={"sim_passed": {"value": verdict == "pass", "unit": "bool"},
                 "error_lines": {"value": errors, "unit": "count"}},
        qor={"sim_verdict": verdict},
        signoff={"verdict": verdict, "vcd": vcd, "analyze_log": "ghdl_analyze.log",
                 "elaborate_log": "ghdl_elaborate.log", "sim_log": "ghdl_run.log",
                 "language": "vhdl", "vhdl_std": std, "simulator": "ghdl",
                 "stop_time": stop_time or "testbench-controlled"},
        inputs_ref={"files": files},
        assumptions=["VHDL simulated natively with GHDL; " + rtl_frontend.language_note(files)],
        validation={"verdict": verdict},
        provenance={"ghdl": _ghdl_version(), "runtime_s": round(elapsed, 3),
                    "logs": ["ghdl_analyze.log", "ghdl_elaborate.log", "ghdl_run.log"]},
    )


def _self_check_evidence(log, returncode, vcd_bytes, compile_log=""):
    """Assess explicit testbench evidence, never generic success-like prose."""
    summaries = re.findall(r"^COMPARISONS=(\d+) MISMATCHES=(\d+)\s*$", log, re.M)
    comparisons, mismatches = (map(int, summaries[0]) if len(summaries) == 1
                               else (None, None))
    marker = bool(re.search(r"^TEST PASSED\s*$", log, re.M))
    failures = bool(re.search(
        r"\b(?:fail(?:ed|ure|ures)?|errors?|fatal|mismatch)\b",
        compile_log + "\n" + log, re.I))
    errors = len(re.findall(r"\b(?:errors?|fatal)\b", compile_log + "\n" + log, re.I))
    passed = (returncode == 0 and not failures and marker and vcd_bytes > 0
              and comparisons is not None and comparisons > 0 and mismatches == 0)
    return {"passed": passed, "comparisons": comparisons, "mismatches": mismatches,
            "exact_pass_marker": marker, "failure_marker": failures,
            "error_lines": errors, "vcd_bytes": vcd_bytes}


def _run_sim(params):
    if not shutil.which("iverilog"):
        return _cde(objective="functional simulation", status="failed",
                    error="iverilog not found on PATH", validation={"verdict": "fail"})
    files = _stage_rtl(params)
    if not files:
        return _cde(objective="functional simulation", status="failed",
                    error="no RTL/testbench supplied (rtl/rtl_files/testbench/testbench_files)",
                    validation={"verdict": "fail"})
    # cocotb (Python) methodology takes precedence: a cocotb test module or a .py
    # testbench routes to the cocotb runner (VHDL DUT -> GHDL backend, Verilog DUT
    # -> Icarus). This is separate from a native HDL testbench, which continues on
    # the Icarus/GHDL paths below.
    if _is_cocotb_run(params, files):
        return _run_sim_cocotb(params, files)
    # Language dispatch: a VHDL source or VHDL testbench routes to native GHDL
    # simulation; a pure-Verilog set stays on the Icarus path (default). Mixed
    # VHDL+Verilog cannot be co-simulated by iverilog or standalone GHDL, so it is
    # flagged with an actionable message instead of crashing at the compiler.
    lang = rtl_frontend.detect_language(files)
    if lang == "vhdl":
        return _run_sim_ghdl(params, files)
    if lang == "mixed":
        return _cde(
            objective="functional simulation", status="failed",
            error=("mixed VHDL+Verilog co-simulation is not supported by iverilog or "
                   "standalone GHDL. Provide a single-language testbench+DUT set, or "
                   "lower the VHDL to Verilog first (ghdl synth --out=verilog). "
                   + rtl_frontend.language_note(files)),
            validation={"verdict": "fail"})
    top = params.get("top") or params.get("tb_top")
    obj = os.path.join(_WORK_DIR, "sim.vvp")
    gen = params.get("generation", "2012")   # -g2012 / -g2005 / -g1995
    cmd = ["iverilog", f"-g{gen}", "-o", obj]
    if top:
        cmd += ["-s", top]
    for d in (params.get("include_dirs") or []):
        cmd += ["-I", str(d)]
    # Library search: -y auto-loads modules from directories, -l names a library
    # file (Icarus `library_dirs` / `libraries`).
    for d in (params.get("library_dirs") or []):
        cmd += ["-y", str(d)]
    for lib in (params.get("libraries") or []):
        cmd += ["-l", str(lib)]
    for k, v in (params.get("defines") or {}).items():
        cmd += ["-D", (f"{k}={v}" if v not in (None, "") else str(k))]
    # Warning classes: `warnings` (list, e.g. ["all","no-timescale"]) -> -Wall / -Wno-...
    for w in (params.get("warnings") or []):
        cmd.append(f"-W{w}")
    # Explicit timescale override (`unit/precision`, e.g. "1ns/1ps") is injected via a
    # generated header compiled ahead of the sources.
    timescale = params.get("timescale")
    if timescale:
        ts_file = os.path.join(_WORK_DIR, "_timescale.v")
        try:
            unit, prec = (str(timescale).split("/") + ["1ps"])[:2]
            open(ts_file, "w").write(f"`timescale {unit.strip()}/{prec.strip()}\n")
            files = [ts_file] + files
        except Exception as _e:
            print("[" + str(TOOL) + "] timescale '" + str(timescale)
                  + "' ignored (unparseable): " + str(_e), flush=True)
    cmd += files
    # --- SDF back-annotation (TIMING GLS) -------------------------------------
    # Without an SDF every gate has zero delay, so the run can prove reset/X
    # hygiene but is structurally blind to glitches, races and at-speed failures.
    # Two things are BOTH required and neither is optional:
    #   * `-gspecify` -- Icarus IGNORES specify blocks by default, and specify
    #     blocks are where cell delays live. Compile without it and $sdf_annotate
    #     loads the file, matches nothing, and the sim silently stays zero-delay.
    #   * an annotator module that calls $sdf_annotate on the DUT scope, because
    #     this tool does not own the testbench and cannot inject the call into it.
    sdf = params.get("sdf")
    sdf_applied = None
    if sdf:
        if not os.path.exists(str(sdf)):
            return _cde(objective="functional simulation", status="failed",
                        error="sdf not found: %s" % sdf,
                        validation={"verdict": "fail"})
        scope = params.get("sdf_scope")
        if not scope:
            return _cde(
                objective="functional simulation", status="failed",
                error=("sdf back-annotation requires 'sdf_scope' -- the hierarchical "
                       "path of the DUT instance inside the testbench (e.g. "
                       "'tb_top.dut'). Annotating the wrong scope loads the SDF, "
                       "matches no cell, and leaves the run silently ZERO-DELAY, "
                       "reporting a clean timing GLS that proved nothing."),
                validation={"verdict": "fail"})
        mtm = str(params.get("sdf_mtm", "max")).strip().lower()
        if mtm not in ("min", "typ", "max"):
            return _cde(objective="functional simulation", status="failed",
                        error="sdf_mtm must be min, typ, or max",
                        validation={"verdict": "fail"})
        ann = os.path.join(_WORK_DIR, "_sdf_annotate.v")
        with open(ann, "w", encoding="utf-8") as fh:
            fh.write(
                "// generated by chip-functional-verification: SDF back-annotation\n"
                "module __sdf_annotator;\n"
                "  initial $sdf_annotate(\"%s\", %s);\n"
                "endmodule\n" % (str(sdf).replace("\\", "/"), scope))
        # Three flags, each load-bearing -- all three verified against the
        # packaged Icarus 11.0, because getting any one wrong yields a run that
        # PASSES while silently proving nothing:
        #   -gspecify            Icarus ignores specify blocks by default, and
        #                        specify blocks are where cell delays live.
        #   -s __sdf_annotator   the annotator is a SECOND ROOT. With only
        #                        `-s <top>` it is never elaborated, its initial
        #                        block never runs, and the sim stays zero-delay
        #                        with no diagnostic whatsoever.
        #   -T<mtm>              Icarus picks the min:typ:max corner at COMPILE
        #                        time and IGNORES $sdf_annotate's mtm_spec
        #                        argument ("currently only uses the first two
        #                        argument"), so selecting the corner there is a
        #                        no-op that silently leaves every run on TYPICAL.
        cmd += ["-gspecify", "-T%s" % mtm, "-s", "__sdf_annotator", ann]
        sdf_applied = {"sdf": str(sdf), "scope": scope, "mtm": mtm,
                       "specify_enabled": True,
                       "corner_selected_by": "iverilog -T%s" % mtm,
                       "annotator_root": "__sdf_annotator"}
    t0 = time.time()
    _save_run_command(cmd)
    cproc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    clog = cproc.stdout + "\n" + cproc.stderr
    open(os.path.join(_OUTPUT_DIR, "iverilog.log"), "w").write(clog)
    if cproc.returncode != 0 or not os.path.exists(obj):
        hint = ""
        if sdf_applied is not None and re.search(r"unable to bind", clog, re.I):
            hint = ("\n\nHINT: the SDF annotator failed to bind '%s'. `sdf_scope` must "
                    "be the hierarchical path of the DUT INSTANCE inside the "
                    "testbench (e.g. 'tb.dut'), not a module name. This is caught at "
                    "elaboration, which is why it is a hard failure rather than a "
                    "silently zero-delay run." % sdf_applied.get("scope"))
        return _cde(objective="functional simulation", status="failed",
                    error="iverilog compile failed; see iverilog.log:\n"
                          + clog[-1500:] + hint,
                    signoff={"sdf_back_annotation": sdf_applied,
                             "native_exit_codes": {"iverilog": cproc.returncode}},
                    validation={"verdict": "fail"},
                    provenance={"iverilog": _iverilog_version(), "log": "iverilog.log"})
    # Run vvp; forward any plusargs and an optional waveform-format flag
    # (`wave_format`: lxt2 | fst | vcd) so the dump is written in the requested form.
    run_cmd = ["vvp", obj]
    wave_format = str(params.get("wave_format") or "").lower()
    if wave_format in ("lxt2", "lxt"):
        run_cmd.append("-lxt2")
    elif wave_format == "fst":
        run_cmd.append("-fst")
    run_cmd += [str(a) for a in (params.get("plusargs") or [])]
    _save_run_command(run_cmd)
    rproc = subprocess.run(run_cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    rlog = rproc.stdout + "\n" + rproc.stderr
    open(os.path.join(_OUTPUT_DIR, "vvp.log"), "w").write(rlog)
    # collect a waveform if the testbench dumped one (VCD, or LXT2/FST when a
    # wave_format was requested).
    vcd = None
    vcd_bytes = 0
    for fn in sorted(os.listdir(_WORK_DIR)):
        if fn.endswith((".vcd", ".lxt2", ".lxt", ".fst")):
            src = os.path.join(_WORK_DIR, fn)
            dst = os.path.join(_OUTPUT_DIR, fn)
            shutil.copyfile(src, dst)
            if fn.endswith(".vcd") and os.path.getsize(dst) > vcd_bytes:
                vcd = fn
                vcd_bytes = os.path.getsize(dst)
    evidence = _self_check_evidence(rlog, rproc.returncode, vcd_bytes, clog)
    errors = evidence["error_lines"]
    verdict = "pass" if evidence["passed"] else "fail"

    # --- SDF annotation must have MATCHED, not merely been requested ----------
    # $sdf_annotate against a wrong scope, or a design compiled without specify
    # blocks, produces a warning and then runs ZERO-DELAY. That is the dangerous
    # case: the run looks like a timing GLS, passes, and proves nothing. Icarus
    # reports non-matching annotation on stdout/stderr, so a requested SDF whose
    # annotation warned is downgraded to a hard fail rather than reported clean.
    if sdf_applied is not None:
        combined = (clog + "\n" + rlog)
        bad = re.findall(
            r"^.*(?:sdf|annotat|delayfile).*(?:not found|no such|cannot|could not|"
            r"failed|ignored|unable|no match|does not|error|invalid).*$",
            combined, re.I | re.M)[:5]
        sdf_applied["annotation_warnings"] = bad
        sdf_applied["annotated"] = not bad
        if bad:
            return _cde(
                objective=f"timing GLS of {top or 'design'}", status="failed",
                results={"sim_passed": {"value": False, "unit": "bool"}},
                signoff={"sdf_back_annotation": sdf_applied,
                         "compile_log": "iverilog.log", "sim_log": "vvp.log"},
                inputs_ref={"files": files, "sdf": sdf_applied["sdf"]},
                error="SDF back-annotation did not apply cleanly:\n"
                      + "\n".join(bad),
                validation={
                    "verdict": "fail",
                    "note": ("SDF was supplied but the annotation warned, so the "
                             "cells kept ZERO delay. A pass here would claim "
                             "timing GLS coverage the run does not have. Check "
                             "'sdf_scope' names the real DUT instance path and "
                             "that the cell models carry specify blocks.")},
                provenance={"iverilog": _iverilog_version(),
                            "runtime_s": round(elapsed, 3),
                            "logs": ["iverilog.log", "vvp.log"]})

    return _cde(
        objective=f"functional simulation of {top or 'design'}",
        status="completed",
        # (A) GATING -- inferred from the testbench's own console markers. Both
        # must close: a run can print PASS while still emitting error lines.
        results={"sim_passed": {
                     "value": verdict == "pass", "unit": "bool",
                     "class": "gating", "basis": "parsed_simulator_console_output",
                     "closes_at": "== true",
                     "note": ("Inferred from testbench PASS/FAIL markers. A null "
                              "means NOT ASSESSED (no explicit marker) and must "
                              "never read as true -- an unmarked testbench is an "
                              "unproven one.")},
                 "comparisons": {
                     "value": evidence["comparisons"], "unit": "count",
                     "class": "gating", "basis": "testbench_summary", "closes_at": "> 0"},
                 "mismatches": {
                     "value": evidence["mismatches"], "unit": "count",
                     "class": "gating", "basis": "testbench_summary", "closes_at": "== 0"},
                 "error_lines": {
                     "value": errors, "unit": "count",
                     "class": "gating", "basis": "parsed_simulator_console_output",
                     "closes_at": "== 0"}},
        qor={"sim_verdict": verdict},
        signoff={"verdict": verdict, "vcd": vcd, "compile_log": "iverilog.log",
                 "self_check": evidence,
                 "native_exit_codes": {"iverilog": cproc.returncode, "vvp": rproc.returncode},
                 "sim_log": "vvp.log", "generation": gen,
                 "wave_format": wave_format or "vcd",
                 "warnings": params.get("warnings") or [],
                 "sdf_back_annotation": sdf_applied,
                 # (B) DIAGNOSTIC -- measured, non-gating. The delay mode is here
                 # rather than in descriptive because it bounds WHAT THE RUN COULD
                 # HAVE OBSERVED: a zero-delay sim cannot see a glitch at all, so
                 # a clean result means far less than it appears to.
                 "diagnostics": {
                     "class": "diagnostic",
                     "basis": "parsed_simulator_console_output",
                     "error_lines": errors,
                     "sdf_annotated": bool(sdf_applied),
                     "observability_note": (
                         "ZERO-DELAY runs observe X-propagation and reset hygiene "
                         "ONLY; glitches and at-speed failures are structurally "
                         "invisible. A pass here does not cover them.")},
                 # (C) DESCRIPTIVE -- configuration, expected to hold steady.
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "top": top or "design", "simulator": "iverilog/vvp",
                     "generation": gen, "wave_format": wave_format or "vcd",
                     "timescale": timescale or "design-default",
                     "elapsed_s": round(elapsed, 3)},
                 # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), errors, "error_lines"),
                 "delay_mode": (("back-annotated SDF (%s corner, enforced by "
                                "`iverilog -T%s`) -- glitch / race / at-speed "
                                "visible" % (sdf_applied["mtm"], sdf_applied["mtm"]))
                                if sdf_applied else
                                "ZERO-DELAY (no SDF) -- X-propagation and reset "
                                "hygiene only; glitches and at-speed failures are "
                                "NOT observable"),
                 "timescale": timescale or "design-default"},
        inputs_ref={"files": files},
        assumptions=["Icarus success requires positive comparisons, zero mismatches, "
                     "exact TEST PASSED, no errors/failure markers and nonempty VCD"],
        validation={"verdict": verdict,
                    "note": "self-check evidence complete" if verdict == "pass"
                    else "incomplete or failing self-check evidence; inspect self_check and logs"},
        provenance={"iverilog": _iverilog_version(), "runtime_s": round(elapsed, 3),
                    "log": "vvp.log"},
    )


def _lint(params):
    """Fast structural elaboration check: `iverilog -t null -Wall ...` compiles
    and reports warnings/errors without producing a runnable object."""
    if not shutil.which("iverilog"):
        return _cde(objective="RTL elaboration lint", status="failed",
                    error="iverilog not found on PATH", validation={"verdict": "fail"})
    files = _stage_rtl(params)
    if not files:
        return _cde(objective="RTL elaboration lint", status="failed",
                    error="no RTL supplied (rtl/rtl_files/testbench/testbench_files)",
                    validation={"verdict": "fail"})
    top = params.get("top") or params.get("tb_top")
    gen = params.get("generation", "2012")
    cmd = ["iverilog", f"-g{gen}", "-t", "null"]
    if top:
        cmd += ["-s", top]
    for d in (params.get("include_dirs") or []):
        cmd += ["-I", str(d)]
    for d in (params.get("library_dirs") or []):
        cmd += ["-y", str(d)]
    for lib in (params.get("libraries") or []):
        cmd += ["-l", str(lib)]
    for k, v in (params.get("defines") or {}).items():
        cmd += ["-D", (f"{k}={v}" if v not in (None, "") else str(k))]
    warns = params.get("warnings") or ["all"]
    for w in warns:
        cmd.append(f"-W{w}")
    cmd += files
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    log = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "iverilog_lint.log"), "w").write(log)
    warn_n = len(re.findall(r"^\s*.*:\s*warning:", log, re.M | re.I))
    err_n = len(re.findall(r"^\s*.*:\s*(?:syntax )?error:", log, re.M | re.I))
    clean = proc.returncode == 0 and err_n == 0
    verdict = "pass" if clean else "fail"
    return _cde(
        objective=f"RTL elaboration lint of {top or 'design'}", status="completed",
        results={"errors": {"value": err_n, "unit": "count"},
                 "warnings": {"value": warn_n, "unit": "count"}},
        qor={"errors": err_n, "warnings": warn_n, "clean": clean},
        signoff={"clean": clean, "errors": err_n, "warnings": warn_n,
                 "warning_classes": warns, "report": "iverilog_lint.log"},
        inputs_ref={"files": files},
        assumptions=["`iverilog -t null` elaborates without generating a runnable "
                     "object; warnings are advisory, elaboration errors fail"],
        validation={"verdict": verdict,
                    "note": ("elaboration clean" if clean else
                             f"{err_n} elaboration error(s)")},
        provenance={"iverilog": _iverilog_version(), "runtime_s": round(elapsed, 3),
                    "log": "iverilog_lint.log"},
    )


def _gls(params):
    """GATE-LEVEL FUNCTIONAL SANITY (GLS). Simulate the mapped/scan gate netlist
    (with the PDK cell Verilog sim models) against a testbench — the confidence net
    for what post-synth/post-DFT LEC cannot see: X-propagation / uninitialized
    state (scan flops with no reset), and — with a back-annotated SDF — glitches
    and timing. This is NOT coverage closure: functional coverage is closed ONCE on
    RTL; GLS is a small DIRECTED sanity regression with a PASS floor.

    Production methodology encoded here:
      - mode=mission (default): scan_enable INACTIVE — the chip does its real job;
        this is the equivalence-confidence run. Iverilog is X-pessimistic by
        default, so uninitialized/undriven state propagates X (the point of GLS).
      - mode=test (top bring-up): scan_enable / TAP / MBIST vectors — chip-level
        test-mode bring-up that only exists at the integrated top.
      - scope=block vs top only changes the methodology note + which structures the
        testbench is expected to exercise.

    Inputs: `netlist` (gate/scan .v), `cell_models` (PDK cell Verilog sim models —
    path or list; REQUIRED so the standard-cell/scan masters simulate), a testbench
    (`testbench`/`testbench_files`), `top`/`tb_top`. Delegates the actual compile+run
    to the Icarus path, then annotates the CDE as a gate-level sanity run."""
    netlist = params.get("netlist")
    cell_models = params.get("cell_models") or params.get("cell_lib_verilog")
    if not netlist or not os.path.exists(str(netlist)):
        return _cde(objective="gate-level functional sanity", status="failed",
                    error="GLS requires a gate/scan `netlist` (existing path)",
                    validation={"verdict": "fail"})
    models = cell_models if isinstance(cell_models, list) else ([cell_models] if cell_models else [])
    models = [m for m in models if m and os.path.exists(str(m))]
    if not models:
        return _cde(
            objective="gate-level functional sanity", status="failed",
            signoff={"missing_cell_models": True, "tool_input_error": True,
                     "remediation": "GLS needs the PDK cell Verilog simulation models "
                     "(e.g. sky130_fd_sc_hd.v + the scan cell) via `cell_models` so the "
                     "standard-cell + scan masters simulate; supply a path/list."},
            error="GLS requires `cell_models` (PDK cell Verilog sim models); none resolved.",
            validation={"verdict": "fail"})
    mode = str(params.get("mode", "mission")).strip().lower()
    scope = str(params.get("scope", "block")).strip().lower()
    # Feed the Icarus sim path: cell models + netlist as rtl_files, TB passthrough.
    p2 = dict(params)
    p2["rtl"] = None
    p2["rtl_files"] = list(models) + [netlist] + list(params.get("rtl_files") or [])
    res = _run_sim(p2)
    # Annotate as a gate-level SANITY run (floor, not closure) with the methodology.
    res["objective"] = (f"gate-level functional sanity (GLS) of "
                        f"{params.get('top') or params.get('tb_top') or 'DUT'} "
                        f"(mode={mode}, scope={scope})")
    se = res.get("signoff_evidence")
    if not isinstance(se, dict):
        se = {}
    se.update({
        "gate_level_sanity": True, "mode": mode, "scope": scope,
        "scan_enable": ("inactive (mission mode)" if mode == "mission"
                        else "active / test-mode vectors"),
        "x_propagation": "Icarus X-pessimistic by default — uninitialized/undriven "
        "state propagates X (GLS catches X-init bugs LEC's 2-state proof cannot)",
        "coverage_role": "SANITY FLOOR, not coverage closure — functional coverage "
        "is closed once on RTL; GLS is a small directed confidence regression",
        "cell_models_loaded": models,
        "timing_gls": bool(params.get("sdf")),
        "sdf_note": (
            "TIMING GLS: SDF back-annotated (sdf_scope=%s, %s delays) -- glitches, "
            "races and at-speed failures are observable in this run"
            % (params.get("sdf_scope"), str(params.get("sdf_mtm", "max")).lower())
            if params.get("sdf") else
            "LOGICAL GLS: no SDF, so every gate is ZERO-DELAY. This run can prove "
            "X-init / reset hygiene but is structurally BLIND to glitches, races "
            "and at-speed failures. Supply `sdf` (from chip-sta write_sdf) + "
            "`sdf_scope` at the signoff corner for timing GLS."),
        "top_bring_up": ("TAP/boundary-scan + MBIST run-and-report + pad scan access"
                         if (scope == "top" and mode == "test") else None)})
    res["signoff_evidence"] = se
    asm = res.get("assumptions") or []
    asm.append("GLS is a gate-level SANITY run (directed, PASS-floor) — NOT functional "
               "coverage closure (closed on RTL); it catches X-init / (with SDF) "
               "timing/glitch issues that LEC's logical 2-state equivalence cannot.")
    res["assumptions"] = asm
    return res


def dispatch(params):
    s = params.get("scenario")
    if s in ("run_sim", "simulate", "functional_sim"):
        return _run_sim(params)
    if s in ("gls", "gate_level_sim", "gate_level_sanity", "gate_sim"):
        return _gls(params)
    if s in ("lint", "elaborate", "compile_check"):
        return _lint(params)
    return _cde(objective="functional verification", status="failed",
                error=f"unknown scenario '{s}'; supported: run_sim, gls, lint",
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
