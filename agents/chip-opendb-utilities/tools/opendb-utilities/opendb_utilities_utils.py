#!/usr/bin/env python3
"""Real OpenROAD/OpenDB utility execution with fail-closed CDE output."""
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time

TOOL = "opendb-utilities"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
CDE_FIELDS = (
    "tool", "status", "objective", "tools_used", "pdk_binding", "assumptions",
    "inputs_ref", "vplan", "results", "qor_metrics", "signoff_evidence",
    "margin", "validation", "provenance",
)
SCENARIOS = (
    "convert_def_to_odb", "convert_odb_to_def", "apply_def_template",
    "manage_obstructions", "manual_macro_placement", "custom_io_placement",
    "insert_tap_endcap_decap", "insert_port_diodes", "set_power_connections",
    "report_disconnected_pins", "report_wire_length", "report_cell_usage",
    "check_macro_instances", "check_antenna_properties", "write_views",
)


def quick_setup(output_dir="/output", work_dir="/workdir"):
    global OUTPUT_DIR, WORK_DIR
    OUTPUT_DIR = os.environ.get("CHIP_OUTPUT_DIR") or os.environ.get("OUTPUT_DIR") or output_dir
    WORK_DIR = os.environ.get("CHIP_WORK_DIR") or os.environ.get("WORK_DIR") or work_dir
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)


def _sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "bytes": os.path.getsize(path)}


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _tcl(value):
    text = str(value)
    if "\x00" in text or "\n" in text or "\r" in text or "}" in text:
        raise ValueError(f"unsafe Tcl value: {text!r}")
    return "{" + text + "}"


def _bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _policy(params):
    binding = params.get("pdk_binding")
    if not isinstance(binding, dict) or not binding:
        raise ValueError("pdk_binding is required and must be a non-empty object")
    policy = binding.get("tool_policy") or {}
    stage = (binding.get("tool_policy") or {}).get("opendb_utilities") or {}
    if stage is not None and not isinstance(stage, dict):
        raise ValueError("pdk_binding.tool_policy.opendb_utilities must be an object")
    return binding, stage or {}


def _resolve(params, binding, policy, name, default=None, aliases=()):
    keys = (name,) + tuple(aliases)
    explicit = next((params[k] for k in keys if k in params and params[k] is not None), None)
    recommended = next((policy[k] for k in keys if k in policy and policy[k] is not None), None)
    bound = next((binding[k] for k in keys if k in binding and binding[k] is not None), None)
    if explicit is not None:
        caveat = None
        if recommended is not None and explicit != recommended:
            caveat = f"explicit '{name}' overrides tool_policy recommendation"
        return explicit, "explicit_parameter", caveat
    if recommended is not None:
        return recommended, "tool_policy.opendb_utilities", None
    if bound is not None:
        return bound, "pdk_binding", None
    return default, "tool_default", None


def _base_envelope(objective, status, binding, params, results=None, evidence=None,
                   validation=None, assumptions=None, provenance=None):
    return {
        "tool": TOOL,
        "status": status,
        "objective": objective,
        "tools_used": [{"name": "OpenROAD/OpenDB", "version": "captured in provenance"}],
        "pdk_binding": binding if binding else "missing",
        "assumptions": assumptions or [],
        "inputs_ref": {k: v for k, v in params.items() if k.endswith("_file") or k in
                       ("def_file", "odb_file", "tech_lef", "cell_lef", "liberty", "sdc")},
        "vplan": "not_applicable",
        "results": results or {},
        "qor_metrics": {},
        "signoff_evidence": evidence or {},
        "margin": {"method": "not_applicable", "value": "not_applicable"},
        "validation": validation or {"verdict": "not_assessable"},
        "provenance": provenance or {},
    }


def failed_envelope(scenario, error, params=None, trace=None):
    params = params if isinstance(params, dict) else {}
    binding = params.get("pdk_binding") if isinstance(params.get("pdk_binding"), dict) else None
    envelope = _base_envelope(
        f"OpenDB utility scenario {scenario}", "failed", binding, params,
        results={"error": str(error)},
        validation={"verdict": "fail", "note": str(error)},
        provenance={"finished_utc": datetime.now(timezone.utc).isoformat(),
                    "traceback": trace} if trace else
                   {"finished_utc": datetime.now(timezone.utc).isoformat()},
    )
    envelope["error"] = str(error)
    return envelope


def _render_summary(env):
    validation = env.get("validation", {})
    lines = ["# OpenDB Utilities — run summary", "",
             f"**{env.get('status', 'unknown').upper()}** · verdict: **{validation.get('verdict', 'unknown')}**",
             "", "## What was done", "", str(env.get("objective", "")), ""]
    if validation.get("note"):
        lines += ["## Validation", "", str(validation["note"]), ""]
    if env.get("results"):
        lines += ["## Results", "", "```json", json.dumps(env["results"], indent=2), "```", ""]
    lines += ["## Artifacts", "", "- `common_design_envelope.json` — authoritative 14-field envelope",
              "- `results/` — generated physical-design artifacts",
              "- `reports/` — reports", "- `logs/` — scripts, commands, and engine logs", ""]
    return "\n".join(lines)


