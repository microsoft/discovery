#!/usr/bin/env python3
"""power_intent_upf_utils.py -- power-intent (UPF) authoring and static checking.

Authors UPF from a structured power architecture, verifies every inter-domain
crossing is isolated/level-shifted per policy, checks power-state-table
completeness and retention/always-on consistency, and requires power-management
cells from the PDK binding. Node-aware. Results conform to the CDE.
"""
import json
import os
import re
import shutil
import subprocess

TOOL = "power-intent-upf"
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


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, inputs_ref=None, error=None,
         qor=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "upf-authoring", "version": "1.0.0"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "static_check"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic UPF static check"},
    }
    if error:
        env["error"] = error
    return env


# UPF commands OpenROAD's reader implements. Measured directly against the
# engine in this image (`info commands <name>`), not copied from a manual.
# Everything a UPF file may legally contain that is NOT in this set is standard
# IEEE 1801 that THIS reader simply does not implement -- a coverage limit, not
# a defect in the authored intent.
_OPENROAD_UPF_COMMANDS = frozenset((
    "read_upf", "write_upf", "create_power_domain", "create_logic_port",
    "create_power_switch", "map_power_switch", "set_isolation",
    "use_interface_cell", "set_domain_area", "set_level_shifter",
    "set_domain_voltage", "set_level_shifter_cell",
))

_STANDARD_UPF_COMMANDS = _OPENROAD_UPF_COMMANDS | frozenset((
    "upf_version", "set_scope", "create_supply_net", "connect_supply_net",
    "create_supply_port", "connect_supply_port", "create_supply_set",
    "set_domain_supply_net", "add_power_state", "add_port_state",
    "create_pst", "add_pst_state", "set_retention", "map_retention_cell",
    "set_retention_control", "set_isolation_control",
))


def _classify_upf_line(line, out, returncode=0):
    """One UPF line -> ('accepted' | 'unsupported_by_reader' | 'no_design' |
    'rejected').

    THE DISTINCTION THAT MATTERS. `create_supply_net`, `connect_supply_net`,
    `upf_version`, `set_scope` and `set_domain_supply_net` are all legitimate
    IEEE 1801, and OpenROAD reports them as `invalid command name`. Calling
    that an authoring defect would be wrong and would train a reader to ignore
    the check. It means the intent is UNVERIFIED by this reader.

    A command the reader DOES implement, failing on its arguments, is a real
    defect -- nothing else in the flow would ever have contradicted it.

    `UPF-0033 No Chip exists` is NEITHER. UPF annotates a LOADED DESIGN, so
    with no design in memory EVERY command fails identically -- valid and
    invalid alike. Measured: a file using only reader-supported commands
    (create_power_domain / set_domain_voltage / set_level_shifter) was
    rejected 3-for-3 that way. Treating it as a defect would make the check
    fail everything, which is exactly as useless as passing everything.
    """
    if re.search(r"UPF-0033|No Chip exists", out):
        return "no_design"
    cmd = (line.split() or [""])[0]
    if re.search(r'invalid command name "%s"' % re.escape(cmd), out):
        return "unsupported_by_reader" if cmd in _STANDARD_UPF_COMMANDS else "rejected"
    if returncode == 0 and "@@UPF_OK@@" in out and not re.search(
            r"\[ERROR\b|invalid command name", out):
        return "accepted"
    return "rejected"


def _upf_design_context(params):
    """Tcl that loads a design so UPF commands have a chip to annotate.

    Returns (tcl, note). Without this every line dies with UPF-0033 and the
    check cannot discriminate at all.
    """
    lefs = params.get("lef") or params.get("tech_lef") or []
    if isinstance(lefs, str):
        lefs = [lefs]
    b = params.get("pdk_binding")
    if isinstance(b, dict):
        for k in ("tech_lef", "cell_lef", "lef"):
            v = b.get(k)
            if isinstance(v, str):
                lefs = lefs + [v]
            elif isinstance(v, list):
                lefs = lefs + v
    lefs = [l for l in dict.fromkeys(lefs) if os.path.isfile(str(l))]
    libs = params.get("liberty") or []
    if isinstance(libs, str):
        libs = [libs]
    if isinstance(b, dict) and b.get("liberty"):
        v = b["liberty"]
        libs = libs + ([v] if isinstance(v, str) else list(v))
    libs = [l for l in dict.fromkeys(libs) if os.path.isfile(str(l))]
    dfile = params.get("def_file") or params.get("design_def")
    if not dfile or not os.path.isfile(str(dfile)) or not lefs:
        return None, ("no design supplied (need `def_file` plus LEFs, or a "
                      "pdk_binding carrying them)")
    tcl = "".join("read_lef %s\n" % l for l in lefs)
    tcl += "".join("read_liberty %s\n" % l for l in libs)
    tcl += "read_def %s\n" % dfile
    return tcl, "design loaded from %s" % os.path.basename(str(dfile))


