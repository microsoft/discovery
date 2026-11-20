#!/usr/bin/env python3
"""library_characterization_utils.py -- cell characterization + view generation.

characterize_liberty: builds and runs a real ngspice transient deck sweeping input
slew x output load, measures propagation delay via .measure, and assembles an NLDM
Liberty timing table. create_lef / create_def: generate physical abstract views.
Node-aware: SPICE models/corners come from the PDK binding. Results conform to the
Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess

TOOL = "library-characterization"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


def _is_ident(s):
    """True if *s* is a safe cell identifier -- blocks script/path injection via
    user-supplied cell names interpolated into SPICE decks, LEF/DEF, and the
    output filenames of generated library views."""
    return bool(s) and bool(re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", str(s)))


def _subckt_ports(netlist_path, cell):
    """Parse the ordered port list from the `.subckt <cell> p1 p2 ...` header in
    *netlist_path* (handles `+` line continuations, case-insensitive). Returns the
    port-name list in declaration order, or None if the subckt is not found.

    This is the fix for the class of defect where the characterization deck
    hard-wired a fixed 4-node instantiation (in, out, VPWR, VGND) regardless of
    the real subckt arity. Real extracted std cells (e.g. sky130
    `A Y VGND VNB VPB VPWR`) expose 6 ports including body ties; instantiating a
    6-port subckt with 4 nodes leaves nodes floating and the transient fails to
    converge. Reading the actual header lets us bind every declared port."""
    try:
        with open(netlist_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception:
        return None
    # stitch line continuations: a line starting with '+' appends to the previous
    lines = []
    for ln in raw.splitlines():
        s = ln.rstrip()
        if s.lstrip().startswith("+") and lines:
            lines[-1] += " " + s.lstrip()[1:].strip()
        else:
            lines.append(s)
    pat = re.compile(r"^\s*\.subckt\s+(\S+)\s+(.*)$", re.IGNORECASE)
    for ln in lines:
        m = pat.match(ln)
        if m and m.group(1).lower() == str(cell).lower():
            toks = m.group(2).split()
            # strip any name=value parameter tokens from the port list
            ports = [t for t in toks if "=" not in t]
            return ports or None
    return None


# Canonical rail-name classes for binding subckt ports to the char-deck nets.
_PWR_NAMES = ("VPWR", "VDD", "VCC", "VDDA", "VPB_PWR")
_GND_NAMES = ("VGND", "VSS", "GND", "VSSA")
_NWELL_TIE = ("VPB", "VNW", "NWELL", "VPP")   # n-well / p-body tie -> power rail
_PSUB_TIE = ("VNB", "VPW", "PSUB", "VBB")     # p-substrate / n-body tie -> ground


def _bind_subckt_nodes(ports, in_pin, out_pin, vpwr="VPWR", vgnd="VGND"):
    """Given the declared subckt *ports*, return (node_list, warnings) binding each
    port to a char-deck net: the input pin, the output pin, the power/ground rails,
    and body ties (n-well tie->power, p-substrate tie->ground). Unknown extra pins
    are tied to ground with a warning so the instantiation is never left floating."""
    nodes, warns = [], []
    for p in ports:
        pu = p.upper()
        if p == in_pin:
            nodes.append(in_pin)
        elif p == out_pin:
            nodes.append(out_pin)
        elif pu in _PWR_NAMES:
            nodes.append(vpwr)
        elif pu in _GND_NAMES:
            nodes.append(vgnd)
        elif pu in _NWELL_TIE:
            nodes.append(vpwr)
        elif pu in _PSUB_TIE:
            nodes.append(vgnd)
        else:
            nodes.append(vgnd)
            warns.append(p)
    return nodes, warns


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


def _ngspice_version():
    try:
        out = subprocess.run(["ngspice", "-v"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip().split("\n")[0]
    except Exception:
        return "unknown"


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None, margin=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "ngspice", "version": _ngspice_version()}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {},
        "margin": margin or {"method": "characterization"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


#: ngspice wordings that mean the solve did not converge or the run aborted. The
#: stage declares `spice_nonconvergence: block` in its gate criteria, but nothing
#: ever looked for one: a non-convergent grid point simply returned no .measure
#: match, was recorded as a None in the delay table, and was then indistinguishable
#: from a point that was never requested. Since a Liberty table writes "0" for a
#: None, a non-convergent characterization silently produced a library full of
#: ZERO DELAYS -- which every downstream timing stage would happily close against.
_NONCONVERGENCE_PATTERNS = (
    "singular matrix", "no convergence", "convergence failure",
    "timestep too small", "iteration limit reached", "too many iterations",
    "gmin stepping failed", "source stepping failed",
    "dynamic gmin stepping failed", "transient analysis failed",
    "matrix is singular", "fatal error",
    "run simulation(s) aborted", "analysis not run", "doanalyses: not found",
    "no data saved",
)

#: Accumulates non-convergence signatures seen across every deck of a run so the
#: envelope can gate on them. Reset at the start of each characterization.
_SPICE_ISSUES = []


def _scan_spice_health(text):
    """Return the non-convergence signatures present in an ngspice log."""
    low = (text or "").lower()
    return [p for p in _NONCONVERGENCE_PATTERNS if p in low]


def _run_ngspice(deck, tag=None):
    dpath = os.path.join(_OUTPUT_DIR, "char.sp")
    open(dpath, "w").write(deck)
    _save_run_command(["ngspice", "-b", dpath])
    proc = subprocess.run(["ngspice", "-b", dpath], capture_output=True, text=True, cwd=_WORK_DIR)
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "ngspice.log"), "a").write(out)
    hits = _scan_spice_health(out)
    if hits:
        _SPICE_ISSUES.append({"point": tag or "unnamed", "signatures": hits})
    return proc.stdout + proc.stderr


def _characterize(params):
    # Reset per-run SPICE health so signatures never leak between invocations
    # (a stale hit would fail an unrelated later run, and a missed reset would
    # hide a real one behind an earlier clean run).
    del _SPICE_ISSUES[:]
    cell = params["cell"]
    netlist = params.get("cell_netlist")
    models = (params.get("pdk_binding") or {}).get("spice_models") or params.get("spice_models")
    if not netlist or not os.path.exists(str(netlist)):
        return _cde(objective=f"characterize {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="cell_netlist (subckt) path required and must exist",
                    validation={"verdict": "fail"})
    if not models or not os.path.exists(str(models)):
        return _cde(objective=f"characterize {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="SPICE device models required from pdk_binding.spice_models",
                    validation={"verdict": "fail"})
    in_pin = params.get("in_pin", "A")
    out_pin = params.get("out_pin", "Y")
    vdd = float(params.get("vdd", 1.8))
    # Resolve the real subckt port order so the DUT instantiation binds every
    # declared pin (input, output, rails, body ties). An explicit `ports` param
    # overrides; otherwise parse the `.subckt` header; else fall back to the
    # legacy 4-node [in, out, VPWR, VGND] order for simple 4-port cells.
    _ports = params.get("ports") or _subckt_ports(str(netlist), cell)
    if _ports:
        _dut_nodes, _dut_warns = _bind_subckt_nodes(_ports, in_pin, out_pin)
    else:
        _dut_nodes, _dut_warns = [in_pin, out_pin, "VPWR", "VGND"], []
    _dut_order = " ".join(_dut_nodes)
    slews = params.get("slews", [0.05, 0.2, 0.8])   # ns
    loads = params.get("loads", [0.005, 0.02, 0.08])  # pF
    # Tier-1 ngspice characterization levers (all backward-compatible: the fall
    # arc is always produced, matching prior behavior).
    #   measure_rise        : also characterize the rise arc (cell_rise) so the
    #                         NLDM has both edges. ngspice: .measure ... FALL/RISE.
    #   measure_output_slew : record 20%-80% output transition per grid point
    #                         (Liberty transition tables).
    #   measure_power       : integrate supply current over the switching window
    #                         to report switching energy (charge x vdd).
    #   temp_c              : simulation temperature via .options temp=... (per
    #                         corner). sim_reltol: transient convergence tolerance.
    measure_rise = str(params.get("measure_rise", True)).lower() not in ("0", "false", "no")
    measure_output_slew = str(params.get("measure_output_slew", True)).lower() not in ("0", "false", "no")
    measure_power = str(params.get("measure_power", False)).lower() in ("1", "true", "yes")
    temp_c = params.get("temp_c")
    sim_reltol = params.get("sim_reltol")
    # Timing model type: "nldm" (default, table-lookup delay) or "ccs" (Composite
    # Current Source). CCS additionally requires (a) the receiver input pin
    # capacitance measured from the DUT and (b) driver output-current waveforms
    # i(Cl)=Cl*dV/dt tabulated across the slew x load grid.
    # Accept either `model_type` (internal name) or `model` (the tool.yaml/agent
    # param name) so a caller passing {"model":"ccs"} actually gets a CCS build.
    model_type = str(params.get("model_type", params.get("model", "nldm"))).lower()
    if model_type not in ("nldm", "ccs"):
        model_type = "nldm"
    # measure_input_cap: measure the receiver pin capacitance Cin = |dQ/dV| on the
    # input pin (always on for CCS; opt-in for NLDM). ccs_current_points sets how
    # many time samples of the output-current waveform are tabulated per arc.
    # Incompatible request: a CCS model REQUIRES the input capacitance, so
    # model_type=ccs with measure_input_cap explicitly disabled is contradictory.
    _mic_raw = params.get("measure_input_cap")
    _mic_explicit_false = (_mic_raw is not None
                           and str(_mic_raw).lower() in ("0", "false", "no"))
    if model_type == "ccs" and _mic_explicit_false:
        return _cde(objective=f"characterize {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="model_type=ccs requires input-pin capacitance; "
                          "measure_input_cap cannot be disabled for a CCS model",
                    validation={"verdict": "fail"})
    measure_input_cap = (model_type == "ccs") or \
        str(params.get("measure_input_cap", False)).lower() in ("1", "true", "yes")
    ccs_current_points = int(params.get("ccs_current_points", 8))
    _opts = []
    if temp_c is not None:
        _opts.append(f".options temp={float(temp_c)}")
    if sim_reltol is not None:
        _opts.append(f".options reltol={float(sim_reltol)}")
    _opts_block = ("\n".join(_opts) + "\n") if _opts else ""

    # Fall (index by slew x load) plus optional rise / output-slew / energy tables.
    table = []          # cell_fall delays [ns]
    rise_table = []     # cell_rise delays [ns]
    fall_slew = []      # output fall transition [ns]
    rise_slew = []      # output rise transition [ns]
    energy_table = []   # switching energy [fJ]
    ccs_fall_current = []   # per grid point: list of {t_ns, i_ua} output current
    ccs_rise_current = []

    # --- Receiver input-pin capacitance (once) -------------------------------
    # Drive the input pin through a known series resistor with a ramp and measure
    # the integral of the current into the pin: Cin = Q / dV = INTEG(i)/vdd.
    input_cap_ff = None
    if measure_input_cap:
        _cap_deck = f"""* input-pin capacitance of {cell}
{_opts_block}.include {models}
.include {netlist}
Vdd VPWR 0 {vdd}
Vss VGND 0 0
Vsrc nsrc 0 PWL(0 0 1n 0 2n {vdd})
Vinsense nsrc {in_pin} 0
Xdut {_dut_order} {cell}
Cl {out_pin} 0 0.01p
.tran 1p 4n
.measure tran qin INTEG i(Vinsense) FROM=1n TO=2n
.end
"""
        _cap_out = _run_ngspice(_cap_deck, tag="input_cap")
        _mq = re.search(r"qin\s*=\s*([0-9.eE+-]+)", _cap_out)
        if _mq is not None:
            # Q accumulated while V ramps 0->vdd over the window; Cin = Q/vdd.
            input_cap_ff = abs(float(_mq.group(1))) / vdd * 1e15  # fF

    for tr in slews:
        row, rrow, fslw, rslw, erow = [], [], [], [], []
        cf_row, cr_row = [], []
        for cl in loads:
            # Two-edge input (rise then fall) so a single transient yields both
            # the output fall (from the input rise) and output rise (input fall)
            # arcs for an inverting cell.
            _t1 = 1.0 + tr           # input reaches vdd
            _t2 = 4.0                # input starts falling
            _t3 = _t2 + tr           # input reaches 0
            meas = [f".measure tran tphl TRIG v({in_pin}) VAL={vdd/2} RISE=1 "
                    f"TARG v({out_pin}) VAL={vdd/2} FALL=1"]
            if measure_rise:
                meas.append(f".measure tran tplh TRIG v({in_pin}) VAL={vdd/2} FALL=1 "
                            f"TARG v({out_pin}) VAL={vdd/2} RISE=1")
            if measure_output_slew:
                meas.append(f".measure tran oslew_f TRIG v({out_pin}) VAL={0.8*vdd} FALL=1 "
                            f"TARG v({out_pin}) VAL={0.2*vdd} FALL=1")
                meas.append(f".measure tran oslew_r TRIG v({out_pin}) VAL={0.2*vdd} RISE=1 "
                            f"TARG v({out_pin}) VAL={0.8*vdd} RISE=1")
            if measure_power:
                # Integral of supply current over the analysis window = net charge;
                # switching energy ~= vdd * |charge|.
                meas.append(f".measure tran qsupply INTEG i(Vdd) FROM=0 TO=8n")
            # CCS: sample the driver output current i(VsenseCL) at a set of
            # output-voltage crossings across each switching arc. Sampling by
            # output voltage (not fixed time) self-centers on the transition
            # regardless of cell speed, giving current-vs-voltage points that are
            # exactly what a Composite Current Source model tabulates.
            ccs_levels = []
            if model_type == "ccs":
                for k in range(ccs_current_points):
                    frac = (k + 0.5) / ccs_current_points   # in (0,1)
                    ccs_levels.append(round(frac * vdd, 6))
                    lvl = frac * vdd
                    meas.append(f".measure tran icf{k} FIND i(VsenseCL) "
                                f"WHEN v({out_pin})={lvl} FALL=1")
                    meas.append(f".measure tran icr{k} FIND i(VsenseCL) "
                                f"WHEN v({out_pin})={lvl} RISE=1")
                    # Capture the crossing TIME too: a CCS output_current vector
                    # is current-vs-time (index_3 = time), so each sample needs
                    # both the current and the instant it occurs.
                    meas.append(f".measure tran tcf{k} WHEN v({out_pin})={lvl} FALL=1")
                    meas.append(f".measure tran tcr{k} WHEN v({out_pin})={lvl} RISE=1")
            deck = f"""* NLDM characterization of {cell}
{_opts_block}.include {models}
.include {netlist}
Vdd VPWR 0 {vdd}
Vss VGND 0 0
Vin {in_pin} 0 PWL(0 0 1n 0 {_t1}n {vdd} {_t2}n {vdd} {_t3}n 0)
Xdut {_dut_order} {cell}
VsenseCL {out_pin} nCL 0
Cl nCL 0 {cl}p
.tran 1p 8n
{chr(10).join(meas)}
.end
"""
            out = _run_ngspice(deck, tag=f"slew={tr}ns,load={cl}pF")

            def _meas(name):
                m = re.search(name + r"\s*=\s*([0-9.eE+-]+)", out)
                return float(m.group(1)) if m else None
            _tphl = _meas("tphl")
            row.append(_tphl * 1e9 if _tphl is not None else None)
            if measure_rise:
                _tplh = _meas("tplh")
                rrow.append(_tplh * 1e9 if _tplh is not None else None)
            if measure_output_slew:
                _of, _or = _meas("oslew_f"), _meas("oslew_r")
                fslw.append(_of * 1e9 if _of is not None else None)
                rslw.append(_or * 1e9 if _or is not None else None)
            if measure_power:
                _q = _meas("qsupply")
                erow.append(abs(_q) * vdd * 1e15 if _q is not None else None)  # fJ
            if model_type == "ccs":
                _fw, _rw = [], []
                for k, lvl in enumerate(ccs_levels):
                    _icf = _meas(f"icf{k}")
                    _icr = _meas(f"icr{k}")
                    _tcf = _meas(f"tcf{k}")
                    _tcr = _meas(f"tcr{k}")
                    _fw.append({"vout_v": lvl,
                                "t_ns": _tcf * 1e9 if _tcf is not None else None,
                                "i_ua": _icf * 1e6 if _icf is not None else None})
                    _rw.append({"vout_v": lvl,
                                "t_ns": _tcr * 1e9 if _tcr is not None else None,
                                "i_ua": _icr * 1e6 if _icr is not None else None})
                cf_row.append({"cap_pf": cl, "current": _fw})
                cr_row.append({"cap_pf": cl, "current": _rw})
        table.append(row)
        if measure_rise:
            rise_table.append(rrow)
        if measure_output_slew:
            fall_slew.append(fslw)
            rise_slew.append(rslw)
        if measure_power:
            energy_table.append(erow)
        if model_type == "ccs":
            ccs_fall_current.append({"slew_ns": tr, "loads": cf_row})
            ccs_rise_current.append({"slew_ns": tr, "loads": cr_row})

    measured = sum(1 for r in table for v in r if v is not None)
    total = len(slews) * len(loads)

    def _lib_table(tables_name, tbl):
        return [f'      {tables_name}("{tmpl_name}") {{',
                f'        index_1("{" ".join(map(str,slews))}");',
                f'        index_2("{" ".join(map(str,loads))}");',
                '        values(' + ", ".join('"' + " ".join(
                    (f"{v:.5f}" if v is not None else "0") for v in r) + '"'
                    for r in tbl) + ');',
                '      }']
    # Named lookup-table template referenced by every delay/transition/power
    # group (Liberty requires the template to be defined at library scope and
    # referenced by name; the prior code emitted an undefined literal `template`).
    tmpl_name = f"{cell}_slew_load_{len(slews)}x{len(loads)}"
    # CCS driver output-current template name (3-D: slew x load x time).
    octmpl_name = f"{cell}_ccs_oc_{len(slews)}x{len(loads)}x{ccs_current_points}"
    # Boolean function of the output pin. Defaults to an inverter (!A) but any
    # single-input combinational function can be supplied via the `function`
    # param (e.g. "A" for a buffer). Multi-input cells should pass `function`.
    out_function = params.get("function")
    if out_function is None:
        out_function = f"!{in_pin}"
    # Assemble the NLDM Liberty (templates + cell function + pin caps + optional
    # internal_power; fall always; rise + transitions opt-in).
    lib = [f'library({cell}_lib) {{',
           '  delay_model : ' + ('ccs_timing' if model_type == "ccs"
                                 else 'table_lookup') + ';',
           '  time_unit : "1ns";',
           '  pulling_resistance_unit : "1kohm";',
           '  voltage_unit : "1V";',
           '  current_unit : "1uA";',
           '  leakage_power_unit : "1nW";',
           '  capacitance_unit(1,pf);',
           f'  lu_table_template({tmpl_name}) {{',
           '    variable_1 : input_net_transition;',
           '    variable_2 : total_output_net_capacitance;',
           f'    index_1("{" ".join(map(str,slews))}");',
           f'    index_2("{" ".join(map(str,loads))}");',
           '  }']
    if measure_power:
        lib += [f'  power_lut_template({tmpl_name}_pwr) {{',
                '    variable_1 : input_net_transition;',
                '    variable_2 : total_output_net_capacitance;',
                f'    index_1("{" ".join(map(str,slews))}");',
                f'    index_2("{" ".join(map(str,loads))}");',
                '  }']
    if model_type == "ccs":
        # CCS driver model: the output current is a function of input slew,
        # output load, AND time (variable_3), tabulated as vectors below.
        lib += [f'  output_current_template({octmpl_name}) {{',
                '    variable_1 : input_net_transition;',
                '    variable_2 : total_output_net_capacitance;',
                '    variable_3 : time;',
                f'    index_1("{" ".join(map(str,slews))}");',
                f'    index_2("{" ".join(map(str,loads))}");',
                '  }']
    lib += [f'  cell({cell}) {{',
            f'    area : {float(params.get("area_um2", 0.0)):.4f};']
    # input pin (with measured capacitance when available)
    if input_cap_ff is not None:
        lib += [f'    pin({in_pin}) {{ direction : input; '
                f'capacitance : {input_cap_ff * 1e-3:.6f}; }}']
    else:
        lib += [f'    pin({in_pin}) {{ direction : input; }}']
    # output pin: function + timing arc(s)
    lib += [f'    pin({out_pin}) {{',
            '      direction : output;',
            f'      function : "{out_function}";',
            '      timing() {',
            f'        related_pin : "{in_pin}";',
            '        timing_type : combinational;']
    lib += _lib_table("cell_fall", table)
    if measure_rise:
        lib += _lib_table("cell_rise", rise_table)
    if measure_output_slew:
        lib += _lib_table("fall_transition", fall_slew)
        lib += _lib_table("rise_transition", rise_slew)
    # CCS driver output-current vectors: one vector() per (slew, load) with the
    # measured i(t) waveform. This is the defining CCS content — without it a
    # `delay_model : ccs_timing` header is not a real CCS model.
    ccs_vectors_emitted = 0
    if model_type == "ccs":
        def _ccs_output_current(group_name, ccs_data):
            nonlocal ccs_vectors_emitted
            out_lines = [f'      {group_name}({octmpl_name}) {{']
            for sblk in ccs_data:
                sv = sblk["slew_ns"]
                for lblk in sblk["loads"]:
                    cv = lblk["cap_pf"]
                    pts = [p for p in lblk["current"]
                           if p.get("t_ns") is not None and p.get("i_ua") is not None]
                    pts = sorted(pts, key=lambda p: p["t_ns"])
                    if not pts:
                        continue
                    ref = pts[0]["t_ns"]
                    times = " ".join(f"{p['t_ns']:.6f}" for p in pts)
                    vals = ", ".join(f"{p['i_ua']:.6f}" for p in pts)  # current_unit=1uA
                    out_lines += [f'        vector({octmpl_name}) {{',
                                  f'          reference_time : {ref:.6f};',
                                  f'          index_1("{sv}");',
                                  f'          index_2("{cv}");',
                                  f'          index_3("{times}");',
                                  f'          values("{vals}");',
                                  '        }']
                    ccs_vectors_emitted += 1
            out_lines += ['      }']
            return out_lines
        lib += _ccs_output_current("output_current_fall", ccs_fall_current)
        lib += _ccs_output_current("output_current_rise", ccs_rise_current)
    lib += ['      }']   # close timing()
    # internal_power group (rise/fall energy tables) when power was measured
    if measure_power and energy_table:
        def _pwr_table(name, tbl):
            return [f'      {name}("{tmpl_name}_pwr") {{',
                    '        values(' + ", ".join('"' + " ".join(
                        (f"{v:.5f}" if v is not None else "0") for v in r) + '"'
                        for r in tbl) + ');',
                    '      }']
        lib += ['      internal_power() {',
                f'        related_pin : "{in_pin}";']
        lib += _pwr_table("rise_power", energy_table)
        lib += _pwr_table("fall_power", energy_table)
        lib += ['      }']
    lib += ['    }']   # close output pin
    lib += ['  }']     # close cell
    lib += ['}']       # close library
    lib_path = os.path.join(_OUTPUT_DIR, f"{cell}.lib")
    open(lib_path, "w").write("\n".join(lib) + "\n")

    def _monotonic(tbl):
        return all(
            all(r[i] is None or r[i + 1] is None or r[i + 1] >= r[i]
                for i in range(len(r) - 1))
            for r in tbl)
    monotonic = _monotonic(table)
    rise_ok = True
    if measure_rise:
        rise_measured = sum(1 for r in rise_table for v in r if v is not None)
        rise_ok = rise_measured == total and _monotonic(rise_table)
    ok = measured == total and monotonic and rise_ok
    arcs = 1 + (1 if measure_rise else 0)
    # CCS completeness: every grid point must have a fully-sampled current
    # waveform (current AND time), the input capacitance must be present, and the
    # output_current vectors must actually be in the emitted Liberty.
    ccs_ok = True
    ccs_samples = 0
    if model_type == "ccs":
        for tblk in ccs_fall_current + ccs_rise_current:
            for lblk in tblk["loads"]:
                for s in lblk["current"]:
                    if s["i_ua"] is None or s.get("t_ns") is None:
                        ccs_ok = False
                    else:
                        ccs_samples += 1
        # input capacitance is mandatory for a CCS receiver model
        if input_cap_ff is None:
            ccs_ok = False
        # the driver output_current vectors must have been emitted into the .lib
        # (one per slew x load, x2 arcs); a ccs_timing header without them is not
        # a real CCS model.
        _expected_vectors = 2 * len(slews) * len(loads)
        if ccs_vectors_emitted < _expected_vectors:
            ccs_ok = False
        ok = ok and ccs_ok
    # SPICE HEALTH GATE. `spice_nonconvergence: block` was declared by this
    # stage's gate criteria and never enforced. A non-convergent grid point
    # produces no .measure value, which _lib_table writes into the Liberty as
    # "0" -- a ZERO DELAY that downstream STA will close against happily.
    spice_issues = list(_SPICE_ISSUES)
    if spice_issues:
        ok = False
    # Zero-fill hazard: report exactly how many table cells were emitted as "0"
    # because no value was measured, so the number is never implicit.
    def _none_cells(tbl):
        return sum(1 for r in (tbl or []) for v in r if v is None)
    zero_filled = _none_cells(table) + _none_cells(rise_table) + \
        _none_cells(fall_slew) + _none_cells(rise_slew) + _none_cells(energy_table)
    if zero_filled:
        ok = False
    _sig = {"liberty": f"{cell}.lib", "model": model_type,
            "slews_ns": slews, "loads_pf": loads,
            "delay_table_ns": table, "monotonic": monotonic,
            "measure_rise": measure_rise,
            "measure_output_slew": measure_output_slew,
            "measure_power": measure_power,
            "measure_input_cap": measure_input_cap,
            "input_cap_ff": input_cap_ff,
            "liberty_template": tmpl_name,
            "output_function": out_function,
            "subckt_ports": _ports,
            "dut_node_binding": _dut_nodes,
            "floating_ports_tied_off": _dut_warns,
            "temp_c": temp_c, "corners": params.get("corners"),
            "spice_nonconvergence": spice_issues or None,
            "spice_converged": not spice_issues,
            "liberty_zero_filled_cells": zero_filled,
            "measured_points": measured, "grid_points": total}
    if measure_rise:
        _sig["rise_table_ns"] = rise_table
    if measure_output_slew:
        _sig["fall_transition_ns"] = fall_slew
        _sig["rise_transition_ns"] = rise_slew
    if measure_power:
        _sig["switching_energy_fj"] = energy_table
    if model_type == "ccs":
        _sig["ccs_current_points"] = ccs_current_points
        _sig["ccs_vectors_emitted"] = ccs_vectors_emitted
        _sig["ccs_output_current_template"] = octmpl_name
        _sig["ccs_fall_current"] = ccs_fall_current
        _sig["ccs_rise_current"] = ccs_rise_current
    _note = ("grid complete and monotonic" if ok
             else "missing points or non-monotonic table")
    if spice_issues:
        _note = ("SPICE DID NOT CONVERGE at %d grid point(s) (%s); the Liberty "
                 "writes an unmeasured cell as 0, so this library would hand "
                 "downstream timing a ZERO DELAY"
                 % (len(spice_issues),
                    ", ".join(sorted({s for i in spice_issues
                                      for s in i["signatures"]}))[:120]))
    elif zero_filled:
        _note = ("%d Liberty table cell(s) had no measured value and were emitted "
                 "as 0; a zero delay is not a measurement" % zero_filled)
    if model_type == "ccs" and not ccs_ok:
        _note = ("CCS model incomplete: missing current samples or input "
                 "capacitance") if not ok else _note
    return _cde(
        objective=f"{model_type.upper()} characterization of {cell}",
        status="completed" if ok else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"arcs_characterized": {"value": arcs, "unit": "count"},
                 "grid_points": {"value": total, "unit": "count"},
                 "measured_points": {"value": measured, "unit": "count"},
                 "input_cap_ff": {"value": round(input_cap_ff, 4)
                                  if input_cap_ff is not None else "n/a",
                                  "unit": "fF"},
                 "ccs_current_samples": {"value": ccs_samples, "unit": "count"},
                 "ccs_output_current_vectors": {"value": ccs_vectors_emitted,
                                                "unit": "count"}},
        signoff=_sig,
        inputs_ref={"cell_netlist": netlist, "spice_models": models},
        assumptions=["inverting combinational cell (fall + optional rise arc); "
                     "grid and corners from the binding; extend for sequential arcs;"
                     + (" CCS current waveforms i(Cl)=Cl*dV/dt sampled per arc, "
                        "receiver Cin measured from a ramp-charge integral"
                        if model_type == "ccs" else "")],
        provenance={"ngspice": _ngspice_version(), "log": "ngspice.log"},
        validation={"verdict": "pass" if ok else "fail", "note": _note},
    )


def _characterize_sequential(params):
    """Characterize a sequential cell's timing constraints (setup + hold) for a
    data pin relative to the active clock edge, via an ngspice constraint search.

    Method (the standard degradation definition): sweep the data-to-clock
    separation and, at each point, launch the clock and measure the clk->Q
    propagation delay. The constraint is the tightest separation at which the
    cell still captures the correct value AND the clk->Q delay stays within
    `degrade_pct` (default 10%) of its relaxed-timing nominal. Tighter than that,
    the flop metastably fails to capture -- that boundary is the setup (data
    before clock) / hold (data after clock) time.

    The DUT subckt exposes clk / d / q (+ power) pins named via params."""
    cell = params["cell"]
    netlist = params.get("cell_netlist")
    models = (params.get("pdk_binding") or {}).get("spice_models") or params.get("spice_models")
    if not netlist or not os.path.exists(str(netlist)):
        return _cde(objective=f"sequential characterize {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="cell_netlist (subckt) path required and must exist",
                    validation={"verdict": "fail"})
    if not models or not os.path.exists(str(models)):
        return _cde(objective=f"sequential characterize {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="SPICE device models required from pdk_binding.spice_models",
                    validation={"verdict": "fail"})
    clk_pin = params.get("clk_pin", "CLK")
    d_pin = params.get("d_pin", "D")
    q_pin = params.get("q_pin", "Q")
    ports = params.get("ports") or [clk_pin, d_pin, q_pin, "VPWR", "VGND"]
    vdd = float(params.get("vdd", 1.8))
    tr = float(params.get("slew_ns", 0.1))       # input transition (ns)
    cl = float(params.get("load_pf", 0.02))      # output load (pF)
    edge = str(params.get("clock_edge", "rise")).lower()  # active clock edge
    degrade = float(params.get("degrade_pct", 10.0)) / 100.0
    # separations to try (ns): data-vs-clock offset. Positive = data before clock
    # (setup side); we mirror for hold. Caller may override the grid.
    seps = params.get("separations_ns") or [1.0, 0.6, 0.4, 0.25, 0.15, 0.1,
                                            0.05, 0.02, 0.0, -0.05, -0.1, -0.2]
    tclk = 5.0    # clock edge time (ns)

    def _order(ports_list):
        return " ".join(str(p) for p in ports_list)

    def _run_point(sep_ns, data_val):
        """Launch clock at tclk; data transitions to data_val at tclk - sep_ns
        (sep>0 => before clock). Return (captured_q, clk_to_q_ns) or (None,None)."""
        t_data = tclk - sep_ns
        # clock waveform: idle low, single active edge at tclk (rise) or high->low
        if edge.startswith("r"):
            clk_pwl = f"PWL(0 0 {tclk-tr}n 0 {tclk}n {vdd} 8n {vdd})"
        else:
            clk_pwl = f"PWL(0 {vdd} {tclk-tr}n {vdd} {tclk}n 0 8n 0)"
        d0 = 0.0 if data_val else vdd
        d1 = vdd if data_val else 0.0
        # data settles to d0 early, transitions to d1 at t_data
        t0 = max(0.5, t_data - tr)
        data_pwl = (f"PWL(0 {d0} {t0}n {d0} {t_data}n {d1} 8n {d1})")
        deck = f""".title seq char {cell}
