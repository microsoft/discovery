#!/usr/bin/env python3
"""placement_utils.py -- real OpenROAD global + detailed placement.

Reads node LEF/Liberty + a floorplan DEF, runs global_placement and
detailed_placement (legalization), writes a placed DEF, and parses HPWL/legality.
LEF/Liberty/site come from the PDK binding. Node-aware. Results conform to the CDE.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "placement"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"

#: scenario -> the flow ROLE's `dir_token` from catalog/policy/stage-roles.json,
#: which is also the obligation-family recipe key in cde_progress.STAGE_RESIDUALS.
#: Only scenarios whose role this agent actually owns are listed; a scenario that
#: is absent stays unstamped and keeps the historical `TOOL` fallback rather than
#: having a role invented for it. `insert_tap_endcap_decap` is resolved from its
#: own `stage` sub-mode instead (see `_stage_token`), because that one scenario
#: can perform either role.
_STAGE_TOKEN_BY_SCENARIO = {
    "place": "placement",
    "insert_taps": "tapcell",
    "insert_tap_endcap": "tapcell",
    "insert_fill": "decap-fill",
    "insert_decap_fill": "decap-fill",
}
#: Role token for the envelope currently being built. Set by `dispatch`.
_ACTIVE_STAGE_TOKEN = None


def _stage_token(params):
    """The flow role this invocation is acting as, or None when undeclared."""
    scenario = str((params or {}).get("scenario") or "")
    if scenario == "insert_tap_endcap_decap":
        # The combined back-compat scenario picks its role from the insertion
        # sub-mode it was asked for; 'all' does taps first, so it lands in the
        # tapcell role's directory.
        return "decap-fill" if str(
            (params or {}).get("stage", "")).lower() == "fill" else "tapcell"
    token = _STAGE_TOKEN_BY_SCENARIO.get(scenario)
    return str(params.get("stage_token") or token) if (
        params.get("stage_token") or token) else None


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


def _stage_policy(params, binding):
    policy = binding.get("tool_policy", {}) if isinstance(binding, dict) else {}
    stage = policy.get("placement", {})
    return stage.get("settings", stage) if isinstance(stage, dict) else {}


def _resolve(params, policy, key, default=None):
    if key in params and params[key] is not None:
        return params[key], "caller"
    if key in policy and policy[key] is not None:
        return policy[key], "pdk_binding.tool_policy"
    return default, "tool_default"


def _wire_rc_layers(params, policy, binding):
    """Resolve signal/clock routing-layer NAMES for `set_wire_rc`, node-portably.

    The resizer (repair_design / repair_timing) needs a wire-RC model to estimate
    net delay; without a `set_wire_rc` before `estimate_parasitics` OpenROAD raises
    RSZ-0089 and does ZERO buffering/resizing, so the whole repair silently no-ops.
    `set_wire_rc -layer <L>` reads the per-unit R/C for layer <L> straight from the
    tech LEF already loaded, so only a routing LAYER NAME is needed -- never a
    hard-coded R/C constant (keeps node facts out of tool logic).

    Priority: caller param -> tool_policy.placement -> pdk_binding.routing_layers.
    Returns (sig_layer, clk_layer, sources). Placement resolves no routing range of
    its own, so there is no derived fallback: an unresolved layer fails closed at the
    call site rather than reproducing the RSZ-0089 no-op.
    """
    rl = binding.get("routing_layers") if isinstance(binding, dict) else None
    rl = rl if isinstance(rl, dict) else {}
    top = binding if isinstance(binding, dict) else {}
    # Bindings in the field spell the top-level keys ORFS-style
    # (`wire_rc_layer` / `wire_rc_clk_layer`, mirroring setRC.tcl); accept both.
    aliases = {"wire_rc_signal_layer": ("wire_rc_signal_layer", "wire_rc_layer"),
               "wire_rc_clock_layer": ("wire_rc_clock_layer", "wire_rc_clk_layer")}
    def pick(key):
        if key in params and params[key]:
            return params[key], "caller"
        if key in policy and policy[key]:
            return policy[key], "pdk_binding.tool_policy"
        v = rl.get(key) or rl.get(key.replace("_layer", ""))
        if v:
            return v, "pdk_binding.routing_layers"
        for alias in aliases[key]:
            if top.get(alias):
                return top[alias], f"pdk_binding.{alias}"
        return None, "missing"
    sig, sig_src = pick("wire_rc_signal_layer")
    clk, clk_src = pick("wire_rc_clock_layer")
    return sig, clk, {"wire_rc_signal_layer": sig_src, "wire_rc_clock_layer": clk_src}


_SETRC_KEYS = ("setrc_tcl", "set_rc", "setrc", "set_rc_tcl")


def _wire_rc_setup(params, policy, binding):
    """Tcl that establishes the wire-RC model, from the best resolvable source.

    Priority: a setRC Tcl file (caller `setrc_tcl` -> tool_policy -> binding
    `setrc_tcl`/`set_rc`/...; it is the PDK's own per-layer RC, e.g. ORFS
    platforms/<node>/setRC.tcl) -> `set_wire_rc -signal/-clock -layer` from the
    resolved layer names. Returns (tcl, sources, error). tcl is "" when nothing
    resolves -- callers decide whether that is fatal (repair) or a fallback
    (timing-driven placement). A NAMED setRC file that does not exist is an
    error: silently substituting another RC model would misreport the source.
    """
    for key in _SETRC_KEYS:
        for value, src in ((params.get(key), "caller"),
                           (policy.get(key) if isinstance(policy, dict) else None,
                            "pdk_binding.tool_policy"),
                           (binding.get(key) if isinstance(binding, dict) else None,
                            f"pdk_binding.{key}")):
            if value:
                if not os.path.isfile(str(value)):
                    return "", {"wire_rc": src}, (
                        f"{key} names a setRC Tcl file that does not exist: {value}")
                return f"source {{{value}}}\n", {"wire_rc": f"{src}:{key}={value}"}, None
    wsig, wclk, wsrc = _wire_rc_layers(params, policy, binding)
    tcl = ""
    if wsig:
        tcl += f"set_wire_rc -signal -layer {wsig}\n"
    if wclk:
        tcl += f"set_wire_rc -clock -layer {wclk}\n"
    sources = dict(wsrc)
    sources["wire_rc"] = "set_wire_rc_layers" if tcl else "missing"
    return tcl, sources, None


def _physical_cell(params, policy, binding, key):
    """caller -> tool_policy -> binding top-level -> binding.physical_cells."""
    value, src = _resolve(params, policy, key, None)
    if value is None and isinstance(binding, dict):
        if binding.get(key) is not None:
            value, src = binding[key], "pdk_binding"
        elif isinstance(binding.get("physical_cells"), dict) and \
                binding["physical_cells"].get(key) is not None:
            value, src = binding["physical_cells"][key], "pdk_binding.physical_cells"
    return value, src


_PHYSICAL_CELL_KEYS = ("tapcell_master", "endcap_master", "decap_cells", "filler_cells",
                       "tapcell_distance", "halo_width_x", "halo_width_y")


def _resolve_physical_cells(params, policy, binding):
    resolved, sources = {}, {}
    for key in _PHYSICAL_CELL_KEYS:
        resolved[key], sources[key] = _physical_cell(params, policy, binding, key)
    return resolved, sources


def _fill_masters(resolved):
    """Row-fill masters for the fill stage: decap cells first, then plain fillers.
    Nangate45 declares decap_cells=[] and filler_cells=FILLCELL_X1..X32, so the
    filler list alone must be enough."""
    return [str(x) for x in _as_list(resolved.get("decap_cells"))
            + _as_list(resolved.get("filler_cells")) if x]


def _physical_cell_cmds(resolved, stage):
    """THE tapcell / filler_placement command builder. Used by the insert_taps /
    insert_fill / insert_tap_endcap_decap scenarios and reused by `place`
    (insert_tapcells) so there is one implementation. Returns (cmds, error)."""
    cmds = []
    if stage in ("taps", "all"):
        missing = [k for k in ("tapcell_master", "endcap_master", "tapcell_distance")
                   if not resolved.get(k)]
        if missing:
            return [], (f"missing required field '{missing[0]}' (check "
                        "pdk_binding.tool_policy.placement or pdk_binding.physical_cells)")
        tap_opts = (f"-tapcell_master {resolved['tapcell_master']} "
                    f"-endcap_master {resolved['endcap_master']} "
                    f"-distance {resolved['tapcell_distance']}")
        for key in ("halo_width_x", "halo_width_y"):
            if resolved.get(key) is not None:
                tap_opts += f" -{key} {resolved[key]}"
        cmds.append(f"tapcell {tap_opts}")
    if stage in ("fill", "all"):
        masters = _fill_masters(resolved)
        if not masters:
            return [], ("missing required field 'decap_cells' or 'filler_cells' (check "
                        "pdk_binding.tool_policy.placement or pdk_binding.physical_cells)")
        # OpenROAD `filler_placement` takes ONE positional argument: a Tcl list of
        # filler master names. Bare space-separated words are parsed as multiple
        # args and error "requires one positional argument" -- wrap in braces so
        # the whole set is a single list argument.
        cmds.append("filler_placement {" + " ".join(masters) + "}")
    return cmds, None


def _load_design(params, binding, objective, require_liberty=False):
    def_file, odb_file = params.get("def_file"), params.get("odb_file")
    if bool(def_file) == bool(odb_file):
        return None, None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error="provide exactly one of 'def_file' or 'odb_file'",
            validation={"verdict": "fail"})
    source = odb_file or def_file
    if not os.path.exists(str(source)):
        return None, None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error=f"input not found: {source}", validation={"verdict": "fail"})
    libs = _as_list(params.get("liberty") or binding.get("liberty"))
    if require_liberty and not libs:
        return None, None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error="missing required field 'liberty' (check pdk_binding)",
            validation={"verdict": "fail"})
    for path in libs:
        if not os.path.exists(str(path)):
            return None, None, None, _cde(
                objective=objective, status="failed", pdk_binding=binding or "none",
                error=f"input not found: {path}", validation={"verdict": "fail"})
    lib_reads = "\n".join(f"read_liberty {{{p}}}" for p in libs)
    if odb_file:
        return lib_reads + f"\nread_db {{{odb_file}}}", {
            "odb_file": odb_file, "liberty": libs}, libs, None
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    if not tech_lef:
        return None, None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error="missing required field 'tech_lef' (check pdk_binding)",
            validation={"verdict": "fail"})
    for path in [tech_lef] + cell_lefs:
        if not os.path.exists(str(path)):
            return None, None, None, _cde(
                objective=objective, status="failed", pdk_binding=binding or "none",
                error=f"input not found: {path}", validation={"verdict": "fail"})
    collision = _check_lef_collisions([tech_lef] + cell_lefs)
    if collision:
        return None, None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error=collision, validation={"verdict": "fail"})
    lef_reads = "\n".join([f"read_lef {{{tech_lef}}}"] +
                            [f"read_lef {{{p}}}" for p in cell_lefs])
    return lib_reads + "\n" + lef_reads + f"\nread_def {{{def_file}}}", {
        "def_file": def_file, "tech_lef": tech_lef,
        "cell_lef": cell_lefs, "liberty": libs}, libs, None


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


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD", "version": "openroad"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "density"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    # THE STAGE ROLE, NOT THE TOOL IDENTITY, SELECTS THE OBLIGATION FAMILY SET.
    # This agent serves three flow roles (placement / tapcell / decap-fill) from
    # one tool. `save_final_results` stamps progress with
    # `results.get("stage") or TOOL`, so leaving this absent silently selected
    # the PLACEMENT recipe for every tap/endcap and decap-fill attempt. Measured
    # on this campaign: 14 envelopes (4 tapcell, 10 decap-fill) carried the
    # 10-family placement set instead of their own, every family unbindable by
    # construction, which self-reports as a BLOCKING metric defect and denies the
    # stage pointer -- one such attempt stopped an entire design's chain until
    # the stage was stamped by hand after the fact.
    if _ACTIVE_STAGE_TOKEN:
        env["stage"] = _ACTIVE_STAGE_TOKEN
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


#: Pre-placement tap/endcap insertion for `place`. Skips when the input already
#: carries any tap/endcap master instance. Inserted cells' supply pins are tied
#: to the special rails BY SIGTYPE (binding power_net/ground_net preferred, else
#: the unique special POWER/GROUND net): with PDN already built, a DEF's rail
#: connection list was resolved at read time, so new taps would otherwise sit on
#: the rails unconnected -- which the __PDN_OUT__ probe correctly fails.
_TAPS_TCL = r"""set _tb [ord::get_db_block]
set _tap_masters [list @MASTERS@]
set _tap_before 0
foreach _i [$_tb getInsts] { if {[lsearch -exact $_tap_masters [[$_i getMaster] getName]] >= 0} { incr _tap_before } }
set _tap_pg 0
if {$_tap_before == 0} {
  @TAPCMD@
  set _tap_pwr ""
  set _tap_gnd ""
  if {"@PWR@" != "" && [$_tb findNet "@PWR@"] != "NULL"} { set _tap_pwr [$_tb findNet "@PWR@"] }
  if {"@GND@" != "" && [$_tb findNet "@GND@"] != "NULL"} { set _tap_gnd [$_tb findNet "@GND@"] }
  set _tap_p {}
  set _tap_g {}
  foreach _n [$_tb getNets] {
    if {![$_n isSpecial]} { continue }
    if {[$_n getSigType] == "POWER"} { lappend _tap_p $_n }
    if {[$_n getSigType] == "GROUND"} { lappend _tap_g $_n }
  }
  if {$_tap_pwr == "" && [llength $_tap_p] == 1} { set _tap_pwr [lindex $_tap_p 0] }
  if {$_tap_gnd == "" && [llength $_tap_g] == 1} { set _tap_gnd [lindex $_tap_g 0] }
  foreach _i [$_tb getInsts] {
    if {[lsearch -exact $_tap_masters [[$_i getMaster] getName]] < 0} { continue }
    foreach _it [$_i getITerms] {
      if {[$_it getNet] != "NULL"} { continue }
      set _st [[$_it getMTerm] getSigType]
      set _net ""
      if {$_st == "POWER"} { set _net $_tap_pwr } elseif {$_st == "GROUND"} { set _net $_tap_gnd }
      if {$_net == ""} { continue }
      if {[catch {$_it connect $_net}]} { odb::dbITerm_connect $_it $_net }
      catch {$_it setSpecial}
      incr _tap_pg
    }
  }
}
set _tap_after 0
foreach _i [$_tb getInsts] { if {[lsearch -exact $_tap_masters [[$_i getMaster] getName]] >= 0} { incr _tap_after } }
puts "__TAPS__ before=$_tap_before after=$_tap_after pg_connected=$_tap_pg"
"""


def _place(params):
    if not shutil.which("openroad"):
        return _cde(objective="placement", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    top = params.get("top")
    binding = params.get("pdk_binding") or {}
    loader, inputs, libs, failure = _load_design(params, binding, "placement")
    if failure:
        return failure
    policy = _stage_policy(params, binding)
    density_v, density_src = _resolve(params, policy, "density", 0.6)
    density = float(density_v)
    # OpenROAD global_placement -density is a 0-1 FRACTION (unlike floorplan
    # -utilization, which is a 0-100 percentage). Guard against a caller passing
    # a percentage (e.g. 60 for 60%): normalize a 1-100 value to a fraction and
    # fail closed outside (0,100]. Prevents a silent mis-scaled placement.
    if not (0 < density <= 100):
        return _cde(objective="placement", status="failed", pdk_binding=binding or "none",
                    error=f"density {density} out of range; give a 0-1 fraction "
                          f"(e.g. 0.6) or a 0-100 percentage (e.g. 60)",
                    validation={"verdict": "fail"})
    if density > 1:
        density = density / 100.0
    sdc = params.get("sdc")
    _has_sdc = bool(sdc and os.path.exists(str(sdc)))
    # Placement quality levers. timing/routability-driven require an SDC to be
    # meaningful; if requested without one we skip and record the reason.
    _gp_opts = ""
    _place_notes = []
    _caveats = []
    # Wire RC is resolved unconditionally: timing-driven global placement runs
    # the resizer's buffer max-wire-length estimate, which errors RSZ-0089 when
    # no `set_wire_rc` was issued (measured: uart_apb on Nangate45 died in the
    # first Nesterov iteration). It is emitted whenever it resolves -- cheap and
    # harmless -- so the placed ODB carries the same RC model downstream.
    _rc_tcl, _rc_src, _rc_err = _wire_rc_setup(params, policy, binding)
    if _rc_err:
        return _cde(objective="placement", status="failed", pdk_binding=binding or "none",
                    error=_rc_err, validation={"verdict": "fail"})
    _timing_driven = False
    if str(params.get("timing_driven", "")).lower() in ("1", "true", "yes"):
        if not _has_sdc:
            _place_notes.append("timing_driven requested but no SDC supplied; skipped")
        elif not libs:
            _caveats.append("timing_driven requested but no liberty loaded; ran "
                            "NON-timing-driven global placement instead")
        elif not _rc_tcl:
            _caveats.append(
                "timing_driven requested but no wire-RC source resolvable (setrc_tcl, "
                "wire_rc_signal_layer/wire_rc_clock_layer, pdk_binding.routing_layers "
                "or pdk_binding.wire_rc_layer/wire_rc_clk_layer); ran NON-timing-driven "
                "global placement instead of failing RSZ-0089")
        else:
            _gp_opts += " -timing_driven"
            _timing_driven = True
    _place_notes.extend(_caveats)
    # --- optional well-tap / endcap insertion (pre-global-placement) ---------
    # Taps are a floorplan-stage op owned by scenario insert_taps; `place` REUSES
    # that scenario's command builder (_physical_cell_cmds) so a flow that skipped
    # insert_taps still gets taps before global placement, where they become
    # FIXED obstacles the placer legalizes around. Default ON only when the
    # binding declares a tap master and the input carries NO instance of it
    # (decided in Tcl, so ODB input works too); an input that already has taps
    # (e.g. insert_taps already ran) is never re-tapped. Measured on
    # uart_apb/Nangate45: every stage from floorplan to routed DEF had 0
    # TAPCELL_X1 although the binding declares one.
    _phys, _phys_src = _resolve_physical_cells(params, policy, binding)
    _tap_master, _endcap_master = _phys["tapcell_master"], _phys["endcap_master"]
    _tap_dist = _phys["tapcell_distance"]
    _ins_raw = params.get("insert_tapcells", policy.get("insert_tapcells"))
    if _ins_raw is None:
        _insert_taps = bool(_tap_master and _endcap_master and _tap_dist)
        _taps_src = ("default(binding declares tapcell_master)" if _insert_taps
                     else "default(off: no tapcell_master/endcap_master/tapcell_distance)")
    else:
        _insert_taps = str(_ins_raw).lower() in ("1", "true", "yes")
        _taps_src = "caller" if "insert_tapcells" in params else "pdk_binding.tool_policy"
    _taps_tcl = ""
    if _insert_taps:
        _tap_cmds, _tap_err = _physical_cell_cmds(_phys, "taps")
        if _tap_err:
            return _cde(objective="placement", status="failed", pdk_binding=binding or "none",
                        error="insert_tapcells=true but " + _tap_err,
                        validation={"verdict": "fail"})
        _tap_masters = " ".join(sorted({str(_tap_master), str(_endcap_master)}))
        _pwr = str(binding.get("power_net") or "")
        _gnd = str(binding.get("ground_net") or "")
        _taps_tcl = _TAPS_TCL.replace("@MASTERS@", _tap_masters).replace(
            "@TAPCMD@", "\n  ".join(_tap_cmds)).replace("@PWR@", _pwr).replace("@GND@", _gnd)
    if str(params.get("routability_driven", "")).lower() in ("1", "true", "yes"):
        _gp_opts += " -routability_driven"
    _pad_l = params.get("pad_left")
    _pad_r = params.get("pad_right")
    if _pad_l is not None:
        _gp_opts += f" -pad_left {int(_pad_l)}"
    if _pad_r is not None:
        _gp_opts += f" -pad_right {int(_pad_r)}"
    # hierarchy_mode=hierarchical (or explicit incremental=true) enables an
    # incremental global placement pass for block-level / ECO-style flows.
    hierarchy_mode = str(params.get("hierarchy_mode", "flat")).strip().lower()
    if (hierarchy_mode == "hierarchical"
            or str(params.get("incremental", "")).lower() in ("1", "true", "yes")):
        _gp_opts += " -incremental"
    # skip_io: place cells WITHOUT letting I/O pin locations pull them. This is the
    # first half of the standard two-pass idiom both reference flows use --
    # OpenLane runs `GlobalPlacementSkipIO` -> `IOPlacement` -> `GlobalPlacement`,
    # and ORFS does the same. The point is ordering: on a design whose pins are not
    # yet fixed, placing cells first lets the pin placer put each pin next to the
    # logic that drives it, instead of the cells being dragged toward an arbitrary
    # initial pin assignment. Placing IOs first and cells second bakes in whatever
    # the pin order happened to be.
    if str(params.get("skip_io", "")).lower() in ("1", "true", "yes"):
        _gp_opts += " -skip_io"
        _place_notes.append(
            "global placement ran with -skip_io: cell positions ignore pin "
            "locations. This is PASS 1 of the two-pass idiom -- place I/O pins "
            "against this placement, then re-run placement without skip_io.")
    # cluster_flops: fold single-bit flops into multi-bit trays where the library
    # provides them. Real area and (mostly) clock-power lever, because one tray
    # shares a clock pin across N bits instead of presenting N loads to the clock
    # tree. Runs BEFORE global placement so the placer sees the trays.
    _cluster = ""
    if str(params.get("cluster_flops", "")).lower() in ("1", "true", "yes"):
        _c_opts = ""
        for key, flag in (("tray_weight", "-tray_weight"),
                          ("flop_timing_weight", "-timing_weight"),
                          ("clock_power_weight", "-clock_power_weight"),
                          ("max_split_size", "-max_split_size"),
                          ("num_paths", "-num_paths")):
            if params.get(key) is not None:
                _c_opts += " %s %s" % (flag, params[key])
        _cluster = "cluster_flops" + _c_opts + "\n"
        _place_notes.append(
            "multi-bit flop clustering enabled; requires multi-bit flop cells in "
            "the bound library or the pass is a no-op")
    # detailed placement max cell displacement (sites); accepts single or "x y".
    _max_disp = params.get("max_displacement")
    _dp_opts = ""
    if _max_disp is not None:
        _dp_opts = f" -max_displacement {_max_disp}"
    for n, v in (("top", top),):
        if not v:
            return _cde(objective="placement", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}'", validation={"verdict": "fail"})
    out_def = os.path.join(_OUTPUT_DIR, "placed.def")
    out_odb = os.path.join(_OUTPUT_DIR, "placed.odb")
    sdc_line = f"read_sdc {sdc}" if sdc and os.path.exists(str(sdc)) else ""
    # --- POWER-NET CONTINUITY -------------------------------------------------
    #
    # THE INCIDENT. On crc16_ccitt the PDN stage produced a DEF with two power
    # nets (VPWR/VGND, met1 follow-pin rails, met4/met5 straps). Placement was
    # then handed the TAPCELL odb instead -- pdn.1 was a dead-end branch -- so
    # its output had no power nets at all. Placement, CTS, routing, metal-fill,
    # decap-fill and ECO all then ran and reported SUCCESS on a design that
    # could never be power-connected. The loss was noticed at routing.2's final
    # artifact inspection, SIX STAGES after it happened, and the recovery
    # attempt (a hand-spliced DEF plus a full reroute) destroyed a proven
    # DRC-clean route.
    #
    # Measured here: placement PRESERVES power nets perfectly when it is given
    # them (2 in -> 2 out, VPWR/VGND intact through global+detailed placement).
    # So the tool was never the defect -- the defect is that NOTHING NOTICED.
    # This stage had no power-net inspection whatsoever, and neither do CTS or
    # metal-fill.
    #
    # Two DIFFERENT signals, deliberately not conflated:
    #
    #  * REGRESSION (fail-closed). The input carried power nets and the output
    #    has fewer -> THIS STAGE destroyed them. Provable without knowing
    #    anything about campaign intent, so it is a hard failure.
    #
    #  * ABSENCE (disclosed, never failed). The input carries no power nets at
    #    all. That is NOT necessarily wrong -- a legitimate flow may build the
    #    PDN after placement -- so failing here would break those flows. It is
    #    recorded, which is exactly what was missing: the loss point becomes
    #    identifiable at the stage where it happens instead of six stages later.
    #
    # Nets are classified by SIGNAL TYPE via getSigType, never by name: VPWR /
    # VDD / vccd1 differ per PDK, but POWER/GROUND is what OpenDB records.
    #
    # SIGTYPE ALONE IS NOT ENOUGH, and the first version of this check was
    # falsely reassuring because of it. Measured on the two real ODBs:
    #
    #   pdn.1     zero_ GROUND special=0 swires=0 iterms=31    <- TIE-OFF net
    #             VPWR  POWER  special=1 swires=1 iterms=705   <- real rail
    #             VGND  GROUND special=1 swires=1 iterms=705   <- real rail
    #   tapcell.1 zero_ GROUND special=0 swires=0 iterms=31    <- ONLY this
    #
    # `zero_` is a logical tie-low, not a supply. Counting by sigtype therefore
    # reported "1 power/ground net preserved" for the tapcell design -- which
    # has NO SPECIALNETS and no VPWR/VGND and cannot be powered at all. A
    # reassuring number about an unpowerable design is worse than no number.
    #
    # A real supply rail is SPECIAL and carries SWIRE geometry: that is what
    # physically distributes power. Both are counted, and the rail count is the
    # one the gate keys on.
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
    _pdn_before = _pdn_probe + "puts \"__PDN_IN__ pg=$_pg rail=$_rail unc=$_unc\"\n"
    _pdn_after = _pdn_probe + "puts \"__PDN_OUT__ pg=$_pg rail=$_rail unc=$_unc\"\n"
    script = f"""{loader}
{sdc_line}
{_rc_tcl}{_pdn_before}{_taps_tcl}{_cluster}global_placement -density {density}{_gp_opts}
detailed_placement{_dp_opts}
check_placement -verbose
{_pdn_after}report_design_area
report_design_area > {os.path.join(_OUTPUT_DIR, "place_area.rpt")}
write_def {out_def}
write_db {out_odb}
exit
"""
    proc, out, elapsed = _run_script(script, "place")
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective=f"placement of {top}", status="failed", pdk_binding=binding or "none",
                    error="OpenROAD placement failed; see place.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "place.log"})
    _pdn = _parse_pdn_continuity(out)
    _taps = None
    _tm = re.search(r"__TAPS__ before=(\d+) after=(\d+) pg_connected=(\d+)", out)
    if _insert_taps:
        if not _tm:
            return _cde(objective=f"placement of {top}", status="failed",
                        pdk_binding=binding or "none",
                        error="insert_tapcells was enabled but the __TAPS__ probe is "
                              "missing from place.log; tap insertion is NOT measured",
                        validation={"verdict": "fail"},
                        provenance={"openroad": "openroad", "log": "place.log"})
        _taps = {"enabled": True, "source": _taps_src,
                 "tapcell_master": _tap_master, "endcap_master": _endcap_master,
                 "tapcell_distance": _tap_dist,
                 "present_before": int(_tm.group(1)), "present_after": int(_tm.group(2)),
                 "inserted": int(_tm.group(2)) - int(_tm.group(1)),
                 "pg_pins_connected": int(_tm.group(3))}
        if _taps["present_before"]:
            _place_notes.append("input already carries %d tap/endcap instance(s); "
                                "tapcell NOT re-run" % _taps["present_before"])
        elif _taps["inserted"] <= 0:
            return _cde(objective=f"placement of {top}", status="failed",
                        pdk_binding=binding or "none",
                        error="tapcell ran but inserted 0 tap/endcap cells",
                        validation={"verdict": "fail"},
                        provenance={"openroad": "openroad", "log": "place.log"})
    else:
        _taps = {"enabled": False, "source": _taps_src}
    if _pdn and _pdn["destroyed"]:
        # The stage was handed power nets and gave back fewer. No campaign
        # knowledge is needed to call that a defect.
        return _cde(
            objective=f"placement of {top}", status="failed",
            pdk_binding=binding or "none",
            error=("PLACEMENT DESTROYED THE POWER GRID: %d supply rail(s) "
                   "entered this stage and only %d survived it. A rail is a "
                   "special power/ground net carrying real geometry, so the "
                   "design can no longer be power-connected -- and every "
                   "downstream stage would run and report success on it anyway."
                   % (_pdn["rails_in"], _pdn["rails_out"])),
            validation={"verdict": "fail"},
            qor={"power_rails_in": _pdn["rails_in"],
                 "power_rails_out": _pdn["rails_out"]},
            provenance={"openroad": "openroad", "log": "place.log"})
    if _pdn and _pdn["unpowered_created"]:
        # The grid is intact but this stage left new cells unattached to it.
        return _cde(
            objective=f"placement of {top}", status="failed",
            pdk_binding=binding or "none",
            error=("PLACEMENT LEFT CELLS UNPOWERED: unconnected supply pins "
                   "rose from %d to %d while the power grid itself stayed "
                   "intact. Cells sitting on the rails but not attached to "
                   "them are dead, and check_power_grid still passes because "
                   "it audits the grid, not each instance's attachment to it. "
                   "Re-run global_connect after inserting cells."
                   % (_pdn["unconnected_pg_pins_in"],
                      _pdn["unconnected_pg_pins_out"])),
            validation={"verdict": "fail"},
            qor={"unconnected_pg_pins_in": _pdn["unconnected_pg_pins_in"],
                 "unconnected_pg_pins_out": _pdn["unconnected_pg_pins_out"]},
            provenance={"openroad": "openroad", "log": "place.log"})
    # LEGALITY comes from `check_placement -verbose`, which is AUTHORITATIVE:
    # OpenROAD errors (DPL-0033 and friends) on an illegal placement, and that
    # non-zero return is caught by the fail-closed branch above. So reaching this
    # line means check_placement accepted the placement.
    #
    # The previous expression was FAIL-OPEN BY SHAPE:
    #     not re.search(r"Placement violations\s*:\s*[1-9]", out)
    # OpenROAD never prints "Placement violations : N" in this flow (verified on
    # a real run -- the log carries "Iteration | Violations | Cells | Sites" and
    # a DPL-1104 penalty line instead), so the pattern matched nothing and the
    # `not` made ABSENCE OF EVIDENCE read as legal. It happened to agree with the
    # engine here, but it would fabricate `legal: true` for any future path where
    # check_placement is skipped -- and one already exists (the taps stage
    # deliberately omits check_placement, because pre-placement cells are
    # legitimately unplaced).
    legal = True  # check_placement ran and did not error; see fail-closed above
    _dpl_violations = re.search(r"Placement violations\s*:\s*([0-9]+)", out)
    if _dpl_violations and int(_dpl_violations.group(1)) > 0:
        legal = False
    # OpenROAD prints "Design area 1747 um^2 52% utilization." -- the previous
    # pattern required `u^2` and therefore MATCHED NOTHING, so a good placement
    # reported utilization=None. Same copied defect as chip-floorplanning; units
    # are now matched tolerantly so a cosmetic upstream change cannot silently
    # re-open the hole.
    m = re.search(r"Design area\s+([0-9.]+)\s*u?m?\^?2\s+([0-9.]+)\s*%", out)
    util = float(m.group(2)) / 100.0 if m else None
    # Power-net continuity note. Disclosed, not gated: a flow that builds its
    # PDN after placement is legitimate, so an absent PDN must not fail here.
    # What it MUST do is say so, because on crc16_ccitt nothing did and six
    # further stages reported success on an unpowerable design.
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
            "power-connected. Placement does not create a PDN, so this is "
            "inherited: check that the stage feeding placement is the PDN "
            "stage and not a pre-PDN one." % _pdn["pg_nets_in"])
    else:
        _pdn_note = ("%d supply rail(s) preserved through placement"
                     % _pdn["rails_out"])
        if _pdn["unpowered_pre_existing"]:
            # Inherited, so not this stage's failure -- but silence here is how
            # 36 dead cells reached a routed design that passed check_power_grid.
            _pdn_note += ("; %d supply pin(s) arrived ALREADY unconnected to "
                          "the grid and are still unconnected -- those cells "
                          "are dead, and the stage that inserted them without "
                          "re-running global_connect is upstream of here"
                          % _pdn["unconnected_pg_pins_out"])
        elif _pdn["unconnected_measured"]:
            _pdn_note += (", %d unconnected supply pin(s)"
                          % _pdn["unconnected_pg_pins_out"])
    return _cde(
        objective=f"global + detailed placement of {top}",
        status="completed",
        pdk_binding=binding or "none",
        results={"legalized": {"value": bool(legal), "unit": "bool"},
                 "utilization": {"value": util, "unit": "fraction"}},
        qor={"target_density": density, "achieved_utilization": util,
             "legalized": bool(legal),
             # Measured, not assumed: what this stage was handed and what it
             # gave back. Rails are the meaningful count.
             "power_rails_in": (_pdn or {}).get("rails_in"),
             "power_rails_out": (_pdn or {}).get("rails_out"),
             "power_rails_preserved": (_pdn or {}).get("preserved"),
             # An intact grid does not mean every cell reaches it.
             "unconnected_pg_pins_in": (_pdn or {}).get("unconnected_pg_pins_in"),
             "unconnected_pg_pins_out": (_pdn or {}).get("unconnected_pg_pins_out"),
             "timing_driven_applied": _timing_driven,
             "tapcells_inserted": (_taps or {}).get("inserted", 0)},
        signoff={"placed_def": "placed.def", "placed_odb": "placed.odb",
             "legal": bool(legal), "report": "place.log",
                 "hierarchy_mode": hierarchy_mode,
                 "placement_options": _gp_opts.strip() or "default",
                 "timing_driven": _timing_driven,
                 "wire_rc_source": _rc_src.get("wire_rc"),
                 "tapcell_insertion": _taps,
                 "power_net_continuity": _pdn,
                 "power_net_continuity_note": _pdn_note,
                 "notes": _place_notes},
        inputs_ref=inputs,
        assumptions=["single-corner placement; timing-driven only if SDC, liberty and a wire-RC source are supplied"] + _caveats,
        validation={"verdict": ("pass_with_caveats" if _caveats else "pass") if legal else "fail",
                    "note": ("legal placement" + ("; " + "; ".join(_caveats) if _caveats else ""))
                            if legal else "placement violations present"},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "place.log", "setting_sources": dict(
                        {"density": density_src, "insert_tapcells": _taps_src}, **_rc_src)},
    )


_DEF_COMPONENT = re.compile(r"^\s*-\s+(?P<inst>\S+)\s+(?P<master>\S+)", re.M)
#: A flop master in any of the spellings this flow's libraries use (sky130
#: `sdfxtp_1`/`dfxtp_1`, generic `DFF_X1`, ...). Used only to report the flop
#: SUBSET of instance preservation; the full-instance census is the real check.
_DEF_FLOP_MASTER = re.compile(r"(^|__|_)s?df[a-z]*t?p?_?\d*$|dff", re.I)


def _def_section(text, name):
    """Body of a `<NAME> n ; ... END <NAME>` DEF section, or None if absent."""
    match = re.search(r"^%s\s+\d+\s*;\s*$(.*?)^END %s\s*$" % (name, name),
                      text, re.M | re.S)
    return match.group(1) if match else None


def _def_census(def_path):
    """Instance, row and PG-connectivity census of a DEF, or None if unreadable.

    Everything the tap/endcap and decap-fill gates assert about a DEF is derived
    here, from the file, rather than asserted by the caller afterwards. Returns
    None only when the file cannot be read -- an empty section is a real answer
    and is reported as such, never as absent.
    """
    try:
        with open(def_path, "r", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    components = {}
    body = _def_section(text, "COMPONENTS")
    for record in (body or "").split(";"):
        match = _DEF_COMPONENT.search(record)
        if match:
            components[match.group("inst")] = {
                "master": match.group("master"),
                "fixed": "+ FIXED" in record,
            }
    pg_nets = {}
    special = _def_section(text, "SPECIALNETS")
    if special is not None:
        for record in re.split(r"^\s*-\s+", special, flags=re.M):
            record = record.strip()
            if not record:
                continue
            head = record.split("+", 1)[0]
            pairs = re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", head)
            pg_nets[record.split()[0]] = {
                "iterms": len(pairs),
                "wildcards": sum(1 for inst, _ in pairs if inst == "*"),
                "instances": sorted({inst for inst, _ in pairs
                                     if inst not in ("*", "PIN")}),
            }
    return {
        "components": components,
        "rows": len(re.findall(r"^ROW\s+", text, re.M)),
        "pg_nets": pg_nets,
        "special_via_placements": len(re.findall(r"\bNEW\b|\+\s*VIA\b", special or "")),
    }


def _pg_enumeration_gap(census):
    """How many placed instances are NOT enumerated on every PG special net.

    WHY THIS IS MEASURED AT INSERTION TIME. A DEF's `( * VPWR )` wildcard is NOT
    preserved through an OpenROAD read/write round-trip: it is resolved against
    the instance set present AT READ TIME and serialized as an explicit iterm
    list. So when PDN runs BEFORE tap/endcap insertion -- the reverse of the ORFS
    reference order -- the physical-only cells inserted here are FIXED correctly
    on the rails and are geometrically perfect, yet they never appear in the
    SPECIALNETS connection list, and nothing downstream says so. Measured on this
    campaign: a tapped DEF with 367 components enumerated only 241 instances on
    each PG net, and the 126 inserted cells were missing from both.

    Reporting only "SPECIALNETS geometry preserved" hides that entirely, which is
    why the gap is counted here and named separately. Closing it is a
    `global_connect` / PDN-refresh obligation, not a tap/endcap one, so this is
    DISCLOSED rather than failed -- but it is never silently clean.
    """
    if not census or not census.get("pg_nets"):
        return None
    placed = set(census["components"])
    if not placed:
        return None
    worst = None
    for name, net in sorted(census["pg_nets"].items()):
        if net["wildcards"]:
            # A live wildcard covers every instance by definition.
            missing = 0
        else:
            missing = len(placed - set(net["instances"]))
        record = {"net": name, "enumerated_instances": len(net["instances"]),
                  "expected_instances": len(placed),
                  "unenumerated_instances": missing,
                  "wildcard": bool(net["wildcards"])}
        if worst is None or missing > worst["unenumerated_instances"]:
            worst = record
    return worst


def _insert_tap_endcap_decap(params):
    """Insert well-tap / endcap / decap-fill physical cells.

    CORRECT EDA ORDERING (why this is stage-parameterized): well-tap and endcap
    cells must be FIXED OBSTACLES BEFORE placement -- they are inserted on the
    floorplan DEF (empty rows) so the placer legalizes logic AROUND them; running
    `tapcell` on an already-placed DEF drops taps into occupied rows and creates
    overlaps. Decap/fill is the opposite: `filler_placement` fills the LEFTOVER
    gaps around real logic, and it must run AFTER ROUTING -- it is the LAST
    placement-row step, not merely a post-placement one. Anything that still
    needs row space afterwards either destroys the fill or is blocked by it:
    CTS re-legalizes with `remove_fillers` + `detailed_placement` (and
    `remove_fillers` has no class filter, so on sky130_fd_sc_hd it deletes
    `__decap_*`, endcap decap_3 included, as readily as `__fill_*` -- all are LEF
    CLASS CORE SPACER), and routing runs `repair_antennas` + another
    `detailed_placement`, where diode insertion needs free rows. Deleting a
    placed cell un-merges the abutted n-well/implant on either side of the hole,
    a real FEOL error (nwell.2a = "min nwell spacing (merged if less)").
    Incident 2026-08-31: filling before CTS lost all 318 filler/decap instances
    and produced 151 un-waived KLayout FEOL nwell/hvtp violations. ORFS agrees --
    `5_3_fillcell` consumes `5_2_route.odb`. Because these
    two steps belong at different points in the flow, `stage` selects which runs:

      * stage='taps' -> tapcell + endcap only, on the FLOORPLAN/PDN DEF, BEFORE
        placement (writes tapped_floorplan.def). This is the DRC-correctness step
        for sky130 nwell ties.
      * stage='fill' -> filler_placement (decap/fill) only, on the ROUTED DEF,
        AFTER routing (writes filled.def).
      * stage='all' (default, back-compat) -> both in one pass. Suboptimal: it
        does NOT re-legalize, AND it forces fill to happen at tap time, which is
        far too early -- CTS will delete it. Only use it on a design where taps
        were already accounted for and fill is re-run later. Prefer taps+fill.
    """
    if not shutil.which("openroad"):
        return _cde(objective="physical-cell insertion", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    stage = str(params.get("stage", "all")).lower()
    if stage not in ("taps", "fill", "all"):
        return _cde(objective="physical-cell insertion", status="failed",
                    error="stage must be 'taps' (pre-placement), 'fill' (post-routing), or 'all'",
                    validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    loader, inputs, _, failure = _load_design(params, binding, "physical-cell insertion")
    if failure:
        return failure
    policy = _stage_policy(params, binding)
    resolved, sources = _resolve_physical_cells(params, policy, binding)
    cmds, _cmd_err = _physical_cell_cmds(resolved, stage)
    if _cmd_err:
        return _cde(objective="physical-cell insertion", status="failed",
                    pdk_binding=binding or "none", error=_cmd_err,
                    validation={"verdict": "fail"})
    # `check_placement -verbose` errors on ANY unplaced/unaligned instance. That is
    # the right gate AFTER placement (fill/all), but WRONG for the pre-placement
    # taps stage: taps/endcaps run on the floorplan/PDN DEF whose LOGIC cells are
    # intentionally still unplaced (placement legalizes them next), so a full-design
    # legality check always fails there. For the taps stage the gate is simply that
    # tapcell succeeds and the tapped DEF writes; the placer checks legality later.
    if stage in ("fill", "all"):
        cmds.append("check_placement -verbose")
    _def_stem = {"taps": "tapped_floorplan", "fill": "filled", "all": "physical_cells"}[stage]
    out_def = os.path.join(_OUTPUT_DIR, f"{_def_stem}.def")
    out_odb = os.path.join(_OUTPUT_DIR, f"{_def_stem}.odb")
    script = f"""{loader}
{chr(10).join(cmds)}
write_def {{{out_def}}}
write_db {{{out_odb}}}
exit
"""
    proc, out, elapsed = _run_script(script, "insert_tap_endcap_decap")
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective="physical-cell insertion", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="OpenROAD physical-cell insertion failed; see insert_tap_endcap_decap.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "insert_tap_endcap_decap.log",
                                "setting_sources": sources})
    _obj = {"taps": "insert well-tap and endcap cells (pre-placement)",
            "fill": "insert decap and fill cells (post-routing)",
            "all": "insert tap, endcap, and decap cells"}[stage]
    _sign = {"stage": stage, "placed_def": f"{_def_stem}.def", "placed_odb": f"{_def_stem}.odb"}
    if stage in ("taps", "all"):
        _sign["tapcell_master"] = resolved["tapcell_master"]
        _sign["endcap_master"] = resolved["endcap_master"]
    if stage in ("fill", "all"):
        _sign["decap_cells"] = _as_list(resolved["decap_cells"])
        _sign["filler_cells"] = _as_list(resolved["filler_cells"])

    # MEASURE THE GATE, DO NOT LEAVE IT TO THE CALLER. Every obligation this
    # stage is judged on (instances preserved, inserted cells FIXED, PDN
    # preserved, dependency order) is a property of the DEF before and after
    # insertion, so it is derived here. Previously the tool emitted only
    # `physical_cells_inserted: true` and the agent hand-authored the rest after
    # the fact, which is how a stale key name and an unmeasured PG gap both
    # survived review.
    before = _def_census(inputs.get("def_file") or params.get("def_file") or "")
    after = _def_census(out_def)
    _checks, _results = {}, {
        "physical_cells_inserted": {"value": True, "unit": "bool"},
        "insertion_stage": {"value": stage, "unit": "enum"},
    }
    if after:
        # PG enumeration and row structure are properties of the OUTPUT alone, so
        # they stay measurable even when the run was ODB-driven and no "before"
        # census exists.
        gap = _pg_enumeration_gap(after)
        _sign["rows_after"] = after["rows"]
        if gap is not None:
            _sign["pg_iterm_enumeration"] = dict(gap, note=(
                "Instances enumerated on the PG special net vs instances placed. "
                "A DEF wildcard `( * VPWR )` is resolved at READ time, so cells "
                "inserted after PDN ran are FIXED on the rails but absent from "
                "the connection list. Closing this is a global_connect / "
                "PDN-refresh obligation, NOT a tap/endcap one -- it is disclosed "
                "here, never silently reported as connected."))
            _results["pg_unenumerated_instances"] = {
                "value": gap["unenumerated_instances"], "unit": "count"}
            _checks["all_instances_pg_enumerated"] = (
                gap["unenumerated_instances"] == 0)
    if before and after:
        kept = set(before["components"]) & set(after["components"])
        lost = sorted(set(before["components"]) - set(after["components"]))
        inserted = sorted(set(after["components"]) - set(before["components"]))
        flops_before = {n for n, c in before["components"].items()
                        if _DEF_FLOP_MASTER.search(c["master"])}
        flops_after = {n for n, c in after["components"].items()
                       if _DEF_FLOP_MASTER.search(c["master"])}
        not_fixed = [n for n in inserted if not after["components"][n]["fixed"]]
        _checks.update({
            "all_flops_preserved": not (flops_before - flops_after),
            "original_instances_preserved": not lost,
            "all_inserted_fixed": not not_fixed,
            # Geometry only -- see `_pg_enumeration_gap` for the connection list.
            "pdn_specialnets_preserved": (
                sorted(before["pg_nets"]) == sorted(after["pg_nets"])
                and after["special_via_placements"]
                >= before["special_via_placements"]),
            "correct_dependency_order_floorplan_then_pdn_then_tapcell": bool(
                before["rows"] and before["pg_nets"]),
        })
        _sign.update({
            "instance_count_before": len(before["components"]),
            "instance_count_after": len(after["components"]),
            "flop_count_before": len(flops_before),
            "flop_count_after": len(flops_after),
            "all_flops_preserved": _checks["all_flops_preserved"],
            "all_original_instances_preserved":
                _checks["original_instances_preserved"],
            "dropped_instances": lost[:64],
            "non_fixed_instances": len(not_fixed),
            "pdn_specialnets_preserved": _checks["pdn_specialnets_preserved"],
            "rows_before": before["rows"],
            "census_basis": "def_components_and_specialnets_before_vs_after",
        })
        _results.update({
            "inserted_total": {"value": len(inserted), "unit": "count"},
            "instances_preserved": {"value": len(kept), "unit": "count"},
            "instances_dropped": {"value": len(lost), "unit": "count"},
            "non_fixed_inserted": {"value": len(not_fixed), "unit": "count"},
        })
        if stage in ("fill", "all"):
            _fm = set(_fill_masters(resolved))
            _fill_new = sum(1 for n in inserted if after["components"][n]["master"] in _fm)
            _fill_total = sum(1 for c in after["components"].values() if c["master"] in _fm)
            _results["filler_cells_inserted"] = {"value": _fill_new, "unit": "count"}
            _results["filler_cells_total"] = {"value": _fill_total, "unit": "count"}
            _sign["filler_cells_inserted"] = _fill_new
            _sign["filler_cells_total"] = _fill_total
            # Measured: a routed DEF with 0 FILLCELL_* -> 285 KLayout WELL.4
            # violations. A fill stage that leaves the design with no filler is
            # not done, whatever OpenROAD's exit code says.
            _checks["filler_cells_present"] = _fill_total > 0
    else:
        _sign["census_basis"] = (
            "PARTIAL: the input DEF could not be read (an ODB-driven run, or an "
            "unreadable path), so instance-preservation and inserted-FIXED facts "
            "were NOT derived. Absent is NOT clean -- bind those obligations from "
            "a readable DEF before closing this gate.")

    _gap_count = (_sign.get("pg_iterm_enumeration") or {}).get(
        "unenumerated_instances") or 0
    _failed = sorted(k for k, v in _checks.items()
                     if v is False and k != "all_instances_pg_enumerated")
    if _failed:
        _verdict = "fail"
        _note = ("physical cells inserted (stage=%s) but %s did not hold"
                 % (stage, ", ".join(_failed)))
    elif not _checks:
        _verdict = "not_assessable"
        _note = ("cells inserted (stage=%s) but no DEF census could be derived, "
                 "so none of this stage's obligations were measured" % stage)
    elif _gap_count:
        _verdict = "pass_with_caveats"
        _note = ("physical cells inserted (stage=%s); %d placed instance(s) are "
                 "NOT enumerated on PG net '%s'. Run global_connect (or refresh "
                 "the PDN) against this DEF before PG signoff -- the cells are "
                 "FIXED on the rails but absent from the connection list"
                 % (stage, _gap_count,
                    _sign["pg_iterm_enumeration"]["net"]))
    else:
        _verdict = "pass"
        _note = f"physical cells inserted (stage={stage})"

    return _cde(objective=_obj, status="completed",
                pdk_binding=binding or "none", inputs_ref=inputs,
                results=_results,
                signoff=_sign,
                assumptions=[
                    "every preservation/FIXED/PG fact below is DERIVED from the "
                    "input and output DEF in this run, not asserted by the caller",
                    "PG-pin connection lists are owned by global_connect/PDN, not "
                    "by tap/endcap insertion; a non-zero pg_unenumerated_instances "
                    "is disclosed here and closed by a PDN refresh"],
                validation={"verdict": _verdict, "note": _note,
                            "checks": _checks},
                provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                            "log": "insert_tap_endcap_decap.log", "setting_sources": sources})


#: Row-FILLER cell masters (`sky130_fd_sc_hd__fill_1`, `FILLCELL_X1`, ...). Matching
#: `decap` here would be WRONG: measured on a correct pre-fill `routed.def`, 52
#: `sky130_fd_sc_hd__decap_3` instances are present as `PHY_EDGE_ROW_*` ENDCAPS from
#: the tapcell stage -- part of the floorplan, not fill, and they saturate nothing.
_FILLER_MASTER = re.compile(r"^\s*-\s+\S+\s+(\S*fill(?:cell)?_?\d*)\s", re.I | re.M)


def _fill_saturation(def_path):
    """Describe fill saturation in an input DEF, or None if unreadable.

    Returns {"fill_shapes": int, "filler_instances": int, "saturated": bool}.
    `FILLS <n> ;` is metal-fill's own authoritative section header; row-filler cell
    masters are the decap/row-fill stage's site-consuming instances.
    """
    try:
        with open(str(def_path), encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return None
    header = re.search(r"^\s*FILLS\s+(\d+)\s*;", text, re.M)
    fills = int(header.group(1)) if header else 0
    components = text.split("COMPONENTS", 1)[-1].split("END COMPONENTS", 1)[0]
    fillers = len(_FILLER_MASTER.findall(components))
    return {"fill_shapes": fills, "filler_instances": fillers,
            "saturated": bool(fills or fillers)}


def _reject_fill_saturated_input(params, scenario, objective, binding, inputs=None):
    """Fail closed when a legalizing repair scenario is pointed at a POST-FILL DEF.

    WHY THIS IS A PREFLIGHT AND NOT A LESSON IN A TICKET.
    `repair_design` inserts buffers and `detailed_placement` must then legalize them,
    which needs FREE SITES. Metal-fill/decap-fill exist to consume every remaining
    site to meet CMP density windows, so the two are mutually exclusive by
    construction. Measured: a repair pointed at `filled.def` reported
    `[INFO DPL-0009] Utilization: 102.7%` then `[ERROR DPL-0038] Utilization greater
    than 100%, impossible to legalize` -- after running the full repair, i.e. a whole
    wasted container run per attempt. The identical repair against the pre-fill
    `routed.def` legalized at 48.2% and closed the residual (87 -> 0 DRV violators).

    The trap is that the post-fill DEF is the NATURAL thing to reach for: it is the
    latest blessed physical artifact, and it is what extraction and the STA attempt
    that reported the DRV residual actually consumed. So the guard names the correct
    input instead of merely refusing.
    """
    def_file = params.get("def_file")
    if not def_file or not os.path.exists(str(def_file)):
        return None
    sat = _fill_saturation(def_file)
    if not sat or not sat["saturated"]:
        return None
    if str(params.get("allow_fill_saturated_def", "")).lower() in ("1", "true", "yes"):
        return None
    return _cde(
        objective=objective, status="failed", pdk_binding=binding or "none",
        inputs_ref=inputs or {"def_file": def_file},
        error=(
            "`def_file` is a POST-FILL DEF (%d FILLS shape(s), %d filler/decap "
            "instance(s)) and `%s` must legalize the buffers it inserts. Fill exists "
            "to consume every free site for CMP density, so `detailed_placement` "
            "cannot converge -- this fails as DPL-0038 'Utilization greater than "
            "100%%, impossible to legalize' only AFTER the full repair has run, "
            "wasting the container run. Point `def_file` at the last PRE-FILL DEF in "
            "the chain (`routing.N/results/routed.def` for post_route_repair; the "
            "cts/placement output for post_placement_repair) and re-run metal-fill "
            "AFTER this ECO, which this scenario's own `requires_reroute: true` "
            "contract already requires. Set `allow_fill_saturated_def` only if the "
            "repair genuinely inserts nothing."
            % (sat["fill_shapes"], sat["filler_instances"], scenario)),
        validation={"verdict": "fail"},
        provenance={"preflight": "fill_saturation"})


def _post_placement_repair(params):
    if not shutil.which("openroad"):
        return _cde(objective="post-placement repair", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    saturated = _reject_fill_saturated_input(
        params, "post_placement_repair", "post-placement repair", binding)
    if saturated:
        return saturated
    loader, inputs, _, failure = _load_design(
        params, binding, "post-placement repair", require_liberty=True)
    if failure:
        return failure
    sdc = params.get("sdc")
    if not sdc or not os.path.exists(str(sdc)):
        return _cde(objective="post-placement repair", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="missing or unreadable required field 'sdc'",
                    validation={"verdict": "fail"})
    policy = _stage_policy(params, binding)
    max_wire, max_wire_src = _resolve(params, policy, "max_wire_length", None)
    repair_args = f" -max_wire_length {max_wire}" if max_wire is not None else ""
    timing = str(params.get("repair_timing", policy.get("repair_timing", "both"))).lower()
    if timing not in ("none", "setup", "hold", "both"):
        return _cde(objective="post-placement repair", status="failed",
                    pdk_binding=binding or "none", error="repair_timing must be none, setup, hold, or both",
                    validation={"verdict": "fail"})
    setup_opts, setup_applied, tf_sources = _repair_timing_opts(params, policy, "setup")
    hold_opts, hold_applied, _th = _repair_timing_opts(params, policy, "hold")
    tf_sources.update(_th)
    repair_transforms = {}
    timing_cmds = []
    if timing in ("setup", "both"):
        timing_cmds.append("repair_timing -setup" + setup_opts)
        repair_transforms["setup"] = setup_applied
    if timing in ("hold", "both"):
        timing_cmds.append("repair_timing -hold" + hold_opts)
        repair_transforms["hold"] = hold_applied
    wire_rc, wsrc, rc_err = _wire_rc_setup(params, policy, binding)
    if rc_err:
        return _cde(objective="post-placement repair", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error=rc_err, validation={"verdict": "fail"})
    if not wire_rc:
        return _cde(objective="post-placement repair", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="missing wire-RC layer for set_wire_rc: repair_design/repair_timing "
                          "need a wire-RC model or they no-op (OpenROAD RSZ-0089, 0 buffers/0 resizes). "
                          "Provide setrc_tcl, or wire_rc_signal_layer/wire_rc_clock_layer (caller), or "
                          "tool_policy.placement.wire_rc_signal_layer/_clock_layer, or "
                          "pdk_binding.routing_layers.wire_rc_signal_layer/_clock_layer.",
                    validation={"verdict": "fail"})
    out_def = os.path.join(_OUTPUT_DIR, "placement_repaired.def")
    out_odb = os.path.join(_OUTPUT_DIR, "placement_repaired.odb")
    script = f"""{loader}
