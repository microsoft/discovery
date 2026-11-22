#!/usr/bin/env python3
"""Physical-integrity evidence aggregator and deterministic OpenROAD checks."""
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time

TOOL = "physical-integrity-checker"
OUTPUT = "/output"
WORK = "/workdir"
CHECKS = (
    "disconnected_pins", "long_wires", "netlist_assigns", "unmapped_cells",
    "routing_drc", "setup_violations", "hold_violations",
    "max_slew_violations", "max_cap_violations", "pdn_violations",
    "pdn_disconnected", "missing_welltaps", "illegal_overlaps",
)
ALIASES = {
    "disconnected_pins": ("disconnected_pins", "floating_pins", "unconnected_pins"),
    "long_wires": ("long_wires", "long_wire_count"),
    "netlist_assigns": ("netlist_assigns", "assign_statements"),
    "unmapped_cells": ("unmapped_cells", "unmapped_cell_count"),
    "routing_drc": ("routing_drc", "drc_violations", "route_drc_count"),
    "setup_violations": ("setup_violations", "setup_count"),
    "hold_violations": ("hold_violations", "hold_count"),
    "max_slew_violations": ("max_slew_violations", "slew_violations"),
    "max_cap_violations": ("max_cap_violations", "capacitance_violations"),
    "pdn_violations": ("pdn_violations", "pdn_check_violations"),
    "pdn_disconnected": ("pdn_disconnected", "pdn_via_gap", "pdn_connectivity_violations"),
    "missing_welltaps": ("missing_welltaps", "missing_tapcells", "welltap_missing", "tapcell_missing"),
    "illegal_overlaps": ("illegal_overlaps", "placement_violations", "overlap_count"),
}


def quick_setup(output_dir="/output", work_dir="/workdir"):
    global OUTPUT, WORK
    OUTPUT = os.environ.get("CHIP_OUTPUT_DIR", output_dir)
    WORK = os.environ.get("CHIP_WORK_DIR", work_dir)
    os.makedirs(OUTPUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    for name in ("results", "reports", "logs"):
        os.makedirs(os.path.join(OUTPUT, name), exist_ok=True)


def _version(executable, argument="-version"):
    path = shutil.which(executable)
    if not path:
        return "unavailable"
    try:
        proc = subprocess.run([path, argument], text=True, capture_output=True, timeout=20)
        text = (proc.stdout + proc.stderr).strip().splitlines()
        return text[0] if text else executable
    except Exception:
        return executable


def _sha(path):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"sha256": digest.hexdigest(), "bytes": os.path.getsize(path)}
    except OSError:
        return None


def _walk_paths(value, found):
    if isinstance(value, str) and os.path.isfile(value):
        found[os.path.abspath(value)] = _sha(value)
    elif isinstance(value, dict):
        for item in value.values():
            _walk_paths(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk_paths(item, found)


def _envelope(objective, status, binding, inputs, checks=None, validation=None,
              provenance=None, error=None):
    checks = checks or []
    critical = sum(int(c.get("count") or 0) for c in checks
                   if c.get("verdict") == "fail")
    result = {
        "tool": TOOL,
        "status": status,
        "objective": objective,
        "tools_used": [{"name": "OpenROAD/OpenDB", "version": _version("openroad")}],
        "pdk_binding": binding or "none",
        "assumptions": [],
        "inputs_ref": inputs or {},
        "vplan": {"required_checks": [c["check"] for c in checks if c.get("required")]},
        "results": {"checks": checks, "total_critical_violations": critical},
        "qor_metrics": {"total_critical_violations": critical,
                        "checks_assessed": sum(c["verdict"] != "not_assessable" for c in checks)},
        "signoff_evidence": {"per_check_verdicts": checks,
                             "total_critical_violations": critical},
        "margin": {"method": "zero_violation_required"},
        "validation": validation or {"verdict": "fail"},
        "provenance": provenance or {},
    }
    if error:
        result["signoff_evidence"]["failure_reason"] = error
    return result


def failure_envelope(objective, error, params=None, trace=None):
    result = _envelope(objective, "failed", (params or {}).get("pdk_binding"),
                       params or {}, validation={"verdict": "fail", "note": error},
                       error=error)
    result["error"] = str(error)
    if trace:
        result["provenance"]["traceback"] = trace
    return result


def _resolve(params, policy, name, default):
    if name in params:
        source = "caller_override" if name in policy and params[name] != policy[name] else "caller"
        return params[name], source
    if name in policy:
        return policy[name], "pdk_policy"
    return default, "tool_default"


def _existing(value):
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if item and os.path.exists(str(item))]


