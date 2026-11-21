#!/usr/bin/env python3
"""debug_utils.py -- failure triage and root-cause analysis for the chip-debug tool.

Buckets failures by a normalized error signature, keeps the smallest-seed
deterministic reproducer per bucket, and ranks root-cause hypotheses from evidence
patterns in the messages/logs. Node-agnostic. Results conform to the CDE.
"""
import json
import os
import re

import reproducer
import vcd_reader

TOOL = "debug"
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


def _cde(objective, status, results=None, signoff=None, assumptions=None,
         validation=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "debug-triage", "version": "1.0.0"}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "shared_artifact",
        "results": results or {}, "qor_metrics": {},
        "signoff_evidence": signoff or {}, "margin": {"method": "evidence_ranking"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic triage"},
    }
    if error:
        env["error"] = error
    return env


def _signature(msg):
    s = msg.lower()
    s = re.sub(r"0x[0-9a-f]+", "0xADDR", s)
    s = re.sub(r"\b\d+\b", "N", s)
    return s.strip()


_HYPOTHESES = [
    (r"scoreboard mismatch|mismatch|expected .* got", "Functional data mismatch: "
     "check reference model / DUT datapath", 0.8),
    (r"timeout|waiting for|hang|deadlock", "Handshake/protocol stall: check "
     "ready/valid or arbitration", 0.7),
    (r"assertion|assert .* failed|sva", "Assertion violation: inspect the failing "
     "property and its antecedent", 0.75),
    (r"x propagation|unknown|'hx|xxxx", "X-propagation: check reset/init of the "
     "flagged signals", 0.65),
    (r"reset|init", "Reset sequencing: check reset polarity/duration", 0.5),
]


def _rank(msg, log="", waveform=None):
    text = (msg + " " + (log or "")).lower()
    ranked = []
    for pat, hyp, conf in _HYPOTHESES:
        if re.search(pat, text):
            ranked.append({"hypothesis": hyp, "confidence": conf,
                           "evidence": pat, "evidence_source": "log_text"})

    # WAVEFORM-DERIVED HYPOTHESES.
    # These outrank text matches, and deliberately so: a log message is what the
    # testbench AUTHOR predicted might go wrong, while the trace is what the
    # design ACTUALLY did. An X on a signal at a specific time is a located,
    # checkable fact; "mismatch" in a string is a category.
    if waveform:
        for x in (waveform.get("x_states") or [])[:5]:
            if x.get("kind") != "x":
                continue
            ranked.append({
                "hypothesis": ("X on '%s' at %s: uninitialised state, an "
                               "incomplete reset, or a contended driver. Trace "
                               "this signal back to its driver first."
                               % (x["signal"], x.get("time_human", x["time"]))),
                "confidence": 0.9, "evidence": "vcd: %s = %s @ t=%s" % (
                    x["signal"], x["value"], x["time"]),
                "evidence_source": "waveform"})
        stuck = waveform.get("stuck_signals") or []
        if stuck and len(stuck) <= 40:
            names = ", ".join(s["signal"] for s in stuck[:6])
            ranked.append({
                "hypothesis": ("%d signal(s) never changed after settle (%s%s). "
                               "If any is a control/enable that should have "
                               "toggled, the fault is upstream of it; tie-offs "
                               "and config inputs are expected to be constant."
                               % (len(stuck), names,
                                  " ..." if len(stuck) > 6 else "")),
                "confidence": 0.45, "evidence": "vcd: no transitions after settle",
                "evidence_source": "waveform"})

    ranked.sort(key=lambda h: -h["confidence"])
    if ranked:
        return ranked
    # No pattern matched. Say what is missing rather than telling the engineer to
    # go and do the analysis this tool exists to do.
    if waveform is None:
        return [{"hypothesis": ("Unclassified failure and NO waveform was "
                                "supplied. Re-run with `waveform` pointing at "
                                "the VCD so X-states and signal activity around "
                                "the failure can be examined."),
                 "confidence": 0.3, "evidence": "no known pattern; no trace",
                 "evidence_source": "none"}]
    return [{"hypothesis": ("Unclassified failure; the waveform was read and "
                            "showed no X-states, so suspect a functional/data "
                            "error rather than an initialisation problem."),
             "confidence": 0.35, "evidence": "no known pattern; trace clean of X",
             "evidence_source": "waveform"}]