read_sdc {{{sdc}}}
{wire_rc}estimate_parasitics -placement
repair_design{repair_args}
{chr(10).join(timing_cmds)}
detailed_placement
check_placement -verbose
report_checks -path_delay min_max -fields {{slew cap input_pin}} > {os.path.join(_OUTPUT_DIR, 'post_placement_timing.rpt')}
write_def {{{out_def}}}
write_db {{{out_odb}}}
exit
"""
    proc, out, elapsed = _run_script(script, "post_placement_repair")
    inputs["sdc"] = sdc
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective="post-placement repair", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="OpenROAD post-placement repair failed; see post_placement_repair.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "post_placement_repair.log"})
    return _cde(objective="post-placement design and timing repair", status="completed",
                pdk_binding=binding or "none", inputs_ref=inputs,
                results={"repair_completed": {"value": True, "unit": "bool"}},
                signoff={"placed_def": "placement_repaired.def",
                         "placed_odb": "placement_repaired.odb",
                         "timing_report": "post_placement_timing.rpt",
                         "repair_timing": timing,
                         "repair_transforms": repair_transforms or None},
                validation={"verdict": "pass", "note": "repair completed and placement legalized"},
                provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                            "log": "post_placement_repair.log",
                            "repair_transforms": repair_transforms or None,
                            "setting_sources": dict({"max_wire_length": max_wire_src,
                                                "wire_rc": wsrc.get("wire_rc"),
                                                "wire_rc_signal_layer": wsrc.get("wire_rc_signal_layer"),
                                                "wire_rc_clock_layer": wsrc.get("wire_rc_clock_layer"),
                                                "repair_timing": "caller" if "repair_timing" in params else ("pdk_binding.tool_policy" if "repair_timing" in policy else "tool_default")},
                                                **tf_sources)})


def _post_route_repair(params):
    """ECO repair against REAL extracted parasitics (post-route).

    WHY THIS EXISTS, SEPARATE FROM `post_placement_repair`.
    `repair_design` at placement time optimizes against ESTIMATED RC
    (`estimate_parasitics -placement` + `set_wire_rc`). The signoff DRV gate is
    measured on EXTRACTED post-route SPEF. Real routed RC is worse than the
    placement estimate, so a design that repair_design declares clean pre-route can
    still violate max_transition/max_capacitance after routing -- the residual is
    not a tool failure, it is the estimate/reality gap.

    Observed on myTop2_Hier: post-placement repair took post-route DRVs 261 -> 102
    (worst slew slack -14.83 ns -> -1.89 ns) and then plateaued, because every
    further placement-time repair was still optimizing the wrong RC model. Closing
    that last residual REQUIRES repairing with the extracted SPEF back-annotated.

    Contract, and why each part is load-bearing:
      * `spef` is MANDATORY. Without it this is just post-placement repair under a
        more reassuring name, and it would silently reproduce the same gap. Fails
        closed rather than falling back to estimates.
      * `set_propagated_clock` is applied because the clock tree EXISTS at this
        point. Repairing a post-CTS netlist on an ideal clock mis-models clock-path
        delay (the same rule the flow instructions state for post-CTS timing work).
      * The written DEF is an ECO that is NOT yet routed: repair inserts buffers,
        which are unplaced, and their nets have no routing. The caller MUST re-run
        routing -> metal fill -> extraction -> STA. The CDE says so explicitly and
        marks `requires_reroute: true`, so a consumer cannot mistake this for a
        signoff-ready layout.
    """
    if not shutil.which("openroad"):
        return _cde(objective="post-route repair", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    saturated = _reject_fill_saturated_input(
        params, "post_route_repair", "post-route repair", binding)
    if saturated:
        return saturated
    loader, inputs, _, failure = _load_design(
        params, binding, "post-route repair", require_liberty=True)
    if failure:
        return failure

    sdc = params.get("sdc")
    if not sdc or not os.path.exists(str(sdc)):
        return _cde(objective="post-route repair", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="missing or unreadable required field 'sdc'",
                    validation={"verdict": "fail"})

    # SPEF is what makes this scenario different from post_placement_repair.
    spef = params.get("spef")
    if not spef or not os.path.exists(str(spef)):
        return _cde(
            objective="post-route repair", status="failed",
            pdk_binding=binding or "none", inputs_ref=inputs,
            error=("missing or unreadable required field 'spef'. post_route_repair "
                   "exists specifically to repair against EXTRACTED parasitics; "
                   "without SPEF it would silently degrade into an estimated-RC "
                   "repair (use scenario 'post_placement_repair' for that)."),
            validation={"verdict": "fail"})

    policy = _stage_policy(params, binding)
    post_rc_tcl, post_rc_src, post_rc_err = _wire_rc_setup(params, policy, binding)
    if post_rc_err:
        return _cde(objective="post-route repair", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error=post_rc_err, validation={"verdict": "fail"})
    max_wire, max_wire_src = _resolve(params, policy, "max_wire_length", None)
    repair_args = f" -max_wire_length {max_wire}" if max_wire is not None else ""
    timing = str(params.get("repair_timing", policy.get("repair_timing", "none"))).lower()
    if timing not in ("none", "setup", "hold", "both"):
        return _cde(objective="post-route repair", status="failed",
                    pdk_binding=binding or "none",
                    error="repair_timing must be none, setup, hold, or both",
                    validation={"verdict": "fail"})
    timing_cmds = []
    post_setup_opts, post_setup_applied, post_tf_src = _repair_timing_opts(
        params, policy, "setup")
    post_hold_opts, post_hold_applied, _pth = _repair_timing_opts(params, policy, "hold")
    post_tf_src.update(_pth)
    post_transforms = {}
    if timing in ("setup", "both"):
        timing_cmds.append("repair_timing -setup" + post_setup_opts)
        post_transforms["setup"] = post_setup_applied
    if timing in ("hold", "both"):
        timing_cmds.append("repair_timing -hold" + post_hold_opts)
        post_transforms["hold"] = post_hold_applied

    out_def = os.path.join(_OUTPUT_DIR, "route_repaired.def")
    out_odb = os.path.join(_OUTPUT_DIR, "route_repaired.odb")
    drv_before = os.path.join(_OUTPUT_DIR, "drv_before.rpt")
    drv_after = os.path.join(_OUTPUT_DIR, "drv_after.rpt")

    # Report DRV on the SAME extracted basis before and after, so the CDE carries
    # measured evidence that the repair moved the real metric -- not a claim.
    script = f"""{loader}
