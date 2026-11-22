#!/usr/bin/env python3
"""floorplanning_utils.py -- real OpenROAD floorplanning for the chip-floorplanning
tool.

Reads node LEF/Liberty + gate netlist, runs `initialize_floorplan` at a target
utilization, places I/O pins, writes a floorplan DEF, and parses die/core area and
utilization. LEF/site/tracks come from the PDK binding. Node-aware. Results conform
to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "floorplanning"
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
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _policy(params, binding, *names):
    """Resolve stage settings with caller > binding tool_policy > default."""
    policy = binding.get("tool_policy", {}) if isinstance(binding, dict) else {}
    stage = {}
    for name in names:
        candidate = policy.get(name)
        if isinstance(candidate, dict):
            stage.update(candidate.get("settings", candidate))
    resolved, sources = {}, {}
    for key, default in params.pop("_policy_defaults", {}).items():
        if key in params and params[key] is not None:
            resolved[key], sources[key] = params[key], "caller"
        elif key in stage and stage[key] is not None:
            resolved[key], sources[key] = stage[key], "pdk_binding.tool_policy"
        else:
            resolved[key], sources[key] = default, "tool_default"
    return resolved, sources


def _input_loader(params, binding, objective):
    def_file, odb_file = params.get("def_file"), params.get("odb_file")
    if bool(def_file) == bool(odb_file):
        return None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error="provide exactly one of 'def_file' or 'odb_file'",
            validation={"verdict": "fail"})
    source = odb_file or def_file
    if not os.path.exists(str(source)):
        return None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error=f"input not found: {source}", validation={"verdict": "fail"})
    if odb_file:
        return f"read_db {{{odb_file}}}", {"odb_file": odb_file}, None
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    if not tech_lef:
        return None, None, _cde(
            objective=objective, status="failed", pdk_binding=binding or "none",
            error="missing required field 'tech_lef' (check pdk_binding)",
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
    reads = "\n".join([f"read_lef {{{tech_lef}}}"] +
                        [f"read_lef {{{p}}}" for p in cell_lefs])
    return reads + f"\nread_def {{{def_file}}}", {
        "def_file": def_file, "tech_lef": tech_lef, "cell_lef": cell_lefs}, None


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD", "version": provenance.get("openroad") if provenance else "unknown"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "utilization"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _run_openroad(script, logname):
    sp = os.path.join(_OUTPUT_DIR, "fp.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command(["openroad", "-exit", sp])
    proc = subprocess.run(["openroad", "-exit", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, logname), "w").write(out)
    return proc, out, elapsed


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


def _initialize(params):
    if not shutil.which("openroad"):
        return _cde(objective="floorplan", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    top, netlist = params.get("top"), params.get("netlist")
    binding = params.get("pdk_binding") or {}
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    libs = _as_list(params.get("liberty") or binding.get("liberty"))
    site = params.get("site") or binding.get("site")
    policy_params = dict(params)
    policy_params["_policy_defaults"] = {
        "utilization": 0.5, "core_margin_um": 5.0,
        "aspect_ratio": 1.0, "hor_layer": "met3", "ver_layer": "met2",
        # No default: a routability limit is node/design specific, so an absent
        # one must yield "not assessed", never a tool-invented threshold.
        "max_routable_utilization": None}
    settings, setting_sources = _policy(
        policy_params, binding, "floorplanning", "floorplan")
    # `utilization` is documented and reported as a 0-1 FRACTION (default 0.5;
    # results unit "fraction"). OpenROAD's initialize_floorplan -utilization
    # expects a PERCENTAGE (0-100). Normalize defensively: a value in (0,1] is a
    # fraction; a value in (1,100] is tolerated as an already-percentage form.
    # `util` stays the FRACTION for reporting; hand OpenROAD `util_pct` below.
    util = float(settings["utilization"])
    if not (0 < util <= 100):
        return _cde(objective="floorplan", status="failed", pdk_binding=binding or "none",
                    error=f"utilization {util} out of range; give a 0-1 fraction "
                          f"(e.g. 0.45) or a 0-100 percentage (e.g. 45)",
                    validation={"verdict": "fail"})
    if util > 1:
        util = util / 100.0
    util_pct = util * 100.0
    margin = float(settings["core_margin_um"])
    # aspect_ratio steers die shape (height/width). core_space accepts either a
    # single margin (all four sides, back-compat with core_margin_um) or a
    # 4-element list [bottom, top, left, right] for asymmetric cores.
    aspect_ratio = float(settings["aspect_ratio"])
    _cs = params.get("core_space_um")
    if isinstance(_cs, (list, tuple)) and len(_cs) == 4:
        core_space = " ".join(str(float(x)) for x in _cs)
    elif _cs is not None:
        core_space = str(float(_cs))
    else:
        core_space = str(margin)
    # additional_sites: hierarchical / mixed-row-height designs may need extra
    # site definitions (e.g. double-height rows for macros). Opt-in passthrough.
    _add_sites = params.get("additional_sites")
    _add_sites_opt = ""
    if _add_sites:
        _add_sites_opt = " -additional_sites " + " ".join(_as_list(_add_sites))
    hierarchy_mode = str(params.get("hierarchy_mode", "flat")).strip().lower()
    # Floorplan sizing has two mutually exclusive modes in OpenROAD's
    # initialize_floorplan: RELATIVE (-utilization/-aspect_ratio/-core_space) or
    # ABSOLUTE (-die_area/-core_area, each a 4-number box [llx lly urx ury]).
    # Reject a mix, and require both boxes for the absolute mode.
    die_area = params.get("die_area")
    core_area = params.get("core_area")
    _rel_explicit = any(params.get(k) is not None for k in
                        ("utilization", "aspect_ratio", "core_space_um", "core_margin_um"))
    if die_area is not None or core_area is not None:
        if _rel_explicit:
            return _cde(objective="floorplan", status="failed", pdk_binding=binding or "none",
                        error="absolute sizing (die_area/core_area) and relative "
                              "sizing (utilization/aspect_ratio/core_space) are "
                              "mutually exclusive; provide one mode",
                        validation={"verdict": "fail"})
        if die_area is None or core_area is None:
            return _cde(objective="floorplan", status="failed", pdk_binding=binding or "none",
                        error="absolute floorplan requires BOTH die_area and "
                              "core_area (each [llx lly urx ury])",
                        validation={"verdict": "fail"})
    for n, v in (("top", top), ("netlist", netlist), ("tech_lef", tech_lef), ("site", site)):
        if not v:
            return _cde(objective="floorplan", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}' (check pdk_binding)",
                        validation={"verdict": "fail"})
    for p in [netlist, tech_lef] + cell_lefs + libs:
        if not os.path.exists(str(p)):
            return _cde(objective="floorplan", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    _lef_err = _check_lef_collisions([tech_lef] + cell_lefs)
    if _lef_err:
        return _cde(objective="floorplan", status="failed", pdk_binding=binding or "none",
                    error=_lef_err, validation={"verdict": "fail"})
    out_def = os.path.join(_OUTPUT_DIR, "floorplan.def")
    out_odb = os.path.join(_OUTPUT_DIR, "floorplan.odb")
    lef_reads = "\n".join([f"read_lef {tech_lef}"] + [f"read_lef {c}" for c in cell_lefs])
    lib_reads = "\n".join(f"read_liberty {l}" for l in libs)
    # Assemble the sizing command for the selected mode.
    if die_area is not None:
        _da = " ".join(str(float(x)) for x in _as_list(die_area))
        _ca = " ".join(str(float(x)) for x in _as_list(core_area))
        _fp_cmd = (f"initialize_floorplan -die_area {{{_da}}} "
                   f"-core_area {{{_ca}}} -site {site}{_add_sites_opt}")
        _sizing = {"mode": "absolute", "die_area": _as_list(die_area),
                   "core_area": _as_list(core_area)}
    else:
        # OpenROAD -utilization takes a PERCENTAGE (0-100); pass util_pct, not the
        # 0-1 fraction. Passing the fraction verbatim made 0.45 read as 0.45%,
        # producing a ~100x oversized die (DX-109 / DX-91 floorplan failures).
        _fp_cmd = (f"initialize_floorplan -utilization {util_pct} "
                   f"-aspect_ratio {aspect_ratio} -core_space {core_space} "
                   f"-site {site}{_add_sites_opt}")
        _sizing = {"mode": "relative", "utilization": util,
                   "aspect_ratio": aspect_ratio, "core_space": core_space}
    script = f"""{lib_reads}
{lef_reads}
read_verilog {netlist}
link_design {top}
{_fp_cmd}
make_tracks
place_pins -hor_layers {settings['hor_layer']} -ver_layers {settings['ver_layer']}
report_design_area
report_design_area > {os.path.join(_OUTPUT_DIR, "fp_area.rpt")}
write_def {out_def}
write_db {out_odb}
exit
"""
    proc, out, elapsed = _run_openroad(script, "floorplan.log")
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective=f"floorplan of {top}", status="failed", pdk_binding=binding or "none",
                    error="OpenROAD floorplan failed; see floorplan.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "floorplan.log"})
    # OpenROAD prints, verbatim:  "Design area 1747 um^2 52% utilization."
    #
    # The previous pattern required `u^2` and therefore MATCHED NOTHING, so a
    # perfectly good floorplan reported design_area=None and utilization=None.
    # That is the false-absence class this repo has been burned by repeatedly
    # (logic-synthesis first-vs-last stat, sta DRV, lec partition tally): a regex
    # that silently matches nothing reads downstream as "not measurable" rather
    # than "not measured". Units are matched tolerantly (um^2 / u^2 / um2) so a
    # cosmetic upstream change cannot silently re-open the hole.
    m = re.search(r"Design area\s+([0-9.]+)\s*u?m?\^?2\s+([0-9.]+)\s*%", out)
    area = float(m.group(1)) if m else None
    achieved_util = float(m.group(2)) / 100.0 if m else None
    # FAIL-CLOSED on an unparsed utilization. This previously read
    # `achieved_util is None or achieved_util <= 0.75`, so a FAILED PARSE
    # reported routable=True -- "we could not measure it" became "it is fine",
    # which is the one direction that must never be assumed.
    #
    # The 0.75 THRESHOLD was itself a hardcoded, unsourced node constant: a
    # routability limit depends on the metal stack and the design, so a fixed
    # number is a check that reports the same answer on a 5-layer and a 15-layer
    # node. It now comes from the caller or the binding's tool_policy, and when
    # NOBODY supplied one the verdict is `None` (not assessable) rather than a
    # comparison against a number this tool invented. Utilization is still
    # measured and reported either way -- the missing piece is the limit, not the
    # measurement.
    _util_limit = settings.get("max_routable_utilization")
    _limit_source = setting_sources.get("max_routable_utilization")
    if _util_limit is not None:
        _util_limit = float(_util_limit)
    if achieved_util is None or _util_limit is None:
        routable = None
    else:
        routable = achieved_util <= _util_limit
    routability_basis = (
        "utilization not parsed from the OpenROAD log" if achieved_util is None
        else ("no max_routable_utilization supplied by the caller or the PDK "
              "binding tool_policy; utilization is reported without a verdict "
              "because this tool will not invent a routability limit"
              if _util_limit is None
              else f"achieved utilization vs max_routable_utilization="
                   f"{_util_limit} (source: {_limit_source})"))
    return _cde(
        objective=f"initialize floorplan for {top}",
        status="completed",
        pdk_binding=binding or "none",
        results={"design_area": {"value": area, "unit": "um^2"},
                 "utilization": {"value": achieved_util, "unit": "fraction"}},
        qor={"design_area_um2": area, "target_utilization": util,
             "achieved_utilization": achieved_util,
             "max_routable_utilization": _util_limit},
        signoff={"floorplan_def": "floorplan.def", "floorplan_odb": "floorplan.odb", "site": site,
                 "utilization_routable": routable, "report": "floorplan.log",
                 "max_routable_utilization": _util_limit,
                 "max_routable_utilization_source": _limit_source,
                 "routability_basis": routability_basis,
                 "routability_assessed": routable is not None,
                 "aspect_ratio": aspect_ratio, "core_space": core_space,
                 "sizing": _sizing,
                 "hierarchy_mode": hierarchy_mode},
        inputs_ref={"netlist": netlist, "tech_lef": tech_lef, "cell_lef": cell_lefs,
                    "liberty": libs},
        assumptions=["square aspect ratio; single-region core; no macros in this run",
                     "routability is judged only against a supplied "
                     "max_routable_utilization; none is defaulted"],
        validation={"verdict": ("pass" if routable
                                else ("pass_with_caveats" if routable is False
                                      else "review")),
                    "note": ("utilization within the supplied routable limit"
                             if routable else
                             ("utilization exceeds the supplied routable limit; "
                              "check routability" if routable is False
                              else "routability NOT assessed -- " + routability_basis))},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "floorplan.log", "setting_sources": setting_sources},
    )


def _place_macros(params):
    """Macro placement.

    Two engines, matching production practice:

      * `auto` (default) -> `rtl_macro_placer`, OpenROAD's HIERARCHICAL macro
        placer (MPL). It autoclusters the netlist into a physical hierarchy and
        places macro clusters against a multi-objective cost (area, wirelength,
        outline, boundary, notch, fence, blockage). This is what ORFS drives for
        every macro-bearing design and is the only engine that scales past a
        handful of macros.
      * `manual` -> one `place_macro -macro_name ... -location {x y}
        -orientation ...` per entry in `macro_placements`, for the case where a
        human has already decided the floorplan. Mirrors OpenLane's
        `Odb.ManualMacroPlacement` and ORFS `MACRO_PLACEMENT_TCL`.

    *** THIS ALSO REPAIRS A LIVE DEFECT. *** The previous implementation emitted
    `macro_placement`, which DOES NOT EXIST in the bound OpenROAD
    (26Q3-1305-gf552262465) -- it was removed when MPL2/MPL3 replaced the old
    annealing placer. Every invocation of this scenario failed with an invalid
    command name. Verified by enumerating `info commands` inside the packaged
    image rather than assuming.
    """
    if not shutil.which("openroad"):
        return _cde(objective="macro placement", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    loader, inputs, failure = _input_loader(params, binding, "macro placement")
    if failure:
        return failure

    engine = str(params.get("engine") or "auto").lower()
    if engine not in ("auto", "manual"):
        return _cde(objective="macro placement", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="engine must be 'auto' (rtl_macro_placer) or 'manual' "
                          "(place_macro per instance)",
                    validation={"verdict": "fail"})

    policy_params = dict(params)
    policy_params["_policy_defaults"] = {
        "halo_um": [0.0, 0.0], "channel_um": [0.0, 0.0],
        "snap_layer": None, "style": "corner_min_wl",
        "target_util": None, "min_ar": None, "max_num_level": None,
        "max_num_macro": None, "min_num_macro": None,
        "max_num_inst": None, "min_num_inst": None,
        "area_weight": None, "wirelength_weight": None, "outline_weight": None,
        "boundary_weight": None, "notch_weight": None,
        "fence": None, "keep_clustering_data": False}
    settings, setting_sources = _policy(
        policy_params, binding, "floorplanning", "floorplan")
    halo, channel = _as_list(settings["halo_um"]), _as_list(settings["channel_um"])
    if len(halo) != 2 or len(channel) != 2:
        return _cde(objective="macro placement", status="failed",
                    pdk_binding=binding or "none",
                    error="halo_um and channel_um must each contain [x, y]",
                    validation={"verdict": "fail"})

    out_def = os.path.join(_OUTPUT_DIR, "macros_placed.def")
    out_odb = os.path.join(_OUTPUT_DIR, "macros_placed.odb")
    report_dir = os.path.join(_OUTPUT_DIR, "macro_placement_reports")

    if engine == "manual":
        placements = params.get("macro_placements") or []
        if not isinstance(placements, list) or not placements:
            return _cde(objective="macro placement", status="failed",
                        pdk_binding=binding or "none", inputs_ref=inputs,
                        error="engine='manual' requires a non-empty "
                              "'macro_placements' list of "
                              "{instance, x, y, orientation}",
                        validation={"verdict": "fail"})
        lines = []
        for entry in placements:
            if not isinstance(entry, dict):
                return _cde(objective="macro placement", status="failed",
                            pdk_binding=binding or "none", inputs_ref=inputs,
                            error="each macro_placements entry must be an object",
                            validation={"verdict": "fail"})
            inst = entry.get("instance") or entry.get("macro_name")
            x, y = entry.get("x"), entry.get("y")
            orient = entry.get("orientation") or "R0"
            if not inst or x is None or y is None:
                return _cde(objective="macro placement", status="failed",
                            pdk_binding=binding or "none", inputs_ref=inputs,
                            error="each macro_placements entry needs "
                                  "'instance', 'x' and 'y' (um)",
                            validation={"verdict": "fail"})
            lines.append("place_macro -macro_name {%s} -location {%s %s} "
                         "-orientation %s" % (inst, x, y, orient))
        place_cmds = "\n".join(lines)
        engine_note = "place_macro x%d (human-supplied floorplan)" % len(lines)
    else:
        opts = ""
        # halo_width/-halo_height are MICRONS in rtl_macro_placer, matching halo_um.
        if float(halo[0]) > 0:
            opts += " -halo_width %s" % halo[0]
        if float(halo[1]) > 0:
            opts += " -halo_height %s" % halo[1]
        for key, flag in (("target_util", "-target_util"),
                          ("min_ar", "-min_ar"),
                          ("max_num_level", "-max_num_level"),
                          ("max_num_macro", "-max_num_macro"),
                          ("min_num_macro", "-min_num_macro"),
                          ("max_num_inst", "-max_num_inst"),
                          ("min_num_inst", "-min_num_inst"),
                          ("area_weight", "-area_weight"),
                          ("wirelength_weight", "-wirelength_weight"),
                          ("outline_weight", "-outline_weight"),
                          ("boundary_weight", "-boundary_weight"),
                          ("notch_weight", "-notch_weight")):
            if settings.get(key) is not None:
                opts += " %s %s" % (flag, settings[key])
        fence = _as_list(settings.get("fence"))
        if len(fence) == 4:
            opts += (" -fence_lx %s -fence_ly %s -fence_ux %s -fence_uy %s"
                     % tuple(fence))
        elif fence:
            return _cde(objective="macro placement", status="failed",
                        pdk_binding=binding or "none", inputs_ref=inputs,
                        error="fence must be [lx, ly, ux, uy] in um",
                        validation={"verdict": "fail"})
        if settings.get("keep_clustering_data"):
            opts += " -keep_clustering_data"
        os.makedirs(report_dir, exist_ok=True)
        opts += " -report_directory {%s}" % report_dir
        place_cmds = "rtl_macro_placer" + opts
        engine_note = "rtl_macro_placer (hierarchical MPL autoclustering)"

    script = f"""{loader}
{place_cmds}
write_def {{{out_def}}}
write_db {{{out_odb}}}
exit
"""
    proc, out, elapsed = _run_openroad(script, "place_macros.log")
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective="macro placement", status="failed",
                    pdk_binding=binding or "none",
                    inputs_ref=inputs, error="OpenROAD macro placement failed; see place_macros.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "place_macros.log",
                                "setting_sources": setting_sources})
    return _cde(objective="place macros", status="completed",
                pdk_binding=binding or "none", inputs_ref=inputs,
                results={"macros_placed": {"value": True, "unit": "bool"}},
                qor={"macro_placement_engine": engine},
                signoff={"floorplan_def": "macros_placed.def",
                         "floorplan_odb": "macros_placed.odb",
                         "macro_placement_engine": engine_note,
                         "macro_placement_command": place_cmds.splitlines()[0],
                         "report_directory": ("macro_placement_reports"
                                              if engine == "auto" else None)},
                assumptions=[
                    "rtl_macro_placer autoclusters the netlist into a physical "
                    "hierarchy; cluster sizes are tool-derived unless "
                    "max/min_num_macro/inst are supplied",
                    "macro placement is NOT legalized against standard cells here "
                    "-- rows are cut around the placed macros by the `cut_rows` "
                    "scenario, and cells are legalized by placement"],
                validation={"verdict": "pass", "note": "macro placement completed"},
                provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                            "log": "place_macros.log", "setting_sources": setting_sources})


def _cut_rows(params):
    """Cut placement rows around placed macros.

    A floorplan's rows are created edge-to-edge by `initialize_floorplan`, which
    knows nothing about macros. Once macros are placed, the rows still run
    straight THROUGH them. Cutting removes row segments covered by a macro (plus a
    halo), so the placer cannot legalize a standard cell into a macro's footprint
    and tapcell does not stripe taps across one.

    Both reference flows treat this as mandatory for any macro-bearing design:
    OpenLane runs `OpenROAD.CutRows` between macro placement and
    `TapEndcapInsertion`; ORFS calls it in `floorplan.tcl` for the same reason.
    Omitting it is not a style choice -- it produces overlaps that no later stage
    repairs.

    A design with NO macros is a legitimate no-op: rows are already correct, so
    this reports `not_applicable` rather than inventing work or failing.
    """
    if not shutil.which("openroad"):
        return _cde(objective="cut rows around macros", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    loader, inputs, failure = _input_loader(params, binding, "cut rows around macros")
    if failure:
        return failure

    physical = (binding.get("physical_cells") or {}) if isinstance(binding, dict) else {}
    policy_params = dict(params)
    policy_params["_policy_defaults"] = {
        "macro_halo_um": [10.0, 10.0],
        "row_min_width_um": None,
        "row_min_height_um": None,
        "endcap_master": physical.get("endcap_master")}
    settings, setting_sources = _policy(
        policy_params, binding, "floorplanning", "floorplan")
    halo = _as_list(settings["macro_halo_um"])
    if len(halo) != 2:
        return _cde(objective="cut rows around macros", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="macro_halo_um must contain [x, y] in um",
                    validation={"verdict": "fail"})

    opts = " -halo_width_x %s -halo_width_y %s" % (halo[0], halo[1])
    if settings.get("row_min_width_um") is not None:
        opts += " -row_min_width %s" % settings["row_min_width_um"]
    if settings.get("row_min_height_um") is not None:
        opts += " -row_min_height %s" % settings["row_min_height_um"]
    if settings.get("endcap_master"):
        opts += " -endcap_master %s" % settings["endcap_master"]

    out_def = os.path.join(_OUTPUT_DIR, "rows_cut.def")
    out_odb = os.path.join(_OUTPUT_DIR, "rows_cut.odb")
    script = f"""{loader}
