#!/usr/bin/env python3
"""analog_spice_utils.py -- real analog SPICE via ngspice (+ Xschem netlisting).

Two scenarios:
  * simulate -- run ngspice in batch (`ngspice -b deck`) on a SPICE netlist/deck,
    parse `.measure` results and the analysis type (DC/AC/transient/noise), and
    report the measured quantities.
  * netlist  -- netlist an Xschem schematic (`xschem -n -s -q <sch> -o <dir>`) to
    a SPICE netlist for a subsequent simulate.

Node-aware: device models / corner come from the PDK binding. Results conform to
the Common Design Envelope.
"""
import json
import math
import os
import random
import re
import shutil
import subprocess
import time

TOOL = "analog-spice"
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
    try:
        import shlex
        line = (" ".join(shlex.quote(str(c)) for c in cmd)
                if isinstance(cmd, (list, tuple)) else str(cmd))
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
    L = ["# " + tool + " \u2014 human summary", ""]
    L.append("- **Status:** " + status.upper())
    if r.get("objective"):
        L.append("- **Objective:** " + str(r["objective"]))
    val = r.get("validation") or {}
    if isinstance(val, dict) and val.get("verdict"):
        note = (" \u2014 " + str(val["note"])) if val.get("note") else ""
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
        if (low.endswith((".log", ".tcl", ".ys", ".sh", ".do", ".sp", ".cir", ".spice"))
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
    prov = r.get("provenance") or {}
    plines = []
    if isinstance(prov, dict) and prov.get("runtime_s") is not None:
        plines.append("- Runtime: " + str(prov["runtime_s"]) + " s")
    pb = r.get("pdk_binding")
    if pb and pb != "none":
        plines.append("- PDK binding: " + (str(pb) if not isinstance(pb, dict) else str(pb.get("pdk", pb))))
    if plines:
        L += ["## Provenance", ""] + plines + [""]
    L += ["## Where to find more", "",
          "- `common_design_envelope.json` \u2014 full machine-readable envelope (this dir)",
          "- `logs/` \u2014 verbatim ngspice/xschem log and the exact run command", ""]
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
    for fn, lbl in ((_write_report_md, "report"), (_write_summary_md, "summary")):
        try:
            fn(results)
        except Exception as _e:
            print("[" + str(TOOL) + "] " + lbl + " generation skipped: " + str(_e), flush=True)
    try:
        _organize_output()
    except Exception as _e:
        print("[" + str(TOOL) + "] output organize skipped: " + str(_e), flush=True)


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def _ngspice_version():
    try:
        out = subprocess.run(["ngspice", "-v"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return txt.splitlines()[0] if txt else "ngspice"
    except Exception:
        return "ngspice"


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, margin=None, error=None, engine="ngspice"):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": engine, "version": _ngspice_version()}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": margin or {"method": "spice_analysis"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _netlist(params):
    if not shutil.which("xschem"):
        return _cde(objective="netlist schematic", status="failed", engine="xschem",
                    error="xschem not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    sch = params.get("schematic")
    if not sch or not os.path.exists(str(sch)):
        return _cde(objective="netlist schematic", status="failed", engine="xschem",
                    pdk_binding=binding or "none",
                    error=f"schematic not found: {sch}", validation={"verdict": "fail"})
    outdir = _OUTPUT_DIR
    cmd = ["xschem", "-n", "-s", "-q", "-x", "--no_x", "-o", outdir, str(sch)]
    rcfile = params.get("xschemrc") or binding.get("xschemrc")
    if rcfile and os.path.exists(str(rcfile)):
        cmd += ["--rcfile", str(rcfile)]
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "xschem.log"), "w").write(out)
    stem = os.path.splitext(os.path.basename(str(sch)))[0]
    netlist = None
    for cand in (f"{stem}.spice", f"{stem}.sp", f"{stem}.cir"):
        if os.path.exists(os.path.join(outdir, cand)):
            netlist = cand
            break
    if not netlist:
        return _cde(objective=f"netlist {stem}", status="failed", engine="xschem",
                    pdk_binding=binding or "none",
                    error="xschem produced no SPICE netlist; see xschem.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"xschem": "xschem", "log": "xschem.log"})
    return _cde(
        objective=f"netlist schematic {stem}", status="completed", engine="xschem",
        pdk_binding=binding or "none",
        results={"netlist": {"value": netlist, "unit": "-"}},
        signoff={"netlist": netlist, "report": "xschem.log"},
        inputs_ref={"schematic": sch},
        assumptions=["SPICE netlist for a subsequent simulate scenario"],
        validation={"verdict": "pass", "note": "SPICE netlist generated"},
        provenance={"xschem": "xschem", "runtime_s": round(elapsed, 3), "log": "xschem.log"},
    )


_NONCONVERGENCE_PATTERNS = (
    # ngspice reports a failed solve in several distinct wordings depending on
    # which solver gave up. Screening for only "singular matrix" / "no
    # convergence" misses the most COMMON transient failure of all -- the
    # timestep collapsing -- and every gmin/source-stepping fallback message.
    "singular matrix",
    "no convergence",
    "convergence failure",
    "timestep too small",
    "iteration limit reached",
    "too many iterations",
    "gmin stepping failed",
    "source stepping failed",
    "dynamic gmin stepping failed",
    "transient analysis failed",
    "doanalyses: iteration limit reached",
    "matrix is singular",
    "fatal error",
)

# A run that ABORTED is a different failure from one that failed to converge, and
# both are different from a clean run. Observed verbatim from ngspice 39 on a deck
# referencing an undefined node: the tool prints these and STILL EXITS 0, so exit
# code alone cannot be the gate.
_ABORT_PATTERNS = (
    "run simulation(s) aborted",
    "analysis not run",
    "doanalyses: not found",
    "no data saved",
    "simulation interrupted",
)


def _scan_aborted(logtext):
    """Return (aborted, [matched patterns]) for an ngspice log."""
    low = (logtext or "").lower()
    hits = [p for p in _ABORT_PATTERNS if p in low]
    return bool(hits), hits


def _scan_convergence(logtext):
    """Return (converged, [matched patterns]) for an ngspice log.

    A non-convergent solve is NOT a slow answer, it is NO answer: the operating
    point or timestep never satisfied the tolerances, so every number downstream
    of it is meaningless. Returns the patterns that matched so the envelope can
    say WHICH failure occurred rather than just 'convergence failure'."""
    low = (logtext or "").lower()
    hits = [p for p in _NONCONVERGENCE_PATTERNS if p in low]
    return (not hits), hits


def _requested_measures(deck_text):
    """Return the names of every `.measure` requested by the deck.

    Needed because a deck that asked for 8 measurements and produced 0 is a
    FAILED run, but the parsed-measure dict alone cannot distinguish that from a
    deck that asked for nothing. ngspice accepts `.meas`/`.measure` followed by
    the analysis type then the result name."""
    names = []
    for m in re.finditer(r"^\s*\.meas(?:ure)?\s+(?:tran|ac|dc|op|noise|sp)?\s*"
                         r"([A-Za-z_][A-Za-z0-9_]*)", deck_text or "", re.M | re.I):
        names.append(m.group(1))
    return names


def _parse_measures(text):
    """Parse ngspice `.measure` results: 'name = value ...' lines.

    ngspice echoes measurements as 'name = <number>'. We restrict to the section
    after measurement output and drop known non-measurement echoes (stack sizes,
    version banners, node voltages) to avoid false captures."""
    _noise = {"v", "i", "temp", "tnom", "stack", "size", "version", "note",
              "warning", "error", "reltol", "abstol", "vntol", "trtol", "gmin"}
    meas = {}
    for m in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+0-9.eE]+)",
                         text, re.M):
        name, val = m.group(1), m.group(2)
        if name.lower() in _noise:
            continue
        try:
            meas[name] = float(val)
        except ValueError:
            pass
    return meas


