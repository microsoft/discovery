#!/usr/bin/env python3
"""routing_utils.py -- real OpenROAD global (FastRoute) + detailed (TritonRoute)
routing.

Reads node LEF/Liberty + a post-CTS DEF, sets the routing layer range from the PDK
binding, runs global_route + detailed_route, reports DRC/short/open counts, and
writes a routed DEF. Node-aware. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "routing"
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
    stage = policy.get("routing", {})
    return stage.get("settings", stage) if isinstance(stage, dict) else {}


def _resolve(params, policy, key, default=None):
    if key in params and params[key] is not None:
        return params[key], "caller"
    if key in policy and policy[key] is not None:
        return policy[key], "pdk_binding.tool_policy"
    return default, "tool_default"


def _binding_layer(binding, name):
    if not isinstance(binding, dict):
        return None
    layers = binding.get("routing_layers")
    if isinstance(layers, dict):
        return layers.get(name) or layers.get(name.replace("_layer", ""))
    return binding.get(name)


def _load_design(params, binding, objective, require_liberty=False):
    def_file, odb_file = params.get("def_file"), params.get("odb_file")
    if bool(def_file) == bool(odb_file):
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none", error="provide exactly one of 'def_file' or 'odb_file'",
            validation={"verdict": "fail"})
    source = odb_file or def_file
    if not os.path.exists(str(source)):
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none", error=f"input not found: {source}",
            validation={"verdict": "fail"})
    libs = _as_list(params.get("liberty") or binding.get("liberty"))
    if require_liberty and not libs:
        return None, None, _cde(objective=objective, status="failed",
            pdk_binding=binding or "none", error="missing required field 'liberty' (check pdk_binding)",
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


def _routing_settings(params, binding, require_layers=True):
    policy = _stage_policy(binding)
    def layer(key):
        if key in params and params[key] is not None:
            return params[key], "caller"
        if key in policy and policy[key] is not None:
            return policy[key], "pdk_binding.tool_policy"
        value = _binding_layer(binding, key)
        return value, "pdk_binding.routing_layers" if value is not None else "missing"
    bot, bot_src = layer("bottom_layer")
    top, top_src = layer("top_layer")
    if require_layers and (not bot or not top):
        return None, None, None, _cde(
            objective="routing", status="failed", pdk_binding=binding or "none",
            error="missing bottom_layer/top_layer references (check pdk_binding.routing_layers or tool_policy.routing)",
            validation={"verdict": "fail"})
    return bot, top, {"bottom_layer": bot_src, "top_layer": top_src}, None


def _wire_rc_layers(params, policy, binding, bot=None, top=None):
    """Resolve the signal/clock routing-layer NAMES for `set_wire_rc`, node-portably.

    OpenROAD's resizer (repair_design / repair_timing) needs a wire-RC model to
    estimate net delay; without a `set_wire_rc` before `estimate_parasitics` it
    raises RSZ-0089 and performs ZERO buffering/resizing (the whole repair silently
    no-ops). `set_wire_rc -layer <L>` makes OpenROAD read the per-unit R/C for layer
    <L> straight from the tech LEF the flow already loaded -- so only a valid routing
    LAYER NAME is needed here, never a hard-coded R/C constant (node-portability).

    Resolution priority (caller override wins, node facts come from the binding):
      1. caller param  wire_rc_signal_layer / wire_rc_clock_layer
      2. pdk_binding.tool_policy.<stage>.wire_rc_signal_layer / _clock_layer
      3. pdk_binding.routing_layers.wire_rc_signal_layer / _clock_layer
      4. DERIVED fallback from the routing range already resolved for this stage:
         signal <- bottom_layer, clock <- top_layer (both are real routing layers
         the design uses, so this is a data-derived default, not a node constant).
    Returns (sig_layer, clk_layer, sources).
    """
    def pick(key, fallback):
        if key in params and params[key]:
            return params[key], "caller"
        if key in policy and policy[key]:
            return policy[key], "pdk_binding.tool_policy"
        v = _binding_layer(binding, key)
        if v:
            return v, "pdk_binding.routing_layers"
        return fallback, ("derived:routing_range" if fallback else "missing")
    sig, sig_src = pick("wire_rc_signal_layer", bot)
    clk, clk_src = pick("wire_rc_clock_layer", top)
    return sig, clk, {"wire_rc_signal_layer": sig_src, "wire_rc_clock_layer": clk_src}


def _set_wire_rc_cmds(sig, clk):
    """Build the `set_wire_rc` lines that MUST precede `estimate_parasitics`."""
    cmds = []
    if sig:
        cmds.append(f"set_wire_rc -signal -layer {sig}")
    if clk:
        cmds.append(f"set_wire_rc -clock -layer {clk}")
    return "\n".join(cmds)


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD FastRoute/TritonRoute", "version": "openroad"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "drc_count"},
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


def _parse_congestion(out):
    """Extract the measured routing congestion from the global-route log.

    Congestion was previously only an INPUT knob (`congestion_iterations`): the
    stage could be told how hard to work against congestion but never reported
    how much it found, so the one quantity routing exists to predict was absent
    from the envelope.

    OpenROAD GRT-0096 prints, verbatim:

        Layer         Resource        Demand        Usage (%)    Max H / Max V / Total Congestion
        met1              2666           396           14.85%             0 /  0 /  0
        Total             7766          1189           15.31%             0 /  0 /  0

    Demand/Resource per layer is the real utilisation of the routing tracks, and
    the trailing triple is the per-GCell overflow (Max H / Max V / Total). Total
    Congestion > 0 means GCells demand more tracks than exist -- genuine overflow.
    Returns None when the report is absent, so an unparsed log is reported as
    unmeasured rather than as zero congestion.

    THE LAST TABLE WINS. A repair scenario runs global_route MORE THAN ONCE --
    once before the repair and once after it -- so the log can hold several
    GRT-0096 tables. The authoritative one is the FINAL state of the design,
    exactly as the DRC count reads the last `number of violations` line rather
    than the first. Reading the first table would report PRE-repair congestion
    as the stage's result, i.e. credit the repair with a number measured before
    it ran."""
    ms = list(re.finditer(r"GRT-0096.*?Final congestion report:(.*?)(?:\n\s*\n|\Z)",
                          out, re.S))
    if not ms:
        return None
    m = ms[-1]
    rows, total = [], None
    for line in m.group(1).splitlines():
        r = re.match(r"\s*(\w+)\s+(\d+)\s+(\d+)\s+([0-9.]+)%\s+"
                     r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$", line)
        if not r:
            continue
        rec = {"layer": r.group(1), "resource": int(r.group(2)),
               "demand": int(r.group(3)), "usage_pct": float(r.group(4)),
               "max_h_overflow": int(r.group(5)),
               "max_v_overflow": int(r.group(6)),
               "total_overflow": int(r.group(7))}
        if rec["layer"].lower() == "total":
            total = rec
        else:
            rows.append(rec)
    if total is None and not rows:
        return None
    worst = max((x["usage_pct"] for x in rows), default=None)
    ovf = sum(x["total_overflow"] for x in rows)
    return {
        "per_layer": rows,
        "total": total,
        "worst_layer_usage_pct": worst,
        "worst_layer": next((x["layer"] for x in rows
                             if x["usage_pct"] == worst), None) if rows else None,
        "overall_usage_pct": (total or {}).get("usage_pct"),
        "total_overflow": ovf,
        # Overflow is the hard signal: tracks demanded that do not exist.
        "congested": ovf > 0,
    }


def _upstream_feedback(cong, drc, unroute):
    """Name the UPSTREAM stage that must change, when this stage's own knobs cannot fix it.

    Routing is where congestion becomes visible, but it is not where congestion is
    DECIDED: the utilization came from floorplanning and the cell spreading came
    from placement. Previously each stage reported only its own residual, so a
    congested design produced a routing failure with no statement of which
    upstream choice caused it -- the operator had to already know the flow to act,
    and an automated loop had nothing to act on at all.

    This emits a MACHINE-READABLE hand-back: which stage, which knob, which
    direction. It never claims a fix will work; it names the lever and the
    evidence, because that is what is actually derivable here."""
    fb = []
    if cong and cong.get("congested"):
        worst = cong.get("worst_layer")
        fb.append({
            "stage": "floorplan", "knob": "utilization",
            "direction": "decrease",
            "evidence": {"total_overflow": cong.get("total_overflow"),
                         "worst_layer": worst,
                         "worst_layer_usage_pct": cong.get("worst_layer_usage_pct")},
            "detail": ("global routing demands more tracks than exist "
                       "(%s GCell-track overflow, worst on %s). Routing has no "
                       "knob that creates tracks: the track budget was set by the "
                       "floorplan utilization."
                       % (cong.get("total_overflow"), worst))})
        fb.append({
            "stage": "placement", "knob": "target_density",
            "direction": "decrease",
            "evidence": {"worst_layer_usage_pct": cong.get("worst_layer_usage_pct")},
            "detail": ("if the die cannot grow, spreading the cells lowers local "
                       "demand without changing the floorplan")})
    elif cong and (cong.get("worst_layer_usage_pct") or 0) >= 90.0:
        # No overflow yet, but one layer is nearly exhausted: the NEXT ECO or
        # fill pass is likely to tip it over. Worth saying before it fails.
        fb.append({
            "stage": "floorplan", "knob": "utilization", "direction": "decrease",
            "evidence": {"worst_layer": cong.get("worst_layer"),
                         "worst_layer_usage_pct": cong.get("worst_layer_usage_pct")},
            "detail": ("%s is at %.1f%% of its track budget with no overflow yet; "
                       "there is little headroom for a later ECO"
                       % (cong.get("worst_layer"),
                          cong.get("worst_layer_usage_pct") or 0.0))})
    if drc and unroute:
        fb.append({
            "stage": "eco", "knob": "repair_scope", "direction": "review",
            "evidence": {"drc_violations": drc},
            "detail": ("residual DRC after an ECO re-route; the ECO edit may not "
                       "be routable as placed")})
    return fb


def _unroute_patterns(raw):
    """Normalise the `unroute_first` request into a list of Tcl match patterns.

    Returns (patterns, error). ``patterns is None`` means "do not unroute".
    ``["*"]`` means the full-slate reroute. Anything else is a SCOPED reroute.

    Patterns are embedded in a generated Tcl script inside braces, so a pattern
    carrying a brace, a backslash or whitespace could break out of its quoting
    and execute as script text. Those characters are REJECTED rather than
    escaped: no legal net name in this flow contains them, so rejecting costs
    nothing and removes the injection surface entirely.
    """
    if raw is None or raw is False:
        return None, None
    if raw is True:
        return ["*"], None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return None, ("'unroute_first' must be true (unroute every signal net), "
                      "or a list of net names/globs to unroute only those; "
                      "got %s" % type(raw).__name__)
    pats = []
    for p in raw:
        if not isinstance(p, str) or not p.strip():
            return None, ("'unroute_first' list entries must be non-empty net "
                          "name/glob strings; got %r" % (p,))
        p = p.strip()
        # Each pattern is emitted as `{pattern}`. Tcl performs NO substitution
        # inside braces, so '[', '$', '"' and ';' are all inert there and are
        # allowed -- bus bits legitimately look like crc_nxt[0]. What DOES break
        # brace quoting is an unbalanced brace or a trailing backslash, and
        # whitespace would silently split one pattern into two list elements.
        bad = [c for c in ("{", "}", "\\") if c in p]
        if any(c.isspace() for c in p):
            bad.append("whitespace")
        if bad:
            return None, ("net pattern %r contains %s, which cannot be safely "
                          "embedded in the generated Tcl; supply the plain net "
                          "name" % (p, ", ".join(bad)))
        pats.append(p)
    if not pats:
        return None, ("'unroute_first' was an EMPTY list: that would unroute "
                      "nothing and leave the design already-routed, which fails "
                      "at DRT-0047. Pass true to reroute everything, or the "
                      "names of the nets the ECO touched.")
    return pats, None


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


def _physical_cells(binding, key):
    """binding top-level, then binding.physical_cells (where ORFS-derived bindings put them)."""
    if not isinstance(binding, dict):
        return None
    if binding.get(key) is not None:
        return binding[key]
    pc = binding.get("physical_cells")
    return pc.get(key) if isinstance(pc, dict) else None


def _filler_settings(params, policy, binding):
    """Resolve the filler / tap masters this stage must KNOW about. Returns
    (settings, error).

    Routing does NOT insert fillers: filler insertion has ONE implementation,
    chip-placement scenario `insert_fill` (filler_placement on the ROUTED DEF,
    the ORFS 5_3_fillcell position). Routing only (a) counts filler instances in
    the routed design and warns when there are none although the binding
    declares filler_cells (measured on uart_apb/Nangate45: routed DEF with 0
    FILLCELL instances -> 285 KLayout WELL.4 violations), and (b) keeps
    physical-only masters out of the written Verilog netlist.
    """
    cells, src = _resolve(params, policy, "filler_cells", None)
    if cells is None:
        cells = _physical_cells(binding, "filler_cells")
        src = "pdk_binding.physical_cells" if cells is not None else "missing"
    cells = [str(c) for c in _as_list(cells) if c]
    taps = []
    for key in ("tapcell_master", "endcap_master"):
        value = _physical_cell_param(params, policy, binding, key)
        if value and str(value) not in taps:
            taps.append(str(value))
    return {"filler_cells": cells, "filler_cells_source": src, "tap_cells": taps}, None


def _physical_cell_param(params, policy, binding, key):
    value, _ = _resolve(params, policy, key, None)
    return value if value is not None else _physical_cells(binding, key)


def _filler_tcl(fill):
    """Count filler-master instances in the routed design (probe only)."""
    if not fill["filler_cells"]:
        return ""
    masters = " ".join(fill["filler_cells"])
    return (f"set _fl_masters [list {masters}]\n"
            "set _fl_count 0\n"
            "foreach _fl_i [[ord::get_db_block] getInsts] { if {[lsearch -exact $_fl_masters [[$_fl_i getMaster] getName]] >= 0} { incr _fl_count } }\n"
            "puts \"__FILL__ count=$_fl_count\"\n")

def _netlist_write_tcl(out_netlist, physical_masters):
    """write_verilog excluding physical-only masters (fillers, taps/endcaps).

    Only masters OpenROAD can resolve as lib cells are passed to -remove_cells,
    so an absent tap master never aborts the netlist write.
    """
    if not physical_masters:
        return f"write_verilog -include_pwr_gnd {out_netlist}\n"
    masters = " ".join(physical_masters)
    return (f"set _vl_rm {{}}\n"
            f"foreach _vl_m [list {masters}] {{ if {{[llength [get_lib_cells -quiet $_vl_m]]}} {{ lappend _vl_rm $_vl_m }} }}\n"
            "puts \"__VLOG_REMOVE_CELLS__ $_vl_rm\"\n"
            "if {[llength $_vl_rm]} {\n"
            f"  write_verilog -include_pwr_gnd -remove_cells $_vl_rm {out_netlist}\n"
            "} else {\n"
            f"  write_verilog -include_pwr_gnd {out_netlist}\n"
            "}\n")


def _parse_fill(out, fill):
    m = re.search(r"__FILL__ count=(\d+)", out)
    rm = re.search(r"__VLOG_REMOVE_CELLS__ ?(.*)", out)
    rec = {"filler_cells": fill["filler_cells"],
           "filler_cells_source": fill["filler_cells_source"],
           "measured": m is not None,
           "filler_cells_total": int(m.group(1)) if m else None,
           "inserted_by": "chip-placement scenario insert_fill (not this stage)",
           "netlist_removed_cells": rm.group(1).split() if rm else []}
    warnings = []
    if fill["filler_cells"] and m and int(m.group(1)) == 0:
        warnings.append(
            "routed design ends with 0 filler cells while the PDK binding declares "
            "filler_cells %s: row gaps leave n-well/implant discontinuities that "
            "KLayout reports as WELL/implant DRC (measured 285 WELL.4 on uart_apb). "
            "Next flow step: chip-placement scenario insert_fill on this routed "
            "DEF/ODB, then stream out / DRC the filled design."
            % fill["filler_cells"])
    if fill["filler_cells"] and not m:
        warnings.append("filler-cell probe (__FILL__) missing from route.log; the "
                        "routed design's filler count was NOT measured")
    return rec, warnings

def _route(params):
    if not shutil.which("openroad"):
        return _cde(objective="routing", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    top = params.get("top")
    binding = params.get("pdk_binding") or {}
    loader, inputs, failure = _load_design(params, binding, "routing")
    if failure:
        return failure
    bot, topl, setting_sources, failure = _routing_settings(params, binding)
    if failure:
        return failure
    for n, v in (("top", top),):
        if not v:
            return _cde(objective="routing", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}'", validation={"verdict": "fail"})
    out_def = os.path.join(_OUTPUT_DIR, "routed.def")
    out_odb = os.path.join(_OUTPUT_DIR, "routed.odb")
    out_netlist = os.path.join(_OUTPUT_DIR, "routed.v")
    drc_rpt = os.path.join(_OUTPUT_DIR, "route_drc.rpt")
    # Routing quality levers. congestion_iterations bounds global-route rip-up &
    # reroute effort against congestion; via_in_pin_layers permits via-in-pin
    # access over a metal-layer window (helps pin access on dense designs).
    _gr_opts = ""
    policy = _stage_policy(binding)
    _cong_iter, cong_source = _resolve(params, policy, "congestion_iterations", None)
    if _cong_iter is not None:
        _gr_opts += f" -congestion_iterations {int(_cong_iter)}"
    # OPT-IN pad-pin-overflow tolerance. By default global_route hard-ERRORS
    # (GRT-0116) on any residual congestion and detailed_route never runs. On a
    # padframe design the only residual overflow is GRT's PESSIMISM at coincident
    # pad/BTerm pins (met5 PAD pins sit on top of the met5 BTerm), which is an
    # estimation artifact the actual pin-accessing detailed_route resolves. When
    # `allow_congestion` is set, global_route proceeds past that residual overflow
    # (reporting it, not routing around it) so detailed_route -- the real DRC gate
    # -- can run. Mirrors antenna_repair's `antenna_allow_congestion`. No effect
    # when there is no overflow; it never relaxes the detailed-route checker.
    if bool(params.get("allow_congestion")):
        _gr_opts += " -allow_congestion"
    # Ask global_route for the per-GCell congestion report. OpenROAD only writes
    # this FILE when there IS overflow, so its absence is not evidence of a clean
    # grid. The authoritative measurement is the GRT-0096 table, which is printed
    # ONLY UNDER -verbose -- without it the stage runs identically but reports no
    # congestion at all, which is precisely the "measured nothing, said nothing"
    # hole being closed here. -verbose only adds log output; it does not change
    # routing behaviour.
    _cong_rpt = os.path.join(_OUTPUT_DIR, "congestion.rpt")
    _gr_opts += f" -congestion_report_file {_cong_rpt} -verbose"
    _dr_opts = ""
    _vip = params.get("via_in_pin_layers")
    if isinstance(_vip, (list, tuple)) and len(_vip) == 2:
        _dr_opts += (f" -via_in_pin_bottom_layer {_vip[0]}"
                     f" -via_in_pin_top_layer {_vip[1]}")
    _fill, _fill_err = _filler_settings(params, policy, binding)
    if _fill_err:
        return _cde(objective="routing", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error=_fill_err, validation={"verdict": "fail"})
    _fill_tcl = _filler_tcl(_fill)  # count probe only; insertion = placement insert_fill
    _vlog_tcl = _netlist_write_tcl(out_netlist, _fill["filler_cells"] + _fill["tap_cells"])

    # --- ECO re-route support (unroute_first) --------------------------------
    # Routing an ALREADY-ROUTED design (the normal case after a post-route ECO
    # such as repair_design resizing drivers) does NOT work by simply re-running
    # the router: global_route sees every net already routed, emits ZERO guides,
    # and detailed_route then dies with the opaque
    #   [ERROR DRT-0047] Design has no global routing guides.
    #
    # `unroute_first` destroys existing per-net wiring before routing, so
    # global_route has something to plan. It is OPT-IN and never implicit:
    # silently discarding routing on a design the caller believed was routed
    # would be a destructive surprise. Special nets (power/ground) are untouched
    # -- only regular-net wires are destroyed.
    #
    # SCOPE. `true` unroutes EVERY signal net (clean slate). A LIST of net names
    # / globs unroutes only those, which is the ECO case: global_route plans
    # exactly the nets that now lack wiring and leaves every other net's
    # geometry byte-identical, so a proven-good route is not thrown away to fix
    # a handful of nets. Measured on crc16_ccitt (290 nets, sky130): scoping to
    # 1/5/25/100 nets changed ONLY the targeted nets, and the full-slate reroute
    # cost 57.0 s against 15.0 s scoped.
    #
    # `-start_incremental`/`-end_incremental` are deliberately NOT used: those
    # reroute nets that GRT's own callbacks marked dirty, and destroying a wire
    # through OpenDB does not mark a net dirty -- measured "Routed nets: 0".
    # Plain global_route routes whatever lacks wiring, which is what is wanted.
    _unroute_raw = params.get("unroute_first")
    _unroute_pats, _err = _unroute_patterns(_unroute_raw)
    if _err:
        return _cde(objective="routing", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error=_err, validation={"verdict": "fail"})
    _unroute = _unroute_pats is not None
    _scoped = bool(_unroute_pats) and _unroute_pats != ["*"]
    # --- BLAST-RADIUS GUARD on the full-slate reroute ------------------------
    #
    # A full-slate `unroute_first: true` DESTROYS EVERY signal net's wiring. On
    # an already-routed design that discards a proven asset -- crc16_ccitt
    # routing.1 was a terminal DRC=0 route -- and it is irreversible within the
    # run: if the reroute dies, the stage produces nothing and the budget is
    # spent.
    #
    # That is exactly how routing.2 was lost. A restored PDN and a full reroute
    # were combined into ONE step; both attempts died with exit 137 before any
    # artifact was written, and because two independent changes moved together
    # neither could be blamed. Each change is independently revertible; the
    # combination is not.
    #
    # WHAT THIS GUARD DOES NOT CLAIM. It does not predict the OOM and it does
    # not diagnose the input. I tested both tempting theories against the real
    # pdn.1 DEF and BOTH ARE FALSE: the PDN occupies met1-met5, so PDN/signal
    # layer overlap is normal and unavoidable rather than a defect signal; and
    # all six generated vias ARE defined in the DEF's VIAS section, so the
    # "referenced-but-undefined via" theory was my own parser bug. A guard
    # built on either would fire on healthy designs and prove nothing.
    #
    # What IS measurable is the blast radius: how many nets have wiring that
    # this call is about to destroy. Since a SCOPED reroute now exists, a
    # full-slate one is a deliberate choice and is made to look like one.
    _ack_full = bool(params.get("acknowledge_full_reroute"))
    _full_slate = _unroute_pats == ["*"]
    _pre = ""
    if _unroute:
        _pl = " ".join("{%s}" % p for p in (_unroute_pats or ["*"]))
        _pre = (
            "set _pats [list %s]\n"
            "set _blk [ord::get_db_block]\n"
            # COUNT BEFORE DESTROYING. The blast radius has to be known while
            # the wiring still exists; counting afterwards reports what was
            # lost, which is too late to refuse.
            "set _routed0 0\n"
            "foreach _net [$_blk getNets] {\n"
            "  if {[$_net isSpecial]} { continue }\n"
            "  if {[$_net getWire] != \"NULL\"} { incr _routed0 }\n"
            "}\n"
            "puts \"__ROUTED_BEFORE__ $_routed0\"\n"
            "if {%d && $_routed0 > 0} {\n"
            "  puts \"__REFUSE_FULL_REROUTE__ $_routed0\"\n"
            "  exit\n"
            "}\n"
            "set _n 0\n"
            "set _hits {}\n"
            % (_pl, 1 if (_full_slate and not _ack_full) else 0)
        ) + (
            "foreach _net [$_blk getNets] {\n"
            "  if {[$_net isSpecial]} { continue }\n"
            "  set _w [$_net getWire]\n"
            "  if {$_w == \"NULL\"} { continue }\n"
            "  set _nm [$_net getName]\n"
            "  set _hit 0\n"
            # Exact name first, THEN glob. Net names legitimately contain '[' and
            # ']' (bus bits such as crc_nxt[0]), which `string match` would treat
            # as a character class and silently fail to match.
            "  foreach _p $_pats {\n"
            "    if {$_nm eq $_p || [string match $_p $_nm]} { set _hit 1; break }\n"
            "  }\n"
            "  if {!$_hit} { continue }\n"
            "  odb::dbWire_destroy $_w\n"
            "  incr _n\n"
            "  lappend _hits $_nm\n"
            "}\n"
            "puts \"__UNROUTED__ $_n\"\n"
            "puts \"__UNROUTED_NETS__ $_hits\"\n")

    # POWER-CONNECTIVITY PRECONDITION, evaluated on the INPUT before routing.
    #
    # routing.2 discovered "no SPECIALNETS and no VPWR/VGND" only at FINAL
    # ARTIFACT INSPECTION -- after the whole stage had run and after routing.1
    # had already been blessed `verdict: pass` on a design that could never
    # satisfy the mandatory power-connectivity requirement. The condition is
    # knowable up front, so it is measured up front.
    #
    # Classified by SIGNAL TYPE, never by name: VPWR/VDD/vccd1 differ per PDK,
    # but POWER/GROUND is what OpenDB records. Two facts are gathered -- how
    # many power/ground NETS exist, and whether the placed cells even HAVE
    # power/ground terminals needing connection. A design whose cells demand
    # power but whose netlist contains no power nets cannot be power-connected
    # by any amount of signal routing. Verified on crc16_ccitt routing.1:
    # 0 PG nets, 0 special nets, while every cell carries 4 PG terminals.
    _pdn_probe = (
        "set _b [ord::get_db_block]\n"
        "set _pg 0\n"
        "set _sp 0\n"
        "set _rail 0\n"
        "foreach _n [$_b getNets] {\n"
        "  if {[$_n isSpecial]} { incr _sp }\n"
        "  set _t [$_n getSigType]\n"
        "  if {$_t != \"POWER\" && $_t != \"GROUND\"} { continue }\n"
        "  incr _pg\n"
        # A REAL SUPPLY RAIL, not merely a POWER/GROUND-typed net. Measured on
        # this campaign's own cts.odb: the tie-low net `zero_` carries GROUND
        # sigtype with no special flag and no geometry, so counting sigtype
        # alone scored pg_nets=1 -- and `power_connectable` (pg > 0) then
        # reported TRUE for a design with 0 special nets and 394 cells needing
        # power. A falsely reassuring number about an unpowerable design is
        # worse than no number. A rail is SPECIAL and carries SWIRE geometry,
        # which is what physically distributes power.
        "  if {[$_n isSpecial] && [llength [$_n getSWires]] > 0} { incr _rail }\n"
        "}\n"
        "set _need 0\n"
        "set _unc 0\n"
        "foreach _i [$_b getInsts] {\n"
        "  set _has 0\n"
        "  foreach _it [$_i getITerms] {\n"
        "    set _t [[$_it getMTerm] getSigType]\n"
        "    if {$_t != \"POWER\" && $_t != \"GROUND\"} { continue }\n"
        "    set _has 1\n"
        # A cell can HAVE supply pins and still not be attached to the grid.
        # Measured on crc16_ccitt: rails intact 2 -> 2 while 36 supply pins on
        # CTS buffers and the tie cell sat unconnected, and check_power_grid
        # passed anyway because it audits the grid, not the attachment to it.
        "    if {[$_it getNet] == \"NULL\"} { incr _unc }\n"
        "  }\n"
        "  if {$_has} { incr _need }\n"
        "}\n"
        "puts \"__PDN__ pg_nets=$_pg special_nets=$_sp rails=$_rail cells_needing_pg=$_need unconnected_pg=$_unc\"\n")

    # Liberty may classify a tie-cell output net as POWER/GROUND even though it
    # is an ordinary routed constant net. TritonRoute rejects such regular nets
    # with DRT-0305. Preserve actual supply rails (special nets with SWIRE
    # geometry) and normalize only geometry-free, non-special tie nets.
    _tie_net_normalize = (
        "set _tn_fixed 0\n"
        "set _tn_names {}\n"
        "foreach _tn [$_b getNets] {\n"
        "  set _tn_t [$_tn getSigType]\n"
        "  if {$_tn_t != \"POWER\" && $_tn_t != \"GROUND\"} { continue }\n"
        "  if {[$_tn isSpecial] || [llength [$_tn getSWires]] > 0} { continue }\n"
        "  $_tn setSigType SIGNAL\n"
        "  incr _tn_fixed\n"
        "  lappend _tn_names [$_tn getName]\n"
        "}\n"
        "puts \"__TIE_NET_NORMALIZE__ count=$_tn_fixed nets=$_tn_names\"\n")

    script = f"""{loader}
{_PG_RECONNECT_TCL}{_pdn_probe}{_tie_net_normalize}{_pre}set_routing_layers -signal {bot}-{topl}
global_route{_gr_opts}
detailed_route -output_drc {drc_rpt}{_dr_opts}
set _open_nets 0
set _open_names {{}}
foreach _cn [[ord::get_db_block] getNets] {{
  if {{[$_cn isSpecial]}} {{ continue }}
  set _terms [expr {{[llength [$_cn getITerms]] + [llength [$_cn getBTerms]]}}]
  if {{$_terms < 2}} {{ continue }}
  if {{[$_cn getWire] == "NULL"}} {{
    incr _open_nets
    lappend _open_names [$_cn getName]
  }}
}}
puts "__CONNECTIVITY__ opens=$_open_nets nets=$_open_names"
{_fill_tcl}write_def {out_def}
write_db {out_odb}
{_vlog_tcl}exit
"""
    proc, out, elapsed = _run_script(script, "route")
    # Blast radius, measured while the wiring still existed.
    _routed_before = None
    _mrb = re.search(r"__ROUTED_BEFORE__\s+(\d+)", out)
    if _mrb:
        _routed_before = int(_mrb.group(1))
    _mref = re.search(r"__REFUSE_FULL_REROUTE__\s+(\d+)", out)
    if _mref:
        _n = int(_mref.group(1))
        return _cde(
            objective="routing", status="failed",
            pdk_binding=binding or "none", inputs_ref=inputs,
            error=(
                f"refusing a full-slate reroute: `unroute_first: true` would "
                f"destroy the wiring of all {_n} routed signal net(s) on this "
                f"design, discarding a route that already exists. Nothing has "
                f"been modified. This is how routing.2 was lost -- a restored "
                f"PDN and a full reroute were combined into one irreversible "
                f"step, and when it died no artifact survived and neither "
                f"change could be blamed. Choose one: (a) scope the reroute to "
                f"the nets that actually need it, e.g. "
                f"`unroute_first: [\"net_a\", \"bus[0]\"]`, which leaves every "
                f"other net's geometry byte-identical; or (b) if a full reroute "
                f"really is intended, set `acknowledge_full_reroute: true` and "
                f"change ONE thing at a time so a failure is attributable."),
            qor={"routed_nets_at_risk": _n, "nets_destroyed": 0},
            validation={"verdict": "fail"})
    _unrouted_n = None
    _m = re.search(r"__UNROUTED__\s+(\d+)", out)
    if _m:
        _unrouted_n = int(_m.group(1))
    _unrouted_names = []
    _mn = re.search(r"__UNROUTED_NETS__\s*(.*)", out)
    if _mn:
        # Tcl's list formatting BRACES any element containing glob-special
        # characters, so a bus bit comes back as `{crc_nxt[0]}`. Strip that
        # framing or the reported name will not match the netlist name.
        _unrouted_names = [n[1:-1] if n.startswith("{") and n.endswith("}") else n
                           for n in _mn.group(1).split()]
    # A SCOPED unroute that matched NOTHING is not a no-op to shrug at: nothing
    # was unrouted, so global_route has nothing to plan and detailed_route dies
    # at DRT-0047. Report the empty match as the cause rather than letting the
    # generic DRT-0047 text blame an "already routed" design and send the caller
    # to the destructive full-slate path.
    if _scoped and _unrouted_n == 0:
        return _cde(
            objective=f"routing of {top}", status="failed",
            pdk_binding=binding or "none", inputs_ref=inputs,
            error=("scoped unroute matched NO routed signal net: none of the "
                   "requested patterns %r selected a net that currently has "
                   "wiring, so nothing was unrouted and there is nothing to "
                   "route. Check the net names against the routed netlist "
                   "(bus bits look like 'crc_nxt[0]'; matching is exact-name "
                   "first, then glob)." % (_unroute_pats,)),
            signoff={"unroute_scope": "scoped", "unroute_patterns": _unroute_pats,
                     "nets_unrouted": 0},
            validation={"verdict": "fail"},
            provenance={"openroad": "openroad", "log": "route.log"})
    # Turn the opaque DRT-0047 into an actionable instruction rather than letting
    # a caller re-run the identical command and get the identical failure.
    if "DRT-0047" in out and not _unroute:
        return _cde(
            objective=f"routing of {top}", status="failed",
            pdk_binding=binding or "none", inputs_ref=inputs,
            error=("global routing produced no guides: the input design is ALREADY "
                   "ROUTED, so global_route had nothing to plan and detailed_route "
                   "failed with DRT-0047. This is the normal state after a "
                   "post-route ECO (e.g. post_route_repair resizes drivers, which "
                   "invalidates the existing routing). Re-run with "
                   "\"unroute_first\" set to the LIST of nets the ECO touched -- "
                   "e.g. [\"net_a\", \"net_b\"] -- to reroute only those and keep "
                   "the rest of the proven route intact; or \"unroute_first\": true "
                   "to discard ALL per-net wiring and route from a clean slate."),
            validation={"verdict": "fail"},
            provenance={"openroad": "openroad", "log": "route.log"})
    # Fail closed on a silent no-op: a 0-exit that wrote no (or an empty)
    # DEF/ODB/netlist
    # -- e.g. a wrong bind-mount / output path -- must NOT be reported as success.
    _def_ok = os.path.exists(out_def) and os.path.getsize(out_def) > 0
    _odb_ok = os.path.exists(out_odb) and os.path.getsize(out_odb) > 0
    _netlist_ok = os.path.exists(out_netlist) and os.path.getsize(out_netlist) > 0
    if proc.returncode != 0 or not _def_ok or not _odb_ok or not _netlist_ok:
        _why = ("nonzero exit" if proc.returncode != 0
                else "routed DEF/ODB/netlist missing or empty (silent no-op: check output path/mount)")
        # Global route may well have COMPLETED and measured congestion before
        # detailed route failed -- and congestion is frequently the reason. Carry
        # the measurement into the failure envelope instead of discarding the one
        # number that explains the failure.
        _fc = _parse_congestion(out)
        return _cde(objective=f"routing of {top}", status="failed", pdk_binding=binding or "none",
                    error=f"OpenROAD routing failed ({_why}); see route.log:\n" + out[-1500:],
                    qor={"congestion_usage_pct": (_fc or {}).get("overall_usage_pct"),
                         "congestion_overflow": (_fc or {}).get("total_overflow")},
                    signoff={"congestion": _fc, "congestion_measured": _fc is not None,
                             "upstream_feedback": _upstream_feedback(
                                 _fc, None, bool(_unroute)) or None,
                             "report": "route.log"},
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "route.log"})
    # TritonRoute prints "Number of violations = N" ONCE PER rip-up/reroute
    # iteration (e.g. 74 -> 6 -> 13 -> 0). The AUTHORITATIVE result is the FINAL
    # (converged) iteration -- the LAST such line -- not the first. Reading the
    # first match reports an early non-residual count as the signoff DRC (observed
    # live: routing.10 native CDE mis-reported 74 while the run converged to 0).
    _viol = re.findall(r"number of violations\s*=\s*(\d+)", out, re.I)
    if not _viol:
        _viol = re.findall(r"violations:\s*(\d+)", out, re.I)
    drc = int(_viol[-1]) if _viol else (0 if "0 violations" in out.lower() else None)
    # COMPLETION GATES CLEANLINESS. A zero DRC count is only signoff evidence
    # if detailed routing actually FINISHED. TritonRoute announces that with
    #   [INFO DRT-0198] Complete detail routing.
    # and writes an EMPTY DRC report when the design is clean -- so an empty
    # report plus no DRT-0198 is "we stopped early", not "there is nothing
    # wrong". Measured on crc16_ccitt: a repair_design -reroute variant sat at
    # 194/195/194 violations and never emitted DRT-0198, while the bracketed
    # flow converged 136 -> 37 -> 26 -> 0 AND printed it.
    #
    # This also closes the routing.2 reading, where drc_violations = 0 was
    # taken from a ZERO-BYTE report: without a completion marker an empty file
    # is indistinguishable from a file nothing ever wrote to.
    #
    # Matched as `[INFO DRT-0198]`, the verbatim form in the campaign logs, not
    # as a bare substring: a bare `"DRT-0198" in out` would also be satisfied
    # by `[ERROR DRT-0198] ...` or by the id appearing in a diagnostic, i.e. a
    # FAILURE could announce completion. Severity is part of the claim.
    route_completed = re.search(r"\[INFO\s+DRT-0198\]", out) is not None
    _mc = re.search(r"__CONNECTIVITY__ opens=(\d+)", out)
    opens = int(_mc.group(1)) if _mc else None
    shorts = 0 if drc == 0 else None
    clean = drc == 0 and route_completed and opens == 0
    _completion_note = None
    if drc == 0 and not route_completed:
        _completion_note = (
            "detailed routing did not report DRT-0198 (Complete detail "
            "routing), so a zero violation count is NOT signoff evidence -- "
            "the run stopped before converging and an empty DRC report is "
            "indistinguishable from one that was never written")

    # Power connectivity, read after the node-portable supply reconnect.
    _pg_reconnect = _parse_pg_reconnect(out)
    _pdn = None
    _pdn_note = None
    _mp = re.search(r"__PDN__ pg_nets=(\d+) special_nets=(\d+) "
                    r"rails=(\d+) cells_needing_pg=(\d+)"
                    r"(?: unconnected_pg=(\d+))?", out)
    if _mp:
        _pdn = {"power_ground_nets": int(_mp.group(1)),
                "special_nets": int(_mp.group(2)),
                "supply_rails": int(_mp.group(3)),
                "cells_needing_power": int(_mp.group(4)),
                # A log predating this probe reads as NOT MEASURED, never zero.
                "unconnected_pg_pins": (int(_mp.group(5))
                                        if _mp.group(5) is not None else None)}
        # KEYED ON RAILS, NOT SIGTYPE. `power_ground_nets > 0` was the original
        # test and it is falsely reassuring: the tie-low net `zero_` carries
        # GROUND sigtype, so on this campaign's real cts.odb the rule scored
        # pg=1 and declared a design with 0 special nets and 394 cells needing
        # power "power_connectable". A rail is a SPECIAL power/ground net that
        # carries SWIRE geometry -- the thing that actually distributes power.
        _pdn["power_connectable"] = (_pdn["supply_rails"] > 0
                                     or _pdn["cells_needing_power"] == 0)
        if not _pdn["power_connectable"]:
            _pdn_note = (
                "NO POWER CONNECTIVITY: the design has %d cell(s) with "
                "power/ground terminals but %d supply rail(s) (%d "
                "POWER/GROUND-typed net(s), %d special net(s)). Signal "
                "routing cannot make this design power-connected, so this "
                "result cannot satisfy a power connectivity gate however "
                "clean its signal DRC is -- build the PDN before routing"
                % (_pdn["cells_needing_power"], _pdn["supply_rails"],
                   _pdn["power_ground_nets"], _pdn["special_nets"]))
            # A design that cannot be power-connected must never be reported as
            # an unqualified clean route; that is exactly how routing.1 came to
            # be blessed `pass` on a design routing.2 then found unshippable.
            clean = False
        elif _pdn["unconnected_pg_pins"]:
            _pdn_note = (
                "%d supply pin(s) are NOT connected to the power grid: the "
                "grid itself is intact (%d rail(s)), but the cells carrying "
                "these pins never joined it and are therefore dead. "
                "check_power_grid does NOT catch this -- it audits the grid, "
                "not each instance's attachment to it."
                % (_pdn["unconnected_pg_pins"], _pdn["supply_rails"]))
            clean = False
    cong = _parse_congestion(out)
    _fill_rec, _fill_warn = _parse_fill(out, _fill)
    env = _cde(
        objective=f"global + detailed routing of {top}",
        status="completed",
        pdk_binding=binding or "none",
        results={"drc_violations": {"value": drc, "unit": "count"},
                 "opens": {"value": opens, "unit": "count"},
                 "shorts": {"value": shorts, "unit": "count"},
                 "layer_range": {"value": f"{bot}-{topl}", "unit": "layers"},
                 "routing_congestion": {
                     "value": (cong or {}).get("overall_usage_pct"),
                     "unit": "percent_of_tracks"},
                 "congestion_overflow": {
                     "value": (cong or {}).get("total_overflow"),
                     "unit": "count"}},
        qor={"drc_violations": drc, "routed": True,
             "nets_unrouted_before_reroute": _unrouted_n,
             "congestion_usage_pct": (cong or {}).get("overall_usage_pct"),
             "worst_layer_usage_pct": (cong or {}).get("worst_layer_usage_pct"),
             "worst_congested_layer": (cong or {}).get("worst_layer"),
             "congestion_overflow": (cong or {}).get("total_overflow"),
             "filler_cells_total": _fill_rec["filler_cells_total"]},
        signoff={"routed_def": "routed.def", "routed_odb": "routed.odb",
                 "routed_netlist": "routed.v",
                 # Routing does not insert fill (chip-placement insert_fill does,
                 # on routed.def/odb); this records the routed design's filler
                 # count and the physical-only masters routed.v omits.
                 "filler_cells": _fill_rec,
             "drc_report": "route_drc.rpt",
                 "connectivity": "complete" if os.path.exists(out_def) else "incomplete",
                 "clean": clean, "report": "route.log",
                 # Whether TritonRoute announced DRT-0198. `clean` requires it,
                 # so a zero count from an unfinished run cannot be read as
                 # signoff evidence.
                 "detailed_route_completed": route_completed,
                 "completion_caveat": _completion_note,
                 # Measured on the INPUT, before routing: whether this design
                 # can be power-connected at all. Signal routing never creates
                 # power nets, so a design with none cannot pass a power
                 # connectivity gate no matter how clean its signal DRC is.
                 "power_connectivity": _pdn,
                 "power_connectivity_caveat": _pdn_note,
                 "power_reconnect": _pg_reconnect,
                 "eco_reroute": bool(_unroute),
                 "unroute_scope": (None if not _unroute
                                   else ("scoped" if _scoped else "all_signal_nets")),
                 "unroute_patterns": _unroute_pats,
                 "nets_unrouted_before_reroute": _unrouted_n,
                 # Blast radius, measured before anything was destroyed: how
                 # many nets carried wiring going in. A full-slate reroute on a
                 # non-zero count discarded an existing route, so provenance
                 # records both the size of that loss and the fact that it was
                 # deliberately acknowledged.
                 "routed_nets_before_reroute": _routed_before,
                 "full_reroute_acknowledged": (
                     _ack_full if (_full_slate and _routed_before) else None),
                 "nets_unrouted_names": (_unrouted_names[:200] or None),
                 "nets_unrouted_names_truncated": len(_unrouted_names) > 200,
                 # A scoped reroute preserves the geometry of every net it did
                 # not target -- EXCEPT that re-entering detailed_route perturbs
                 # a small fixed set of nets (measured on crc16_ccitt: the clock
                 # nets, identically in a null control that unrouted nothing).
                 # Post-CTS skew is therefore NOT preserved by construction and
                 # must be re-checked; claiming otherwise would be unmeasured.
                 "scoped_reroute_caveat": (
                     "detailed_route perturbs clock-net geometry on any re-entry, "
                     "including when nothing was unrouted; re-verify CTS skew and "
                     "post-route timing rather than assuming they are unchanged"
                     if _scoped else None),
                 # MEASURED congestion, not the effort knob that was requested.
                 "congestion": cong,
                 "congestion_measured": cong is not None,
                 # WHICH UPSTREAM STAGE MUST CHANGE. Routing sees congestion but
                 # does not own the track budget; naming the stage and the knob
                 # is what turns a residual into an actionable hand-back.
                 "upstream_feedback": _upstream_feedback(
                     cong, drc, bool(_unroute)) or None,
                 "congestion_iterations_requested": _cong_iter,
                 "route_options": (_gr_opts + _dr_opts).strip() or "default"},
        inputs_ref=inputs,
        assumptions=["signal routing on the node layer range; power routing via PDN",
                     "congestion is read from the GRT-0096 final congestion report; "
                     "overflow > 0 means GCells demand more tracks than exist"],
        validation={"verdict": "pass" if clean else ("fail" if drc else "pass_with_caveats"),
                    # The headline must describe the ACTUAL residual. `clean`
                    # is now gated on completion and power connectivity too, so
                    # "violations remain" would be a false headline on a design
                    # whose DRC is 0 but whose PDN is missing.
                    "note": ("DRC-clean routing" if clean
                             else ("routing DRC violations remain" if drc
                                   else "signal DRC is 0 but the route is not "
                                        "signoff-clean"))
                    + ("" if _completion_note is None
                       else "; " + _completion_note)
                    + ("" if _pdn_note is None else "; " + _pdn_note)
                    + ("" if cong is None
                       else (f"; congestion {cong['overall_usage_pct']}% of tracks"
                             + (f", OVERFLOW {cong['total_overflow']} GCell-track(s) "
                                f"on {cong['worst_layer']}"
                                if cong["congested"] else ", no overflow")))
                    + ("; congestion NOT measured (no GRT-0096 report in the log)"
                       if cong is None else "")
                    + "".join("; WARNING: " + w for w in _fill_warn)},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "route.log", "setting_sources": dict(
                        setting_sources, congestion_iterations=cong_source,
                        filler_cells=_fill["filler_cells_source"])},
    )
    if _fill_warn:
        env["envelope_warnings"] = list(env.get("envelope_warnings") or []) + _fill_warn
        env["warnings"] = list(_fill_warn)
    return env


def _repair_scenario(params, scenario):
    if not shutil.which("openroad"):
        return _cde(objective=scenario, status="failed", error="openroad not found on PATH",
                    validation={"verdict": "fail"})
    # Every repair scenario below INSERTS CELLS -- repair_design/repair_timing
    # buffers, or antenna diodes -- and OpenROAD does not attach their supply
    # pins on creation. Re-attached after detailed_placement, before the design
    # is re-routed and written. See _PG_RECONNECT_TCL.
    _pg_reconnect = _PG_RECONNECT_TCL
    binding = params.get("pdk_binding") or {}
    need_timing = scenario in ("post_global_route_repair", "post_route_timing_optimization")
    loader, inputs, failure = _load_design(params, binding, scenario, require_liberty=need_timing)
    if failure:
        return failure
    bot, topl, sources, failure = _routing_settings(params, binding)
    if failure:
        return failure
    #: Populated by the timing-repair branches below; stays empty for antenna
    #: repair, which runs no resizer transforms.
    repair_transforms = {}
    policy = _stage_policy(binding)
    wsig, wclk, wsrc = _wire_rc_layers(params, policy, binding, bot, topl)
    sources.update(wsrc)
    wire_rc = _set_wire_rc_cmds(wsig, wclk)
    sdc = params.get("sdc")
    if need_timing and (not sdc or not os.path.exists(str(sdc))):
        return _cde(objective=scenario, status="failed", pdk_binding=binding or "none",
                    inputs_ref=inputs, error="missing or unreadable required field 'sdc'",
                    validation={"verdict": "fail"})
    if sdc:
        inputs["sdc"] = sdc
    out_names = {
        "post_global_route_repair": "global_route_repaired",
        "post_route_timing_optimization": "route_timing_optimized",
        "antenna_repair": "antenna_repaired"}
    stem = out_names[scenario]
    out_def = os.path.join(_OUTPUT_DIR, stem + ".def")
    out_odb = os.path.join(_OUTPUT_DIR, stem + ".odb")
    drc = os.path.join(_OUTPUT_DIR, stem + "_drc.rpt")
    # MEASURE the congestion these scenarios leave behind, on the FINAL
    # global_route only.
    #
    # routing.2 recorded this exact hole in its own envelope: "The
    # post_global_route_repair scenario did not request a GRT-0096 congestion
    # report, so numeric GCell overflow is unavailable" -- and then declared
    # congestion "resolved_by_detailed_route_completion", which is an INFERENCE
    # recorded as a measurement.
    #
    # `-verbose` is REQUIRED: OpenROAD writes the report FILE only when there is
    # overflow, so file-absence is not evidence of a clean grid; the
    # authoritative GRT-0096 table is printed to the log ONLY under -verbose.
    # Attaching it to the final global_route (never the pre-repair one) keeps a
    # single authoritative table in the log, and `_parse_congestion` takes the
    # last one regardless.
    _repair_cong_rpt = os.path.join(_OUTPUT_DIR, stem + "_congestion.rpt")
    _repair_gr_opts = f" -congestion_report_file {_repair_cong_rpt} -verbose"
    prelude = f"{loader}\nset_routing_layers -signal {bot}-{topl}\n"
    if scenario == "post_global_route_repair":
        setup_margin, sources["setup_margin"] = _resolve(params, policy, "setup_margin", 0.0)
        hold_margin, sources["hold_margin"] = _resolve(params, policy, "hold_margin", 0.0)
        repair_spef = params.get("repair_spef")
        if repair_spef:
            if not os.path.exists(str(repair_spef)):
                return _cde(objective=scenario, status="failed", pdk_binding=binding or "none",
                            inputs_ref=inputs, error=f"repair_spef not found: {repair_spef}",
                            validation={"verdict": "fail"})
            parasitics = f"read_spef {{{repair_spef}}}"
            sources["parasitics"] = "read_spef (annotated real extracted parasitics)"
            inputs["repair_spef"] = repair_spef
        else:
            parasitics = "estimate_parasitics -global_routing"
            sources["parasitics"] = "estimate_parasitics -global_routing"
        rd_opts = ""
        slew_margin = params.get("slew_margin")
        cap_margin = params.get("cap_margin")
        if slew_margin is not None:
            rd_opts += f" -slew_margin {slew_margin}"
            sources["slew_margin"] = "caller"
        if cap_margin is not None:
            rd_opts += f" -cap_margin {cap_margin}"
            sources["cap_margin"] = "caller"
        setup_opts, setup_applied, _ts = _repair_timing_opts(params, policy, "setup")
        hold_opts, hold_applied, _th = _repair_timing_opts(params, policy, "hold")
        sources.update(_ts)
        sources.update(_th)
        repair_transforms = {"setup": setup_applied, "hold": hold_applied}
        commands = f"""read_sdc {{{sdc}}}
