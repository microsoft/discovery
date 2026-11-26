#!/usr/bin/env python3
"""code_coverage_utils.py -- structural code-coverage logic for the
chip-code-coverage tool.

Scenarios:
  measure_coverage -- Verilate the RTL with --coverage, build+run, parse the
                      coverage annotation for per-type coverage and uncovered items.
  merge_coverage   -- union of supplied coverage databases (Verilator/JSON).
  exclude          -- apply/justify unreachable-item exclusions and re-report.

Node-agnostic. Reports against a supplied goal when present, else without an
invented threshold. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

import rtl_frontend

TOOL = "code-coverage"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"
_VERILATOR_COVERAGE_FLAGS = {
    "line": "--coverage-line",
    "toggle": "--coverage-toggle",
    "expression": "--coverage-expr",
    "user": "--coverage-user",
}
_METRIC_ALIASES = {"expr": "expression", "cond": "condition", "mcdc": "condition"}


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


def _resolve_verilator_metrics(requested):
    """Return explicit requested/supported/unsupported metric sets."""
    raw = requested if isinstance(requested, (list, tuple)) else [requested]
    normalized = []
    for metric in raw:
        name = _METRIC_ALIASES.get(str(metric).strip().lower(),
                                   str(metric).strip().lower())
        if name and name not in normalized:
            normalized.append(name)
    if "all" in normalized:
        normalized = list(_VERILATOR_COVERAGE_FLAGS) + [
            "branch", "condition", "fsm"
        ]
    supported = [name for name in normalized if name in _VERILATOR_COVERAGE_FLAGS]
    unsupported = [name for name in normalized if name not in _VERILATOR_COVERAGE_FLAGS]
    return {
        "requested_metrics": normalized,
        "supported_metrics": supported,
        "unsupported_metrics": unsupported,
    }


def _stamp_metric_capabilities(envelope, capabilities):
    """Add the resolved Verilator metric contract to every measurement outcome."""
    for field in ("qor_metrics", "signoff_evidence"):
        block = envelope.setdefault(field, {})
        if isinstance(block, dict):
            for key, value in capabilities.items():
                block.setdefault(key, value)
    return envelope


def _reconcile_measured_capabilities(capabilities, per_type):
    """Promote requested metrics only when the coverage database measured them.

    Verilator has no distinct branch instrumentation flag, but some versions emit
    ``v_branch`` points while line coverage is enabled. Static flag discovery must
    therefore remain conservative before a run, while the completed envelope must
    treat a real non-empty point population as authoritative capability evidence.
    """
    reconciled = {
        key: list(value) if isinstance(value, list) else value
        for key, value in capabilities.items()
    }
    supported = reconciled["supported_metrics"]
    unsupported = reconciled["unsupported_metrics"]
    for metric in reconciled["requested_metrics"]:
        point_type = "expr" if metric == "expression" else metric
        measured = per_type.get(point_type)
        if not isinstance(measured, dict) or not measured.get("total"):
            continue
        if metric not in supported:
            supported.append(metric)
        if metric in unsupported:
            unsupported.remove(metric)
    return reconciled


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


def _verilator_version():
    try:
        out = subprocess.run(["verilator", "--version"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _verilator_mm():
    """(major, minor) tuple of the installed Verilator, or None if unknown.

    Used to gate features that need a newer Verilator -- e.g. the cocotb 2.x
    runner requires Verilator >= 5.036 for Verilog co-simulation.
    """
    try:
        out = subprocess.run(["verilator", "--version"], capture_output=True,
                             text=True, timeout=30)
        m = re.search(r"Verilator\s+(\d+)\.(\d+)", out.stdout + out.stderr)
        if m:
            return (int(m.group(1)), int(m.group(2)))
    except Exception:
        pass
    return None


def _parse_verilator_coverage(dat_path):
    """Parse a Verilator ``coverage.dat`` into per-type {hit,total,percent}.

    Each data line is ``C '<keys>' <count>`` where ``<keys>`` is a list of
    ``\\x01``-delimited ``key\\x02value`` pairs. The point TYPE is the ``page``
    value's prefix (``v_line`` / ``v_branch`` / ``v_toggle`` / ``v_user`` /
    ``v_fsm``); a point is HIT iff its count > 0. This reads REAL executed hit
    counts -- it is only meaningful after the instrumented model has actually
    been built AND run (the bug this fixes: the old path never ran the model).
    """
    per = {}
    try:
        with open(dat_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.startswith("C "):
                    continue
                m = re.match(r"^C\s+'(.*)'\s+(\d+)\s*$", line)
                if not m:
                    continue
                keys, cnt = m.group(1), int(m.group(2))
                page = None
                for kv in keys.split("\x01"):
                    if "\x02" in kv:
                        k, v = kv.split("\x02", 1)
                        if k == "page":
                            page = v
                            break
                ctype = (page[2:].split("/", 1)[0]
                         if page and page.startswith("v_") else "line")
                slot = per.setdefault(ctype, [0, 0])
                slot[1] += 1
                if cnt > 0:
                    slot[0] += 1
    except FileNotFoundError:
        return {}
    return {t: {"hit": h, "total": n,
                "percent": round(100.0 * h / n, 2) if n else None}
            for t, (h, n) in per.items()}


# Default A-policy ruling that authorizes excluding test-mode-only coverage points
# from a MISSION-mode functional-coverage gate. Overridable per-run via the
# `test_mode_ruling_id` param. The ruling itself lives in the campaign policy
# ledger (catalog/policy/default-waiver-authorizations.json seeds it); the tool
# only CITES it -- it never self-authorizes.
_SCANMODE_RULING = "APOLICY-COVERAGE-SCANMODE-001"


def _parse_verilator_points(dat_path):
    """Parse a Verilator ``coverage.dat`` into a list of per-point records.

    Each record: ``{type, hit(bool), count, file, line, name, comment, hier, raw}``.
    This is the per-point detail that ``_parse_verilator_coverage`` aggregates away;
    MODE-AWARE exclusion (mission vs test) needs each point's IDENTITY (which signal
    / source line it belongs to), not just the per-type totals, so a test-mode-only
    control point (scan_en/scan_in/scan_out, the scan mux) can be told apart from a
    genuine mission-mode gap.
    """
    points = []
    try:
        with open(dat_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.startswith("C "):
                    continue
                m = re.match(r"^C\s+'(.*)'\s+(\d+)\s*$", line)
                if not m:
                    continue
                keys, cnt = m.group(1), int(m.group(2))
                kv = {}
                for pair in keys.split("\x01"):
                    if "\x02" in pair:
                        k, v = pair.split("\x02", 1)
                        kv[k] = v
                page = kv.get("page", "")
                ctype = (page[2:].split("/", 1)[0]
                         if page.startswith("v_") else "line")
                points.append({
                    "type": ctype,
                    "hit": cnt > 0,
                    "count": cnt,
                    "file": kv.get("f") or kv.get("filename") or "",
                    "line": kv.get("l") or kv.get("lineno") or "",
                    "name": kv.get("n") or "",
                    "comment": kv.get("o") or kv.get("comment") or "",
                    "hier": kv.get("h") or kv.get("hier") or "",
                    "raw": " ".join(str(v) for v in kv.values()),
                })
    except FileNotFoundError:
        return []
    return points


def _matches_test_signal(point, sig):
    """True if a coverage point belongs to test-mode signal/locator ``sig``.

    ``sig`` may be a bare signal name (matched as a WHOLE word against the point's
    name/comment/hier/raw key text so ``scan_en`` does not match ``scan_enable``)
    OR a ``file:line`` locator (matched against the point's file basename + line).
    """
    s = str(sig).strip()
    if not s:
        return False
    if ":" in s and s.rsplit(":", 1)[1].isdigit():
        f, ln = s.rsplit(":", 1)
        pf = os.path.basename(str(point.get("file", "")))
        want = os.path.basename(f)
        return (want == "" or pf == want or pf.endswith(want)) \
            and str(point.get("line", "")) == ln
    hay = " ".join([str(point.get("name", "")), str(point.get("comment", "")),
                    str(point.get("hier", "")), str(point.get("raw", ""))])
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(s) + r"(?![A-Za-z0-9_])",
                     hay) is not None


def _partition_mission_mode(points, test_mode_signals):
    """Partition coverage points for a MISSION-mode run.

    Returns ``(per_type, reachable_unhit, mission_unreachable)``:
      * ``per_type``  -- ``{type: {hit,total,percent}}`` over MISSION-REACHABLE
        points only (test-mode-only points removed from the denominator).
      * ``reachable_unhit`` -- unhit points that are NOT test-mode-only: real gaps.
      * ``mission_unreachable`` -- unhit points on a declared test-mode signal;
        excluded from the mission gate (their exercise is owned by the DFT/scan
        stages, not mission-mode functional coverage).

    Only UNHIT points are ever excluded: a test-mode point the mission regression
    happens to hit still counts as covered -- a point is NEVER dropped to inflate a
    percentage. With an empty ``test_mode_signals`` this is identical to the legacy
    aggregate (no exclusion), so the default path is unchanged.
    """
    sigs = [s for s in (test_mode_signals or []) if str(s).strip()]
    per = {}
    reachable_unhit = []
    mission_unreachable = []
    for p in points:
        slot = per.setdefault(p["type"], [0, 0])
        if (not p["hit"]) and sigs and any(_matches_test_signal(p, s) for s in sigs):
            mission_unreachable.append(p)
            continue  # removed from BOTH numerator and denominator
        slot[1] += 1
        if p["hit"]:
            slot[0] += 1
        else:
            reachable_unhit.append(p)
    per_type = {t: {"hit": h, "total": n,
                    "percent": round(100.0 * h / n, 2) if n else None}
                for t, (h, n) in per.items()}
    return per_type, reachable_unhit, mission_unreachable


def _pt_brief(p):
    return {"type": p.get("type"), "file": p.get("file"), "line": p.get("line"),
            "name": p.get("name"), "hits": p.get("count", 0)}


def _reachability_proof(points, reachable_unhit, mission_unreachable, mode, sigs,
                        ruling_id):
    """Build the machine-checked reachability proof the coverage gate consumes.

    Test-mode-only points excluded in mission mode are recorded under
    ``structurally_unreachable`` (each citing ``ruling_id`` + a mission-mode basis),
    exactly the field the A-policy authorization checks; the mission-real gaps stay
    in ``reachable_unhit``. This moves the proof from agent-authored to
    TOOL-EMITTED so the classification is mechanical and auditable.
    """
    types = sorted({p["type"] for p in points})
    totals = {}
    for t in types:
        tp = [p for p in points if p["type"] == t]
        hit = sum(1 for p in tp if p["hit"])
        totals[t] = {"points": len(tp), "hit": hit, "unhit": len(tp) - hit}
    ru_by_type = {}
    for p in reachable_unhit:
        ru_by_type[p["type"]] = ru_by_type.get(p["type"], 0) + 1
    basis = ("mission-mode functional coverage: DFT/test-mode-only points (scan "
             "enable/in/out and the scan mux) are unreachable with scan_en inactive "
             "and are EXCLUDED from the mission gate. Their exercise is owned by "
             "scan-chain-integrity (flush/shift-pattern sim) and GLS mode=test, NOT "
             "mission-mode code coverage. Only UNHIT test-mode points are excluded.")
    return {
        "schema_version": "1.0",
        "tool": "reachability-proof",
        "policy": "A (reachable-coverage closure)",
        "coverage_mode": ("test" if str(mode).lower() == "test" else "mission"),
        "test_mode_signals": list(sigs),
        "basis": basis,
        "totals": totals,
        "reachable_unhit_by_type": ru_by_type,
        "reachable_unhit": [_pt_brief(p) for p in reachable_unhit],
        "structurally_unreachable": [
            {**_pt_brief(p),
             "basis": "test_mode_only_unreachable_in_mission_mode",
             "ruling_id": ruling_id}
            for p in mission_unreachable
        ],
        "summary": {
            "reachable_unhit_total": len(reachable_unhit),
            "structural_total": len(mission_unreachable),
            "reachable_unhit_zero": len(reachable_unhit) == 0,
            "structural_all_authorized": bool(ruling_id) or not mission_unreachable,
        },
    }


def _find_coverage_dat(*roots):
    """Return the path of the first non-empty coverage.dat under any of *roots*."""
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for _r, _d, _fn in os.walk(root):
            for f in _fn:
                if f == "coverage.dat":
                    p = os.path.join(_r, f)
                    try:
                        if os.path.getsize(p) > 0:
                            return p
                    except OSError:
                        pass
    return None


def _cocotb_version():
    try:
        out = subprocess.run(
            ["python3", "-c", "import cocotb; print(cocotb.__version__)"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _cde(objective, status, results=None, signoff=None, qor=None, assumptions=None,
         validation=None, provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [
            {"name": "Verilator", "version": _verilator_version()},
            {"name": "cocotb", "version": _cocotb_version()},
        ],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "shared_artifact",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {},
        "margin": {"method": "coverage_sampling"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _stage_rtl(params):
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "dut.v")
        open(p, "w").write(params["rtl"])
        files.append(p)
    for rf in params.get("rtl_files", []):
        if os.path.exists(rf):
            files.append(rf)
    if not files:
        raise ValueError("no RTL provided: supply 'rtl' or 'rtl_files'")
    return files


def _goal_compliance(pct, goal):
    if goal is None:
        return {"verdict": "review", "note": "no goal supplied; reported without compliance verdict"}
    # A NULL MEASUREMENT IS NOT A FAILED GOAL, AND NOT A MET ONE.
    # `pct` is None whenever coverage could not be established -- no coverage
    # database merged, or neither line nor branch percentage parsed. This
    # function previously handled `goal is None` but not `pct is None`, so it
    # raised TypeError on `None >= goal`. That is fail-closed by accident rather
    # than by design: the caller gets a stack trace instead of an envelope, and
    # any outer handler that swallows the exception would turn "we could not
    # measure" into something else entirely.
    #
    # Note the asymmetry that produced this: the sibling verdict at the merge
    # site correctly guards `driving is not None`, while the adjacent
    # goal_compliance call on the very next line does not.
    if pct is None:
        return {"verdict": "not_assessable", "goal_percent": goal,
                "measured_percent": None,
                "note": ("coverage could not be measured (no parsable coverage "
                         "data), so compliance with the %s%% goal is UNKNOWN -- "
                         "this is not a pass and not a fail" % goal)}
    return {"verdict": "pass" if pct >= goal else "fail",
            "goal_percent": goal, "measured_percent": pct}


def _crosscheck_interpretation(interp, measured, key="reachable_unhit"):
    """Cross-check the model's count against the measured one via the shared module.

    Delegates to catalog/tools/metric_classes.py (vendored into this build
    context by catalog/migrate_cde_progress.py). Two hand-maintained copies of
    the routine whose whole job is to CATCH disagreement is exactly the drift it
    exists to detect, so it lives in one place.

    If the shared module is unavailable the absence is RECORDED rather than
    swallowed -- a missing cross-check must never be indistinguishable from a
    passed one.
    """
    try:
        import metric_classes
    except Exception as exc:
        return {"checked": False,
                "reason": "metric_classes module unavailable (%s); the "
                          "cross-check did NOT run" % exc}
    return metric_classes.crosscheck_interpretation(interp, measured, key)


def _ghdl_has_gcc_backend():
    """True iff the installed GHDL is the GCC back-end (the only backend that can
    emit gcov data: mcode/llvm/JIT cannot). Probed from `ghdl --version`."""
    try:
        out = subprocess.run(["ghdl", "--version"], capture_output=True,
                             text=True, timeout=30)
        return "gcc" in (out.stdout + out.stderr).lower()
    except Exception:
        return False


def _ghdl_gcc_major():
    """The GCC major version GHDL's gcc back-end was built with (e.g. 10 from
    'GNAT Version: 10.3.1'). gcov instrumentation, the linked libgcov runtime, and
    the gcov parser MUST all match this major or .gcda emission fails with a
    'Version mismatch' error. Defaults to '10' (the ghdl-gcc GNAT on jammy)."""
    try:
        out = subprocess.run(["ghdl", "--version"], capture_output=True,
                             text=True, timeout=30)
        m = re.search(r"GNAT Version:\s*(\d+)", out.stdout + out.stderr)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "10"


def _gcov_link_flags(major):
    """Linker flags that pull the libgcov MATCHING the ghdl-gcc backend major, so
    the .gcda format matches the parser. GHDL drives `ld` directly, so we prepend
    the gcc-<major> lib dir before -lgcov (system gcc-11's libgcov would otherwise
    win and cause a version mismatch)."""
    import glob
    for cand in glob.glob(f"/usr/lib/gcc/*/{major}*/libgcov.a") + \
            glob.glob(f"/usr/lib/gcc/*/{major}/libgcov.a"):
        return [f"-Wl,-L{os.path.dirname(cand)}", "-Wl,-lgcov"]
    # Fall back to a bare -lgcov (still better than no link); a mismatch will
    # surface as an explicit .gcda version error the caller reports honestly.
    return ["-Wl,-lgcov"]


def _gcov_executable(major):
    """The gcov binary matching the backend major (gcov-<major> if present, else
    plain gcov). gcovr is told to use it via --gcov-executable."""
    exe = shutil.which(f"gcov-{major}")
    return f"gcov-{major}" if exe else "gcov"


def _cocotb_vpi_arg():
    """Resolve the cocotb VPI shared-library path for GHDL.

    Returns the ``--vpi=<path>`` argument string.  Raises ``RuntimeError`` if
    ``cocotb-config`` is unavailable or fails.
    """
    try:
        p = subprocess.run(
            ["cocotb-config", "--lib-name-path", "vpi", "ghdl"],
            capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            raise RuntimeError(
                f"cocotb-config --lib-name-path vpi ghdl failed "
                f"(rc={p.returncode}): {p.stderr.strip()}")
        vpi_path = p.stdout.strip()
        if not vpi_path:
            raise RuntimeError("cocotb-config returned empty VPI path")
        return f"--vpi={vpi_path}"
    except FileNotFoundError:
        raise RuntimeError(
            "cocotb-config not found; install cocotb (pip install cocotb) "
            "to use cocotb-driven VHDL coverage")


def _build_cocotb_env(cocotb_toplevel, cocotb_module, base_env=None):
    """Build the subprocess environment dict for a cocotb-driven GHDL run.

    Returns a new dict merging *base_env* (or ``os.environ``) with the six
    required cocotb-2.x environment variables.

    Raises ``RuntimeError`` if ``LIBPYTHON_LOC`` cannot be resolved — cocotb 2.x
    VPI co-simulation with GHDL requires the shared libpython path at load time;
    without it the VPI plugin fails with an opaque dlopen/import error.
    """
    import sys
    import sysconfig
    env = dict(base_env if base_env is not None else os.environ)
    env["COCOTB_TOPLEVEL"] = cocotb_toplevel
    env["COCOTB_TEST_MODULES"] = cocotb_module   # comma-separated if multiple
    env["TOPLEVEL_LANG"] = "vhdl"
    env["COCOTB_TRUST_INERTIAL_WRITES"] = "1"
    # LIBPYTHON_LOC -- required for cocotb 2.x GHDL VPI co-sim.
    libpython_loc = None
    try:
        configdir = sysconfig.get_config_var("LIBDIR") or ""
        ldlib = sysconfig.get_config_var("LDLIBRARY") or ""
        if configdir and ldlib:
            libpython_loc = os.path.join(configdir, ldlib)
    except Exception:
        pass
    if not libpython_loc:
        try:
            pc = subprocess.run(
                ["python3-config", "--configdir"],
                capture_output=True, text=True, timeout=10)
            if pc.returncode == 0 and pc.stdout.strip():
                libpython_loc = pc.stdout.strip()
        except Exception:
            pass
    if not libpython_loc:
        raise RuntimeError(
            "Cannot resolve LIBPYTHON_LOC (the shared libpython path). "
            "cocotb 2.x VPI co-simulation with GHDL requires this at load "
            "time. Ensure Python was built with --enable-shared, or set "
            "LIBPYTHON_LOC in the environment before invoking the tool. "
            "Tried: sysconfig.get_config_var('LIBDIR'/'LDLIBRARY') and "
            "python3-config --configdir; both returned empty/None.")
    env["LIBPYTHON_LOC"] = libpython_loc
    env["PYGPI_PYTHON_BIN"] = sys.executable
    return env


def _measure_vhdl(params, top, files):
    """Real line/branch coverage for a PURE-VHDL design via the GHDL GCC back-end.

    ghdl-gcc routes VHDL through gcc, so gcov instrumentation
    (-fprofile-arcs/-ftest-coverage, passed to the C compiler with GHDL's -Wc,)
    emits .gcno at analyze/elaborate and .gcda when the elaborated design runs.
    ``gcovr`` then aggregates them into line + branch %. This measures the
    AUTHORITATIVE VHDL -- no Verilog conversion, no VCD-toggle proxy.

    A run needs a self-contained VHDL testbench top to produce .gcda hit counts;
    supply it as ``tb_top`` (its sources included in ``rtl``/``rtl_files``).
    Without a ``tb_top`` we still analyze+elaborate the DUT with instrumentation
    and report instrumentation-complete (verdict=review), symmetric with the
    Verilog path.

    **cocotb path** (new): when *both* ``cocotb_module`` and ``cocotb_toplevel``
    are supplied, the simulation is driven via cocotb over VPI instead of a
    self-contained VHDL testbench.  The gcov instrumentation flags and gcovr
    aggregation are identical; only the ``ghdl -r`` invocation changes (adds
    ``--vpi=<cocotb lib>`` and sets the six cocotb-2.x env vars).
    """
    if not _ghdl_has_gcc_backend():
        # Backend genuinely absent -> honest flag (never fake a number). This is
        # the ONLY path that still flags a pure-VHDL design, and it means the
        # image was built without ghdl-gcc (the Containerfile now installs it).
        return _cde(
            objective=f"code coverage of {top}", status="failed",
            inputs_ref={"rtl_files": files},
            error=("VHDL line/branch coverage requires the GHDL GCC back-end "
                   "(ghdl-gcc, gcov-capable); the installed GHDL is not the gcc "
                   "backend. Rebuild the chip-code-coverage image (its Containerfile "
                   "installs ghdl-gcc). " + rtl_frontend.language_note(files)),
            validation={"verdict": "flag", "reason": "ghdl_gcc_backend_absent"})

    std = str(params.get("vhdl_std", params.get("std", "08"))).strip() or "08"
    work = os.path.join(_WORK_DIR, "ghdl_cov")
    os.makedirs(work, exist_ok=True)
    gcov_flags = ["-g", "-Wc,-fprofile-arcs", "-Wc,-ftest-coverage"]
    # GHDL drives `ld` directly (not the gcc driver), so -fprofile-arcs at link does
    # NOT auto-pull the gcov runtime; the elaborate step must link libgcov
    # explicitly or it fails with `undefined reference to __gcov_init`. The libgcov
    # AND the gcov parser must match the ghdl-gcc backend major, or .gcda emission
    # fails with a 'Version mismatch' error.
    _gcc_major = _ghdl_gcc_major()
    link_flags = _gcov_link_flags(_gcc_major)
    _gcov_exe = _gcov_executable(_gcc_major)
    logs = []

    def _run(cmd, cwd=None, env=None):
        _save_run_command(cmd, name="ghdl_cov_cmd.txt")
        p = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or work, env=env)
        logs.append("$ " + " ".join(cmd) + "\n" + p.stdout + p.stderr)
        return p

    tb_top = params.get("tb_top")
    cocotb_module = params.get("cocotb_module")
    cocotb_toplevel = params.get("cocotb_toplevel")
    _cocotb = bool(cocotb_module and cocotb_toplevel)
    run_top = tb_top or (cocotb_toplevel if _cocotb else None) or top
    goal = params.get("goal_percent")
    t0 = time.time()

    # 1) analyze all VHDL units with gcov instrumentation
    a = _run(["ghdl", "-a", f"--std={std}", f"--workdir={work}"] + gcov_flags + files)
    if a.returncode != 0:
        open(os.path.join(_OUTPUT_DIR, "ghdl_cov.log"), "w").write("\n".join(logs))
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error="ghdl -a (analyze) failed; see ghdl_cov.log:\n" + a.stderr[-1500:],
                    validation={"verdict": "fail"})
    # 2) elaborate the run top with gcov instrumentation
    e = _run(["ghdl", "-e", f"--std={std}", f"--workdir={work}",
              "-o", os.path.join(work, run_top)] + gcov_flags + link_flags + [run_top])
    if e.returncode != 0:
        open(os.path.join(_OUTPUT_DIR, "ghdl_cov.log"), "w").write("\n".join(logs))
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error="ghdl -e (elaborate) failed; see ghdl_cov.log:\n" + e.stderr[-1500:],
                    validation={"verdict": "fail"})

    if not tb_top and not _cocotb:
        # Instrumentation-complete, no harness to generate hit counts -> review,
        # symmetric with the Verilog instrumentation-only path.
        elapsed = time.time() - t0
        open(os.path.join(_OUTPUT_DIR, "ghdl_cov.log"), "w").write("\n".join(logs))
        return _cde(
            objective=f"code coverage instrumentation of {top}", status="completed",
            results={t: {"value": None, "unit": "percent"}
                     for t in params.get("types", ["line", "branch"])},
            qor={"coverage_types": params.get("types", ["line", "branch"]),
                 "instrumented": True, "backend": "ghdl-gcc/gcov"},
            signoff={"note": "GHDL gcc-backend gcov instrumentation complete; supply "
                             "`tb_top` (a self-contained VHDL testbench) to run the "
                             "design and measure line/branch hit rates",
                     "goal_compliance": _goal_compliance(0.0, goal) if goal else None},
            inputs_ref={"rtl_files": files},
            assumptions=["hit-rate requires running a VHDL testbench top (tb_top); "
                         "instrumentation verified on the gcc backend"],
            provenance={"ghdl_backend": "gcc", "runtime_s": round(elapsed, 3),
                        "log": "ghdl_cov.log"},
            validation={"verdict": "review"})

    # 3) run the testbench (or cocotb-driven simulation) to emit .gcda hit data
    _run_args = list(params.get("run_args") or [])
    if _cocotb:
        try:
            _vpi = _cocotb_vpi_arg()
            _cocotb_env = _build_cocotb_env(cocotb_toplevel, cocotb_module)
        except RuntimeError as _ce:
            open(os.path.join(_OUTPUT_DIR, "ghdl_cov.log"), "w").write("\n".join(logs))
            return _cde(objective=f"code coverage of {top}", status="failed",
                        inputs_ref={"rtl_files": files},
                        error=f"cocotb setup failed: {_ce}",
                        validation={"verdict": "fail"})
        r = _run(["ghdl", "-r", f"--std={std}", f"--workdir={work}",
                  run_top, _vpi] + _run_args, cwd=work, env=_cocotb_env)
    else:
        r = _run(["ghdl", "-r", f"--std={std}", f"--workdir={work}", tb_top]
                 + _run_args, cwd=work)
    # A TB that ends via `assert false severity failure` (the GHDL stop idiom)
    # returns non-zero but still flushes .gcda; only treat a MISSING .gcda as fatal.
    gcda = []
    for _root, _d, _fn in os.walk(work):
        gcda += [f for f in _fn if f.endswith(".gcda")]
    _joined_logs = "\n".join(logs)
    if "Version mismatch" in _joined_logs and not any(
            os.path.getsize(os.path.join(_rt, f)) > 8
            for _rt, _d, _fn in os.walk(work) for f in _fn if f.endswith(".gcda")):
        # Toolchain SKEW, not a design fault: the apt ghdl-gcc backend was built
        # against a gcc minor (e.g. GNAT 10.3.1) that no longer matches the
        # archive's gcov/libgcov (10.5/11.4 on jammy), so the .gcda version is
        # unreadable. Flag honestly for human review with the remediation paths --
        # never a fabricated number and never a VCD-toggle proxy self-waiver.
        open(os.path.join(_OUTPUT_DIR, "ghdl_cov.log"), "w").write(_joined_logs)
        return _cde(
            objective=f"code coverage of {top}", status="failed",
            inputs_ref={"rtl_files": files},
            error=("GHDL gcc-backend gcov VERSION SKEW: ghdl instruments with its "
                   "baked-in gcc minor but the image's gcov/libgcov differ, so the "
                   ".gcda is unreadable (see ghdl_cov.log 'Version mismatch'). This "
                   "is a toolchain packaging skew, NOT a design or coverage fault. "
                   "Remediation (either): (a) build the image on a base where "
                   "ghdl-gcc and gcov share the same gcc minor (self-consistent "
                   "gcov), or (b) lower VHDL->Verilog via the ghdl-yosys-plugin and "
                   "measure Verilator --coverage on the lowered RTL. Do NOT accept a "
                   "VCD-toggle proxy as line/branch closure."),
            validation={"verdict": "flag", "reason": "ghdl_gcov_version_skew"})
    if not gcda:
        open(os.path.join(_OUTPUT_DIR, "ghdl_cov.log"), "w").write("\n".join(logs))
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error="ghdl -r produced no .gcda coverage data; see ghdl_cov.log:\n"
                          + r.stderr[-1500:],
                    validation={"verdict": "fail"})

    # 4) aggregate with gcovr into line + branch %
    line_pct = branch_pct = None
    # GHDL emits an internal elaboration wrapper `e~<top>` that has NO source file,
    # so gcovr errors on it ("Cannot open source file e~<top>") -- ignore that class
    # of error, and FILTER to the real DUT sources so only authentic VHDL lines are
    # scored (not the wrapper or any stdlib).
    import re as _re
    _src_filter = "|".join(_re.escape(os.path.basename(f)) for f in files)
    _gcovr_common = ["gcovr", "--gcov-executable", _gcov_exe,
                     "--gcov-ignore-errors=no_working_dir_found"]
    if _src_filter:
        _gcovr_common += ["--filter", f".*({_src_filter})"]
    gcovr = subprocess.run(_gcovr_common + ["--json-summary", "-r", ".", work],
                           capture_output=True, text=True, cwd=work)
    logs.append("$ " + " ".join(_gcovr_common) + " --json-summary\n" + gcovr.stdout + gcovr.stderr)
    try:
        gj = json.loads(gcovr.stdout or "{}")
        line_pct = gj.get("line_percent")
        branch_pct = gj.get("branch_percent")
    except Exception:
        pass
    # Human-readable lcov-style report alongside the machine summary.
    txt = subprocess.run(_gcovr_common + ["-r", ".", work],
                         capture_output=True, text=True, cwd=work)
    open(os.path.join(_OUTPUT_DIR, "coverage_gcovr.txt"), "w").write(txt.stdout + txt.stderr)
    open(os.path.join(_OUTPUT_DIR, "ghdl_cov.log"), "w").write("\n".join(logs))
    elapsed = time.time() - t0

    results = {}
    if line_pct is not None:
        results["line"] = {"value": round(float(line_pct), 2), "unit": "percent"}
    if branch_pct is not None:
        results["branch"] = {"value": round(float(branch_pct), 2), "unit": "percent"}
    # Gate the reported metric against the goal when one is supplied; the tightest
    # (worst) of line/branch drives compliance so neither can be laundered.
    driving = None
    for _v in (line_pct, branch_pct):
        if _v is not None:
            driving = _v if driving is None else min(driving, _v)
    verdict = "review"
    if goal is not None and driving is not None:
        verdict = "pass" if float(driving) >= float(goal) else "fail"
    return _cde(
        objective=f"code coverage of {top} (GHDL gcc-backend / gcov)",
        status="completed", results=results,
        qor={"line_percent": line_pct, "branch_percent": branch_pct,
             "backend": "ghdl-gcc/gcov", "measured_on": "authoritative VHDL"},
        signoff={"gcda_files": len(gcda), "report": "coverage_gcovr.txt",
                 "tb_top": tb_top,
                 "cocotb_module": cocotb_module if _cocotb else None,
                 "cocotb_toplevel": cocotb_toplevel if _cocotb else None,
                 "goal_compliance": _goal_compliance(driving, goal) if goal else None},
        inputs_ref={"rtl_files": files},
        assumptions=["line/branch measured via gcov on the gcc-backend-compiled VHDL "
                     "(no Verilog conversion, no VCD-toggle proxy)"],
        provenance={"ghdl_backend": "gcc", "runtime_s": round(elapsed, 3),
                    "log": "ghdl_cov.log"},
        validation={"verdict": verdict,
                    "note": "real VHDL line/branch coverage via GHDL gcc-backend gcov"})


def _measure(params):
    top = params["top"]
    files = _stage_rtl(params)
    # Verilator cannot instrument VHDL. For a PURE-VHDL design we now measure real
    # line/branch coverage on the authoritative VHDL via the GHDL GCC back-end
    # (gcov) instead of the old dishonest FLAG dead-end (see _measure_vhdl). Only a
    # MIXED VHDL+Verilog set stays flagged: gcc-backend GHDL cannot compile the
    # Verilog half, and Verilator cannot read the VHDL half, so neither engine can
    # cover a mixed set on its own.
    lang = rtl_frontend.detect_language(files)
    if lang == "vhdl":
        return _measure_vhdl(params, top, files)
    if lang == "mixed":
        return _cde(
            objective=f"code coverage of {top}", status="failed",
            inputs_ref={"rtl_files": files},
            error=("Mixed VHDL+Verilog code coverage is unsupported in one engine: "
                   "Verilator cannot read VHDL and the GHDL gcc back-end cannot read "
                   "Verilog. Cover each language's sources separately (Verilator for the "
                   "Verilog partition, ghdl-gcc/gcov for the VHDL partition) and merge. "
                   + rtl_frontend.language_note(files)),
            validation={"verdict": "flag",
                        "reason": "mixed_language_coverage_unsupported",
                        "language": lang})
    capabilities = _resolve_verilator_metrics(
        params.get("types", ["line", "toggle"]))
    types = capabilities["requested_metrics"]
    supported_types = capabilities["supported_metrics"]
    obj = os.path.join(_WORK_DIR, "obj_dir")
    cov_args = [_VERILATOR_COVERAGE_FLAGS[t] for t in supported_types]
    # Verilator exposes no dedicated branch flag, but emits v_branch points under
    # line instrumentation on versions/designs that can measure branch coverage.
    # Enable that measurement opportunity even for a branch-only request; the
    # completed run still stays null/not_assessable if no branch points appear.
    if "branch" in types and "--coverage-line" not in cov_args:
        cov_args.append("--coverage-line")
    if not cov_args:
        return _cde(
            objective=f"code coverage of {top}", status="completed",
            results={t: {"value": None, "unit": "percent"} for t in types},
            qor={**capabilities, "backend": "verilator", "instrumented": False},
            signoff={**capabilities,
                     "note": "none of the requested metrics is supported by Verilator"},
            inputs_ref={"rtl_files": files},
            validation={"verdict": "not_assessable",
                        "reason": "requested_metrics_unsupported"})
    if str(params.get("coverage_underscore", "")).lower() in ("1", "true", "yes"):
        cov_args.append("--coverage-underscore")
    # Preprocessor defines (-D), include search dirs (-I), and top-level parameter
    # overrides (-G) so parameterized / multi-file RTL can be covered without
    # inlining. All optional and backward-compatible.
    extra = []
    for k, v in (params.get("defines") or {}).items():
        extra.append(f"-D{k}={v}" if v not in (None, "") else f"-D{k}")
    for d in (params.get("include_dirs") or []):
        extra.append(f"-I{d}")
    for k, v in (params.get("parameters") or {}).items():
        extra.append(f"-G{k}={v}")
    # Verilator lint-warning passthrough. Code coverage is NOT lint signoff, so a
    # lint warning (e.g. UNOPTFLAT on a legitimate combinational feedback in
    # GHDL-translated RTL) must NOT abort the coverage build. Callers can supply
    # `verilator_flags` (e.g. ["-Wno-UNOPTFLAT","-Wno-WIDTH"]); by default we add
    # `-Wno-fatal` so warnings are reported but non-fatal. IMPORTANT: measure
    # coverage on RTL, not a flattened gate-level netlist (the latter is
    # pathologically expensive to Verilate and semantically wrong for code
    # coverage).
    vflags = list(params.get("verilator_flags") or [])
    if not any(f == "-Wno-fatal" or f.startswith("-Wfatal") for f in vflags):
        vflags.append("-Wno-fatal")
    extra += vflags
    goal = params.get("goal_percent")

    # ---- Driver selection: to produce REAL hit rates the instrumented model must
    # be BUILT and RUN. Two drivers are supported (symmetric with the VHDL path):
    #   * tb_top       -- a self-contained Verilog/SV testbench that drives the DUT
    #                     and $finishes; built runnable via `verilator --binary`.
    #   * cocotb_module + cocotb_toplevel -- a cocotb Python testbench driven via
    #                     the cocotb runner (needs Verilator >= 5.036).
    # With NO driver we still verilate (to VERIFY instrumentation) and report
    # instrumentation-only (verdict=review) -- never a fabricated hit rate.
    tb_top = params.get("tb_top")
    cocotb_module = params.get("cocotb_module")
    cocotb_toplevel = params.get("cocotb_toplevel")
    _cocotb = bool(cocotb_module and cocotb_toplevel)

    if _cocotb:
        return _stamp_metric_capabilities(
            _measure_verilog_cocotb(
                params, top, files, cov_args, extra, types, goal, obj),
            capabilities)
    if tb_top:
        return _stamp_metric_capabilities(
            _measure_verilog_binary(
                params, top, files, tb_top, cov_args, extra, types, goal, obj),
            capabilities)

    # --- No driver: instrumentation-only. Build the C++ model (NOT runnable) just
    # to verify the RTL verilates with coverage, then honestly report review.
    cmd = ["verilator", "--cc"] + cov_args + ["--top-module", top,
           "--Mdir", obj] + extra + files
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    open(os.path.join(_OUTPUT_DIR, "verilator.log"), "w").write(proc.stdout + "\n" + proc.stderr)
    if proc.returncode != 0:
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error="verilator --coverage failed; see verilator.log:\n" + proc.stderr[-1500:],
                    validation={"verdict": "fail"})
    return _cde(
        objective=f"code coverage instrumentation of {top}",
        status="completed",
        results={t: {"value": None, "unit": "percent"} for t in types},
        qor={"coverage_types": types, **capabilities, "instrumented": True},
        signoff={**capabilities, "coverage_flags": cov_args + extra,
                 "note": "instrumentation verified but NO hit rates measured: supply "
                         "a Verilog testbench via `tb_top` (built with --binary) or a "
                         "cocotb testbench via `cocotb_module`+`cocotb_toplevel` to build, "
                         "run, and measure real line/branch/toggle coverage",
                 "goal_compliance": _goal_compliance(0.0, goal) if goal else None},
        inputs_ref={"rtl_files": files},
        assumptions=["hit-rate requires building AND running the model with a driver "
                     "(tb_top or cocotb); instrumentation-only was verified here"],
        provenance={"verilator": _verilator_version(), "runtime_s": round(elapsed, 3),
                    "log": "verilator.log"},
        validation={"verdict": "review",
                    "note": "instrumentation-only; no testbench/driver supplied"},
    )


def _measure_verilog_binary(params, top, files, tb_top, cov_args, extra, types, goal, obj):
    """Build a RUNNABLE coverage model from a self-contained Verilog/SV testbench
    (`tb_top`), execute it, and parse the real ``coverage.dat`` hit counts. This is
    the fix for the core defect: the old path stopped at ``verilator --cc`` (source
    generation) and never built or ran the model, so no coverage data ever existed.

    NOTE (why not ``--binary``): Verilator's auto-generated main (``--main`` /
    ``--binary``) does NOT emit a coverage dump -- it runs the sim to ``$finish``
    but never calls ``coveragep()->write()`` -- so ``coverage.dat`` is never
    produced. We therefore supply our OWN tiny timing-aware harness that runs the
    self-driving testbench to completion and then writes the coverage database.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(tb_top)):
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error=f"invalid tb_top identifier: {tb_top!r}",
                    validation={"verdict": "fail"})
    run_args = list(params.get("run_args") or [])
    # Generic timing-aware harness: run the self-driving TB (its own clock/initial/
    # $finish) to completion, then dump coverage. Works for any tb_top; needs
    # --timing so `#delay`/event scheduling in the TB is honored.
    harness = os.path.join(_WORK_DIR, "cov_harness.cpp")
    with open(harness, "w") as _h:
        _h.write(
            f'#include "V{tb_top}.h"\n'
            '#include "verilated.h"\n'
            'int main(int argc, char** argv) {\n'
            '    VerilatedContext* contextp = new VerilatedContext;\n'
            '    contextp->commandArgs(argc, argv);\n'
            f'    V{tb_top}* top = new V{tb_top}{{contextp}};\n'
            '    top->eval();\n'
            '    while (!contextp->gotFinish() && top->eventsPending()) {\n'
            '        contextp->time(top->nextTimeSlot());\n'
            '        top->eval();\n'
            '    }\n'
            '    top->final();\n'
            '#if VM_COVERAGE\n'
            '    contextp->coveragep()->write("coverage.dat");\n'
            '#endif\n'
            '    delete top;\n'
            '    delete contextp;\n'
            '    return 0;\n'
            '}\n')
    # --exe --build compiles a runnable binary using our harness (NOT --main, which
    # would inject a coverage-less main and clash with ours); --timing honors TB
    # delays; --coverage defines VM_COVERAGE so the harness dump is compiled in.
    build = ["verilator", "--cc", "--exe", "--build", "--timing"] + cov_args + \
            ["--top-module", tb_top, "--Mdir", obj] + extra + files + [harness]
    t0 = time.time()
    _save_run_command(build)
    proc = subprocess.run(build, capture_output=True, text=True, cwd=_WORK_DIR)
    open(os.path.join(_OUTPUT_DIR, "verilator.log"), "w").write(proc.stdout + "\n" + proc.stderr)
    if proc.returncode != 0:
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error="verilator coverage build failed; see verilator.log:\n"
                          + proc.stderr[-1500:],
                    validation={"verdict": "fail"})
    exe = os.path.join(obj, "V" + tb_top)
    if not os.path.isfile(exe):
        _cand = [os.path.join(obj, n) for n in os.listdir(obj)
                 if os.access(os.path.join(obj, n), os.X_OK)
                 and os.path.isfile(os.path.join(obj, n))]
        exe = _cand[0] if _cand else exe
    if not os.path.isfile(exe):
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error="coverage build produced no executable in " + obj,
                    validation={"verdict": "fail"})
    # Run the simulation; the harness writes coverage.dat to cwd on exit.
    _save_run_command([exe] + run_args, name="run_sim_command.txt")
    runp = subprocess.run([exe] + run_args, capture_output=True, text=True, cwd=_WORK_DIR)
    open(os.path.join(_OUTPUT_DIR, "simulation.log"), "w").write(runp.stdout + "\n" + runp.stderr)
    elapsed = time.time() - t0
    dat = _find_coverage_dat(_WORK_DIR, obj)
    if not dat:
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error=("model built and ran but produced no coverage.dat; ensure the "
                           "testbench $finishes normally so the coverage dump runs. "
                           "sim log tail:\n" + (runp.stdout + runp.stderr)[-1200:]),
                    validation={"verdict": "fail"})
    shutil.copyfile(dat, os.path.join(_OUTPUT_DIR, "coverage.dat"))
    return _finish_verilog_coverage(top, files, dat, types, goal, elapsed,
                                    driver={"tb_top": tb_top}, obj=obj,
                                    mode=params.get("coverage_mode", "mission"),
                                    test_mode_signals=params.get("test_mode_signals"),
                                    ruling_id=params.get("test_mode_ruling_id",
                                                         _SCANMODE_RULING),
                                    interpretation=params.get("interpretation"))