def _validate_upf(params):
    """Read the authored UPF back with a real engine.

    This agent produced power intent as TEXT and validated it with its own
    opinion; its image did not even contain an EDA tool. A UPF file that no
    reader has ever loaded is an assertion, not an artifact.

    Each executable line is fed to `read_upf` INDEPENDENTLY, because the reader
    aborts the whole file at the first error -- measured: the real generated
    UPF dies on line 1 (`upf_version`), which says nothing about lines 2..14.
    Per-line probing is what makes the classification possible at all.

    Strategy lines are probed with their power domain pre-declared, so a
    `set_isolation` is judged on ITS OWN validity rather than on ordering.
    """
    upf_path = params.get("upf_file") or params.get("upf_path")
    text = params.get("upf")
    if not text:
        if not upf_path or not os.path.isfile(str(upf_path)):
            _authoring = sorted(k for k in ("domains", "supplies", "crossings",
                                            "states") if k in params)
            hint = (" validate_upf READS an existing UPF; it does not author "
                    "one. Run scenario `author_upf` first: its envelope gives "
                    "the file at results.upf_file.value (= results/design.upf "
                    "in that run's output, e.g. /output/results/design.upf or "
                    "wherever that output is mounted for this run, such as "
                    "/input/<prev_run>/results/design.upf) and the full text "
                    "at signoff_evidence.upf_text -- pass the path as "
                    "`upf_file` or the text as `upf`.")
            if _authoring:
                hint += (" Authoring params %s were supplied here; send them "
                         "to author_upf instead." % _authoring)
            return _cde(objective="UPF round-trip validation", status="failed",
                        error=("provide `upf` (text) or `upf_file` (path); "
                               "got upf_file=%r%s.%s"
                               % (upf_path, " (file not found)"
                                  if upf_path else "", hint)),
                        signoff={"expected_upf_from_author_upf":
                                 "results/design.upf",
                                 "authoring_params_supplied": _authoring},
                        validation={"verdict": "fail"})
        text = open(upf_path, encoding="utf-8", errors="replace").read()

    binname = shutil.which("openroad")
    if not binname:
        # NOT a pass. The check did not run.
        return _cde(objective="UPF round-trip validation", status="failed",
                    error=("no UPF reader available: `openroad` is not on "
                           "PATH, so the authored power intent CANNOT be "
                           "validated. Reporting it as acceptable would be a "
                           "check that cannot fail."),
                    validation={"verdict": "not_assessable"})

    lines = [l.strip() for l in text.splitlines()
             if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return _cde(objective="UPF round-trip validation", status="failed",
                    error="UPF contains no executable commands",
                    validation={"verdict": "fail"})

    ctx, ctx_note = _upf_design_context(params)
    work = os.path.join(_WORK_DIR, "upf_rt")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    accepted, unsupported, rejected, no_design = [], [], [], []
    for i, line in enumerate(lines):
        # A strategy needs its domain to exist; declaring it first isolates
        # the line's own validity from file ordering.
        pre = ""
        if re.match(r"set_(isolation|level_shifter|domain_)", line):
            m = re.search(r"-domain\s+(\S+)", line)
            if m:
                pre = "create_power_domain %s\n" % m.group(1)
        one = os.path.join(work, "one.upf")
        with open(one, "w", encoding="utf-8") as fh:
            fh.write(pre + line + "\n")
        tcl = os.path.join(work, "rt.tcl")
        with open(tcl, "w", encoding="utf-8") as fh:
            fh.write((ctx or "")
                     + 'read_upf -file %s\nputs "@@UPF_OK@@"\nexit\n' % one)
        proc = subprocess.run([binname, "-no_init", "-exit", tcl],
                              capture_output=True, text=True, cwd=work)
        out = proc.stdout + proc.stderr
        kind = _classify_upf_line(line, out, proc.returncode)
        with open(os.path.join(work, "line_%d.log" % (i + 1)), "w",
                  encoding="utf-8") as fh:
            fh.write(out)
        why = ""
        m = re.search(r"(\[ERROR [^\]]+\][^\n]*|invalid command name \"[^\"]+\")",
                      out)
        if m:
            why = m.group(1)[:200]
        rec = {"line_number": i + 1, "command": (line.split() or [""])[0],
               "text": line[:200], "detail": why}
        {"accepted": accepted, "unsupported_by_reader": unsupported,
         "rejected": rejected, "no_design": no_design}[kind].append(rec)

    full_upf = os.path.join(work, "complete.upf")
    with open(full_upf, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    with open(tcl, "w", encoding="utf-8") as fh:
        fh.write((ctx or "")
                 + 'read_upf -file %s\nputs "@@UPF_OK@@"\nexit\n' % full_upf)
    full_proc = subprocess.run([binname, "-no_init", "-exit", tcl],
                               capture_output=True, text=True, cwd=work)
    full_out = full_proc.stdout + full_proc.stderr
    full_log = os.path.join(_OUTPUT_DIR, "upf_complete_read.log")
    with open(full_log, "w", encoding="utf-8") as fh:
        fh.write(full_out)
    full_accepted = (full_proc.returncode == 0 and "@@UPF_OK@@" in full_out
                     and not re.search(r"\[ERROR\b|invalid command name", full_out))
    total = len(lines)
    cov = round(100.0 * len(accepted) / total, 2) if total else None
    if no_design:
        # Cannot discriminate: with no chip loaded, valid and invalid commands
        # fail identically.
        verdict = "not_assessable"
        note = (
            "UPF annotates a LOADED DESIGN and none was supplied (%s), so %d "
            "command(s) failed with 'No Chip exists' regardless of whether "
            "they are correct. Supply `def_file` plus LEFs (or a pdk_binding "
            "carrying them) to make this check discriminating."
            % (ctx_note, len(no_design)))
    elif rejected and not full_accepted:
        verdict = "fail"
        note = (
            "%d UPF command(s) were rejected or unrecognized; inspect the "
            "reader diagnostics rather than assuming unsupported intent is valid: %s"
            % (len(rejected), "; ".join(r["command"] for r in rejected[:5])))
    elif unsupported:
        verdict = "not_assessable"
        note = (
            "%d of %d command(s) could not be verified by this reader; "
            "partial command acceptance is not a UPF validation pass."
            % (len(unsupported), total))
    elif not full_accepted:
        verdict = "fail"
        note = ("the complete UPF did not load successfully in the supplied "
                "order; isolated line acceptance does not prove a valid file")
    else:
        verdict = "pass"
        note = ("%d of %d command(s) (%.2f%%) were accepted by the reader"
                % (len(accepted), total, cov))
        note += ("; the complete file loaded in the supplied order "
                 "(reader validation only; isolated diagnostics may lack Tcl context)")

    result = _cde(
        objective="UPF round-trip validation (read_upf)",
        status="completed",
        results={"commands_total": {"value": total, "unit": "count"},
                 "commands_accepted": {"value": len(accepted), "unit": "count"},
                 "commands_rejected": {"value": len(rejected), "unit": "count"}},
        qor={"upf_reader_coverage_pct": cov,
             "commands_total": total,
             "commands_accepted": len(accepted),
             "commands_unsupported_by_reader": len(unsupported),
             "commands_rejected": len(rejected),
             "commands_no_design_context": len(no_design)},
        signoff={"accepted": accepted, "unsupported_by_reader": unsupported,
                 "rejected": rejected, "no_design_context": no_design,
                 "reader": "OpenROAD read_upf", "design_context": ctx_note,
                 "complete_file_read": {
                     "accepted": full_accepted, "engine_exit": full_proc.returncode,
                     "log": full_log},
                 "note": note,
                 "reader_coverage_caveat": (
                     "OpenROAD implements a SUBSET of IEEE 1801. A command "
                     "listed under unsupported_by_reader is valid UPF whose "
                     "intent this reader cannot confirm; it is not evidence "
                     "of a defect, and it is not evidence of correctness "
                     "either.")},
        inputs_ref={"upf_file": upf_path, "def_file": params.get("def_file")},
        validation={"verdict": verdict, "note": note})
    result["provenance"]["engine"] = "OpenROAD read_upf"
    result["tools_used"] = [{"name": "OpenROAD", "version": "not_recorded"}]
    result["margin"]["method"] = "reader_roundtrip"
    return result


def _author(params):
    domains = params.get("domains", [])
    supplies = params.get("supplies", {})
    crossings = params.get("crossings", [])
    states = params.get("states", [])
    binding = params.get("pdk_binding", {})
    cells = (binding or {}).get("power_mgmt_cells", {})
    if not domains or not supplies:
        return _cde(objective="author UPF", status="failed",
                    error="need 'domains' and 'supplies'", validation={"verdict": "fail"})
    if not isinstance(cells, dict):
        cells = {}

    dom_supply = {d["name"]: d.get("supply") for d in domains}
    # WHICH CELL CLASSES THIS INTENT ACTUALLY NEEDS. The binding used to be
    # required to carry power-management cells unconditionally, so a design with
    # ONE always-on domain (nothing to isolate, shift or retain) failed with
    # "power-management cells missing". A class is now required only when the
    # declared intent uses it, and a missing REQUIRED class still fails closed:
    #   * isolation      -- a crossing whose source domain can shut off (or that
    #                       explicitly requests isolation)
    #   * level_shifter  -- a crossing between domains at different voltages (or
    #                       that explicitly requests level shifting)
    #   * retention      -- a retention strategy is requested (a domain state of
    #                       `retention`, or domains[].retention truthy)
    shutoff = set()
    retention_requested = set()
    for d in domains:
        if d.get("shutoff") or d.get("switchable"):
            shutoff.add(d["name"])
        if d.get("retention") or d.get("retention_strategy"):
            retention_requested.add(d["name"])
    for st in states:
        for d, v in (st.get("domain_states") or st.get("domains") or {}).items():
            v = str(v).lower()
            if v in ("off", "retention"):
                shutoff.add(d)
            if v == "retention":
                retention_requested.add(d)
    # With neither a state table nor domain flags, which domains can power down
    # is UNKNOWN, so every crossing is conservatively treated as isolatable.
    shutoff_known = bool(states) or any(
        d.get("shutoff") is not None or d.get("switchable") is not None
        for d in domains)

    # Each crossing between different-voltage domains needs level-shift; a
    # crossing from a domain that can power off needs isolation.
    violations = []
    plan = []
    required_cells = {}
    for c in crossings:
        fs = supplies.get(dom_supply.get(c["from_domain"]))
        ts = supplies.get(dom_supply.get(c["to_domain"]))
        need_ls = fs is not None and ts is not None and fs != ts
        need_iso = (c["from_domain"] in shutoff) if shutoff_known else True
        strat = c.get("strategy", "")
        has_ls = strat in ("level_shift", "both")
        has_iso = strat in ("isolation", "both")
        cr_name = f"{c['from_domain']}->{c['to_domain']}"
        if need_ls and not has_ls:
            violations.append({"crossing": c, "missing": "level_shifter"})
        if need_iso and not has_iso:
            violations.append({"crossing": c, "missing": "isolation"})
        if need_iso or has_iso:
            required_cells.setdefault("isolation", []).append(
                f"crossing {cr_name}"
                + (" (source domain can shut off)" if need_iso and shutoff_known
                   else " (shut-off unknown: no states)" if need_iso
                   else " (isolation requested)"))
        if need_ls or has_ls:
            required_cells.setdefault("level_shifter", []).append(
                f"crossing {cr_name}"
                + (f" ({fs} V -> {ts} V)" if need_ls
                   else " (level shift requested)"))
        plan.append({"crossing": f"{c['from_domain']}->{c['to_domain']}",
                     "level_shift": has_ls, "isolation": has_iso,
                     # Carried through so the UPF emitter can write a REAL
                     # set_isolation: the destination domain owns the strategy,
                     # and the clamp value / isolation supply are caller intent
                     # that must never be invented.
                     "to_domain": c.get("to_domain"),
                     "from_domain": c.get("from_domain"),
                     "clamp_value": c.get("clamp_value"),
                     "isolation_power_net": c.get("isolation_power_net"),
                     # The CONTROL of an isolation cell: which signal clamps
                     # it, at what polarity, and which domain powers it. All
                     # three are accepted flags on set_isolation (measured:
                     # -isolation_signal / -isolation_sense / -location) and
                     # none of them was ever carried out of the crossing, so
                     # the emitted strategy described a cell that nothing
                     # switched.
                     "isolation_signal": c.get("isolation_signal"),
                     "isolation_sense": c.get("isolation_sense"),
                     "isolation_location": c.get("isolation_location")
                     or c.get("location"),
                     "cells": {"isolation": cells.get("isolation"),
                               "level_shifter": cells.get("level_shifter")}})
    # Power-state table completeness: every domain has a state in every mode.
    dom_names = {d["name"] for d in domains}
    incomplete = []
    for st in states:
        ds = st.get("domain_states", {})
        missing = dom_names - set(ds)
        if missing:
            incomplete.append({"state": st.get("name"), "missing_domains": sorted(missing)})
    # Retention: a domain whose state must SURVIVE a power-down needs a
    # retention cell. Retention is required where it is REQUESTED (a domain
    # state of `retention`, or domains[].retention); a domain that merely powers
    # `off` with no retention requested loses its state by design and must be
    # re-initialised on wake -- reported as an explicit caveat, not silently.
    retention_needed = set(retention_requested)
    retention_cell = cells.get("retention")
    shutoff_without_retention = sorted(shutoff - retention_needed)
    if retention_needed:
        required_cells["retention"] = [
            f"domain {d} (retention requested)" for d in sorted(retention_needed)]
    # A gap here is a state-loss bug in silicon (the domain powers down, nothing
    # holds its registers, and it wakes with garbage), so it stays gating.
    retention_gaps = []
    if retention_needed and not retention_cell:
        retention_gaps.append({
            "domains": sorted(retention_needed),
            "missing": "retention",
            "detail": ("%s request state retention across power-down, but the "
                       "PDK binding declares no retention cell, so nothing "
                       "preserves their state across the power-down."
                       % ", ".join(sorted(retention_needed)))})

    # FAIL CLOSED on any cell class the declared intent needs but the binding
    # lacks -- and ONLY on those (see the derivation of required_cells above).
    missing_cells = {k: v for k, v in required_cells.items()
                     if k != "retention" and not cells.get(k)}
    if missing_cells:
        return _cde(objective="author UPF", status="failed",
                    pdk_binding=binding or "none",
                    error=("power-management cell class(es) required by this "
                           "power intent are missing from "
                           "pdk_binding.power_mgmt_cells: %s (%s)"
                           % (", ".join(sorted(missing_cells)),
                              "; ".join(f"{k}: {', '.join(v[:3])}"
                                        for k, v in sorted(missing_cells.items())))),
                    signoff={"required_cell_classes": required_cells,
                             "missing_cell_classes": sorted(missing_cells),
                             "power_mgmt_cells": cells},
                    validation={"verdict": "fail",
                                "note": "fail-closed: required power-management "
                                        "cells absent from the binding"})

    # --- UPF emission --------------------------------------------------------
    # The previous emission was a SKETCH, not UPF: `create_power_domain X` with
    # no -elements, `create_supply_net` with no -domain, `set_isolation` with no
    # -isolation_power_net / -clamp_value / -applies_to, and NO supply ports, no
    # port-to-net connection, and no power state table at all. No UPF-consuming
    # tool would accept it, so the file looked like power intent while carrying
    # none of the information that makes power intent checkable.
    #
    # Anything the caller did not supply is NOT invented -- a fabricated clamp
    # value or an assumed always-on domain would be silently synthesized into the
    # design. Missing pieces are emitted as explicit TODO comments and reported
    # in `upf_gaps` so the file is honestly incomplete rather than quietly wrong.
    upf_gaps = []
    # UPF PROFILE. The emitter used to write full IEEE 1801 that OpenROAD's
    # reader cannot load: measured on real output, 11 of 14 executable lines
    # were rejected and the file died on line 1 (`upf_version`).
    #
    # NARROWING IS NOT DELETION. `create_supply_port`, `create_supply_net`,
    # `connect_supply_net`, `set_domain_supply_net`, `add_power_state`,
    # `set_scope` and `upf_version` are all legitimate IEEE 1801, and a
    # commercial tool with fuller support would consume them. Dropping them
    # outright would DESTROY power intent to make a checker happy. So under the
    # `openroad` profile they are retained VERBATIM as `#[ieee1801]` comment
    # lines -- still readable, still reviewable, still greppable -- while the
    # executable body is restricted to what the reader implements.
    #
    # Where a supported command can carry the SAME intent it is now emitted, so
    # the profile is partly additive rather than purely subtractive (all
    # measured ACCEPTED against the engine in this image):
    #   * supply voltage      -> set_domain_voltage -domain D -voltage V
    #   * isolation control   -> create_logic_port <signal> -direction in
    #   * power-mgmt cell     -> use_interface_cell -domain D -strategy S -lib_cells {...}
    profile = str(params.get("upf_profile") or "openroad").lower()
    if profile not in ("openroad", "ieee1801"):
        return _cde(objective="author UPF", status="failed",
                    error=("unknown upf_profile %r; use 'openroad' (reader-"
                           "loadable, default) or 'ieee1801' (full standard)"
                           % profile), validation={"verdict": "fail"})
    _or = profile == "openroad"

    def _std(line):
        """Emit an IEEE 1801 line the OpenROAD reader cannot execute.

        Under the openroad profile it is preserved as a comment rather than
        dropped: the intent survives review and downstream tools, but the file
        still loads.
        """
        upf_lines.append(("#[ieee1801] " + line) if _or else line)

    upf_lines = [
        "# UPF 3.0 power intent (generated)",
        "# profile: %s -- %s" % (
            profile,
            ("executable body restricted to commands OpenROAD's read_upf "
             "implements; lines marked #[ieee1801] are valid standard UPF "
             "this reader cannot execute and are preserved, not dropped")
            if _or else
            "full IEEE 1801; NOT loadable by OpenROAD's read_upf"),
    ]
    _std("upf_version 3.0")
    upf_lines += ["", "# ---- supply ports and nets ----"]
    top_scope = params.get("top") or params.get("design") or "."
    _std(f"set_scope {top_scope}")
    upf_lines.append("")
    for name, v in supplies.items():
        _std(f"create_supply_port {name} -domain {domains[0]['name']}"
             if domains else f"create_supply_port {name}")
        _std(f"create_supply_net {name}"
             + (f" -domain {domains[0]['name']}" if domains else ""))
        _std(f"connect_supply_net {name} -ports {{{name}}}")
        upf_lines.append(f"# nominal voltage: {v} V")
    if not supplies:
        upf_gaps.append("no supplies declared: the UPF has no supply ports or nets")
    upf_lines += ["", "# ---- power domains ----"]
    for d in domains:
        elements = d.get("elements") or d.get("instances")
        if elements:
            upf_lines.append(
                f"create_power_domain {d['name']} -elements {{{' '.join(elements)}}}")
        else:
            # -elements is what BINDS a domain to logic. Without it the domain
            # contains nothing and no isolation/retention can be placed.
            upf_lines.append(f"create_power_domain {d['name']}")
            upf_lines.append(
                f"# TODO(-elements): no instances declared for {d['name']}; this "
                f"domain is EMPTY and binds to no logic")
            upf_gaps.append(f"power domain '{d['name']}' declares no -elements, so "
                            f"it binds to no logic")
        prim = d.get("supply") or d.get("primary_supply")
        gnd = d.get("ground") or "VSS"
        if prim:
            _std(f"set_domain_supply_net {d['name']} "
                 f"-primary_power_net {prim} -primary_ground_net {gnd}")
            # The VOLTAGE of that supply IS expressible to this reader, so the
            # part of the intent that can be machine-checked is emitted as a
            # real command rather than lost with the comment above.
            volts = supplies.get(prim)
            if volts is not None:
                upf_lines.append(
                    f"set_domain_voltage -domain {d['name']} -voltage {volts}")
        else:
            upf_gaps.append(f"power domain '{d['name']}' has no primary power net")
    upf_lines += ["", "# ---- power state table ----"]
    if states:
        for st in states:
            sname = st.get("name") or st.get("state")
            # KEY MISMATCH, pre-existing. The completeness check above reads
            # `domain_states`, the documented schema and every example use
            # `domain_states`, and this loop read `domains` -- which is never
            # present, so the per-domain lookup always missed and NOT A SINGLE
            # add_power_state line was ever emitted. Confirmed on real output:
            # a run with ACTIVE and SLEEP states produced only the summary
            # comment and no state commands at all. Both spellings accepted.
            _ds = st.get("domain_states") or st.get("domains") or {}
            for d in domains:
                dstate = _ds.get(d["name"])
                if dstate:
                    _std(
                        f"add_power_state {d['name']} -state {{{sname}_{d['name']} "
                        f"-logic_expr {{power_state == {dstate}}}}}")
        pst_states = [s.get("name") or s.get("state") for s in states]
        upf_lines.append(f"# power states declared: {', '.join(map(str, pst_states))}")
    else:
        upf_lines.append("# TODO: no power states supplied; the PST is EMPTY, so "
                         "no state-dependent isolation or retention can be checked")
        upf_gaps.append("no power state table: state-dependent intent is unverifiable")
    upf_lines += ["", "# ---- isolation / level shifting ----"]
    _declared_ports = set()
    for p in plan:
        cr = p["crossing"]
        if p["isolation"]:
            line = (f"set_isolation iso_{cr} -domain {p.get('to_domain', cr)} "
                    f"-applies_to outputs")
            clamp = p.get("clamp_value")
            if clamp is None:
                upf_lines.append(
                    f"# TODO(-clamp_value): the value {cr} must clamp to during "
                    f"power-down was not supplied and is NOT assumed")
                upf_gaps.append(f"isolation on '{cr}' has no clamp_value")
            else:
                line += f" -clamp_value {clamp}"
            # `-isolation_power_net` IS NOT A UPF FLAG. Measured against the
            # reader: `[ERROR STA-0562] set_isolation -isolation_power_net is
            # not a known keyword or flag`. It was emitted on every isolated
            # crossing and nothing ever contradicted it, because no reader had
            # ever loaded the file. The accepted flag set is exactly
            # -domain / -applies_to / -clamp_value / -isolation_signal /
            # -isolation_sense / -location / -update.
            sig = p.get("isolation_signal")
            if sig:
                if sig not in _declared_ports:
                    upf_lines.append(f"create_logic_port {sig} -direction in")
                    _declared_ports.add(sig)
                line += f" -isolation_signal {sig}"
                sense = p.get("isolation_sense")
                if sense:
                    line += f" -isolation_sense {sense}"
            else:
                upf_gaps.append(
                    f"isolation on '{cr}' has no isolation_signal, so nothing "
                    f"controls when the isolation cell clamps")
            loc = p.get("isolation_location")
            if loc:
                line += f" -location {loc}"
            else:
                upf_gaps.append(
                    f"isolation on '{cr}' has no location, so which domain "
                    f"powers the isolation cell is undeclared")
            upf_lines.append(line)
            # The caller's isolation-supply intent is PRESERVED, not dropped.
            # It is not a flag `set_isolation` accepts, so writing it into the
            # command is what produced STA-0562; recording it keeps the intent
            # visible for a tool that can consume it.
            iso_net = p.get("isolation_power_net")
            if iso_net:
                upf_lines.append(
                    f"# isolation supply intent for {cr}: {iso_net} "
                    f"(not expressible on set_isolation in this reader)")
            # Bind the PDK isolation cell to the strategy. The binding already
            # carried this cell and the emitter never wrote it out, so the
            # strategy named no implementation at all.
            iso_cell = (p.get("cells") or {}).get("isolation")
            if iso_cell:
                upf_lines.append(
                    f"use_interface_cell -domain {p.get('to_domain', cr)} "
                    f"-strategy iso_{cr} -lib_cells {{{iso_cell}}} iso_impl_{cr}")
        if p["level_shift"]:
            upf_lines.append(
                f"set_level_shifter ls_{cr} -domain {p.get('to_domain', cr)} "
                f"-applies_to inputs -rule both -location self")
    for rg in retention_gaps:
        upf_lines.append(f"# TODO(retention): {rg['detail']}")
    for d in shutoff_without_retention:
        upf_lines.append(f"# NOTE(no-retention): {d} powers off with no retention "
                         f"requested; its state is lost and must be re-initialised")
    upf_text = "\n".join(upf_lines) + "\n"
    open(os.path.join(_OUTPUT_DIR, "design.upf"), "w").write(upf_text)
    # _organize_output() moves *.upf into results/, so that is where the file
    # lives in the run output; spelled out so validate_upf can be chained.
    upf_rel = "results/design.upf"
    upf_abs = os.path.join(_OUTPUT_DIR, "results", "design.upf")

    # WHAT WAS NEVER SUPPLIED IS NOT WHAT WAS CHECKED AND FOUND CLEAN.
    # `crossings` and `states` are caller-supplied lists, so an empty one drives
    # zero loop iterations, accumulates zero violations, and previously read as
    # `pass`. MEASURED: two power domains with NO crossings declared, and a
    # design with NO power-state table at all, both returned verdict `pass` --
    # "an empty state table is complete".
    #
    # The tool cannot derive these from anything it holds: it never sees the
    # netlist, so it cannot know whether a crossing list is complete. It can
    # only report that it was given nothing to check.
    unverified = []
    if not crossings and len(domains) > 1:
        unverified.append(
            "no crossings supplied: isolation and level-shift were NOT checked "
            "on any boundary. With %d domains declared this is an absence of "
            "evidence, not a clean result." % len(domains))
    if not states:
        unverified.append(
            "no power-state table supplied: state-table completeness and "
            "retention need were NOT assessed.")

    ok = not violations and not incomplete and not retention_gaps
    if unverified and ok:
        verdict = "not_assessable"
        note = "; ".join(unverified)
    elif ok and upf_gaps:
        # The intent CHECKS passed, but the emitted UPF cannot be consumed as
        # written. Reporting a clean pass here would hand the next stage a file
        # that names domains binding to no logic and isolation with no clamp.
        verdict = "not_assessable"
        note = ("power intent is self-consistent, but the emitted UPF is "
                "INCOMPLETE and no tool can act on it as written: "
                + "; ".join(upf_gaps[:4])
                + (f" (+{len(upf_gaps) - 4} more)" if len(upf_gaps) > 4 else ""))
    elif ok:
        verdict, note = "pass", "power intent consistent and the emitted UPF is complete"
    else:
        verdict = "fail"
        note = "isolation/level-shift, state-table or retention issues"
    if shutoff_without_retention:
        note += ("; caveat: %s power(s) off with no retention requested -- state "
                 "is lost across power-down" % ", ".join(shutoff_without_retention))
    note += "; UPF written to %s (pass as validate_upf `upf_file`, or pass " \
            "signoff_evidence.upf_text as `upf`)" % upf_rel
    return _cde(
        objective="author and check power intent (UPF)",
        status="completed" if ok else "failed",
        pdk_binding=binding or "none",
        results={"upf_file": {"value": upf_rel, "unit": "path",
                              "path_in_run": upf_abs,
                              "note": ("authored UPF; chain to validate_upf "
                                       "via `upf_file` (path as mounted in the "
                                       "next run) or `upf` (= signoff_evidence."
                                       "upf_text)")},
                 "domains": {"value": len(domains), "unit": "count"},
                 "crossings": {"value": len(crossings), "unit": "count"},
                 "violations": {"value": len(violations), "unit": "count",
                                "class": "gating",
                                "basis": "declared_crossings_only",
                                "closes_at": "== 0"},
                 "retention_gaps": {
                     "value": len(retention_gaps), "unit": "count",
                     "class": "gating",                      "basis": "requested_retention_vs_pdk_cells",
                     "closes_at": "== 0",
                     "note": ("A domain that requests state retention with no "
                              "retention cell in the binding loses its state "
                              "across the power-down.")}},
        signoff={"upf": "design.upf", "upf_file": upf_rel,
                 "upf_path_in_run": upf_abs, "upf_text": upf_text,
                 "required_cell_classes": required_cells,
                 "shutoff_domains": sorted(shutoff),
                 "shutoff_known": shutoff_known,
                 "shutoff_without_retention": shutoff_without_retention,
                 "isolation_level_shift_plan": plan,
                 "violations": violations,
                 # What the emitted UPF could NOT state, because the caller did
                 # not supply it. A UPF that omits -elements or -clamp_value is
                 # not a smaller UPF; it is one a tool cannot act on.
                 "upf_gaps": upf_gaps or None,
                 "upf_complete": not upf_gaps,
                 "power_state_table": states,
                 "incomplete_states": incomplete,
                 "retention_domains": sorted(retention_needed),
                 "retention_cell": retention_cell,
                 "retention_gaps": retention_gaps,
                 "unverified": unverified or None,
                 "coverage_note": ("Crossings and states are CALLER-SUPPLIED. "
                                   "This tool does not read the netlist, so it "
                                   "cannot know whether the crossing list is "
                                   "complete -- it checks what it was given and "
                                   "says so.")},
        inputs_ref={"domains": list(dom_names)},
        assumptions=["level-shift required when supply voltages differ; isolation "
                     "required on a crossing whose source domain can power off "
                     "(on every crossing when no state table/shutoff flags are "
                     "given)",
                     "power-management cells are required only for the classes "
                     "the intent uses (isolation / level_shifter / retention)",
                     "a domain that requests retention (state `retention` or "
                     "domains[].retention) requires a retention cell; a domain "
                     "that is merely `off` loses its state (caveat, not gating)"],
        validation={"verdict": verdict, "note": note},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("author_upf", "power_state_table", "low_power_check"):
        return _author(params)
    if s in ("validate_upf", "upf_round_trip", "read_upf"):
        return _validate_upf(params)
    return _cde(objective="power intent", status="failed",
                error=f"unknown scenario '{s}'", validation={"verdict": "fail"})


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
