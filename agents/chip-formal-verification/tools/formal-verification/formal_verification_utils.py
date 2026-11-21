#!/usr/bin/env python3
"""formal_verification_utils.py -- real SymbiYosys formal property verification.

Runs model checking of SystemVerilog `assert` properties through SymbiYosys
(`sby`): bounded model checking (`mode bmc`) with the smtbmc (z3) engine, or an
unbounded proof (`mode prove`) via k-induction plus `abc pdr` (property-directed
reachability). A counterexample is a fail. SymbiYosys is the standard open-source
formal front-end that drives Yosys + the SMT/PDR engines. Node-agnostic. Results
conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "formal-verification"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


def _is_ident(s):
    """True if *s* is a safe HDL/Tcl identifier -- blocks script injection via
    user-supplied module names interpolated into Yosys scripts."""
    return bool(s) and bool(re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", str(s)))


def _is_safe_filename(s):
    """True if *s* is a safe basename for interpolation into a Yosys/GHDL
    command string.  Allows alphanumeric, underscore, hyphen, and dot.
    Rejects whitespace, shell metacharacters, path separators, and '..'."""
    return (bool(s)
            and bool(re.match(r"^[A-Za-z0-9_.\-]+$", str(s)))
            and ".." not in str(s))


_VALID_VHDL_STDS = frozenset({"93", "93c", "08", "19"})
_VHDL_EXTS = frozenset({".vhd", ".vhdl"})


def _build_read_directives(basenames, top, vhdl_std="08"):
    """Build Yosys script lines for reading HDL source files.

    Routes .vhd/.vhdl files through the GHDL→Yosys frontend plugin and
    .v/.sv (and anything else) through ``read -formal``.  VHDL files are
    passed to a single ``ghdl`` command in the caller-supplied order
    (the VHDL analysis order must match dependency order).

    Returns a list of Yosys script lines (strings, no trailing newlines).

    Raises ``ValueError`` on unsafe filenames or invalid *vhdl_std*.
    """
    if vhdl_std not in _VALID_VHDL_STDS:
        raise ValueError(
            f"unsupported vhdl_std {vhdl_std!r}; allowed: {sorted(_VALID_VHDL_STDS)}")
    if not _is_ident(top):
        raise ValueError(f"invalid top identifier: {top!r}")
    read_lines = []
    vhdl_basenames = []
    for bn in basenames:
        if not _is_safe_filename(bn):
            raise ValueError(
                f"unsafe filename rejected (shell metacharacters / whitespace): {bn!r}")
        ext = os.path.splitext(bn)[1].lower()
        if ext in _VHDL_EXTS:
            vhdl_basenames.append(bn)
        else:
            read_lines.append(f"read -formal {bn}")
    if vhdl_basenames:
        ghdl_read = [
            # Requires the GHDL Yosys plugin (ghdl.so) in the container.
            # If missing, Yosys will error on 'plugin -i ghdl' with:
            #   ERROR: Can't load module `ghdl': ...
            # Ensure the formal-verification container image includes
            # yosys-ghdl-module (ghdl.so) at /usr/local/share/yosys/plugins/.
            "plugin -i ghdl",
            "ghdl --std=" + vhdl_std + " " + " ".join(vhdl_basenames)
            + f" -e {top}",
        ]
        read_lines = ghdl_read + read_lines
    return read_lines


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
        if (low.endswith((".log", ".tcl", ".ys", ".sh", ".do", ".smt2", ".vcd"))
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
          "- `logs/` \u2014 verbatim Yosys formal log and the exact run command", ""]
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


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def _yosys_version():
    try:
        out = subprocess.run(["yosys", "-V"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return txt.splitlines()[0] if txt else "yosys"
    except Exception:
        return "yosys"


def _cde(objective, status, results=None, signoff=None, assumptions=None,
         validation=None, provenance=None, inputs_ref=None, qor=None, error=None,
         vplan="shared_artifact"):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "SymbiYosys (sby)", "version": _yosys_version()}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": vplan,
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "bounded_model_check"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _stage_rtl(params):
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "dut.sv")
        open(p, "w").write(params["rtl"])
        files.append(p)
    files += [f for f in params.get("rtl_files", []) if os.path.exists(str(f))]
    return files


def _labelled_interpretation(interp):
    """Stamp the model-authored class/basis via the shared module (never a bare or)."""
    try:
        import metric_classes
    except Exception:
        # Degrade to an explicitly-labelled block rather than an unlabelled one:
        # an unclassified quantity is exactly what the contract forbids.
        base = dict(interp) if isinstance(interp, dict) and interp else {}
        base.setdefault("basis", "agent_read_of_formal_log"
                        if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(
        interp, basis="agent_read_of_formal_log")


def _crosscheck_interpretation(interp, measured):
    """Cross-check the model's count against the parsed one via the shared module.

    Delegates to catalog/tools/metric_classes.py (vendored into this build
    context by catalog/migrate_cde_progress.py). It lived here as a local copy
    until 2026-09-02, when a second tool needed it: two hand-maintained copies of
    the thing whose whole job is to CATCH disagreement is exactly the drift it
    exists to detect.

    If the shared module is unavailable the absence is RECORDED rather than
    swallowed -- a missing cross-check must never be indistinguishable from a
    passed one.
    """
    try:
        import metric_classes
    except Exception as exc:
        return {"checked": False,
                "reason": "metric_classes module unavailable (%s); the "
                          "cross-check did NOT run" % exc}
    return metric_classes.crosscheck_interpretation(
        interp, measured, "failing_properties")


def _static_property_counts(files):
    """Static (text-scan) counts of the property/assumption call sites in the
    RTL fed to sby, for the DX-145 progress obligations `property_work`
    (must show real work happened) and `source_assumptions` (assumption
    cells, `assume(...)`) -- and the `self_waivers`/`source_assertions`
    baseline (this tool never narrows a gating population from what it was
    given, so the honest, measured gap is 0 rather than an omitted key).

    Counts immediate-assertion call sites (`assert (`/`assert(`, the only
    style these designs use -- concurrent `assert property (...)` parses
    only in commercial front-ends per this agent's own CRITICAL RULES) and
    `assume(`/`assume (` call sites the same way. This is a REAL count of
    what is actually in the files sby elaborated, not a fabricated
    placeholder; a design with no assumes/no narrowing genuinely counts 0.
    """
    assert_re = re.compile(r"(?<![A-Za-z0-9_])assert\s*\(")
    assume_re = re.compile(r"(?<![A-Za-z0-9_])assume\s*\(")
    n_assert = n_assume = 0
    for f in files:
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        # Strip // line comments and /* */ block comments so a commented-out
        # example assert/assume is never counted as real property work.
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        text = re.sub(r"//.*", "", text)
        n_assert += len(assert_re.findall(text))
        n_assume += len(assume_re.findall(text))
    return n_assert, n_assume


def _obligation_results(files):
    """Shared DX-145 obligation-family fields, MEASURED (never fabricated),
    attached to every scenario's `results` block so `self_waivers`,
    `source_assumptions` and `property_work` never normalize to
    `not_assessable` for want of a bound key. `self_waivers`/
    `source_assertions` are set equal to the measured assertion-call-site
    count: this tool has no narrowing/exclusion logic at all, so the
    authored and gating populations are always identical here -- a real
    zero gap, not an assumed one."""
    n_assert, n_assume = _static_property_counts(files)
    return {
        "source_assumption_cells": n_assume,
        "property_work_count": n_assert,
        "self_waivers": 0,
        "source_assertions": n_assert,
        "gating_assertions": n_assert,
    }


def _persist_solver_evidence(mode, log):
    source = os.path.join(_WORK_DIR, mode)
    if os.path.isdir(source):
        destination = os.path.join(_OUTPUT_DIR, "solver_evidence", mode)
        shutil.copytree(source, destination, dirs_exist_ok=True)
        for root, _dirs, files in os.walk(destination):
            for name in files:
                if name.endswith(".vcd"):
                    path = os.path.join(root, name)
                    with open(path, encoding="utf-8", errors="replace") as stream:
                        print("NATIVE_WITNESS=" + os.path.relpath(path, _OUTPUT_DIR)
                              + "\n" + stream.read(65536), flush=True)
    print("NATIVE_SOLVER_LOG=" + log, flush=True)


def _prove(params):
    if not shutil.which("sby"):
        return _cde(objective="formal", status="failed",
                    error="sby (SymbiYosys) not found on PATH", validation={"verdict": "fail"})
    top = params.get("top")
    files = _stage_rtl(params)
    if not top or not files:
        return _cde(objective="formal", status="failed",
                    error="missing 'top' or RTL (rtl/rtl_files)", validation={"verdict": "fail"})
    if not _is_ident(top):
        return _cde(objective="formal", status="failed",
                    error=f"invalid 'top' identifier: {top!r}", validation={"verdict": "fail"})
    try:
        depth = int(params.get("depth", 20))
    except (TypeError, ValueError):
        depth = 20
    mode = str(params.get("mode", "bmc")).strip().lower()  # bmc | prove (k-induction)
    sby_mode = "prove" if mode in ("prove", "induct", "k-induction") else "bmc"
    vhdl_std = str(params.get("vhdl_std", "08")).strip()
    if vhdl_std not in _VALID_VHDL_STDS:
        vhdl_std = "08"
    # Copy RTL into the workdir by basename so the SymbiYosys [files] section can
    # reference them locally.
    file_lines = []
    for f in files:
        bn = os.path.basename(f)
        dst = os.path.join(_WORK_DIR, bn)
        try:
            if os.path.abspath(f) != os.path.abspath(dst):
                shutil.copyfile(f, dst)
        except Exception:
            pass
        file_lines.append(bn)
    try:
        read_lines = _build_read_directives(file_lines, top, vhdl_std=vhdl_std)
    except ValueError as exc:
        return _cde(objective=f"formal verification of {top}", status="failed",
                    error=str(exc), validation={"verdict": "fail"})
    # SymbiYosys engines: smtbmc (z3) is the general BMC/k-induction engine; add
    # abc pdr (IC3/property-directed reachability) for an unbounded `prove` so
    # sequential proofs that pure k-induction cannot close still converge.
    engines = "smtbmc z3\n" + ("abc pdr\n" if sby_mode == "prove" else "")
    sby_text = f"""[options]
mode {sby_mode}
depth {depth}

[engines]
{engines}
[script]
{chr(10).join(read_lines)}
prep -top {top}

[files]
{chr(10).join(file_lines)}
"""
    sp = os.path.join(_WORK_DIR, "formal.sby")
    open(sp, "w").write(sby_text)
    # -f overwrites the sby workdir (named after the .sby file: ./formal/).
    cmd = ["sby", "-f", sp]
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    # Fold the sby workdir logfile into the captured log for full provenance.
    sby_logfile = os.path.join(_WORK_DIR, "formal", "logfile.txt")
    if os.path.exists(sby_logfile):
        try:
            out += "\n\n===== sby logfile.txt =====\n" + open(sby_logfile).read()
        except Exception:
            pass
    open(os.path.join(_OUTPUT_DIR, "formal.log"), "w").write(out)
    open(os.path.join(_OUTPUT_DIR, "formal.sby"), "w").write(sby_text)
    _persist_solver_evidence("formal", out)
    # SymbiYosys prints a terminal `DONE (PASS|FAIL|UNKNOWN|ERROR, rc=N)` line and
    # exits 0 only on PASS. PASS/FAIL are valid analysis results; ERROR is a tool
    # error; UNKNOWN is inconclusive.
    passed = bool(re.search(r"DONE \(PASS", out))
    failed = bool(re.search(r"DONE \(FAIL", out))
    unknown = bool(re.search(r"DONE \(UNKNOWN", out))
    errored = bool(re.search(r"DONE \(ERROR", out))

    # ------------------------------------------------------------------
    # (A) GATING METRICS -- DETERMINISTIC AND FAIL-CLOSED.
    # ------------------------------------------------------------------
    # Parsed from sby's own output using patterns captured from REAL runs (a
    # deliberately-failing fixture plus a clean one), never from assumed
    # phrasing. THREE tools in this repo shipped regexes matching a string their
    # engine never prints -- chip-logic-synthesis (first-vs-last `stat`),
    # chip-sta (DRV), chip-lec ("N of M partitions proven") -- and each produced
    # a FALSE ABSENCE that downstream read as "not measurable" rather than "not
    # measured". Always verify a metric parser by replaying a real log.
    #
    # The two shapes sby actually emits:
    #   FAIL: "summary:   failed assertion <top>.<name> at <file>:<loc> step <N>"
    #         "engine_0: ##  0:00:00  Assert failed in <top>: <name>"
    #   PASS: "engine_0: Status returned by engine: pass"  + "DONE (PASS, rc=0)"
    #
    # *** A PASSING RUN NAMES NO PROPERTIES AT ALL, *** so the POPULATION is not
    # recoverable from a passing log. That is recorded honestly rather than
    # papered over with a fabricated denominator: a residual without its
    # population is not comparable across attempts (the Goodhart guard learned
    # on the LEC partition counts, where a changed denominator could make a
    # weaker proof look like progress).
    _failed_named = []
    for _m in re.finditer(
            r"failed assertion\s+(\S+?)\s+at\s+(\S+?)(?:\s+step\s+(\d+))?\s*$",
            out, re.M):
        _failed_named.append({"property": _m.group(1), "location": _m.group(2),
                              "step": int(_m.group(3)) if _m.group(3) else None})
    # sby's summary is repeated when the workdir logfile is folded in -- dedupe.
    _seen, _uniq = set(), []
    for _f in _failed_named:
        _k = (_f["property"], _f["location"], _f["step"])
        if _k not in _seen:
            _seen.add(_k)
            _uniq.append(_f)
    _failed_named = _uniq
    # Fallback when the summary block is absent but the engine line is present.
    _assert_failed = sorted(set(re.findall(r"Assert failed in \S+?:\s*(\S+)", out)))
    if not _failed_named and _assert_failed:
        _failed_named = [{"property": p, "location": None, "step": None}
                         for p in _assert_failed]

    # FAIL-CLOSED: emit a count ONLY where the terminal verdict makes it
    # meaningful. `None` means NOT ASSESSED and must never be read as zero --
    # "silence is not a pass", and a fabricated 0 on a formal gate is the single
    # most dangerous value this tool could emit.
    if passed:
        failing_properties = 0
    elif failed:
        # A FAIL that names no property is a PARSE GAP, not a clean result.
        failing_properties = len(_failed_named) or None
    else:
        failing_properties = None          # unknown / errored -> not assessed
    named_population = len(_failed_named) or None
    if errored and not (passed or failed):
        return _cde(objective=f"formal verification of {top}", status="failed",
                    error="SymbiYosys error; see formal.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"engine": "SymbiYosys (sby)", "log": "formal.log"})
    if failed and not passed:
        verdict, note = "fail", f"assertion violated within depth {depth} (counterexample)"
    elif passed:
        verdict, note = "pass", (
            "assertions proven unbounded (k-induction/PDR)" if sby_mode == "prove"
            else f"assertions hold to bounded depth {depth}")
    elif unknown:
        verdict, note = "review", "inconclusive (UNKNOWN); inspect formal.log"
    elif proc.returncode == 0:
        verdict, note = "pass", f"assertions hold to depth {depth}"
    else:
        verdict, note = "review", "inconclusive; inspect formal.log"
    status = "completed" if verdict in ("pass", "fail", "review") else "failed"
    return _cde(
        objective=f"formal ({'unbounded prove' if sby_mode == 'prove' else 'bounded BMC'}) "
                  f"verification of {top}",
        status=status,
        results={"proved": {"value": verdict == "pass", "unit": "bool"},
                 # GATING (deterministic, fail-closed). `null` = NOT ASSESSED,
                 # never "zero failures".
                 "failing_properties": {"value": failing_properties,
                                        "unit": "count",
                                        "class": "gating",
                                        "basis": "parsed_sby_summary"},
                 "depth": {"value": depth, "unit": "cycles"},
                 # DX-145: self_waivers/source_assumptions/property_work
                 # obligation-family evidence, measured from the same RTL
                 # this run actually elaborated (never fabricated).
                 **_obligation_results(files)},
        qor={"formal_verdict": verdict, "mode": sby_mode,
             "failing_properties": failing_properties},
        signoff={"verdict": verdict, "mode": sby_mode, "depth": depth,
                 "engine": "SymbiYosys (smtbmc z3" + (" + abc pdr" if sby_mode == "prove" else "") + ")",
                 # ----------------------------------------------------------
                 # (B) DIAGNOSTIC -- measured, non-gating. Exists to make
                 # in-stage debug possible: these are the numbers an agent
                 # reasons over when choosing the next setting. Nothing closes
                 # on them.
                 # ----------------------------------------------------------
                 "diagnostics": {
                     "class": "diagnostic",
                     "basis": "parsed_sby_summary",
                     "failing_property_names": [f["property"] for f in _failed_named],
                     "counterexamples": _failed_named,
                     "named_population": named_population,
                     # WHY THE POPULATION IS OFTEN null: sby names properties
                     # only when they FAIL. On a clean run nothing is named, so
                     # the denominator is genuinely unknown -- reported as such
                     # instead of invented.
                     "population_note": (
                         "sby names properties only on failure; a passing run "
                         "yields no population, so `named_population` is null "
                         "rather than fabricated"),
                     # THE LEVER READOUT: what was actually tried, so a later
                     # attempt can tell which knob moved and which did not.
                     "engines_used": ("smtbmc z3"
                                      + (" + abc pdr" if sby_mode == "prove" else "")),
                     "bounded": sby_mode == "bmc",
                     "inconclusive": bool(unknown),
                 },
                 # ----------------------------------------------------------
                 # (C) DESCRIPTIVE -- context that is SUPPOSED to hold steady.
                 # Kept separate because a constant that plateaus is NOT a
                 # stalled metric; conflating the two is what forced the
                 # name-heuristic (`_VIOLATION_HINTS`) in mine_attempt_chains.
                 # ----------------------------------------------------------
                 "descriptive": {
                     "class": "descriptive",
                     "basis": "run_configuration",
                     "sby_mode": sby_mode,
                     "depth_cycles": depth,
                     "rtl_file_count": len(file_lines),
                     "elapsed_s": round(elapsed, 3),
                     "note": "configuration/context, not a gate and not a "
                             "progress signal -- these are expected to be "
                             "stable across attempts",
                 },
                 # ----------------------------------------------------------
                 # (D) MODEL-AUTHORED INTERPRETATION -- the agent's read of the
                 # evidence above. LAYERED ON MEASUREMENT, NEVER SUBSTITUTED
                 # FOR IT.
                 # ----------------------------------------------------------
                 # A model reading the log is ROBUST to phrasing changes in a way
                 # a regex is not -- which is exactly why this layer exists. But
                 # it must never own a GATING number: a model asked "how many
                 # failed?" will answer a number even when it cannot tell, and a
                 # plausible-but-wrong count entering a gate is strictly worse
                 # than a missing one. It is also non-reproducible, and these
                 # envelopes are hash-chained.
                 # So the split is: the TOOL measures, the AGENT interprets, and
                 # `basis` makes which-is-which visible to a reviewer.
                 #
                 # The agent SHOULD populate `interpretation` when it can add
                 # signal the parser cannot -- e.g. whether a counterexample is
                 # a real design defect or an unconstrained-input artifact, and
                 # which lever to try next. It is OPTIONAL: absent means "not
                 # offered", which is honest. It is ADVISORY-ONLY: nothing in
                 # the gate, the residual, or the stall rule may read it.
                 #
                 # `_labelled_interpretation` (NOT a bare `or` default): an
                 # agent-supplied block used to bypass the default entirely, so
                 # the very case that NEEDS the label -- a real model-authored
                 # reading -- shipped without `class`/`basis`. Caught by the
                 # contract checker on a live run 2026-09-02.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 # CROSS-CHECK: when the agent also reports a count the parser
                 # computed, disagreement is HIGH-VALUE SIGNAL -- it means either
                 # the parser is stale (the DX-60/DX-55 class) or the model is
                 # confabulating, and a reviewer needs to know which. Recorded,
                 # never auto-resolved.
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), failing_properties),
                 "report": "formal.log"},
        inputs_ref={"rtl_files": files},
        assumptions=[f"SymbiYosys {sby_mode} to depth {depth}; a bmc pass is bounded, "
                     "an unbounded proof requires mode=prove (k-induction/PDR) to succeed"],
        validation={"verdict": verdict, "note": note},
        provenance={"yosys": _yosys_version(), "engine": "SymbiYosys (sby)",
                    "runtime_s": round(elapsed, 3), "log": "formal.log"},
    )


def _unreached_cover_names(log):
    summary = "\n".join(line.split("] summary: ", 1)[-1] for line in log.splitlines())
    match = re.search(r"unreached cover statements:\n((?:  .+\n?)+)", summary)
    if match:
        return sorted(set(re.findall(r"^\s+(\S+) at \S+", match.group(1), re.M)))
    return sorted(set(
        top + "." + name for top, name in re.findall(
            r"Unreached cover statement at (\S+):[^\n]*\(([^()\n]+)\)", log)))


def _cover(params):
    """DX-145: EXECUTE an SBY `mode cover` run and report real cover-target
    reachability, so `vacuity`/`unreached_antecedent_covers` bind to
    EXECUTED cover-mode evidence rather than normalizing to
    `not_assessable`. A `cover(...)` statement that sby cannot reach is
    exactly an unreached antecedent/vacuity witness: if the guarding
    condition of a gated assert can never be true, the assert is proved
    vacuously and the corresponding cover for that condition never fires.
    This is a SEPARATE sby run from `_prove` (cover and bmc/prove are
    different sby `mode`s); tool presence and exit 0 are not evidence, so
    the reached/unreached counts below are parsed from this run's own log,
    never assumed from the bmc/prove result.
    """
    if not shutil.which("sby"):
        return _cde(objective="formal cover", status="failed",
                    error="sby (SymbiYosys) not found on PATH", validation={"verdict": "fail"})
    top = params.get("top")
    files = _stage_rtl(params)
    if not top or not files:
        return _cde(objective="formal cover", status="failed",
                    error="missing 'top' or RTL (rtl/rtl_files)", validation={"verdict": "fail"})
    if not _is_ident(top):
        return _cde(objective="formal cover", status="failed",
                    error=f"invalid 'top' identifier: {top!r}", validation={"verdict": "fail"})
    try:
        depth = int(params.get("depth", 20))
    except (TypeError, ValueError):
        depth = 20
    vhdl_std = str(params.get("vhdl_std", "08")).strip()
    if vhdl_std not in _VALID_VHDL_STDS:
        vhdl_std = "08"
    file_lines = []
    for f in files:
        bn = os.path.basename(f)
        dst = os.path.join(_WORK_DIR, bn)
        try:
            if os.path.abspath(f) != os.path.abspath(dst):
                shutil.copyfile(f, dst)
        except Exception:
            pass
        file_lines.append(bn)
    try:
        read_lines = _build_read_directives(file_lines, top, vhdl_std=vhdl_std)
    except ValueError as exc:
        return _cde(objective=f"formal cover of {top}", status="failed",
                    error=str(exc), validation={"verdict": "fail"})
    sby_text = f"""[options]
mode cover
depth {depth}

[engines]
smtbmc z3

[script]
{chr(10).join(read_lines)}
prep -top {top}

[files]
{chr(10).join(file_lines)}
"""
    sp = os.path.join(_WORK_DIR, "cover.sby")
    open(sp, "w").write(sby_text)
    # sby names the workdir after the .sby file (`cover/`) -- kept distinct
    # from `_prove`'s `formal/` workdir so a stage running both in the same
    # /workdir never has one overwrite the other.
    cmd = ["sby", "-f", sp]
    t0 = time.time()
    _save_run_command(cmd, name="run_command_cover.txt")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    sby_logfile = os.path.join(_WORK_DIR, "cover", "logfile.txt")
    if os.path.exists(sby_logfile):
        try:
            out += "\n\n===== sby logfile.txt =====\n" + open(sby_logfile).read()
        except Exception:
            pass
    open(os.path.join(_OUTPUT_DIR, "cover.log"), "w").write(out)
    open(os.path.join(_OUTPUT_DIR, "cover.sby"), "w").write(sby_text)
    _persist_solver_evidence("cover", out)
    passed = bool(re.search(r"DONE \(PASS", out))
    errored = bool(re.search(r"DONE \(ERROR", out))
    if errored and not passed:
        return _cde(objective=f"formal cover of {top}", status="failed",
                    error="SymbiYosys cover error; see cover.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"engine": "SymbiYosys (sby)", "log": "cover.log"})
    # sby's summary block (see sby_core.py `_summary`) prints one
    # "reached cover statement <hdlname> at <loc>" line per witness trace,
    # and -- ONLY when the run did not fully PASS -- an
    # "unreached cover statements:" header followed by "  <hdlname> at <loc>"
    # lines for every cover point sby's own design hierarchy marks
    # UNKNOWN/FAIL. Parsed from a REAL run's log, captured against this
    # design (bsum16_checker.sv, 8/8 reached) 2026-09-25 -- never assumed
    # phrasing.
    reached_names = sorted(set(re.findall(
        r"reached cover statement (\S+) at \S+", out)))
    unreached_names = _unreached_cover_names(out)
    cover_targets_reached = len(reached_names)
    cover_targets_unreached = 0 if passed else len(unreached_names)
    if passed:
        verdict, note = "pass", (
            f"{cover_targets_reached}/{cover_targets_reached} cover targets "
            "reached within depth %d (0 unreached -- no vacuity witness)" % depth)
    elif cover_targets_unreached:
        verdict, note = "fail", (
            f"{cover_targets_unreached} cover target(s) unreached within depth "
            f"{depth}: a guarding antecedent may be vacuously unsatisfiable")
    else:
        verdict, note = "review", "cover run inconclusive; inspect cover.log"
    status = "completed" if verdict in ("pass", "fail", "review") else "failed"
    return _cde(
        objective=f"formal cover-mode reachability check of {top}",
        status=status,
        results={
            "cover_targets_reached": {"value": cover_targets_reached,
                                      "unit": "count", "class": "gating",
                                      "basis": "parsed_sby_cover_summary"},
            "cover_targets_unreached": {"value": cover_targets_unreached,
                                       "unit": "count", "class": "gating",
                                       "basis": "parsed_sby_cover_summary"},
            # `vacuity`/`unreached_antecedent_covers` obligation families
            # (catalog/tools/cde_progress.py) both check this exact key
            # first -- a cover point sby's own reachability search could
            # never reach IS the unreached-antecedent/vacuity witness.
            "unreached_antecedent_covers": cover_targets_unreached,
            "vacuous_count": cover_targets_unreached,
            "depth": {"value": depth, "unit": "cycles"},
            "reached_cover_names": reached_names,
            "unreached_cover_names": unreached_names,
            **_obligation_results(files),
        },
        qor={"cover_verdict": verdict, "cover_targets_reached": cover_targets_reached,
             "cover_targets_unreached": cover_targets_unreached},
        signoff={"verdict": verdict, "mode": "cover", "depth": depth,
                 "engine": "SymbiYosys (smtbmc z3)",
                 "cover_targets_reached": cover_targets_reached,
                 "cover_targets_unreached": cover_targets_unreached,
                 "report": "cover.log"},
        inputs_ref={"rtl_files": files},
        assumptions=[f"SymbiYosys cover-mode reachability search to depth {depth}; "
                     "an unreached cover point within this bound is reported as a "
                     "vacuity/unreached-antecedent witness, not proved unreachable "
                     "beyond depth {0}".format(depth)],
        validation={"verdict": verdict, "note": note},
        provenance={"yosys": _yosys_version(), "engine": "SymbiYosys (sby)",
                    "runtime_s": round(elapsed, 3), "log": "cover.log"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("prove", "bmc", "formal_check"):
        return _prove(params)
    if s in ("cover", "cover_reachability", "vacuity"):
        return _cover(params)
    return _cde(objective="formal verification", status="failed",
                error=f"unknown scenario '{s}'; supported: prove, cover",
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