set _blocks [[[ord::get_db] getChip] getBlock]
set _macros 0
foreach _inst [$_blocks getInsts] {{
  if {{[[$_inst getMaster] isBlock]}} {{ incr _macros }}
}}
puts "__MACRO_COUNT__ $_macros"
puts "__ROWS_BEFORE__ [llength [$_blocks getRows]]"
if {{$_macros > 0}} {{
  cut_rows{opts}
}}
puts "__ROWS_AFTER__ [llength [$_blocks getRows]]"
write_def {{{out_def}}}
write_db {{{out_odb}}}
exit
"""
    proc, out, elapsed = _run_openroad(script, "cut_rows.log")
    if proc.returncode != 0 or not os.path.exists(out_def) or not os.path.exists(out_odb):
        return _cde(objective="cut rows around macros", status="failed",
                    pdk_binding=binding or "none", inputs_ref=inputs,
                    error="OpenROAD cut_rows failed; see cut_rows.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "cut_rows.log",
                                "setting_sources": setting_sources})

    def _marker(name):
        m = re.search(r"__%s__\s+(\d+)" % name, out)
        return int(m.group(1)) if m else None

    macros = _marker("MACRO_COUNT")
    before, after = _marker("ROWS_BEFORE"), _marker("ROWS_AFTER")
    applicable = bool(macros)
    return _cde(
        objective="cut placement rows around placed macros",
        status="completed", pdk_binding=binding or "none", inputs_ref=inputs,
        results={"rows_cut": {"value": applicable, "unit": "bool"},
                 "macros_seen": {"value": macros, "unit": "count"}},
        qor={"macro_count": macros, "rows_before": before, "rows_after": after},
        signoff={"floorplan_def": "rows_cut.def", "floorplan_odb": "rows_cut.odb",
                 "cut_rows_options": opts.strip() if applicable else None,
                 "endcap_master": settings.get("endcap_master"),
                 "log": "cut_rows.log"},
        assumptions=[
            "rows are cut around every instance whose master is a BLOCK (macro)",
            "a design with zero macros is a legitimate no-op -- rows already "
            "correct; reported not_applicable rather than fabricating work"],
        validation={"verdict": "pass" if applicable else "not_applicable",
                    "note": ("cut rows around %s macro(s): %s -> %s row segments"
                             % (macros, before, after)) if applicable
                    else "no macros in the design; rows left untouched"},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "cut_rows.log", "setting_sources": setting_sources})


def dispatch(params):
    s = params.get("scenario")
    if s == "initialize_floorplan":
        return _initialize(params)
    if s == "place_macros":
        return _place_macros(params)
    if s in ("cut_rows", "cut_rows_around_macros"):
        return _cut_rows(params)
    return _cde(objective="floorplan", status="failed",
                error=f"unknown scenario '{s}'; supported: initialize_floorplan, "
                      "place_macros, cut_rows",
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