def _organize():
    for folder in ("results", "reports", "logs"):
        os.makedirs(os.path.join(OUTPUT_DIR, folder), exist_ok=True)
    for name in list(os.listdir(OUTPUT_DIR)):
        path = os.path.join(OUTPUT_DIR, name)
        if not os.path.isfile(path) or name in ("common_design_envelope.json", "final_results.json", "SUMMARY.md"):
            continue
        low = name.lower()
        if low.endswith((".log", ".tcl", ".txt")) or low == "run_command.txt":
            folder = "logs"
        elif low.endswith((".rpt", ".md", ".csv")) or "report" in low:
            folder = "reports"
        else:
            folder = "results"
        target = os.path.join(OUTPUT_DIR, folder, name)
        if os.path.exists(target):
            os.remove(target)
        os.replace(path, target)


def save_final_results(env):
    missing = [field for field in CDE_FIELDS if field not in env]
    if missing:
        env = failed_envelope("envelope_validation",
                              f"CDE missing mandatory fields: {missing}", env)
    with open(os.path.join(OUTPUT_DIR, "common_design_envelope.json"), "w", encoding="utf-8") as stream:
        json.dump(env, stream, indent=2, default=str)
    # option b: SUMMARY.md removed (tool emits REPORT.md; agent emits
    # EXECUTIVE_SUMMARY.md). Render the deterministic report under reports/.
    with open(os.path.join(OUTPUT_DIR, "REPORT.md"), "w", encoding="utf-8") as stream:
        stream.write(_render_summary(env))
    _organize()


def _require_files(paths):
    for path in paths:
        if not path or not os.path.isfile(str(path)):
            raise FileNotFoundError(f"required input reference not found: {path}")


def _load_prefix(params, binding, policy, decisions, caveats):
    def_file, source, note = _resolve(params, binding, policy, "def_file")
    decisions["def_file"] = source
    if note: caveats.append(note)
    odb_file, source, note = _resolve(params, binding, policy, "odb_file")
    decisions["odb_file"] = source
    if note: caveats.append(note)
    if bool(def_file) == bool(odb_file):
        raise ValueError("provide exactly one of def_file or odb_file")
    tech_lef, source, note = _resolve(params, binding, policy, "tech_lef")
    decisions["tech_lef"] = source
    if note: caveats.append(note)
    cell_lefs, source, note = _resolve(params, binding, policy, "cell_lef", [])
    decisions["cell_lef"] = source
    if note: caveats.append(note)
    cell_lefs = _as_list(cell_lefs)
    if not tech_lef or not cell_lefs:
        raise ValueError("tech_lef and at least one cell_lef are required from params/binding/policy")
    liberty, source, note = _resolve(params, binding, policy, "liberty", [])
    decisions["liberty"] = source
    if note: caveats.append(note)
    liberties = _as_list(liberty)
    sdc, source, note = _resolve(params, binding, policy, "sdc")
    decisions["sdc"] = source
    if note: caveats.append(note)
    _require_files([tech_lef] + cell_lefs + liberties + ([sdc] if sdc else []) + [def_file or odb_file])
    lines = [f"read_liberty {_tcl(path)}" for path in liberties]
    lines += [f"read_lef {_tcl(tech_lef)}"] + [f"read_lef {_tcl(path)}" for path in cell_lefs]
    if def_file:
        lines.append(f"read_def {_tcl(def_file)}")
    else:
        lines.append(f"read_db {_tcl(odb_file)}")
    if sdc:
        lines.append(f"read_sdc {_tcl(sdc)}")
    return lines, def_file or odb_file, "def" if def_file else "odb", tech_lef, cell_lefs, liberties, sdc


def _required(params, name):
    value = params.get(name)
    if value is None or value == "" or value == []:
        raise ValueError(f"missing required scenario parameter '{name}'")
    return value


def _placements_tcl(placements):
    lines = []
    for item in placements:
        if not isinstance(item, dict):
            raise ValueError("each placement must be an object")
        inst = _required(item, "instance")
        x, y = _required(item, "x"), _required(item, "y")
        orient = item.get("orient", "R0")
        lines += [f"if {{[llength [get_cells {_tcl(inst)}]] != 1}} {{error \"instance not found or ambiguous: {inst}\"}}",
                  f"place_cell -inst_name {_tcl(inst)} -origin {{{float(x)} {float(y)}}} -orient {_tcl(orient)} -status FIRM"]
    return lines


WIRE_LENGTH_SOURCES = ("auto", "detailed_route", "global_route", "hpwl")