set_propagated_clock [all_clocks]
global_route
{wire_rc}
{parasitics}
repair_design{rd_opts}
repair_timing -setup -setup_margin {setup_margin}{setup_opts}
repair_timing -hold -hold_margin {hold_margin}{hold_opts}
detailed_placement
{_pg_reconnect}global_route{_repair_gr_opts}
detailed_route -output_drc {{{drc}}}"""
    elif scenario == "post_route_timing_optimization":
        setup_margin, sources["setup_margin"] = _resolve(params, policy, "setup_margin", 0.0)
        hold_margin, sources["hold_margin"] = _resolve(params, policy, "hold_margin", 0.0)
        setup_opts, setup_applied, _ts = _repair_timing_opts(params, policy, "setup")
        hold_opts, hold_applied, _th = _repair_timing_opts(params, policy, "hold")
        sources.update(_ts)
        sources.update(_th)
        repair_transforms = {"setup": setup_applied, "hold": hold_applied}
        commands = f"""read_sdc {{{sdc}}}
set_propagated_clock [all_clocks]
{wire_rc}
estimate_parasitics -global_routing
repair_timing -setup -setup_margin {setup_margin}{setup_opts}
repair_timing -hold -hold_margin {hold_margin}{hold_opts}
detailed_placement
{_pg_reconnect}global_route{_repair_gr_opts}
detailed_route -output_drc {{{drc}}}
report_checks -path_delay min_max -fields {{slew cap input_pin}} > {os.path.join(_OUTPUT_DIR, 'post_route_timing.rpt')}"""
    else:
        diode, sources["diode_cell"] = _resolve(
            params, policy, "diode_cell", binding.get("antenna_diode_cell"))
        iterations, sources["antenna_iterations"] = _resolve(
            params, policy, "antenna_iterations", 3)
        ratio, sources["ratio_margin"] = _resolve(params, policy, "ratio_margin", 0.0)
        if not diode:
            return _cde(objective=scenario, status="failed", pdk_binding=binding or "none",
                        inputs_ref=inputs,
                        error="missing required field 'diode_cell' (check pdk_binding/tool_policy.routing)",
                        validation={"verdict": "fail"})
        # Antenna mitigation MODE. OpenROAD can fix an antenna violation two ways
        # and they cost different things:
        #   * diode insertion -- adds a real cell, so it consumes area and needs
        #     placement legalization afterwards;
        #   * layer jumping -- routes the offending net up and back down through a
        #     higher layer to break the charge-collecting run, costing routing
        #     resource instead of area.
        # `both` (default) lets the tool choose per net, which is what a production
        # flow wants; the single-mode options exist for a congested design (prefer
        # diodes) or an area-critical one (prefer jumpers).
        mode = str(params.get("antenna_mode")
                   or policy.get("antenna_mode") or "both").lower()
        if mode not in ("both", "diode_only", "jumper_only"):
            return _cde(objective=scenario, status="failed",
                        pdk_binding=binding or "none", inputs_ref=inputs,
                        error="antenna_mode must be both, diode_only, or jumper_only",
                        validation={"verdict": "fail"})
        sources["antenna_mode"] = ("caller" if params.get("antenna_mode")
                                   else ("pdk_binding.tool_policy"
                                         if policy.get("antenna_mode") else "tool_default"))
        mode_flag = "" if mode == "both" else " -" + mode
        if bool(params.get("antenna_allow_congestion")):
            mode_flag += " -allow_congestion"
            sources["antenna_allow_congestion"] = "caller"
        commands = f"""global_route