def _measure_verilog_cocotb(params, top, files, cov_args, extra, types, goal, obj):
    """Build+run a coverage model driven by a cocotb Python testbench, then parse
    the real coverage.dat. Requires Verilator >= 5.036 (the cocotb 2.x runner);
    on an older Verilator this fails CLOSED with the exact version reason rather
    than silently degrading to no measurement.
    """
    mm = _verilator_mm()
    if mm is None or mm < (5, 36):
        return _cde(
            objective=f"code coverage of {top}", status="failed",
            inputs_ref={"rtl_files": files},
            error=("cocotb-driven Verilog coverage needs Verilator >= 5.036 (the "
                   f"cocotb {_cocotb_version()} runner); installed: "
                   f"{_verilator_version()}. Rebuild the chip-code-coverage image with "
                   "a newer Verilator, or supply a self-contained Verilog testbench via "
                   "`tb_top` (built with --binary)."),
            validation={"verdict": "flag", "reason": "verilator_too_old_for_cocotb"})
    cocotb_module = params["cocotb_module"]
    cocotb_toplevel = params["cocotb_toplevel"]
    try:
        from cocotb_tools.runner import get_runner  # cocotb 2.x
    except Exception:
        try:
            from cocotb.runner import get_runner   # cocotb 1.x fallback
        except Exception as _e:
            return _cde(objective=f"code coverage of {top}", status="failed",
                        inputs_ref={"rtl_files": files},
                        error=f"cocotb runner unavailable: {_e}",
                        validation={"verdict": "fail"})
    build_dir = os.path.join(_WORK_DIR, "sim_build")
    # cocotb imports the test module by name, so its directory must be on the
    # Python path. Resolve candidate dirs from an explicit `cocotb_test_dir`, else
    # the directories of the supplied RTL files, plus the workdir. Inject into both
    # sys.path (for in-process) and PYTHONPATH (for the runner's child process).
    import sys as _sys
    _test_dirs = []
    _ctd = params.get("cocotb_test_dir")
    if _ctd:
        _test_dirs += ([_ctd] if isinstance(_ctd, str) else list(_ctd))
    _test_dirs += sorted({os.path.dirname(os.path.abspath(f)) for f in files})
    _test_dirs.append(_WORK_DIR)
    for _d in _test_dirs:
        if _d and _d not in _sys.path:
            _sys.path.insert(0, _d)
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [d for d in _test_dirs if d] + [os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)
    t0 = time.time()
    try:
        runner = get_runner("verilator")
        runner.build(verilog_sources=files, hdl_toplevel=cocotb_toplevel,
                     build_args=cov_args + extra, build_dir=build_dir,
                     always=True)
        test_module = (cocotb_module if isinstance(cocotb_module, str)
                       else ",".join(cocotb_module))
        runner.test(hdl_toplevel=cocotb_toplevel, test_module=test_module,
                    test_dir=build_dir, test_args=list(params.get("run_args") or []))
    except Exception as _e:
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error=f"cocotb runner build/test failed: {_e}",
                    validation={"verdict": "fail"})
    elapsed = time.time() - t0
    dat = _find_coverage_dat(build_dir, _WORK_DIR, obj)
    if not dat:
        return _cde(objective=f"code coverage of {top}", status="failed",
                    inputs_ref={"rtl_files": files},
                    error="cocotb run produced no coverage.dat under " + build_dir,
                    validation={"verdict": "fail"})
    shutil.copyfile(dat, os.path.join(_OUTPUT_DIR, "coverage.dat"))
    return _finish_verilog_coverage(
        top, files, dat, types, goal, elapsed,
        driver={"cocotb_module": cocotb_module, "cocotb_toplevel": cocotb_toplevel},
        obj=obj,
        mode=params.get("coverage_mode", "mission"),
        test_mode_signals=params.get("test_mode_signals"),
        ruling_id=params.get("test_mode_ruling_id", _SCANMODE_RULING),
        interpretation=params.get("interpretation"))


