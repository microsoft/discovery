#!/usr/bin/env python3
"""cts_utils.py -- real OpenROAD TritonCTS clock-tree synthesis.

Reads node LEF/Liberty + a placed DEF + SDC, runs clock_tree_synthesis, re-legalizes,
reports clock skew and insertion delay, writes a post-CTS DEF. Clock buffers come
from the PDK binding. Node-aware. Results conform to the Common Design Envelope.

INSERTION DELAY IS ALWAYS MEASURED; IT GATES ONLY IF A BUDGET IS DECLARED.
Until 2026-09-08 this docstring was aspirational: nothing here ever produced an
insertion-delay number, so a stage whose gate said "insertion delay within budget"
could never satisfy it from tool output. The metric is now emitted unconditionally
(`report_clock_latency` -> cts_latency.rpt), and `insertion_delay_budget_ns`
(binding or params) decides whether it gates. Three outcomes, kept distinct:
  * budget declared    -> pass / fail against it
  * no budget declared -> `not_gating`, WITH the measured number
  * not measured       -> `not_assessable`, which is never compliance
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "cts"
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
        _output_hashes = {}
        if os.path.isdir(_OUTPUT_DIR):
            for _name in os.listdir(_OUTPUT_DIR):
                _path = os.path.join(_OUTPUT_DIR, _name)
                if os.path.isfile(_path) and _name != "common_design_envelope.json":
                    _h = _hash_input_file(_path)
                    if _h:
                        _output_hashes[_name] = _h
        if _output_hashes:
            prov.setdefault("output_hashes", _output_hashes)
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


def _stage_policy(binding):
    policy = binding.get("tool_policy", {}) if isinstance(binding, dict) else {}
    stage = policy.get("cts", {})
    return stage.get("settings", stage) if isinstance(stage, dict) else {}


def _resolve(params, policy, key, default=None):
    if key in params and params[key] is not None:
        return params[key], "caller"
    if key in policy and policy[key] is not None:
        return policy[key], "pdk_binding.tool_policy"
    return default, "tool_default"


def _resolve_binding_fallback(params, policy, binding, key, binding_value):
    if key in params and params[key] is not None:
        return params[key], "caller"
    if key in policy and policy[key] is not None:
        return policy[key], "pdk_binding.tool_policy"
    if binding_value is not None:
        return binding_value, "pdk_binding"
    return None, "missing"


def _count_masters_in_def(def_path, masters):
    """Count DEF component instances whose master is one of `masters`.

    The former diagnostic regex-escaped the JOINED buffer-name string and
    searched the DEF for it as ONE literal. A DEF never contains the caller's
    separators or braces, so the count was 0 on every multi-size buffer list --
    a second wrong number sitting next to a passing verdict, readable as "CTS
    inserted no buffers at all". Counts per master instead.
    """
    if not masters or not os.path.exists(def_path):
        return None
    try:
        with open(def_path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    total = 0
    for master in masters:
        total += len(re.findall(
            r"^\s*-\s+\S+\s+" + re.escape(str(master)) + r"(?![\w$])",
            text, re.M))
    return total


def _parse_inserted_cells(log_text):
    """[(instance, master), ...] for every instance CTS added, from the census."""
    return [(m.group(1), m.group(2)) for m in re.finditer(
        r"^__CTS_NEW__\s+(\S+)\s+(\S+)\s*$", log_text or "", re.M)]


def _buffer_name_list(value):
    """Normalize a clock-buffer spec into a plain list of cell names.

    Accepts the binding's native JSON array, a bare space-separated string, and
    the pre-braced Tcl-list string callers adopted as a workaround for the
    unbraced-`-buf_list` crash. Braces are stripped here so the single brace
    added at the call site cannot become a double brace.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(x) for x in value]
    else:
        items = str(value).replace("{", " ").replace("}", " ").split()
    return [name for name in (item.strip() for item in items) if name]


def _load_design(params, binding, objective):
    def_file, odb_file = params.get("def_file"), params.get("odb_file")
    if bool(def_file) == bool(odb_file):
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none",
            error="provide exactly one of 'def_file' or 'odb_file'",
            validation={"verdict": "fail"})
    source = odb_file or def_file
    if not os.path.exists(str(source)):
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none", error=f"input not found: {source}",
            validation={"verdict": "fail"})
    libs = _as_list(params.get("liberty") or binding.get("liberty"))
    if not libs:
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none",
            error="missing required field 'liberty' (check pdk_binding)",
            validation={"verdict": "fail"})
    for path in libs:
        if not os.path.exists(str(path)):
            return None, None, _cde(objective=objective, status="failed",
                pdk_binding=binding or "none", error=f"input not found: {path}",
                validation={"verdict": "fail"})
    lib_reads = "\n".join(f"read_liberty {{{p}}}" for p in libs)
    if odb_file:
        return lib_reads + f"\nread_db {{{odb_file}}}", {
            "odb_file": odb_file, "liberty": libs}, None
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    if not tech_lef:
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none", error="missing required field 'tech_lef' (check pdk_binding)",
            validation={"verdict": "fail"})
    for path in [tech_lef] + cell_lefs:
        if not os.path.exists(str(path)):
            return None, None, _cde(objective=objective, status="failed",
                pdk_binding=binding or "none", error=f"input not found: {path}",
                validation={"verdict": "fail"})
    collision = _check_lef_collisions([tech_lef] + cell_lefs)
    if collision:
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none", error=collision,
            validation={"verdict": "fail"})
    lef_reads = "\n".join([f"read_lef {{{tech_lef}}}"] +
                            [f"read_lef {{{p}}}" for p in cell_lefs])
    return lib_reads + "\n" + lef_reads + f"\nread_def {{{def_file}}}", {
        "def_file": def_file, "tech_lef": tech_lef, "cell_lef": cell_lefs,
        "liberty": libs}, None