def _analyze_waveform(params):
    """Read the trace if one was supplied.

    Returns (waveform_facts_or_None, status_dict). A trace that could not be read
    is reported as not_assessable -- NEVER as a trace with nothing wrong in it.
    """
    path = params.get("waveform") or params.get("vcd")
    if not path:
        return None, {"assessable": False, "supplied": False,
                      "note": ("no waveform supplied; hypotheses are ranked from "
                               "log text alone, which reflects what the "
                               "testbench author anticipated rather than what "
                               "the design did")}
    try:
        vcd = vcd_reader.read(path)
    except vcd_reader.VcdUnavailable as e:
        return None, {"assessable": False, "supplied": True, "error": str(e),
                      "note": ("waveform could not be read; this is NOT evidence "
                               "that the trace is clean")}
    settle = int(params.get("settle_time", 0) or 0)
    ignore = params.get("ignore_signals") or ()
    facts = {
        "x_states": vcd_reader.find_x_states(vcd, settle_time=settle,
                                             ignore=ignore),
        "stuck_signals": vcd_reader.find_stuck_signals(vcd, settle_time=settle),
        "settle_time": settle,
        "trace": vcd_reader.summarize(vcd)}
    ft = params.get("failure_time")
    if ft is not None:
        window = int(params.get("window", 100) or 100)
        facts["activity_before_failure"] = vcd_reader.activity_window(
            vcd, params.get("signals"), max(0, int(ft) - window), int(ft))
    return facts, {"assessable": True, "supplied": True,
                   "settle_time_excluded": settle,
                   "basis": "parsed_vcd"}


def _bucket(params):
    failures = params.get("failures", [])
    if not failures:
        return _cde(objective="bucket failures", status="failed",
                    error="no 'failures' supplied", validation={"verdict": "fail"})
    buckets = {}
    for f in failures:
        sig = _signature(f.get("message", ""))
        buckets.setdefault(sig, []).append(f)
    wave, wave_status = _analyze_waveform(params)
    out = []
    for sig, items in buckets.items():
        rep = min(items, key=lambda x: x.get("seed", 1 << 30))
        out.append({"signature": sig, "count": len(items),
                    "minimal_reproducer": {
                        "test": rep.get("test"), "seed": rep.get("seed"),
                        "is_minimized": False,
                        "determinism": (
                            "not assessed in bucketing -- run the `reduce` "
                            "scenario with `repro_cmd` to establish it by "
                            "re-execution")},
                    "ranked_hypotheses": _rank(rep.get("message", ""),
                                               rep.get("log"), wave)})
    out.sort(key=lambda b: -b["count"])
    return _cde(objective="failure triage", status="completed",
                results={"failures": {"value": len(failures), "unit": "count",
                                      "class": "diagnostic",
                                      "basis": "supplied_by_caller"},
                         "buckets": {"value": len(out), "unit": "count",
                                     "class": "diagnostic",
                                     "basis": "error_signature_clustering"}},
                signoff={"buckets": out,
                         "waveform_analysis": wave_status,
                         "waveform_findings": wave},
                assumptions=["signature normalizes addresses/numbers; hypotheses "
                             "are evidence-ranked, not proven",
                             "bucketing does NOT establish determinism or "
                             "minimality of any representative reproducer"],
                validation={"verdict": "completed"})


