#!/usr/bin/env python3
"""eco_utils.py -- one ECO wave per invocation for the chip-eco tool.

The signoff ECO stage is a *targeted* repair tier that sits between signoff STA
rung-1 and a rung-2 reopen. It exists because a focused fix is often cheaper and
less destructive than re-running implementation -- but only when the violations
are CLUSTERED and the miss is SMALL. Deciding that is judgement; this module
supplies the measurements the judgement needs and executes the wave the agent
chooses.

WHY ONE WAVE PER INVOCATION
---------------------------
"A large number of fixes at once causes chaos" is the governing constraint of
ECO work. So a wave is the unit of execution AND the unit of audit: each
invocation checkpoints, applies ONE bounded batch, re-times, and then either
commits or rolls back. The reasoning agent chooses the next wave's scope from
the previous wave's measured response. A loop that ran entirely inside the
container would hide exactly the decision that needs a human-legible record.

ROLLBACK IS THE SAFETY MECHANISM
--------------------------------
A wave that regresses is reverted, not carried forward. That is not politeness:
it makes the convergence trace MONOTONE by construction, which is what makes
"plateau" a trustworthy signal. If regressions were allowed into the trace,
a plateau would be indistinguishable from an oscillation, and the rung-2
escalation decision would be reading noise.

Concretely, a rejected wave (a) points ``eco_def`` at a copy of the pre-wave
DEF and (b) renames its own mutated DEF/netlist/SPEF with a ``.rejected``
suffix so no downstream glob can pick them up. Artifacts are wave-indexed
(``eco_wave_3.def``) so consecutive waves cannot overwrite each other's
evidence.

The verdict covers setup, hold, DRV, routing DRC and power-grid connectivity.
Judging on timing alone would commit a wave that closed setup while creating
max-cap violations or route shorts. A class whose report is missing is recorded
as ``unavailable``, never as clean.

ENCAPSULATED SUB-FLOW
---------------------
Each wave runs the whole incremental chain in-container so the blast radius
stays inside the stage:

    std-cell fill removal -> repair -> std-cell fill insertion
      -> incremental global route (+ PDN via repair + grid re-verify)
      -> parasitic re-extraction -> STA refresh -> judge

"Incremental" is precise about which router it describes: GLOBAL routing is
bracketed with ``-start_incremental``/``-end_incremental`` so only the nets the
repair modified are re-routed, but OpenROAD's ``detailed_route`` has NO
incremental mode, so every wave performs a full detailed route. Wave runtime is
dominated by that, not by the repair.

Metal fill is deliberately NOT in this loop -- it is removed once at ECO entry
and re-inserted once by the downstream post-ECO metal-fill stage. Re-filling per
wave costs runtime and buys nothing, because fill barely moves timing.

PARASITICS
----------
``estimate_parasitics -placement`` OVERWRITES the parasitics of every net, and
the OpenROAD manual is explicit that placement-based parasitics cannot predict
routed ones. On a post-route design that already carries signoff SPEF, issuing
it would discard the real extraction and make the wave's entire verdict an
optimistic estimate. So the SPEF is read and nothing is estimated; after the
repair the design is RE-EXTRACTED and re-read, so the verdict is measured
against post-ECO parasitics rather than the now-stale pre-ECO SPEF.

WHAT THIS STAGE CANNOT DO
-------------------------
OpenROAD has a repair engine for setup, hold and the DRV trio (max slew / max
capacitance / max fanout), plus antenna after global route. It has NO repair
command for minimum pulse width, minimum period, or crosstalk noise. Those
classes are DETECT-ONLY here and are reported with
``measurement: "unavailable"`` so that "no engine exists" can never be recorded
as "checked and clean".
"""
import json
import os
import re
import shutil
import subprocess
import time

import path_cluster

TOOL = "eco"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"

# Transform families ordered by how much collateral they disturb. Sizing and
# buffering leave the logic structure alone; cloning, pin swapping and buffer
# removal RESTRUCTURE it and can perturb paths that were previously clean.
# Early waves should stay conservative until the design's response is known.
AGGRESSION_LEVELS = {
    "conservative": [
        "-skip_gate_cloning", "-skip_pin_swap", "-skip_buffer_removal",
        "-skip_size_down", "-skip_last_gasp",
    ],
    "moderate": ["-skip_gate_cloning", "-skip_buffer_removal"],
    "aggressive": [],
}

# Fallback ONLY. The authority is `pdk_binding.capabilities.vt_swap`; this tuple
# exists so a binding predating the capability block still gets the right answer
# on sky130. See _is_single_vt().
_SINGLE_VT_LIBS = ("sky130_fd_sc_hd", "sky130_fd_sc_hs", "sky130_fd_sc_ms")


def _is_single_vt(binding, liberty_paths):
    """Is VT swap a no-op on this node?

    PREFER THE BINDING. `capabilities.vt_swap` is where the node owner recorded
    the decision: `not_applicable` means single-Vt (every OpenROAD VT move does
    nothing), `available` means a second Vt library is bound and VT swap is a
    REAL transform.

    WHY THE NAME HEURISTIC IS NOT ENOUGH: matching Liberty paths against a tuple
    of sky130 library names answers "is this one of three known single-Vt
    libraries", not "is this node single-Vt". Every OTHER node -- including one
    that genuinely is single-Vt -- falls through to False, i.e. "VT swap is
    available", and the wave then promises a recovery class that does nothing.
    It is right on sky130 and on nangate45 BY COINCIDENCE (nangate45 really is
    multi-Vt), which is exactly the kind of accidental correctness that hides a
    defect until a third node appears.
    """
    if isinstance(binding, dict):
        caps = binding.get("capabilities")
        if isinstance(caps, dict):
            entry = caps.get("vt_swap")
            if isinstance(entry, dict):
                state = entry.get("state")
                if state == "not_applicable":
                    return True, "binding:capabilities.vt_swap=not_applicable"
                if state in ("available", "available_with_gaps", "degraded"):
                    return False, "binding:capabilities.vt_swap=%s" % state
    joined = " ".join(liberty_paths or [])
    if any(v in joined for v in _SINGLE_VT_LIBS):
        return True, "liberty_name_heuristic:known_single_vt_library"
    return None, "undetermined:no vt_swap capability and no known library name"

DETECT_ONLY_CLASSES = ("min_pulse_width", "min_period", "noise")


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


def _is_ident(s):
    """True if *s* is a safe design identifier -- blocks Tcl injection via a
    user-supplied top-module name interpolated into a generated script."""
    return bool(s) and bool(re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", str(s)))


def _env_dir(default, *names):
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
    """CDE self-validation + provenance stamping. Never raises."""
    if not isinstance(results, dict):
        return results
    try:
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

    try:
        import cde_progress as _cde_progress   # _CDE_PROGRESS_STAMPED_V1
        _cde_progress.stamp_progress(results, results.get("stage") or TOOL)
    except Exception as _e:
        print("[" + str(TOOL) + "] progress stamp skipped: " + str(_e), flush=True)

    return results


def _save_run_command(cmd, name="run_command.txt"):
    try:
        import shlex
        if isinstance(cmd, (list, tuple)):
            line = " ".join(shlex.quote(str(c)) for c in cmd)
        else:
            line = str(cmd)
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
            unit = v.get("unit")
            return str(v["value"]) + ((" " + str(unit)) if unit else "")
        return json.dumps(v, default=str)[:300]
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)[:300]
    return str(v)


def _report_kv_rows(d):
    rows = []
    for k, v in (d or {}).items():
        rows.append("| " + str(k) + " | " + _report_fmt_val(v) + " |")
    return rows


def _render_report_md(r):
    L = ["# " + str(r.get("tool", TOOL)) + " report", ""]
    val = r.get("validation") or {}
    L += ["**status:** " + str(r.get("status", "unknown"))
          + " \u00b7 **verdict:** " + str(val.get("verdict", "")), ""]
    if r.get("objective"):
        L += [str(r["objective"]), ""]
    if val.get("note"):
        L += ["> " + str(val["note"]), ""]
    for title, key in (("Results", "results"), ("QoR metrics", "qor_metrics"),
                       ("Signoff evidence", "signoff_evidence")):
        d = r.get(key)
        if isinstance(d, dict) and d:
            rows = _report_kv_rows(d)
            if rows:
                L += ["## " + title, "", "| Metric | Value |", "| --- | --- |"] \
                    + rows + [""]
    if r.get("error"):
        L += ["## Error", "", "```", str(r["error"]), "```", ""]
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
            print("[" + str(TOOL) + "] organize: could not move " + entry
                  + ": " + str(_e), flush=True)


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
        _organize_output()
    except Exception as _org_e:
        print("[" + str(TOOL) + "] output organize skipped: " + str(_org_e), flush=True)


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _openroad_bin():
    return shutil.which("openroad")


def _tool_version(binname):
    try:
        out = subprocess.run([binname, "-version"], capture_output=True,
                             text=True, timeout=30)
        return (out.stdout + out.stderr).strip().split("\n")[0]
    except Exception:
        return "unknown"