.include {models}
.include {netlist}
Vdd VPWR 0 {vdd}
Vss VGND 0 0
Vclk {clk_pin} 0 {clk_pwl}
Vd {d_pin} 0 {data_pwl}
Xdut {_order(ports)} {cell}
Cl {q_pin} 0 {cl}p
.tran 2p 8n
.measure tran qfin FIND v({q_pin}) AT=7.5n
.measure tran tcq TRIG v({clk_pin}) VAL={vdd/2} {'RISE' if edge.startswith('r') else 'FALL'}=1 TARG v({q_pin}) VAL={vdd/2} CROSS=1
.end
"""
        out = _run_ngspice(deck)
        mq = re.search(r"qfin\s*=\s*([0-9.eE+-]+)", out)
        mt = re.search(r"tcq\s*=\s*([0-9.eE+-]+)", out)
        q = float(mq.group(1)) if mq else None
        tcq = float(mt.group(1)) * 1e9 if mt else None
        cap = None if q is None else (q > vdd / 2)
        return cap, tcq

    def _constraint(data_val, side):
        """side='setup' (data before clock, sep decreasing) or 'hold' (data after,
        sep negative). Returns (constraint_ns, nominal_cq_ns, table)."""
        table = []
        # nominal clk->Q at the most relaxed separation on this side
        relaxed = seps[0] if side == "setup" else seps[-1]
        _, nom_cq = _run_point(relaxed if side == "setup" else abs(relaxed), data_val) \
            if side == "setup" else _run_point(relaxed, data_val)
        constraint = None
        ordered = seps if side == "setup" else list(reversed(seps))
        for sep in ordered:
            cap, tcq = _run_point(sep, data_val)
            correct = (cap == bool(data_val))
            within = (nom_cq is not None and tcq is not None
                      and tcq <= nom_cq * (1.0 + degrade))
            ok = correct and within
            table.append({"separation_ns": sep, "captured": cap,
                          "clk_to_q_ns": None if tcq is None else round(tcq, 4),
                          "ok": bool(ok)})
            if ok:
                # tightest still-passing separation seen so far
                if side == "setup":
                    constraint = sep
                else:
                    constraint = sep
        return constraint, (None if nom_cq is None else round(nom_cq, 4)), table

    setup_ns, setup_nom, setup_tbl = _constraint(1, "setup")
    hold_ns, hold_nom, hold_tbl = _constraint(1, "hold")
    # setup time is the tightest passing positive separation; hold is the
    # magnitude of the tightest passing (data-after-clock) point.
    setup_time = setup_ns if setup_ns is not None else None
    hold_time = (-hold_ns) if (hold_ns is not None and hold_ns < 0) else \
        (0.0 if hold_ns is not None else None)
    ok = setup_time is not None and hold_time is not None
    lib_path = os.path.join(_OUTPUT_DIR, f"{cell}_seq.lib")
    lib = [f'library({cell}_seq_lib) {{', '  delay_model : table_lookup;',
           '  time_unit : "1ns";',
           f'  cell({cell}) {{ ff("IQ","IQN") {{ clocked_on : "{clk_pin}"; }}',
           f'    pin({d_pin}) {{ direction : input;',
           f'      timing() {{ related_pin : "{clk_pin}"; timing_type : setup_rising;',
           f'        intrinsic_rise : {setup_time if setup_time is not None else 0}; }}',
           f'      timing() {{ related_pin : "{clk_pin}"; timing_type : hold_rising;',
           f'        intrinsic_rise : {hold_time if hold_time is not None else 0}; }}',
           '    } } }']
    open(lib_path, "w").write("\n".join(lib) + "\n")
    return _cde(
        objective=f"sequential (setup/hold) characterization of {cell}",
        status="completed" if ok else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"setup_time": {"value": setup_time, "unit": "ns"},
                 "hold_time": {"value": hold_time, "unit": "ns"}},
        qor={"setup_ns": setup_time, "hold_ns": hold_time,
             "clk_to_q_nominal_ns": setup_nom},
        signoff={"liberty": f"{cell}_seq.lib", "arc": "setup+hold",
                 "clock_edge": edge, "degrade_pct": degrade * 100,
                 "setup_ns": setup_time, "hold_ns": hold_time,
                 "clk_to_q_nominal_ns": setup_nom,
                 "setup_sweep": setup_tbl, "hold_sweep": hold_tbl,
                 "report": "ngspice.log"},
        inputs_ref={"cell_netlist": netlist, "spice_models": models},
        assumptions=["setup/hold defined by the " + str(degrade * 100)
                     + "% clk->Q degradation criterion; sequential ff arc only, "
                     "single data pin vs the active clock edge; extend for "
                     "recovery/removal and multi-bit cells"],
        validation={"verdict": "pass" if ok else "fail",
                    "note": ("setup/hold constraints found"
                             if ok else "constraint search did not converge; "
                             "widen separations_ns or check the DUT")},
        provenance={"ngspice": _ngspice_version(), "log": "ngspice.log"},
    )


#: Top-level keys create_lef understands. Anything else is rejected fail-closed:
#: an agent that sent `pins_source: {def: ...}` (not a supported key) previously
#: got a "completed" 0-pin LEF and then a QA pass over it.
_CREATE_LEF_KEYS = ("scenario", "cell", "size_um", "pins", "obstructions",
                    "pdk_binding", "allow_no_pins", "attempt_intent",
                    "description", "notes")


def _create_lef(params):
    cell = params["cell"]
    unknown = sorted(k for k in params if k not in _CREATE_LEF_KEYS)
    if unknown:
        return _cde(objective=f"LEF abstract for {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=(f"create_lef: unknown parameter(s) {unknown}; "
                           f"accepted keys: {list(_CREATE_LEF_KEYS)}. Pins must "
                           "be given inline as `pins: [{name, dir, layer, use, "
                           "rects:[[x1,y1,x2,y2],...]}]` (pin extraction from a "
                           "DEF/`pins_source` is not supported)."),
                    signoff={"unknown_params": unknown,
                             "accepted_params": list(_CREATE_LEF_KEYS)},
                    validation={"verdict": "fail",
                                "note": "fail-closed: unknown parameter(s) "
                                        + ", ".join(unknown)})
    size = params.get("size_um", [1.0, 1.0])
    pins = params.get("pins") or []
    if not isinstance(pins, list):
        return _cde(objective=f"LEF abstract for {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=f"create_lef: `pins` must be a list, got "
                          f"{type(pins).__name__}",
                    validation={"verdict": "fail"})
    if not pins and not params.get("allow_no_pins"):
        return _cde(objective=f"LEF abstract for {cell}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=("create_lef: 0 pins resolved -- an empty abstract is "
                           "a placeholder, not a view. Supply `pins` (with "
                           "per-pin `rects`), or set `allow_no_pins: true` for a "
                           "physical-only cell."),
                    results={"pins": {"value": 0, "unit": "count"}},
                    validation={"verdict": "fail",
                                "note": "fail-closed: 0 pins"})
    # Optional real abstract geometry (signoff-grade): per-pin `rects` (list of
    # [x1,y1,x2,y2] in um) + `layer`/`use`, plus routing `obstructions`
    # (list of {layer, rects}). When a pin carries real rects we emit them
    # verbatim; a pin WITHOUT geometry is recorded as incomplete so the verdict
    # reflects that the abstract is not signoff-complete (the prior code silently
    # emitted a 0.1x0.1 placeholder and always reported the LEF as consistent).
    obstructions = params.get("obstructions", [])
    lines = [f"MACRO {cell}", "  CLASS CORE ;",
             f"  ORIGIN 0 0 ;",
             f"  SIZE {size[0]} BY {size[1]} ;"]
    _default_use = {"INPUT": "SIGNAL", "OUTPUT": "SIGNAL",
                    "INOUT": "POWER"}
    pins_with_geom = 0
    for p in pins:
        pdir = p.get("dir", "INPUT")
        puse = p.get("use") or _default_use.get(pdir, "SIGNAL")
        layer = p.get("layer", "li1")
        rects = p.get("rects")
        lines += [f"  PIN {p['name']}",
                  f"    DIRECTION {pdir} ;",
                  f"    USE {puse} ;",
                  "    PORT",
                  f"      LAYER {layer} ;"]
        if rects:
            for r in rects:
                lines.append("      RECT "
                             + " ".join(f"{float(c):.4f}" for c in r) + " ;")
            pins_with_geom += 1
        else:
            # no real geometry supplied -> emit nothing routable and flag it
            lines.append("      # WARNING: no pin geometry supplied (not signoff-complete)")
        lines += ["    END", f"  END {p['name']}"]
    # routing obstructions (blockages) if provided
    if obstructions:
        lines.append("  OBS")
        for ob in obstructions:
            lines.append(f"    LAYER {ob.get('layer','met1')} ;")
            for r in ob.get("rects", []):
                lines.append("    RECT "
                             + " ".join(f"{float(c):.4f}" for c in r) + " ;")
        lines.append("  END")
    lines += [f"END {cell}"]
    lef_path = os.path.join(_OUTPUT_DIR, f"{cell}.lef")
    open(lef_path, "w").write("\n".join(lines) + "\n")
    # signoff-complete only if every pin has real geometry
    geom_complete = bool(pins) and pins_with_geom == len(pins)
    _note = ("all pins carry real geometry" if geom_complete
             else f"{pins_with_geom}/{len(pins)} pins have geometry — "
                  "placeholder-free abstract requires real rects per pin")
    return _cde(objective=f"LEF abstract for {cell}", status="completed",
                pdk_binding=params.get("pdk_binding", "none"),
                results={"pins": {"value": len(pins), "unit": "count"},
                         "pins_with_geometry": {"value": pins_with_geom,
                                                "unit": "count"},
                         "obstructions": {"value": len(obstructions),
                                          "unit": "count"}},
                signoff={"lef": f"{cell}.lef", "size_um": size,
                         "pins_with_geometry": pins_with_geom,
                         "geometry_complete": geom_complete,
                         "pins_consistent_with_layout": geom_complete},
                assumptions=["abstract pins/obstructions must match the layout; "
                             "supply per-pin `rects` for a signoff-complete LEF"],
                validation={"verdict": "pass" if geom_complete else "review",
                            "note": _note})


def _create_def(params):
    cell = params["cell"]
    size = params.get("size_um", [1.0, 1.0])
    pins = params.get("pins", [])
    dbu = int(params.get("units_per_micron", 1000))
    # Full component/pin DEF: DIEAREA from the cell size and a PINS section from
    # the declared pins (the prior code emitted only `COMPONENTS 0` with no
    # DIEAREA and no PINS, which no downstream tool can consume).
    w = int(round(float(size[0]) * dbu))
    h = int(round(float(size[1]) * dbu))
    L = [f"VERSION 5.8 ;",
         f'DIVIDERCHAR "/" ;',
         f'BUSBITCHARS "[]" ;',
         f"DESIGN {cell} ;",
         f"UNITS DISTANCE MICRONS {dbu} ;",
         f"DIEAREA ( 0 0 ) ( {w} {h} ) ;"]
    _dir_map = {"INPUT": "INPUT", "OUTPUT": "OUTPUT", "INOUT": "INOUT"}
    if pins:
        L.append(f"PINS {len(pins)} ;")
        for i, p in enumerate(pins):
            pdir = _dir_map.get(p.get("dir", "INPUT"), "INPUT")
            layer = p.get("layer", "li1")
            use = p.get("use") or ("POWER" if pdir == "INOUT" else "SIGNAL")
            # place pin along the left edge, evenly distributed (deterministic)
            py = int(round(h * (i + 1) / (len(pins) + 1)))
            L += [f"  - {p['name']} + NET {p['name']} + DIRECTION {pdir} + USE {use}",
                  f"    + LAYER {layer} ( -70 -70 ) ( 70 70 )",
                  f"    + PLACED ( 0 {py} ) N ;"]
        L.append("END PINS")
    L += ["COMPONENTS 0 ;", "END COMPONENTS", "END DESIGN", ""]
    def_path = os.path.join(_OUTPUT_DIR, f"{cell}.def")
    open(def_path, "w").write("\n".join(L))
    has_diearea = True
    has_pins = bool(pins)
    complete = has_diearea and has_pins
    return _cde(objective=f"DEF view for {cell}", status="completed",
                pdk_binding=params.get("pdk_binding", "none"),
                results={"def": {"value": 1, "unit": "count"},
                         "pins": {"value": len(pins), "unit": "count"},
                         "diearea_um": {"value": f"{size[0]}x{size[1]}",
                                        "unit": "um"}},
                signoff={"def": f"{cell}.def", "has_diearea": has_diearea,
                         "has_pins": has_pins, "pin_count": len(pins),
                         "matches_abstract": complete},
                assumptions=["supply `pins` and `size_um` for a DIEAREA/PINS-"
                             "complete DEF"],
                validation={"verdict": "pass" if complete else "review",
                            "note": ("DIEAREA + PINS present" if complete
                                     else "missing PINS — supply `pins`")})


def _extract_braced_block(text, start_kw_regex):
    """Return the substring of *text* covering the first `<kw>(...) { ... }` block
    whose opening keyword matches *start_kw_regex*, with braces balanced. Returns
    None if not found. Used to lift each `cell(...) { ... }` out of a per-cell
    Liberty fragment when assembling a combined library."""
    m = re.search(start_kw_regex, text)
    if not m:
        return None
    i = text.find("{", m.start())
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():j + 1]
    return None


def _assemble_library(params):
    """Merge per-cell Liberty fragments into a single `library(<lib_name>)` file.

    Inputs: `lib_name` (output library name) and either `liberty_files` (list of
    paths) or `cells` (list of {liberty: path}). Each fragment must exist, be
    non-empty, and contain a `cell(...)` group; every cell block is lifted and
    re-wrapped under one library header (units/templates copied from the first
    fragment). Fails closed if any fragment is missing or has no cell group — no
    empty or fabricated library is ever emitted."""
    lib_name = params.get("lib_name") or params.get("library") or "stdcells"
    files = list(params.get("liberty_files") or [])
    for c in (params.get("cells") or []):
        if isinstance(c, dict) and c.get("liberty"):
            files.append(c["liberty"])
    if not files:
        return _cde(objective=f"assemble library {lib_name}", status="failed",
                    error="no liberty_files/cells provided to assemble",
                    validation={"verdict": "fail"})
    header, cell_blocks, cell_names, missing = None, [], [], []
    for fp in files:
        if not fp or not os.path.isfile(str(fp)) or os.path.getsize(str(fp)) == 0:
            missing.append(str(fp))
            continue
        txt = open(fp, "r", encoding="utf-8", errors="replace").read()
        cblk = _extract_braced_block(txt, r"cell\s*\(")
        if not cblk:
            missing.append(str(fp) + " (no cell group)")
            continue
        cell_blocks.append(cblk)
        _cn = re.search(r"cell\s*\(\s*([^)\s]+)", cblk)
        if _cn:
            cell_names.append(_cn.group(1))
        if header is None:
            # copy library-scope declarations (units + templates) from first frag
            libblk = _extract_braced_block(txt, r"library\s*\(")
            if libblk:
                inner = libblk[libblk.find("{") + 1:]
                decls = []
                for tkw in (r"delay_model\s*:[^;]*;", r"\w+_unit[^;]*;",
                            r"capacitance_unit\([^)]*\)\s*;"):
                    decls += re.findall(tkw, inner)
                for tmpl in re.finditer(r"(lu_table_template|power_lut_template|output_current_template)\s*\(", inner):
                    blk = _extract_braced_block(inner[tmpl.start():],
                                                r"(lu_table_template|power_lut_template|output_current_template)\s*\(")
                    if blk:
                        decls.append(blk)
                header = decls
    if missing:
        return _cde(objective=f"assemble library {lib_name}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="missing/invalid fragments: " + "; ".join(missing),
                    signoff={"missing": missing, "assembled": 0},
                    validation={"verdict": "fail",
                                "note": "fail-closed: incomplete inputs"})
    out = [f"library({lib_name}) {{"]
    for d in (header or []):
        out.append("  " + d.strip())
    for blk in cell_blocks:
        out += ["  " + ln for ln in blk.splitlines()]
    out += ["}"]
    lib_path = os.path.join(_OUTPUT_DIR, f"{lib_name}.lib")
    open(lib_path, "w").write("\n".join(out) + "\n")
    return _cde(objective=f"assemble library {lib_name}", status="completed",
                pdk_binding=params.get("pdk_binding", "none"),
                results={"cells": {"value": len(cell_blocks), "unit": "count"}},
                signoff={"library": f"{lib_name}.lib", "cells": cell_names,
                         "cell_count": len(cell_blocks)},
                assumptions=["fragments must be self-consistent (same units/corner)"],
                validation={"verdict": "pass",
                            "note": f"assembled {len(cell_blocks)} cell(s)"})


_QA_VIEW_EXT = {".lib": "liberty", ".liberty": "liberty", ".lef": "lef",
                ".def": "def"}
_QA_VIEW_ALIASES = {"liberty": "liberty", "lib": "liberty",
                    "liberty_file": "liberty", "lef": "lef", "lef_file": "lef",
                    "def": "def", "def_file": "def"}
_QA_DIR_KEYS = ("views_dir", "generated_output_dir", "dir", "output_dir")
_QA_POWER_USES = ("POWER", "GROUND")


def _qa_collect_views(params):
    """Resolve the views library_qa must check. Sources: top-level `liberty` /
    `lef` / `def` (path or list of paths), a `views` dict (known keys or any key
    whose value is a .lib/.lef/.def path) or list of paths, and a directory
    (`views_dir` / `views.generated_output_dir`) scanned for .lib/.lef/.def.
    Returns (views=[(kind, path, source)], missing_dirs, ignored)."""
    views, missing_dirs, ignored, dirs = [], [], [], []

    def _add(kind, val, src):
        for v in (val if isinstance(val, (list, tuple)) else [val]):
            if v is None or v == "":
                continue
            views.append((kind, str(v), src))

    def _by_ext(v, src):
        kind = _QA_VIEW_EXT.get(os.path.splitext(str(v))[1].lower())
        if kind:
            _add(kind, v, src)
        else:
            ignored.append(f"{src}={v!r} (not a .lib/.lef/.def path)")

    for k in ("liberty", "lef", "def"):
        if k in params:
            _add(k, params[k], k)
    for k in _QA_DIR_KEYS:
        if params.get(k):
            dirs.append((params[k], k))
    vd = params.get("views")
    if isinstance(vd, dict):
        for k, v in vd.items():
            if k in _QA_DIR_KEYS:
                dirs.append((v, f"views.{k}"))
            elif k in _QA_VIEW_ALIASES:
                _add(_QA_VIEW_ALIASES[k], v, f"views.{k}")
            elif isinstance(v, (list, tuple)):
                for x in v:
                    _by_ext(x, f"views.{k}")
            else:
                _by_ext(v, f"views.{k}")
    elif isinstance(vd, (list, tuple)):
        for v in vd:
            _by_ext(v, "views[]")
    elif isinstance(vd, str):
        _by_ext(vd, "views")
    cell = params.get("cell")
    for d, src in dirs:
        if not os.path.isdir(str(d)):
            missing_dirs.append(f"{src}={d}")
            continue
        found = []
        for root, _dirs, files in os.walk(str(d)):
            for fn in sorted(files):
                kind = _QA_VIEW_EXT.get(os.path.splitext(fn)[1].lower())
                if kind:
                    found.append((kind, os.path.join(root, fn)))
        # prefer the cell's own views when the directory holds several cells
        if cell:
            mine = [f for f in found
                    if os.path.splitext(os.path.basename(f[1]))[0] == cell]
            found = mine or found
        if not found:
            missing_dirs.append(f"{src}={d} (no .lib/.lef/.def inside)")
        for kind, p in found:
            views.append((kind, p, src))
    seen, uniq = set(), []
    for v in views:
        if (v[0], v[1]) not in seen:
            seen.add((v[0], v[1]))
            uniq.append(v)
    return uniq, missing_dirs, ignored


def _qa_parse_liberty_cells(t):
    """{cell_name: [signal pin names]} (pg_pin groups are not counted)."""
    cells = {}
    for m in re.finditer(r"\bcell\s*\(\s*\"?([^)\"\s]+)\"?\s*\)", t):
        blk = _extract_braced_block(t[m.start():], r"\bcell\s*\(") or ""
        cells[m.group(1)] = re.findall(
            r"\bpin\s*\(\s*\"?([^)\"\s]+)\"?\s*\)", blk)
    return cells


def _qa_parse_lef_macros(t):
    """{macro: {pin: {"use": str, "geometry": bool}}} from comment-stripped LEF.
    A pin has geometry only when a PORT block carries a RECT or POLYGON."""
    t = re.sub(r"#[^\n]*", "", t)
    macros = {}
    for m in re.finditer(r"^\s*MACRO\s+(\S+)", t, re.MULTILINE):
        name = m.group(1)
        end = re.search(r"^\s*END\s+" + re.escape(name) + r"\s*$",
                        t[m.end():], re.MULTILINE)
        body = t[m.end():m.end() + end.start()] if end else t[m.end():]
        pins = {}
        for pm in re.finditer(r"^\s*PIN\s+(\S+)", body, re.MULTILINE):
            pn = pm.group(1)
            pe = re.search(r"^\s*END\s+" + re.escape(pn) + r"\s*$",
                           body[pm.end():], re.MULTILINE)
            pb = body[pm.end():pm.end() + pe.start()] if pe else body[pm.end():]
            use = re.search(r"\bUSE\s+(\w+)", pb)
            geom = False
            for port in re.finditer(r"\bPORT\b(.*?)\bEND\b", pb, re.DOTALL):
                if re.search(r"\b(RECT|POLYGON)\b", port.group(1)):
                    geom = True
                    break
            pins[pn] = {"use": (use.group(1).upper() if use else "SIGNAL"),
                        "geometry": geom}
        macros[name] = pins
    return macros


def _qa_parse_def_pins(t):
    """(declared_count|None, {pin: use}) from the DEF PINS section."""
    m = re.search(r"^\s*PINS\s+(\d+)\s*;(.*?)^\s*END\s+PINS",
                  t, re.MULTILINE | re.DOTALL)
    if not m:
        d = re.search(r"^\s*PINS\s+(\d+)\s*;", t, re.MULTILINE)
        return (int(d.group(1)) if d else None), {}
    pins = {}
    for chunk in m.group(2).split(";"):
        pm = re.search(r"-\s+(\S+)", chunk)
        if pm:
            um = re.search(r"\+\s*USE\s+(\w+)", chunk)
            pins[pm.group(1)] = um.group(1).upper() if um else "SIGNAL"
    return int(m.group(1)), pins


def _library_qa(params):
    """Real cross-view consistency QA over generated Liberty/LEF/DEF. Each gate is
    checked against file content; the run passes only when at least one view was
    supplied and resolved, every requested view is present AND signoff-complete
    (defined templates, timing tables, cell function, >=1 cell and >=1 pin per
    cell; >=1 LEF macro, >=1 pin per macro, PORT geometry on every pin without
    placeholders; DEF DIEAREA + non-empty PINS), and signal-pin sets agree across
    views. Zero gates can never read as a pass: the prior version returned
    "all gates passed" with 0 gates when it was handed no resolvable views."""
    cell = params.get("cell")
    expected = params.get("expected") if isinstance(params.get("expected"),
                                                    dict) else {}
    views, missing_dirs, ignored = _qa_collect_views(params)
    gates, fails = [], []

    def _gate(name, ok, detail=""):
        gates.append({"gate": name, "pass": bool(ok), "detail": detail})
        if not ok:
            fails.append(name)

    _gate("qa.views_supplied", bool(views),
          f"{len(views)} view file(s) resolved" if views else
          "no Liberty/LEF/DEF view resolved -- supply `liberty`/`lef`/`def` "
          "(path or list), `views: {liberty|lef|def|<name>: path}` or "
          "`views_dir`" + (f"; ignored: {ignored}" if ignored else ""))
    for md in missing_dirs:
        _gate("qa.views_dir_present", False, md)

    kinds_n = {}
    for kind, _p, _s in views:
        kinds_n[kind] = kinds_n.get(kind, 0) + 1
    for kind in ("liberty", "lef", "def"):
        if expected.get(kind):
            _gate(f"expected.{kind}_present", kinds_n.get(kind, 0) > 0,
                  f"{kinds_n.get(kind, 0)} {kind} view(s) supplied")

    counts = {"liberty_cells": 0, "liberty_pins": 0, "lef_macros": 0,
              "lef_pins": 0, "lef_pins_with_geometry": 0, "def_pins": 0,
              "views_checked": 0}
    # per-view signal pin sets keyed by label, and per-view cell maps
    pin_sets, cell_maps, view_summary = {}, {}, []
    for kind, path, src in views:
        label = (kind if kinds_n[kind] == 1
                 else f"{kind}[{os.path.basename(path)}]")
        if not (os.path.isfile(path) and os.path.getsize(path) > 0):
            _gate(f"{label}.present", False, f"{path}: missing or empty")
            view_summary.append({"view": label, "path": path, "source": src,
                                 "present": False})
            continue
        counts["views_checked"] += 1
        t = open(path, "r", encoding="utf-8", errors="replace").read()
        summ = {"view": label, "path": path, "source": src, "present": True}
        if kind == "liberty":
            _gate(f"{label}.library_group", "library(" in t
                  or bool(re.search(r"\blibrary\s*\(", t)))
            cells = _qa_parse_liberty_cells(t)
            _gate(f"{label}.cell_group", bool(cells))
            _gate(f"{label}.cell_count", len(cells) > 0, f"cells={len(cells)}")
            empty = sorted(c for c, ps in cells.items() if not ps)
            _gate(f"{label}.cells_with_pins", bool(cells) and not empty,
                  f"{len(cells) - len(empty)}/{len(cells)} cells have pins"
                  + (f"; empty={empty[:10]}" if empty else ""))
            tmpls = set(re.findall(r"lu_table_template\s*\(\s*([^)\s]+)", t))
            _gate(f"{label}.template_defined", bool(tmpls),
                  f"templates={sorted(tmpls)}")
            refs = set(re.findall(r"cell_(?:fall|rise)\s*\(\s*\"?([^)\"\s]+)", t))
            _gate(f"{label}.timing_tables", bool(refs),
                  f"tables_ref={sorted(refs)}")
            _gate(f"{label}.templates_resolve",
                  bool(refs) and refs.issubset(tmpls),
                  f"unresolved={sorted(refs - tmpls)}")
            _gate(f"{label}.cell_function", bool(re.search(r"function\s*:", t)))
            # CCS-specific gates: a Liberty that declares `delay_model :
            # ccs_timing` is only a real CCS model if it defines an
            # output_current_template and emits output_current_rise/fall vector
            # groups that reference it.
            if re.search(r"delay_model\s*:\s*ccs_timing", t):
                oc_tmpls = set(re.findall(
                    r"output_current_template\s*\(\s*([^)\s]+)", t))
                _gate(f"{label}.ccs_output_current_template", bool(oc_tmpls),
                      f"oc_templates={sorted(oc_tmpls)}")
                _has_oc_fall = bool(re.search(r"output_current_fall\s*\(", t))
                _has_oc_rise = bool(re.search(r"output_current_rise\s*\(", t))
                _gate(f"{label}.ccs_output_current_groups",
                      _has_oc_fall and _has_oc_rise,
                      f"fall={_has_oc_fall} rise={_has_oc_rise}")
                _vectors = re.findall(r"vector\s*\(\s*([^)\s]+)", t)
                _gate(f"{label}.ccs_vectors_present", len(_vectors) > 0,
                      f"vectors={len(_vectors)}")
                _gate(f"{label}.ccs_vectors_resolve",
                      bool(_vectors) and set(_vectors).issubset(oc_tmpls),
                      f"unresolved={sorted(set(_vectors) - oc_tmpls)}")
                _gate(f"{label}.ccs_input_capacitance",
                      bool(re.search(r"capacitance\s*:", t)),
                      "receiver input-pin capacitance required for CCS")
            if cell:
                _gate(f"{label}.cell_present", cell in cells,
                      f"cell {cell!r} in {sorted(cells)[:10]}")
            cell_maps[label] = {c: set(ps) for c, ps in cells.items()}
            counts["liberty_cells"] += len(cells)
            counts["liberty_pins"] += sum(len(ps) for ps in cells.values())
            summ.update(cells=len(cells),
                        pins=sum(len(ps) for ps in cells.values()))
        elif kind == "lef":
            _gate(f"{label}.macro", "MACRO" in t)
            _gate(f"{label}.size", "SIZE" in t)
            macros = _qa_parse_lef_macros(t)
            _gate(f"{label}.macro_count", len(macros) > 0,
                  f"macros={len(macros)}")
            nopin = sorted(m for m, ps in macros.items() if not ps)
            _gate(f"{label}.macros_with_pins", bool(macros) and not nopin,
                  f"{len(macros) - len(nopin)}/{len(macros)} macros have pins"
                  + (f"; empty={nopin[:10]}" if nopin else ""))
            allp = [(m, p, i) for m, ps in macros.items() for p, i in ps.items()]
            nogeo = [f"{m}/{p}" for m, p, i in allp if not i["geometry"]]
            _gate(f"{label}.pins_with_port_geometry",
                  bool(allp) and not nogeo,
                  f"{len(allp) - len(nogeo)}/{len(allp)} pins have PORT "
                  "RECT/POLYGON" + (f"; missing={nogeo[:10]}" if nogeo else ""))
            rects = re.findall(r"RECT\s+([0-9.\-]+)\s+([0-9.\-]+)\s+"
                               r"([0-9.\-]+)\s+([0-9.\-]+)", t)
            placeholder = all(
                (abs(float(x2) - float(x1)) <= 0.1001
                 and abs(float(y2) - float(y1)) <= 0.1001)
                for (x1, y1, x2, y2) in rects) if rects else True
            _gate(f"{label}.pin_geometry", bool(rects) and not placeholder,
                  "no rects" if not rects else
                  ("placeholder-only geometry" if placeholder
                   else "real geometry"))
            _gate(f"{label}.no_geometry_warning", "no pin geometry" not in t)
            if expected.get("size_um") and cell in macros:
                sm = re.search(
                    r"^\s*MACRO\s+" + re.escape(cell) + r"\b.*?SIZE\s+([0-9.]+)"
                    r"\s+BY\s+([0-9.]+)", t, re.MULTILINE | re.DOTALL)
                try:
                    ew, eh = (float(x) for x in expected["size_um"][:2])
                    okz = bool(sm) and abs(float(sm.group(1)) - ew) < 1e-3 \
                        and abs(float(sm.group(2)) - eh) < 1e-3
                except (TypeError, ValueError):
                    okz = False
                _gate(f"{label}.size_matches_expected", okz,
                      f"lef={sm.groups() if sm else None} "
                      f"expected={expected['size_um']}")
            if cell:
                _gate(f"{label}.cell_present", cell in macros,
                      f"macro {cell!r} in {sorted(macros)[:10]}")
            cell_maps[label] = {
                m: {p for p, i in ps.items()
                    if i["use"] not in _QA_POWER_USES}
                for m, ps in macros.items()}
            counts["lef_macros"] += len(macros)
            counts["lef_pins"] += len(allp)
            counts["lef_pins_with_geometry"] += len(allp) - len(nogeo)
            summ.update(macros=len(macros), pins=len(allp),
                        pins_with_geometry=len(allp) - len(nogeo))
        else:
            _gate(f"{label}.diearea", "DIEAREA" in t)
            declared, dpins = _qa_parse_def_pins(t)
            _gate(f"{label}.pins", bool(declared) and len(dpins) > 0,
                  f"declared={declared} listed={len(dpins)}")
            _gate(f"{label}.pin_count_matches", declared == len(dpins),
                  f"declared={declared} listed={len(dpins)}")
            pin_sets[label] = {p for p, u in dpins.items()
                               if u not in _QA_POWER_USES}
            counts["def_pins"] += len(dpins)
            summ.update(pins=len(dpins))
        view_summary.append(summ)

    # ---- cross-view signal-pin consistency (power/ground pins excluded) ----
    # Liberty/LEF: the target cell (`cell`, else the single cell in the view);
    # DEF: its PINS section. An EMPTY set is compared too -- a 0-pin view never
    # agrees with a populated one (the prior code skipped empty views).
    for label, cmap in cell_maps.items():
        if cell:
            pin_sets[label] = set(cmap.get(cell, set()))
        elif len(cmap) == 1:
            pin_sets[label] = set(next(iter(cmap.values())))
        elif not cmap:
            pin_sets[label] = set()
    if len(pin_sets) >= 2:
        common = set.intersection(*pin_sets.values())
        union = set.union(*pin_sets.values())
        _gate("cross.pin_consistency", common == union and bool(union),
              ("no signal pins in any view" if not union else
               f"disagree={sorted(union - common)[:20]}; "
               + ", ".join(f"{k}={len(v)}" for k, v in pin_sets.items())))
    multi = {k: v for k, v in cell_maps.items() if len(v) > 1}
    if not cell and len(cell_maps) >= 2 and multi:
        names = [set(v) for v in cell_maps.values()]
        _gate("cross.cell_set_consistency",
              set.intersection(*names) == set.union(*names),
              f"disagree={sorted(set.union(*names) - set.intersection(*names))[:20]}")
        for c in sorted(set.intersection(*names)):
            sets = [v[c] for v in cell_maps.values()]
            if set.intersection(*sets) != set.union(*sets):
                _gate(f"cross.pin_consistency[{c}]", False,
                      f"disagree={sorted(set.union(*sets) - set.intersection(*sets))[:20]}")

    ok = bool(gates) and not fails
    passed = len(gates) - len(fails)
    note = (f"all {len(gates)} gates passed over {counts['views_checked']} "
            "view(s)" if ok else
            f"failed {len(fails)}/{len(gates)} gates: " + ", ".join(fails))
    if ok and len(pin_sets) < 2:
        note += " (single view: cross-view pin consistency not checked)"
    _assume = ["QA passes only when every requested view is signoff-complete "
               "and pin names agree",
               "power/ground pins (LEF/DEF USE POWER|GROUND, Liberty pg_pin) "
               "are excluded from cross-view pin comparison",
               "Liberty bus()/bundle() members are compared by their pin() names"]
    if ignored:
        _assume.append("ignored view entries: " + "; ".join(ignored))
    return _cde(objective="library QA (cross-view consistency)",
                status="completed" if ok else "failed",
                pdk_binding=params.get("pdk_binding", "none"),
                results={"gates": {"value": len(gates), "unit": "count"},
                         "passed_gates": {"value": passed, "unit": "count"},
                         "failed_gates": {"value": len(fails), "unit": "count"},
                         **{k: {"value": v, "unit": "count"}
                            for k, v in counts.items()}},
                signoff={"gates": gates, "failed": fails,
                         "gate_names": [g["gate"] for g in gates],
                         "views": view_summary,
                         "ignored_view_entries": ignored,
                         "pin_sets": {k: sorted(v)
                                      for k, v in pin_sets.items()},
                         "liberty_pins": sorted(set().union(*(
                             pin_sets[k] for k in pin_sets
                             if k.startswith("liberty")))),
                         "lef_pins": sorted(set().union(*(
                             pin_sets[k] for k in pin_sets
                             if k.startswith("lef")))),
                         "def_pins": sorted(set().union(*(
                             pin_sets[k] for k in pin_sets
                             if k.startswith("def"))))},
                assumptions=_assume,
                validation={"verdict": "pass" if ok else "fail",
                            "note": note})


def _characterize_corners(params):
    """Characterize the cell at EVERY declared corner and report the spread.

    `multi_corner: true` was declared in this stage's capabilities and a
    `corners` array was accepted, echoed into the envelope, and NEVER ITERATED:
    one nominal run was performed and the corner list was decorative. A library
    characterized at one corner cannot support multi-corner STA -- the slow
    corner is precisely the one timing closes against.

    Each corner must NAME ITSELF and supply what makes it a corner (its SPICE
    model file and/or temperature and/or supply). Nothing is defaulted: a corner
    with no distinguishing parameter would silently re-run the nominal point and
    report N identical 'corners'."""
    corners = params.get("corners") or []
    if not corners:
        return _characterize(params)
    norm, bad = [], []
    for i, c in enumerate(corners):
        if isinstance(c, str):
            bad.append(f"corner[{i}]={c!r}: a bare name carries no models, "
                       f"temperature or supply, so it cannot differ from nominal")
            continue
        if not isinstance(c, dict) or not c.get("name"):
            bad.append(f"corner[{i}]: needs a 'name'")
            continue
        if not any(k in c for k in ("spice_models", "temp_c", "vdd")):
            bad.append(f"corner '{c['name']}': declares no spice_models, temp_c "
                       f"or vdd, so it is indistinguishable from nominal")
            continue
        norm.append(c)
    if bad:
        return _cde(objective="multi-corner characterization", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="unusable corner definition(s): " + "; ".join(bad),
                    validation={"verdict": "fail"})
    names = [c["name"] for c in norm]
    if len(set(names)) != len(names):
        return _cde(objective="multi-corner characterization", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=f"duplicate corner name(s) in {names}",
                    validation={"verdict": "fail"})
    per_corner, failed = [], []
    base_out = _OUTPUT_DIR
    for c in norm:
        p = dict(params)
        p.pop("corners", None)
        if c.get("spice_models"):
            p["spice_models"] = c["spice_models"]
            binding = dict(p.get("pdk_binding") or {})
            binding["spice_models"] = c["spice_models"]
            p["pdk_binding"] = binding
        if c.get("temp_c") is not None:
            p["temp_c"] = c["temp_c"]
        if c.get("vdd") is not None:
            p["vdd"] = c["vdd"]
        r = _characterize(p)
        v = (r.get("validation") or {}).get("verdict")
        ev = r.get("signoff_evidence") or {}
        # Give each corner its own Liberty so they cannot overwrite one another.
        src = os.path.join(base_out, f"{params.get('cell')}.lib")
        dest_name = f"{params.get('cell')}__{c['name']}.lib"
        if os.path.exists(src):
            try:
                os.replace(src, os.path.join(base_out, dest_name))
            except OSError:
                dest_name = f"{params.get('cell')}.lib"
        per_corner.append({
            "corner": c["name"], "verdict": v, "status": r.get("status"),
            "liberty": dest_name,
            "temp_c": c.get("temp_c"), "vdd": c.get("vdd"),
            "spice_models": c.get("spice_models"),
            "delay_table_ns": ev.get("delay_table_ns"),
            "spice_converged": ev.get("spice_converged"),
            "zero_filled_cells": ev.get("liberty_zero_filled_cells"),
            "note": (r.get("validation") or {}).get("note"),
        })
        if r.get("status") != "completed" or v not in ("pass",):
            failed.append(c["name"])
    # Corner spread of the worst-case (largest) measured delay per corner.
    spread = {}
    worst = {}
    for pc in per_corner:
        tbl = pc.get("delay_table_ns") or []
        vals = [v for row in tbl for v in row if isinstance(v, (int, float))]
        if vals:
            worst[pc["corner"]] = max(vals)
    if len(worst) >= 2:
        lo_c = min(worst, key=worst.get)
        hi_c = max(worst, key=worst.get)
        spread = {"fastest_corner": lo_c, "fastest_max_delay_ns": worst[lo_c],
                  "slowest_corner": hi_c, "slowest_max_delay_ns": worst[hi_c],
                  "ratio": (worst[hi_c] / worst[lo_c]) if worst[lo_c] else None}
        # Every corner producing an IDENTICAL table means the corner definitions
        # never reached the simulation -- the same no-op class as a Monte Carlo
        # sweep that does not vary anything.
        spread["corners_differ"] = len({round(v, 12) for v in worst.values()}) > 1
    verdict = "pass"
    note = f"characterized at {len(norm)} corner(s): {', '.join(names)}"
    if failed:
        verdict = "fail"
        note = f"corner(s) failed characterization: {', '.join(failed)}"
    elif len(worst) < len(norm):
        verdict = "fail"
        note = ("one or more corners produced no measurable delay, so the "
                "multi-corner library is incomplete")
    elif spread and spread.get("corners_differ") is False:
        verdict = "fail"
        note = ("every corner produced an IDENTICAL delay table: the corner "
                "definitions never reached the simulation, so these are not "
                "distinct corners")
    return _cde(
        objective=f"multi-corner characterization of {params.get('cell')} "
                  f"({len(norm)} corners)",
        status="completed" if verdict == "pass" else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"corners": {"value": len(norm), "unit": "count"},
                 "slowest_max_delay_ns": {"value": spread.get("slowest_max_delay_ns"),
                                          "unit": "ns"}},
        qor={"corner_count": len(norm), "corners": names,
             "failed_corners": failed, "corner_spread": spread},
        signoff={"per_corner": per_corner, "corner_spread": spread,
                 "corners_requested": names, "failed_corners": failed},
        margin={"method": "corner_spread",
                "ratio_slow_over_fast": spread.get("ratio")},
        assumptions=["each corner is characterized by a full independent SPICE "
                     "sweep using that corner's models/temperature/supply; no "
                     "corner is interpolated or scaled from another"],
        validation={"verdict": verdict, "note": note},
        provenance={"ngspice": _ngspice_version(), "corners": names},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("characterize_liberty", "characterize_sequential", "setup_hold",
             "create_lef", "create_def"):
        _cell = params.get("cell")
        if not _is_ident(_cell):
            return _cde(objective="library characterization", status="failed",
                        error=f"invalid or missing 'cell' identifier: {_cell!r}",
                        validation={"verdict": "fail"})
    if s == "characterize_liberty":
        if not shutil.which("ngspice"):
            return _cde(objective="characterize", status="failed",
                        error="ngspice not found on PATH", validation={"verdict": "fail"})
        # A declared corner list is now ITERATED, not merely echoed.
        if params.get("corners"):
            return _characterize_corners(params)
        return _characterize(params)
    if s in ("characterize_sequential", "setup_hold"):
        if not shutil.which("ngspice"):
            return _cde(objective="characterize sequential", status="failed",
                        error="ngspice not found on PATH", validation={"verdict": "fail"})
        return _characterize_sequential(params)
    if s == "create_lef":
        return _create_lef(params)
    if s == "create_def":
        return _create_def(params)
    if s == "assemble_library":
        return _assemble_library(params)
    if s == "library_qa":
        return _library_qa(params)
    return _cde(objective="library characterization", status="failed",
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
                    "sha256": _capture_digest(value), "head": value[:120]}
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