# `report_wire_length` REQUIRES `-net` (GRT-0238 "-net is required." otherwise),
# and `-global_route` on a database with no global route warns GRT-0241 per net
# and reports nothing. So the script first PROBES what the database actually
# carries (dbWire => detailed route; grt::have_routes => global route, which also
# loads guides stored in the ODB), then asks for exactly that source per net via
# `-net *` (power/ground/special nets are skipped by OpenROAD itself). With no
# route at all, `auto` falls back to a per-net HPWL ESTIMATE, labelled as such,
# and refuses outright when instances are unplaced (HPWL is meaningless there).
_WIRE_LENGTH_TCL = r"""set _wl_blk [ord::get_db_block]
if {$_wl_blk == "NULL"} { error "no design block loaded" }
set _wl_dr 0
foreach _wl_n [$_wl_blk getNets] { if {[$_wl_n getWire] != "NULL"} { set _wl_dr 1; break } }
set _wl_gr 0
if {[llength [info commands grt::have_routes]]} { if {[catch {set _wl_gr [grt::have_routes]}]} { set _wl_gr 0 } }
set _wl_insts 0
set _wl_unplaced 0
foreach _wl_i [$_wl_blk getInsts] { incr _wl_insts; if {![$_wl_i isPlaced]} { incr _wl_unplaced } }
puts "__WL_SOURCES__ global_route=$_wl_gr detailed_route=$_wl_dr instances=$_wl_insts unplaced=$_wl_unplaced"
set _wl_mode @MODE@
set _wl_flags {}
if {$_wl_mode == "auto"} {
  if {$_wl_dr} { set _wl_mode detailed_route } elseif {$_wl_gr} { set _wl_mode global_route } else { set _wl_mode hpwl }
}
if {$_wl_mode == "detailed_route"} {
  if {!$_wl_dr} { error "WL_SOURCE_MISSING: wire_length_source=detailed_route requested but no net carries a detailed-route wire (run detailed_route first)" }
  set _wl_flags -detailed_route
} elseif {$_wl_mode == "global_route"} {
  if {!$_wl_gr} { error "WL_SOURCE_MISSING: wire_length_source=global_route requested but the database carries no global route (run global_route or read_guides first)" }
  set _wl_flags -global_route
}
puts "__WL_MODE__ $_wl_mode"
if {$_wl_mode == "hpwl"} {
  if {$_wl_unplaced > 0} { error "WL_UNPLACED: $_wl_unplaced of $_wl_insts instances are unplaced and the database has no route; wire length is undefined before placement" }
  set _wl_fh [open @RPT@ w]
  puts $_wl_fh "tool net total_wl #pins"
  set _wl_dbu [$_wl_blk getDbUnitsPerMicron]
  foreach _wl_n [$_wl_blk getNets] {
    set _wl_t [$_wl_n getSigType]
    if {$_wl_t == "POWER" || $_wl_t == "GROUND" || [$_wl_n isSpecial]} { continue }
    set _wl_xs {}
    set _wl_ys {}
    foreach _wl_it [$_wl_n getITerms] {
      if {[catch {set _wl_b [$_wl_it getBBox]}]} { set _wl_b [[$_wl_it getInst] getBBox] }
      lappend _wl_xs [expr {([$_wl_b xMin] + [$_wl_b xMax]) / 2.0}]
      lappend _wl_ys [expr {([$_wl_b yMin] + [$_wl_b yMax]) / 2.0}]
    }
    foreach _wl_bt [$_wl_n getBTerms] {
      set _wl_b [$_wl_bt getBBox]
      lappend _wl_xs [expr {([$_wl_b xMin] + [$_wl_b xMax]) / 2.0}]
      lappend _wl_ys [expr {([$_wl_b yMin] + [$_wl_b yMax]) / 2.0}]
    }
    set _wl_np [llength $_wl_xs]
    set _wl_len 0.0
    if {$_wl_np > 1} {
      set _wl_xs [lsort -real $_wl_xs]
      set _wl_ys [lsort -real $_wl_ys]
      set _wl_len [expr {(([lindex $_wl_xs end] - [lindex $_wl_xs 0]) + ([lindex $_wl_ys end] - [lindex $_wl_ys 0])) / double($_wl_dbu)}]
    }
    puts $_wl_fh "hpwl: [$_wl_n getName] $_wl_len $_wl_np"
  }
  close $_wl_fh
} else {
  report_wire_length -net * $_wl_flags -file @RPT@
}"""

_WL_LINE = re.compile(r"^(grt|drt|hpwl):\s+(\S+)\s+([-+0-9.eE]+)\s+(\d+)")
_WL_SOURCE_NAMES = {"drt": "detailed_route", "grt": "global_route", "hpwl": "hpwl_estimate"}


def _wire_length_tcl(report, source):
    return (_WIRE_LENGTH_TCL.replace("@MODE@", source)
            .replace("@RPT@", _tcl(report)).splitlines())


