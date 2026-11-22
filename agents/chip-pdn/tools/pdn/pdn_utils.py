#!/usr/bin/env python3
"""pdn_utils.py -- real OpenROAD pdngen power-grid generation.

Reads node LEF/Liberty + a floorplan DEF + a pdngen config, runs pdngen, checks grid
connectivity, and writes a PDN DEF. Metal stack comes from the PDK binding.
Node-aware. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "pdn"
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


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None, error=None,
         qor=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD pdngen", "version": "openroad"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "connectivity"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _lef_pg_pins(lef_paths):
    """{macro_name: {pin_name: {"use": POWER|GROUND, "abutment": bool}}} from LEF.

    Only PG-sigtype (`USE POWER` / `USE GROUND`) pins are returned -- the whole point
    is to enumerate what the BOUND LIBRARY declares rather than what a human remembered
    to type into a global-connect config.
    """
    macros = {}
    for path in lef_paths:
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for mm in re.finditer(r"^MACRO\s+(\S+)(.*?)^END\s+\1\s*$", text, re.S | re.M):
            name, body = mm.group(1), mm.group(2)
            pins = {}
            for pm in re.finditer(r"^\s*PIN\s+(\S+)(.*?)^\s*END\s+\1\s*$",
                                  body, re.S | re.M):
                pin, pin_body = pm.group(1), pm.group(2)
                # LEF terminates statements with `;`, and several may share a line
                # (`DIRECTION INOUT ; USE GROUND ; SHAPE ABUTMENT ;`), so anchoring
                # on line start would silently read a real pin as USE SIGNAL.
                use = re.search(r"(?:^|;)\s*USE\s+(\S+)\s*;", pin_body, re.M)
                use = use.group(1).upper() if use else "SIGNAL"
                if use not in ("POWER", "GROUND"):
                    continue
                pins[pin] = {
                    "use": use,
                    "abutment": bool(re.search(r"(?:^|;)\s*SHAPE\s+ABUTMENT\s*;",
                                               pin_body, re.M)),
                }
            if pins:
                macros[name] = pins
    return macros


def _def_instantiated_masters(def_path):
    """Master cell names actually instantiated in a DEF's COMPONENTS section.

    Returns None when the section cannot be read, which callers must treat as "scope
    unknown" and widen to the whole library rather than narrow to nothing.
    """
    masters = set()
    try:
        in_comp = False
        with open(def_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("COMPONENTS "):
                    in_comp = True
                    continue
                if s.startswith("END COMPONENTS"):
                    return masters
                if not in_comp:
                    continue
                m = re.match(r"-\s+(\S+)\s+(\S+)", s)
                if m:
                    masters.add(m.group(2))
    except OSError:
        return None
    return masters or None


#: Caller/binding override keys for a library whose PG pin names this tool must not
#: guess at (a second supply such as `KAPWR` / `LOWLVPWR` / `VPWRIN` on sky130's
#: low-power cells is a DIFFERENT rail, not a body tie -- tying it to the core supply
#: would be an electrical error, so it must be declared, never inferred).
_PG_PATTERN_KEYS = (("power_pin_patterns", "power"), ("ground_pin_patterns", "ground"))


def _derive_pg_pin_patterns(params, binding, pnet, gnet, def_file=None,
                            cell_lefs=()):
    """Derive the `add_global_connection` pin-pattern set from the BOUND LEF.

    WHY THIS IS DERIVED AND NOT TYPED OUT.
    `add_global_connection` binds nets to pins strictly by the declared regex and
    treats an unmatched PG pin as ordinary unconnected logic -- it never fails, and
    never warns above informational severity. A hand-authored pattern list is therefore
    only as complete as whoever wrote it. Measured on this campaign: sky130_fd_sc_hd
    declares FOUR PG-sigtype MTerms per functional cell (`VPWR`+`VPB` POWER,
    `VGND`+`VNB` GROUND); the config named two, and every standard cell in two designs
    carried a floating body/well tie from PDN through placement -- a guaranteed LVS
    device-terminal mismatch that no stage reported.

    CLASSIFICATION IS FROM THE LEF, NOT FROM A NAME TABLE:
      * a PG pin whose name IS the domain's power/ground net  -> the rail itself;
      * a PG pin with NO `SHAPE ABUTMENT`                     -> a body/well tie, which
        belongs to the same-sigtype rail of this domain (`VPB`->power, `VNB`->ground on
        every sky130 cell, including the low-power ones);
      * any OTHER `SHAPE ABUTMENT` PG pin                     -> a SECOND SUPPLY
        (`KAPWR`, `LOWLVPWR`, `VPWRIN`), which must be mapped explicitly by the caller.
        Auto-tying it to the core rail would short two supplies together, so it is
        reported UNMAPPED and left for `_build`'s connectivity gate to fail on.

    Returns {"power": [...], "ground": [...], "unmapped": [...], "source": str,
             "scope": str, "masters_scanned": int}.
    """
    overrides = {}
    policy = ((binding.get("tool_policy") or {}).get("pdn") or {}).get("settings") or {}
    for key, slot in _PG_PATTERN_KEYS:
        value = params.get(key)
        if value is None:
            value = policy.get(key) or binding.get(key)
        if value:
            overrides[slot] = [str(v) for v in _as_list(value)]

    power, ground, unmapped = {pnet}, {gnet}, {}
    macros = _lef_pg_pins(cell_lefs)
    scope = "no cell LEF bound"
    scanned = 0
    if macros:
        instantiated = _def_instantiated_masters(def_file) if def_file else None
        if instantiated:
            names = [n for n in macros if n in instantiated]
            scope = "masters instantiated in the input DEF"
        else:
            # Unknown scope must widen, never narrow: a missed pattern floats a
            # terminal silently, an extra one simply matches nothing.
            names = list(macros)
            scope = "every master in the bound cell LEF (DEF scope unreadable)"
        scanned = len(names)
        for name in names:
            for pin, info in macros[name].items():
                if pin in (pnet, gnet):
                    continue
                if not info["abutment"]:
                    (power if info["use"] == "POWER" else ground).add(pin)
                else:
                    unmapped.setdefault(pin, {"use": info["use"], "masters": []})
                    unmapped[pin]["masters"].append(name)

    derived = {"power": sorted(power), "ground": sorted(ground),
               "source": "derived from bound cell LEF PG-sigtype declarations",
               "scope": scope, "masters_scanned": scanned}
    for slot in ("power", "ground"):
        if slot in overrides:
            derived[slot] = sorted(set(derived[slot]) | set(overrides[slot]))
            for pin in overrides[slot]:
                unmapped.pop(pin, None)
    if overrides:
        derived["source"] += " + caller/binding pin-pattern override"
    derived["unmapped"] = [
        {"pin": pin, "use": info["use"], "masters": len(info["masters"]),
         "example_master": sorted(info["masters"])[0] if info["masters"] else None}
        for pin, info in sorted(unmapped.items())]
    return derived


def _global_connect_lines(derived, pnet, gnet):
    """One `add_global_connection` per DERIVED PG pin name, then `global_connect`."""
    lines = []
    for pin in derived["power"]:
        lines.append("add_global_connection -net %s -pin_pattern {^%s$} -power"
                     % (pnet, pin))
    for pin in derived["ground"]:
        lines.append("add_global_connection -net %s -pin_pattern {^%s$} -ground"
                     % (gnet, pin))
    lines.append("global_connect")
    return lines


def _synthesize_pdn_config(params, binding, derived_pg=None):
    """Build a pdngen Tcl config from surfaced parameters (used when no
    pdn_config file is supplied). Generates global connections, a std-cell grid
    with follow-pin rails + metal straps, optional core ring, and layer
    connects.

    `derived_pg` is the LEF-derived PG pin-pattern set from `_derive_pg_pin_patterns`;
    when absent it is derived here from the same inputs, so the emitted config can
    never silently fall back to a two-pattern `VPWR`/`VGND` guess.
    """
    pnet = params.get("power_net", "VDD")
    gnet = params.get("ground_net", "VSS")
    vd_name = params.get("voltage_domain_name", "Core")
    rail_layer = params.get("rail_layer") or binding.get("pdn_rail_layer") or "met1"
    rail_width = params.get("rail_width", 0.48)
    straps = params.get("straps") or binding.get("pdn_straps") or [
        {"layer": "met4", "width": 1.6, "pitch": 56.0, "offset": 2.0},
        {"layer": "met5", "width": 1.6, "pitch": 56.0, "offset": 2.0},
    ]
    # Boundary power pins (hierarchical / core-level macro closure). When a
    # core-level block is hardened with no I/O ring (DESIGN_IS_CORE=1, no pads),
    # OpenROAD PSM has no current-injection terminal and check_power_grid fails
    # PSM-0025 ("no VPWR/VGND terminals"). The fix is the standard hierarchical
    # macro flow: route the top PDN layer to the die boundary and expose real
    # VPWR/VGND power PINS there via `define_pdn_grid -pins`. Those boundary pins
    # become (a) the terminals the top-level integration abuts, AND (b) the PSM
    # source terminals, so check_power_grid seeds from them. Enabled explicitly
    # via `boundary_power_pins`, or automatically when the caller marks the block
    # core-level (`core_level`/`design_is_core`) which is the padless case.
    _core_level = str(params.get("core_level", params.get("design_is_core", ""))).lower() \
        in ("1", "true", "yes")
    boundary_pins = params.get("boundary_power_pins")
    if boundary_pins is None:
        boundary_pins = _core_level
    else:
        boundary_pins = str(boundary_pins).lower() in ("1", "true", "yes")
    # Default the pin layer(s) to the top strap layer (the one that reaches the
    # macro edge and mates with the top-level PDN).
    top_strap_layer = straps[-1]["layer"] if straps else (rail_layer)
    pin_layers = params.get("pin_layers") or ([top_strap_layer] if boundary_pins else [])
    if derived_pg is None:
        derived_pg = _derive_pg_pin_patterns(
            params, binding, pnet, gnet,
            def_file=params.get("def_file"),
            cell_lefs=_as_list(params.get("cell_lef") or binding.get("cell_lef")))
    lines = _global_connect_lines(derived_pg, pnet, gnet)
    lines.append(
        f"set_voltage_domain -name {vd_name} -power {pnet} -ground {gnet}")
    # `-pins {layers}` makes pdngen create boundary power pins on those layers.
    _grid = f"define_pdn_grid -name stdcell_grid -voltage_domains {vd_name}"
    if boundary_pins and pin_layers:
        _grid += f" -pins {{{' '.join(pin_layers)}}}"
    lines.append(_grid)
    lines.append(
        f"add_pdn_stripe -grid stdcell_grid -layer {rail_layer} "
        f"-width {rail_width} -followpins")
    for s in straps:
        opt = (f"-layer {s['layer']} -width {s.get('width', 1.6)} "
               f"-pitch {s.get('pitch', 56.0)} -offset {s.get('offset', 2.0)}")
        if s.get("spacing") is not None:
            opt += f" -spacing {s['spacing']}"
        # Extend the pin-layer stripes to the boundary so the exposed power pins
        # actually reach the die/core edge for hierarchical mating + PSM seeding.
        if boundary_pins and s["layer"] in pin_layers:
            opt += " -extend_to_boundary"
        lines.append(f"add_pdn_stripe -grid stdcell_grid {opt}")
    if str(params.get("core_ring", "")).lower() in ("1", "true", "yes"):
        rl = params.get("ring_layers") or [straps[0]["layer"],
                                           straps[-1]["layer"]]
        rw = params.get("ring_width", 2.0)
        rs = params.get("ring_spacing", 2.0)
        co = params.get("ring_core_offset", 2.0)
        lines.append(
            f"add_pdn_ring -grid stdcell_grid -layers {{{' '.join(rl)}}} "
            f"-widths {{{rw} {rw}}} -spacings {{{rs} {rs}}} "
            f"-core_offsets {{{co} {co}}}")
    # Layer connects: rail->first strap, then chain successive strap layers,
    # unless the caller supplies explicit connect_layers pairs.
    connects = params.get("connect_layers")
    if not connects:
        chain = [rail_layer] + [s["layer"] for s in straps]
        connects = [[chain[i], chain[i + 1]] for i in range(len(chain) - 1)]
    for pair in connects:
        lines.append(f"add_pdn_connect -grid stdcell_grid "
                     f"-layers {{{pair[0]} {pair[1]}}}")
    return "\n".join(lines)


#: DEF routing-statement keywords that can follow a `( x y )` point but are NOT a via
#: name. Everything else in that position IS a via placement, per LEF/DEF's
#: `( x y [ext] ) [viaName [orient]]` grammar.
_DEF_ROUTE_KEYWORDS = frozenset((
    "NEW", "ROUTED", "FIXED", "COVER", "SHAPE", "USE", "MASK", "RECT", "VIRTUAL",
    "STYLE", "NONDEFAULTRULE", "SOURCE", "PROPERTY", "ORIGINAL", "PATTERN",
    "WEIGHT", "ESTCAP", "SPECIAL", "DIRECTION", "PIN", "SYNTHESIZED", "TIMING",
    "TEST", "DIST", "NETLIST", "USER", "END",
))

#: Explicit `+ VIA <name>` form, and pdngen's `( x y ) <viaName>` form. `pdngen`
#: emits ONLY the second: `NEW met3 0 + SHAPE STRIPE ( 64440 78880 ) via4_5_1600_...`.
_DEF_VIA_AFTER_POINT = re.compile(r"\)\s+([A-Za-z_][A-Za-z0-9_]*)")


def _count_specialnets_vias(def_path):
    """Count via *instances* inside the SPECIALNETS section of a DEF.

    Returns a dict with the via count and the set of PDN metal layers seen on
    ROUTED/NEW stripes. A grid with >=2 stripe layers but 0 SPECIALNETS vias is
    electrically disconnected.

    WHY THIS PARSES TWO FORMS. The original counter matched only the literal
    `"+ VIA "` token. `pdngen` never emits that: it writes the via NAME as the
    trailing token of a routing point (`( x y ) via3_4_1600_480_1_4_400_400`), per
    LEF/DEF's `( x y [ext] ) [viaName [orient]]` grammar. Measured on a real, fully
    connected sky130 grid: 128 via placements in the DEF, `specialnets_via_count`
    reported `0`. A zero in a signoff-evidence integer is not self-evidently clean --
    it reads identically whether the grid has no vias or the parser has no eyes.
    """
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
                for token in _DEF_VIA_AFTER_POINT.findall(line):
                    if token.upper() not in _DEF_ROUTE_KEYWORDS:
                        vias += 1
                m = re.findall(r"(?:ROUTED|NEW)\s+(met\d+|metal\d+|m\d+)", line)
                for lyr in m:
                    layers.add(lyr)
    except OSError:
        return {"specialnets_vias": None, "stripe_layers": [], "readable": False}
    return {"specialnets_vias": vias, "stripe_layers": sorted(layers), "readable": True}


def _count_power_pins(def_path, pnet="VDD", gnet="VSS"):
    """Count boundary power PINS (USE POWER/GROUND) in the DEF PINS section.

    These are the block terminals that (a) mate with the top-level PDN during
    hierarchical integration and (b) act as the PSM current-injection source for
    a padless core-level macro. Returns per-net counts; 0 for a core-level block
    means PSM will fail PSM-0025 (no terminals)."""
    counts = {pnet: 0, gnet: 0, "power_total": 0}
    try:
        in_pins = False
        cur_use = None
        cur_net = None
        with open(def_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("PINS "):
                    in_pins = True
                    continue
                if s.startswith("END PINS"):
                    break
                if not in_pins:
                    continue
                m = re.match(r"-\s+(\S+)\s+\+\s+NET\s+(\S+)", s)
                if m:
                    cur_net = m.group(2)
                    cur_use = None
                if "+ USE POWER" in s:
                    cur_use = "POWER"
                elif "+ USE GROUND" in s:
                    cur_use = "GROUND"
                if s.startswith(";") or s.endswith(";"):
                    if cur_use in ("POWER", "GROUND") and cur_net:
                        counts["power_total"] += 1
                        if cur_net in counts:
                            counts[cur_net] += 1
                    cur_use = None
                    cur_net = None
    except OSError:
        return None
    return counts



def _parse_pg_terminals(log_text):
    """Read the `__PG_TERMINALS__` probe line into a per-MTerm-name breakdown.

    Returns None when the marker is absent -- "the probe did not run" must never be
    reported as "nothing was unconnected".
    """
    m = re.search(r"__PG_TERMINALS__\s+total=(\d+)\s+unconnected=(\d+)\s+by_pin=(\S*)",
                  log_text)
    if not m:
        return None
    by_pin = {}
    for item in (m.group(3) or "").split(","):
        if "=" in item:
            name, _, count = item.partition("=")
            try:
                by_pin[name] = int(count)
            except ValueError:
                continue
    return {"total": int(m.group(1)), "unconnected": int(m.group(2)),
            "unconnected_by_pin": by_pin}


def _count_floating_indicators(log_text):
    """Keep unknown diagnostics fail-closed, but honor explicit numeric counts."""
    indicators = re.finditer(
        r"\b(?:floating|unconnected)\b(?:\s*=\s*(\d+)(?![\w.+-]))?",
        log_text, re.I)
    return sum(int(match.group(1)) if match.group(1) is not None else 1
               for match in indicators)


def _build(params):
    if not shutil.which("openroad"):
        return _cde(objective="PDN", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    top, def_file, cfg = params.get("top"), params.get("def_file"), params.get("pdn_config")
    binding = params.get("pdk_binding") or {}
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    libs = _as_list(params.get("liberty") or binding.get("liberty"))
    hierarchy_mode = str(params.get("hierarchy_mode", "flat")).strip().lower()
    for n, v in (("top", top), ("def_file", def_file), ("tech_lef", tech_lef)):
        if not v:
            return _cde(objective="PDN", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}'", validation={"verdict": "fail"})
    for p in [def_file, tech_lef] + cell_lefs + libs:
        if not os.path.exists(str(p)):
            return _cde(objective="PDN", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    # Every PG-sigtype pin the BOUND library declares, derived before the config is
    # written so an explicit pdn_config file can be audited against the same set.
    derived_pg = _derive_pg_pin_patterns(
        params, binding, params.get("power_net", "VDD"),
        params.get("ground_net", "VSS"), def_file=def_file, cell_lefs=cell_lefs)
    # Grid source: an explicit pdn_config file (back-compat) OR a config
    # synthesized from surfaced parameters. Fail closed if a config file is
    # named but missing.
    if cfg:
        if not os.path.exists(str(cfg)):
            return _cde(objective="PDN", status="failed", pdk_binding=binding or "none",
                        error=f"pdn_config not found: {cfg}", validation={"verdict": "fail"})
        cfg_path = cfg
        grid_source = "pdn_config_file"
    else:
        cfg_path = os.path.join(_OUTPUT_DIR, "pdn_generated.tcl")
        _params_for_cfg = dict(params)
        _params_for_cfg.setdefault("def_file", def_file)
        _params_for_cfg.setdefault("cell_lef", cell_lefs)
        open(cfg_path, "w").write(
            _synthesize_pdn_config(_params_for_cfg, binding, derived_pg))
        grid_source = "synthesized_from_params"
    out_def = os.path.join(_OUTPUT_DIR, "pdn.def")
    pnet = params.get("power_net", "VDD")
    gnet = params.get("ground_net", "VSS")
    lef_reads = "\n".join([f"read_lef {tech_lef}"] + [f"read_lef {c}" for c in cell_lefs])
    lib_reads = "\n".join(f"read_liberty {l}" for l in libs)
    # Boundary-pin / core-level detection (mirror of _synthesize_pdn_config) so
    # the PSM source is declared consistently and recorded in the CDE.
    _core_level = str(params.get("core_level", params.get("design_is_core", ""))).lower() \
        in ("1", "true", "yes")
    _bp = params.get("boundary_power_pins")
    boundary_pins = _core_level if _bp is None else (str(_bp).lower() in ("1", "true", "yes"))
    # Rail voltage for PSM. PSM-0025 ("no VPWR/VGND terminals") on a padless
    # core-level block is fixed by the boundary power PINS created above (which
    # become the PSM source terminals); set_pdnsim_net_voltage declares the rail
    # voltage so check_power_grid can seed from those pins. Power net = supply
    # voltage; ground net = 0 V.
    try:
        _vdd = float(params.get("pdn_voltage", (binding.get("voltage") or 1.8)))
    except (TypeError, ValueError):
        _vdd = 1.8
    _psm_src = ""
    if boundary_pins:
        _psm_src = (f"set_pdnsim_net_voltage -net {pnet} -voltage {_vdd}\n"
                    f"set_pdnsim_net_voltage -net {gnet} -voltage 0\n")
    # After pdngen, run PSM check_power_grid on both supply nets. A grid that has
    # stripes but no connecting vias between layers is electrically disconnected;
    # PSM reports it (PSM-0069 and related) here rather than letting it slip
    # downstream to power-ir. Wrapped in catch so we can classify the error text.
    #
    # The PG-TERMINAL PROBE is the name-independent backstop for a missing
    # global-connect pattern. `add_global_connection` treats an unmatched PG pin as
    # ordinary unconnected logic -- never an error, never above an informational
    # `PDN-0189` warning -- so a pattern the config forgot floats every instance of
    # that terminal silently. This walks the ODB after `pdngen` and reports the
    # unconnected PG ITerm count BROKEN DOWN BY MTERM NAME, because a single
    # aggregate is unreadable: 586 unconnected looks alarming until it decomposes
    # into 0 rail and 586 body tie, and 0 rail looks clean until it decomposes the
    # other way. Works on any library and any pin naming, because it asks the
    # database what is unbound instead of asking a human what to bind.
    _pg_probe = (
        'set _blk [ord::get_db_block]\n'
        'array unset _unc\n'
        'set _tot 0\n'
        'set _bad 0\n'
        'foreach _i [$_blk getInsts] {\n'
        '  foreach _it [$_i getITerms] {\n'
        '    set _mt [$_it getMTerm]\n'
        '    set _st [$_mt getSigType]\n'
        '    if {$_st != "POWER" && $_st != "GROUND"} { continue }\n'
        '    incr _tot\n'
        '    if {[$_it getNet] == "NULL"} {\n'
        '      incr _bad\n'
        '      set _n [$_mt getName]\n'
        '      if {[info exists _unc($_n)]} { incr _unc($_n) } else { set _unc($_n) 1 }\n'
        '    }\n'
        '  }\n'
        '}\n'
        'set _br {}\n'
        'foreach _n [lsort [array names _unc]] { lappend _br "$_n=$_unc($_n)" }\n'
        'puts "__PG_TERMINALS__ total=$_tot unconnected=$_bad by_pin=[join $_br ,]"\n')
    script = f"""{lib_reads}
{lef_reads}
read_def {def_file}
source {cfg_path}
pdngen
puts "__PDN_CHECK__"
{_pg_probe}{_psm_src}if {{[catch {{check_power_grid -net {pnet}}} _pg_p]}} {{ puts "__PG_ERR__ {pnet}: $_pg_p" }} else {{ puts "__PG_OK__ {pnet}" }}
if {{[catch {{check_power_grid -net {gnet}}} _pg_g]}} {{ puts "__PG_ERR__ {gnet}: $_pg_g" }} else {{ puts "__PG_OK__ {gnet}" }}
write_def {out_def}
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "pdn.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command(["openroad", "-exit", sp])
    proc = subprocess.run(["openroad", "-exit", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "pdn.log"), "w").write(out)
    if proc.returncode != 0 or not os.path.exists(out_def):
        return _cde(objective=f"PDN of {top}", status="failed", pdk_binding=binding or "none",
                    error="OpenROAD pdngen failed; see pdn.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "pdn.log"})
    floating = _count_floating_indicators(out)
    # Real connectivity gate: parse PSM check_power_grid results + count the
    # via instances that actually stitch PDN layers together in the output DEF.
    pg_errors = re.findall(r"__PG_ERR__\s+(.+)", out)
    pg_ok = re.findall(r"__PG_OK__\s+(\S+)", out)
    psm_codes = sorted(set(re.findall(r"PSM-\d+", out)))
    pg_terms = _parse_pg_terminals(out)
    via_info = _count_specialnets_vias(out_def)
    sn_vias = via_info.get("specialnets_vias")
    n_layers = len(via_info.get("stripe_layers") or [])
    pin_info = _count_power_pins(out_def, pnet, gnet)
    n_power_pins = (pin_info or {}).get("power_total", 0)
    # A core-level (padless) macro MUST expose boundary power pins, else PSM has
    # no source terminal (PSM-0025) and the top cannot mate its PDN.
    boundary_pins_ok = (not boundary_pins) or (n_power_pins > 0)
    # PSM check_power_grid is the AUTHORITATIVE connectivity gate: when it ran and
    # explicitly reported OK for BOTH supply nets (__PG_OK__) with no error, the
    # grid is electrically connected regardless of how the DEF encodes vias.
    psm_verified = (not pg_errors) and (pnet in pg_ok) and (gnet in pg_ok)
    # The SPECIALNETS via-count is only a FALLBACK heuristic for the case where
    # PSM did not verify (older/edge cases, or named-via DEF syntax the counter
    # cannot read). Do NOT let a via-parser miss override an explicit PSM pass.
    via_gap = (sn_vias == 0 and n_layers >= 2) and not psm_verified
    # A PG terminal left with no net is a MISSING GLOBAL-CONNECT PATTERN, not a grid
    # defect, and PSM cannot see it: PSM checks the geometry of the nets that EXIST,
    # so a terminal that was never bound to a net is simply absent from its model.
    # Measured on this campaign: PSM reported "all shapes connected" on both nets
    # while every standard cell's VPB/VNB body tie floated, for four stages. So this
    # is its own gate, and a caller who genuinely wants a floating PG terminal must
    # say so explicitly rather than inherit it from a forgotten pattern.
    allow_floating = str(params.get("allow_unconnected_pg_pins", "")).lower() \
        in ("1", "true", "yes")
    pg_terminal_gap = bool(pg_terms and pg_terms["unconnected"] > 0) and not allow_floating
    unmapped_pg = derived_pg.get("unmapped") or []
    connected = ((not pg_errors) and (not via_gap) and (floating == 0)
                 and boundary_pins_ok and not pg_terminal_gap)
    pg_evidence = {
        "pg_pin_patterns": {"power": derived_pg["power"], "ground": derived_pg["ground"],
                            "source": derived_pg["source"], "scope": derived_pg["scope"],
                            "masters_scanned": derived_pg["masters_scanned"]},
        "unmapped_pg_pins": unmapped_pg,
        "pg_terminals": pg_terms,
    }
    if not connected:
        note = []
        if pg_errors:
            note.append("PSM check_power_grid error: " + "; ".join(pg_errors)[:400])
        if via_gap:
            note.append(f"PDN via gap: {n_layers} stripe layers "
                        f"({', '.join(via_info['stripe_layers'])}) but 0 SPECIALNETS vias "
                        f"-> layers isolated")
        if pg_terminal_gap:
            breakdown = ", ".join(
                "%s=%d" % kv for kv in
                sorted((pg_terms.get("unconnected_by_pin") or {}).items()))
            note.append(
                "%d of %d PG-sigtype instance terminals resolve to NO net after "
                "global_connect (%s). Every unmatched pin name needs an "
                "`add_global_connection -pin_pattern` mapping: a body/well tie belongs "
                "to this domain's same-sigtype rail, a SECOND SUPPLY must be declared "
                "via `power_pin_patterns`/`ground_pin_patterns` (never guessed). "
                "Patterns issued this run: power=%s ground=%s%s"
                % (pg_terms["unconnected"], pg_terms["total"], breakdown or "no breakdown",
                   ",".join(derived_pg["power"]), ",".join(derived_pg["ground"]),
                   ("; UNMAPPED second supplies detected: "
                    + ", ".join("%s (%s, %d master(s))"
                                % (u["pin"], u["use"], u["masters"])
                                for u in unmapped_pg)) if unmapped_pg else ""))
        if not boundary_pins_ok:
            note.append("core-level block requested boundary power pins but the "
                        "output DEF has 0 POWER/GROUND pins -> PSM has no source "
                        "terminal (PSM-0025) and top integration cannot mate")
        if floating:
            note.append(f"{floating} floating/unconnected indicator(s) in log")
        return _cde(
            objective=f"power delivery network of {top}",
            status="failed",
            pdk_binding=binding or "none",
            results={"floating_power_nets": {"value": floating, "unit": "count"},
                     "specialnets_vias": {"value": sn_vias, "unit": "count"},
                     "pdn_stripe_layers": {"value": n_layers, "unit": "count"},
                     "boundary_power_pins": {"value": n_power_pins, "unit": "count"},
                     "pg_terminals_total": {
                         "value": (pg_terms or {}).get("total"), "unit": "count"},
                     "pg_terminals_unconnected": {
                         "value": (pg_terms or {}).get("unconnected"), "unit": "count"}},
            signoff=dict({
                "pdn_def": "pdn.def", "connectivity": "disconnected",
                "pdn_connectivity_ok": False, "specialnets_via_count": sn_vias,
                "pdn_stripe_layers": via_info.get("stripe_layers"),
                "boundary_power_pins": boundary_pins,
                "boundary_power_pin_count": n_power_pins,
                "boundary_power_pins_by_net": pin_info,
                "psm_error_codes": psm_codes, "report": "pdn.log",
                "grid_source": grid_source, "hierarchy_mode": hierarchy_mode},
                **pg_evidence),
            inputs_ref={"def_file": def_file, "pdn_config": cfg_path, "tech_lef": tech_lef,
                        "cell_lef": cell_lefs, "liberty": libs},
            assumptions=["grid topology from " + grid_source + "; metal stack from the node"],
            validation={"verdict": "fail", "note": " | ".join(note)},
            provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3), "log": "pdn.log"},
        )

    return _cde(
        objective=f"power delivery network of {top}",
        status="completed",
        pdk_binding=binding or "none",
        results={"floating_power_nets": {"value": floating, "unit": "count"},
                 "specialnets_vias": {"value": sn_vias, "unit": "count"},
                 "pdn_stripe_layers": {"value": n_layers, "unit": "count"},
                 "boundary_power_pins": {"value": n_power_pins, "unit": "count"},
                 "pg_terminals_total": {
                     "value": (pg_terms or {}).get("total"), "unit": "count"},
                 "pg_terminals_unconnected": {
                     "value": (pg_terms or {}).get("unconnected"), "unit": "count"}},
        signoff=dict({
            "pdn_def": "pdn.def", "connectivity": "complete",
            "pdn_connectivity_ok": True, "specialnets_via_count": sn_vias,
            "pdn_stripe_layers": via_info.get("stripe_layers"),
            "psm_verified": psm_verified, "psm_nets_ok": pg_ok,
            "boundary_power_pins": boundary_pins,
            "boundary_power_pin_count": n_power_pins,
            "boundary_power_pins_by_net": pin_info,
            "psm_error_codes": psm_codes, "report": "pdn.log",
            "grid_source": grid_source, "hierarchy_mode": hierarchy_mode},
            **pg_evidence),
        qor={"psm_verified": psm_verified,
             "specialnets_via_count": sn_vias,
             "unconnected_pg_terminals": (pg_terms or {}).get("unconnected")},
        inputs_ref={"def_file": def_file, "pdn_config": cfg_path, "tech_lef": tech_lef,
                    "cell_lef": cell_lefs, "liberty": libs},
        assumptions=["grid topology from " + grid_source + "; metal stack from the node",
                     "global-connect pin patterns are DERIVED from the bound cell LEF's "
                     "PG-sigtype declarations (%s), not from a hand-authored name list; "
                     "power=%s ground=%s"
                     % (derived_pg["scope"], ",".join(derived_pg["power"]),
                        ",".join(derived_pg["ground"]))],
        validation={
            "verdict": "pass",
            # PSM's own solver result, net-agnostic, so a downstream consumer can
            # residual-track the authoritative electrical check instead of a derived
            # ITerm/row proxy -- and a per-net breakdown for the reader.
            "checks": {
                "psm_all_supply_nets_connected": bool(psm_verified),
                "all_pg_terminals_connected": (
                    None if pg_terms is None else pg_terms["unconnected"] == 0),
                "no_unmapped_pg_pin_names": not unmapped_pg,
            },
            "checks_evidence": {
                "psm_all_supply_nets_connected":
                    "pdn.log `__PG_OK__` markers for %s (OpenROAD PSM "
                    "check_power_grid)" % "+".join(pg_ok or [pnet, gnet]),
                "all_pg_terminals_connected":
                    "pdn.log `__PG_TERMINALS__` ODB ITerm walk over every "
                    "POWER/GROUND-sigtype MTerm, broken down by pin name",
                "no_unmapped_pg_pin_names":
                    "signoff_evidence.unmapped_pg_pins (LEF-derived PG-sigtype pin "
                    "names with no declared net mapping)",
            },
            "note": (f"grid connected (PSM check_power_grid OK for {pnet}+{gnet})"
                     if psm_verified else
                     f"grid connected; {sn_vias} SPECIALNETS vias across "
                     f"{n_layers} PDN layers")
                    + (f"; {n_power_pins} boundary power pins for hierarchical "
                       f"integration + PSM source" if boundary_pins else "")
                    + ("; %d/%d PG terminals bound to a net"
                       % (pg_terms["total"] - pg_terms["unconnected"], pg_terms["total"])
                       if pg_terms else "; PG-terminal probe did not run")},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3), "log": "pdn.log"},
    )