read_sdc {{{sdc}}}
read_spef {{{spef}}}
{post_rc_tcl}set_propagated_clock [all_clocks]
puts "__DRV_BEFORE__"
report_check_types -max_slew -max_capacitance -max_fanout -violators > {drv_before}
report_check_types -max_slew -max_capacitance -max_fanout -violators
repair_design{repair_args}
{chr(10).join(timing_cmds)}
detailed_placement
check_placement -verbose
puts "__DRV_AFTER__"
report_check_types -max_slew -max_capacitance -max_fanout -violators > {drv_after}
report_check_types -max_slew -max_capacitance -max_fanout -violators
report_checks -path_delay min_max -fields {{slew cap input_pin}} > {os.path.join(_OUTPUT_DIR, 'post_route_timing.rpt')}
write_def {{{out_def}}}
write_db {{{out_odb}}}
exit
"""
    proc, out, elapsed = _run_script(script, "post_route_repair")
    inputs["sdc"] = sdc
    inputs["spef"] = spef
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective="post-route repair", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="OpenROAD post-route repair failed; see post_route_repair.log:\n"
                          + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "post_route_repair.log"})

    def _violator_count(path):
        try:
            with open(path, "r", errors="replace") as fh:
                return sum(1 for ln in fh if "(VIOLATED)" in ln)
        except OSError:
            return None

    before_n = _violator_count(drv_before)
    after_n = _violator_count(drv_after)
    m = re.search(r"Inserted\s+(\d+)\s+buffers", out)
    buffers = int(m.group(1)) if m else 0
    m2 = re.search(r"Inserted\s+\d+\s+buffers in\s+(\d+)\s+nets", out)
    nets = int(m2.group(1)) if m2 else None
    resized = None
    m3 = re.search(r"Resized\s+(\d+)\s+instance", out)
    if m3:
        resized = int(m3.group(1))

    improved = (before_n is not None and after_n is not None and after_n < before_n)
    return _cde(
        objective="post-route ECO repair against extracted parasitics",
        status="completed", pdk_binding=binding or "none", inputs_ref=inputs,
        results={"repair_completed": {"value": True, "unit": "bool"},
                 "requires_reroute": {"value": True, "unit": "bool"}},
        qor={"drv_violators_before": before_n, "drv_violators_after": after_n,
             "buffers_inserted": buffers, "nets_repaired": nets,
             "instances_resized": resized},
        signoff={"routed_repaired_def": "route_repaired.def",
                 "routed_repaired_odb": "route_repaired.odb",
                 "drv_before_report": "drv_before.rpt",
                 "drv_after_report": "drv_after.rpt",
                 "timing_report": "post_route_timing.rpt",
                 "parasitics_basis": "extracted SPEF (post-route)",
                 "repair_timing": timing,
                 "repair_transforms": post_transforms or None,
                 "requires_reroute": True},
        assumptions=[
            "DRV counts are measured on the EXTRACTED SPEF basis, before and after "
            "the repair, in the same OpenROAD session -- they are measurements, "
            "not estimates.",
            "set_propagated_clock is applied: the clock tree exists post-CTS, so "
            "repairing on an ideal clock would mis-model clock-path delay.",
            "The emitted DEF is an ECO and is NOT routed: inserted buffers have no "
            "routing. Routing -> metal fill -> extraction -> STA MUST be re-run "
            "before any signoff claim.",
            "after-count is the residual on the PRE-ECO routing; the post-reroute "
            "number is only established by re-running extraction + STA.",
        ],
        validation={
            "verdict": "pass" if improved or before_n == 0 else "pass_with_caveats",
            "note": ("repaired on extracted SPEF: %s -> %s DRV violators, %d buffer(s) "
                     "inserted%s. THIS IS AN ECO -- re-run routing, metal fill, "
                     "extraction and STA; the design is NOT signoff-ready as written."
                     % (before_n, after_n, buffers,
                        "" if improved or before_n == 0
                        else " (no measured reduction on this basis)")),
        },
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "post_route_repair.log",
                    "setting_sources": {"max_wire_length": max_wire_src,
                                        "repair_timing": ("caller" if "repair_timing" in params
                                                          else "tool_default")}})



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
    global _ACTIVE_STAGE_TOKEN
    _ACTIVE_STAGE_TOKEN = _stage_token(params)
    s = params.get("scenario")
    if s == "place":
        return _place(params)
    if s == "insert_tap_endcap_decap":
        return _insert_tap_endcap_decap(params)
    if s in ("insert_taps", "insert_tap_endcap"):
        # Pre-placement well-tap + endcap insertion on the floorplan/PDN DEF.
        return _insert_tap_endcap_decap({**params, "stage": "taps"})
    if s in ("insert_fill", "insert_decap_fill"):
        # Post-routing decap/fill insertion on the routed DEF.
        return _insert_tap_endcap_decap({**params, "stage": "fill"})
    if s == "post_placement_repair":
        return _post_placement_repair(params)
    if s in ("post_route_repair", "eco_repair"):
        return _post_route_repair(params)
    return _cde(objective="placement", status="failed",
                error=(f"unknown scenario '{s}'; supported: place, insert_taps, insert_fill, "
                       "insert_tap_endcap_decap, post_placement_repair, post_route_repair"),
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
