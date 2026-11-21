#!/usr/bin/env python3
"""constraints_utils.py -- SDC lint via real OpenSTA for the chip-constraints tool.

Reads the design + SDC with OpenSTA, checks for unconstrained endpoints and
unclocked registers (report_checks / check_setup), and reports constraint coverage.
Liberty/units come from the PDK binding. Node-aware. Results conform to the CDE.
"""
import json
import hashlib
import os
import re
import shutil
import subprocess
import time

import sdc_author

TOOL = "constraints"
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


def _bin():
    # SDC lint reads Verilog + Liberty (no LEF); standalone OpenSTA is correct here.
    for b in ("sta", "openroad"):
        if shutil.which(b):
            return b
    return None


def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    An envelope that stamps no `stage` resolves to no registry entry, reports NO
    METRIC, and a missing metric is indistinguishable downstream from a closed
    gate. The tool names its own gate rather than leaving it to the caller.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "constraints"
    except Exception:
        return "constraints"


# --- metric-class helpers (_METRIC_CLASS_HELPERS_V1) -------------------------------------
# Generated by catalog/migrate_metric_class_helpers.py. Do not hand-edit: the
# shared logic lives in catalog/tools/metric_classes.py so a fix reaches every
# tool at once.
def _labelled_interpretation(interp):
    """Stamp the model-authored class/basis via the shared vendored module.

    NOT a bare `or` default: an agent-SUPPLIED block must still be labelled, and
    the naive idiom labels only the ABSENT case -- so the one reading that
    actually needs the label ships unclassified.
    """
    try:
        import metric_classes
    except Exception:
        base = dict(interp) if isinstance(interp, dict) and interp else {}
        base.setdefault("basis", "agent_read_of_sdc_lint_log" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_sdc_lint_log")


def _crosscheck_interpretation(interp, measured, key):
    """Compare a model-authored count against the measured one; never decide.

    A disagreement is RECORDED, not resolved: a stale parser and a confabulated
    count need opposite fixes. An unavailable module is RECORDED too -- a
    cross-check that did not run must not read as one that passed.
    """
    try:
        import metric_classes
    except Exception as exc:
        return {"checked": False,
                "reason": "metric_classes module unavailable (%s); the "
                          "cross-check did NOT run" % exc}
    return metric_classes.crosscheck_interpretation(interp, measured, key)
# --- end metric-class helpers --------------------------------------------


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "stage": _canonical_stage(),
        "status": status, "objective": objective,
        "tools_used": [{"name": "OpenSTA", "version": provenance.get("sta") if provenance else "unknown"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": {},
        "signoff_evidence": signoff or {}, "margin": {"method": "constraint_coverage"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


# OpenSTA implements a subset of the Synopsys SDC/Tcl command set. These
# DC/PrimeTime-only collection-manipulation and constraint commands are NOT
# implemented in OpenSTA, so it aborts with a Tcl "invalid command name" error
# the instant read_sdc evaluates them -- surfacing as an opaque solver crash
# rather than a constraint finding. We pre-lint the SDC for them before invoking
# the solver so the failure is actionable (names the command + line number),
# fails closed, and is classified as a tool_input (authoring) error rather than
# an unconstrained-path failure. Extend/override per run via `sdc_disallow` /
# `sdc_allow`.
_OPENSTA_UNSUPPORTED_SDC = (
    "remove_from_collection",
    "add_to_collection",
    "copy_collection",
    "index_collection",
    "sort_collection",
    "compare_collections",
    "derive_constraints",
)


def _prelint_sdc(sdc_path, extra_disallow=None, allow=None):
    """Deterministically scan an SDC for OpenSTA-incompatible commands before the
    solver is ever invoked. Returns a list of {line, command, text} findings.
    An unreadable file returns no findings and is left to the solver to report."""
    findings = []
    allow_set = {str(a) for a in (allow or ())}
    disallow = [c for c in _OPENSTA_UNSUPPORTED_SDC if c not in allow_set]
    for c in (extra_disallow or []):
        if str(c) not in allow_set:
            disallow.append(str(c))
    try:
        with open(sdc_path, "r", encoding="utf-8", errors="replace") as _f:
            lines = _f.readlines()
    except Exception:
        return findings
    for i, raw in enumerate(lines, 1):
        code = raw.split("#", 1)[0]  # drop trailing comment
        if not code.strip():
            continue
        for cmd in disallow:
            if re.search(r"(?:^|[\s\[{;])" + re.escape(cmd) + r"(?:$|[\s\]};])", code):
                findings.append({"line": i, "command": cmd, "text": code.strip()[:200]})
    return findings


_GENERIC_CELL_RE = re.compile(r"^\s*\d+\s+(\$\S+)\s*$", re.M)


def _sha256(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


def _needs_gate_level_mapping(original, libs, top, yosys):
        """Structurally decide whether `original` still needs Yosys gate mapping.

        Elaborates the design for real (read_verilog; hierarchy; proc; opt_clean)
        and inspects the resulting cell census via `stat`. A design already
        expressed purely as named Liberty-cell instances needs no mapping; a
        design still containing generic Yosys RTLIL primitives ($dff, $adff,
        $mux, $add, $_DFF_P_, ...) after `proc` lowers its `always`/`assign`
        constructs is behavioral and requires dfflibmap/techmap/abc. This is a
        structural read of the elaborated netlist, not a regex over source text:
        a source file can need mapping whether or not it happens to contain a
        continuous-assignment expression (e.g. a register driven only by
        `always` blocks, as in crc16_ccitt, still needs mapping).

        Returns (needs_mapping, probe_log). On a probe failure (e.g. genuinely
        malformed RTL) this returns True so the caller's normalization attempt
        runs and surfaces the real Yosys error, rather than silently skipping
        normalization because the probe itself could not run.
        """
        liberty_reads = "; ".join(
            "read_liberty -lib {}".format(str(p)) for p in libs)
        script = (
            "{}; read_verilog {}; hierarchy -check -top {}; "
            "proc; opt_clean; stat -top {}"
        ).format(liberty_reads, original, top, top)
        probe = subprocess.run(
            [yosys, "-Q", "-p", script], capture_output=True, text=True,
            cwd=_WORK_DIR)
        output = (probe.stdout or "") + "\n" + (probe.stderr or "")
        if probe.returncode != 0:
            return True, output
        generic_cells = _GENERIC_CELL_RE.findall(output)
        return bool(generic_cells), output


def _opensta_netlist(netlist, libs, top):
        """Return an OpenSTA-readable netlist plus normalization provenance.

        OpenSTA's Verilog reader rejects behavioral RTL outright (`always`
        blocks raise a hard syntax error) as well as valid continuous
        expressions such as ``assign scan_out = scan_en & terminal_Q``.
        Normalize only when the elaborated design structurally still contains
        un-mapped RTLIL primitives (see `_needs_gate_level_mapping`), using
        Yosys and the caller-supplied Liberty. The original DFT artifact
        remains immutable.
        """
        original = str(netlist)
        meta = {
            "applied": False,
            "original_path": original,
            "original_sha256": _sha256(original),
            "normalized_path": original,
            "normalized_sha256": _sha256(original),
            "semantic_preservation": "identity",
        }
        if original.lower().endswith(".def"):
            return original, meta
        yosys = shutil.which("yosys")
        if not yosys:
            raise RuntimeError(
                "Verilog normalization requires Yosys to structurally determine "
                "whether gate-level mapping is needed, but yosys is not on PATH")
        needs_mapping, probe_log = _needs_gate_level_mapping(
            original, libs, top, yosys)
        probe_log_path = os.path.join(_OUTPUT_DIR, "netlist_mapping_probe.log")
        open(probe_log_path, "w", encoding="utf-8").write(probe_log)
        if not needs_mapping:
            return original, meta
        normalized = os.path.join(
            _OUTPUT_DIR, os.path.basename(original) + ".opensta.v")
        norm_log = os.path.join(_OUTPUT_DIR, "netlist_normalize.log")
        liberty_reads = "; ".join(
            "read_liberty -lib {}".format(str(p)) for p in libs)
        script = (
            "{}; read_verilog {}; hierarchy -check -top {}; "
            "proc; opt_clean; techmap; opt_clean; dfflibmap -liberty {}; "
            "opt_clean; abc -liberty {}; clean -purge; "
            "write_verilog -noattr -noexpr -nodec {}"
        ).format(liberty_reads, original, top, str(libs[0]), str(libs[0]),
                 normalized)
        proc = subprocess.run(
            [yosys, "-Q", "-p", script], capture_output=True, text=True,
            cwd=_WORK_DIR)
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        open(norm_log, "w", encoding="utf-8").write(output)
        if proc.returncode != 0 or not os.path.isfile(normalized):
            raise RuntimeError(
                "Yosys failed to normalize Verilog expressions; see "
                + os.path.basename(norm_log))

        equiv_log = os.path.join(_OUTPUT_DIR, "netlist_equivalence.log")
        # The gate netlist now instantiates real Liberty cells (dfxtp_1, etc,
        # via dfflibmap/abc), so proving gold/gate equivalence needs an actual
        # functional model for those cells, not the blackbox stubs `-lib`
        # produces for synthesis. `-wb` imports each cell's Liberty `function`/
        # `next_state` as a real gate-level body, and `flatten -wb` inlines
        # those whitebox cell bodies into the top module so equiv_make/
        # equiv_induct's SAT engine (which only reasons about a single
        # flattened module) has real logic to match against, not an opaque
        # cell type it cannot model.
        equiv_liberty_reads = "; ".join(
            "read_liberty -wb -ignore_miss_func {}".format(str(p)) for p in libs)
        equiv_script = (
            "{}; read_verilog {}; prep -top {}; flatten -wb; design -stash gold; "
            "{}; read_verilog {}; prep -top {}; flatten -wb; design -stash gate; "
            "design -copy-from gold -as gold {}; "
            "design -copy-from gate -as gate {}; "
            "equiv_make gold gate equiv; hierarchy -top equiv; "
            "equiv_simple; equiv_induct; equiv_status -assert"
        ).format(
            equiv_liberty_reads, original, top, equiv_liberty_reads, normalized,
            top, top, top)
        equiv = subprocess.run(
            [yosys, "-Q", "-p", equiv_script], capture_output=True, text=True,
            cwd=_WORK_DIR)
        equiv_output = (equiv.stdout or "") + "\n" + (equiv.stderr or "")
        open(equiv_log, "w", encoding="utf-8").write(equiv_output)
        if equiv.returncode != 0:
            raise RuntimeError(
                "normalized netlist failed Yosys equivalence; see "
                + os.path.basename(equiv_log))
        meta.update({
            "applied": True,
            "normalized_path": normalized,
            "normalized_sha256": _sha256(normalized),
            "normalizer": "yosys",
            "normalization_log": os.path.basename(norm_log),
            "semantic_preservation": "yosys_equiv_status_assert_pass",
            "equivalence_log": os.path.basename(equiv_log),
        })
        return normalized, meta


def _lint(params):
    binname = _bin()
    if binname is None:
        return _cde(objective="SDC lint", status="failed",
                    error="OpenSTA/openroad not found on PATH", validation={"verdict": "fail"})
    top, netlist, sdc = params.get("top"), params.get("netlist"), params.get("sdc")
    lib = params.get("liberty") or (params.get("pdk_binding") or {}).get("liberty")
    for n, v in (("top", top), ("netlist", netlist), ("sdc", sdc)):
        if not v:
            return _cde(objective="SDC lint", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"missing required field '{n}'", validation={"verdict": "fail"})
    if not lib:
        return _cde(objective="SDC lint", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="missing Liberty from params/pdk_binding", validation={"verdict": "fail"})
    libs = lib if isinstance(lib, list) else [lib]
    # Liberty-mount preflight: the SDC lint is worthless without the node Liberty,
    # and a missing mount is a distinct, recoverable failure class (fix the INPUTS/
    # mount recipe) -- NOT a design or unconstrained-path finding. Fail closed with
    # the binding-advertised path(s) vs. what is actually present in-container so the
    # Engine can repair the mount rather than mis-triage a solver crash.
    _missing_libs = [str(p) for p in libs if not os.path.exists(str(p))]
    if _missing_libs:
        _adv = None
        _pb = params.get("pdk_binding")
        if isinstance(_pb, dict):
            _refs = _pb.get("references") or {}
            _adv = {k: (_refs[k].get("container_path") if isinstance(_refs[k], dict) else _refs[k])
                    for k in ("liberty_tt", "liberty", "liberty_ss", "liberty_ff")
                    if k in _refs}
        return _cde(
            objective=f"SDC lint of {top}", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            results={"missing_liberty": _missing_libs},
            signoff={"clean": False, "liberty_mount_ok": False, "tool_input_error": True,
                     "genuine_unconstrained_clock_path": False,
                     "expected_liberty": libs, "missing_liberty": _missing_libs,
                     "binding_advertised_liberty": _adv,
                     "remediation": ("The node Liberty is not present at the expected "
                                     "container path(s); repair the INPUTS/mount recipe so "
                                     "the pdk-binding Liberty (references.liberty_tt."
                                     "container_path) is mounted read-only into this stage. "
                                     "This is a mount/environment error, not a design "
                                     "or unconstrained-path failure.")},
            inputs_ref={"netlist": netlist, "sdc": sdc, "liberty": libs},
            assumptions=["Liberty-mount preflight runs before OpenSTA; a missing Liberty "
                         "mount is classified distinctly from a constraint failure"],
            error=("Liberty not found at expected container path(s): "
                   + ", ".join(_missing_libs)
                   + ". Repair the PDK Liberty mount; SDC lint cannot proceed without it."),
            validation={"verdict": "fail",
                        "note": "Liberty mount preflight failed (liberty_mount_ok=false)"},
            provenance={"sta": binname, "preflight": "liberty_mount_v1"})
    for p in [netlist, sdc]:
        if not os.path.exists(str(p)):
            return _cde(objective="SDC lint", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    # Pre-lint the SDC for OpenSTA-incompatible commands and fail closed with an
    # actionable, correctly-classified error before we ever launch the solver.
    _sdc_findings = _prelint_sdc(sdc, extra_disallow=params.get("sdc_disallow"),
                                 allow=params.get("sdc_allow"))
    if _sdc_findings:
        _names = sorted({f["command"] for f in _sdc_findings})
        _detail = "; ".join(f"line {f['line']}: {f['command']}" for f in _sdc_findings[:20])
        return _cde(
            objective=f"SDC lint of {top}", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            results={"sdc_prelint_findings": _sdc_findings,
                     "unsupported_commands": _names},
            signoff={"clean": False, "tool_input_error": True,
                     "genuine_unconstrained_clock_path": False,
                     "remediation": ("Re-author the SDC using OpenSTA-supported commands; "
                                     "OpenSTA does not implement these Synopsys DC/PT "
                                     "commands: " + ", ".join(_names) + ". Build port/pin "
                                     "lists with get_ports/get_pins + filtering instead of "
                                     "remove_from_collection/add_to_collection.")},
            inputs_ref={"netlist": netlist, "sdc": sdc, "liberty": libs},
            assumptions=["SDC pre-lint runs before OpenSTA to catch tool-incompatible "
                         "commands, fail closed, and classify a tool_input error "
                         "distinctly from an unconstrained-path failure"],
            error=("SDC uses OpenSTA-unsupported command(s): " + _detail + ". These abort "
                   "OpenSTA with a Tcl 'invalid command name' error at read_sdc. This is a "
                   "constraint-authoring (tool_input) error, not an unconstrained-path failure."),
            validation={"verdict": "fail",
                        "note": "SDC pre-lint rejected OpenSTA-incompatible command(s) "
                                "before solver invocation"},
            provenance={"sta": binname, "prelint": "sdc_prelint_v1"})
    reads = "\n".join(f"read_liberty {l}" for l in libs)
    try:
        sta_netlist, normalization = _opensta_netlist(netlist, libs, top)
    except Exception as e:
        return _cde(
            objective=f"SDC lint of {top}", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            error=str(e), validation={"verdict": "fail"},
            inputs_ref={"netlist": netlist, "sdc": sdc, "liberty": libs},
            provenance={"sta": binname, "netlist_normalization": "failed"})
    reader = (f"read_def {sta_netlist}" if sta_netlist.endswith(".def")
              else f"read_verilog {sta_netlist}")
    # check_setup enrichment. -verbose expands diagnostics; check_setup_flags lets
    # the caller enable specific structural checks (e.g. -multiple_clock,
    # -no_clock, -no_input_delay, -loops, -generated_clocks,
    # -unconstrained_endpoints) that surface more constraint gaps.
    _cs_opts = ""
    if str(params.get("verbose", "")).lower() in ("1", "true", "yes"):
        _cs_opts += " -verbose"
    _valid_flags = {"-multiple_clock", "-no_clock", "-no_input_delay", "-loops",
                    "-generated_clocks", "-unconstrained_endpoints"}
    for f in (params.get("check_setup_flags") or []):
        fl = f if str(f).startswith("-") else "-" + str(f)
        if fl in _valid_flags:
            _cs_opts += f" {fl}"
    script = f"""{reads}
{reader}
link_design {top}
read_sdc {sdc}
puts "__UNCONSTRAINED__"
report_checks -unconstrained -format end
puts "__CHECKSETUP__"
check_setup{_cs_opts}
report_checks -unconstrained -format end > {os.path.join(_OUTPUT_DIR, "constraints.rpt")}
check_setup{_cs_opts} >> {os.path.join(_OUTPUT_DIR, "constraints.rpt")}
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "lint.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command([binname, "-exit", sp])
    proc = subprocess.run([binname, "-exit", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "lint.log"), "w").write(out)
    if proc.returncode != 0 and "__CHECKSETUP__" not in out:
        _tool_input = bool(re.search(
            r"invalid command name|syntax error|wrong # args|can't read|no such (?:file|command)",
            out, re.I))
        return _cde(objective="SDC lint", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    signoff={"clean": False, "tool_input_error": _tool_input,
                             "genuine_unconstrained_clock_path": False},
                    error=("OpenSTA failed"
                           + (" (SDC/tool-input error)" if _tool_input else "")
                           + "; see lint.log:\n" + out[-1500:]),
                    validation={"verdict": "fail"},
                    provenance={"sta": binname, "log": "lint.log"})
    unclocked = len(re.findall(r"unclocked|no clock|not constrained", out, re.I))
    # *** THE TOOL'S OWN SECTION MARKER MUST NOT BE COUNTED AS A VIOLATION. ***
    # This script prints `puts "__UNCONSTRAINED__"` as a banner, and the old
    # pattern (`Unconstrained|no paths|missing`, case-insensitive) matched it --
    # so the count was PINNED AT >= 1 on every run and the gate was UNCLOSABLE BY
    # CONSTRUCTION. Measured on a real sandbox run: 2 indicators reported on an
    # SDC whose real defect count was ZERO (one hit was this banner, the other a
    # DELIBERATE `set_false_path` on rst_n).
    #
    # Same family as the DX-55 synthesis deadlock (no code path could reach
    # `pass`): a gate that cannot close is indistinguishable from a design defect
    # to everyone downstream.
    _scan = "\n".join(l for l in out.splitlines()
                      if "__UNCONSTRAINED__" not in l)
    unconstrained = len(re.findall(r"Unconstrained|no paths|missing", _scan, re.I))
    warnings = re.findall(r"Warning:.*", out)

    # --- CONSTRAINT COVERAGE (measured, not keyword-counted) -----------------
    # `unclocked_indicators` counts words in a report, so a regex that matches
    # nothing yields 0 and closes the gate: "no complaints" and "nothing was
    # examined" are indistinguishable. Enumerating the design gives the missing
    # DENOMINATOR -- endpoints that exist -- so the two can finally be told
    # apart. Coverage is reported as not_assessable (null) whenever the
    # population cannot be established; null is never rendered as zero.
    _cov = {"assessable": False, "note": "enumeration not attempted"}
    try:
        _enum = sdc_author.enumerate_design(
            binname, _WORK_DIR, _OUTPUT_DIR, reads, reader, top, sdc=sdc)
        _cov = sdc_author.coverage(_enum)
    except Exception as _e:  # noqa: BLE001
        _cov = {"assessable": False,
                "note": "design enumeration failed: %s" % _e}
        _enum = {}

    try:
        with open(sdc, encoding="utf-8") as _handle:
            _sdc_text = _handle.read()
        _electrical = sdc_author.verify_electrical_intent(
            _sdc_text, _enum, params.get("constraint_intent"))
    except Exception as _e:  # noqa: BLE001
        _electrical = {
            "required": bool(params.get("constraint_intent")),
            "assessable": False, "pass": False,
            "missing_commands": ["electrical verification failed: %s" % _e],
        }

    # --- VERDICT -------------------------------------------------------------
    # THIS PATH PREVIOUSLY COULD NOT FAIL. `unclocked_indicators` is declared
    # gating with closes_at "== 0", yet the verdict was
    #     "pass" if clean else "pass_with_caveats"
    # so a design WITH unclocked endpoints returned status=completed, exit 0 and
    # a passing-family verdict. A gate that cannot fail is not a gate, and an
    # agent whose verdict contradicts its own declared gate teaches every reader
    # downstream to distrust the declaration. A non-zero gating count is now a
    # FAIL here, at the source, instead of relying on a later layer to notice.
    #
    # Coverage that could not be measured is NOT a failure -- it is a missing
    # measurement, and it is recorded as a caveat so it cannot read as clean.
    _gate_open = (
        unclocked > 0
        or (_electrical.get("required") and not _electrical.get("pass")))
    if _gate_open:
        _verdict = "fail"
        if unclocked > 0:
            _vnote = ("unclocked_indicators=%d: the design has endpoint(s) STA "
                      "will never analyze, so the timing question itself is "
                      "incomplete" % unclocked)
        else:
            _vnote = (
                "electrical intent verification failed: %d command(s) missing"
                % len(_electrical.get("missing_commands") or []))
    elif not _cov.get("assessable"):
        _verdict = "pass_with_caveats"
        _vnote = ("no unclocked indicators, but constraint COVERAGE was not "
                  "measurable (%s), so completeness is unproven rather than "
                  "confirmed" % _cov.get("note", "reason unrecorded"))
    else:
        _verdict = "pass"
        _vnote = ("no unclocked indicators; endpoint population measured (%s)"
                  % _cov.get("endpoint_population"))
    clean = not _gate_open
    return _cde(
        objective=f"SDC lint of {top}",
        status="completed",
        pdk_binding=params.get("pdk_binding", "none"),
        # (A) GATING -- an unclocked endpoint is a path STA will never analyze,
        # so it is a hole in the timing question itself, not a timing result.
        # NOTE the honest limitation recorded in `basis`: these are counted by
        # keyword over OpenSTA text, so they are INDICATORS, not an authoritative
        # endpoint enumeration -- the name says `_indicators` for that reason.
        results={"unclocked_indicators": {
                     "value": unclocked, "unit": "count",
                     "class": "gating", "basis": "parsed_opensta_check_setup_output",
                     "closes_at": "== 0",
                     "note": ("Keyword-counted INDICATORS over OpenSTA output, not "
                              "an authoritative endpoint enumeration. An unclocked "
                              "endpoint is a path STA never analyzes, so zero here "
                              "is necessary but not sufficient for constraint "
                              "completeness. A null means NOT ASSESSED.")},
                 "unconstrained_indicators": {
                     "value": unconstrained, "unit": "count",
                     "class": "diagnostic", "basis": "parsed_opensta_check_setup_output",
                     "note": ("DIAGNOSTIC, deliberately NOT gating. This keyword "
                              "count CANNOT distinguish a REQUIRED exception from "
                              "a real gap: a `set_false_path` on an async reset is "
                              "correct design intent, yet OpenSTA still reports the "
                              "port as missing set_input_delay and this counter "
                              "would score it as a defect. Gating on it would make "
                              "the stage unclosable for a design that is right. "
                              "`unclocked_indicators` is the real gate.")},
                 "warnings": {
                     "value": len(warnings), "unit": "count",
                     "class": "diagnostic", "basis": "parsed_opensta_check_setup_output",
                     "note": ("Advisory noise. Deliberately NOT gating: gating on "
                              "raw warning volume would make the stage unclosable "
                              "for reasons unrelated to constraint completeness.")},
                 "endpoint_population": {
                     "value": _cov.get("endpoint_population"), "unit": "count",
                     "class": "diagnostic", "basis": "opensta_tcl_design_enumeration",
                     "note": ("The DENOMINATOR the keyword counts never had. "
                              "Measured by design introspection, so 'no findings' "
                              "can finally be told apart from 'nothing was "
                              "examined'. NULL means the population could not be "
                              "established -- not that it is zero.")},
                 "clocks_defined": {
                     "value": _cov.get("clocks_defined"), "unit": "count",
                     "class": "diagnostic", "basis": "opensta_tcl_design_enumeration",
                     "note": ("Clocks the SDC actually defines, read back from the "
                              "solver rather than from the SDC text. Zero clocks on "
                              "a sequential design means every endpoint is "
                              "unconstrained however few words the report used.")},
                 "electrical_intent_commands_verified": {
                     "value": _electrical.get("verified_commands"),
                     "unit": "count",
                     "class": ("gating" if _electrical.get("required")
                               else "diagnostic"),
                     "basis": _electrical.get(
                         "basis",
                         "authored_sdc_exact_command_and_enumerated_object_crosscheck"),
                     "closes_at": "== expected_commands",
                     "note": ("Exact set_clock_transition, pre-CTS "
                              "set_clock_latency, set_input_transition, and "
                              "set_load commands are checked against the "
                              "enumerated clock/input/output object population.")}},
        signoff={"clean": clean, "warnings_sample": warnings[:20], "report": "lint.log",
                 "liberty_mount_ok": True,
                 "constraint_coverage": _cov,
                 "electrical_intent_verification": _electrical,
                 "check_setup_options": _cs_opts.strip() or "default",
                 # (B) DIAGNOSTIC -- the repair surface: the actual warning text
                 # is what tells an author WHICH ports/clocks are unconstrained.
                 "diagnostics": {
                     "class": "diagnostic",
                     "basis": "parsed_opensta_check_setup_output",
                     "warnings_sample": warnings[:20],
                     "warning_count": len(warnings),
                     "unclocked_indicators": unclocked,
                     "unconstrained_indicators": unconstrained,
                     "method_note": ("ZERO EXCEPTIONS IS NOT A QUALITY TARGET: a "
                                     "REQUIRED-but-absent exception (e.g. a "
                                     "synchronizer false path) is as much a defect "
                                     "as an unjustified one, and no downward count "
                                     "here can detect that.")},
                 # (C) DESCRIPTIVE -- configuration, expected to hold steady.
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "top": top, "engine": binname,
                     "liberty_count": len(libs) if isinstance(libs, list) else 1,
                     "check_setup_options": _cs_opts.strip() or "default",
                     "elapsed_s": round(elapsed, 3)},
                 # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), unclocked,
                     "unclocked_indicators")},
        inputs_ref={"netlist": netlist, "opensta_netlist": sta_netlist,
                    "sdc": sdc, "liberty": libs},
        assumptions=["coverage inferred from OpenSTA check_setup/report_checks output",
                     "constraint coverage is measured by design enumeration; when the "
                     "endpoint population cannot be established the result is "
                     "not_assessable and is NEVER reported as zero"],
        validation={"verdict": _verdict, "note": _vnote},
        provenance={"sta": binname, "runtime_s": round(elapsed, 3),
                    "log": "lint.log", "netlist_normalization": normalization},
    )


def _author(params):
    """Author an SDC from DERIVED netlist structure + SUPPLIED intent, then lint
    the result in the same run.

    THE ROUND TRIP IS THE POINT. An authored SDC that has not been checked is a
    claim; authoring and immediately linting makes the artifact and its evidence
    the same run, so the tool can never emit constraints it has not examined.

    NOTHING IS DEFAULTED. A constraint whose intent was not supplied becomes a
    named HOLE and the run is not_assessable. That rule exists because of one
    number in particular: an invented clock period is targeted by synthesis,
    balanced by CTS, closed by STA and blessed at signoff, with every stage
    reporting success against a period nobody chose.
    """
    binname = _bin()
    if binname is None:
        return _cde(objective="SDC authoring", status="failed",
                    error="OpenSTA/openroad not found on PATH",
                    validation={"verdict": "fail"})
    top, netlist = params.get("top"), params.get("netlist")
    lib = params.get("liberty") or (params.get("pdk_binding") or {}).get("liberty")
    for n, v in (("top", top), ("netlist", netlist)):
        if not v:
            return _cde(objective="SDC authoring", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"missing required field '{n}'",
                        validation={"verdict": "fail"})
    if not lib:
        return _cde(objective="SDC authoring", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error="missing Liberty from params/pdk_binding",
                    validation={"verdict": "fail"})
    libs = lib if isinstance(lib, list) else [lib]
    for p in [netlist] + [str(x) for x in libs]:
        if not os.path.exists(str(p)):
            return _cde(objective="SDC authoring", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"input not found: {p}",
                        validation={"verdict": "fail"})

    reads = "\n".join(f"read_liberty {l}" for l in libs)
    try:
        sta_netlist, normalization = _opensta_netlist(netlist, libs, top)
    except Exception as e:
        return _cde(
            objective=f"SDC authoring for {top}", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            error=str(e), signoff={"authored": False},
            validation={"verdict": "fail",
                        "note": "netlist normalization failed"},
            inputs_ref={"netlist": netlist, "liberty": libs},
            provenance={"sta": binname, "netlist_normalization": "failed"})
    reader = (f"read_def {sta_netlist}" if str(sta_netlist).endswith(".def")
              else f"read_verilog {sta_netlist}")
    # Enumerate WITHOUT an SDC: this is the raw structural population, which is
    # what authoring needs (with an SDC we would only see what is already
    # constrained -- the wrong question when the SDC is what we are writing).
    try:
        enum = sdc_author.enumerate_design(binname, _WORK_DIR, _OUTPUT_DIR,
                                           reads, reader, top, sdc=None)
    except Exception as e:  # noqa: BLE001
        return _cde(objective=f"SDC authoring for {top}", status="failed",
                    pdk_binding=params.get("pdk_binding", "none"),
                    error=f"design enumeration failed: {e}",
                    signoff={"authored": False},
                    validation={"verdict": "fail",
                                "note": "cannot author without design structure"},
                    provenance={"sta": binname})

    lines, emitted, holes, port_classes = sdc_author.author_sdc(
        enum, params.get("constraint_intent"), top=top)
    if lines is None:
        return _cde(
            objective=f"SDC authoring for {top}", status="failed",
            pdk_binding=params.get("pdk_binding", "none"),
            results={"authored_constraints": {
                "value": 0, "unit": "count", "class": "diagnostic",
                "basis": "opensta_tcl_design_enumeration",
                "note": "nothing authored: design structure was never enumerated"}},
            signoff={"authored": False, "holes": holes,
                     "constraint_coverage": sdc_author.coverage(enum)},
            error=("design enumeration produced no structure, so no constraint "
                   "could be derived; this is NOT an empty-but-clean result"),
            validation={"verdict": "not_assessable",
                        "note": "authoring requires design structure"},
            provenance={"sta": binname, "log": enum.get("log")})

    out_sdc = os.path.join(_OUTPUT_DIR, f"{top}.authored.sdc")
    open(out_sdc, "w").write("\n".join(lines) + "\n")

    # CARRY-FORWARD REGRESSION CHECK. An SDC refresh that silently loses a
    # directive class its predecessor carried is invisible downstream: the file
    # still parses, every later stage reads it without complaint, and the lost
    # constraint simply stops being checked. Comparing against the SDC this one
    # supersedes is the only place that loss is cheap to see.
    baseline_path = params.get("baseline_sdc")
    baseline_text = None
    if baseline_path:
        try:
            with open(baseline_path, encoding="utf-8", errors="replace") as _f:
                baseline_text = _f.read()
        except OSError as _e:
            return _cde(objective=f"SDC authoring for {top}", status="failed",
                        pdk_binding=params.get("pdk_binding", "none"),
                        error=f"baseline_sdc not readable: {baseline_path}: {_e}",
                        validation={"verdict": "fail",
                                    "note": ("a baseline was named but could not "
                                             "be read; proceeding without it "
                                             "would silently skip the "
                                             "carry-forward check and report a "
                                             "dropped directive as clean")})
    carry_forward = sdc_author.carry_forward_check(
        baseline_text, "\n".join(lines),
        (params.get("constraint_intent") or {}).get("dropped_directives"))
    if baseline_text is not None:
        carry_forward["baseline_sdc"] = str(baseline_path)
        _baseline_hash = _hash_input_file(str(baseline_path))
        if _baseline_hash:
            carry_forward.update(_baseline_hash)
    for dropped in carry_forward.get("dropped_without_justification") or []:
        holes.append({
            "kind": "directive_dropped_without_justification",
            "command": dropped["command"],
            "detail": ("'{cmd}' appeared {n}x in the SDC this one supersedes "
                       "({base}) and 0x here, with no recorded justification. "
                       "A directive class that disappears between attempts is "
                       "indistinguishable downstream from one that was never "
                       "required -- declare the removal in "
                       "constraint_intent.dropped_directives (command + reason "
                       "+ source), or re-author the directive."
                       .format(cmd=dropped["command"],
                               n=dropped["baseline_count"],
                               base=baseline_path))})

    # ROUND TRIP: lint what we just wrote, in this run.
    lint_res = None
    if emitted:
        lint_res = _lint(dict(
            params, netlist=sta_netlist, sdc=out_sdc,
            constraint_intent=params.get("constraint_intent")))

    _lint_verdict = ((lint_res or {}).get("validation") or {}).get("verdict")
    _regressions = carry_forward.get("dropped_without_justification") or []
    if _regressions:
        verdict, note = "fail", (
            "%d directive class(es) present in the superseded SDC are absent "
            "here with no recorded justification (%s); a silently dropped "
            "directive stops being checked downstream while the file still "
            "reads as complete"
            % (len(_regressions),
               ", ".join(r["command"] for r in _regressions)))
    elif holes:
        verdict, note = "not_assessable", (
            "%d constraint(s) not emitted because the intent behind them was not "
            "supplied; an SDC missing them is incomplete, and inventing them "
            "would be worse" % len(holes))
    elif _lint_verdict in ("fail", None):
        verdict, note = "fail", (
            "authored SDC did not lint clean (%s); the artifact and its evidence "
            "are the same run, so this is reported rather than shipped"
            % _lint_verdict)
    else:
        verdict, note = "pass", "authored SDC lints clean with no unsupplied intent"
        if not carry_forward.get("assessable"):
            note += (" (NOT compared against a superseded SDC: no baseline_sdc "
                     "was supplied, so a dropped directive class would not have "
                     "been detected)")

    return _cde(
        objective=f"SDC authoring for {top}",
        status="completed" if not holes else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={
            "authored_constraints": {
                "value": len(emitted), "unit": "count", "class": "diagnostic",
                "basis": "netlist_structure_plus_supplied_intent",
                "note": ("Constraints written. Structure derived from the netlist; "
                         "every NUMBER caller-supplied and recorded with its "
                         "source in the SDC itself.")},
            "unsupplied_intent_holes": {
                "value": len(holes), "unit": "count", "class": "gating",
                "basis": "netlist_structure_plus_supplied_intent",
                "closes_at": "== 0",
                "note": ("Constraints that COULD NOT be written because their "
                         "intent was not supplied -- most importantly a clock "
                         "period. Gating: an authored SDC with holes is "
                         "incomplete, and a defaulted value would be adopted by "
                         "synthesis, CTS, STA and signoff with every stage "
                         "reporting success against a number nobody chose.")}},
        signoff={"authored": True, "sdc": out_sdc,
                 "emitted": emitted, "holes": holes,
                 "constraint_coverage": sdc_author.coverage(enum),
                 # CARRY-FORWARD: what the SDC this one supersedes carried and
                 # this one does not. `assessable: false` means no baseline was
                 # supplied, so the comparison never ran -- that is an honest
                 # unknown and must not be read as "nothing was dropped".
                 "carry_forward_check": carry_forward,
                 # PORT CLASSIFICATION: which inputs are clocks, which are
                 # declared resets, which are data. Input ports are not one
                 # population -- a clock port given set_input_delay is timed as
                 # a data path while the real clock stays undefined.
                 "input_port_classes": port_classes,
                 "port_class_counts": {
                     k: sum(1 for v in port_classes.values() if v == k)
                     for k in ("clock", "reset", "data")},
                 "round_trip_lint_verdict": _lint_verdict,
                 "round_trip_constraint_coverage": (
                     ((lint_res or {}).get("signoff_evidence") or {}).get(
                         "constraint_coverage")),
                 "round_trip_electrical_intent_verification": (
                     ((lint_res or {}).get("signoff_evidence") or {}).get(
                         "electrical_intent_verification")),
                 "diagnostics": {
                     "class": "diagnostic",
                     "basis": "netlist_structure_plus_supplied_intent",
                     "clock_candidates": sdc_author.derive_clock_candidates(enum),
                     "native_enumeration": enum,
                     "method_note": ("Structure is DERIVABLE (which ports drive "
                                     "clock pins); intent is NOT (the period, the "
                                     "I/O budget, which paths are truly false). "
                                     "The second kind is never inferred.")},
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "top": top, "engine": binname,
                     "liberty_count": len(libs)},
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), len(holes),
                     "unsupplied_intent_holes")},
        inputs_ref={"netlist": netlist, "opensta_netlist": sta_netlist,
                    "liberty": libs},
        assumptions=[
            "netlist structure is DERIVED; every numeric value is CALLER-SUPPLIED "
            "and recorded with its source -- no period, budget or exception is "
            "ever defaulted",
            "the authored SDC is linted in the same run, so the tool never emits "
            "constraints it has not itself checked",
            ("this SDC was compared command-for-command against the one it "
             "supersedes (%s); a directive class that disappeared with no "
             "recorded justification is a gating hole, not a silent edit"
             % baseline_path) if carry_forward.get("assessable") else
            ("NO baseline SDC was supplied, so this SDC was NOT compared "
             "against the one it supersedes; a directive class dropped since "
             "the previous attempt would not have been detected here")],
        validation={"verdict": verdict, "note": note},
        provenance={"sta": binname, "log": enum.get("log"),
                    "authored_sdc": out_sdc,
                    "netlist_normalization": normalization},
    )


def dispatch(params):
    s = params.get("scenario")
    if s == "lint_sdc":
        return _lint(params)
    if s == "author_sdc":
        return _author(params)
    return _cde(objective="constraints", status="failed",
                error=f"unknown scenario '{s}'; supported: lint_sdc, author_sdc",
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