def _reduce(params):
    """Reduce a failure to a MINIMAL reproducer and OBSERVE its determinism.

    Replaces two false claims. Previously this function performed no reduction
    (it echoed the supplied test/seed) and declared the reproducer deterministic
    whenever a `seed` field happened to be present, without ever re-running it.

    Both properties are now established by EXECUTION, and when the caller gives
    this tool no way to execute anything, both are reported as not_assessable
    rather than assumed.
    """
    f = params.get("failure") or (params.get("failures") or [{}])[0]
    wave, wave_status = _analyze_waveform(params)

    # --- REDUCTION: real ddmin, driven by an executed oracle -----------------
    items = params.get("stimulus") or params.get("transactions")
    red_status = {"attempted": False,
                  "note": ("no `stimulus` list supplied, so there was nothing to "
                           "minimise; the reproducer is the ORIGINAL failing "
                           "test, not a reduced one")}
    minimal = None
    if items and params.get("repro_cmd") and params.get("fail_regex"):
        oracle = reproducer.make_command_oracle(
            params["repro_cmd"], params["fail_regex"], cwd=params.get("cwd"),
            timeout=int(params.get("timeout_s", 600) or 600))
        minimal, red_status = reproducer.ddmin(
            items, oracle, max_steps=int(params.get("max_steps", 200) or 200))
        red_status["attempted"] = True
        if minimal is not None and not red_status.get("hit_step_cap"):
            red_status["failure_reproduced"] = oracle(minimal)
            red_status["one_minimal"] = all(
                not oracle(minimal[:i] + minimal[i + 1:])
                for i in range(len(minimal)))
    elif items:
        red_status = {"attempted": False,
                      "note": ("`stimulus` was supplied but `repro_cmd` and "
                               "`fail_regex` were not, so the failure cannot be "
                               "re-tested on a candidate subset. Reduction "
                               "REQUIRES an executable oracle -- guessing which \n"
                               "transactions matter would produce a 'minimal' "
                               "case that does not reproduce the bug")}

    # Re-execute the candidate that was actually reduced, never a command
    # containing a literal {input} or an unrelated caller-side default.
    det_cmd = params.get("repro_cmd")
    candidate = minimal if minimal is not None else items
    if isinstance(det_cmd, str) and "{input}" in det_cmd:
        if candidate is None:
            det_cmd = None
        else:
            import shlex
            candidate_path = os.path.join(_WORK_DIR, "determinism_stimulus.json")
            with open(candidate_path, "w", encoding="utf-8") as stream:
                json.dump(candidate, stream)
            det_cmd = det_cmd.replace("{input}", shlex.quote(candidate_path))
    det = reproducer.check_determinism(
        det_cmd, runs=int(params.get("determinism_runs", 3) or 3),
        cwd=params.get("cwd"), timeout=int(params.get("timeout_s", 600) or 600),
        fail_regex=params.get("fail_regex"))
    det["stimulus_basis"] = "reduced_candidate" if minimal is not None else "original_stimulus"
    det["stimulus"] = candidate

    reduced_ok = (red_status.get("reduced") is True
                  and red_status.get("failure_reproduced") is True
                  and red_status.get("one_minimal") is True)
    # The gate is honest about which of the two claims is being made: a run that
    # neither reduced nor observed determinism has produced no reproducer
    # evidence at all, and must not read as a completed reduction.
    if not det.get("assessable") and not red_status.get("attempted"):
        verdict, vnote = "not_assessable", (
            "no reproducer command and no reducible stimulus were supplied, so "
            "neither minimality nor determinism was established; the 'reproducer' "
            "here is just the original failure")
    elif det.get("assessable") and det.get("deterministic") is False:
        verdict, vnote = "fail", (
            "the reproducer is NOT deterministic (%d distinct outcomes in %d "
            "runs); debugging it as if it reproduces on demand will mislead"
            % (det.get("distinct_outcomes", 0), det.get("runs", 0)))
    elif det.get("failure_reproduced") is False:
        verdict, vnote = "fail", "the supplied failure signature did not reproduce"
    elif (det.get("assessable") is True and det.get("deterministic") is True
          and det.get("failure_reproduced") is True and reduced_ok):
        verdict, vnote = "pass", (
            "failure reproduced in %d agreeing executions; executed deletion "
            "checks confirmed a 1-minimal failing stimulus of %d item(s)"
            % (det["runs"], len(minimal)))
    else:
        verdict, vnote = "not_assessable", (
            "full reproducer contract not established: determinism=%s, reduced=%s"
            % (det.get("deterministic"), reduced_ok))

    return _cde(
        objective="reduce to minimal reproducer", status="completed",
        results={
            "reproducer_seed": {
                "value": f.get("seed"), "unit": "seed", "class": "descriptive",
                "basis": "supplied_by_caller",
                "note": ("Recorded for re-running. A seed does NOT by itself "
                         "make a reproducer deterministic -- see "
                         "determinism_runs_agreed.")},
            "determinism_runs_agreed": {
                "value": (None if not det.get("assessable")
                          else det.get("runs") if det.get("deterministic")
                          else 0),
                "unit": "count", "class": "gating", "closes_at": "> 1",
                "basis": det.get("basis", "not_executed"),
                "note": ("Number of agreeing re-runs, OBSERVED by executing the "
                         "reproducer. NULL means it was never executed, which is "
                         "not the same as 1 and must never be read as "
                         "deterministic. Agreement is bounded evidence: N runs "
                         "cannot exclude a rarer flake, though ONE disagreement "
                         "does prove non-determinism.")},
            "stimulus_reduction": {
                "value": (red_status.get("to") if red_status.get("attempted")
                          else None),
                "unit": "count", "class": "diagnostic",
                "basis": red_status.get("basis", "not_attempted"),
                "note": ("Size of the 1-minimal failing stimulus found by ddmin "
                         "with an EXECUTED oracle. NULL means no reduction was "
                         "attempted.")}},
        signoff={
            "minimal_reproducer": {
                "test": f.get("test"), "seed": f.get("seed"),
                "is_minimized": reduced_ok,
                "minimal_stimulus": minimal,
                "reduction": red_status,
                "determinism": det},
            "waveform_analysis": wave_status,
            "waveform_findings": wave,
            "ranked_hypotheses": _rank(f.get("message", ""), f.get("log"), wave)},
        assumptions=[
            "determinism is established ONLY by re-executing the reproducer and "
            "comparing normalized outcomes; it is never inferred from a seed",
            "reduction is real delta debugging (ddmin) against an executed "
            "oracle; with no oracle no reduction is claimed"],
        validation={"verdict": verdict, "note": vnote})


def dispatch(params):
    s = params.get("scenario")
    if s == "bucket_failures":
        return _bucket(params)
    if s in ("root_cause", "reduce"):
        return _reduce(params)
    return _cde(objective="debug", status="failed",
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