def _finish_verilog_coverage(top, files, dat, types, goal, elapsed, driver, obj,
                             mode="mission", test_mode_signals=None,
                             ruling_id=_SCANMODE_RULING, interpretation=None):
    """Shared tail: parse coverage.dat, gate against the goal, emit the CDE.

    The reported metric per requested type is the REAL hit rate. The goal (when
    supplied) is gated on the WORST of the reported types so no dimension can be
    laundered. Condition (MC/DC) coverage is not produced by Verilator in any
    version -- if requested it is surfaced as null with an honest note, never
    fabricated.

    MODE AWARENESS: in a MISSION-mode run (``mode`` != "test") any UNHIT toggle/
    line/branch point that belongs to a declared ``test_mode_signals`` entry
    (scan_en/scan_in/scan_out, the scan mux, ...) is reclassified as
    mission-UNREACHABLE and removed from the gate denominator, because scan_en is
    held inactive in mission mode by design (DR-094) -- those points are exercised
    by the DFT/scan stages (scan-chain integrity + GLS mode=test), NOT by
    mission-mode code coverage. This prevents a test-mode control point from
    failing (or being force-toggled into) the mission gate. In a ``test``-mode run
    NOTHING is excluded (test mode SHOULD hit them). With no ``test_mode_signals``
    the behavior is identical to before.
    """
    points = _parse_verilator_points(dat)
    capabilities = _resolve_verilator_metrics(types)
    sigs = [s for s in (test_mode_signals or []) if str(s).strip()]
    apply_mode = (str(mode).lower() != "test") and bool(sigs)
    per_type, reachable_unhit, mission_unreachable = _partition_mission_mode(
        points, sigs if apply_mode else [])
    capabilities = _reconcile_measured_capabilities(capabilities, per_type)
    # verilator_coverage --annotate for a human-readable annotated report.
    try:
        ann = os.path.join(_OUTPUT_DIR, "annotated")
        subprocess.run(["verilator_coverage", "--annotate", ann, dat],
                       capture_output=True, text=True, cwd=_WORK_DIR, timeout=120)
    except Exception:
        pass
    results = {}
    unsupported = capabilities["unsupported_metrics"]
    folded = [t for t in unsupported if t == "branch"]
    for t in types:
        if t in unsupported:
            results[t] = {
                "value": None, "unit": "percent",
                "covered": None, "total": None,
            }
            continue
        point_type = "expr" if t == "expression" else t
        m = per_type.get(point_type)
        results[t] = {
            "value": (m["percent"] if m else None),
            "unit": "percent",
            "covered": (m["hit"] if m else None),
            "total": (m["total"] if m else None),
        }
    # Drive goal compliance off the worst measured (non-null) type -- computed over
    # MISSION-REACHABLE points when mode exclusion applied.
    measured = [v["value"] for v in results.values() if v.get("value") is not None]
    driving = min(measured) if measured else None
    verdict = "review"
    if goal is not None and driving is not None:
        verdict = "pass" if float(driving) >= float(goal) else "fail"
    if unsupported:
        verdict = "not_assessable"
    # Emit the machine-checked reachability proof (tool-authored, not agent-authored).
    reach = _reachability_proof(points, reachable_unhit, mission_unreachable,
                                mode, sigs, ruling_id if apply_mode else "")
    try:
        with open(os.path.join(_OUTPUT_DIR, "code_coverage_reachability.json"),
                  "w", encoding="utf-8") as _rf:
            json.dump(reach, _rf, indent=2)
    except Exception:
        pass
    note = "real line/toggle coverage measured on a built+run model"
    if apply_mode:
        note += ("; MISSION mode: %d test-mode-only point(s) on %s excluded as "
                 "mission-unreachable (owned by scan-chain integrity + GLS mode=test), "
                 "%d mission-reachable point(s) still unhit"
                 % (len(mission_unreachable), ",".join(sigs), len(reachable_unhit)))
    if folded:
        note += ("; branch coverage is not a distinct Verilator metric (folded into "
                 "line/basic-block coverage), reported null")
    if unsupported:
        note += ("; unsupported requested Verilator metrics reported null: "
                 + ",".join(unsupported))

    # --- METRIC CLASSES (see catalog/tools/metric_classes.py) ----------------
    # (A) GATING. The gate is `reachable_unhit == 0`, and this is the ONLY value
    # allowed to close or block it. It is counted from the machine-checked
    # reachability proof, never narrated. Fail-closed: if the proof did not
    # produce a count, emit None (NOT ASSESSED) rather than a fabricated 0 --
    # a zero here would read as a fully-covered design.
    _ru = (reach.get("summary") or {}).get("reachable_unhit_total")
    results["reachable_unhit"] = {
        "value": int(_ru) if isinstance(_ru, int) else None,
        "unit": "points",
        "class": "gating",
        "basis": "counted_from_reachability_proof",
        "note": ("null means NOT ASSESSED (no reachability proof), never zero. "
                 "A percentage is NOT the gate: 100% of the wrong population "
                 "still closes nothing."),
    }
    # (D) MODEL-AUTHORED, advisory only. Cross-checked below and never a gate.
    # Labelled via the shared helper so an agent-SUPPLIED block still carries its
    # class/basis -- the naive `or`-default labels only the absent case.
    _interp = None
    if isinstance(interpretation, dict) and interpretation:
        try:
            import metric_classes
            _interp = metric_classes.label_interpretation(
                interpretation, basis="agent_read_of_coverage_report")
        except Exception:
            _interp = dict(interpretation)
            _interp.setdefault("basis", "agent_read_of_coverage_report")
            _interp["class"] = "model_authored"
    _xcheck = _crosscheck_interpretation(_interp, results["reachable_unhit"]["value"])
    # --- end metric classes --------------------------------------------------

    return _cde(
        objective=f"code coverage of {top} (Verilator, built+run)",
        status="completed", results=results,
        qor={"per_type": per_type, "coverage_types": types, **capabilities,
             "backend": "verilator",
             "measured_on": "RTL", "driving_percent": driving,
             "reachable_unhit": results["reachable_unhit"]["value"],
             "coverage_mode": ("test" if str(mode).lower() == "test" else "mission"),
             "mission_reachable_gate": apply_mode},
        signoff={"coverage_dat": "coverage.dat", "annotated": "annotated/",
                  **capabilities,
                 **driver,
                 "unsupported_types": unsupported, "folded_types": folded,
                 "coverage_mode": ("test" if str(mode).lower() == "test" else "mission"),
                 "test_mode_signals": sigs,
                 "reachability_proof": "code_coverage_reachability.json",
                 # (B) DIAGNOSTIC -- measured, non-gating. The debug surface: WHICH
                 # points are unhit, so a stimulus author can act without re-running.
                 "diagnostics": {
                     "class": "diagnostic",
                     "basis": "counted_from_reachability_proof",
                     "reachable_unhit_points": reach["reachable_unhit"],
                     "mission_unreachable_points": reach["structurally_unreachable"],
                     "per_type_hit_total": per_type,
                     "unsupported_types": unsupported,
                     "folded_types": folded,
                 },
                 # (C) DESCRIPTIVE -- configuration/context EXPECTED to hold steady.
                 # Separated so a constant that plateaus is not mistaken by the
                 # stall machinery for a gate that has stopped improving.
                 "descriptive": {
                     "class": "descriptive",
                     "basis": "run_configuration",
                     "backend": "verilator",
                     "coverage_types": types,
                     "rtl_file_count": len(files),
                     "mission_reachable_gate": apply_mode,
                     "elapsed_s": round(elapsed, 2),
                     "note": ("context, not a gate and not a progress signal -- "
                              "these are expected to stay constant across attempts"),
                 },
                 **({"interpretation": _interp} if _interp else {}),
                 "interpretation_crosscheck": _xcheck,
                 "reachability": {
                     "mode": reach["coverage_mode"],
                     "reachable_unhit_total": reach["summary"]["reachable_unhit_total"],
                     "mission_unreachable_total": reach["summary"]["structural_total"],
                     "reachable_unhit_zero": reach["summary"]["reachable_unhit_zero"],
                     "ruling_id": (ruling_id if apply_mode and mission_unreachable
                                   else None),
                     "reachable_unhit": reach["reachable_unhit"],
                     "mission_unreachable": reach["structurally_unreachable"],
                 },
                 "goal_compliance": _goal_compliance(driving, goal) if goal else None},
        inputs_ref={"rtl_files": files},
        assumptions=["hit rates measured by building AND running the instrumented "
                     "model (not instrumentation-only); goal gated on the worst type"
                     + (" over mission-reachable points" if apply_mode else "")],
        provenance={"verilator": _verilator_version(), "runtime_s": round(elapsed, 3),
                    "log": "verilator.log", "sim_log": "simulation.log"},
        validation={"verdict": verdict, "note": note},
    )