def _cde(objective, status, results=None, signoff=None, qor=None,
         pdk_binding=None, assumptions=None, margin=None, validation=None,
         provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "stage": "eco",
        "tools_used": [{"name": "OpenROAD",
                        "version": (provenance or {}).get("openroad", "unknown")}],
        "pdk_binding": pdk_binding or "none",
        "assumptions": assumptions or [],
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


def _fail(objective, error, params=None):
    env = _cde(objective, "failed",
               validation={"verdict": "fail", "note": error}, error=error)
    if params is not None:
        env["input_parameters"] = dict(params)
    return env


# --------------------------------------------------------------------------
# scenario: analyze_violations -- pure analysis, no engine, no mutation
# --------------------------------------------------------------------------
def _handle_analyze_violations(params):
    """Cluster a signoff STA report and apply the ECO entry screen.

    This is the scenario the agent calls FIRST, before any wave. It never edits
    the design, so it is safe to run repeatedly and cheap to re-run after each
    wave to re-derive the next target.
    """
    obj = "cluster violating paths and screen ECO entry"
    rpt = params.get("sta_report")
    if not rpt or not os.path.isfile(str(rpt)):
        return _fail(obj, "sta_report is required and must be an existing file "
                          "(OpenSTA report_checks output)", params)

    with open(rpt, "r", encoding="utf-8", errors="replace") as fh:
        paths = path_cluster.parse_report_checks(fh.read())

    ptype = params.get("path_type")
    if ptype in ("max", "min"):
        paths = [p for p in paths if p["path_type"] == ptype]

    period = params.get("clock_period_ns")
    endpoints = params.get("total_endpoints")
    thresholds = params.get("thresholds") or None

    # Scopes this level may not modify. In a timing-transparent hierarchical
    # flow the top-level report contains macro-INTERNAL instances (the macro is
    # read as routed netlist + SPEF because no Liberty abstraction exists), so
    # without this the highest-leverage candidate can be an illegal fix target.
    frozen = _as_list(params.get("frozen_prefixes"))

    analysis = path_cluster.analyze(paths, clock_period_ns=period,
                                    thresholds=thresholds,
                                    frozen_prefixes=frozen)
    screen = path_cluster.entry_screen(analysis, total_endpoints=endpoints,
                                       clock_period_ns=period,
                                       thresholds=thresholds)
    top = int(params.get("top", 20))
    ranked = analysis["candidates"][:top]

    # A hard reject is a real, reportable OUTCOME -- the stage ran, measured,
    # and concluded ECO is the wrong instrument. It is not a tool failure, and
    # it is not a pass: the gate is still open and the caller must escalate.
    if screen["verdict"] == "hard_reject":
        verdict = {"verdict": "fail",
                   "note": "ECO entry rejected; escalate to a rung-2 reopen. "
                           + "; ".join(screen["reasons"])}
    else:
        verdict = {"verdict": "review",
                   "note": "ECO entry is plausible on the screen; the fix-set, "
                           "batch size and aggression level are the agent's "
                           "decision from the ranked candidates."}

    return _cde(
        obj, "completed",
        results={
            "entry_verdict": screen["verdict"],
            "frozen_scopes_declared": {
                "value": len(analysis["frozen"]["prefixes"]), "unit": "count"},
            "paths_with_no_fixable_instance": {
                "value": analysis["frozen"]["paths_with_no_fixable_instance"],
                "unit": "count"},
            "violating_paths": {"value": analysis["path_counts"]["violating"],
                                "unit": "count"},
            "wns_ns": {"value": analysis["wns_ns"], "unit": "ns"},
            "tns_ns": {"value": analysis["tns_ns"], "unit": "ns"},
            "concentration_fraction": {
                "value": analysis["concentration"]["coverage_fraction"],
                "unit": "fraction"},
        },
        qor={
            "violating_paths": analysis["path_counts"]["violating"],
            "wns_ns": analysis["wns_ns"],
            "tns_ns": analysis["tns_ns"],
            "concentration_fraction":
                analysis["concentration"]["coverage_fraction"],
            "analyzed_paths": analysis["path_counts"]["total_parsed"],
        },
        signoff={
            "entry_screen": screen,
            "ranked_candidates": ranked,
            # Dominant but ILLEGAL to modify here. Surfaced so the agent can
            # escalate to the owning block rather than silently ignoring the
            # real cause -- or worse, editing into a signed-off macro.
            "frozen_candidates": analysis["frozen_candidates"][:top],
            "frozen": analysis["frozen"],
            "by_startpoint": analysis["by_startpoint"],
            "by_launch_clock": analysis["by_launch_clock"],
            "by_path_group": analysis["by_path_group"],
            "thresholds_provisional": screen["thresholds_provisional"],
        },
        margin={"method": "entry_screen_bands",
                "endpoint_band": screen["endpoint_band"],
                "wns_band": screen["wns_band"]},
        assumptions=[
            "Entry thresholds are PROVISIONAL priors, not calibrated against "
            "this flow or PDK; recalibrate from real converged/plateaued runs.",
            "Concentration, not raw violation count, is the primary entry "
            "discriminator.",
        ],
        inputs_ref={"sta_report": rpt},
        validation=verdict,
        pdk_binding=params.get("pdk_binding") or "none",
        provenance={"analysis_only": True, "engine": "none"},
    )


# --------------------------------------------------------------------------
# scenario: eco_wave -- one bounded, checkpointed, reversible repair wave
# --------------------------------------------------------------------------
def _resize_swaps(params):
    """Normalise and syntactically validate the requested cell swaps.

    Returns (swaps, error) where swaps is a list of (instance, to_cell).

    The swaps are AGENT-SUPPLIED and are never inferred here. That is a
    deliberate limit, not an omission: OpenSTA's `report_equiv_cells` reports
    only AREA and LEAKAGE (measured against the sky130 Liberty -- e.g.
    inv_1 leakage 5.327e-12 is reported verbatim as the 4th column), and
    carries NO drive-strength column. Cell NAMES do not encode it reliably
    either -- sky130 inv_1 and inv_2 have IDENTICAL area, and the leakage
    ordering across the inv family is non-monotonic in the numeric suffix. So
    there is no sound basis in the available data for this tool to decide which
    equivalent cell is "stronger", and inventing one would produce a confident
    wrong swap. The agent names the target cell; the tool proves it is
    logically equivalent and executes it reversibly.
    """
    raw = params.get("resize_swaps")
    if raw is None:
        return [], None
    if not isinstance(raw, (list, tuple)):
        return None, ("'resize_swaps' must be a list of "
                      "{\"instance\": ..., \"to_cell\": ...} objects; got %s"
                      % type(raw).__name__)
    swaps = []
    seen = {}
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, ("resize_swaps[%d] must be an object with 'instance' "
                          "and 'to_cell'; got %r" % (i, item))
        inst = item.get("instance")
        cell = item.get("to_cell")
        for nm, v in (("instance", inst), ("to_cell", cell)):
            if not isinstance(v, str) or not v.strip():
                return None, ("resize_swaps[%d].%s must be a non-empty string"
                              % (i, nm))
        inst, cell = inst.strip(), cell.strip()
        # Both values are interpolated into the generated Tcl via _tq, which
        # rejects braces/newlines. Reject here too so the failure names the
        # offending swap rather than surfacing as an opaque quoting error.
        for nm, v in (("instance", inst), ("to_cell", cell)):
            if any(c in v for c in "{}\n\r") or any(c.isspace() for c in v):
                return None, ("resize_swaps[%d].%s = %r contains whitespace or "
                              "braces, which cannot be embedded in the "
                              "generated Tcl" % (i, nm, v))
        # The same instance swapped twice in one wave is a contradiction: only
        # the LAST would survive, so the fix ledger would claim a swap that the
        # design does not carry.
        if inst in seen and seen[inst] != cell:
            return None, ("resize_swaps names instance %r twice with different "
                          "targets (%r then %r); one wave applies one swap per "
                          "instance" % (inst, seen[inst], cell))
        seen[inst] = cell
        swaps.append((inst, cell))
    return swaps, None


def _parse_equiv_cells(text):
    """Parse `report_equiv_cells` stdout into {queried_cell: set(equivalents)}.

    Real captured form (OpenSTA 3.1.0, sky130 -- verbatim, including rules):

        The following 3 cells are equivalent to sky130_fd_sc_hd__xor2_1:
        =============================================================
                  Cell                        Area   Area Leakage  Leakage  VT
                                             (um^2)  Ratio  (W)     Ratio  Type
        =============================================================
        sky130_fd_sc_hd__xor2_1               8.758  1.00 4.28e-12  1.00   -
        sky130_fd_sc_hd__xor2_2              16.266  1.86 5.59e-12  1.31   -
        -------------------------------------------------------------

    The tool's OWN column header settles what this report does and does not
    say: Area, Area Ratio, Leakage, Leakage Ratio, VT Type. There is NO drive
    strength here, which is why the target cell of a swap must be supplied by
    the caller and cannot be chosen from this table.

    A block whose parsed row count disagrees with its declared "The following N
    cells" header is DISCARDED rather than returned short. A silently truncated
    equivalence set would wrongly reject a legal swap, or -- if the parser ever
    drifts the other way -- wrongly admit an illegal one.
    """
    out, counts = {}, {}
    cur = None
    for line in (text or "").splitlines():
        line = line.rstrip()
        stripped = line.strip()
        m = re.match(r"\s*The following (\d+) cells are equivalent to (\S+?)"
                     r"(?:\s+with matching)?:?\s*$", line)
        if m:
            cur = m.group(2).rstrip(":")
            out.setdefault(cur, set())
            counts[cur] = int(m.group(1))
            continue
        if cur is None or not stripped:
            continue
        # Rules, the wrapped two-line column header, and the trailing rule.
        if set(stripped) <= set("=-") or stripped.startswith("Cell") \
                or stripped.startswith("(um^2)") or stripped.endswith(":"):
            continue
        # name  area  area_ratio  leakage  leakage_ratio  vt
        m2 = re.match(r"(\S+)\s+[\d.]+\s+[\d.]+\s+[\d.eE+-]+\s+[\d.]+\s+\S+$",
                      stripped)
        if m2:
            out[cur].add(m2.group(1))
        else:
            cur = None
    for cell, want in counts.items():
        if len(out.get(cell, ())) != want:
            out.pop(cell, None)
    return out


BUFFER_PURPOSES = ("fanout", "hold", "load_isolation")


def _buffer_insertions(params):
    """Normalise and syntactically validate requested buffer insertions.

    Returns (insertions, error). Each entry is a dict with `net`,
    `buffer_cell`, `load_pins`, `purpose` and an optional `location`.

    ONE COMMAND, TWO JOBS. `insert_buffer` serves both
      * FANOUT SPLITTING -- move a subset of a net's loads behind a new buffer
        so the driver's fanout drops below the max_fanout limit; and
      * HOLD PADDING -- interpose a buffer between a driver and a specific load
        to add delay on a too-fast path.
    The mechanics are identical, so `purpose` is recorded rather than inferred:
    the same insertion is a fanout fix or a hold fix depending on intent the
    tool cannot read off the netlist, and mislabelling it would make the fix
    ledger lie about why the design changed.

    The BUFFER CELL is caller-supplied. It is not chosen here for the same
    reason the resize target is not: the drive strength / delay needed is a
    timing decision, and no drive-strength ranking is available from the data
    this tool can read.
    """
    raw = params.get("buffer_insertions")
    if raw is None:
        return [], None
    if not isinstance(raw, (list, tuple)):
        return None, ("'buffer_insertions' must be a list of objects with "
                      "'net', 'buffer_cell' and 'load_pins'; got %s"
                      % type(raw).__name__)
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, ("buffer_insertions[%d] must be an object with 'net', "
                          "'buffer_cell' and 'load_pins'; got %r" % (i, item))
        net = item.get("net")
        cell = item.get("buffer_cell")
        pins = item.get("load_pins")
        for nm, v in (("net", net), ("buffer_cell", cell)):
            if not isinstance(v, str) or not v.strip():
                return None, ("buffer_insertions[%d].%s must be a non-empty "
                              "string" % (i, nm))
        if not isinstance(pins, (list, tuple)) or not pins:
            return None, ("buffer_insertions[%d].load_pins must be a non-empty "
                          "list of instance/pin names -- an insertion that "
                          "moves no load changes nothing and would be a no-op"
                          % i)
        purpose = item.get("purpose") or "fanout"
        if purpose not in BUFFER_PURPOSES:
            return None, ("buffer_insertions[%d].purpose must be one of %s; "
                          "got %r" % (i, ", ".join(BUFFER_PURPOSES), purpose))
        clean_pins = []
        for p in pins:
            if not isinstance(p, str) or not p.strip():
                return None, ("buffer_insertions[%d].load_pins entries must be "
                              "non-empty strings" % i)
            clean_pins.append(p.strip())
        # Everything below is interpolated into generated Tcl via _tq, which
        # rejects braces/newlines. Reject here so the error names the offending
        # insertion instead of surfacing as an opaque quoting failure.
        for nm, v in ([("net", net.strip()), ("buffer_cell", cell.strip())]
                      + [("load_pins entry", p) for p in clean_pins]):
            if any(c in v for c in "{}\n\r") or any(c.isspace() for c in v):
                return None, ("buffer_insertions[%d] %s = %r contains "
                              "whitespace or braces, which cannot be embedded "
                              "in the generated Tcl" % (i, nm, v))
        if len(set(clean_pins)) != len(clean_pins):
            return None, ("buffer_insertions[%d].load_pins repeats a pin; a "
                          "pin can only move behind the new buffer once" % i)
        loc = item.get("location")
        if loc is not None:
            if (not isinstance(loc, (list, tuple)) or len(loc) != 2
                    or not all(isinstance(c, (int, float)) for c in loc)):
                return None, ("buffer_insertions[%d].location must be [x, y] "
                              "in DBU" % i)
        out.append({"net": net.strip(), "buffer_cell": cell.strip(),
                    "load_pins": clean_pins, "purpose": purpose,
                    "location": list(loc) if loc else None})

    # A load pin may only be claimed ONCE per wave. The first insertion moves
    # it off its net; a second insertion naming the same pin is then asking to
    # move a pin that is no longer where it says it is -- and OpenROAD does not
    # refuse that, it silently rewires (the same hazard as an off-net pin).
    # Caught across the WHOLE request, not just within one entry.
    claimed = {}
    for i, b in enumerate(out):
        for p in b["load_pins"]:
            if p in claimed:
                return None, ("buffer_insertions[%d] and [%d] both move load "
                              "pin %r. After the first insertion that pin is "
                              "no longer on net %r, so the second would "
                              "silently rewire it -- one pin, one insertion "
                              "per wave" % (claimed[p], i, p, out[i]["net"]))
            claimed[p] = i
    return out, None


def _clock_buffer_cells(raw):
    """Normalise a clock-buffer list from any shape the flow actually uses.

    NOT cosmetic. chip-cts is driven in this campaign with

        "clock_buffer": "{sky130_fd_sc_hd__clkbuf_1 sky130_fd_sc_hd__clkbuf_2
                          sky130_fd_sc_hd__clkbuf_4 ...}"

    -- a Tcl LIST STRING, because that value is passed straight to a Tcl
    command. Read naively that is ONE string containing braces, which can never
    equal a cell name, so every clock-net insertion would be refused with a
    baffling "not in the list" message quoting the whole blob. The rule would
    be unusable against the very binding the flow supplies.

    Accepts: a JSON list, a plain space/comma-separated string, or the
    brace-wrapped Tcl form. Returns a set of bare cell names.
    """
    cells = set()
    for item in _as_list(raw):
        if not isinstance(item, str):
            continue
        s = item.strip()
        # Strip the Tcl braces that wrap a list value, then split on
        # whitespace/commas so all three shapes converge.
        if s.startswith("{") and s.endswith("}"):
            s = s[1:-1]
        for part in re.split(r"[\s,]+", s):
            part = part.strip().strip("{}")
            if part:
                cells.add(part)
    return cells


def _repair_commands(params):
    """Build the ordered repair command list for this wave.

    ORDER IS DOCTRINE, NOT PREFERENCE. The default is
    DRV pre-pass -> setup -> hold -> full DRV, because:
      * a slew/cap violation frequently MANIFESTS as a setup miss, so cleaning
        DRV first can delete part of the setup list for free;
      * setup repair injects delay changes that break hold closure, so fixing
        hold first usually means fixing it twice.
    OpenROAD also hardcodes setup-before-hold when both are passed in ONE call,
    so setup and hold are issued as SEPARATE invocations to keep the ordering
    explicit and auditable rather than delegated.
    """
    classes = _as_list(params.get("repair_classes") or ["drv_pre", "setup", "hold", "drv"])
    aggression = params.get("aggression", "conservative")
    if aggression not in AGGRESSION_LEVELS:
        return None, ("aggression must be one of "
                      + ", ".join(sorted(AGGRESSION_LEVELS)))
    skips = list(AGGRESSION_LEVELS[aggression])

    # Agent-directed cell swaps. Coupling is checked in BOTH directions so a
    # half-specified request can never run as a silent no-op: swaps supplied
    # but never applied would report a wave that "did nothing wrong", and a
    # resize class with no swaps would report a repair that never happened.
    swaps, err = _resize_swaps(params)
    if err:
        return None, err
    if swaps and "resize" not in classes:
        return None, ("resize_swaps were supplied but 'resize' is not in "
                      "repair_classes, so the swaps would never be applied; "
                      "add 'resize' to repair_classes or drop resize_swaps")
    if "resize" in classes and not swaps:
        return None, ("repair_classes includes 'resize' but resize_swaps is "
                      "empty; a resize wave with no swaps cannot change "
                      "anything and would be rolled back as a no-op")

    # Agent-directed buffer insertions, coupled in both directions for the same
    # reason as the swaps.
    bufs, err = _buffer_insertions(params)
    if err:
        return None, err
    if bufs and "buffer" not in classes:
        return None, ("buffer_insertions were supplied but 'buffer' is not in "
                      "repair_classes, so they would never be applied; add "
                      "'buffer' to repair_classes or drop buffer_insertions")
    if "buffer" in classes and not bufs:
        return None, ("repair_classes includes 'buffer' but buffer_insertions "
                      "is empty; a buffer wave with no insertions cannot "
                      "change anything and would be rolled back as a no-op")

    # OpenROAD's own -repair_tns default is 100, i.e. repair EVERY violating
    # endpoint -- the widest possible batch. A stage whose entire doctrine is
    # "small bounded waves" must not inherit that: an unspecified batch breadth
    # defaults to the NARROWEST setting (worst endpoint only), and widening it
    # is an explicit decision the agent records.
    repair_tns = params.get("repair_tns")
    if repair_tns is None:
        repair_tns = 0
    max_per_pass = params.get("max_repairs_per_pass")
    setup_margin = params.get("setup_margin_ns")
    hold_margin = params.get("hold_margin_ns")
    max_util = params.get("max_utilization")
    max_buf_pct = params.get("max_buffer_percent")

    cmds = []
    for c in classes:
        if c == "resize":
            # An explicit swap is worthless if the instance is frozen by the
            # scope guard, so each target is thawed immediately before its
            # swap. This is narrower than thawing the whole cluster: the
            # instance is unfrozen for the swap and the batch optimizer still
            # sees the scope the agent set.
            for inst, cell in swaps:
                cmds.append((c, "unset_dont_touch [get_cells %s]" % _tq(inst)))
                cmds.append((c, "replace_cell %s %s" % (_tq(inst), _tq(cell))))
        elif c == "buffer":
            for i, b in enumerate(bufs):
                line = ("insert_buffer -buffer_cell %s -net %s -load_pins %s"
                        % (_tq(b["buffer_cell"]), _tq(b["net"]),
                           "[list %s]"
                           % " ".join(_tq(p) for p in b["load_pins"])))
                if b["location"]:
                    line += (" -location {%d %d}"
                             % (int(b["location"][0]), int(b["location"][1])))
                # A requested name is a REQUEST: OpenROAD appends a uniquifying
                # suffix (measured: eco_buf_req -> eco_buf_req1), so the name
                # recorded as evidence is DISCOVERED after the fact rather than
                # assumed from what was asked for.
                line += " -buffer_name %s" % _tq(
                    "eco_w%d_buf%d" % (int(params.get("wave_index", 0)), i))
                cmds.append((c, line))
        elif c in ("drv_pre", "drv"):
            line = "repair_design"
            if params.get("max_wire_length_um"):
                line += " -max_wire_length %s" % float(params["max_wire_length_um"])
            # repair_design accepts -max_utilization too; applying the area cap
            # to only half the repair passes would let DRV repair blow through
            # the budget the agent set.
            if max_util is not None:
                line += " -max_utilization %s" % float(max_util)
            cmds.append((c, line))
        elif c in ("setup", "hold"):
            line = "repair_timing -%s" % c
            line += " -repair_tns %s" % float(repair_tns)
            if max_per_pass is not None:
                line += " -max_repairs_per_pass %d" % int(max_per_pass)
            if c == "setup" and setup_margin is not None:
                line += " -setup_margin %s" % float(setup_margin)
            if c == "hold" and hold_margin is not None:
                line += " -hold_margin %s" % float(hold_margin)
            if max_util is not None:
                line += " -max_utilization %s" % float(max_util)
            if c == "hold" and max_buf_pct is not None:
                line += " -max_buffer_percent %d" % int(max_buf_pct)
            # Every skip flag names a SETUP-fixing transform (pin swap, gate
            # cloning, fanout down-sizing, rebuffering, buffer removal, last
            # gasp), so they are emitted only on the setup pass. Attaching them
            # to -hold would be inert and would misrepresent the fix ledger as
            # having constrained hold repair.
            if c == "setup":
                line += "".join(" " + s for s in skips)
            # -allow_setup_violations is DELIBERATELY never emitted. OpenROAD
            # otherwise refuses hold buffers that would break setup, which is a
            # free per-wave regression guard beneath our own rollback.
            cmds.append((c, line))
        else:
            return None, ("unknown repair class %r; expected any of "
                          "resize, buffer, drv_pre, setup, hold, drv" % c)
    return cmds, None


def _validate_buffers(orbin, paths, insertions, wave, clock_cells):
    """Prove every buffer insertion is safe BEFORE mutating the design.

    Runs a separate READ-ONLY OpenROAD pass, for the same reason the resize
    probe does: the answers are only available by parsing tool output, and a
    bad insertion must be refused before the netlist is touched rather than
    detected afterwards by a judge that cannot see it.

    WHAT OPENROAD ALREADY REFUSES, and is therefore NOT re-checked here (a
    duplicated rule drifts): a non-buffer cell -- an inverter, a NAND -- is
    rejected with RSZ-0211, and an unknown lib cell with STA-0119.

    WHAT OPENROAD ACCEPTS AND MUST BE CAUGHT HERE (both measured on
    crc16_ccitt):
      * a net that does not exist -- a buffer is still created and the load
        pin is moved onto a net with no proper driver;
      * a load pin that is NOT on the named net -- the pin is silently
        rewired. Measured: clkbuf_0_clk/A moved from `clk` to the new net,
        i.e. a clock input was re-parented onto a scan-enable-driven buffer.
        No timing or DRV check downstream would ever report that.

    CLOCK NETS. A buffer on a clock net becomes part of the clock tree, so it
    must come from the node's clock-buffer list: an ordinary data buffer is
    not characterised for the balanced rise/fall the tree was built on, and
    CTS balanced the tree against those cells. Clock-ness is classified from
    the UNION of two INDEPENDENT signals, because either alone can be blind:
      * the OpenDB signal type (`+ USE CLOCK` in the DEF), which is absent
        when the upstream flow did not annotate it; and
      * whether OpenSTA propagates a clock onto the net's pins, which is
        driven by the SDC and needs no DEF annotation.
    Measured on crc16_ccitt: both agree exactly -- clk / clknet_0_clk /
    clknet_2_0__leaf_clk are CLOCK, scan_en / _131_ / _124_ are not.
    Driver-cell NAMES are deliberately NOT used: net `_131_` is a data net
    driven by `sky130_fd_sc_hd__clkinv_1`, so a name heuristic reports a false
    clock.

    Returns (info, error).
    """
    probe = os.path.join(_OUTPUT_DIR, "eco_wave_%d_buffer_probe.tcl" % wave)
    L = ["# chip-eco buffer validation probe -- READ ONLY, mutates nothing"]
    for lib in paths["liberty"]:
        L.append("read_liberty %s" % _tq(lib))
    L.append("read_lef %s" % _tq(paths["tech_lef"]))
    for lef in paths["cell_lef"]:
        L.append("read_lef %s" % _tq(lef))
    L.append("read_def %s" % _tq(paths["def_file"]))
    L.append("read_sdc %s" % _tq(paths["sdc"]))
    # Clock classification needs propagated clocks, exactly as the wave does.
    L.append("set_propagated_clock [all_clocks]")
    L.append('puts "__NCLOCKS__ [llength [get_clocks]]"')
    L.append("set _blk [ord::get_db_block]")

    for idx, ins in enumerate(insertions):
        L.append('set _n [$_blk findNet %s]' % _tq(ins["net"]))
        L.append('if {$_n == "NULL"} { puts "__NONET__ %d" } else {'
                 % idx)
        L.append('  puts "__SIGTYPE__ %d [$_n getSigType]"' % idx)
        # Which pins are actually on this net right now.
        L.append('  set _on {}')
        L.append('  foreach _it [$_n getITerms] {')
        L.append('    lappend _on "[[$_it getInst] getName]/'
                 '[[$_it getMTerm] getName]"')
        L.append('  }')
        L.append('  puts "__ONNET__ %d $_on"' % idx)
        # STA-side clock propagation, independent of the DEF annotation.
        L.append('  set _wc 0')
        L.append('  if {![catch {set _pins [get_pins -of_objects '
                 '[get_nets %s]]}]} {' % _tq(ins["net"]))
        L.append('    foreach _p $_pins {')
        L.append('      if {[catch {set _cl [get_property $_p clocks]}]} '
                 '{ continue }')
        L.append('      if {$_cl ne ""} { incr _wc }')
        L.append('    }')
        L.append('  }')
        L.append('  puts "__PINCLOCKS__ %d $_wc"' % idx)
        L.append("}")
    L.append("exit")
    with open(probe, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    try:
        p = subprocess.run([orbin, "-exit", "-no_init", probe],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return None, "buffer validation probe timed out"
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    with open(os.path.join(_OUTPUT_DIR,
                           "eco_wave_%d_buffer_probe.log" % wave),
              "w", encoding="utf-8") as f:
        f.write(out)

    missing_net = set(re.findall(r"__NONET__\s+(\d+)", out))
    sigtypes = dict(re.findall(r"__SIGTYPE__\s+(\d+)\s+(\S+)", out))
    pinclocks = dict(re.findall(r"__PINCLOCKS__\s+(\d+)\s+(\d+)", out))
    onnet = {}
    for m in re.finditer(r"__ONNET__\s+(\d+)\s*(.*)", out):
        onnet[m.group(1)] = set(
            n[1:-1] if n.startswith("{") and n.endswith("}") else n
            for n in m.group(2).split())
    m_nclk = re.search(r"__NCLOCKS__\s+(\d+)", out)
    n_clocks = int(m_nclk.group(1)) if m_nclk else None

    info, bad = [], []
    for idx, ins in enumerate(insertions):
        key = str(idx)
        if key in missing_net or key not in sigtypes:
            bad.append("buffer_insertions[%d]: net %r does not exist in the "
                       "design. OpenROAD ACCEPTS this and still creates a "
                       "buffer, moving the load pins onto a net with no proper "
                       "driver, so it is refused here"
                       % (idx, ins["net"]))
            continue
        present = onnet.get(key, set())
        off = [p for p in ins["load_pins"] if p not in present]
        if off:
            bad.append("buffer_insertions[%d]: load pin(s) %s are NOT on net "
                       "%r. OpenROAD ACCEPTS this and SILENTLY REWIRES them "
                       "onto the new net (measured: a clock buffer input was "
                       "re-parented off the clock net), so it is refused here"
                       % (idx, ", ".join(sorted(off)[:6])
                          + (" ..." if len(off) > 6 else ""), ins["net"]))
            continue

        by_def = sigtypes.get(key) == "CLOCK"
        by_sta = int(pinclocks.get(key, 0)) > 0
        is_clock = by_def or by_sta
        basis = ("opendb_sigtype+sta_propagation" if (by_def and by_sta)
                 else "opendb_sigtype" if by_def
                 else "sta_propagation" if by_sta else "neither")
        if is_clock:
            if not clock_cells:
                bad.append(
                    "buffer_insertions[%d]: net %r is a CLOCK net (%s) but no "
                    "clock-buffer list is available, so the cell cannot be "
                    "checked against it. Supply 'clock_buffer_cells' (or set "
                    "it in the PDK binding); an unvalidated clock-tree "
                    "insertion is refused rather than guessed"
                    % (idx, ins["net"], basis))
                continue
            if ins["buffer_cell"] not in clock_cells:
                bad.append(
                    "buffer_insertions[%d]: net %r is a CLOCK net (%s) so the "
                    "buffer must come from the clock-buffer list; %r is not in "
                    "it (%s). A data buffer on the clock tree is not "
                    "characterised for the balanced rise/fall CTS built the "
                    "tree on"
                    % (idx, ins["net"], basis, ins["buffer_cell"],
                       ", ".join(sorted(clock_cells)[:6])
                       + (" ..." if len(clock_cells) > 6 else "")))
                continue
        elif n_clocks == 0:
            # No clocks in the SDC at all: "not a clock net" was never really
            # decided, it was merely never contradicted. Say so rather than
            # letting the data-path rule pass by default.
            bad.append(
                "buffer_insertions[%d]: net %r could not be classified because "
                "the SDC defines NO clocks, so neither signal can distinguish "
                "a clock net from a data net. Supply constraints that define "
                "the clocks, or the clock-buffer rule is unenforceable"
                % (idx, ins["net"]))
            continue

        info.append({
            "index": idx, "net": ins["net"], "buffer_cell": ins["buffer_cell"],
            "purpose": ins["purpose"],
            "load_pin_count": len(ins["load_pins"]),
            "loads_on_net_before": len(present),
            "net_class": "clock" if is_clock else "data",
            "net_class_basis": basis,
            "clock_cell_rule": ("enforced: cell is in the clock-buffer list"
                                if is_clock else "not applicable (data net)"),
        })
    if bad:
        return None, ("refusing unsafe buffer insertion(s):\n  - "
                      + "\n  - ".join(bad))
    return info, None


def _validate_swaps(orbin, paths, swaps, wave):
    """Prove every requested swap is LOGICALLY EQUIVALENT before mutating.

    Runs a separate READ-ONLY OpenROAD pass. Validating inside the mutating
    script is not possible: OpenSTA offers no Tcl accessor returning the
    equivalence set as a list, `report_equiv_cells` only prints, and this build
    has no redirect API -- so the answer is only available by parsing stdout,
    which cannot be done from inside the script that is already mutating.

    Doing it in a prior pass is also the SAFER order: a non-equivalent swap is
    refused before the design is touched at all, rather than being detected
    afterwards by a timing judge that cannot see a function change.

    Returns (info, error). `info` maps instance -> {"from","to","equivalents"}.
    """
    probe = os.path.join(_OUTPUT_DIR, "eco_wave_%d_swap_probe.tcl" % wave)
    L = ["# chip-eco swap validation probe -- READ ONLY, mutates nothing"]
    for lib in paths["liberty"]:
        L.append("read_liberty %s" % _tq(lib))
    L.append("read_lef %s" % _tq(paths["tech_lef"]))
    for lef in paths["cell_lef"]:
        L.append("read_lef %s" % _tq(lef))
    L.append("read_def %s" % _tq(paths["def_file"]))
    L.append("set _blk [ord::get_db_block]")
    for inst, _cell in swaps:
        L.append('set _i [$_blk findInst %s]' % _tq(inst))
        L.append('if {$_i == "NULL"} { puts "__NOINST__ %s" } else {'
                 ' puts "__MASTER__ %s [[$_i getMaster] getName]" }'
                 % (inst, inst))
    # Report the equivalence set of each CURRENT master (resolved above).
    L.append('foreach _nm [list %s] {'
             % " ".join(_tq(i) for i, _ in swaps))
    L.append('  set _i [$_blk findInst $_nm]')
    L.append('  if {$_i == "NULL"} { continue }')
    L.append('  puts "__EQ_FOR__ $_nm"')
    L.append('  catch {report_equiv_cells [[$_i getMaster] getName]}')
    L.append('}')
    L.append("exit")
    with open(probe, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    try:
        p = subprocess.run([orbin, "-exit", "-no_init", probe],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return None, "swap validation probe timed out"
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    with open(os.path.join(_OUTPUT_DIR,
                           "eco_wave_%d_swap_probe.log" % wave),
              "w", encoding="utf-8") as f:
        f.write(out)

    missing = re.findall(r"__NOINST__\s+(\S+)", out)
    if missing:
        return None, ("resize_swaps names instance(s) not present in the "
                      "design: %s" % ", ".join(sorted(set(missing))))
    masters = dict(re.findall(r"__MASTER__\s+(\S+)\s+(\S+)", out))
    equiv = _parse_equiv_cells(out)

    info, bad = {}, []
    for inst, cell in swaps:
        cur = masters.get(inst)
        if cur is None:
            return None, ("could not resolve the current cell of instance %r; "
                          "see eco_wave_%d_swap_probe.log" % (inst, wave))
        eq = equiv.get(cur)
        if not eq:
            # No equivalence set means the question was never answered. That is
            # NOT permission to proceed: an unchecked swap could change design
            # function, which no downstream timing check would catch.
            bad.append("%s: could not read the equivalence set of its current "
                       "cell %s, so the swap to %s is unverified"
                       % (inst, cur, cell))
            continue
        if cell not in eq:
            bad.append("%s: %s -> %s is NOT in the logical-equivalence set of "
                       "%s (%d equivalents: %s)"
                       % (inst, cur, cell, cur, len(eq),
                          ", ".join(sorted(eq)[:6])
                          + (" ..." if len(eq) > 6 else "")))
            continue
        if cell == cur:
            bad.append("%s is already %s; the swap would change nothing"
                       % (inst, cur))
            continue
        info[inst] = {"from": cur, "to": cell, "equivalents": sorted(eq)}
    if bad:
        return None, ("refusing to apply cell swap(s) that are not proven "
                      "logically equivalent:\n  - " + "\n  - ".join(bad))
    return info, None


def _tq(s):
    """Quote a value for safe interpolation into the generated Tcl.

    Every value that reaches the script -- file paths, net names, cell names,
    layer names -- is caller-supplied. Tcl treats `[`, `$`, `;` and whitespace
    as syntax, so an unquoted path with a space is a syntax error and an
    unquoted net name containing `[exec ...]` is command substitution. Braces
    suppress ALL substitution, so this is the safe form; a literal brace in the
    value would break the quoting, so it is rejected outright rather than
    escaped (no legitimate DEF/LEF name contains one).
    """
    s = str(s)
    if "{" in s or "}" in s or "\n" in s or "\r" in s:
        raise ValueError(
            "unsafe value for a generated Tcl script (braces/newlines are not "
            "permitted in paths, net, cell or layer names): %r" % s)
    return "{" + s + "}"


def _build_wave_tcl(params, cmds, paths):
    """Emit the OpenROAD script for one wave.

    Every value is brace-quoted via `_tq`; see that function for why.
    """
    wave = int(params.get("wave_index", 0))     # int() blocks comment injection
    L = ["# chip-eco wave %d -- generated, do not hand-edit" % wave]
    for lib in paths["liberty"]:
        L.append("read_liberty %s" % _tq(lib))
    L.append("read_lef %s" % _tq(paths["tech_lef"]))
    for lef in paths["cell_lef"]:
        L.append("read_lef %s" % _tq(lef))
    L.append("read_def %s" % _tq(paths["def_file"]))
    L.append("read_sdc %s" % _tq(paths["sdc"]))

    swaps, swap_error = _resize_swaps(params)
    if swap_error:
        raise ValueError(swap_error)
    if swaps:
        # Already-routed nets produce no GRT guides. Rebuild only wiring
        # incident to the explicitly resized instances, never the supply grid.
        L.append("set _eco_nets [dict create]")
        L.append("set _eco_block [ord::get_db_block]")
        for inst, _cell in swaps:
            L.append("set _eco_inst [$_eco_block findInst %s]" % _tq(inst))
            L.append('if {$_eco_inst == "NULL"} { error "resize instance disappeared" }')
            L.append("foreach _it [$_eco_inst getITerms] {")
            L.append("  set _net [$_it getNet]")
            L.append('  if {$_net == "NULL" || [$_net isSpecial]} { continue }')
            L.append('  if {[$_net getSigType] in {POWER GROUND}} { continue }')
            L.append("  dict set _eco_nets [$_net getName] $_net")
            L.append("}")
        L.append("dict for {_name _net} $_eco_nets {")
        L.append("  set _wire [$_net getWire]")
        L.append('  if {$_wire != "NULL"} { odb::dbWire_destroy $_wire }')
        L.append("}")
        L.append('puts "__ECO_RESIZE_REROUTE_NETS__ [dict keys $_eco_nets]"')

    if paths.get("signal_routing_layers"):
        L.append("set_routing_layers -signal %s" % _tq(paths["signal_routing_layers"]))
    # DEF retains detailed wires, not GRT's transient trees/listeners.
    # Reconstruct them before incremental repair, then load the input SPEF.
    L.append("global_route")

    # PARASITICS -- the single most consequential choice in this script.
    #
    # `estimate_parasitics -placement` OVERWRITES the parasitics held in the STA
    # database for every net. The manual is explicit that "placement-based
    # parasitics cannot accurately predict routed parasitics". On a post-route
    # design that already has signoff SPEF, issuing it would DISCARD the real
    # extraction and make every number this wave reports -- WNS, TNS, and the
    # commit/rollback verdict itself -- a placement estimate. A wave could then
    # be committed on optimistic timing and fail real signoff STA afterwards.
    # So: when SPEF is supplied, read it and estimate NOTHING.
    #
    # Placement estimation is correct ONLY when there is no SPEF (a pre-route
    # design), and `set_wire_rc` must precede it or the estimate has no RC model
    # to work from.
    # Repair creates nets even when existing nets have extracted parasitics.
    if paths.get("wire_rc_layer"):
        L.append("set_wire_rc -layer %s" % _tq(paths["wire_rc_layer"]))
    if paths.get("wire_rc_clk_layer"):
        L.append("set_wire_rc -clock -layer %s"
                 % _tq(paths["wire_rc_clk_layer"]))
    if paths.get("spef"):
        L.append("read_spef %s" % _tq(paths["spef"]))
        parasitic_basis = "spef_read"
    else:
        L.append("estimate_parasitics -placement")
        parasitic_basis = "placement_estimate"

    # The clock tree physically exists by now. Repairing against an ideal clock
    # mis-estimates every clock-path delay, so propagate before anything else.
    L.append("set_propagated_clock [all_clocks]")

    # std-cell fill must be gone before any cell is added: filler occupies the
    # row space the new buffers need.
    #
    # THIS MUST PRECEDE THE SCOPE FREEZE. `set_dont_touch [get_cells *]` marks
    # EVERY instance, including the physical filler/tap/endcap cells, and
    # `remove_fillers` then aborts the whole script on the first one:
    #   [ERROR ODB-0362] Attempt to destroy dont_touch instance
    #                    PHY_EDGE_ROW_0_Left_25
    # Measured on crc16_ccitt: with the freeze first, EVERY scoped wave died at
    # this line before running a single repair -- so `target_instances`, the
    # scoping that makes this stage "targeted", silently did nothing at all.
    # Removing fill first is safe: fill carries no signal nets, so nothing the
    # scope guard exists to protect is exposed by removing it earlier.
    L.append("remove_fillers")

    # Scope: freeze everything outside the target cluster so the batch optimizer
    # cannot wander off the cluster the agent selected. This is what makes the
    # repair "targeted" rather than a whole-design re-optimization.
    dont_touch = _as_list(params.get("dont_touch"))
    scope = _as_list(params.get("target_instances"))
    if scope:
        L.append("set_dont_touch [get_cells *]")
        for inst in scope:
            L.append("unset_dont_touch [get_cells %s]" % _tq(inst))
    for inst in dont_touch:
        L.append("set_dont_touch [get_cells %s]" % _tq(inst))

    # Incremental global route is a BRACKET, not a step: -start_incremental
    # installs the listener that records which nets the repair modifies, and
    # -end_incremental then re-routes ONLY those. Opening the bracket after the
    # repair would record nothing and silently degrade to a no-op re-route.
    L.append("global_route -start_incremental")

    for _cls, cmd in cmds:
        L.append("# --- repair class: %s" % _cls)
        L.append(cmd)

    # `-incremental` is REQUIRED here, not optional. The manual: "By default DPL
    # initiates with all instances unplaced." A bare `detailed_placement` on a
    # ROUTED design therefore re-legalizes the WHOLE die, moving cells far from
    # the positions their routing was built for -- which would defeat the
    # set_dont_touch scoping this stage is built around and invalidate routing
    # well outside the target cluster. `-max_displacement` bounds it further.
    dp = "detailed_placement -incremental"
    disp = params.get("max_displacement")
    if disp is not None:
        dp += " -max_displacement %s" % _tq(disp)
    L.append(dp)

    fillers = _as_list(params.get("filler_cells"))
    if fillers:
        L.append("filler_placement %s"
                 % _tq(" ".join(str(f) for f in fillers)))

    # RE-ATTACH EVERY NEW CELL TO THE SUPPLY NETS. This wave inserts real cells
    # -- repair buffers, resized gates, filler -- and OpenROAD does NOT connect
    # their power/ground pins on creation. Measured on crc16_ccitt (CTS, the
    # same defect class): 8 inserted buffers left 32 supply pins unattached
    # while the rails stayed perfectly intact, and `check_power_grid` passed
    # anyway because it audits the GRID, not each instance's attachment to it.
    # An ECO buffer with no power is a dead gate on a repaired timing path.
    #
    # Placed AFTER filler_placement so filler cells are covered too. See
    # _PG_RECONNECT_TCL for why `global_connect` alone does not fix this.
    L.append(_PG_RECONNECT_TCL.rstrip("\n"))

    # Close the bracket: re-route only the nets the repair touched.
    L.append("global_route -end_incremental")

    # PDN vias were legal against an empty canvas; the incremental route just
    # put real metal beside them. detailed_route repairs them inline when a
    # rail layer is named; otherwise the standalone pass runs afterwards.
    dr = "detailed_route -output_drc %s" % _tq(
        os.path.join(_OUTPUT_DIR, "eco_wave_route_drc.rpt"))
    via_layer = params.get("pdn_via_repair_layer")
    if via_layer:
        dr += " -repair_pdn_vias %s" % _tq(via_layer)
    L.append(dr)
    if params.get("repair_pdn_vias", True):
        L.append("repair_pdn_vias -all")

    # ARTIFACTS BEFORE VERIFICATION. A failing check_placement or
    # check_power_grid raises a Tcl error and aborts the script; if that
    # happened before write_def the whole wave would be destroyed and a
    # DETECTED problem would be indistinguishable from a CRASH. Writing first
    # means a wave that is merely bad can still be measured and rolled back on
    # the evidence, instead of vanishing.
    out_def = os.path.join(_OUTPUT_DIR, "eco_wave_%d.def" % wave)
    out_v = os.path.join(_OUTPUT_DIR, "eco_wave_%d.v" % wave)
    out_spef = os.path.join(_OUTPUT_DIR, "eco_wave_%d.spef" % wave)
    L.append("write_def %s" % _tq(out_def))
    L.append("write_verilog %s" % _tq(out_v))

    # Re-extract, then RE-READ, so the wave's verdict is measured against fresh
    # post-ECO parasitics rather than the pre-ECO SPEF (whose nets the repair
    # just changed) or a placement estimate. `define_process_corner` takes a
    # REQUIRED corner-name argument after the index -- omitting it is a hard
    # Tcl error, which is why the corner name is always emitted.
    if paths.get("rc_rules"):
        corner = params.get("corner_name") or "X"
        L.append("define_process_corner -ext_model_index 0 %s" % _tq(corner))
        L.append("extract_parasitics -ext_model_file %s"
                 % _tq(paths["rc_rules"]))
        L.append("write_spef %s" % _tq(out_spef))
        L.append("read_spef %s" % _tq(out_spef))
        parasitic_basis = "post_eco_reextracted"

    # Verification AFTER the artifacts exist. Errors are written to files so a
    # non-zero finding is captured as evidence rather than aborting the script.
    L.append("check_placement -verbose")
    if params.get("repair_pdn_vias", True):
        for _nm, _net in (("power", params.get("power_net") or "VDD"),
                          ("ground", params.get("ground_net") or "VSS")):
            L.append("check_power_grid -net %s -error_file %s"
                     % (_tq(_net),
                        _tq(os.path.join(_OUTPUT_DIR,
                                         "eco_wave_%d_grid_%s.rpt"
                                         % (wave, _nm)))))
            L.append('puts "__ECO_GRID_OK__ %s"' % _nm)

    rpt = os.path.join(_OUTPUT_DIR, "eco_wave_%d_sta.rpt" % wave)
    drv = os.path.join(_OUTPUT_DIR, "eco_wave_%d_drv.rpt" % wave)
    # `>` is OpenSTA's OWN redirection, parsed before normal argument handling,
    # so the target is left UNBRACED to match the form already proven in the
    # chip-sta tool. Safe because these targets are tool-generated paths under
    # the output dir and can never contain caller-supplied text.
    #
    # `-group_path_count`, NOT the deprecated `-group_count`. OpenSTA 3.1.0
    # still accepts the old spelling but answers every call with
    #   [WARNING STA-0503] report_checks -group_count is deprecated.
    # which lands INSIDE the redirected report, so the warning became line 1 of
    # the very file the judge parses. Verified equivalent on crc16_ccitt: the
    # two reports are byte-identical once that warning line is removed (4225 vs
    # 4224 lines, one diff hunk), so this is a safe rename and not a change of
    # what gets measured.
    L.append("report_checks -path_delay max -group_path_count %d > %s"
             % (int(params.get("max_paths", 200)), rpt))
    L.append("report_checks -path_delay min -group_path_count %d >> %s"
             % (int(params.get("max_paths", 200)), rpt))
    L.append("report_check_types -max_slew -max_capacitance -max_fanout "
             "-violators > %s" % drv)
    # CLOCK TREE BALANCE. Any wave that touches the clock tree -- a clock-net
    # buffer insertion above all -- can unbalance what CTS balanced, and that
    # damage is invisible to every other class measured here. Both check types
    # are emitted into ONE file; each line carries its own "setup skew" /
    # "hold skew" suffix, so the two remain distinguishable.
    skew = os.path.join(_OUTPUT_DIR, "eco_wave_%d_clock_skew.rpt" % wave)
    L.append("report_clock_skew -setup > %s" % skew)
    L.append("report_clock_skew -hold >> %s" % skew)
    L.append("exit")
    return "\n".join(L) + "\n", {
        "def": out_def, "netlist": out_v, "spef": out_spef,
        "sta_report": rpt, "drv_report": drv, "skew_report": skew,
        "route_drc": os.path.join(_OUTPUT_DIR, "eco_wave_route_drc.rpt"),
        "grid_reports": {
            "power": os.path.join(_OUTPUT_DIR,
                                  "eco_wave_%d_grid_power.rpt" % wave),
            "ground": os.path.join(_OUTPUT_DIR,
                                   "eco_wave_%d_grid_ground.rpt" % wave),
        },
        "parasitic_basis": parasitic_basis,
    }


def _parse_clock_skew(report_path):
    """Parse `report_clock_skew` output into {"<clock> <check>": skew_ns}.

    Verbatim captured form (OpenSTA 3.1.0, crc16_ccitt):

        Clock clk
           0.34 source latency _478_/CLK ^
          -0.33 target latency _479_/CLK ^
           0.05 clock uncertainty
           0.00 CRPR
        --------------
           0.06 setup skew

    and the hold report ends `  -0.06 hold skew`. The tool writes both check
    types into one file; each total carries its own suffix, and the most recent
    `Clock <name>` header names the clock, so a multi-clock design yields one
    entry per (clock, check type).

    Returns None when the report is absent -- "we did not look" must never be
    recorded as "we looked and the tree is balanced".
    """
    if not report_path or not os.path.isfile(report_path):
        return None
    out = {}
    clock = None
    with open(report_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"\s*Clock\s+(\S+)\s*$", line)
            if m:
                clock = m.group(1)
                continue
            m2 = re.match(r"\s*(-?[\d.]+)\s+(setup|hold)\s+skew\s*$", line)
            if m2 and clock:
                out["%s %s" % (clock, m2.group(2))] = float(m2.group(1))
    # A report that exists but yielded nothing parseable is NOT an empty-and-
    # therefore-balanced tree; it is an unreadable measurement.
    return out or None


def _count_drv_violators(report_path):
    """Count max-slew / max-cap / max-fanout violators in a report_check_types
    `-violators` report. Returns None when the report is absent -- "we did not
    look" must never be recorded as "we looked and it was clean"."""
    if not report_path or not os.path.isfile(report_path):
        return None
    n = 0
    with open(report_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # The pin-based shape carries an explicit marker; the group-table
            # shape does not, so a bare data row with a negative slack counts.
            if "(VIOLATED)" in line:
                n += 1
            elif re.match(r"^\s*\S+\s+-\d", line):
                n += 1
    return n


def _count_route_drc(report_path):
    """Count violations in a detailed_route `-output_drc` report, or None when
    the report is absent."""
    if not report_path or not os.path.isfile(report_path):
        return None
    n = 0
    with open(report_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.lstrip().startswith("violation type:"):
                n += 1
    return n


def _grid_errors(report_paths, log_text=None):
    """Read the `check_power_grid -error_file` outputs.

    Returns ``None`` when a report is missing. That distinction matters: a
    hard-coded "re-verified" string would report the INTENT to check rather
    than its RESULT, which is precisely the absence-as-evidence failure this
    stage exists to avoid.
    """
    out = {}
    for name, path in (report_paths or {}).items():
        if not path or not os.path.isfile(path):
            # PSM need not create an error file on success. Only a marker
            # emitted AFTER its successful native check can establish zero.
            out[name] = (0 if log_text is not None and
                         re.search(r"(?m)^__ECO_GRID_OK__ " + re.escape(name)
                                   + r"\s*$", log_text) else None)
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            out[name] = sum(1 for ln in fh if ln.strip())
    return out


def _measure(report_path, clock_period_ns=None, drv_report=None,
             route_drc=None, grid_reports=None, skew_report=None, grid_log=None):
    """Re-derive the wave's full state -- timing AND the other check classes.

    Timing alone is not enough to judge a wave: a repair that closes setup
    while creating max-cap violations, route shorts, a broken power grid or an
    unbalanced clock tree has made the design worse, and a timing-only verdict
    would commit it.
    """
    if not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8", errors="replace") as fh:
        paths = path_cluster.parse_report_checks(fh.read())
    setup = path_cluster.analyze([p for p in paths if p["path_type"] == "max"],
                                 clock_period_ns=clock_period_ns)
    hold = path_cluster.analyze([p for p in paths if p["path_type"] == "min"],
                                clock_period_ns=clock_period_ns)
    return {
        "setup": setup, "hold": hold,
        "drv_violators": _count_drv_violators(drv_report),
        "route_drc": _count_route_drc(route_drc),
        "grid_errors": _grid_errors(grid_reports, grid_log),
        "clock_skew": _parse_clock_skew(skew_report),
    }


_JUDGE_EPS = 1e-9


def _class_deltas(before, after):
    """Per-class before/after comparison for one wave.

    Used by BOTH the commit decision and the envelope evidence, so the deltas a
    reviewer reads are the very numbers the verdict was taken on rather than a
    re-derivation that could drift away from it.

    Every class is classified `improved`, `regressed`, `unchanged` or
    `not_measured`. `not_measured` is never folded into `unchanged`: "we did
    not look" and "we looked and it was clean" are different claims, and only
    one of them is evidence.
    """
    if before is None or after is None:
        return None
    out = []

    for cls in ("setup", "hold"):
        b, a = before[cls], after[cls]
        b_v = b["path_counts"]["violating"]
        a_v = a["path_counts"]["violating"]
        b_tns = b["tns_ns"] or 0.0
        a_tns = a["tns_ns"] or 0.0
        if b_v == 0 and a_v > 0:
            status = "regressed"
            detail = "%s was clean and now has %d violating paths" % (cls, a_v)
        elif b_v > 0 and a_v == 0:
            # Closing the last violating path lands at TNS 0.0 on BOTH sides of
            # the arithmetic, so a naive `after > before` test would roll back
            # the wave that actually won.
            status = "improved"
            detail = "%s closed its last %d violating path(s)" % (cls, b_v)
        elif a_tns > b_tns + _JUDGE_EPS:
            status = "improved"
            detail = ("%s TNS improved from %.4f to %.4f ns"
                      % (cls, b_tns, a_tns))
        elif a_tns < b_tns - _JUDGE_EPS:
            status = "regressed"
            detail = ("%s TNS worsened from %.4f to %.4f ns"
                      % (cls, b_tns, a_tns))
        else:
            status = "unchanged"
            detail = ("%s unchanged (%d violating, TNS %.4f ns)"
                      % (cls, a_v, a_tns))
        out.append({"class": cls, "status": status,
                    "before": {"violating_paths": b_v, "tns_ns": b_tns},
                    "after": {"violating_paths": a_v, "tns_ns": a_tns},
                    "detail": detail})

    for key, label in (("drv_violators", "DRV violators"),
                       ("route_drc", "routing DRC violations")):
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            out.append({
                "class": key, "status": "not_measured",
                "before": b, "after": a,
                "detail": ("%s were not measured on both sides of the wave, so "
                           "this class can neither vouch for nor block the "
                           "commit" % label)})
        elif a < b:
            out.append({"class": key, "status": "improved",
                        "before": b, "after": a,
                        "detail": "%s fell from %d to %d" % (label, b, a)})
        elif a > b:
            out.append({"class": key, "status": "regressed",
                        "before": b, "after": a,
                        "detail": "%s rose from %d to %d" % (label, b, a)})
        else:
            out.append({"class": key, "status": "unchanged",
                        "before": b, "after": a,
                        "detail": "%s unchanged at %d" % (label, a)})

    # CLOCK TREE BALANCE. Judged on |skew|: CTS balanced the tree, and a wave
    # that unbalances it has spent that investment. Larger magnitude = less
    # balanced, in either direction, so a skew moving TOWARD zero is a genuine
    # improvement.
    #
    # THIS IS NOT A TIMING CHECK, and must not be read as one. Measured on
    # crc16_ccitt across one clock-net buffer insertion:
    #     setup skew 0.06 -> 0.21 ns   while setup slack 10.37 -> 10.51 (BETTER)
    #     hold  skew -0.06 -> -0.21 ns while hold  slack  0.19 ->  0.06 (WORSE)
    # Skew and slack moved in OPPOSITE directions on the setup side -- that is
    # useful skew. So this class answers "is the clock tree still as balanced
    # as CTS made it", which setup/hold slack cannot answer, and it never
    # claims to predict which paths got faster.
    b_skew = before.get("clock_skew")
    a_skew = after.get("clock_skew")
    if b_skew is None or a_skew is None:
        out.append({
            "class": "clock_skew", "status": "not_measured",
            "before": b_skew, "after": a_skew,
            "detail": ("clock skew was not measured on both sides of the wave, "
                       "so clock-tree balance can neither vouch for nor block "
                       "the commit; pass 'baseline_clock_skew_report' to make "
                       "a clock-tree change judgeable")})
    else:
        for key in sorted(set(b_skew) | set(a_skew)):
            b, a = b_skew.get(key), a_skew.get(key)
            if b is None or a is None:
                out.append({
                    "class": "clock_skew:%s" % key, "status": "not_measured",
                    "before": b, "after": a,
                    "detail": ("clock skew for %s was reported on only one "
                               "side of the wave" % key)})
                continue
            if abs(a) > abs(b) + _JUDGE_EPS:
                status, detail = "regressed", (
                    "clock tree less balanced on %s: skew %.4f -> %.4f ns "
                    "(|skew| %.4f -> %.4f)" % (key, b, a, abs(b), abs(a)))
            elif abs(a) < abs(b) - _JUDGE_EPS:
                status, detail = "improved", (
                    "clock tree more balanced on %s: skew %.4f -> %.4f ns "
                    "(|skew| %.4f -> %.4f)" % (key, b, a, abs(b), abs(a)))
            else:
                status, detail = "unchanged", (
                    "clock skew on %s unchanged at %.4f ns" % (key, a))
            out.append({"class": "clock_skew:%s" % key, "status": status,
                        "before": b, "after": a, "detail": detail})

    # Power-grid connectivity is NOT symmetric with the other classes. A design
    # whose power grid reports errors is not shippable at any violation count,
    # so a non-zero AFTER is a veto even when the BEFORE was worse. Only the
    # transition to a fully clean grid counts as an improvement.
    b_grid = before.get("grid_errors") or {}
    a_grid = after.get("grid_errors") or {}
    for net in sorted(set(b_grid) | set(a_grid)):
        b, a = b_grid.get(net), a_grid.get(net)
        if a is None:
            status, detail = "not_measured", (
                "power grid on %s was not checked after the wave" % net)
        elif a > 0:
            status, detail = "regressed", (
                "power grid on %s reports %d error(s)" % (net, a))
        elif b:
            status, detail = "improved", (
                "power grid on %s went from %d error(s) to clean" % (net, b))
        else:
            status, detail = "unchanged", (
                "power grid on %s clean" % net)
        out.append({"class": "grid_errors:%s" % net, "status": status,
                    "before": b, "after": a, "detail": detail})
    return out


def _judge(before, after):
    """Commit-or-rollback decision for one wave.

    MULTI-CLASS. A wave is committed when it strictly improved AT LEAST ONE
    measured class -- setup, hold, DRV, routing DRC or power-grid connectivity
    -- and regressed NONE of them.

    Improvement is deliberately not restricted to timing. A repair that takes
    DRV from 155 to 0 while leaving slack untouched is a real, committable fix;
    judging it on total negative slack alone would roll it back with "the wave
    was unnecessary" and hand the identical work to the next stage, which is
    exactly the churn this stage exists to prevent.

    "Previously clean regressed" still outranks "target improved": trading a
    clean check for a better headline number is the chaos wave discipline
    prevents, so ANY regression vetoes the commit no matter how large the gain
    elsewhere.
    """
    if before is None or after is None:
        return False, ("timing could not be measured on both sides of the wave; "
                       "an unmeasurable wave is rolled back, never committed")

    deltas = _class_deltas(before, after)
    regressed = [d["detail"] for d in deltas if d["status"] == "regressed"]
    improved = [d["detail"] for d in deltas if d["status"] == "improved"]

    if regressed:
        return False, "rolled back: " + "; ".join(regressed)
    if improved:
        return True, ("committed: improved with no regression in any measured "
                      "class -- " + "; ".join(improved))

    # Nothing improved and nothing regressed. Distinguish "there was nothing to
    # fix" from "there was something to fix and this wave did not fix it": the
    # first says the wave should never have run, the second is a genuine
    # plateau data point.
    def _dirty(side):
        for d in deltas:
            if d["status"] == "not_measured":
                continue
            # Clock skew is a CONTINUOUS QUALITY metric, not a violation count.
            # EVERY real clock tree has non-zero skew, so a truthiness test
            # would read 0.06 ns of perfectly healthy skew as "something is
            # violating" and turn every "the wave was unnecessary" verdict into
            # a spurious "plateau" -- corrupting the very signal that drives
            # rung-2 escalation.
            if d["class"].startswith("clock_skew"):
                continue
            v = d[side]
            if isinstance(v, dict):
                if v["violating_paths"] > 0:
                    return True
            elif v:
                return True
        return False

    if not _dirty("before") and not _dirty("after"):
        return False, ("rolled back: nothing was violating before the wave "
                       "and nothing is now; the wave was unnecessary")
    return False, ("rolled back: no measurable improvement in any measured "
                   "class; a no-op wave must not enter the convergence trace")


def _churn(before, after):
    """Violations created per violation removed.

    The decisive plateau signature is NOT a flat WNS -- it is churn >= closure:
    each fix creating about as many new violations as it removes. That is the
    unambiguous "ECO is exhausted, the cause is structural" signal, and it is
    the evidence that names the rung-2 target.
    """
    if before is None or after is None:
        return None
    created = removed = 0
    for cls in ("setup", "hold"):
        b_ends = set(before[cls]["by_endpoint"].keys())
        a_ends = set(after[cls]["by_endpoint"].keys())
        created += len(a_ends - b_ends)
        removed += len(b_ends - a_ends)
    if removed == 0:
        return {"created": created, "removed": removed, "ratio": None,
                "note": "no violations removed; ratio undefined "
                        "(treat as exhausted if created > 0)"}
    return {"created": created, "removed": removed,
            "ratio": round(created / float(removed), 4)}


def _wave_closed(committed, before, after, deltas, outs):
    """A committed improvement is not necessarily a closed repair wave."""
    if not committed or not before or not after or not deltas:
        return False
    if any(d["status"] in ("not_measured", "regressed") for d in deltas):
        return False
    for measurement in (before, after):
        for cls in ("setup", "hold"):
            if measurement[cls]["path_counts"]["total_parsed"] <= 0:
                return False
    for cls in ("setup", "hold"):
        if (after[cls]["path_counts"]["violating"] != 0
                or after[cls]["tns_ns"] != 0.0):
            return False
    if after.get("drv_violators") != 0 or after.get("route_drc") != 0:
        return False
    grid = after.get("grid_errors") or {}
    if set(grid) != {"power", "ground"} or any(v != 0 for v in grid.values()):
        return False
    if outs.get("parasitic_basis") != "post_eco_reextracted":
        return False
    return all(outs.get(key) and os.path.isfile(outs[key])
               and os.path.getsize(outs[key]) > 0 for key in ("def", "netlist", "spef"))


def _handle_eco_wave(params):
    """Execute exactly ONE checkpointed, reversible ECO repair wave."""
    wave = int(params.get("wave_index", 0))
    obj = "ECO wave %d on %s" % (wave, params.get("top", "?"))
    binding = params.get("pdk_binding") or {}

    top = params.get("top")
    if not _is_ident(top):
        return _fail(obj, "top must be a valid design identifier", params)

    paths = {
        "def_file": params.get("def_file"),
        "sdc": params.get("sdc"),
        # Every node-dependent input falls back to the binding, because the
        # documented contract says it does. A missing fallback would silently
        # drop the input -- e.g. no filler cells means the wave writes a DEF
        # with unfilled rows and broken power-rail continuity.
        "spef": params.get("spef") or binding.get("spef"),
        "tech_lef": params.get("tech_lef") or binding.get("tech_lef"),
        "cell_lef": _as_list(params.get("cell_lef") or binding.get("cell_lef")),
        "liberty": _as_list(params.get("liberty") or binding.get("liberty")),
        "rc_rules": params.get("rc_rules") or binding.get("rc_rules"),
        "wire_rc_layer": params.get("wire_rc_layer") or binding.get("wire_rc_layer"),
        "wire_rc_clk_layer": (params.get("wire_rc_clk_layer")
                              or binding.get("wire_rc_clk_layer")),
    }
    routing = binding.get("routing_layers") or {}
    paths["signal_routing_layers"] = params.get("signal_routing_layers")
    if not paths["signal_routing_layers"] and routing.get("bottom_layer") and routing.get("top_layer"):
        paths["signal_routing_layers"] = "%s-%s" % (
            routing["bottom_layer"], routing["top_layer"])
    for key in ("def_file", "sdc", "tech_lef"):
        if not paths[key] or not os.path.isfile(str(paths[key])):
            return _fail(obj, "%s is required and must be an existing file" % key,
                         params)
    if not paths["liberty"]:
        return _fail(obj, "liberty is required (directly or via pdk_binding)",
                     params)
    if not paths["wire_rc_layer"]:
        return _fail(obj, "wire_rc_layer is required (directly or via "
                     "pdk_binding), including with SPEF: repair creates new nets",
                     params)

    # A wave cannot be JUDGED without a baseline, and an unjudgeable wave is
    # always rolled back -- which would look exactly like a plateau and could
    # send the flow to a rung-2 reopen for a missing argument. Fail closed
    # instead of emitting an endless series of "rolled back" waves.
    baseline = params.get("baseline_sta_report")
    if not baseline or not os.path.isfile(str(baseline)):
        return _fail(obj, "baseline_sta_report is required and must be an "
                          "existing file: without it the wave cannot be judged, "
                          "and an unjudgeable wave is indistinguishable from a "
                          "plateau", params)

    # The OPTIONAL non-timing baselines. A class whose baseline is missing is
    # unmeasured, and an unmeasured class can never be shown to have improved,
    # so without these the multi-class commit rule can never fire on DRV or
    # routing DRC -- and a rule that cannot fire is not a rule.
    #
    # Validated HERE, alongside the other inputs, rather than at the point of
    # use: the point of use sits after the rollback checkpoint has already been
    # written, so a caller who mistypes this path would get a spurious
    # checkpoint artifact before being told the argument was wrong.
    baseline_drv = params.get("baseline_drv_report")
    baseline_drc = params.get("baseline_route_drc_report")
    baseline_skew = params.get("baseline_clock_skew_report")
    for _nm, _p in (("baseline_drv_report", baseline_drv),
                    ("baseline_route_drc_report", baseline_drc),
                    ("baseline_clock_skew_report", baseline_skew)):
        if _p and not os.path.isfile(str(_p)):
            return _fail(obj, "%s was supplied but is not an existing file: "
                              "%s -- a baseline that cannot be read leaves its "
                              "class unjudgeable, so it is reported rather "
                              "than silently dropped" % (_nm, _p), params)

    # Fillers are node cells; resolve them from the binding when not given.
    if not params.get("filler_cells"):
        _bf = (binding.get("physical_cells") or {}).get("decap_cells") \
            if isinstance(binding.get("physical_cells"), dict) else None
        _bf = _bf or binding.get("filler_cells")
        if _bf:
            params = dict(params)
            params["filler_cells"] = _as_list(_bf)

    orbin = _openroad_bin()
    if not orbin:
        return _fail(obj, "openroad binary not found in the container image",
                     params)

    cmds, err = _repair_commands(params)
    if err:
        return _fail(obj, err, params)

    # Prove any agent-directed cell swap is logically equivalent BEFORE the
    # design is touched. A function-changing swap is invisible to this stage's
    # timing/DRV judge, so it must be refused up front rather than measured
    # afterwards.
    swaps, _serr = _resize_swaps(params)
    swap_info = {}
    if swaps:
        swap_info, serr = _validate_swaps(orbin, paths, swaps, wave)
        if serr:
            return _fail(obj, serr, params)

    # Buffer insertions are validated the same way and for the same reason.
    # The clock-buffer list is resolved caller > binding with NO invented
    # default: a fabricated list would let a data buffer onto the clock tree
    # while reporting that the rule had been applied.
    bufs, _berr = _buffer_insertions(params)
    buf_info = []
    clock_cells = _clock_buffer_cells(params.get("clock_buffer_cells")
                                      or binding.get("clock_buffer_cells")
                                      or binding.get("clock_buffer")
                                      or binding.get("clock_buffers"))
    if bufs:
        buf_info, berr = _validate_buffers(orbin, paths, bufs, wave,
                                           clock_cells)
        if berr:
            return _fail(obj, berr, params)

    period = params.get("clock_period_ns")

    # --- checkpoint -------------------------------------------------------
    # The rollback artifact is a copy of the INPUT, written into the OUTPUT
    # tree. It must live in /output, not /workdir: the envelope names it as the
    # artifact a rejected wave hands downstream, and a /workdir path would be a
    # dangling reference outside the container.
    ckpt_def = os.path.join(_OUTPUT_DIR, "eco_wave_%d_rollback.def" % wave)
    try:
        shutil.copyfile(paths["def_file"], ckpt_def)
    except Exception as e:
        return _fail(obj, "could not checkpoint the input DEF: %s" % e, params)

    tcl_path = os.path.join(_OUTPUT_DIR, "eco_wave_%d.tcl" % wave)
    try:
        script, outs = _build_wave_tcl(params, cmds, paths)
    except ValueError as e:
        return _fail(obj, str(e), params)
    with open(tcl_path, "w", encoding="utf-8") as f:
        f.write(script)

    # The baseline must be measured with the SAME extractor as the wave result,
    # or the two totals are not commensurable: `tns_ns` is the sum over the
    # paths PRESENT IN THE TEXT, so a baseline truncated at a different
    # -group_path_count would make any wave look like an improvement. The report is
    # parsed identically here, but the generating settings are outside this
    # tool's control, so the risk is recorded in the envelope rather than
    # silently assumed away.
    # The NON-TIMING baselines matter just as much. A class whose BEFORE is
    # unmeasured can never be shown to have improved, so passing only the STA
    # report would leave the multi-class commit rule unable to ever fire on
    # DRV or routing DRC. `baseline_drv` / `baseline_drc` were validated with
    # the other inputs above; their ABSENCE is reported as a named gap below
    # rather than silently collapsing the wave into "nothing improved".
    before = _measure(baseline, period,
                      drv_report=baseline_drv, route_drc=baseline_drc,
                      skew_report=baseline_skew)

    cmd = [orbin, "-exit", tcl_path]
    _save_run_command(cmd)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=int(params.get("timeout_s", 7200)))
    except subprocess.TimeoutExpired:
        return _fail(obj, "OpenROAD timed out during the ECO wave", params)
    runtime = round(time.time() - t0, 3)

    log_path = os.path.join(_OUTPUT_DIR, "eco_wave_%d.log" % wave)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(proc.stdout + "\n" + proc.stderr)

    engine_ok = proc.returncode == 0 and os.path.isfile(outs["def"])
    after = _measure(outs["sta_report"], period,
                     drv_report=outs.get("drv_report"),
                     route_drc=outs.get("route_drc"),
                     skew_report=outs.get("skew_report"),
                     grid_reports=outs.get("grid_reports"),
                     grid_log=proc.stdout + "\n" + proc.stderr) if engine_ok else None
    committed, note = _judge(before, after) if engine_ok else (
        False, "rolled back: OpenROAD exited %d or produced no DEF"
               % proc.returncode)
    deltas = _class_deltas(before, after) if engine_ok else None
    wave_closed = _wave_closed(committed, before, after, deltas, outs)
    churn = _churn(before, after)

    # A class that could not be judged is a GAP, and the gap has a cause the
    # caller can act on. Without this, a wave that really did fix DRV would be
    # reported as "no measurable improvement" -- indistinguishable from a wave
    # that achieved nothing -- purely because no baseline DRV report was
    # supplied to compare against.
    _gaps = []
    for _d in (deltas or []):
        if _d["status"] != "not_measured":
            continue
        if _d["class"] == "drv_violators" and not baseline_drv:
            _gaps.append("DRV could not be judged: pass 'baseline_drv_report' "
                         "(a pre-wave report_check_types -violators report) so "
                         "a DRV improvement is commitable rather than invisible")
        elif _d["class"] == "route_drc" and not baseline_drc:
            _gaps.append("routing DRC could not be judged: pass "
                         "'baseline_route_drc_report' so a DRC improvement is "
                         "commitable rather than invisible")
        elif _d["class"].startswith("clock_skew") and not baseline_skew:
            _gaps.append("clock-tree balance could not be judged: pass "
                         "'baseline_clock_skew_report' (a pre-wave "
                         "report_clock_skew report) or a wave that unbalances "
                         "the clock tree commits undetected")
        else:
            _gaps.append("%s could not be judged (report absent on one or both "
                         "sides of the wave)" % _d["class"])
    # A multi-clock design yields one unmeasured skew delta PER (clock, check
    # type), all with the same cause and the same remedy. Repeating the advice
    # N times buries the other gaps, so collapse duplicates while keeping order.
    _gaps = list(dict.fromkeys(_gaps))
    if _gaps and not committed and engine_ok:
        note = note + " [" + "; ".join(_gaps) + "]"

    # --- ROLLBACK: actually revert, do not merely re-point a field ---------
    # A rejected wave must leave NOTHING a downstream consumer can mistake for
    # a result. Re-pointing `eco_def` at the checkpoint while the mutated DEF
    # sat on disk under a plausible name would let a glob pick up the rejected
    # mutation -- so the mutated artifacts are renamed to an explicit
    # `.rejected` suffix, which is inert to every downstream pattern.
    if not committed:
        for _k in ("def", "netlist", "spef"):
            _p = outs.get(_k)
            if _p and os.path.isfile(_p):
                try:
                    os.replace(_p, _p + ".rejected")
                except Exception as _e:
                    print("[" + str(TOOL) + "] could not quarantine rejected "
                          + str(_p) + ": " + str(_e), flush=True)

    def _snap(m, cls):
        if not m:
            return {"measurement": "unavailable"}
        return {"violating_paths": m[cls]["path_counts"]["violating"],
                "wns_ns": m[cls]["wns_ns"], "tns_ns": m[cls]["tns_ns"]}

    results = {
        "wave_committed": {"value": committed, "unit": "bool"},
        "setup_before": _snap(before, "setup"),
        "setup_after": _snap(after, "setup"),
        "hold_before": _snap(before, "hold"),
        "hold_after": _snap(after, "hold"),
        "churn": churn or {"measurement": "unavailable"},
    }

    # Detect-only classes are reported as explicitly unavailable. OpenROAD has
    # no repair engine for them, and a silent 0 here would be a false clean.
    detect_only = {c: {"measurement": "unavailable",
                       "reason": "no repair engine exists in OpenROAD for this "
                                 "check class; ECO can DETECT but not fix it"}
                   for c in DETECT_ONLY_CLASSES}

    committed_def = outs["def"] if committed else ckpt_def
    single_vt, single_vt_basis = _is_single_vt(binding, paths["liberty"])

    qor = {
        "wave_index": wave,
        "wave_committed": committed,
        "wave_closed": wave_closed,
        "repair_tns": params.get("repair_tns"),
        "aggression": params.get("aggression", "conservative"),
        "target_instance_count": len(_as_list(params.get("target_instances"))),
        "runtime_s": runtime,
    }
    if after:
        qor["wns_ns"] = after["setup"]["wns_ns"]
        qor["tns_ns"] = after["setup"]["tns_ns"]
        qor["violating_paths"] = (after["setup"]["path_counts"]["violating"]
                                  + after["hold"]["path_counts"]["violating"])
        for _k in ("drv_violators", "route_drc"):
            if after.get(_k) is not None:
                qor[_k] = after[_k]
    if churn and churn.get("ratio") is not None:
        qor["churn_ratio"] = churn["ratio"]

    # Evidence paths are BASENAMES, matching every other physical tool in the
    # catalog. `save_final_results` calls `_organize_output`, which moves files
    # into results/ reports/ logs/ AFTER the envelope is written -- so an
    # absolute path recorded here would be stale the moment it is read.
    def _ref(p):
        return os.path.basename(p) if p else None

    # Grid connectivity reports the RESULT of the check, never the intent to
    # run it. A hard-coded "re-verified" string would be absence-of-evidence
    # dressed as evidence, which the downstream review agent would read as a
    # genuine check.
    _grid = (after or {}).get("grid_errors")
    if not params.get("repair_pdn_vias", True):
        grid_connectivity = {"measurement": "not_checked",
                             "reason": "repair_pdn_vias disabled for this wave"}
    elif not _grid:
        grid_connectivity = {"measurement": "unavailable",
                             "reason": "the wave produced no power-grid report"}
    else:
        grid_connectivity = {
            net: ({"measurement": "unavailable"} if err is None
                  else {"errors": err, "clean": err == 0})
            for net, err in _grid.items()}

    signoff = {
        "eco_def": _ref(committed_def),
        "eco_netlist": _ref(outs["netlist"]) if committed else None,
        "eco_spef": (_ref(outs["spef"])
                     if (committed and os.path.isfile(outs["spef"])) else None),
        "sta_report": _ref(outs["sta_report"]) if engine_ok else None,
        "drv_report": _ref(outs.get("drv_report")) if engine_ok else None,
        "route_drc_report": _ref(outs.get("route_drc")) if engine_ok else None,
        "clock_skew_report": (_ref(outs.get("skew_report"))
                              if engine_ok else None),
        # Clock-tree balance is judged on |skew|. It is NOT a timing check:
        # measured on crc16_ccitt, setup skew rose 0.06 -> 0.21 ns while setup
        # slack IMPROVED 10.37 -> 10.51, so skew and slack can move in
        # opposite directions. This class answers only "is the tree still as
        # balanced as CTS made it".
        "clock_skew_basis": (
            "|skew| per clock per check type from report_clock_skew; larger "
            "magnitude = less balanced than CTS built it. Not a proxy for "
            "slack -- the two can move in opposite directions."
            if engine_ok else None),
        "rollback_checkpoint": _ref(ckpt_def),
        "rolled_back": not committed,
        # On rollback the mutated artifacts are quarantined with a `.rejected`
        # suffix so no downstream glob can pick them up.
        "quarantined_artifacts": ([] if committed else
                                  [_ref(outs[k]) + ".rejected"
                                   for k in ("def", "netlist", "spef")
                                   if outs.get(k)]),
        "parasitic_basis": outs.get("parasitic_basis"),
        # The per-class comparison the commit decision was actually taken on.
        # A reviewer can see WHICH class carried the wave -- a DRV-only fix is
        # a legitimate commit here, so "which class improved" is no longer
        # inferable from the timing numbers alone.
        "class_deltas": deltas,
        "improved_classes": ([d["class"] for d in (deltas or [])
                              if d["status"] == "improved"] or None),
        "regressed_classes": ([d["class"] for d in (deltas or [])
                               if d["status"] == "regressed"] or None),
        "unmeasured_classes": ([d["class"] for d in (deltas or [])
                                if d["status"] == "not_measured"] or None),
        "judgement_gaps": (_gaps or None),
        "baseline_drv_report": _ref(baseline_drv) if baseline_drv else None,
        "baseline_clock_skew_report": (_ref(baseline_skew)
                                       if baseline_skew else None),
        "baseline_route_drc_report": (_ref(baseline_drc) if baseline_drc
                                      else None),
        "commit_rule": (
            "committed when at least one measured class strictly improved and "
            "none regressed; improvement is NOT restricted to timing, so a "
            "DRV-only or routing-DRC-only fix is committable"),
        "fix_ledger": [{"wave": wave,
                        "repair_class": c, "command": cmd_line,
                        "scoped_to": _as_list(params.get("target_instances"))}
                       for c, cmd_line in cmds],
        "repair_commands": [c for _cls, c in cmds],
        # Agent-directed swaps, each carrying the PROOF that let it run: the
        # cell it came from and the equivalence set membership was checked
        # against. Empty when the wave requested no swaps.
        "cell_swaps": ([{"instance": i, "from_cell": v["from"],
                         "to_cell": v["to"],
                         "equivalence_verified": True,
                         "equivalent_cells": v["equivalents"]}
                        for i, v in sorted(swap_info.items())] or None),
        "cell_swap_basis": (
            "each swap was proven a member of the current cell's "
            "report_equiv_cells set in a read-only pass BEFORE any mutation; "
            "the target cell is agent-supplied because report_equiv_cells "
            "carries only area and leakage, not drive strength"
            if swap_info else None),
        "swap_validation_log": (_ref(os.path.join(
            _OUTPUT_DIR, "eco_wave_%d_swap_probe.log" % wave))
            if swap_info else None),
        # Buffer insertions, each carrying WHY it was allowed: the net's
        # classification, which independent signal(s) established it, and
        # whether the clock-buffer rule applied.
        "buffer_insertions": (buf_info or None),
        "buffer_clock_rule": (
            "a buffer on a clock net must come from the clock-buffer list; "
            "clock-ness is the union of the OpenDB signal type and OpenSTA "
            "clock propagation, so a DEF that does not annotate clock nets is "
            "still classified correctly"
            if buf_info else None),
        "clock_buffer_cells": (sorted(clock_cells) or None) if bufs else None,
        "buffer_validation_log": (_ref(os.path.join(
            _OUTPUT_DIR, "eco_wave_%d_buffer_probe.log" % wave))
            if buf_info else None),
        "aggression_level": params.get("aggression", "conservative"),
        "skip_flags": AGGRESSION_LEVELS[params.get("aggression", "conservative")],
        "allow_setup_violations": False,
        "grid_connectivity": grid_connectivity,
        "wave_closed": wave_closed,
        "detect_only_classes": detect_only,
        "ordering_doctrine": [c for c, _ in cmds],
        "doctrine_deviation": params.get("doctrine_deviation_justification"),
        "baseline_sta_report": _ref(baseline),
        "log": _ref(log_path),
    }

    # Rollback, partial improvement and missing checks cannot close the wave.
    if not engine_ok:
        validation = {"verdict": "fail", "note": note}
        status = "failed"
    else:
        validation = {"verdict": "pass" if wave_closed else "pass_with_caveats",
                      "note": note}
        status = "completed"

    assumptions = [
        "One wave per invocation: the fix-set, batch breadth and aggression "
        "level for the NEXT wave are the reasoning agent's decision.",
        "A regressing or non-improving wave is rolled back: `eco_def` points at "
        "the pre-wave checkpoint and the mutated artifacts are quarantined with "
        "a `.rejected` suffix, so the convergence trace stays monotone and "
        "'plateau' remains a trustworthy signal.",
        "The wave verdict covers setup, hold, DRV, routing DRC and power-grid "
        "connectivity. A class whose report is absent is recorded as "
        "`unavailable` and NEVER treated as clean.",
        "-allow_setup_violations is never passed, so OpenROAD's own refusal to "
        "insert setup-breaking hold buffers acts as a guard beneath rollback.",
        "Metal fill is NOT re-inserted here; the downstream post-ECO metal-fill "
        "stage owns that, and DRC/LVS/antenna consume its filled layout.",
        # An honest statement of what "incremental" does and does not mean here.
        "Global routing is incremental (bracketed around the repair, so only "
        "modified nets are re-routed), but OpenROAD's detailed_route has no "
        "incremental mode -- each wave performs a full detailed route. Wave "
        "runtime is therefore dominated by detailed routing, not by the repair.",
        "`tns_ns` is the sum over the paths PRESENT IN THE REPORT TEXT, not "
        "design TNS. The before/after comparison is only sound if the baseline "
        "report was generated with the same corner and path-count settings as "
        "this wave's; that is outside this tool's control and is not verified "
        "here.",
    ]
    if single_vt:
        assumptions.append(
            "The bound library is single-Vt (basis: %s), so every VT-swap move "
            "in OpenROAD's default -sequence is a no-op; the real repertoire is "
            "size up/down, buffer/rebuffer, unbuffer, clone, pin swap and "
            "load split." % single_vt_basis)
    elif single_vt is False:
        assumptions.append(
            "The bound node has MORE THAN ONE Vt flavour (basis: %s), so VT "
            "swap is a REAL transform here and is left in the repair "
            "repertoire. Suppressing it would under-repair." % single_vt_basis)
    else:
        # Neither the binding nor the library name settled it. Say so rather
        # than letting the absence read as "multi-Vt, VT swap works" -- an
        # unverified repertoire claim is how a wave promises a recovery class
        # that does nothing.
        assumptions.append(
            "Vt flavour count is UNDETERMINED (%s): the binding carries no "
            "capabilities.vt_swap and the bound Liberty is not a known "
            "single-Vt library. VT-swap effectiveness on this node is "
            "unverified -- do not claim VT-swap recovery without confirming it."
            % single_vt_basis)

    return _cde(
        obj, status, results=results, qor=qor, signoff=signoff,
        assumptions=assumptions,
        inputs_ref={k: v for k, v in paths.items() if isinstance(v, str) and v},
        margin={"method": "wave_rollback_guard",
                "setup_margin_ns": params.get("setup_margin_ns"),
                "hold_margin_ns": params.get("hold_margin_ns")},
        validation=validation,
        pdk_binding=params.get("pdk_binding") or "none",
        provenance={"openroad": _tool_version(orbin), "runtime_s": runtime,
                    "log": log_path, "script": tcl_path,
                    "returncode": proc.returncode},
    )


def dispatch(params):
    if not isinstance(params, dict):
        return _fail("eco dispatch", "params must be a JSON object")
    s = params.get("scenario")
    if s == "analyze_violations":
        return _handle_analyze_violations(params)
    if s == "eco_wave":
        return _handle_eco_wave(params)
    return _fail("eco dispatch",
                 "unknown scenario %r; expected analyze_violations or eco_wave"
                 % s, params)