repair_antennas {diode} -iterations {int(iterations)} -ratio_margin {ratio}{mode_flag}
detailed_placement
{_pg_reconnect}global_route
detailed_route -output_drc {{{drc}}}
check_antennas -report_file {os.path.join(_OUTPUT_DIR, 'antenna.rpt')}"""
    script = f"""{prelude}{commands}
write_def {{{out_def}}}
write_db {{{out_odb}}}
exit
"""
    proc, out, elapsed = _run_script(script, scenario)
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective=scenario, status="failed", pdk_binding=binding or "none",
                    inputs_ref=inputs,
                    error=f"OpenROAD {scenario} failed; see {scenario}.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": scenario + ".log",
                                "setting_sources": sources})
    evidence = {"routed_def": stem + ".def", "routed_odb": stem + ".odb",
                "drc_report": stem + "_drc.rpt"}
    # These scenarios END IN detailed_route, so the same completion doctrine
    # applies here as in _route: the stage previously reported
    # "OpenROAD stage completed; inspect DRC/timing/antenna reports" with NO
    # violation count and NO completion check -- an invitation to read an
    # empty DRC report as clean when routing may have stopped early.
    _rviol = re.findall(r"number of violations\s*=\s*(\d+)", out, re.I)
    _rdrc = int(_rviol[-1]) if _rviol else None
    _rdone = re.search(r"\[INFO\s+DRT-0198\]", out) is not None
    evidence["drc_violations"] = _rdrc
    evidence["detailed_route_completed"] = _rdone
    _rnote = None
    if _rdrc == 0 and not _rdone:
        _rnote = ("detailed routing did not report DRT-0198, so a zero "
                  "violation count is NOT signoff evidence for this repair")
    elif _rdrc is None:
        _rnote = ("no violation count found in the log: this repair's DRC "
                  "state is UNMEASURED, not clean")
    evidence["completion_caveat"] = _rnote
    # MEASURED congestion, now that the scenario actually asks for it. Reported
    # even when None, because "we did not measure" and "we measured zero" are
    # different claims and only one of them is evidence.
    _rcong = _parse_congestion(out)
    evidence["congestion"] = _rcong
    evidence["congestion_measured"] = _rcong is not None
    if _rcong is None:
        evidence["congestion_note"] = (
            "no GRT-0096 table in the log: congestion is UNMEASURED for this "
            "run, which is not the same as uncongested")
    if scenario == "antenna_repair":
        evidence["antenna_report"] = "antenna.rpt"
        evidence["antenna_mode"] = mode
    if scenario == "post_route_timing_optimization":
        evidence["timing_report"] = "post_route_timing.rpt"
    if repair_transforms:
        evidence["repair_transforms"] = repair_transforms
    return _cde(objective=scenario.replace("_", " "), status="completed",
                pdk_binding=binding or "none", inputs_ref=inputs,
                results={"optimization_completed": {"value": True, "unit": "bool"}},
                signoff=evidence,
                validation={"verdict": "pass_with_caveats",
                            "note": "OpenROAD stage completed; inspect DRC/timing/antenna reports"
                                    + ("" if _rnote is None else "; " + _rnote)},
                provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                            "log": scenario + ".log", "setting_sources": sources,
                            "repair_transforms": repair_transforms or None})



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
    if s == "route":
        return _route(params)
    if s in ("post_global_route_repair", "post_route_timing_optimization", "antenna_repair"):
        return _repair_scenario(params, s)
    return _cde(objective="routing", status="failed",
                error=f"unknown scenario '{s}'; supported: route, post_global_route_repair, post_route_timing_optimization, antenna_repair",
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