def _simulate(params):
    if not shutil.which("ngspice"):
        return _cde(objective="SPICE simulation", status="failed",
                    error="ngspice not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    # Incompatible inputs: the deck source is exactly one of deck / netlist /
    # deck_text. Providing more than one is ambiguous (which deck runs?) -- fail
    # closed rather than silently picking one by precedence.
    _deck_srcs = [k for k in ("deck", "netlist", "deck_text") if params.get(k)]
    if len(_deck_srcs) > 1:
        return _cde(objective="SPICE simulation", status="failed", pdk_binding=binding or "none",
                    error="provide exactly one deck source; got multiple: "
                          + ", ".join(_deck_srcs), validation={"verdict": "fail"})
    deck = params.get("deck") or params.get("netlist")
    if params.get("deck_text"):
        deck = os.path.join(_WORK_DIR, "deck.sp")
        open(deck, "w").write(params["deck_text"])
    if not deck or not os.path.exists(str(deck)):
        return _cde(objective="SPICE simulation", status="failed", pdk_binding=binding or "none",
                    error=f"deck/netlist not found: {deck}", validation={"verdict": "fail"})
    # Simulation-control knobs: temperature and convergence tolerance map to
    # ngspice `.options temp=`/`reltol=`; `extra_options` is a free-form list of
    # additional `.options` tokens (e.g. "gmin=1e-13", "method=gear"). When any
    # are set we compile an augmented deck that injects an `.options` line after
    # the title (line 1), leaving the caller's deck untouched.
    temp_c = params.get("temp_c")
    reltol = params.get("reltol")
    extra_options = params.get("extra_options") or []
    opt_tokens = []
    if temp_c is not None:
        opt_tokens.append("temp=%s" % float(temp_c))
    if reltol is not None:
        opt_tokens.append("reltol=%s" % float(reltol))
    opt_tokens += [str(o) for o in extra_options]
    if opt_tokens:
        try:
            src = open(str(deck)).read().splitlines()
            title = src[:1] or ["* augmented deck"]
            body = src[1:]
            aug = os.path.join(_WORK_DIR, "deck_opts.sp")
            open(aug, "w").write("\n".join(title + [".options " + " ".join(opt_tokens)]
                                           + body) + "\n")
            deck = aug
        except Exception as _e:
            print("[" + str(TOOL) + "] deck .options augmentation failed; using "
                  "original deck: " + str(_e), flush=True)
    log = os.path.join(_OUTPUT_DIR, "ngspice.log")
    cmd = ["ngspice", "-b", "-o", log, str(deck)]
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    logtext = out
    if os.path.exists(log):
        logtext += "\n" + open(log).read()
    open(log, "w").write(logtext)
    if proc.returncode != 0 and "error" in out.lower() and "aborted" in out.lower():
        return _cde(objective="SPICE simulation", status="failed", pdk_binding=binding or "none",
                    error="ngspice aborted; see ngspice.log:\n" + logtext[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"ngspice": _ngspice_version(), "log": "ngspice.log"})
    measures = _parse_measures(logtext)
    _deck_text = open(deck).read()
    analysis = "unknown"
    for a in ("tran", "ac", "dc", "noise", "op", "disto", "tf", "sens"):
        if re.search(r"^\." + a + r"\b", _deck_text, re.M | re.I):
            analysis = a
            break
    converged, _conv_hits = _scan_convergence(logtext)
    _aborted, _abort_hits = _scan_aborted(logtext)
    # MEASUREMENT COMPLETENESS. A deck that requested measurements and produced
    # NONE ran, exited 0, and previously reported status=completed/verdict=pass
    # with an empty results dict -- a pass carrying no measured evidence at all.
    # ngspice also prints "measurement failed" per failed .measure while still
    # exiting 0.
    _requested = _requested_measures(_deck_text)
    _missing = [n for n in _requested if n not in measures]
    _meas_failed = len(re.findall(r"measure(?:ment)?\s+failed|"
                                  r"can't\s+measure|no\s+such\s+(?:vector|measure)",
                                  logtext, re.I))
    if not converged:
        verdict = "fail"
        _note = ("SPICE did not converge (" + ", ".join(_conv_hits)
                 + "); every reported quantity is meaningless")
    elif _aborted:
        verdict = "fail"
        _note = ("the ngspice run ABORTED (" + ", ".join(_abort_hits)
                 + "); ngspice still exited 0, so this is not visible from the "
                   "exit status alone")
    elif _requested and not measures:
        # Asked for measurements, got none back.
        verdict = "fail"
        _note = (f"deck requested {len(_requested)} measurement(s) "
                 f"({', '.join(_requested[:6])}) and NONE were produced; the run "
                 f"completed but measured nothing")
    elif _missing:
        verdict = "fail"
        _note = (f"{len(_missing)} of {len(_requested)} requested measurement(s) "
                 f"missing from the ngspice output: {', '.join(_missing[:6])}")
    elif not _requested and not measures:
        # Nothing was asked for and nothing measured: the simulation ran, but
        # there is no measured evidence to judge, so this is not a pass.
        verdict = "review"
        _note = ("simulation converged but the deck contains no .measure "
                 "directives, so no quantity was measured to judge")
    else:
        verdict = "pass"
        _note = f"{analysis} converged; {len(measures)} measurement(s)"
    return _cde(
        objective=f"ngspice {analysis} simulation", status="completed",
        pdk_binding=binding or "none",
        results={k: {"value": v, "unit": "-"} for k, v in measures.items()} or
                {"converged": {"value": converged, "unit": "bool"}},
        qor={"analysis": analysis, "measures": measures, "converged": converged,
             "measurements_requested": len(_requested),
             "measurements_returned": len(measures),
             "measurements_missing": len(_missing)},
        signoff={"analysis": analysis, "measures": measures,
                 "converged": converged,
                 "nonconvergence_signatures": _conv_hits,
                 "aborted": _aborted,
                 "abort_signatures": _abort_hits,
                 "measurements_requested": _requested,
                 "measurements_missing": _missing,
                 "measure_failure_lines": _meas_failed,
                 "temp_c": temp_c if temp_c is not None else "deck-default",
                 "reltol": reltol if reltol is not None else "ngspice-default",
                 "extra_options": [str(o) for o in extra_options],
                 "report": "ngspice.log"},
        inputs_ref={"deck": deck},
        assumptions=["device models / corner from the deck or PDK binding; measured "
                     "quantities parsed from .measure output",
                     "single-run nominal simulation: NO Monte Carlo, mismatch or "
                     "statistical spread is computed by this scenario"],
        margin={"method": "spice_" + analysis},
        validation={"verdict": verdict, "note": _note},
        provenance={"ngspice": _ngspice_version(), "runtime_s": round(elapsed, 3),
                    "log": "ngspice.log"},
    )


def _monte_carlo(params):
    """Statistical (Monte Carlo / mismatch) analysis over repeated SPICE runs.

    An analog spec is a claim about SILICON, and silicon varies. A single nominal
    simulation says nothing about the spread, so a design that meets its spec at
    nominal and fails at 2 sigma was previously indistinguishable from one with
    real margin. This runs the deck N times, perturbing caller-declared parameters
    with a seeded Gaussian, and reports mean / sigma / min / max per measurement
    plus the YIELD against any supplied spec limits.

    Parameters are perturbed by this tool, NOT invented: each entry of `mc_params`
    must name the parameter and give a nominal and a sigma. Nothing is defaulted,
    because a fabricated sigma would produce a confident, meaningless yield."""
    if not shutil.which("ngspice"):
        return _cde(objective="Monte Carlo", status="failed",
                    error="ngspice not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    deck = params.get("deck") or params.get("netlist")
    if params.get("deck_text"):
        deck = os.path.join(_WORK_DIR, "mc_deck.sp")
        open(deck, "w").write(params["deck_text"])
    if not deck or not os.path.exists(str(deck)):
        return _cde(objective="Monte Carlo", status="failed", pdk_binding=binding or "none",
                    error="deck not found", validation={"verdict": "fail"})
    mc_params = params.get("mc_params") or []
    if not mc_params:
        return _cde(objective="Monte Carlo", status="failed", pdk_binding=binding or "none",
                    error=("'mc_params' is required: a list of {name, nominal, sigma} "
                           "(sigma absolute, or sigma_pct as a percentage of nominal). "
                           "No distribution is assumed -- an invented sigma would "
                           "produce a confident but meaningless yield."),
                    validation={"verdict": "fail"})
    bad = []
    for p in mc_params:
        if not isinstance(p, dict) or not p.get("name"):
            bad.append(str(p))
        elif p.get("nominal") is None:
            bad.append(f"{p.get('name')}: no nominal")
        elif p.get("sigma") is None and p.get("sigma_pct") is None:
            bad.append(f"{p.get('name')}: no sigma or sigma_pct")
    if bad:
        return _cde(objective="Monte Carlo", status="failed", pdk_binding=binding or "none",
                    error="incomplete mc_params: " + "; ".join(bad),
                    validation={"verdict": "fail"})
    try:
        runs = int(params.get("runs", 100))
    except (TypeError, ValueError):
        runs = 100
    if runs < 2:
        return _cde(objective="Monte Carlo", status="failed", pdk_binding=binding or "none",
                    error=f"runs={runs}: a spread needs at least 2 samples",
                    validation={"verdict": "fail"})
    seed = int(params.get("seed", 1))
    rng = random.Random(seed)
    deck_src = open(deck).read().splitlines()
    requested = _requested_measures("\n".join(deck_src))
    # WHERE the injected .param goes decides whether the sweep happens at all.
    # ngspice takes the LAST definition of a parameter, so injecting after the
    # title (the obvious choice) is silently overridden by the deck's own
    # `.param rval=...` further down -- every sample then runs at nominal and the
    # tool reports sigma=0 and a confident 100% yield from a simulation that never
    # varied anything. Inject immediately BEFORE `.end` so the perturbed value
    # wins, and verify afterwards that the values actually moved.
    _end_ix = len(deck_src)
    for _i in range(len(deck_src) - 1, -1, -1):
        if re.match(r"^\s*\.end\s*$", deck_src[_i], re.I):
            _end_ix = _i
            break
    samples = []          # per-run {measure: value}
    draws = []            # per-run {param: value}
    failed_runs = []
    t0 = time.time()
    for i in range(runs):
        draw = {}
        for p in mc_params:
            nom = float(p["nominal"])
            sig = (float(p["sigma"]) if p.get("sigma") is not None
                   else abs(nom) * float(p["sigma_pct"]) / 100.0)
            draw[str(p["name"])] = rng.gauss(nom, sig)
        plines = [".param %s=%.10g" % (k, v) for k, v in sorted(draw.items())]
        rd = os.path.join(_WORK_DIR, f"mc_{i:04d}.sp")
        open(rd, "w").write("\n".join(deck_src[:_end_ix] + plines
                                      + deck_src[_end_ix:]) + "\n")
        rlog = os.path.join(_WORK_DIR, f"mc_{i:04d}.log")
        proc = subprocess.run(["ngspice", "-b", "-o", rlog, rd],
                              capture_output=True, text=True, cwd=_WORK_DIR)
        txt = proc.stdout + "\n" + proc.stderr
        if os.path.exists(rlog):
            txt += "\n" + open(rlog, errors="ignore").read()
        conv, chits = _scan_convergence(txt)
        abrt, ahits = _scan_aborted(txt)
        m = _parse_measures(txt)
        missing = [n for n in requested if n not in m]
        if not conv or abrt or missing:
            # A non-convergent or incomplete sample is DISCARDED FROM THE
            # STATISTICS and counted, never silently treated as a passing sample.
            # Dropping it quietly would shrink the tail and RAISE the reported
            # yield -- the failures are exactly the samples that matter.
            failed_runs.append({"run": i, "converged": conv, "aborted": abrt,
                                "missing": missing,
                                "signatures": (chits + ahits)[:3]})
            continue
        samples.append(m)
        draws.append(draw)
    elapsed = time.time() - t0
    ok = len(samples)
    stats = {}
    names = sorted({k for s in samples for k in s})
    for n in names:
        vals = [s[n] for s in samples if n in s]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        var = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
               if len(vals) > 1 else 0.0)
        sd = math.sqrt(var)
        stats[n] = {"samples": len(vals), "mean": mean, "sigma": sd,
                    "min": min(vals), "max": max(vals),
                    # 3-sigma corners are a NORMAL-DISTRIBUTION EXTRAPOLATION from
                    # a finite sample, not an observed value. Labelled as such.
                    "minus_3sigma": mean - 3 * sd, "plus_3sigma": mean + 3 * sd}
    # Yield against caller-supplied spec limits. No limit is invented, so a
    # measurement with no declared limit is reported without a pass/fail.
    limits = params.get("spec_limits") or {}
    yield_rows = []
    for n, lim in limits.items():
        lo = lim.get("min") if isinstance(lim, dict) else None
        hi = lim.get("max") if isinstance(lim, dict) else None
        vals = [s[n] for s in samples if n in s]
        if not vals:
            yield_rows.append({"measure": n, "status": "not_assessable",
                               "reason": "no samples produced this measurement"})
            continue
        inside = [v for v in vals
                  if (lo is None or v >= float(lo)) and (hi is None or v <= float(hi))]
        yield_rows.append({"measure": n, "min": lo, "max": hi,
                           "samples": len(vals), "within_spec": len(inside),
                           "yield_pct": round(100.0 * len(inside) / len(vals), 3),
                           "status": "pass" if len(inside) == len(vals) else "fail"})
    unknown_limits = [n for n in limits if n not in names]
    target_yield = params.get("target_yield_pct")
    worst_yield = min((y["yield_pct"] for y in yield_rows
                       if "yield_pct" in y), default=None)
    # NO-OP SWEEP DETECTION. If every parameter was drawn with a non-zero sigma
    # and the draws really did differ, but EVERY measurement came back identical
    # across samples, then the perturbation never reached the simulation (a
    # shadowed .param, a parameter the deck does not reference, a typo in the
    # name). The statistics would then be a confident sigma=0 distribution and a
    # 100% yield describing a sweep that never happened -- the most dangerous
    # possible output of this scenario, because it looks like excellent margin.
    _drawn_varied = any(
        len({round(d.get(p["name"], 0.0), 12) for d in draws}) > 1
        for p in mc_params) if len(draws) > 1 else False
    _sigma_requested = any(
        (float(p["sigma"]) if p.get("sigma") is not None
         else abs(float(p["nominal"])) * float(p["sigma_pct"]) / 100.0) > 0
        for p in mc_params)
    _all_flat = bool(stats) and all(s["sigma"] == 0.0 for s in stats.values())
    _sweep_ineffective = bool(_sigma_requested and _drawn_varied and _all_flat)
    if ok < 2:
        verdict = "fail"
        note = (f"only {ok} of {runs} runs produced usable measurements; there is "
                f"no distribution to report")
    elif _sweep_ineffective:
        verdict = "fail"
        note = ("the perturbation never reached the simulation: parameters "
                + ", ".join(sorted(d for p in mc_params for d in [str(p["name"])]))
                + " were drawn with non-zero spread yet EVERY measurement is "
                  "identical across samples. Check that the deck references the "
                  "parameter (e.g. R1 a b {name}) and does not redefine it. The "
                  "statistics below describe a sweep that did not happen.")
    elif unknown_limits:
        verdict = "fail"
        note = ("spec limits reference measurements the deck never produced: "
                + ", ".join(sorted(unknown_limits)))
    elif failed_runs:
        # Samples were lost. The surviving statistics are conditioned on the
        # survivors, so the spread is understated by an unknown amount.
        verdict = "review"
        note = (f"{len(failed_runs)} of {runs} sample(s) did not converge or were "
                f"incomplete and were EXCLUDED; the reported spread is conditioned "
                f"on the {ok} surviving samples and understates the true tail")
    elif target_yield is not None and worst_yield is not None and \
            worst_yield < float(target_yield):
        verdict = "fail"
        note = f"worst yield {worst_yield}% is below the target {target_yield}%"
    elif any(y.get("status") == "fail" for y in yield_rows):
        verdict = "fail"
        note = "one or more measurements fall outside their spec limits"
    elif not limits:
        verdict = "review"
        note = (f"{ok} samples characterised, but no spec_limits were supplied so "
                f"no yield verdict can be formed")
    else:
        verdict = "pass"
        note = f"{ok}/{runs} samples within spec (worst yield {worst_yield}%)"
    return _cde(
        objective=f"Monte Carlo ({runs} runs) of {os.path.basename(str(deck))}",
        status="completed" if ok >= 2 else "failed",
        pdk_binding=binding or "none",
        results={n: {"value": s["mean"], "unit": "-", "sigma": s["sigma"]}
                 for n, s in stats.items()},
        qor={"runs_requested": runs, "runs_usable": ok,
             "runs_failed": len(failed_runs), "seed": seed,
             "statistics": stats, "yield": yield_rows,
             "worst_yield_pct": worst_yield},
        signoff={"statistics": stats, "yield": yield_rows,
                 "failed_runs": failed_runs[:20],
                 "failed_run_count": len(failed_runs),
                 "sweep_effective": not _sweep_ineffective,
                 "draws_varied": _drawn_varied,
                 "mc_params": mc_params, "seed": seed,
                 "spec_limits": limits,
                 "target_yield_pct": target_yield,
                 "measurements_requested": requested},
        inputs_ref={"deck": deck},
        margin={"method": f"monte_carlo_{runs}_runs_seed_{seed}",
                "worst_yield_pct": worst_yield},
        assumptions=[
            "parameters are perturbed by an INDEPENDENT Gaussian per parameter "
            "using the caller-supplied nominal and sigma; no correlation model and "
            "no PDK statistical model is applied",
            "device-level mismatch is only modelled to the extent the caller "
            "declares it as mc_params; intra-die mismatch from the PDK statistical "
            "corner decks is NOT used",
            "+/-3 sigma figures are a normal extrapolation from a finite sample, "
            "not observed values",
            f"run-to-run reproducibility comes from seed={seed}",
        ],
        validation={"verdict": verdict, "note": note},
        provenance={"ngspice": _ngspice_version(), "runtime_s": round(elapsed, 3),
                    "runs": runs, "seed": seed},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("simulate", "spice", "run_spice"):
        return _simulate(params)
    if s in ("netlist", "netlist_schematic"):
        return _netlist(params)
    if s in ("monte_carlo", "montecarlo", "mc", "mismatch", "statistical"):
        return _monte_carlo(params)
    return _cde(objective="analog SPICE", status="failed",
                error=f"unknown scenario '{s}'; supported: simulate, netlist, "
                      f"monte_carlo",
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