def _numeric(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        value = value.get("count", value.get("value"))
        if isinstance(value, (int, float)):
            return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value)
    return None


def _metric(metrics, check):
    for alias in ALIASES[check]:
        if alias in metrics:
            count = _numeric(metrics[alias])
            if count is not None:
                return count, "structured_metric:" + alias
    return None, None


def _report_count(path, check):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    aliases = "|".join(re.escape(x.replace("_", r"[ _-]*")) for x in ALIASES[check])
    matches = re.findall(r"(?im)(?:" + aliases + r")[^\n\d]{0,80}(\d+)", text)
    if matches:
        return sum(int(x) for x in matches)
    if re.search(r"(?im)\b(?:no|zero)\s+(?:violations?|errors?|unconnected|unmapped|overlaps?)\b", text):
        return 0
    if check in ("setup_violations", "hold_violations"):
        match = re.search(r"(?im)^\s*violator count\s*[:=]\s*(\d+)", text)
        if match:
            return int(match.group(1))
    return None


def _netlist_checks(path, known_cells):
    text = open(path, encoding="utf-8", errors="replace").read()
    text = re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)
    assigns = len(re.findall(r"\bassign\b", text))
    primitives = {"module", "endmodule", "input", "output", "inout", "wire", "reg",
                  "logic", "assign", "always", "initial", "generate", "endgenerate"}
    instantiated = set(re.findall(r"(?:^|;)\s*([A-Za-z_$][\w$]*)\s+(?:#\s*\([^;]*?\)\s*)?[A-Za-z_$][\w$]*\s*\(", text))
    modules = set(re.findall(r"\bmodule\s+([A-Za-z_$][\w$]*)", text))
    candidates = instantiated - modules - primitives
    unmapped = sorted(candidates - known_cells) if known_cells else None
    return assigns, unmapped


def _liberty_cells(paths):
    cells = set()
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as stream:
            text = stream.read()
        cells.update(quoted or bare for quoted, bare in re.findall(
            r'\bcell\s*\(\s*(?:"([^"]+)"|([^\s()"]+))\s*\)', text))
    return cells