def _merge(params):
    dbs = params.get("coverage_dbs", [])
    merged = {}
    total = 0
    skipped = []
    for db in dbs:
        if os.path.exists(db):
            try:
                d = json.load(open(db))
                for k, v in d.items():
                    merged[k] = max(merged.get(k, 0), v)
                total += 1
            except Exception as _e:
                skipped.append({"db": os.path.basename(str(db)), "error": str(_e)})
                print("[" + str(TOOL) + "] coverage DB skipped (unparseable): "
                      + str(db) + ": " + str(_e), flush=True)
        else:
            skipped.append({"db": os.path.basename(str(db)), "error": "not found"})
    covered = sum(1 for v in merged.values() if v > 0)
    pct = round(100.0 * covered / len(merged), 2) if merged else None
    return _cde(objective="merge code coverage", status="completed",
                results={"merged_coverage": {"value": pct, "unit": "percent"}},
                qor={"points": len(merged), "covered": covered, "dbs_merged": total},
                signoff={"goal_compliance": _goal_compliance(pct, params.get("goal_percent")),
                         "dbs_skipped": skipped},
                inputs_ref={"coverage_dbs": dbs})


def _exclude(params):
    excl = params.get("exclusions", [])
    bad = [e for e in excl if not (e.get("justification") and e.get("owner"))]
    if bad:
        return _cde(objective="apply coverage exclusions", status="failed",
                    error="every exclusion requires justification and owner",
                    signoff={"unjustified": bad}, validation={"verdict": "fail"})
    return _cde(objective="apply coverage exclusions", status="completed",
                results={"exclusions_applied": {"value": len(excl), "unit": "count"}},
                signoff={"exclusion_ledger": excl},
                validation={"verdict": "pass_with_caveats"})


_SCENARIOS = {"measure_coverage": _measure, "merge_coverage": _merge, "exclude": _exclude}


def dispatch(params):
    s = params.get("scenario")
    if s not in _SCENARIOS:
        return _cde(objective="code coverage", status="failed",
                    error=f"unknown scenario '{s}'; supported: " + ", ".join(_SCENARIOS),
                    validation={"verdict": "fail"})
    if s == "measure_coverage" and not (shutil.which("verilator") or shutil.which("ghdl")):
        return _cde(objective="code coverage", status="failed",
                    error="neither verilator (Verilog) nor ghdl (VHDL) found on PATH",
                    validation={"verdict": "fail"})
    return _SCENARIOS[s](params)


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