def _repair_pdn_vias(params):
    """Remove power-grid vias that cause DRC after detailed routing.

    WHY THIS IS A REAL STAGE AND NOT A NICETY.
    The PDN is built BEFORE routing, so pdngen places its layer-to-layer vias
    against an empty canvas. Detailed routing then fills the same tracks with
    signal wires. A PDN via that was legal on the empty floorplan can end up
    illegal once real routing is beside it -- and because the offending shape
    belongs to a SPECIALNET, no amount of re-running signal routing will move it.
    The result is a DRC violation with no remedy anywhere else in the flow, which
    is exactly the situation this repairs (ORFS `REPAIR_PDN_VIA_LAYER`).

    Owned by chip-pdn rather than chip-routing because the artifact being edited
    is the POWER GRID: one agent owns the grid's construction, its checking, and
    its repair, so the grid never has two authors.

    Ordering matters and is checked: this runs on a ROUTED DEF (post-DRT). Run it
    on an unrouted one and it repairs nothing, because the conflicts it exists to
    remove do not exist yet. The layout is re-checked with check_power_grid
    afterwards, so a repair that disconnected the grid fails here instead of
    surfacing later as an IR-drop anomaly.
    """
    if not shutil.which("openroad"):
        return _cde(objective="PDN via repair", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    def_file = params.get("def_file")
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    for n, v in (("def_file", def_file), ("tech_lef", tech_lef)):
        if not v:
            return _cde(objective="PDN via repair", status="failed",
                        pdk_binding=binding or "none",
                        error=f"missing required field '{n}'",
                        validation={"verdict": "fail"})
    for p in [def_file, tech_lef] + cell_lefs:
        if not os.path.exists(str(p)):
            return _cde(objective="PDN via repair", status="failed",
                        pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})

    pnet = params.get("power_net", "VDD")
    gnet = params.get("ground_net", "VSS")
    nets = _as_list(params.get("nets")) or [pnet, gnet]
    all_nets = str(params.get("all_nets", "")).lower() in ("1", "true", "yes")

    out_def = os.path.join(_OUTPUT_DIR, "pdn_via_repaired.def")
    lef_reads = "\n".join([f"read_lef {tech_lef}"] + [f"read_lef {c}" for c in cell_lefs])
    if all_nets:
        repair_cmds = "repair_pdn_vias -all"
    else:
        repair_cmds = "\n".join("repair_pdn_vias -net %s" % n for n in nets)
    script = f"""{lef_reads}
read_def {def_file}
puts "__VIAS_BEFORE__ [llength [[[[ord::get_db] getChip] getBlock] getVias]]"
{repair_cmds}
puts "__VIAS_AFTER__ [llength [[[[ord::get_db] getChip] getBlock] getVias]]"
if {{[catch {{check_power_grid -net {pnet}}} _e]}} {{ puts "__PG_ERR__ {pnet}: $_e" }} else {{ puts "__PG_OK__ {pnet}" }}
if {{[catch {{check_power_grid -net {gnet}}} _e]}} {{ puts "__PG_ERR__ {gnet}: $_e" }} else {{ puts "__PG_OK__ {gnet}" }}
write_def {out_def}
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "repair_pdn_vias.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command(["openroad", "-exit", sp])
    proc = subprocess.run(["openroad", "-exit", sp], capture_output=True,
                          text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "repair_pdn_vias.log"), "w").write(out)
    if proc.returncode != 0 or not os.path.exists(out_def):
        return _cde(objective="PDN via repair", status="failed",
                    pdk_binding=binding or "none",
                    inputs_ref={"def_file": def_file, "tech_lef": tech_lef},
                    error="OpenROAD repair_pdn_vias failed; see repair_pdn_vias.log:\n"
                          + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "repair_pdn_vias.log"})

    def _marker(name):
        m = re.search(r"__%s__\s+(\d+)" % name, out)
        return int(m.group(1)) if m else None

    before, after = _marker("VIAS_BEFORE"), _marker("VIAS_AFTER")
    removed = (before - after) if (before is not None and after is not None) else None
    pg_errors = re.findall(r"__PG_ERR__\s+(.+)", out)
    pg_ok = re.findall(r"__PG_OK__\s+(\S+)", out)
    # A repair that broke grid connectivity is worse than the DRC it fixed: it
    # trades a geometry violation for an electrical one that only shows up as an
    # IR-drop anomaly much later. Fail closed on it.
    connected = not pg_errors and len(pg_ok) >= 2
    return _cde(
        objective="repair power-grid vias that conflict with detailed routing",
        status="completed", pdk_binding=binding or "none",
        inputs_ref={"def_file": def_file, "tech_lef": tech_lef, "cell_lef": cell_lefs},
        results={"pdn_vias_removed": {"value": removed, "unit": "count"},
                 "grid_still_connected": {"value": connected, "unit": "bool"}},
        qor={"pdn_vias_before": before, "pdn_vias_after": after,
             "pdn_vias_removed": removed},
        signoff={"pdn_def": "pdn_via_repaired.def",
                 "nets_repaired": ("all" if all_nets else nets),
                 "psm_nets_ok": pg_ok, "psm_errors": pg_errors,
                 "log": "repair_pdn_vias.log",
                 "ordering": ("must run on a ROUTED (post-detailed-route) DEF -- "
                              "the via/route conflicts this removes do not exist "
                              "before routing")},
        assumptions=[
            "removed vias are redundant stitches; grid connectivity is re-verified "
            "with check_power_grid after the repair, not assumed"],
        validation={"verdict": "pass" if connected else "fail",
                    "note": ("removed %s conflicting PDN via(s); grid still "
                             "connected on %s" % (removed, ", ".join(pg_ok)))
                    if connected else
                    ("PDN via repair left the grid DISCONNECTED: %s. A repair that "
                     "breaks connectivity trades a DRC violation for an electrical "
                     "one that would surface much later as an IR-drop anomaly."
                     % " | ".join(pg_errors))},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "repair_pdn_vias.log"})


def dispatch(params):
    s = params.get("scenario")
    if s == "build_pdn":
        return _build(params)
    if s in ("repair_pdn_vias", "repair_vias"):
        return _repair_pdn_vias(params)
    return _cde(objective="PDN", status="failed",
                error=f"unknown scenario '{s}'; supported: build_pdn, repair_pdn_vias",
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