def _pdn_via_stats(def_path):
    """Count via instances and stripe layers in the SPECIALNETS section of a DEF.
    A grid with >=2 PDN stripe layers but 0 SPECIALNETS vias is electrically
    disconnected (the root of PSM-0069). Returns (via_count, stripe_layers) or
    (None, []) when the DEF cannot be read."""
    vias = 0
    layers = set()
    try:
        in_sn = False
        with open(def_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("SPECIALNETS"):
                    in_sn = True
                    continue
                if s.startswith("END SPECIALNETS"):
                    break
                if not in_sn:
                    continue
                vias += line.count("+ VIA ")
                for lyr in re.findall(r"(?:ROUTED|NEW)\s+(met\d+|metal\d+|m\d+)", line):
                    layers.add(lyr)
    except OSError:
        return None, []
    return vias, sorted(layers)


def _welltap_stats(def_path):
    """Count total placed COMPONENTS and well-tap cells in a DEF. A placed design
    with many standard cells but ZERO tap cells has no well/substrate ties, which
    drives LVS floating-well mismatches and DRC latch-up/nwell-tap violations
    (the DX-41 root cause). Tap cells are matched node-agnostically by the 'tap'
    substring in the component master name (sky130: *__tapvpwrvgnd*, generally
    *tap*/*welltap*). Returns (total_components, tapcells) or (None, None) when
    the DEF cannot be read."""
    total = 0
    taps = 0
    try:
        in_comp = False
        with open(def_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("COMPONENTS"):
                    in_comp = True
                    continue
                if s.startswith("END COMPONENTS"):
                    break
                if not in_comp or not s.startswith("- "):
                    continue
                parts = s.split()
                if len(parts) < 3:
                    continue
                master = parts[2]
                total += 1
                if re.search(r"(?i)(?:^|_)tap|welltap|tapvpwrvgnd", master):
                    taps += 1
    except OSError:
        return None, None
    return total, taps


def _openroad_checks(params, binding, threshold):
    db = params.get("odb") or params.get("db")
    deffile = params.get("def_file") or params.get("def")
    if not db and not deffile:
        return {}, None
    if not shutil.which("openroad"):
        return {}, "openroad not found on PATH"
    if db and not os.path.exists(str(db)):
        return {}, "ODB not found: " + str(db)
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = params.get("cell_lef") or binding.get("cell_lef") or []
    cell_lefs = cell_lefs if isinstance(cell_lefs, list) else [cell_lefs]
    if deffile:
        if not os.path.exists(str(deffile)):
            return {}, "DEF not found: " + str(deffile)
        if not tech_lef or not os.path.exists(str(tech_lef)):
            return {}, "DEF input requires existing PDK tech_lef"
        if not cell_lefs or any(not os.path.exists(str(x)) for x in cell_lefs):
            return {}, "DEF input requires existing PDK cell_lef references"
    metrics_path = os.path.join(WORK, "openroad_integrity_metrics.txt")
    load = "read_db " + _tcl(db) if db else "\n".join(
        ["read_lef " + _tcl(tech_lef)] +
        ["read_lef -library " + _tcl(x) for x in cell_lefs] +
        ["read_def " + _tcl(deffile)])
    script = load + r'''
set block [ord::get_db_block]
set disconnected 0
set long_wires 0
set long_wires_assessable 1
set overlaps 0
foreach inst [$block getInsts] {
    foreach iterm [$inst getITerms] { if {![$iterm isConnected]} {incr disconnected} }
}
foreach bterm [$block getBTerms] {
    set net [$bterm getNet]
    if {[llength [$bterm getBPins]] == 0 || $net eq "NULL"} {
        incr disconnected
    } elseif {[llength [$net getITerms]] == 0} {
        incr disconnected
    }
}
foreach net [$block getNets] {
  set wire [$net getWire]
  if {$wire ne "NULL"} {
    if {[catch {$wire getLength} len]} {
      set long_wires_assessable 0
      puts "Wire length not assessable: $len"
    } elseif {$len > $long_limit_dbu} {
      incr long_wires
    }
  }
}
set insts [$block getInsts]
for {set i 0} {$i < [llength $insts]} {incr i} {
  set a [lindex $insts $i]
  set ab [$a getBBox]
  for {set j [expr {$i+1}]} {$j < [llength $insts]} {incr j} {
    set b [lindex $insts $j]
    set bb [$b getBBox]
    if {[$ab xMin] < [$bb xMax] && [$ab xMax] > [$bb xMin] && [$ab yMin] < [$bb yMax] && [$ab yMax] > [$bb yMin]} {incr overlaps}
  }
}
set fp [open $metrics_file w]
puts $fp "disconnected_pins=$disconnected"
if {$long_wires_assessable} { puts $fp "long_wires=$long_wires" }
puts $fp "illegal_overlaps=$overlaps"
close $fp
catch {check_placement -verbose} placement_message
puts $placement_message
'''
    # Convert microns to database units inside Tcl after loading the DB.
    script = script.replace("set block [ord::get_db_block]",
        "set block [ord::get_db_block]\nset dbu [$block getDbUnitsPerMicron]\nset long_limit_dbu [expr {" + str(float(threshold)) + " * $dbu}]")
    script = "set metrics_file " + _tcl(metrics_path) + "\n" + script
    tcl = os.path.join(WORK, "physical_integrity.tcl")
    open(tcl, "w", encoding="utf-8").write(script)
    command = ["openroad", "-exit", "-no_init", tcl]
    open(os.path.join(OUTPUT, "logs", "run_command.txt"), "w", encoding="utf-8").write(
        " ".join(shlex.quote(x) for x in command) + "\n")
    if os.path.exists(metrics_path):
        os.unlink(metrics_path)
    proc = subprocess.run(command, text=True, capture_output=True, cwd=WORK)
    log = proc.stdout + "\n" + proc.stderr
    open(os.path.join(OUTPUT, "logs", "openroad_integrity.log"), "w", encoding="utf-8").write(log)
    shutil.copy2(tcl, os.path.join(OUTPUT, "logs", "physical_integrity.tcl"))
    if not os.path.exists(metrics_path):
        return {}, "OpenROAD integrity Tcl failed; see logs/openroad_integrity.log: " + log[-2000:]
    values = {}
    for line in open(metrics_path, encoding="utf-8"):
        if "=" in line:
            key, value = line.strip().split("=", 1)
            values[key] = int(value)
    engine_error = None
    if proc.returncode != 0:
        engine_error = ("OpenROAD exited with code " + str(proc.returncode) +
                        " after writing native measurements; see logs/openroad_integrity.log: " +
                        log[-2000:])
    return values, engine_error


def _tcl(value):
    return "{" + str(value).replace("}", "\\}") + "}"


def _integrity(params):
    started = time.time()
    binding = params.get("pdk_binding")
    if not isinstance(binding, dict) or not binding:
        return failure_envelope("Physical integrity check", "missing required pdk_binding", params)
    policy = ((binding.get("tool_policy") or {}).get("physical_integrity") or {})
    threshold, threshold_source = _resolve(params, policy, "long_wire_threshold_um", 500.0)
    required, required_source = _resolve(params, policy, "required_checks", list(CHECKS))
    required = required if isinstance(required, list) else [required]
    unknown = sorted(set(required) - set(CHECKS))
    if unknown:
        return failure_envelope("Physical integrity check", "unknown required checks: " + ", ".join(unknown), params)
    metrics = params.get("metrics") or {}
    reports = params.get("reports") or {}
    if not isinstance(metrics, dict) or not isinstance(reports, dict):
        return failure_envelope("Physical integrity check", "metrics and reports must be objects", params)
    deterministic, engine_error = _openroad_checks(params, binding, threshold)
    # Deterministic PDN via-connectivity check straight from the DEF SPECIALNETS.
    # PDN stripes with zero connecting vias => layers isolated => PSM-0069 class
    # failure. This is the check that would have caught DX-94 at signoff.
    _deffile = params.get("def_file") or params.get("def")
    if _deffile and os.path.exists(str(_deffile)):
        _sn_vias, _stripe_layers = _pdn_via_stats(str(_deffile))
        if _sn_vias is not None and len(_stripe_layers) >= 2:
            deterministic["pdn_disconnected"] = 1 if _sn_vias == 0 else 0
            open(os.path.join(OUTPUT, "reports", "pdn_connectivity.rpt"), "w",
                 encoding="utf-8").write(
                f"specialnets_vias={_sn_vias}\n"
                f"stripe_layers={','.join(_stripe_layers)}\n"
                f"pdn_disconnected={1 if _sn_vias == 0 else 0}\n")
        # Deterministic well-tap presence check. A placed design (>=20 std cells)
        # with ZERO tap cells has no well/substrate ties -> LVS floating wells +
        # DRC latch-up/nwell-tap. This is the check that would have caught DX-41
        # one stage before LVS/DRC surfaced it.
        _tot_comp, _taps = _welltap_stats(str(_deffile))
        if _tot_comp is not None and _tot_comp >= 20:
            deterministic["missing_welltaps"] = 1 if _taps == 0 else 0
            open(os.path.join(OUTPUT, "reports", "welltap_presence.rpt"), "w",
                 encoding="utf-8").write(
                f"total_components={_tot_comp}\n"
                f"tapcells={_taps}\n"
                f"missing_welltaps={1 if _taps == 0 else 0}\n")
    netlist = params.get("netlist")
    if netlist:
        if not os.path.exists(str(netlist)):
            return failure_envelope("Physical integrity check", "netlist not found: " + str(netlist), params)
        liberty = params.get("liberty") or binding.get("liberty") or []
        liberty = liberty if isinstance(liberty, list) else [liberty]
        known = _liberty_cells(_existing(liberty))
        assigns, unmapped = _netlist_checks(netlist, known)
        deterministic["netlist_assigns"] = assigns
        if unmapped is not None:
            deterministic["unmapped_cells"] = len(unmapped)
            open(os.path.join(OUTPUT, "reports", "unmapped_cells.rpt"), "w", encoding="utf-8").write("\n".join(unmapped) + ("\n" if unmapped else ""))
    checks = []
    for check in CHECKS:
        count = None
        source = None
        if check in deterministic:
            count, source = deterministic[check], "deterministic_engine"
        if count is None:
            count, source = _metric(metrics, check)
        if count is None:
            report = reports.get(check)
            if report and os.path.exists(str(report)):
                count, source = _report_count(str(report), check), "report:" + str(report)
        is_required = check in required
        verdict = "not_assessable" if count is None else ("pass" if count == 0 else "fail")
        checks.append({"check": check, "required": is_required, "verdict": verdict,
                       "count": count, "evidence": source or "missing"})
    missing = [c["check"] for c in checks if c["required"] and c["verdict"] == "not_assessable"]
    failed = [c for c in checks if c["required"] and c["verdict"] == "fail"]
    if engine_error and (params.get("odb") or params.get("def_file") or params.get("def")):
        missing_note = engine_error
    else:
        missing_note = None
    if failed:
        status, verdict, note = "failed", "fail", "one or more required checks reported violations"
    elif missing or missing_note:
        status, verdict = "failed", "not_assessable"
        note = missing_note or ("required evidence missing for: " + ", ".join(missing))
    else:
        status, verdict, note = "completed", "pass", "all required checks are evidenced and clean"
    provenance = {
        "started_utc": datetime.datetime.fromtimestamp(started, datetime.timezone.utc).isoformat(),
        "runtime_s": round(time.time() - started, 3),
        "settings_source": {"long_wire_threshold_um": threshold_source,
                            "required_checks": required_source},
        "effective_settings": {"long_wire_threshold_um": threshold,
                               "required_checks": required},
    }
    result = _envelope("Aggregate and verify physical integrity", status, binding,
                       {k: params.get(k) for k in ("odb", "def_file", "netlist", "reports") if params.get(k)},
                       checks, {"verdict": verdict, "note": note}, provenance,
                       None if status == "completed" else note)
    result["signoff_evidence"]["engine_error"] = engine_error
    result["signoff_evidence"]["settings_source"] = provenance["settings_source"]
    return result


def save_final_results(result):
    hashes = {}
    _walk_paths(result.get("inputs_ref"), hashes)
    _walk_paths({"output": OUTPUT}, hashes)
    result.setdefault("provenance", {})["input_hashes"] = {
        path: value for path, value in hashes.items() if value and not path.startswith(os.path.abspath(OUTPUT))}
    result["provenance"]["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    checks_path = os.path.join(OUTPUT, "results", "per_check_verdicts.json")
    with open(checks_path, "w", encoding="utf-8") as stream:
        json.dump(result.get("results", {}).get("checks", []), stream, indent=2)
    summary = ["# Physical integrity summary", "", "- Status: **" + result.get("status", "unknown") + "**",
               "- Verdict: **" + str(result.get("validation", {}).get("verdict", "unknown")) + "**",
               "- Critical violations: **" + str(result.get("results", {}).get("total_critical_violations", 0)) + "**", "",
               "| Check | Required | Verdict | Count | Evidence |", "|---|---:|---|---:|---|"]
    for check in result.get("results", {}).get("checks", []):
        summary.append("| {check} | {required} | {verdict} | {count} | {evidence} |".format(**check))
    open(os.path.join(OUTPUT, "SUMMARY.md"), "w", encoding="utf-8").write("\n".join(summary) + "\n")
    open(os.path.join(OUTPUT, "reports", "REPORT.md"), "w", encoding="utf-8").write("\n".join(summary) + "\n")
    with open(os.path.join(OUTPUT, "common_design_envelope.json"), "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    output_hashes = {}
    for root, _, files in os.walk(OUTPUT):
        for name in files:
            path = os.path.join(root, name)
            if name != "common_design_envelope.json":
                output_hashes[os.path.relpath(path, OUTPUT).replace(os.sep, "/")] = _sha(path)
    result["provenance"]["output_hashes"] = output_hashes
    with open(os.path.join(OUTPUT, "common_design_envelope.json"), "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)


def dispatch(params):
    if params.get("scenario") == "integrity_check":
        return _integrity(params)
    return failure_envelope("Physical integrity check",
                            "unknown scenario {!r}; supported: integrity_check".format(params.get("scenario")), params)


# --- shared CDE stack (migrate_shared_envelope.py) -------------------------
# _SHARED_ENVELOPE_WRAPPED_V1 template=78fcd5727179
# This tool builds its envelope by hand rather than through the shared
# `_finalize_envelope`. The wrapper below closes that gap WITHOUT rewriting the
# hand-rolled construction: it runs once, at dispatch exit, after every
# post-construction mutation (`error`, `signoff_evidence.engine_error`,
# `provenance.traceback`) has already been applied. Stamping at the envelope
# helper instead would snapshot a dict that is then edited underneath it.
#
# Everything here is setdefault-based and non-fatal: the tool's own richer
# values always win, and envelope bookkeeping must never fail a design run.
_CDE_REQUIRED_FIELDS = ('tool', 'status', 'objective', 'tools_used', 'pdk_binding', 'assumptions', 'inputs_ref', 'vplan', 'results', 'qor_metrics', 'signoff_evidence', 'margin', 'validation', 'provenance')

# NOTE: single braces. This template is expanded with str.replace(), NOT
# str.format(), so doubled braces would emit literally -- and `{{...}}` is a SET
# containing a dict, which imports cleanly past py_compile and then dies with
# "unhashable type: 'dict'" at module load. That failure mode was hit here once.
_EMPTY_DEFAULTS = {
    "tools_used": [], "assumptions": [], "qor_metrics": {},
    "signoff_evidence": {}, "inputs_ref": {}, "margin": {},
    "vplan": "shared_artifact", "pdk_binding": "none",
}


def _finalize_envelope(results):
    """Typed-empty defaults + provenance + progress + runtime. Never raises."""
    if not isinstance(results, dict):
        return results
    try:
        _defaulted = []
        for _k, _dv in _EMPTY_DEFAULTS.items():
            if _k not in results:
                results[_k] = list(_dv) if isinstance(_dv, list) else \
                    (dict(_dv) if isinstance(_dv, dict) else _dv)
                _defaulted.append(_k)
        _missing = [k for k in _CDE_REQUIRED_FIELDS if k not in results]
        _warns = results.get("envelope_warnings")
        if not isinstance(_warns, list):
            _warns = []
        if _defaulted:
            _warns.append("CDE auto-defaulted empty required field(s): "
                          + ", ".join(sorted(_defaulted)))
        if _missing:
            _warns.append("CDE missing required field(s): " + ", ".join(_missing))
        if _warns:
            results["envelope_warnings"] = _warns
    except Exception as _e:
        print("[" + str(TOOL) + "] CDE self-check skipped: " + str(_e), flush=True)
    try:
        import datetime as _dt
        _prov = results.get("provenance")
        if not isinstance(_prov, dict):
            _prov = {} if _prov in (None, "") else {"note": str(_prov)}
        _prov.setdefault(
            "finished_utc",
            _dt.datetime.now(_dt.timezone.utc).isoformat())
        # Always record the input-hash key even when empty, so the audit chain
        # is an explicit empty rather than a silent gap. These tools already
        # hash their own inputs on the success paths; setdefault preserves that.
        _prov.setdefault("input_hashes", {})
        results["provenance"] = _prov
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
# --- end shared CDE stack --------------------------------------------------


# --- dispatch finalization (migrate_shared_envelope.py) --------------------
_dispatch_unfinalized = dispatch


def dispatch(params):          # noqa: F811  (intentional wrap)
    """Run the tool, then stamp the shared envelope contract on the result."""
    return _finalize_envelope(_dispatch_unfinalized(params))
# --- end dispatch finalization ---------------------------------------------


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