def _summarize_wire_length(report, log_text, top_n=10):
    """Total and top-N per-net wire length parsed from the per-net report."""
    nets = []
    tools = set()
    with open(report, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            match = _WL_LINE.match(line.strip())
            if match:
                tools.add(match.group(1))
                nets.append((match.group(2), float(match.group(3)), int(match.group(4))))
    if not nets:
        raise RuntimeError(
            "report_wire_length produced no per-net entries; refusing to report a "
            "zero wire length as if it were measured")
    probe = re.search(r"__WL_SOURCES__ global_route=(\d) detailed_route=(\d) "
                      r"instances=(\d+) unplaced=(\d+)", log_text)
    mode = re.search(r"__WL_MODE__ (\S+)", log_text)
    nets.sort(key=lambda item: item[1], reverse=True)
    top_n = max(1, int(top_n))
    return {
        "source": ",".join(sorted(_WL_SOURCE_NAMES[t] for t in tools)),
        "mode_selected": mode.group(1) if mode else "unknown",
        "database_has_global_route": bool(probe and probe.group(1) == "1"),
        "database_has_detailed_route": bool(probe and probe.group(2) == "1"),
        "nets_reported": len(nets),
        "total_wire_length_um": round(sum(item[1] for item in nets), 3),
        "nets_without_route_warnings": len(re.findall(r"GRT-02(?:39|41)", log_text)),
        "top_nets": [{"net": n, "length_um": round(length, 3), "pins": pins}
                     for n, length, pins in nets[:top_n]],
    }


def _scenario_tcl(scenario, params, binding, policy, decisions, caveats):
    lines, input_db, input_kind, tech_lef, cell_lefs, liberties, sdc = _load_prefix(
        params, binding, policy, decisions, caveats)
    outputs, reports = [], []
    out_odb = os.path.join(OUTPUT_DIR, params.get("output_odb", "updated.odb"))
    out_def = os.path.join(OUTPUT_DIR, params.get("output_def", "updated.def"))

    if scenario == "convert_def_to_odb":
        if input_kind != "def":
            raise ValueError("convert_def_to_odb requires def_file")
        out_odb = os.path.join(OUTPUT_DIR, params.get("output_odb", "converted.odb"))
        lines += [f"write_db {_tcl(out_odb)}"]
        outputs = [out_odb]
    elif scenario == "convert_odb_to_def":
        if input_kind != "odb":
            raise ValueError("convert_odb_to_def requires odb_file")
        out_def = os.path.join(OUTPUT_DIR, params.get("output_def", "converted.def"))
        lines += [f"write_def {_tcl(out_def)}"]
        outputs = [out_def]
    elif scenario == "apply_def_template":
        template = _required(params, "template_def")
        _require_files([template])
        lines += [f"read_def -incremental {_tcl(template)}", f"write_db {_tcl(out_odb)}", f"write_def {_tcl(out_def)}"]
        outputs = [out_odb, out_def]
    elif scenario == "manage_obstructions":
        action = str(_required(params, "action")).lower()
        kind = str(_required(params, "kind")).lower()
        if action not in ("add", "remove") or kind not in ("placement", "routing", "pdn"):
            raise ValueError("manage_obstructions requires add/remove and placement/routing/pdn")
        if action == "remove":
            layer = params.get("layer")
            command = "remove_obstructions"
            if layer: command += f" -layer {_tcl(layer)}"
            lines.append(command)
        else:
            rects = _as_list(_required(params, "rectangles"))
            layer = params.get("layer")
            if kind in ("routing", "pdn") and not layer:
                raise ValueError("routing/PDN obstruction add requires layer")
            for rect in rects:
                if not isinstance(rect, (list, tuple)) or len(rect) != 4:
                    raise ValueError("each obstruction rectangle must be [x_min,y_min,x_max,y_max]")
                command = f"create_obstruction -bbox {{{' '.join(str(float(v)) for v in rect)}}}"
                if layer: command += f" -layer {_tcl(layer)}"
                if kind == "pdn": command += " -except_pg_nets"
                lines.append(command)
        lines += [f"write_db {_tcl(out_odb)}", f"write_def {_tcl(out_def)}"]
        outputs = [out_odb, out_def]
    elif scenario == "manual_macro_placement":
        lines += _placements_tcl(_as_list(_required(params, "placements")))
        lines += [f"write_db {_tcl(out_odb)}", f"write_def {_tcl(out_def)}"]
        outputs = [out_odb, out_def]
    elif scenario == "custom_io_placement":
        pins = _as_list(_required(params, "pins"))
        horizontal = _required(params, "horizontal_layer")
        vertical = _required(params, "vertical_layer")
        side = str(params.get("side", "bottom")).lower()
        if side not in ("bottom", "right", "top", "left"):
            raise ValueError("side must be bottom/right/top/left")
        pin_expr = " ".join(str(pin) for pin in pins)
        lines += [f"if {{[llength [get_ports {{{pin_expr}}}]] != {len(pins)}}} {{error \"one or more ordered pins do not exist\"}}",
                  f"set_io_pin_constraint -pin_names [get_ports {{{pin_expr}}}] -region edge:{side}",
                  f"place_pins -hor_layers {_tcl(horizontal)} -ver_layers {_tcl(vertical)}",
                  f"write_db {_tcl(out_odb)}", f"write_def {_tcl(out_def)}"]
        outputs = [out_odb, out_def]
    elif scenario == "insert_tap_endcap_decap":
        tap = _required(params, "tapcell_master")
        endcap = _required(params, "endcap_master")
        distance = float(_required(params, "distance"))
        cmd = f"tapcell -tapcell_master {_tcl(tap)} -endcap_master {_tcl(endcap)} -distance {distance}"
        decap = params.get("decap_master")
        lines.append(cmd)
        if decap:
            lines.append(f"filler_placement -prefix DECAP_ {_tcl(decap)}")
        lines += [f"write_db {_tcl(out_odb)}", f"write_def {_tcl(out_def)}"]
        outputs = [out_odb, out_def]
    elif scenario == "insert_port_diodes":
        diode = _required(params, "diode_cell")
        pin = _required(params, "diode_pin")
        lines += [f"repair_antennas -diode_cell {_tcl(diode)} -diode_pin {_tcl(pin)}",
                  f"write_db {_tcl(out_odb)}", f"write_def {_tcl(out_def)}"]
        outputs = [out_odb, out_def]
    elif scenario == "set_power_connections":
        connections = _as_list(_required(params, "connections"))
        for connection in connections:
            if not isinstance(connection, dict):
                raise ValueError("each power connection must be an object")
            net = _required(connection, "net")
            pin_pattern = _required(connection, "pin_pattern")
            inst_pattern = connection.get("inst_pattern", ".*")
            net_type = str(connection.get("type", "power")).lower()
            if net_type not in ("power", "ground"):
                raise ValueError("power connection type must be power or ground")
            lines.append(f"add_global_connection -net {_tcl(net)} -inst_pattern {_tcl(inst_pattern)} -pin_pattern {_tcl(pin_pattern)} -{net_type}")
        lines += ["global_connect", f"write_db {_tcl(out_odb)}", f"write_def {_tcl(out_def)}"]
        outputs = [out_odb, out_def]
    elif scenario == "report_disconnected_pins":
        report = os.path.join(OUTPUT_DIR, "disconnected_pins.rpt")
        # `tee -file`, NOT `redirect -file`. OpenROAD 26Q3 has NO `redirect`
        # command (`info commands redirect` -> empty); the Tcl script aborted with
        # `invalid command name "redirect"` AFTER the design had already been read,
        # so the run burned the full DEF-read cost and produced nothing. All four
        # report scenarios here carried it, i.e. every reporting scenario this tool
        # offers was dead. It failed CLOSED (status=failed), which is why it was
        # never mistaken for a clean result -- but it also meant the scenarios could
        # never close. Verified in-image: `tee` present, `redirect` absent, and a
        # real `tee -file` run captured 285 bytes of report_cell_usage output.
        lines += [f"tee -file {_tcl(report)} {{ report_floating_nets -verbose }}"]
        reports = [report]
    elif scenario == "report_wire_length":
        report = os.path.join(OUTPUT_DIR, "wire_length.rpt")
        source = str(params.get("wire_length_source", "auto")).strip().lower()
        if source not in WIRE_LENGTH_SOURCES:
            raise ValueError(f"wire_length_source must be one of {', '.join(WIRE_LENGTH_SOURCES)}")
        lines += _wire_length_tcl(report, source)
        reports = [report]
    elif scenario == "report_cell_usage":
        # Cell-frequency inventory (OpenLane `Odb.CellFrequencyTables`). Cheap, and
        # it is how an unintended cell class gets caught: a flood of buffers means
        # the resizer fought the design, a surprise latch means an RTL defect
        # survived lint, and a high-Vt cell where none was intended means the
        # don't-use list is not being honoured.
        report = os.path.join(OUTPUT_DIR, "cell_usage.rpt")
        lines += [f"tee -file {_tcl(report)} {{ report_cell_usage }}"]
        reports = [report]
    elif scenario == "check_macro_instances":
        # PRE-FLIGHT, not a signoff gate. Confirms every macro the configuration
        # claims is actually instantiated in the design, before hours of P&R run
        # against a floorplan built around a macro that does not exist (OpenLane
        # `OpenROAD.CheckMacroInstances`). Fails fast and cheap.
        expected = _as_list(params.get("expected_macros"))
        if not expected:
            raise ValueError(
                "check_macro_instances requires 'expected_macros' -- the macro "
                "instance names the configuration declares. With an empty list the "
                "check would pass vacuously, which is worse than not running it.")
        report = os.path.join(OUTPUT_DIR, "macro_instances.rpt")
        checks = "\n".join(
            'if {[$block findInst %s] == "NULL"} { puts $_fh "MISSING %s" } '
            'else { puts $_fh "PRESENT %s" }' % (_tcl(name), name, name)
            for name in expected)
        lines += [
            "set block [[[ord::get_db] getChip] getBlock]",
            f"set _fh [open {_tcl(report)} w]",
            checks,
            "close $_fh",
            f"puts \"__MACRO_CHECK__ [exec cat {_tcl(report)}]\"",
        ]
        reports = [report]
    elif scenario == "check_antenna_properties":
        # Antenna properties in the generated LEF abstract (OpenLane
        # `Odb.CheckDesignAntennaProperties`). A macro handed upward WITHOUT
        # per-pin antenna properties cannot be antenna-checked by the parent: the
        # parent's checker has no gate-area data for those pins, so it silently
        # reports the macro as clean. That is a false clean at the integration
        # level, which is why this belongs on the macro-producing side.
        report = os.path.join(OUTPUT_DIR, "antenna_properties.rpt")
        lines += [f"tee -file {_tcl(report)} {{ check_antennas -verbose }}"]
        reports = [report]
    elif scenario == "write_views":
        requested = _as_list(params.get("views", ["odb", "def"]))
        if not requested:
            raise ValueError("write_views requires at least one requested view")
        if "odb" in requested:
            lines.append(f"write_db {_tcl(out_odb)}"); outputs.append(out_odb)
        if "def" in requested:
            lines.append(f"write_def {_tcl(out_def)}"); outputs.append(out_def)
        if "powered_netlist" in requested:
            netlist = os.path.join(OUTPUT_DIR, params.get("output_netlist", "powered.v"))
            lines.append(f"write_verilog -include_pwr_gnd {_tcl(netlist)}"); outputs.append(netlist)
        if "lef" in requested:
            lef = os.path.join(OUTPUT_DIR, params.get("output_lef", "abstract.lef"))
            lines.append(f"write_abstract_lef {_tcl(lef)}"); outputs.append(lef)
        unknown = sorted(set(requested) - {"odb", "def", "powered_netlist", "lef"})
        if unknown: raise ValueError(f"unknown requested views: {unknown}")
    else:
        raise ValueError(f"unknown scenario '{scenario}'; supported: {', '.join(SCENARIOS)}")
    lines.append("exit")
    return ("\n".join(lines) + "\n", outputs, reports, input_db, tech_lef,
            cell_lefs, liberties, sdc)


def _version(engine):
    proc = subprocess.run([engine, "-version"], capture_output=True, text=True, timeout=30)
    text = (proc.stdout + proc.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def _cell_pin_lists(sources):
    """{cell: [pin, ...]} parsed from PDK cell netlists (.spice / .cdl).

    The PDK is the AUTHORITY for which pins a cell has. Never infer a pin list
    from the instantiation (that is the thing being repaired) and never hardcode
    one: sky130's bulk pins are VPB/VNB, another node names them differently.
    """
    pins = {}
    for src in sources:
        try:
            with open(src, encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    m = re.match(r"^\.subckt\s+(\S+)\s+(.*)$", line.strip(), re.I)
                    if m:
                        pins.setdefault(m.group(1), m.group(2).split())
        except OSError:
            continue
    return pins


def _complete_netlist_pins(scenario, outputs, params, binding):
    """Connect every PDK-declared pin the emitted Verilog netlist left open.

    *** WHY THIS EXISTS: `write_verilog -include_pwr_gnd` IS NOT LVS-COMPLETE. ***
    Measured on a real filled bsum16 DEF (620 components):
      - it omits the BULK/WELL terminals: a41oi_1 is instantiated with 8 of its
        10 PDK-declared pins, missing .VPB/.VNB. Netgen reports
        "Instance of ... has only 8 of 10 ports" and files a `port_match_error`
        PER INSTANCE -- 1387 of them -- which then wrecks top-level net matching.
      - it emits PHYSICAL cells with an EMPTY connection list, e.g.
        `sky130_fd_sc_hd__fill_1 FILLER_0_127 ();`, while the layout carries 185
        wired fill/decap/tap instances.
    A physical cell's PG connectivity is IMPLICIT in the DEF (rails / special
    nets), not in its NETS section, so the writer has nothing to emit. The same
    gap sinks `write_cdl` (it drops fill/decap entirely and marks tap power
    `_unconnected_`), so this is NOT fixable by choosing a different format.
    MEASURED after completion: devices 258==258, nets 270==270, port errors 0.

    TWO RULES, BOTH LOAD-BEARING:
    1. Power/bulk pins go to their RAILS. Which pin is a rail is read from the
       binding (`pg_pin_map`) when present, so a different node can name them.
    2. Every OTHER unconnected pin gets a UNIQUE PER-INSTANCE net. *** Tying them
       to one shared `_unused_` net would SHORT them together in the source,
       creating a node the layout does not have -- a fabricated difference that
       can MASK A REAL SHORT. *** Uniqueness also preserves detectability: a
       genuine open still fails, because the source names a net the layout does
       not have at that pin. This RECONCILES REPRESENTATION WITHOUT DISCARDING
       EVIDENCE, which is why it is the right fix and netgen's `ignore` is not --
       `ignore` would drop exactly the signal that separates an intended dangling
       output from a real open circuit.
    Returns an evidence dict, or None when it does not apply.
    """
    if scenario != "write_views":
        return None
    netlists = [p for p in outputs if str(p).lower().endswith((".v", ".vlog", ".verilog"))]
    if not netlists:
        return None
    models = _as_list(params.get("cell_models") or binding.get("cell_spice")
                      or binding.get("cdl_masters") or binding.get("cell_models"))
    if not models:
        # NOT silently skipped: an un-completed netlist is a LATENT LVS failure,
        # so say so in the envelope rather than emitting a clean-looking file.
        return {"applied": False,
                "reason": ("no cell_models/pdk_binding.cell_spice supplied, so the "
                           "PDK pin lists could not be read; the emitted netlist "
                           "omits bulk pins and leaves physical cells unconnected, "
                           "and will NOT match in LVS"),
                "lvs_ready": False}
    pins = _cell_pin_lists(models)
    if not pins:
        return {"applied": False,
                "reason": f"no .subckt definitions parsed from {models}",
                "lvs_ready": False}
    rails = dict(binding.get("pg_pin_map")
                 or {"VPWR": "VPWR", "VGND": "VGND", "VPB": "VPWR", "VNB": "VGND"})
    totals = {"rail_pins_connected": 0, "dangling_pins_named": 0,
              "instances_modified": 0, "instances_reordered": 0,
              "cells_unknown_to_pdk": set()}

    def _fix(match):
        body = match.group(0)
        cell = re.match(r"(\S+)", body).group(1)
        inst_m = re.match(r"\S+\s+(\S+)", body)
        declared = pins.get(cell)
        if declared is None:
            totals["cells_unknown_to_pdk"].add(cell)
            return body
        if not inst_m:
            return body
        inst = inst_m.group(1)
        # Existing connections, by pin name. An explicitly EMPTY `.PIN()` is
        # NOT a connection -- it is exactly the physical-cell case this
        # function exists to complete -- so it must not read as connected.
        existing = {}
        for pin_name, net in re.findall(r"\.(\w+)\(\s*([^()]*?)\s*\)", body):
            if net:
                existing[pin_name] = net

        # Emit EVERY declared pin, in the PDK'S DECLARED PORT ORDER.
        #
        # *** ORDER IS LOAD-BEARING, NOT COSMETIC. *** Netgen binds a cell that
        # is DEFINED BY A SPICE `.subckt` POSITIONALLY -- it does not honour the
        # Verilog dot-names, because there is no Verilog module declaration to
        # bind them against. So a name-correct netlist whose connections are in
        # a different ORDER than the .subckt silently connects signals to the
        # wrong pins. MEASURED on sky130: `.subckt ... and2_2 A B VGND VNB VPB
        # VPWR X` vs OpenROAD's emitted order A B VGND VPWR X -- position 5 is
        # VPB in the PDK and X in the netlist, so the OUTPUT net landed on the
        # BULK pin ("Net: sum_nxt[14] -> and2_2/VPB" in the netgen report) and
        # the top cell could never match. Re-ordering is derived ENTIRELY from
        # the PDK subckt header; nothing here is invented.
        ordered, reordered = [], False
        for idx, pin in enumerate(declared):
            if pin in existing:
                net = existing[pin]
            elif pin in rails:
                net = rails[pin]
                totals["rail_pins_connected"] += 1
            else:
                net = "_open_%s_%s_" % (inst, pin)
                totals["dangling_pins_named"] += 1
            ordered.append(".%s(%s)" % (pin, net))
        emitted_order = [p for p, _ in re.findall(r"\.(\w+)\(\s*([^()]*?)\s*\)", body)]
        if emitted_order != list(declared):
            reordered = True

        if len(existing) == len(declared) and not reordered:
            return body
        if reordered:
            totals["instances_reordered"] += 1
        totals["instances_modified"] += 1
        return re.sub(r"\(.*\)\s*;", "(\n    " + ",\n    ".join(ordered) + ");",
                      body, flags=re.S)

    known = "|".join(re.escape(c) for c in sorted(pins, key=len, reverse=True))
    pattern = r"(?:%s)\s+\S+\s+\([^;]*?\);" % known
    for netlist in netlists:
        try:
            with open(netlist, encoding="utf-8", errors="replace") as stream:
                text = stream.read()
            with open(netlist, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(re.sub(pattern, _fix, text, flags=re.S))
        except OSError as exc:
            return {"applied": False, "reason": f"could not rewrite {netlist}: {exc}",
                    "lvs_ready": False}
    unknown = sorted(totals.pop("cells_unknown_to_pdk"))
    evidence = {"applied": True, "lvs_ready": not unknown,
                "pdk_pin_source": [os.path.basename(str(m)) for m in models],
                "rail_map": rails}
    evidence.update(totals)
    if unknown:
        # A cell the PDK netlist does not define cannot be completed, and it is
        # also the cell most likely to break LVS. Name it; never imply coverage.
        evidence["cells_not_in_pdk_netlist"] = unknown
    return evidence


def dispatch(params):
    scenario = str(params.get("scenario", ""))
    if scenario not in SCENARIOS:
        return failed_envelope(scenario or "missing",
                               f"unknown scenario '{scenario}'; supported: {', '.join(SCENARIOS)}", params)
    try:
        binding, policy = _policy(params)
        engine, engine_source, engine_note = _resolve(params, binding, policy, "engine", "openroad")
        decisions = {"engine": engine_source}
        caveats = [engine_note] if engine_note else []
        executable = shutil.which(str(engine))
        if not executable:
            raise FileNotFoundError(f"OpenROAD engine not found on PATH: {engine}")
        script, outputs, reports, input_db, tech_lef, cell_lefs, liberties, sdc = _scenario_tcl(
            scenario, params, binding, policy, decisions, caveats)
        script_path = os.path.join(OUTPUT_DIR, f"{scenario}.tcl")
        log_path = os.path.join(OUTPUT_DIR, f"{scenario}.log")
        with open(script_path, "w", encoding="utf-8") as stream:
            stream.write(script)
        command = [executable, "-exit", script_path]
        with open(os.path.join(OUTPUT_DIR, "run_command.txt"), "w", encoding="utf-8") as stream:
            stream.write(" ".join(shlex.quote(item) for item in command) + "\n")
        started = time.time()
        proc = subprocess.run(command, cwd=WORK_DIR, capture_output=True, text=True)
        elapsed = round(time.time() - started, 3)
        with open(log_path, "w", encoding="utf-8") as stream:
            stream.write(proc.stdout + "\n" + proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError(f"OpenROAD exited {proc.returncode}; see {os.path.basename(log_path)}: " +
                               (proc.stdout + proc.stderr)[-1200:])
        # An OUTPUT (DEF/ODB) that is empty is always broken -- keep that strict.
        for path in outputs:
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise RuntimeError(f"OpenROAD did not produce required non-empty output: {path}")
        # A REPORT is different: for a check-style report an EMPTY file is the
        # CLEAN result. `report_floating_nets` prints nothing when there are zero
        # floating nets, so requiring non-empty made the scenario UNCLOSABLE BY
        # CONSTRUCTION on a healthy design -- it failed a design precisely because
        # the design was clean. Same defect shape as the constraints banner bug.
        # The guard still has teeth: `tee -file` creates the file only if the
        # command actually executed, so a MISSING report still means the run did
        # not happen and still fails. Emptiness is recorded as evidence, never
        # silently equated with "not run".
        empty_reports = []
        for path in reports:
            if not os.path.isfile(path):
                raise RuntimeError(
                    f"OpenROAD did not produce required report: {path} "
                    "(the report command did not execute)")
            if os.path.getsize(path) == 0:
                empty_reports.append(os.path.basename(path))
        pin_completion = _complete_netlist_pins(scenario, outputs, params, binding)
        wire_length = None
        if scenario == "report_wire_length":
            wire_length = _summarize_wire_length(
                reports[0], proc.stdout + "\n" + proc.stderr, params.get("top_n", 10))
            if wire_length["source"] == "hpwl_estimate":
                caveats.append(
                    "database carries no global or detailed route: wire length is a "
                    "per-net HPWL ESTIMATE from pin positions, not a routed length")
        input_paths = [input_db, tech_lef] + cell_lefs + liberties + ([sdc] if sdc else [])
        for value in (params.get("template_def"),):
            if value: input_paths.append(value)
        input_hashes = {os.path.basename(path): _sha(path) for path in input_paths}
        output_hashes = {os.path.basename(path): _sha(path) for path in outputs + reports}
        evidence = {"engine_exit_code": proc.returncode,
                    "artifacts": [os.path.basename(path) for path in outputs],
                    "reports": [os.path.basename(path) for path in reports],
                    "setting_sources": decisions}
        if empty_reports:
            # State the clean result EXPLICITLY. An empty check-report means the
            # command ran and found nothing; saying so beats leaving a reader to
            # infer it from a zero-byte file, which is indistinguishable at a
            # glance from a report that was never written.
            evidence["empty_reports"] = empty_reports
            evidence["empty_report_note"] = (
                "report command executed and produced no findings; for a "
                "check-style report (e.g. report_floating_nets) an empty report "
                "is the CLEAN result, not a missing artifact")
        if pin_completion: evidence["pin_completion"] = pin_completion
        if wire_length: evidence["wire_length"] = wire_length
        if caveats: evidence["override_caveats"] = caveats
        scenario_results = {"scenario": scenario, "artifacts_written": len(outputs),
                            "reports_written": len(reports)}
        if wire_length:
            scenario_results["wire_length"] = {
                k: wire_length[k] for k in ("source", "nets_reported",
                                            "total_wire_length_um", "top_nets")}
        envelope = _base_envelope(
            f"Execute OpenROAD/OpenDB scenario {scenario}", "completed", binding, params,
            results=scenario_results, evidence=evidence,
            validation={"verdict": "pass_with_caveats" if caveats else "pass",
                        "note": "real OpenROAD execution completed and required outputs were verified"},
            assumptions=caveats,
            provenance={"engine": executable, "engine_version": _version(executable),
                        "runtime_s": elapsed, "input_hashes": input_hashes,
                        "output_hashes": output_hashes,
                        "container_image": os.environ.get("CONTAINER_IMAGE", "openroad/orfs:latest"),
                        "environment": {"python": os.sys.version.split()[0], "platform": os.name},
                        "finished_utc": datetime.now(timezone.utc).isoformat()},
        )
        if wire_length:
            envelope["qor_metrics"] = {
                "total_wire_length_um": wire_length["total_wire_length_um"],
                "wire_length_source": wire_length["source"],
                "nets_reported": wire_length["nets_reported"]}
        return envelope
    except Exception as exc:
        return failed_envelope(scenario, exc, params)


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