def _run_script(script, stem):
    sp = os.path.join(_OUTPUT_DIR, stem + ".tcl")
    with open(sp, "w", encoding="utf-8") as f:
        f.write(script)
    t0 = time.time()
    _save_run_command(["openroad", "-exit", sp])
    proc = subprocess.run(["openroad", "-exit", sp], capture_output=True,
                          text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    with open(os.path.join(_OUTPUT_DIR, stem + ".log"), "w", encoding="utf-8") as f:
        f.write(out)
    return proc, out, elapsed


# --- vendored: supply reconnect after cell insertion -------------------------
# OpenROAD does NOT attach the power/ground pins of a cell it inserts. Measured
# on crc16_ccitt: clock_tree_synthesis added 8 buffers and left all 32 of their
# supply pins unconnected while the rails stayed perfectly intact 2 -> 2, and
# `check_power_grid` passed anyway because it audits the GRID, not each
# instance attachment to it. Those cells are dead.
#
# `global_connect` ALONE IS NOT ENOUGH, and this was measured rather than
# assumed: it replays add_global_connection RULES, which live in the ODB. When
# a stage is handed an .odb the rules survive and global_connect repairs all 36
# pins; when it is handed a .def -- which is what the packaged tools take --
# the rules do not exist and global_connect is a silent NO-OP (32 unconnected
# before, 32 after).
#
# So the supply nets are DERIVED FROM THE DESIGN instead: the single special
# POWER net and single special GROUND net that carry SWIRE geometry. No net
# name is hard-coded, so this stays node-portable. When the design has no rails
# (a legitimate pre-PDN flow) or more than one rail per polarity (multi-voltage,
# where the correct domain is a matter of power INTENT and cannot be inferred
# from geometry), it SKIPS and says so rather than guessing -- a wrong supply
# domain is worse than an unconnected pin, and the continuity gate still
# reports whatever remains unconnected.
_PG_RECONNECT_TCL = (
    "set _rc_b [ord::get_db_block]\n"
    "set _rc_pwr {}\n"
    "set _rc_gnd {}\n"
    "foreach _rc_n [$_rc_b getNets] {\n"
    "  if {![$_rc_n isSpecial] || [llength [$_rc_n getSWires]] == 0} { continue }\n"
    "  set _rc_t [$_rc_n getSigType]\n"
    "  if {$_rc_t == \"POWER\"} { lappend _rc_pwr $_rc_n } elseif {$_rc_t == \"GROUND\"} { lappend _rc_gnd $_rc_n }\n"
    "}\n"
    "set _rc_fixed 0\n"
    "if {[llength $_rc_pwr] == 1 && [llength $_rc_gnd] == 1} {\n"
    "  set _rc_pn [lindex $_rc_pwr 0]\n"
    "  set _rc_gn [lindex $_rc_gnd 0]\n"
    "  foreach _rc_i [$_rc_b getInsts] {\n"
    "    foreach _rc_it [$_rc_i getITerms] {\n"
    "      set _rc_st [[$_rc_it getMTerm] getSigType]\n"
    "      if {$_rc_st != \"POWER\" && $_rc_st != \"GROUND\"} { continue }\n"
    "      if {[$_rc_it getNet] != \"NULL\"} { continue }\n"
    "      if {$_rc_st == \"POWER\"} { odb::dbITerm_connect $_rc_it $_rc_pn } else { odb::dbITerm_connect $_rc_it $_rc_gn }\n"
    "      incr _rc_fixed\n"
    "    }\n"
    "  }\n"
    "  puts \"__PG_RECONNECT__ status=applied power=[$_rc_pn getName] ground=[$_rc_gn getName] connected=$_rc_fixed\"\n"
    "} else {\n"
    "  puts \"__PG_RECONNECT__ status=skipped power_rails=[llength $_rc_pwr] ground_rails=[llength $_rc_gnd] connected=0\"\n"
    "}\n")


def _parse_pg_reconnect(out):
    """Parse the __PG_RECONNECT__ marker. None when the marker is absent, so an
    old log reads as NOT ATTEMPTED rather than as a clean zero."""
    import re as _re
    m = _re.search(r"__PG_RECONNECT__ status=(\w+)"
                   r"(?: power=(\S+) ground=(\S+))?"
                   r"(?: power_rails=(\d+) ground_rails=(\d+))?"
                   r" connected=(\d+)", out)
    if not m:
        return None
    return {"status": m.group(1),
            "power_net": m.group(2), "ground_net": m.group(3),
            "power_rails": int(m.group(4)) if m.group(4) is not None else None,
            "ground_rails": int(m.group(5)) if m.group(5) is not None else None,
            "pins_reconnected": int(m.group(6))}


def _parse_pdn_continuity(out):
    """Parse the __PDN_IN__/__PDN_OUT__ pair into a continuity record.

    Returns None when either marker is missing, so an old log reads as NOT
    MEASURED rather than as a clean pass -- absence of the probe must never be
    reportable as "power nets are fine".

    Everything keys on RAILS (special power/ground nets that carry SWIRE
    geometry), not on the raw POWER/GROUND sigtype count. Measured: a design
    with no PDN at all still reports one GROUND-typed net, because the tie-low
    net `zero_` carries that sigtype. Keying on sigtype reported "1 power net
    preserved" for a design that cannot be powered.

    `destroyed` is deliberately narrow: rails ENTERED and fewer LEFT. A design
    that arrives with none cannot have them destroyed here, and is reported
    through `absent` instead, because a flow that builds its PDN after
    placement is legitimate and must not be failed.

    UNCONNECTED SUPPLY PINS are tracked separately, because an intact grid does
    NOT mean every cell reaches it. Measured on crc16_ccitt: the rails survived
    every stage 2 -> 2 while CTS's 8 new clock buffers and the tie cell sat with
    all 4 supply pins unattached (0 -> 32 -> 36). `check_power_grid` still
    passed, since it audits the grid, not each instance's attachment to it.
    OpenROAD's global connection RULES persist in the ODB, so any stage that
    inserts cells must re-run `global_connect`; none did.

    `unpowered_created` fires only when THIS stage increased the count, mirroring
    `destroyed`. A pre-existing count is disclosed, not failed -- the stage that
    introduced it is the one that should answer for it. On a design with no PDN
    every supply pin is unconnected by definition (measured: 1410 on crc16_ccitt
    pre-PDN), so the flag is suppressed entirely when no rails entered.
    """
    mi = re.search(r"__PDN_IN__\s+pg=(\d+)\s+rail=(\d+)(?:\s+unc=(\d+))?", out)
    mo = re.search(r"__PDN_OUT__\s+pg=(\d+)\s+rail=(\d+)(?:\s+unc=(\d+))?", out)
    if not mi or not mo:
        return None
    pg_in, rail_in = int(mi.group(1)), int(mi.group(2))
    pg_out, rail_out = int(mo.group(1)), int(mo.group(2))
    # A log predating the unc= probe reads as NOT MEASURED, never as zero.
    unc_in = int(mi.group(3)) if mi.group(3) is not None else None
    unc_out = int(mo.group(3)) if mo.group(3) is not None else None
    unc_measured = unc_in is not None and unc_out is not None
    return {
        "measured": True,
        "pg_nets_in": pg_in, "pg_nets_out": pg_out,
        "rails_in": rail_in, "rails_out": rail_out,
        "destroyed": rail_in > 0 and rail_out < rail_in,
        "absent": rail_in == 0,
        "preserved": rail_in > 0 and rail_out >= rail_in,
        "unconnected_measured": unc_measured,
        "unconnected_pg_pins_in": unc_in,
        "unconnected_pg_pins_out": unc_out,
        "unpowered_created": bool(
            unc_measured and rail_in > 0 and unc_out > unc_in),
        "unpowered_pre_existing": bool(
            unc_measured and rail_in > 0 and unc_in > 0),
        "note": ("a rail is a SPECIAL power/ground net carrying SWIRE "
                 "geometry; POWER/GROUND sigtype alone also matches tie-off "
                 "nets such as `zero_` and does not mean the design is "
                 "powerable"),
    }


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD TritonCTS", "version": "openroad"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "skew_analysis"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _check_lef_collisions(lef_paths):
    """Detect FATAL LEF MACRO double-definitions across the given LEF files.

    OpenROAD's read_lef does not de-duplicate cell MACRO definitions: if the same
    cell MACRO name is defined by more than one LEF, the collision can drop
    masters downstream (e.g. 'clkinv_1 not found'). This most often happens when a
    merged/complete LEF (which already contains the standard cells) is passed
    together with a separate tech + cell LEF. Duplicate SITE (and VIARULE)
    definitions are NOT fatal -- OpenROAD keeps the first identical definition and
    only logs ODB-0394 -- and many PDK tech+cell LEF pairs legitimately define the
    same SITEs in both files, so they are ignored here. Return a human-readable
    error naming the colliding MACROs, or None if the LEF set is clean."""
    import re as _re
    lefs = [str(p) for p in lef_paths if p]
    seen = {}          # object name -> first realpath that defined it
    collide = {}       # object name -> set of realpaths
    obj_re = _re.compile(r"^\s*(MACRO|SITE)\s+(\S+)", _re.MULTILINE)
    reals = []
    for p in lefs:
        rp = os.path.realpath(p)
        if rp in reals:
            return "duplicate LEF passed more than once: " + p
        reals.append(rp)
        try:
            with open(p, "r", errors="ignore") as _f:
                txt = _f.read()
        except Exception:
            continue
        for kind, name in obj_re.findall(txt):
            # Only a duplicate MACRO is fatal: OpenROAD can drop a colliding cell
            # master downstream ('clkinv_1 not found'). A duplicate SITE (or
            # VIARULE) is benign -- OpenROAD keeps the first identical definition
            # and merely logs ODB-0394. Many PDK tech+cell LEF pairs (e.g. sky130A
            # unithd/unithddbl) legitimately define the SITEs in BOTH files, so
            # treating a SITE overlap as fatal is a false positive that blocks
            # every physical stage. Screen MACRO collisions only.
            if kind != "MACRO":
                continue
            if name in seen and seen[name] != rp:
                collide.setdefault(name, {seen[name]})
                collide[name].add(rp)
            else:
                seen[name] = rp
    if collide:
        names = sorted(collide)
        shown = ", ".join(names[:5]) + ("" if len(names) <= 5 else " (+%d more)" % (len(names) - 5))
        return ("LEF double-define: object(s) " + shown + " are defined in more than "
                "one of the supplied LEFs; pass the merged LEF ONCE as tech_lef with "
                "NO separate cell_lef so cell masters are not dropped")
    return None


def _clock_wire_rc(params, binding, policy):
    """Use declared clock RC layers before CTS, never the engine's zero default."""
    routing = binding.get("routing_layers") or {}
    settings = {}
    script = ""
    for kind in ("signal", "clock"):
        key = "wire_rc_%s_layer" % kind
        layer, source = _resolve(params, policy, key, routing.get(key))
        if not layer:
            if kind == "clock":
                raise ValueError("missing wire_rc_clock_layer for clock-tree characterization; "
                                 "supply caller, tool_policy.cts, or binding routing-layer intent")
            continue
        if not isinstance(layer, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", layer):
            raise ValueError(key + " must be one routing-layer name")
        settings[key] = {"layer": layer, "source": source}
        script += "set_wire_rc -%s -layer {%s}\n" % (kind, layer)
    return script, settings


def _cts(params):
    if not shutil.which("openroad"):
        return _cde(objective="CTS", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    top, sdc = params.get("top"), params.get("sdc")
    binding = params.get("pdk_binding") or {}
    loader, inputs, failure = _load_design(params, binding, "CTS")
    if failure:
        return failure
    policy = _stage_policy(binding)
    try:
        wire_rc, wire_rc_settings = _clock_wire_rc(params, binding, policy)
    except ValueError as error:
        return _cde(objective="CTS", status="failed", pdk_binding=binding or "none",
                    error=str(error), validation={"verdict": "fail"})
    clkbuf, clkbuf_source = _resolve_binding_fallback(
        params, policy, binding, "clock_buffer",
        binding.get("clock_buffer") or binding.get("clock_buffers"))
    approved_buffers = _buffer_name_list(clkbuf)
    # `-buf_list` takes ONE Tcl list. A bare space-separated string is parsed as
    # `-buf_list <first>` plus N-1 stray positional args, and OpenSTA fails the
    # whole run closed with STA-0564 -- which is exactly what the binding's own
    # native `clock_buffers` array produced. Rebuild the braced form from the
    # parsed names so a caller who already pre-braced it (the historical
    # workaround) is not double-braced.
    clkbuf = " ".join(approved_buffers)
    clkbuf_tcl = "{" + clkbuf + "}" if approved_buffers else ""
    for n, v in (("top", top), ("sdc", sdc), ("clock_buffer", clkbuf)):
        if not v:
            return _cde(objective="CTS", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}' (check pdk_binding)",
                        validation={"verdict": "fail"})
    for p in [sdc]:
        if not os.path.exists(str(p)):
            return _cde(objective="CTS", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    out_def = os.path.join(_OUTPUT_DIR, "cts.def")
    out_odb = os.path.join(_OUTPUT_DIR, "cts.odb")
    skew_rpt = os.path.join(_OUTPUT_DIR, "cts_skew.rpt")
    latency_rpt = os.path.join(_OUTPUT_DIR, "cts_latency.rpt")
    # Clock-tree quality levers. root_buf selects the top-of-tree driver;
    # sink_clustering_* tune local buffering; obstruction_aware and
    # macro_clustering_* matter for designs with macros / hierarchy.
    _cts_opts = ""
    _root_buf, root_source = _resolve(params, policy, "root_buffer_cell", None)
    if _root_buf:
        _cts_opts += f" -root_buf {_root_buf}"
    _sc_size, sc_size_source = _resolve(params, policy, "sink_clustering_size", None)
    if _sc_size is not None:
        _cts_opts += f" -sink_clustering_size {int(_sc_size)}"
    _sc_diam, sc_diam_source = _resolve(params, policy, "sink_clustering_max_diameter", None)
    if _sc_diam is not None:
        _cts_opts += f" -sink_clustering_max_diameter {_sc_diam}"
    if str(params.get("obstruction_aware", "")).lower() in ("1", "true", "yes"):
        _cts_opts += " -obstruction_aware"
    # SINK CLUSTERING -- NOW A CALLER-FACING SWITCH, NOT A HARDCODED FLAG.
    # `-sink_clustering_enable` turns on TritonCTS's dummy-load balancing, which
    # is the feature that reaches OUTSIDE `-buf_list` for a load cell. It was
    # appended unconditionally with no `params.get()` gate, so a caller who hit
    # an unapproved dummy-load master had no off-switch even in principle --
    # measured across four parameter configurations, all producing the identical
    # unapproved master at identical coordinates. Default stays enabled so
    # existing recipes are unchanged.
    _sink_clustering = str(
        params.get("sink_clustering_enable", True)).strip().lower() not in (
            "0", "false", "no", "off")
    if _sink_clustering:
        _cts_opts += " -sink_clustering_enable"
    # hierarchy_mode=hierarchical enables macro clustering knobs for
    # macro-dominated / block-level clock trees.
    hierarchy_mode = str(params.get("hierarchy_mode", "flat")).strip().lower()
    if hierarchy_mode == "hierarchical":
        _mc_size = params.get("macro_clustering_size")
        if _mc_size is not None:
            _cts_opts += f" -macro_clustering_size {int(_mc_size)}"
        _mc_diam = params.get("macro_clustering_max_diameter")
        if _mc_diam is not None:
            _cts_opts += f" -macro_clustering_max_diameter {_mc_diam}"
    # Do NOT call `remove_fillers` here. It is broader than its name suggests:
    # OpenROAD
    # selects fillers by LEF CLASS, and in sky130_fd_sc_hd both `__fill_*` and
    # `__decap_*` (including the decap_3 used as endcap_master) are CORE SPACER,
    # so it deletes fixed boundary endcaps too -- not just movable fill. Removing
    # a cell
    # un-merges the abutted n-well/implant shapes on either side of the hole,
    # which is a real FEOL DRC error (sky130 nwell.2a is "min nwell spacing
    # (merged if less)"). Incident 2026-08-31: cell fill ran BEFORE CTS, this
    # line deleted all 318 filler/decap instances, and the final layout carried
    # 151 un-waived KLayout FEOL nwell/hvtp violations.
    #
    # THE FIX IS ORDERING, NOT A CHANGE HERE: cell fill now runs AFTER routing
    # (stage `decapfill`, matching ORFS `5_3_fillcell`, which consumes
    # `5_2_route.odb`). Routing itself runs `repair_antennas` + a further
    # `detailed_placement`, so filling any earlier -- including immediately
    # after CTS -- would block antenna-diode insertion. A pre-filled legacy input
    # must fail legalization rather than silently losing physical-only cells.
    # --- POWER-NET CONTINUITY (see chip-placement for the full incident) -----
    #
    # On crc16_ccitt the PDN stage produced a design with two supply rails and
    # placement was handed the PRE-PDN tapcell odb instead, so pdn.1 was a
    # dead-end branch. CTS, routing, metal-fill, decap-fill and ECO then all
    # ran and reported SUCCESS on a design that could never be power-connected;
    # the loss surfaced only at routing.2's final artifact inspection.
    #
    # Measured here: CTS PRESERVES rails when given them (2 in -> 2 out through
    # clock_tree_synthesis + remove_fillers + detailed_placement). So this
    # stage is a CARRIER, not the destroyer -- and the defect is that it had no
    # power-net inspection at all and so could not say what it was handed.
    #
    # A rail is a SPECIAL power/ground net carrying SWIRE geometry. Sigtype
    # alone is NOT sufficient: measured on this campaign's own cts.odb, the
    # tie-low net `zero_` carries GROUND sigtype, so counting sigtype scored 1
    # on a design with no PDN whatsoever.
    _pdn_probe = (
        "set _b [ord::get_db_block]\n"
        "set _pg 0\n"
        "set _rail 0\n"
        "set _unc 0\n"
        "foreach _n [$_b getNets] {\n"
        "  set _t [$_n getSigType]\n"
        "  if {$_t != \"POWER\" && $_t != \"GROUND\"} { continue }\n"
        "  incr _pg\n"
        "  if {[$_n isSpecial] && [llength [$_n getSWires]] > 0} { incr _rail }\n"
        "}\n"
        "foreach _i [$_b getInsts] {\n"
        "  foreach _it [$_i getITerms] {\n"
        "    set _st [[$_it getMTerm] getSigType]\n"
        "    if {$_st != \"POWER\" && $_st != \"GROUND\"} { continue }\n"
        "    if {[$_it getNet] == \"NULL\"} { incr _unc }\n"
        "  }\n"
        "}\n")
    _pdn_in = _pdn_probe + "puts \"__PDN_IN__ pg=$_pg rail=$_rail unc=$_unc\"\n"
    _pdn_out = _pdn_probe + "puts \"__PDN_OUT__ pg=$_pg rail=$_rail unc=$_unc\"\n"
    # CTS INSERTS CELLS, so it must re-attach them to the supply nets. Measured
    # on crc16_ccitt: clock_tree_synthesis added 8 buffers and every one of
    # their 4 supply pins was left unconnected -- 0 -> 32 dead pins on a design
    # whose rails were fully intact. See _PG_RECONNECT_TCL for why
    # `global_connect` alone does not fix this on a DEF-sourced design.
    _reconnect = _PG_RECONNECT_TCL
    # INSERTED-CELL CENSUS -- taken in Tcl, not by text-diffing two DEFs, so it
    # works identically for a DEF-sourced and an ODB-sourced run and names the
    # master exactly as the database holds it.
    _census_pre = (
        "set _b [ord::get_db_block]\n"
        "set _cts_pre [dict create]\n"
        "foreach _i [$_b getInsts] { dict set _cts_pre [$_i getName] 1 }\n")
    _census_post = (
        "set _b [ord::get_db_block]\n"
        "foreach _i [$_b getInsts] {\n"
        "  set _n [$_i getName]\n"
        "  if {![dict exists $_cts_pre $_n]} {\n"
        "    puts \"__CTS_NEW__ $_n [[$_i getMaster] getName]\"\n"
        "  }\n"
        "}\n")
    # `set_dont_use` is the ONLY lever that constrains TritonCTS's dummy-load
    # characterization, which draws from the whole library rather than from
    # `-buf_list`. `restrict_clock_cells` derives the complement automatically
    # from the database's own buffer/inverter masters, so no PDK-specific cell
    # list is hard-coded here. Both are opt-in; the census below reports the
    # violation either way, so a caller can never carry an unapproved cell
    # silently just because it did not set these.
    _dont_use = _buffer_name_list(
        params.get("dont_use") or params.get("additional_dont_use")
        or binding.get("dont_use"))
    _restrict = str(params.get("restrict_clock_cells", "")).strip().lower() in (
        "1", "true", "yes", "on")
    _approved_tcl = "{" + " ".join(
        sorted(set(approved_buffers) | ({_root_buf} if _root_buf else set()))) + "}"
    _dont_use_tcl = ""
    if _dont_use:
        _dont_use_tcl += "set_dont_use {%s}\n" % " ".join(_dont_use)
    if _restrict:
        _dont_use_tcl += (
            "set _approved %s\n"
            "set _blocked {}\n"
            "foreach _lib [[ord::get_db] getLibs] {\n"
            "  foreach _m [$_lib getMasters] {\n"
            "    if {![$_m isBuffer] && ![$_m isInverter]} { continue }\n"
            "    set _mn [$_m getName]\n"
            "    if {[lsearch -exact $_approved $_mn] >= 0} { continue }\n"
            "    lappend _blocked $_mn\n"
            "  }\n"
            "}\n"
            "if {[llength $_blocked] > 0} { set_dont_use $_blocked }\n"
            "puts \"__CTS_DONTUSE__ [llength $_blocked]\"\n" % _approved_tcl)
    script = f"""{loader}
read_sdc {sdc}
{wire_rc}{_dont_use_tcl}{_census_pre}{_pdn_in}clock_tree_synthesis -buf_list {clkbuf_tcl}{_cts_opts}
set_propagated_clock [all_clocks]
detailed_placement
{_reconnect}report_clock_skew
report_clock_skew > {skew_rpt}
report_clock_latency -digits 4 > {latency_rpt}
{_census_post}{_pdn_out}write_def {out_def}
write_db {out_odb}
exit
"""
    proc, out, elapsed = _run_script(script, "cts")
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective=f"CTS of {top}", status="failed", pdk_binding=binding or "none",
                    error="OpenROAD CTS failed; see cts.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "cts.log"})
    _pdn = _parse_pdn_continuity(out)
    _pgrc = _parse_pg_reconnect(out)
    if _pdn and _pdn["destroyed"]:
        return _cde(
            objective=f"CTS of {top}", status="failed",
            pdk_binding=binding or "none",
            error=("CTS DESTROYED THE POWER GRID: %d supply rail(s) entered "
                   "this stage and only %d survived it. A rail is a special "
                   "power/ground net carrying real geometry, so the design can "
                   "no longer be power-connected -- and every downstream stage "
                   "would run and report success on it anyway."
                   % (_pdn["rails_in"], _pdn["rails_out"])),
            validation={"verdict": "fail"},
            qor={"power_rails_in": _pdn["rails_in"],
                 "power_rails_out": _pdn["rails_out"]},
            provenance={"openroad": "openroad", "log": "cts.log"})
    if _pdn and _pdn["unpowered_created"]:
        # The supply reconnect ran above, so reaching here means it did NOT
        # re-attach the cells CTS inserted -- the grid is intact and the new
        # clock buffers are dead. Not waivable as a warning: an unpowered
        # buffer in the clock tree is a broken clock.
        return _cde(
            objective=f"CTS of {top}", status="failed",
            pdk_binding=binding or "none",
            error=("CTS LEFT INSERTED CELLS UNPOWERED: unconnected supply "
                   "pins rose from %d to %d even after the supply reconnect "
                   "(%s), while the power grid itself stayed intact. Clock "
                   "buffers sitting on the rails but not attached to them are "
                   "dead, and check_power_grid still passes because it audits "
                   "the grid, not each instance's attachment to it."
                   % (_pdn["unconnected_pg_pins_in"],
                      _pdn["unconnected_pg_pins_out"],
                      "reconnect not attempted" if _pgrc is None
                      else "reconnect status=%s, %d pin(s) re-attached"
                           % (_pgrc["status"], _pgrc["pins_reconnected"]))),
            validation={"verdict": "fail"},
            qor={"unconnected_pg_pins_in": _pdn["unconnected_pg_pins_in"],
                 "unconnected_pg_pins_out": _pdn["unconnected_pg_pins_out"],
                 "supply_pins_reconnected": (_pgrc or {}).get("pins_reconnected")},
            provenance={"openroad": "openroad", "log": "cts.log"})
    # Disclosed, not gated: a flow may legitimately build its PDN after CTS,
    # so an absent PDN must not fail here. What it MUST do is say so, because
    # on crc16_ccitt nothing did and the loss surfaced five stages later.
    _pdn_note = None
    if _pdn is None:
        _pdn_note = ("power-net continuity NOT measured (no __PDN_IN__/"
                     "__PDN_OUT__ markers in this log)")
    elif _pdn["absent"]:
        _pdn_note = (
            "this design carries NO supply rails on entry (%d POWER/GROUND-"
            "typed net(s) seen, but none of them special with geometry -- a "
            "tie-off net such as `zero_` carries that sigtype without "
            "distributing power), so nothing downstream of here can be "
            "power-connected. CTS does not create a PDN, so this is "
            "inherited: check that the stage feeding CTS is downstream of the "
            "PDN stage." % _pdn["pg_nets_in"])
    else:
        _pdn_note = ("%d supply rail(s) preserved through CTS"
                     % _pdn["rails_out"])
        if _pdn["unpowered_pre_existing"]:
            _pdn_note += ("; %d supply pin(s) arrived ALREADY unconnected to "
                          "the grid -- those cells are dead, and the stage "
                          "that inserted them without re-running "
                          "global_connect is upstream of here"
                          % _pdn["unconnected_pg_pins_out"])
        elif _pdn["unconnected_measured"]:
            _pdn_note += (", %d unconnected supply pin(s) after reconnect"
                          % _pdn["unconnected_pg_pins_out"])
            if _pgrc and _pgrc["status"] == "applied":
                _pdn_note += (" (%d pin(s) on cells CTS inserted were "
                              "re-attached to %s/%s)"
                              % (_pgrc["pins_reconnected"],
                                 _pgrc["power_net"], _pgrc["ground_net"]))
            elif _pgrc and _pgrc["status"] == "skipped":
                _pdn_note += (" (supply reconnect SKIPPED: %s power and %s "
                              "ground rail(s) carry geometry, so the correct "
                              "domain for an inserted cell is power INTENT "
                              "and cannot be inferred here)"
                              % (_pgrc["power_rails"], _pgrc["ground_rails"]))
    # CLOCK SKEW -- this stage's GATE METRIC, so a null here makes the whole
    # stage unmeasurable.
    #
    # TWO defects, both measured on a real run:
    #  1. WRONG DIRECTION. OpenSTA prints the value BEFORE the word:
    #         --------------
    #           -0.00 setup skew
    #     The old pattern `skew\s+([0-9.eE+-]+)` expects `skew <number>` and so
    #     matched NOTHING -- clock_skew was None on every run.
    #  2. WRONG SOURCE. `report_clock_skew` is REDIRECTED to cts_skew.rpt, so the
    #     numbers are not in stdout at all. Parsing `out` could never have found
    #     them even with a correct pattern.
    # Read the report file first (authoritative), fall back to stdout.
    _skew_text = ""
    try:
        if os.path.exists(skew_rpt):
            _skew_text = open(skew_rpt, encoding="utf-8", errors="replace").read()
    except Exception:
        _skew_text = ""
    skew = None
    for _src in (_skew_text, out):
        if not _src:
            continue
        # Anchored to the summary line so `report_clock_skew` (the command echo)
        # and the per-endpoint latency rows cannot be mistaken for the result.
        m = re.search(
            r"^\s*(-?[0-9.]+(?:[eE][+-]?[0-9]+)?)\s+(?:setup|hold)?\s*skew\s*$",
            _src, re.I | re.M)
        if m:
            skew = float(m.group(1))
            break
    bufs = _count_masters_in_def(out_def, approved_buffers)
    # SR-086-CLASS GATE: every cell CTS inserted must be an approved clock
    # buffer. TritonCTS's dummy-load balancing picks its load cell from the
    # whole library, not from `-buf_list`, so a run can report zero unbuffered
    # clocks and a skew well inside budget while silently carrying an
    # unapproved master. Measured on two designs; the caller had to diff the
    # DEF by hand to see it, and one blessed attempt only avoided it by
    # topology luck. The census is unconditional and FAILS the gate -- a
    # detection a caller must remember to perform is not a control.
    inserted = _parse_inserted_cells(out)
    approved_set = set(approved_buffers) | ({_root_buf} if _root_buf else set())
    unapproved = sorted({
        master for _name, master in inserted if master not in approved_set})
    unapproved_count = sum(
        1 for _name, master in inserted if master not in approved_set)
    cells_measured = bool(inserted)

    # CLOCK INSERTION DELAY -- ALWAYS MEASURED, GATING ONLY IF A BUDGET EXISTS.
    #
    # Measured 2026-09-08: this tool's docstring, agent.yaml and README all claimed
    # it "reports skew and insertion delay", but no results/qor field ever carried
    # it -- the number was never produced. The `insertion_delay_ns: null` seen in
    # bsum16 cts.1 came from a hand-authored fail-closed CDE, not from here.
    #
    # The metric is now unconditional: a clock tree HAS an insertion delay whether
    # or not anyone declared a budget, and reporting it is how a budget can ever be
    # chosen on evidence instead of guessed. Gating is separate and conditional --
    # see _insertion_delay_gate(). Keep the two ideas distinct:
    #   measured + budget declared -> pass/fail against the budget
    #   measured + no budget       -> reported, NOT gating (still a real number)
    #   not measured               -> not_assessable (never a pass)
    insertion_delay, insertion_delay_by_clock = _parse_insertion_delay(
        latency_rpt, out)
    _id_budget, _id_budget_source = _resolve(
        params, policy, "insertion_delay_budget_ns",
        (binding or {}).get("insertion_delay_budget_ns"))
    insertion_gate = _insertion_delay_gate(insertion_delay, _id_budget)

    # THE CTS GATE: every valid clock must have had buffers ADDED or RESIZED.
    #
    # `bufs` above counts buffer-master occurrences in the OUTPUT DEF. That is a
    # diagnostic, NOT the gate, for two reasons:
    #   * It cannot distinguish a buffer CTS inserted from one that was already
    #     in the incoming netlist. On a design that arrives pre-buffered it would
    #     report a healthy count even if CTS did nothing -- fail-open.
    #   * It is design-wide, so a multi-clock design where ONE clock got no tree
    #     at all is masked by the other clocks' buffers.
    # TritonCTS reports per-clock, so take the gate from the log instead. On the
    # measured run the DEF count (6) and the reported count (5) already disagree.
    clocks_seen, buffered, current = [], {}, None
    for line in out.splitlines():
        # CTS-0007: Net "clk" found for clock "clk".  -> a clock CTS will act on
        mm = re.search(r"CTS-0007\]\s*Net\s+\"([^\"]+)\"\s+found for clock\s+\"([^\"]+)\"", line)
        if mm:
            current = mm.group(2)
            if current not in clocks_seen:
                clocks_seen.append(current)
                buffered.setdefault(current, 0)
            continue
        # CTS-0027: Generating H-Tree topology for net <net>. -> per-clock section
        mm = re.search(r"CTS-0027\]\s*Generating H-Tree topology for net\s+(\S+?)\.?\s*$", line)
        if mm:
            current = mm.group(1)
            buffered.setdefault(current, 0)
            continue
        # CTS-0018: Created N clock buffers.   /  resized buffers, where reported
        mm = re.search(r"CTS-0018\]\s*Created\s+(\d+)\s+clock buffers", line)
        if mm and current is not None:
            buffered[current] = buffered.get(current, 0) + int(mm.group(1))
            continue
        mm = re.search(r"[Rr]esized\s+(\d+)\s+(?:clock\s+)?buffer", line)
        if mm and current is not None:
            buffered[current] = buffered.get(current, 0) + int(mm.group(1))

    # A clock CTS never mentioned is NOT silently treated as buffered. If the log
    # named no clocks at all we cannot evaluate the gate, so report None rather
    # than 0 -- "not measured" must never read as "no violation".
    if not clocks_seen and not buffered:
        unbuffered_clocks = None
        buffers_added = None
        per_clock = None
    else:
        per_clock = {c: buffered.get(c, 0) for c in (clocks_seen or list(buffered))}
        unbuffered_clocks = sum(1 for n in per_clock.values() if n <= 0)
        buffers_added = sum(per_clock.values())

    gate_ok = (unbuffered_clocks == 0) if unbuffered_clocks is not None else None
    return _cde(
        objective=f"clock tree synthesis of {top}",
        status="completed",
        pdk_binding=binding or "none",
        results={"clock_skew": {"value": skew, "unit": "ns"},
                 "clock_insertion_delay": {"value": insertion_delay, "unit": "ns"},
                 "clock_buffers": {"value": bufs, "unit": "count"},
                 "unbuffered_clocks": {"value": unbuffered_clocks,
                                       "unit": "clocks"},
                 "buffers_added": {"value": buffers_added, "unit": "count"},
                 "unapproved_inserted_count": {"value": unapproved_count if cells_measured else None,
                                               "unit": "count"},
                 "clocks_buffered": {"value": per_clock, "unit": "count_by_clock"}},
        qor={"unbuffered_clocks": unbuffered_clocks,
             "buffers_added": buffers_added,
             "clock_skew_ns": skew, "clock_buffers": bufs,
             "unapproved_inserted_count": unapproved_count if cells_measured else None,
             "cts_inserted_cells": len(inserted) if cells_measured else None,
             # ALWAYS reported, whether or not it gates -- see
             # _insertion_delay_gate(). A null here means not measured, which is
             # never compliance.
             "insertion_delay_ns": insertion_delay,
             "insertion_delay_budget_ns": insertion_gate["budget_ns"],
             "insertion_delay_status": insertion_gate["status"],
             "insertion_delay_gating": insertion_gate["gating"],
             # Measured, not assumed: what this stage was handed and what it
             # gave back. Rails are the meaningful count.
             "power_rails_in": (_pdn or {}).get("rails_in"),
             "power_rails_out": (_pdn or {}).get("rails_out"),
             "power_rails_preserved": (_pdn or {}).get("preserved"),
             # An intact grid does not mean every cell reaches it.
             "unconnected_pg_pins_in": (_pdn or {}).get("unconnected_pg_pins_in"),
             "unconnected_pg_pins_out": (_pdn or {}).get("unconnected_pg_pins_out"),
             "supply_pins_reconnected": (_pgrc or {}).get("pins_reconnected")},
        signoff={"cts_def": "cts.def", "cts_odb": "cts.odb",
             "clock_buffer": clkbuf, "report": "cts.log",
                  "wire_rc_layers": wire_rc_settings,
                 "approved_clock_cells": sorted(approved_set),
                 "inserted_cells": [{"instance": n, "master": m}
                                    for n, m in inserted],
                 "unapproved_inserted_masters": unapproved,
                 "approved_clock_buffer_only": (
                     unapproved_count == 0 if cells_measured else None),
                 "skew_report": "cts_skew.rpt", "hierarchy_mode": hierarchy_mode,
                 "latency_report": "cts_latency.rpt",
                 "insertion_delay": insertion_gate,
                 "insertion_delay_by_clock": insertion_delay_by_clock,
                 "clocks_buffered": per_clock,
                 "power_net_continuity": _pdn,
                 "supply_reconnect": _pgrc,
                 "power_net_continuity_note": _pdn_note,
                 "cts_options": _cts_opts.strip() or "default"},
        inputs_ref=dict(inputs, sdc=sdc),
        assumptions=["single clock buffer cell; propagated-clock skew reported",
                     "gate = every clock TritonCTS reported had >0 buffers "
                     "added or resized; clock_skew is diagnostic only",
                     "clock insertion delay is ALWAYS measured and reported; it "
                     "gates ONLY when an insertion_delay_budget_ns is declared "
                     "(binding or params). Absent a budget it is reported as "
                     "not_gating -- which is neither a pass nor a waiver",
                     "every cell CTS inserted is censused from the database and "
                     "checked against the approved clock-cell set; an unapproved "
                     "master (TritonCTS dummy-load balancing draws from the whole "
                     "library, not from -buf_list) FAILS this gate"],
        validation={"verdict": "pass" if (gate_ok and cells_measured
                          and insertion_gate["status"] not in ("fail", "not_assessable")
                          and unapproved_count == 0)
                               else "fail",
                    "insertion_delay": insertion_gate,
                    "approved_clock_buffer_only": (
                        unapproved_count == 0 if cells_measured else None),
                    "note": ("clock tree built and legalized; "
                             + ("all %d clock(s) buffered" % len(per_clock or {})
                                if gate_ok else
                                "gate NOT evaluated: no clocks reported by CTS"
                                if unbuffered_clocks is None else
                                "%d clock(s) received no buffering"
                                % unbuffered_clocks)
                             + "; insertion delay " + insertion_gate["note"]
                             + ("; %d inserted instance(s) use unapproved "
                                "master(s) %s -- not waivable"
                                % (unapproved_count, ", ".join(unapproved))
                                if unapproved_count else
                                "; all inserted cells are approved"
                                if cells_measured else
                                "; inserted-cell census NOT measured"))},

        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "cts.log", "setting_sources": {
                        "clock_buffer": clkbuf_source, "root_buffer_cell": root_source,
                        "sink_clustering_size": sc_size_source,
                        "sink_clustering_max_diameter": sc_diam_source}},
    )


def _parse_insertion_delay(latency_rpt, stdout_text):
    """Max clock insertion delay (ns) from `report_clock_latency`, plus per-clock.

    PARSED FROM REAL OUTPUT, NOT FROM ASSUMPTION. Captured from the pinned image
    (OpenROAD 26Q3-1305-gf552262465) on 2026-09-08:

        Clock clk
        rise -> rise
            min     max
         0.0000  0.0000 source latency
         0.0931         network latency ff/CLK
                 0.0931 network latency ff/CLK
        ---------------
         0.0931  0.0931 latency
                 0.0000 skewfall -> fall
            min     max
         0.0000  0.0000 source latency
         ...
         0.1026  0.1026 latency

    Three things that a from-memory parser gets wrong, all visible above:
      * The summary row carries TWO columns (min and max), not one. A pattern
        expecting `<number> latency` matches NOTHING and yields None forever --
        the same defect the skew parser already carries a comment about.
      * Each clock reports SEPARATE rise->rise and fall->fall blocks. The clock's
        insertion delay is the WORST of them (0.1026 here, not 0.0931).
      * OpenSTA omits a newline after `skew`, so `skewfall -> fall` arrives as one
        line. Nothing may depend on those being separate lines.

    `source latency` and `network latency <pin>` rows are deliberately NOT matched:
    only the post-rule summary row is the clock's latency.

    Returns (max_ns_or_None, {clock: ns}). None means NOT MEASURED, which must
    never be reported as compliance, and is distinct from "measured, no budget".
    """
    text = ""
    try:
        if latency_rpt and os.path.exists(latency_rpt):
            text = open(latency_rpt, encoding="utf-8", errors="replace").read()
    except Exception:
        text = ""
    _num = r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
    # Anchored on end-of-line so `source latency` / `network latency <pin>` cannot
    # match. Second column (max) is the gating side when both are present.
    row = re.compile(r"^\s*(%s)(?:\s+(%s))?\s+latency\s*$" % (_num, _num))
    clock_hdr = re.compile(r"^\s*Clock\s+(\S+)\s*$")
    for src_text in (text, stdout_text or ""):
        if not src_text:
            continue
        per_clock, current = {}, None
        for line in src_text.splitlines():
            m = clock_hdr.match(line)
            if m:
                current = m.group(1)
                continue
            m = row.match(line)
            if not m or current is None:
                continue
            value = float(m.group(2) if m.group(2) is not None else m.group(1))
            # Worst across this clock's rise/fall blocks.
            per_clock[current] = max(per_clock.get(current, value), value)
        if per_clock:
            return max(per_clock.values()), per_clock
    return None, None


def _insertion_delay_gate(measured_ns, budget_ns):
    """Resolve the THREE distinct insertion-delay outcomes.

    A budget is OPTIONAL design intent. When one is declared the metric gates;
    when none is declared the metric is still measured and reported, but it
    cannot pass or fail -- there is nothing to compare against, and inventing a
    threshold would manufacture design intent (that is exactly what DX-283
    refused to do).

    The `not_gating` status is NOT a pass and NOT a waiver. It carries a real
    measured number so a budget can later be chosen from evidence. `not_assessable`
    is reserved for the genuinely different case of no measurement at all.
    """
    try:
        budget = float(budget_ns) if budget_ns is not None else None
    except (TypeError, ValueError):
        budget = None
    if measured_ns is None:
        return {"status": "not_assessable", "gating": budget is not None,
                "budget_ns": budget, "measured_ns": None,
                "note": ("clock insertion delay was NOT measured; this is not a pass"
                         + (" and a declared budget could not be checked"
                            if budget is not None else ""))}
    if budget is None:
        return {"status": "not_gating", "gating": False, "budget_ns": None,
                "measured_ns": measured_ns,
                "note": ("measured and reported; no insertion-delay budget is "
                         "declared, so this metric does not gate. Declaring a "
                         "budget makes it gating.")}
    return {"status": "pass" if measured_ns <= budget else "fail",
            "gating": True, "budget_ns": budget, "measured_ns": measured_ns,
            "note": "measured %.4f ns against declared budget %.4f ns"
                    % (measured_ns, budget)}


def _post_cts_timing_optimization(params):
    if not shutil.which("openroad"):
        return _cde(objective="post-CTS timing optimization", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    loader, inputs, failure = _load_design(params, binding, "post-CTS timing optimization")
    if failure:
        return failure
    sdc = params.get("sdc")
    if not sdc or not os.path.exists(str(sdc)):
        return _cde(objective="post-CTS timing optimization", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="missing or unreadable required field 'sdc'",
                    validation={"verdict": "fail"})
    policy = _stage_policy(binding)
    setup_margin, setup_source = _resolve(params, policy, "setup_margin", 0.0)
    hold_margin, hold_source = _resolve(params, policy, "hold_margin", 0.0)
    max_buffer, max_buffer_source = _resolve(params, policy, "max_buffer_percent", None)
    common = f" -max_buffer_percent {max_buffer}" if max_buffer is not None else ""
    # repair_timing/repair_design need a wire-RC model or they hard-error
    # (OpenROAD RSZ-0089: "Could not find a resistance value for any corner").
    # Resolve wire-RC layers: caller params -> tool_policy -> pdk_binding.routing_layers.
    _rl = (binding.get("routing_layers") or {}) if isinstance(binding, dict) else {}
    wsig = (params.get("wire_rc_signal_layer")
            or policy.get("wire_rc_signal_layer")
            or _rl.get("wire_rc_signal_layer"))
    wclk = (params.get("wire_rc_clock_layer")
            or policy.get("wire_rc_clock_layer")
            or _rl.get("wire_rc_clock_layer"))
    if not wsig and not wclk:
        return _cde(objective="post-CTS timing optimization", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="missing wire-RC layer for set_wire_rc: repair_timing needs a "
                          "wire-RC model or it hard-errors (OpenROAD RSZ-0089). Provide "
                          "wire_rc_signal_layer/wire_rc_clock_layer (caller), or "
                          "tool_policy.cts.wire_rc_signal_layer/_clock_layer, or "
                          "pdk_binding.routing_layers.wire_rc_signal_layer/_clock_layer.",
                    validation={"verdict": "fail"})
    wire_rc = ""
    if wsig:
        wire_rc += f"set_wire_rc -signal -layer {wsig}\n"
    if wclk:
        wire_rc += f"set_wire_rc -clock -layer {wclk}\n"
    out_def = os.path.join(_OUTPUT_DIR, "cts_optimized.def")
    out_odb = os.path.join(_OUTPUT_DIR, "cts_optimized.odb")
    timing_rpt = os.path.join(_OUTPUT_DIR, "post_cts_timing.rpt")
    setup_opts, setup_applied, tf_sources = _repair_timing_opts(params, policy, "setup")
    hold_opts, hold_applied, _hs = _repair_timing_opts(params, policy, "hold")
    tf_sources.update(_hs)
    script = f"""{loader}
read_sdc {{{sdc}}}
set_propagated_clock [all_clocks]
{wire_rc}estimate_parasitics -placement
repair_timing -setup -setup_margin {setup_margin}{common}{setup_opts}
repair_timing -hold -hold_margin {hold_margin}{common}{hold_opts}
detailed_placement
check_placement -verbose
report_checks -path_delay min_max -fields {{slew cap input_pin}} > {{{timing_rpt}}}
write_def {{{out_def}}}
write_db {{{out_odb}}}
exit
"""
    proc, out, elapsed = _run_script(script, "post_cts_timing_optimization")
    inputs["sdc"] = sdc
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective="post-CTS timing optimization", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="OpenROAD post-CTS timing optimization failed; see post_cts_timing_optimization.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "post_cts_timing_optimization.log"})
    return _cde(objective="post-CTS setup and hold optimization", status="completed",
                pdk_binding=binding or "none", inputs_ref=inputs,
                results={"timing_optimization_completed": {"value": True, "unit": "bool"}},
                signoff={"cts_def": "cts_optimized.def", "cts_odb": "cts_optimized.odb",
                         "timing_report": "post_cts_timing.rpt",
                         "setup_margin": setup_margin, "hold_margin": hold_margin},
                validation={"verdict": "pass_with_caveats",
                            "note": "optimization completed; inspect timing report for closure"},
                provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                            "log": "post_cts_timing_optimization.log",
                            "repair_transforms": {"setup": setup_applied,
                                                  "hold": hold_applied},
                            "setting_sources": dict({"setup_margin": setup_source,
                                                     "hold_margin": hold_source,
                                                     "max_buffer_percent": max_buffer_source},
                                                    **tf_sources)})



# --- repair_timing transform control (vendored; see migrate_repair_transforms.py) ---
_REPAIR_TRANSFORMS_V1 = True

#: Every optimization transform OpenROAD's resizer can apply, and the flag that
#: DISABLES it. Names mirror ORFS (`SKIP_PIN_SWAP`, `SKIP_GATE_CLONING`, ...) so a
#: recipe can be moved between the two flows without translation.
#:
#: WHY THIS MATTERS: `repair_timing` with no transform control is a single lever --
#: resize and buffer. ORFS drives six more (pin swap, gate cloning, size-down,
#: buffer removal, VT swap, last gasp), and they are exactly what a design reaches
#: for once resizing alone has plateaued. A convergence ladder that can only pull
#: one lever will report `converged-stalled` on a design that a production flow
#: would still close.
_REPAIR_SKIPS = (
    ("skip_pin_swap", "-skip_pin_swap",
     "commutative-input pin swapping"),
    ("skip_gate_cloning", "-skip_gate_cloning",
     "gate cloning to split high-fanout critical loads"),
    ("skip_size_down", "-skip_size_down",
     "sizing cells DOWN (area/power recovery on non-critical paths)"),
    ("skip_buffering", "-skip_buffering",
     "buffer insertion"),
    ("skip_buffer_removal", "-skip_buffer_removal",
     "removing synthesis buffers to give the resizer freedom"),
    ("skip_last_gasp", "-skip_last_gasp",
     "the final aggressive optimization pass"),
    ("skip_vt_swap", "-skip_vt_swap",
     "swapping to a different Vt flavour"),
    ("skip_crit_vt_swap", "-skip_crit_vt_swap",
     "Vt swap restricted to remaining critical cells"),
)


def _repair_timing_opts(params, policy, phase):
    """Build the shared `repair_timing` option string for one phase.

    `phase` is "setup" or "hold" -- a few options are phase-specific and applying
    them to the wrong pass is silently wrong rather than an error:
      * `-recover_power` only means anything on the SETUP pass (it trades positive
        setup slack for power);
      * `-allow_setup_violations` only means anything on the HOLD pass (it permits
        hold fixing to eat setup margin).

    Resolution order matches every other knob in this tool: caller > pdk_binding
    tool_policy > tool default. Returns (options_string, applied, sources).
    """
    opts, applied, sources = "", {}, {}

    def _get(key, default=None):
        if key in params and params[key] is not None:
            sources[key] = "caller"
            return params[key]
        if key in policy and policy.get(key) is not None:
            sources[key] = "pdk_binding.tool_policy"
            return policy[key]
        return default

    for key, flag, meaning in _REPAIR_SKIPS:
        if bool(_get(key, False)):
            opts += " " + flag
            applied[key] = {"skipped": True, "transform": meaning}

    seq = _get("repair_sequence")
    if seq:
        # -sequence takes a comma-separated move list; accept a list for ergonomics.
        seq_str = ",".join(str(s) for s in seq) if isinstance(seq, list) else str(seq)
        opts += " -sequence %s" % seq_str
        applied["repair_sequence"] = seq_str

    max_passes = _get("max_passes")
    if max_passes is not None:
        opts += " -max_passes %s" % max_passes
        applied["max_passes"] = max_passes

    max_util = _get("max_utilization")
    if max_util is not None:
        opts += " -max_utilization %s" % max_util
        applied["max_utilization"] = max_util

    if bool(_get("match_cell_footprint", False)):
        opts += " -match_cell_footprint"
        applied["match_cell_footprint"] = True

    # TNS_END_PERCENT: how many violating endpoints to chase. 100 = all (best QoR,
    # slowest); lowering it is the standard runtime lever in exploration.
    repair_tns = _get("repair_tns_percent")
    if repair_tns is not None:
        opts += " -repair_tns %s" % repair_tns
        applied["repair_tns_percent"] = repair_tns

    if phase == "setup":
        recover = _get("recover_power_percent")
        if recover is not None:
            opts += " -recover_power %s" % recover
            applied["recover_power_percent"] = {
                "value": recover,
                "meaning": ("percent of positive-slack paths that may be SLOWED to "
                            "recover power; a pure-power lever with no timing "
                            "benefit, so it is opt-in and never defaulted on")}
    elif phase == "hold":
        if bool(_get("allow_setup_violations", False)):
            opts += " -allow_setup_violations"
            applied["allow_setup_violations"] = {
                "value": True,
                "caution": ("hold fixing may now consume setup margin. A setup "
                            "violation costs frequency; a hold violation is "
                            "dead-on-arrival silicon -- which is why this exists, "
                            "but the resulting setup slack is no longer free")}
    return opts, applied, sources
# --- end repair_timing transform control ------------------------------------

def dispatch(params):
    s = params.get("scenario")
    if s == "cts":
        return _cts(params)
    if s == "post_cts_timing_optimization":
        return _post_cts_timing_optimization(params)
    return _cde(objective="CTS", status="failed",
                error=f"unknown scenario '{s}'; supported: cts, post_cts_timing_optimization",
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
