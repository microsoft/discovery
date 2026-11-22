#!/usr/bin/env python3
"""cdc_rdc_utils.py -- structural CDC/RDC signoff for the chip-cdc-rdc tool.

Approach: Yosys elaborates the RTL and writes a JSON netlist; we extract flip-flops
and their clock nets, then use the supplied domain_map to classify crossings. A
crossing is a data path from a flop in domain A into a flop in domain B. We
recognize a 2-flop synchronizer when the destination-domain flop feeds a second
destination-domain flop before fan-out. Unsynchronized crossings (or single-flop)
are violations unless waived. The domain map is required.

Scenarios (dispatch):
  * cdc_signoff        -- clock-domain-crossing screen (above).
  * rdc_signoff        -- a genuine RESET-domain analysis (`_analyze_rdc`): async-
                          reset flops whose reset was asserted in one domain but
                          lands in a flop clocked in another domain without a reset
                          synchronizer are reset crossings. NOT a relabeled CDC.
  * synchronizer_verify-- CDC screen + per-crossing 2-flop-synchronizer check; a
                          crossing missing its synchronizer fails the gate.
  * reconvergence      -- CDC screen + fan-in check: multiple separately-synchronized
                          crossings into one destination flop are flagged.

FAIL-CLOSED: when elaboration extracts zero sequential cells (nothing to check) or
the supplied domain map does not resolve against the netlist, the tool returns
status=failed / verdict=not_assessable -- it never reports status=completed for a
non-assessment, so a downstream reviewer cannot mistake 'did not run' for a clean
signoff (the DX-34 zero-flop VHDL incident).

This is a real structural screen on the elaborated netlist; it is not a full
commercial CDC/RDC signoff. Node-agnostic. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

import rtl_frontend
import cdc_formal
import domain_formal

TOOL = "cdc-rdc"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"
_ACTIVE_VERILOG_DEFINES = []
_ACTIVE_MODEL_PATHS = set()
_ACTIVE_MODEL_EVIDENCE = None
_ACTIVE_INPUT_BRIDGES = []
#: Hierarchical instances `flatten` could not inline and this run ACCEPTED, with
#: the basis for each. Always populated (unlike `_ACTIVE_MODEL_EVIDENCE`, which
#: only exists when a PDK binding supplied cell models), so an acceptance is
#: never made silently for want of somewhere to record it.
_ACCEPTED_HIERARCHY = []
#: Unsupported state the run accepted under a named-human ledger ruling, with the
#: machine-checked proof that authorized it. `None` whenever no acceptance was
#: made, so the absence of a waiver and a silent waiver can never look alike.
_ACCEPTED_UNSUPPORTED_STATE = None


def _is_ident(s):
    """True if *s* is a safe HDL/Tcl identifier -- blocks script injection via
    user-supplied module names interpolated into Yosys scripts."""
    s = str(s) if s else ""
    if not s or not (s[0].isalpha() or s[0] == "_"):
        return False
    return all(c.isalnum() or c in "_$" for c in s)


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

_CDC_REQUIRED_STRUCTURAL_FAMILIES = (
    "synchronizer_verification",
    "reconvergence",
    "crossing_classification",
    "reset_resolution",
)

#: Gate scopes that MUST bind every structural family before a `pass` is allowed
#: out. A waiver-accepted gate is listed here deliberately: the acceptance
#: narrows what was measured, it does not exempt the envelope from being bound.
_CDC_BOUND_GATE_SCOPES = (
    "cdc_structural_complete",
    "cdc_accepted_with_waiver",
)

_HOST_OWNED_TASK_IDENTITY_FIELDS = (
    "run_id",
    "task_uuid",
    "task_dx_id",
    "task_identity_sha256",
)


def _enforce_task_identity_handoff(results):
    """Raw tool output must never claim host-owned task/run identity."""
    provenance = results.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        results["provenance"] = provenance
    claimed = sorted({
        key for key in _HOST_OWNED_TASK_IDENTITY_FIELDS
        if results.get(key) not in (None, "")
        or provenance.get(key) not in (None, "")
    })
    provenance["task_identity_authority"] = (
        "catalog/stage_task_identity.canonical_stamp")
    if not claimed:
        provenance["task_identity_state"] = "host_finalization_required"
        return

    error = (
        "raw CDC tool output contains host-owned task/run identity field(s): "
        + ", ".join(claimed)
        + "; leave them absent and finalize the attempt on the host with "
          "catalog/finalize_cde.py")
    provenance["task_identity_state"] = "rejected_untrusted_tool_stamp"
    results["status"] = "failed"
    results["error"] = error
    validation = results.get("validation")
    if not isinstance(validation, dict):
        validation = {}
        results["validation"] = validation
    validation["verdict"] = "fail"
    validation["stage_closure_eligible"] = False
    validation["note"] = error


def _enforce_cdc_progress_contract(results):
    """A passing full CDC result must bind every structural obligation."""
    signoff = results.get("signoff_evidence")
    validation = results.get("validation")
    if not isinstance(signoff, dict) \
            or signoff.get("gate_scope") not in _CDC_BOUND_GATE_SCOPES \
            or not isinstance(validation, dict) \
            or validation.get("verdict") != "pass":
        return
    progress = results.get("progress")
    families = progress.get("families") if isinstance(progress, dict) else None
    missing = [
        name for name in _CDC_REQUIRED_STRUCTURAL_FAMILIES
        if not isinstance(families, dict)
        or not isinstance(families.get(name), dict)
        or not isinstance(families[name].get("residual"), (int, float))
    ]
    open_families = [
        name for name in _CDC_REQUIRED_STRUCTURAL_FAMILIES
        if isinstance(families, dict)
        and isinstance(families.get(name), dict)
        and isinstance(families[name].get("residual"), (int, float))
        and families[name]["residual"] != 0
    ]
    if not missing and not open_families:
        return
    detail = []
    if missing:
        detail.append("unbound: " + ", ".join(missing))
    if open_families:
        detail.append("open: " + ", ".join(open_families))
    error = "full CDC gate has invalid structural progress (" + "; ".join(detail) + ")"
    results["status"] = "failed"
    results["error"] = error
    results["validation"] = {
        "verdict": "fail",
        "stage_closure_eligible": False,
        "note": error,
    }


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

    _enforce_task_identity_handoff(results)

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

    _enforce_cdc_progress_contract(results)

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


def _yosys_version():
    try:
        return subprocess.run(["yosys", "-V"], capture_output=True, text=True,
                              timeout=30).stdout.strip().split("\n")[0]
    except Exception:
        return "unknown"


def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    An envelope that stamps no `stage` resolves to no registry entry, reports NO
    METRIC, and a missing metric is indistinguishable downstream from a closed
    gate. The tool names its own gate rather than leaving it to the caller.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "cdc"
    except Exception:
        return "cdc"


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
        base.setdefault("basis", "agent_read_of_cdc_report" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_cdc_report")


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


#: A waiver is an ACCOUNTABILITY RECORD, not a mute button. Matching on the
#: crossing ID alone meant any caller could silence a real CDC violation by
#: naming it -- with no owner to answer for the decision and no reason anyone
#: could review later. These are the same fields chip-ppa-signoff-design-review
#: already requires, so a waiver that survives here also survives signoff review.
_WAIVER_REQUIRED_FIELDS = ("owner", "justification")


def _split_waivers(waivers):
    """Split waivers into (valid, invalid).

    An INVALID waiver does not waive anything: the violation it names stays
    un-waived and still gates. It is reported separately so the caller can see
    that the waiver was rejected rather than silently ignored."""
    valid, invalid = [], []
    for w in (waivers or []):
        if not isinstance(w, dict):
            invalid.append({"waiver": w, "missing": ["not an object"]})
            continue
        missing = [f for f in _WAIVER_REQUIRED_FIELDS
                   if not str(w.get(f) or "").strip()]
        if missing:
            invalid.append({"waiver": w.get("crossing") or w.get("bus")
                            or w.get("signal") or w, "missing": missing})
        else:
            valid.append(w)
    return valid, invalid


def _cde(objective, status, results=None, signoff=None, assumptions=None,
         validation=None, provenance=None, inputs_ref=None, error=None,
         pdk_binding="none"):
    env = {
        "tool": TOOL, "stage": _canonical_stage(),
        "status": status, "objective": objective,
        "tools_used": [{"name": "Yosys", "version": _yosys_version()}],
        "pdk_binding": pdk_binding, "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "shared_artifact",
        "results": results or {}, "qor_metrics": {},
        "signoff_evidence": signoff or {},
        "margin": {"method": "structural_cdc_screen"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _stage_rtl(params):
    global _ACTIVE_VERILOG_DEFINES, _ACTIVE_MODEL_PATHS
    global _ACTIVE_MODEL_EVIDENCE, _ACTIVE_INPUT_BRIDGES, _ACCEPTED_HIERARCHY
    global _ACCEPTED_UNSUPPORTED_STATE
    _ACTIVE_VERILOG_DEFINES = []
    _ACTIVE_MODEL_PATHS = set()
    _ACTIVE_MODEL_EVIDENCE = None
    _ACTIVE_INPUT_BRIDGES = []
    _ACCEPTED_HIERARCHY = []
    _ACCEPTED_UNSUPPORTED_STATE = None
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "dut.v")
        open(p, "w").write(params["rtl"])
        files.append(p)
    for rf in params.get("rtl_files", []):
        if os.path.exists(rf):
            files.append(rf)
    source_uses_io = any(
        "sky130_ef_io__" in open(path, encoding="utf-8", errors="ignore").read()
        for path in files)
    if source_uses_io:
        binding = params.get("pdk_binding")
        if isinstance(binding, str):
            with open(binding, encoding="utf-8") as stream:
                binding = json.load(stream)
        if not isinstance(binding, dict):
            raise ValueError(
                "Sky130 pad hierarchy requires a hash-pinned pdk_binding")
        profile = ((binding.get("functional_cell_models") or {})
                   .get("yosys_io_hierarchy"))
        entries = profile.get("files") if isinstance(profile, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError(
                "pdk_binding.functional_cell_models.yosys_io_hierarchy "
                "is required for Sky130 pad elaboration")
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("path") \
                    or not entry.get("sha256"):
                raise ValueError(
                    "Sky130 pad model entries require path and sha256")
            path = entry["path"]
            if not os.path.isfile(path):
                raise ValueError("Sky130 pad model is missing: " + path)
            actual = _hash_input_file(path)
            if not actual or actual["sha256"].lower() != str(
                    entry["sha256"]).lower():
                raise ValueError(
                    "Sky130 pad model SHA-256 verification failed: " + path)
            files.append(path)
            _ACTIVE_MODEL_PATHS.add(os.path.realpath(path))
        defines = profile.get("defines", [])
        if not isinstance(defines, list) or any(
                not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item))
                for item in defines):
            raise ValueError(
                "Sky130 pad model defines must be simple identifiers")
        _ACTIVE_VERILOG_DEFINES = [str(item) for item in defines]
        bridges = profile.get("input_bridges", [])
        if not isinstance(bridges, list):
            raise ValueError("Sky130 pad input_bridges must be a list")
        for bridge in bridges:
            if not isinstance(bridge, dict) or any(
                    not _is_ident(bridge.get(field))
                    for field in ("module", "external_port", "internal_port")):
                raise ValueError(
                    "Sky130 pad input_bridges require safe module and port names")
        _ACTIVE_INPUT_BRIDGES = [dict(item) for item in bridges]
        _ACTIVE_MODEL_EVIDENCE = {
            "source": "pdk_binding.functional_cell_models.yosys_io_hierarchy",
            "binding_sha256": binding.get("binding_sha256"),
            "files": entries,
            "defines": _ACTIVE_VERILOG_DEFINES,
            "input_bridges": _ACTIVE_INPUT_BRIDGES,
        }
    if not files:
        raise ValueError("no RTL provided")
    return files


def _elaborate_json(top, files, preserve_hierarchy=False):
    reads = rtl_frontend.yosys_read_block(files, top)
    if _ACTIVE_VERILOG_DEFINES:
        flags = " ".join("-D" + item for item in _ACTIVE_VERILOG_DEFINES)
        reads = "\n".join(
            line.replace("read_verilog ", f"read_verilog {flags} ", 1)
            if line.startswith("read_verilog ") else line
            for line in reads.splitlines())
    js = os.path.join(_OUTPUT_DIR, "netlist.json")
    # By default we flatten so crossings are analyzed on a single flat netlist.
    # preserve_hierarchy keeps module boundaries so crossing endpoints retain
    # hierarchical instance paths (block-level / SoC CDC review).
    _flat = "" if preserve_hierarchy else "flatten\n"
    # Lower inferred memories (FIFO/RAM arrays) to ordinary flops BEFORE the
    # state census. Left as $mem_v2/$memwr_v2/$memrd cells they were rejected
    # as "unsupported asynchronous/latch state" on a single-clock uart_apb.
    # memory_map turns every storage bit into a $dff clocked by its WRITE-port
    # clock, so memory state is counted in the domain that actually writes it.
    # Any
    # $mem*/memrd/memwr survivor (e.g. an unmappable async write port) is
    # still refused, by name, in the census. memory_collect (not the full
    # `memory -nomap`) is used so memory_dff does not absorb the design's own
    # read-data registers into the memory and rename them: every RTL flop
    # keeps its name and clock exactly as before.
    _mem = "memory_collect\nmemory_map\n"
    script = (f"{reads}\nhierarchy -check -top {top}\nproc\n{_mem}{_flat}"
              f"write_json {js}\n")
    sp = os.path.join(_OUTPUT_DIR, "cdc.ys")
    open(sp, "w").write(script)
    _save_run_command(["yosys", "-q", "-s", sp])
    proc = subprocess.run(["yosys", "-q", "-s", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    open(os.path.join(_OUTPUT_DIR, "yosys_cdc.log"), "w").write(proc.stdout + "\n" + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError("yosys elaboration failed: " + proc.stderr[-1500:])
    return json.load(open(js))


# Yosys sequential cell types. Async-reset/set flavors carry an ARST/SET/CLR
# control input in addition to CLK -- those are the reset-carrying flops RDC cares
# about; the plain $dff/$dffe types are reset-free (or sync-reset via $sdff).
_FF_TYPES = ("$dff", "$adff", "$sdff", "$dffe", "$adffe", "$sdffe",
             "$aldff", "$aldffe", "$dffsr", "$dffsre", "$sr")
_ASYNC_RESET_PORTS = ("ARST", "SET", "CLR", "ALOAD")


def _extract_flops(mod):
    """Extract every sequential cell as a dict of bit-tuples for CLK/D/Q and any
    async reset/set control net. Returns (flops, cell_count). A flop with an async
    control port is tagged has_async_reset with its reset net bits."""
    cells = mod.get("cells", {})
    flops = []
    for cname, c in cells.items():
        ctype = c.get("type", "")
        if not ctype.startswith(_FF_TYPES):
            continue
        conns = c.get("connections", {})
        rst_bits = ()
        rst_port = None
        for p in _ASYNC_RESET_PORTS:
            if p in conns and conns[p]:
                rst_bits = tuple(conns[p])
                rst_port = p
                break
        flops.append({
            "name": cname, "type": ctype,
            "clk": tuple(conns.get("CLK", [])),
            "d": tuple(conns.get("D", [])),
            "q": tuple(conns.get("Q", [])),
            "rst": rst_bits, "rst_port": rst_port,
            "has_async_reset": bool(rst_bits),
            "parameters": c.get("parameters") or {},
        })
    return flops, len(cells)


def _is_memory_cell_type(ctype):
    normalized = str(ctype).lower().replace("_", "")
    return (normalized.startswith("$mem") or "memrd" in normalized
            or "memwr" in normalized)


def _unsupported_state_cells(mod):
    unsupported = []
    for name, cell in (mod.get("cells") or {}).items():
        ctype = str(cell.get("type", ""))
        normalized = ctype.lower().replace("_", "")
        if (normalized.startswith(("$dlatch", "$adlatch", "$sr")) or
                _is_memory_cell_type(ctype)):
            unsupported.append({"name": name, "type": ctype})
    return unsupported


def _bit_domain_index(mod, domain_map):
    """Map each net BIT to its domain by matching netnames against domain_map keys."""
    bit_domain = {}
    for nname, ninfo in mod.get("netnames", {}).items():
        dom = domain_map.get(nname)
        if dom:
            for b in ninfo.get("bits", []):
                bit_domain[b] = dom
    for bridge in _ACTIVE_INPUT_BRIDGES:
        for cell in (mod.get("cells") or {}).values():
            if cell.get("type") != bridge["module"]:
                continue
            connections = cell.get("connections") or {}
            external = connections.get(bridge["external_port"], [])
            internal = connections.get(bridge["internal_port"], [])
            domains = {bit_domain[bit] for bit in external if bit in bit_domain}
            if len(domains) == 1:
                domain = next(iter(domains))
                for bit in internal:
                    if isinstance(bit, int):
                        bit_domain[bit] = domain
    return bit_domain


def _bit_net_index(mod):
    """Map each net BIT to (netname, bit_index, net_width).

    Needed to reassemble per-bit crossings into the BUS they belong to. Yosys
    numbers bits globally, so a bit alone cannot tell you which signal it is part
    of; without this index a 32-bit bus is indistinguishable from 32 unrelated
    1-bit crossings, which is exactly the misreading this module exists to stop.

    Public (non `$`-prefixed) names win: an auto-generated alias for the same bit
    carries no design intent and would make the grouping unstable between runs.
    """
    idx = {}
    for nname, ninfo in mod.get("netnames", {}).items():
        bits = ninfo.get("bits", [])
        w = len(bits)
        for i, b in enumerate(bits):
            if not isinstance(b, int):
                continue  # constant driver ('0'/'1'), not a net bit
            prev = idx.get(b)
            if prev is None or (prev[0].startswith("$") and not nname.startswith("$")):
                idx[b] = (nname, i, w)
    return idx


def _formal_input_bridge_pairs(mod):
    bit_net = _bit_net_index(mod)
    ports = mod.get("ports") or {}
    input_bits = {
        bit for port in ports.values() if port.get("direction") == "input"
        for bit in port.get("bits", []) if isinstance(bit, int)
    }
    pairs = []
    for bridge in _ACTIVE_INPUT_BRIDGES:
        for name, cell in (mod.get("cells") or {}).items():
            if cell.get("type") != bridge["module"]:
                continue
            connections = cell.get("connections") or {}
            external = connections.get(bridge["external_port"], [])
            internal = connections.get(bridge["internal_port"], [])
            for external_bit, internal_bit in zip(external, internal):
                if external_bit not in input_bits:
                    continue
                if external_bit not in bit_net or internal_bit not in bit_net:
                    continue
                external_name, external_index, external_width = bit_net[external_bit]
                internal_name, internal_index, internal_width = bit_net[internal_bit]
                external_ref = (external_name if external_width == 1 else
                                f"{external_name}[{external_index}]")
                internal_ref = (internal_name if internal_width == 1 else
                                f"{internal_name}[{internal_index}]")
                pairs.append({
                    "instance": name,
                    "external": external_ref.lstrip("\\"),
                    "internal": internal_ref.lstrip("\\"),
                    "module": bridge["module"],
                })
    return pairs


def _combinational_fanout(mod):
    """Return conservative bit-to-bit fanout through combinational cells only."""
    fanout = {}
    for cell in mod.get("cells", {}).values():
        if str(cell.get("type", "")).startswith(_FF_TYPES):
            continue
        directions = cell.get("port_directions", {})
        connections = cell.get("connections", {})
        bridges = [
            bridge for bridge in _ACTIVE_INPUT_BRIDGES
            if cell.get("type") == bridge["module"]
        ]
        if bridges:
            for bridge in bridges:
                external = connections.get(bridge["external_port"], [])
                internal = connections.get(bridge["internal_port"], [])
                for source, destination in zip(external, internal):
                    if isinstance(source, int) and isinstance(destination, int):
                        fanout.setdefault(source, set()).add(destination)
            continue
        inputs = {
            bit for port, bits in connections.items()
            if directions.get(port) in ("input", "inout")
            for bit in bits if isinstance(bit, int)
        }
        outputs = {
            bit for port, bits in connections.items()
            if directions.get(port) in ("output", "inout")
            for bit in bits if isinstance(bit, int)
        }
        for bit in inputs:
            fanout.setdefault(bit, set()).update(outputs)
    return fanout


def _reachable_bits(seeds, fanout):
    reached = {bit for bit in seeds if isinstance(bit, int)}
    pending = list(reached)
    while pending:
        bit = pending.pop()
        for nxt in fanout.get(bit, ()):
            if nxt not in reached:
                reached.add(nxt)
                pending.append(nxt)
    return reached


def _flop_lanes(flops):
    """Split vector Yosys flops into bit-level sequential stages."""
    lanes = []
    for flop in flops:
        width = max(len(flop["d"]), len(flop["q"]))
        for index in range(width):
            d_bit = flop["d"][index] if index < len(flop["d"]) else None
            q_bit = flop["q"][index] if index < len(flop["q"]) else None
            lanes.append({
                "name": flop["name"],
                "stage": f"{flop['name']}[{index}]",
                "index": index,
                "d": d_bit,
                "q": q_bit,
                "domain": flop.get("domain") or flop.get("clk_domain"),
                "rst": flop["rst"],
                "has_async_reset": flop["has_async_reset"],
            })
    return lanes


def _lanes_reached(lanes, reached, domain):
    return [
        lane for lane in lanes
        if lane["domain"] == domain and lane["d"] in reached
    ]


def _measure_primary_input_obligations(mod, flops, obligations):
    """Structurally reconcile authoritative asynchronous input declarations.

    The legacy CDC walk starts at flop Q pins, so primary inputs are outside its
    producer index. This companion census starts at top-level input bits, walks
    combinational logic up to the first destination-domain register, and then
    checks the required sequential structure without treating a declaration as
    measured evidence.
    """
    if not obligations:
        return [], []

    ports = mod.get("ports", {})
    fanout = _combinational_fanout(mod)
    bit_net = _bit_net_index(mod)
    lanes = _flop_lanes(flops)
    measured = []
    by_signal = {}

    # REGISTERS A DECLARED QUALIFIED-CAPTURE BUS SAYS A QUALIFIER GATES.
    #
    # The "clean 2-flop synchronizer" recognizer below refuses any first stage
    # that has a second consumer, because an unexplained extra consumer of a
    # not-yet-settled flop is exactly the shape it exists to catch. But sharing
    # the qualifier's synchronizer with a qualified capture is a DECLARED
    # structure, not an unexplained one: the map itself says this bus is
    # captured under this qualifier. Measured on a real SoC, that legitimate
    # second consumer made `len(direct) == 1` false and the tool reported a
    # textbook, plainly-present 2-flop chain as MISSING -- a recognizer gap, not
    # a design defect.
    #
    # So consumers the map DECLARED are accounted for here and do not disqualify
    # the chain. Everything undeclared still does: this narrows the exemption to
    # exactly what the caller took responsibility for, and never widens it.
    capture_stages_by_qualifier = {}
    capture_names_by_qualifier = {}
    for other in obligations:
        if other.get("kind") != "qualified_capture_bus":
            continue
        qualifier = other.get("qualifier")
        if not qualifier:
            continue
        data_port = ports.get(other["signal"]) or {}
        sinks = []
        for bit in data_port.get("bits", []):
            if not isinstance(bit, int):
                continue
            sinks.extend(_lanes_reached(
                lanes, _reachable_bits([bit], fanout), other["to_domain"]))
        capture_stages_by_qualifier.setdefault(qualifier, set()).update(
            lane["stage"] for lane in sinks)
        capture_names_by_qualifier.setdefault(qualifier, set()).update(
            lane["name"] for lane in sinks)

    work_items = sorted(
        enumerate(obligations),
        key=lambda item: item[1]["kind"] == "qualified_capture_bus")
    for order, obligation in work_items:
        signal = obligation["signal"]
        port = ports.get(signal) or {}
        port_bits = [
            bit for bit in port.get("bits", []) if isinstance(bit, int)
        ]
        record = dict(obligation)
        record.update({
            "measured": False,
            "port_present": port.get("direction") == "input",
            "measured_width": len(port_bits),
            "evidence_basis": "elaborated_netlist_primary_input_trace",
            "_order": order,
        })
        if not record["port_present"] or len(port_bits) != obligation["width"]:
            record["reason"] = (
                f"input port '{signal}' is absent or has width {len(port_bits)}; "
                f"the domain map requires width {obligation['width']}")
            measured.append(record)
            by_signal[signal] = record
            continue

        destination = obligation["to_domain"]
        if obligation["kind"] == "control_synchronizer":
            first_reach = _reachable_bits(port_bits, fanout)
            candidates = _lanes_reached(lanes, first_reach, destination)
            downstream_d = set()
            for source in candidates:
                downstream_d.update(
                    lane["d"] for lane in candidates
                    if lane["stage"] != source["stage"]
                    and lane["d"] in _reachable_bits([source["q"]], fanout))
            first = [lane for lane in candidates if lane["d"] not in downstream_d]
            first_q = [lane["q"] for lane in first
                       if isinstance(lane["q"], int)]
            first_stages = {lane["stage"] for lane in first}
            declared_capture_stages = capture_stages_by_qualifier.get(
                signal, set())
            declared_capture_names = capture_names_by_qualifier.get(
                signal, set())
            second = []
            complete_first = []
            declared_capture_consumers = set()
            for source in first:
                reached = _reachable_bits([source["q"]], fanout)
                direct = [lane for lane in lanes
                          if lane["domain"] == destination and
                          lane["stage"] not in first_stages and
                          lane["d"] in reached]
                # Split the first stage's consumers into the synchronizer's own
                # second stage and the capture registers the map DECLARED this
                # signal qualifies. Anything left over is unaccounted for and
                # still disqualifies the chain.
                sync_direct = [lane for lane in direct
                               if lane["stage"] not in declared_capture_stages]
                declared_capture_consumers.update(
                    lane["stage"] for lane in direct
                    if lane["stage"] in declared_capture_stages)
                unaccounted = [lane for lane in lanes
                               if lane["stage"] != source["stage"] and
                               lane["stage"] not in declared_capture_stages and
                               lane["d"] in reached]
                control_uses = []
                for flop in flops:
                    if flop["name"] in declared_capture_names:
                        continue
                    cell = (mod.get("cells") or {}).get(flop["name"], {})
                    for port, bits in (cell.get("connections") or {}).items():
                        if (cell.get("port_directions") or {}).get(port) != "input":
                            continue
                        for bit_index, bit in enumerate(bits):
                            if bit in reached and port != "D":
                                control_uses.append((flop["name"], port, bit_index))
                output_use = any(
                    bit in reached for port in ports.values()
                    if port.get("direction") in ("output", "inout")
                    for bit in port.get("bits", []))
                if (len(sync_direct) == 1 and unaccounted == sync_direct and
                        not control_uses and not output_use):
                    complete_first.append(source)
                    second.extend(sync_direct)
            record.update({
                "first_stage": sorted({lane["stage"] for lane in first}),
                "second_stage": sorted({lane["stage"] for lane in second}),
                "declared_capture_consumers": sorted(
                    declared_capture_consumers),
                "stage_count": 2 if first and second else (1 if first else 0),
                "_first_stage_q_bits": [
                    lane["q"] for lane in first
                    if isinstance(lane["q"], int)
                ],
                "_synchronized_q_bits": [
                    lane["q"] for lane in second
                    if isinstance(lane["q"], int)
                ],
            })
            record["measured"] = bool(first) and len(complete_first) == len(first)
            if not record["measured"]:
                record["reason"] = (
                    f"'{signal}' did not reach a two-stage synchronizer in "
                    f"destination domain '{destination}'")

        elif obligation["kind"] == "reset_synchronizer":
            reset_reach = _reachable_bits(port_bits, fanout)
            reset_lanes = [
                lane for lane in lanes
                if lane["domain"] == destination and lane["has_async_reset"]
                and any(bit in reset_reach for bit in lane["rst"])
            ]
            reset_stage_ids = {lane["stage"] for lane in reset_lanes}
            edges = {stage: set() for stage in reset_stage_ids}
            for source in reset_lanes:
                if not isinstance(source["q"], int):
                    continue
                for target in reset_lanes:
                    if (target["stage"] != source["stage"]
                            and target["d"] == source["q"]):
                        edges[source["stage"]].add(target["stage"])

            def depth(stage, active):
                if stage in active:
                    return 0
                return 1 + max(
                    (depth(nxt, active | {stage}) for nxt in edges[stage]),
                    default=0)

            stage_count = max(
                (depth(stage, set()) for stage in reset_stage_ids), default=0)
            chain_stage_ids = {
                stage for source, targets in edges.items() if targets
                for stage in ({source} | targets)
            }
            bypass_reset_stages = sorted(reset_stage_ids - chain_stage_ids)
            record.update({
                "reset_stages": sorted(reset_stage_ids),
                "stage_count": stage_count,
                "bypass_reset_stages": bypass_reset_stages,
            })
            predecessor_stages = {
                target for targets in edges.values() for target in targets
            }
            terminal_lanes = [
                lane for lane in reset_lanes
                if lane["stage"] in predecessor_stages
                and not edges[lane["stage"]]
            ]
            record["synchronized_signals"] = sorted({
                bit_net[lane["q"]][0].lstrip("\\")
                for lane in terminal_lanes if lane["q"] in bit_net
            })
            record["measured"] = stage_count >= 2 and not bypass_reset_stages
            if not record["measured"]:
                if bypass_reset_stages:
                    record["reason"] = (
                        f"'{signal}' directly reaches async-reset stage(s) "
                        f"outside a reset synchronizer chain in "
                        f"'{destination}': {', '.join(bypass_reset_stages)}")
                else:
                    record["reason"] = (
                        f"'{signal}' did not reach a two-stage async-assert, "
                        f"sync-deassert reset synchronizer in '{destination}'")

        elif obligation["kind"] == "qualified_capture_bus":
            captures = []
            captured_bits = []
            for index, bit in enumerate(port_bits):
                reached = _reachable_bits([bit], fanout)
                sinks = _lanes_reached(lanes, reached, destination)
                if sinks:
                    captured_bits.append(index)
                    captures.extend(sinks)
            qualifier = by_signal.get(obligation.get("qualifier"), {})
            qualifier_reach = _reachable_bits(
                qualifier.get("_synchronized_q_bits", []), fanout)
            # WHICH STAGE ACTUALLY GATES THE CAPTURE IS THE WHOLE QUESTION. A
            # capture enabled from the SECOND (settled) synchronizer stage is
            # the structure the map declares. A capture enabled from the FIRST
            # stage samples on an output that has not yet resolved, so the
            # coherency the qualifier is supposed to provide is not actually
            # provided. Both cases used to produce the same opaque "did not show
            # a complete capture" message, which reads like a measurement
            # failure rather than the finding it is.
            first_stage_reach = _reachable_bits(
                qualifier.get("_first_stage_q_bits", []), fanout)
            per_bit_qualified = []
            per_bit_first_stage_gated = []
            for index, bit in enumerate(port_bits):
                reached = _reachable_bits([bit], fanout)
                sinks = _lanes_reached(lanes, reached, destination)
                if not sinks:
                    continue
                if all(lane["d"] in qualifier_reach for lane in sinks):
                    per_bit_qualified.append(index)
                elif all(lane["d"] in first_stage_reach for lane in sinks):
                    per_bit_first_stage_gated.append(index)
            width = obligation["width"]
            if len(set(per_bit_qualified)) == width:
                gate_stage = "second"
            elif len(set(per_bit_qualified) | set(per_bit_first_stage_gated)) \
                    == width and per_bit_first_stage_gated:
                gate_stage = "first"
            else:
                gate_stage = None
            record.update({
                "captured_bits": sorted(set(captured_bits)),
                "capture_registers": sorted({
                    lane["name"] for lane in captures
                }),
                "qualifier": obligation.get("qualifier"),
                "qualifier_measured": bool(
                    qualifier.get("measured") and
                    len(set(per_bit_qualified)) == width),
                "qualifier_gate_stage": gate_stage,
                "bus_coherency": "qualified_capture",
                "per_bit_synchronizers": 0,
            })
            record["measured"] = (
                len(set(captured_bits)) == width
                and record["qualifier_measured"]
            )
            if not record["measured"]:
                if gate_stage == "first":
                    record["reason"] = (
                        f"'{signal}' is captured under "
                        f"'{obligation.get('qualifier')}', but the enable comes "
                        f"from the FIRST synchronizer stage, whose output has "
                        f"not resolved yet. A qualifier only makes a bus "
                        f"coherent once it is settled: gate the capture from "
                        f"the SECOND stage, or declare a different coherency "
                        f"scheme. This is a design finding, not an unmeasured "
                        f"crossing")
                elif not qualifier.get("measured"):
                    record["reason"] = (
                        f"'{signal}' is declared qualified by "
                        f"'{obligation.get('qualifier')}', whose own "
                        f"synchronizer was not measured; the bus cannot be "
                        f"credited while its qualifier is unproven")
                else:
                    record["reason"] = (
                        f"'{signal}' did not show a complete {width}-bit "
                        f"capture qualified by synchronized "
                        f"'{obligation.get('qualifier')}'")

        measured.append(record)
        by_signal[signal] = record

    measured.sort(key=lambda item: item["_order"])
    for record in measured:
        record.pop("_order", None)
        record.pop("_synchronized_q_bits", None)
        record.pop("_first_stage_q_bits", None)
    missing = [record for record in measured if not record["measured"]]
    return measured, missing


def _group_crossings_into_buses(crossings, protocols):
    """Reassemble per-bit crossings into buses and judge multi-bit safety.

    THE POINT OF THIS FUNCTION. Per-bit analysis reports an N-bit crossing whose
    N bits each carry their own 2-flop synchronizer as N synchronized crossings
    and zero violations. That is backwards: independently synchronizing the bits
    of a multi-bit value is not a fix, it IS the defect. Each bit resolves its
    own metastability on its own cycle, so the receiver can latch a combination
    of old and new bits -- a word that never existed in the source domain.

    A multi-bit crossing is only safe when something makes the bits coherent:
      * gray      -- at most one bit changes per source cycle, so no combination
                     of old/new bits is ever wrong (counters, FIFO pointers).
      * handshake -- data is held stable while a synchronized req/ack qualifier
                     travels, so the receiver samples a settled word.
      * mux/qualifier -- the destination only samples when a synchronized enable
                     says the word is stable.
      * fifo      -- an async FIFO with gray-coded pointers.
    None of those is structurally distinguishable from an unprotected bus by
    counting flops, so the scheme is DECLARED by the caller and recorded as an
    assumption. An UNDECLARED multi-bit crossing is reported as unprotected --
    fail-closed, because assuming protection nobody stated is how this class of
    bug reaches silicon.
    """
    buses = {}
    for c in crossings:
        key = (c.get("signal") or c["from"], c["from_domain"], c["to_domain"])
        b = buses.get(key)
        if b is None:
            b = buses[key] = {
                "signal": c.get("signal") or c["from"],
                "from_domain": c["from_domain"], "to_domain": c["to_domain"],
                "net_width": c.get("net_width", 1),
                "bits": [], "crossings": [],
            }
        if c.get("bit") is not None:
            b["bits"].append(c["bit"])
        b["crossings"].append(c)

    out = []
    for b in buses.values():
        b["bits"] = sorted(set(b["bits"]))
        b["crossing_bits"] = len(b["crossings"])
        # FAIL-CLOSED ON UNRESOLVED IDENTITY. If any crossing in this group could
        # not be tied back to a named net bit, the DISTINCT-BIT count is unknown,
        # not one. Trusting it would collapse a real N-bit bus to width 1 and
        # report the exact defect this function exists to catch as clean -- the
        # same "a check that examined nothing reports no findings" failure that
        # shows up everywhere else in this flow. So when identity is unresolved
        # we fall back to the NUMBER OF CROSSINGS as a conservative width: it can
        # overcount (one bit fanning out to several destinations) but it cannot
        # silently undercount a wide bus to 1.
        b["net_identity_resolved"] = all(
            c.get("bit") is not None for c in b["crossings"])
        if b["net_identity_resolved"]:
            # Width that actually crosses -- NOT the declared net width. A 32-bit
            # net of which 2 bits cross is a 2-bit coherency problem.
            b["width"] = max(len(b["bits"]), 1)
        else:
            b["width"] = max(len(b["bits"]), b["crossing_bits"], 1)
            b["width_basis"] = "crossing_count_upper_bound_identity_unresolved"
        b["multi_bit"] = b["width"] > 1
        decl = (protocols or {}).get(b["signal"]) or {}
        scheme = str(decl.get("scheme", "")).strip().lower() or None
        b["declared_scheme"] = scheme
        b["scheme_source"] = "caller_declared" if scheme else "undeclared"
        b["protected"] = scheme in ("gray", "handshake", "mux", "qualifier",
                                    "fifo", "async_fifo")
        b["unprotected_multi_bit"] = b["multi_bit"] and not b["protected"]
        if b["unprotected_multi_bit"]:
            b["why"] = (
                f"{b['width']} bits of '{b['signal']}' cross from "
                f"{b['from_domain']} to {b['to_domain']} with no declared "
                f"coherency scheme. Per-bit synchronizers do NOT make a "
                f"multi-bit value coherent: the bits settle on different "
                f"destination cycles, so the receiver can assemble a word that "
                f"never existed in the source domain. Declare gray/handshake/"
                f"qualifier/fifo, or restructure the crossing.")
            if not b["net_identity_resolved"]:
                b["why"] += (
                    " NOTE: bit identity could not be resolved for this group, "
                    "so the width is the crossing count (an upper bound) and the "
                    "signal name is the source cell. Reported as multi-bit "
                    "because an unknown width must not read as one.")
        out.append(b)
    out.sort(key=lambda x: (-x["width"], x["signal"]))
    return out


def _not_assessable_cde(kind, top, files, reason, cell_count):
    """FAIL-CLOSED not-assessable envelope. When the tool cannot actually assess a
    crossing (elaboration produced zero sequential cells, so there is nothing to
    check), it MUST NOT report status=completed -- that would launder a
    non-assessment into a pass-shaped result. A downstream reviewer/grader reads
    status=failed + verdict=not_assessable as 'this gate did not run', never as a
    clean signoff. See the DX-34 incident: a zero-flop VHDL elaboration previously
    returned completed/not_assessable and looked benign."""
    return _cde(
        objective=f"{kind} signoff of {top}",
        status="failed",
        results={"crossings": {"value": 0, "unit": "count"},
                 "sequential_cells_extracted": {"value": 0, "unit": "count"},
                 "cells_seen": {"value": cell_count, "unit": "count"}},
        signoff={"verdict": "not_assessable"},
        inputs_ref={"rtl_files": files},
        assumptions=["fail-closed: not_assessable is NOT a pass"],
        validation={"verdict": "not_assessable", "note": reason},
        error=reason,
        provenance={"yosys": _yosys_version(), "log": "yosys_cdc.log"},
    )


_WAIVER_AUTH_DISPOSITION = "accepted_with_waiver"
_WAIVER_AUTH_GATE_TYPE = "cdc_rdc"
_WAIVER_AUTH_SHA_BASIS = (
    "sha256(json.dumps(ruling without 'sha256', sort_keys=True, "
    "separators=(',',':')))"
)


def _ruling_content_sha256(ruling):
    """Canonical ruling hash: sorted-key compact JSON with `sha256` removed.

    Always recomputed. The field stored beside the ruling is the claim under
    test, never the authority -- a ledger edit that forgot to restamp it, or a
    stamp that was edited to fit an altered body, both have to fail here."""
    import hashlib
    body = {k: v for k, v in ruling.items() if k != "sha256"}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _instance_prefix(cell_name):
    """Hierarchical instance that owns *cell_name*.

    Yosys hierarchy components are `\\`-escaped and auto-generated leaf names
    begin with `$` and may themselves contain dots (`$auto$proc_dlatch.cc:467:
    ...`), so a plain rsplit on "." would cut inside the leaf name. The split
    point is the last dot that actually BEGINS a new component."""
    name = str(cell_name)
    cut = -1
    for i, ch in enumerate(name):
        if ch == "." and i + 1 < len(name) and name[i + 1] in ("\\", "$"):
            cut = i
    return name[:cut] if cut >= 0 else name


def _derive_unsupported_census(unsupported):
    """Re-derive the unsupported-state census from THIS run's netlist.

    Never reads a recorded census artifact: the scope a ruling is allowed to
    accept has to be measured from the netlist in front of us, or a stale
    artifact could silently widen an acceptance the human never granted."""
    counts = {}
    types = set()
    for cell in unsupported:
        ctype = str(cell.get("type", ""))
        types.add(ctype)
        key = (ctype, _instance_prefix(cell.get("name", "")))
        counts[key] = counts.get(key, 0) + 1
    families = [{"type": t, "instance": inst, "cells": n}
                for (t, inst), n in sorted(counts.items())]
    modules = sorted({inst.rsplit(".", 1)[-1].lstrip("\\")
                      for (_t, inst) in counts})
    return {
        "cell_count": len(unsupported),
        "cell_types": sorted(types),
        "instance_families": families,
        "instance_family_count": len(families),
        "module_definitions": modules,
        "module_definition_count": len(modules),
    }


def _match_waiver_authorization(params, top, files, unsupported):
    """Match a named-human ledger ruling against this run's measured scope.

    Returns ``(ruling, proof)`` only when the ruling's identity, hash, scope and
    every enumerated condition match exactly; otherwise ``(None, reason)`` so the
    caller keeps its existing fail-closed behaviour. Nothing is taken on the
    caller's word: the ruling hash, the source-RTL hash, the domain-map hash and
    the unsupported-state census are all recomputed here. The ledger is only ever
    read -- this tool never writes a ruling."""
    import fnmatch

    req = params.get("waiver_authorization")
    if not isinstance(req, dict):
        return None, "no waiver_authorization supplied"
    ledger_path = req.get("ledger")
    ruling_id = req.get("ruling_id")
    expected_sha = str(req.get("sha256") or "").lower()
    attempt_path = str(req.get("attempt_path") or "")
    if not ledger_path or not ruling_id or not expected_sha:
        return None, "waiver_authorization requires ledger, ruling_id and sha256"

    try:
        with open(ledger_path) as _fh:
            ledger = json.load(_fh)
    except Exception as exc:
        return None, f"waiver ledger unreadable: {exc}"
    rulings = ledger.get("rulings")
    if not isinstance(rulings, list):
        return None, "waiver ledger carries no rulings list"
    matches = [r for r in rulings
               if isinstance(r, dict) and r.get("ruling_id") == ruling_id]
    if len(matches) != 1:
        return None, f"ruling {ruling_id} is not uniquely present in the ledger"
    ruling = matches[0]

    computed = _ruling_content_sha256(ruling)
    if computed != str(ruling.get("sha256") or "").lower():
        return None, "recomputed ruling hash does not match its recorded sha256"
    if computed != expected_sha:
        return None, "recomputed ruling hash does not match the requested sha256"

    superseding = sorted({str(r.get("ruling_id")) for r in rulings
                          if isinstance(r, dict)
                          and ruling_id in (r.get("supersedes") or [])})
    if superseding:
        return None, f"ruling {ruling_id} is superseded by {superseding}"

    # Every condition the ruling binds -- including its disposition and the
    # accepted unsupported-state census -- lives inside the ``conditions``
    # block. Read them only from there so a stray root-level key can never
    # stand in for an authorized condition.
    conditions = ruling.get("conditions")
    if not isinstance(conditions, dict):
        return None, "ruling carries no conditions block"

    if ruling.get("gate_type") != _WAIVER_AUTH_GATE_TYPE:
        return None, "ruling gate_type is not cdc_rdc"
    if conditions.get("disposition") != _WAIVER_AUTH_DISPOSITION:
        return None, "ruling disposition is not accepted_with_waiver"
    if ruling.get("source") != "human":
        return None, "ruling source is not a human action"
    if not str(ruling.get("authorized_by") or "").strip():
        return None, "ruling names no human authorizer"
    if not str(ruling.get("rule_deck_version") or "").strip():
        return None, "ruling carries no rule_deck_version"

    scope = str(ruling.get("scope") or "")
    if not scope or not attempt_path:
        return None, "ruling scope or attempt_path is missing"
    if not fnmatch.fnmatch(attempt_path, scope):
        return None, f"attempt path {attempt_path!r} is outside ruling scope {scope!r}"

    for field in ("campaign", "design", "task_id", "task_uuid", "attempt_basis"):
        want = conditions.get(field)
        if not want or str(want) != str(req.get(field) or ""):
            return None, f"ruling condition {field} does not match this run"

    staged = {os.path.realpath(str(f)) for f in (files or [])}
    source_rtl = str(req.get("source_rtl") or "")
    if source_rtl and os.path.realpath(source_rtl) not in staged:
        return None, "source_rtl is not one of the RTL files staged for this run"
    spec_domain_map = str(req.get("spec_domain_map") or "")
    if not spec_domain_map:
        return None, "waiver_authorization requires spec_domain_map"
    hashes = {}
    for field, target in (("source_rtl_sha256", source_rtl),
                          ("domain_map_sha256", spec_domain_map)):
        want = str(conditions.get(field) or "").lower()
        if not want:
            return None, f"ruling condition {field} is missing"
        digest = _hash_input_file(target) if target else None
        if not digest:
            return None, f"cannot hash {field} source {target!r}"
        if digest["sha256"].lower() != want:
            return None, f"{field} does not match the authorized hash"
        hashes[field] = {"path": target, **digest}

    # The ruling binds the authoritative declared-intent domain map, while the
    # run consumes its flat {port: clock} projection. Prove the consumed input is
    # exactly that projection so neither artifact can drift behind the other.
    # By the time a scenario runs, ``params["domain_map"]`` has been replaced by
    # the flat {port: clock} mapping itself and the file it was read from is
    # recorded on the normalized contract. Resolve the path from the contract so
    # the projection is verified against the artifact on disk rather than against
    # a stringified dict, and stay fail-closed when no hashable file backs it.
    _contract = params.get("_domain_map_contract")
    _raw_map = params.get("domain_map")
    if isinstance(_raw_map, str):
        consumed_map = _raw_map
    elif isinstance(_contract, dict):
        consumed_map = str(_contract.get("source") or "")
    else:
        consumed_map = ""
    if not consumed_map or not os.path.isfile(consumed_map):
        return None, ("consumed domain_map is not backed by a readable file "
                      f"that can be hashed (resolved {consumed_map!r})")
    try:
        with open(spec_domain_map) as _fh:
            _spec = json.load(_fh)
        with open(consumed_map) as _fh:
            _flat = json.load(_fh)
        projection = {str(c.get("port")): str(c.get("name"))
                      for c in (_spec.get("clocks") or [])}
    except Exception as exc:
        return None, f"cannot verify domain_map projection: {exc}"
    if not projection or projection != _flat:
        return None, ("domain_map is not the authorized projection of "
                      "spec_domain_map")
    consumed_digest = _hash_input_file(consumed_map)
    hashes["domain_map_projection"] = {
        "path": consumed_map,
        "verified": True,
        "clock_count": len(projection),
        **(consumed_digest or {}),
    }

    census = _derive_unsupported_census(unsupported)
    accepted = conditions.get("accepted_unsupported_state")
    if not isinstance(accepted, dict):
        return None, "ruling carries no accepted_unsupported_state scope"
    if census["cell_types"] != [accepted.get("cell_type")]:
        return None, (f"observed unsupported state types {census['cell_types']} "
                      f"exceed the accepted type {accepted.get('cell_type')!r}")
    for key, observed in (("cell_count", census["cell_count"]),
                          ("instance_families", census["instance_family_count"]),
                          ("module_definitions", census["module_definition_count"])):
        if observed != accepted.get(key):
            return None, (f"observed {key} {observed} differs from the accepted "
                          f"{accepted.get(key)}")

    proof = {
        "ruling_id": ruling_id,
        "ledger": str(ledger_path),
        "sha256_recomputed": computed,
        "sha256_basis": _WAIVER_AUTH_SHA_BASIS,
        "authorized_by": ruling.get("authorized_by"),
        "approved_at": ruling.get("approved_at"),
        "rule_deck_version": ruling.get("rule_deck_version"),
        "disposition": conditions.get("disposition"),
        "gate_type": ruling.get("gate_type"),
        "scope": scope,
        "attempt_path": attempt_path,
        "top": top,
        "supersedes": list(ruling.get("supersedes") or []),
        "conditions_verified": sorted(conditions.keys()),
        "hashes_recomputed": hashes,
        "observed_unsupported_state": census,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return ruling, proof


def _waiver_accepted_cde(kind, top, files, ruling, proof):
    """Disclosed-acceptance envelope for a gate a named human accepted.

    This is a PROCESS waiver, not a clean signoff. The structural families bind
    at zero because the ruling removed them from the unwaived population -- each
    one is annotated `measured: false` and every accepted gap, limitation and
    evidence path the ruling named is restated here verbatim, so a reader cannot
    mistake an accepted absence for a proven absence."""
    results, checks, signoff = _canonical_cdc_evidence(
        [], [], [], 0, False, {}, [],
        gate_scope="cdc_accepted_with_waiver")
    ruling_id = proof["ruling_id"]
    # Accepted-scope keys are bound inside the ruling's ``conditions`` block;
    # read them from there so the disclosure restates what was authorized.
    _cond = ruling.get("conditions") or {}
    for _name in _CDC_REQUIRED_STRUCTURAL_FAMILIES:
        _entry = signoff.get(_name)
        if isinstance(_entry, dict):
            _entry["measured"] = False
            _entry["basis"] = f"accepted_by_ruling_{ruling_id}"
    for _key, _entry in results.items():
        if isinstance(_entry, dict) and _entry.get("class") == "gating":
            _entry["measured"] = False
            _entry["basis"] = f"accepted_by_ruling_{ruling_id}"
    signoff["waiver_authorization"] = {
        "disposition": _WAIVER_AUTH_DISPOSITION,
        "clean_signoff": False,
        "statement": ("CDC/RDC gate CLOSED BY NAMED-HUMAN WAIVER, not by "
                      "measurement. This run produced no crossing census and no "
                      "structural coverage; it is NOT CDC/RDC clean."),
        "proof": proof,
        "accepted_unsupported_state": _cond.get("accepted_unsupported_state"),
        "accepted_not_assessable_obligations": list(
            _cond.get("accepted_not_assessable_obligations") or []),
        "accepted_spec_open_items": list(
            _cond.get("accepted_spec_open_items") or []),
        "authorized_implementation": _cond.get("authorized_implementation"),
        "close_when": _cond.get("close_when"),
        "fail_if": _cond.get("fail_if"),
        "required_evidence": list(ruling.get("required_evidence") or []),
        "limitations": list(ruling.get("limitations") or []),
        "rationale": ruling.get("rationale"),
    }
    return _cde(
        objective=(f"{kind} signoff of {top} -- accepted with waiver under "
                   f"{ruling_id}"),
        status="completed",
        results=results,
        signoff=signoff,
        inputs_ref={"rtl_files": files,
                    "waiver_ledger": proof["ledger"],
                    "ruling_id": ruling_id,
                    "ruling_sha256": proof["sha256_recomputed"]},
        assumptions=[
            f"gate closed under named-human ruling {ruling_id} "
            f"(authorized_by={proof['authorized_by']}, "
            f"rule_deck_version={proof['rule_deck_version']}); the ruling id, "
            "content hash, scope and every condition were recomputed and matched "
            "locally before acceptance",
            "accepted_with_waiver is NOT a clean CDC/RDC signoff: the crossing "
            "census, classification, synchronizer and declared-scheme "
            "verification, reconvergence screen and structural coverage were NOT "
            "produced by this run and are accepted as unavailable",
            "structural residuals read zero because the ruling removed these "
            "obligations from the UNWAIVED population; every gating entry is "
            "annotated measured=false",
            "scope is this campaign task only: no additional latch, reset gap, "
            "crossing, design, task or campaign is waived",
        ],
        validation={
            "verdict": "pass",
            "stage_closure_eligible": True,
            "basis": "accepted_with_waiver",
            "ruling_id": ruling_id,
            "ruling_sha256": proof["sha256_recomputed"],
            "checks": checks,
            "note": (f"gate closed by named-human waiver {ruling_id}; accepted "
                     "gaps are disclosed in signoff_evidence.waiver_authorization "
                     "and are NOT claims of clean coverage"),
        },
        provenance={"yosys": _yosys_version(), "log": "yosys_cdc.log",
                    "waiver_authorization_proof": proof},
    )


def _elaborate_mod(params, kind):
    """Shared front half: validate top, stage RTL, elaborate, return (top, mod,
    files, flops, cell_count) -- or (None, cde) when validation fails."""
    top = params["top"]
    if str(params.get("preserve_hierarchy", "")).lower() in (
            "1", "true", "yes"):
        return None, _cde(
            objective=f"{kind} signoff of {top}", status="failed",
            error=("preserve_hierarchy is not supported by the exhaustive CDC/RDC "
                   "screen; flattening is required so child state cannot disappear"),
            validation={"verdict": "not_assessable"})
    if not _is_ident(top):
        return None, _cde(objective=f"{kind} signoff", status="failed",
                          error=f"invalid 'top' identifier: {top!r}",
                          validation={"verdict": "fail"})
    files = _stage_rtl(params)
    _preserve = str(params.get("preserve_hierarchy", "")).lower() in ("1", "true", "yes")
    netlist = _elaborate_json(top, files, preserve_hierarchy=_preserve)
    mod = netlist["modules"].get(top) or next(iter(netlist["modules"].values()))
    module_names = set(netlist.get("modules") or {})
    residual_hierarchy = []
    accepted_model_blackboxes = []
    for name, cell in (mod.get("cells") or {}).items():
        cell_type = cell.get("type")
        if cell_type not in module_names:
            continue
        child = netlist["modules"][cell_type]
        source = str((child.get("attributes") or {}).get("src", "")).split(
            ":", 1)[0]
        # A module with no cells, no processes and no memories has no internal
        # structure at all, so it cannot hide a crossing BY CONSTRUCTION --
        # there is nothing inside it to hide one in. Yosys's `flatten` still
        # cannot inline such a module (measured: an empty `module leaf(input a,
        # output b); endmodule` survives `flatten` as a cell, with or without a
        # `(* blackbox *)` attribute), so without this branch the tool rejected
        # every design that represents a hard macro as an interface-only stub --
        # the normal delivery form when the macro's own RTL is owned by a
        # separate campaign leaf. The rejection message ("hierarchical instances
        # that hide child state") was also actively misleading for this case.
        #
        # This is an EMPTINESS proof, not a trust decision: it is re-derived
        # from the elaborated netlist on every run and every accepted instance
        # is recorded, so the acceptance is disclosed rather than silent. A
        # child with even one cell or process is still residual hierarchy.
        is_empty_module = not (child.get("cells") or child.get("processes")
                               or child.get("memories"))
        is_bound_stateless_blackbox = (
            bool((child.get("attributes") or {}).get("blackbox"))
            and not child.get("cells") and not child.get("processes")
            and os.path.realpath(source) in _ACTIVE_MODEL_PATHS)
        if is_bound_stateless_blackbox or is_empty_module:
            accepted_model_blackboxes.append({
                "instance": name, "module": cell_type, "source": source,
                "basis": ("pdk_bound_stateless_blackbox"
                          if is_bound_stateless_blackbox
                          else "verified_empty_module"),
                "blackbox_attribute": bool(
                    (child.get("attributes") or {}).get("blackbox")),
                "child_cells": len(child.get("cells") or {}),
                "child_processes": len(child.get("processes") or {}),
            })
        else:
            residual_hierarchy.append(name)
    if residual_hierarchy:
        return None, _cde(
            objective=f"{kind} signoff of {top}", status="failed",
            error=("flattening left hierarchical instances that hide child state: "
                   + ", ".join(sorted(residual_hierarchy))),
            validation={"verdict": "not_assessable"})
    unsupported = _unsupported_state_cells(mod)
    if unsupported:
        _ruling, _proof = _match_waiver_authorization(
            params, top, files, unsupported)
        if _ruling is None:
            _mem_left = [cell for cell in unsupported
                         if _is_memory_cell_type(cell["type"])]
            _mem_note = (
                f"inferred memory cells survived memory_collect/memory_map "
                f"lowering and cannot be attributed to a clock domain "
                f"(e.g. asynchronous write port or mixed write clocks): "
                f"{_mem_left}; " if _mem_left else "")
            return None, _cde(
                objective=f"{kind} signoff of {top}", status="failed",
                error=(_mem_note
                       + f"unsupported asynchronous/latch state in CDC/RDC census: "
                       f"{unsupported}"
                       + (f" (no authorized acceptance applied: {_proof})"
                          if _proof else "")),
                validation={"verdict": "not_assessable"})
        global _ACCEPTED_UNSUPPORTED_STATE
        _ACCEPTED_UNSUPPORTED_STATE = {
            "ruling_id": _proof["ruling_id"],
            "basis": "named_human_ledger_ruling",
            "census": _proof["observed_unsupported_state"],
        }
        return None, _waiver_accepted_cde(kind, top, files, _ruling, _proof)
    flops, cell_count = _extract_flops(mod)
    global _ACCEPTED_HIERARCHY
    _ACCEPTED_HIERARCHY = accepted_model_blackboxes
    if accepted_model_blackboxes and _ACTIVE_MODEL_EVIDENCE is not None:
        _ACTIVE_MODEL_EVIDENCE["accepted_stateless_blackboxes"] = \
            accepted_model_blackboxes
    return top, (mod, files, flops, cell_count)


def _elaboration_signature(files, top):
    """(flop_count, cell_count) for *files* -- the fingerprint used to prove that
    injecting formal properties did not perturb the design under test."""
    nl = _elaborate_json(top, files)
    m = nl["modules"].get(top) or next(iter(nl["modules"].values()))
    fl, cc = _extract_flops(m)
    return (len(fl), cc)


def _clock_of_domain(domain_map):
    """domain -> one clock net driving it. Deterministic (sorted) so a rerun on an
    unchanged design produces an identical property set; an unstable choice would
    make two runs incomparable for no reason."""
    out = {}
    for net, dom in sorted(domain_map.items()):
        out.setdefault(dom, net)
    return out


def _formal_symbols(mod, flops=None):
    symbols = {}
    for name, record in (mod.get("netnames") or {}).items():
        symbols[name.lstrip("\\")] = {
            "width": len(record.get("bits") or []), "direction": None}
    for name, record in (mod.get("ports") or {}).items():
        symbols[name.lstrip("\\")] = {
            "width": len(record.get("bits") or []),
            "direction": record.get("direction")}
    if flops:
        bit_net = _bit_net_index(mod)
        for flop in flops:
            for bit in flop.get("q", []):
                net = bit_net.get(bit)
                name = net[0].lstrip("\\") if net else None
                if name in symbols:
                    symbols[name]["state"] = True
                    symbols[name].setdefault("producer_domains", set()).add(
                        flop.get("domain") or flop.get("clk_domain"))
    return symbols


def _formal_blocks_closure(requested, status):
    """Requested formal evidence closes only on an explicit PASS."""
    return bool(requested) and status != "pass"


def _canonical_formal_evidence(requested, formal):
    """Return canonical formal results/checks only when formal was requested."""
    if not requested:
        return {}, {}
    formal = formal if isinstance(formal, dict) else {}
    tasks = formal.get("tasks") if isinstance(formal.get("tasks"), dict) else {}
    checks = {}
    for mode in ("bmc", "prove", "cover"):
        task = tasks.get(mode) if isinstance(tasks.get(mode), dict) else {}
        expected = task.get("expected_work_count")
        observed = task.get("observed_work_count")
        checks[mode + "_task_pass"] = bool(
            formal.get("status") == "pass"
            and task.get("status") == "pass"
            and isinstance(expected, int) and expected > 0
            and observed == expected
            and not task.get("missing_properties")
            and not task.get("unexpected_properties"))
    positive_work = formal.get("positive_work_count")
    if not isinstance(positive_work, int) or isinstance(positive_work, bool):
        positive_work = sum(
            task.get("observed_work_count", 0)
            for task in tasks.values()
            if isinstance(task, dict)
            and isinstance(task.get("observed_work_count"), int))
    checks["formal_positive_work"] = positive_work > 0
    checks["no_skipped_formal_properties"] = bool(
        formal.get("status") == "pass"
        and not formal.get("skipped")
        and all(checks[mode + "_task_pass"]
                for mode in ("bmc", "prove", "cover")))
    return {
        "formal_positive_work_count": {
            "value": positive_work,
            "unit": "count",
            "class": "gating",
            "basis": "formal_task_matrix",
            "closes_at": "> 0",
        },
    }, checks


def _canonical_cdc_evidence(crossings, unwaived, missing_primary,
                            unresolved_identity, formal_requested, formal,
                            undeclared_reset_sources=None,
                            gate_scope="cdc_structural_complete"):
    """Derive the exact progress-binding dialect from measured CDC evidence."""
    crossings = list(crossings or [])
    unwaived = list(unwaived or [])
    missing_primary = list(missing_primary or [])
    by_destination = {}
    missing_destinations = []
    for crossing in crossings:
        destination = crossing.get("to") or crossing.get("to_stage")
        if destination is None:
            missing_destinations.append(crossing)
            continue
        by_destination.setdefault(destination, []).append(crossing)
    reconvergent = {
        destination: items for destination, items in by_destination.items()
        if len(items) > 1
    }
    missing_synchronizers = [
        item for item in missing_primary
        if item.get("kind") in ("control_synchronizer", "reset_synchronizer")
    ]
    missing_resets = [
        item for item in missing_primary
        if item.get("kind") == "reset_synchronizer"
    ]
    undeclared_reset_sources = sorted(set(undeclared_reset_sources or []))
    classification_failures = (int(unresolved_identity or 0)
                               + len(missing_primary)
                               + len(missing_destinations))
    results = {
        "synchronizer_verification_failures": {
            "value": len(unwaived) + len(missing_synchronizers),
            "unit": "count", "class": "gating",
            "basis": "structural_netlist_analysis", "closes_at": "== 0"},
        "reconvergence_violations": {
            "value": len(reconvergent),
            "unit": "count", "class": "gating",
            "basis": "destination_fanin_analysis", "closes_at": "== 0"},
        "unclassified_crossings": {
            "value": classification_failures,
            "unit": "count", "class": "gating",
            "basis": "net_identity_and_declared_census", "closes_at": "== 0"},
        "reset_resolution_failures": {
            "value": len(missing_resets) + len(undeclared_reset_sources),
            "unit": "count", "class": "gating",
            "basis": "declared_reset_obligation_reconciliation",
            "closes_at": "== 0"},
    }
    checks = {
        "synchronizer_pass": results["synchronizer_verification_failures"]["value"] == 0,
        "all_crossings_classified": classification_failures == 0,
        "reset_resolution_preserved": not missing_resets and not undeclared_reset_sources,
        "reconvergence_pass": not reconvergent and not missing_destinations,
    }
    formal_results, formal_checks = _canonical_formal_evidence(
        formal_requested, formal)
    results.update(formal_results)
    checks.update(formal_checks)
    signoff = {
        "gate_scope": gate_scope,
        "required_structural_families": list(_CDC_REQUIRED_STRUCTURAL_FAMILIES),
        "synchronizer_verification": {
            "failures": results["synchronizer_verification_failures"]["value"],
        },
        "reconvergence": {
            "destinations_with_multiple_crossings": len(reconvergent),
            "reconvergent": [
                {"dest": destination, "sources": items}
                for destination, items in sorted(reconvergent.items())
            ],
            "crossings_without_destination_identity": missing_destinations,
        },
        "crossing_classification": {
            "unclassified_crossings": classification_failures,
        },
        "reset_resolution": {
            "failures": len(missing_resets) + len(undeclared_reset_sources),
            "undeclared_async_reset_sources": undeclared_reset_sources,
        },
    }
    return results, checks, signoff


def _undeclared_async_reset_sources(mod, flops, declared_obligations):
    """Top-level inputs reaching async-reset pins must be declared reset intent."""
    reset_bits = {
        bit for flop in flops if flop.get("has_async_reset")
        for bit in (flop.get("rst") or []) if isinstance(bit, int)
    }
    if not reset_bits:
        return []
    fanout = _combinational_fanout(mod)
    actual_sources = set()
    for name, port in (mod.get("ports") or {}).items():
        if port.get("direction") != "input":
            continue
        reached = _reachable_bits(port.get("bits") or [], fanout)
        if reset_bits & reached:
            actual_sources.add(name)
    declared_sources = {
        item.get("signal") for item in (declared_obligations or [])
        if item.get("kind") == "reset_synchronizer" and item.get("signal")
    }
    return sorted(actual_sources - declared_sources)


def _analyze(params, kind):
    domain_map = params.get("domain_map")
    if not domain_map:
        return _cde(objective=f"{kind} signoff", status="failed",
                    error="domain_map is required for CDC/RDC signoff",
                    validation={"verdict": "fail"})
    top, rest = _elaborate_mod(params, kind)
    if top is None:
        return rest
    mod, files, flops, cell_count = rest

    # FAIL-CLOSED: zero sequential cells means the crossing analysis never ran.
    if not flops:
        reason = (f"CDC screen not assessable: Yosys elaboration of top '{top}' "
                  f"extracted 0 sequential cells (saw {cell_count} cells). No "
                  f"clock-domain crossings can be analyzed. Likely causes: the "
                  f"design is purely combinational at this top, or the front-end "
                  f"did not lower flip-flops (e.g. a VHDL top not elaborated "
                  f"through the GHDL Yosys frontend). This is NOT a pass.")
        return _not_assessable_cde(kind, top, files, reason, cell_count)

    bit_domain = _bit_domain_index(mod, domain_map)
    bit_net = _bit_net_index(mod)
    for f in flops:
        f["domain"] = next((bit_domain[b] for b in f["clk"] if b in bit_domain), None)

    unresolved_flops = [f["name"] for f in flops if f["clk"] and not f["domain"]]
    observed_domains = {f["domain"] for f in flops if f.get("domain")}
    declared_domains = set(domain_map.values())
    if unresolved_flops or not declared_domains.issubset(observed_domains):
        reason = (
            "CDC screen not assessable: partial domain-map coverage; "
            f"unmapped sequential cells={sorted(unresolved_flops)}, "
            f"declared domains without sequential cells="
            f"{sorted(declared_domains - observed_domains)}")
        return _not_assessable_cde(kind, top, files, reason, cell_count)

    fanout = _combinational_fanout(mod)
    lanes = _flop_lanes(flops)
    # Crossings: source Q reaches destination D, directly or through combinational
    # logic. Per-lane records prevent one synchronized vector lane from blessing
    # every other lane in the same Yosys cell.
    # Each crossing carries the NET IDENTITY of the crossed bit so the per-bit
    # results can be reassembled into buses below. Without that identity an N-bit
    # bus and N unrelated 1-bit signals are the same result.
    crossings = []
    for source in lanes:
        if not isinstance(source["q"], int) or not source.get("domain"):
            continue
        reached = _reachable_bits([source["q"]], fanout)
        nname, nidx, nwidth = bit_net.get(source["q"], (None, None, 1))
        for destination in lanes:
            if (destination.get("domain") and
                    destination["domain"] != source["domain"] and
                    destination["d"] in reached):
                crossings.append({
                    "from": source["name"], "from_stage": source["stage"],
                    "from_domain": source["domain"],
                    "to": destination["name"], "to_stage": destination["stage"],
                    "to_q": destination["q"],
                    "to_domain": destination["domain"],
                    "signal": nname, "bit": nidx, "net_width": nwidth})
    synchronized = set()
    output_bits = {
        bit for port in (mod.get("ports") or {}).values()
        if port.get("direction") in ("output", "inout")
        for bit in port.get("bits", []) if isinstance(bit, int)}
    for crossing in crossings:
        reached = _reachable_bits([crossing.get("to_q")], fanout)
        consumers = [
            lane for lane in lanes
            if lane["stage"] != crossing["to_stage"] and
            lane["d"] == crossing.get("to_q")]
        sequential_uses = []
        for flop in flops:
            cell = (mod.get("cells") or {}).get(flop["name"], {})
            for port, bits in (cell.get("connections") or {}).items():
                if (cell.get("port_directions") or {}).get(port) != "input":
                    continue
                for index, bit in enumerate(bits):
                    if bit in reached:
                        sequential_uses.append((flop["name"], port, index))
        expected_use = (consumers[0]["name"], "D", consumers[0]["index"]) \
            if len(consumers) == 1 else None
        clean_second_stage = (
            len(consumers) == 1 and
            consumers[0]["domain"] == crossing["to_domain"] and
            not (reached & output_bits) and sequential_uses == [expected_use])
        if clean_second_stage:
            synchronized.add(crossing["to_stage"])
    unsync = [c for c in crossings if c["to_stage"] not in synchronized]

    valid_waivers, invalid_waivers = _split_waivers(params.get("waivers", []))
    waivers = {w.get("crossing") for w in valid_waivers}
    unwaived = [c for c in unsync
                if f"{c['from']}->{c['to']}" not in waivers and
                f"{c['from_stage']}->{c['to_stage']}" not in waivers]

    # --- MULTI-BIT COHERENCY (bus-level) -------------------------------------
    # Reassemble the per-bit crossings into buses. This is a SEPARATE defect
    # class from "is there a synchronizer": every bit of an unprotected bus can
    # be perfectly 2-flop synchronized and the bus still be broken. Waivers are
    # matched on the SIGNAL name here because the defect belongs to the bus, not
    # to any one flop-to-flop pair.
    bus_waivers = {w.get("bus") or w.get("signal")
                   for w in valid_waivers} - {None}
    buses = _group_crossings_into_buses(crossings, params.get("bus_protocols"))
    multi_bit_buses = [b for b in buses if b["multi_bit"]]
    unprotected_buses = [b for b in buses if b["unprotected_multi_bit"]
                         and b["signal"] not in bus_waivers]
    # How many crossings could NOT be tied to a named net bit. Load-bearing, not
    # cosmetic: bus width is derived from bit identity, so a run with a high
    # unresolved count is reporting widths it could not actually measure.
    unresolved_identity = sum(1 for c in crossings if c.get("bit") is None)

    # No unmapped domain? If NONE of the flops resolved a domain the map does not
    # match this netlist -- report not_assessable rather than a false "0 crossings".
    if not any(f.get("domain") for f in flops):
        reason = (f"CDC screen not assessable: none of the {len(flops)} sequential "
                  f"cells matched a clock net in the supplied domain_map "
                  f"({sorted(domain_map)}). The domain_map net names do not "
                  f"resolve against this netlist, so 0 crossings is not a real "
                  f"result. This is NOT a pass.")
        return _not_assessable_cde(kind, top, files, reason, cell_count)

    map_contract = params.get("_domain_map_contract") or {}
    declared_obligations = list(map_contract.get("obligations") or [])
    declared_census = dict(map_contract.get("census") or {})
    primary_crossings, missing_primary = _measure_primary_input_obligations(
        mod, flops, declared_obligations)
    measured_primary_count = len(primary_crossings) - len(missing_primary)

    # --- FORMAL COHERENCY PROOF (optional, opt-in) ---------------------------
    # Proves the SOURCE-DOMAIN obligation behind each DECLARED multi-bit scheme
    # (gray: at most one bit changes per source cycle; handshake: data stable in
    # the qualifier window). Structure cannot answer this -- a gray-coded bus and
    # an unprotected one have identical flop topology.
    #
    # A declaration is a claim by the caller. Left unproved it is an assumption
    # carried into signoff; proved, it is evidence. A COUNTEREXAMPLE FAILS THE
    # GATE: the declared scheme does not hold, so the bus was being treated as
    # protected on the strength of a claim that is false.
    formal = {"attempted": False, "status": "not_attempted",
              "note": "formal coherency proof not requested (formal=true to run)"}
    formal_requested = str(params.get("formal", "")).lower() in (
        "1", "true", "yes")
    if formal_requested:
        formal_scope = str(params.get("formal_scope", "source")).lower()
        try:
            formal_params = dict(params)
            if _ACCEPTED_HIERARCHY:
                formal_params["_formal_blackbox_cell_types"] = sorted({
                    item["module"] for item in _ACCEPTED_HIERARCHY})
            if _ACTIVE_MODEL_EVIDENCE:
                formal_params["_formal_input_bridge_pairs"] = \
                    _formal_input_bridge_pairs(mod)
            if formal_scope in ("multiclock", "full"):
                if map_contract.get("schema") != "clock-reset-domain-map/v2":
                    raise ValueError(
                        "multi-clock formal requires clock-reset-domain-map/v2")
                formal_contract = dict(map_contract)
                reset_intent = dict(map_contract.get("reset_intent") or {})
                symbols = _formal_symbols(mod, flops)
                bridge_pairs = formal_params.get(
                    "_formal_input_bridge_pairs", [])
                resolved_resets = {}
                reset_resolutions = []
                resolved_reset_properties = []
                resolved_reset_assumptions = []
                resolved_module = None
                resolved_scope = "top_level"
                for reset_id, reset in reset_intent.items():
                    signal = reset.get("synchronized_signal")
                    if signal in symbols:
                        resolved_resets[reset_id] = reset
                        continue
                    measured_reset = next((
                        item for item in primary_crossings
                        if item.get("kind") == "reset_synchronizer"
                        and item.get("signal") in (
                            reset.get("port"), reset.get("source_port"))
                        and item.get("measured")), None)
                    replacements = (
                        measured_reset.get("synchronized_signals", [])
                        if measured_reset else [])
                    if not replacements:
                        resolved_resets[reset_id] = reset
                        continue
                    source = (reset.get("port") or reset.get("source_port")
                              or reset.get("name"))
                    internal_source = next((
                        pair["internal"] for pair in bridge_pairs
                        if pair.get("external") == source), source)
                    polarity = reset.get("polarity")
                    source_active = (
                        f"!{source}" if polarity == "active_low" else source)
                    terminal = replacements[0].split(".")[-1]
                    terminal_active = (
                        f"!{terminal}" if polarity == "active_low" else terminal)
                    clock = map_contract["clock_intent"][
                        reset["destination_domains"][0]]["clock_port"]
                    latency = int(reset.get("deassertion_latency_cycles", 2))
                    resolved_reset_properties.extend([
                        domain_formal._property(
                            f"rdc_{reset_id}_structural_assert", clock,
                            terminal, "reset_asynchronous_assertion",
                            f"!({source_active}) || ({terminal_active})",
                            source_active,
                            f"Resolved reset {reset_id} asserts its measured "
                            "terminal whenever the declared source is active."),
                        domain_formal._property(
                            f"rdc_{reset_id}_structural_release_bound", clock,
                            terminal, "reset_release_bounded",
                            (f"!(_rdcf_assert_seen_{reset_id} && "
                             f"!({source_active}) && "
                             f"_rdcf_release_age_{reset_id} >= {latency}) "
                             f"|| !({terminal_active})"),
                            (f"_rdcf_assert_seen_{reset_id} && "
                             f"!({source_active}) && "
                             f"_rdcf_release_age_{reset_id} >= {latency} && "
                             f"!({terminal_active})"),
                            f"Resolved reset {reset_id} releases its measured "
                            f"terminal after {latency} destination edges.",
                            history=1),
                    ])
                    _, _, assumption_text = \
                        domain_formal.build_reset_properties({
                            reset_id: dict(
                                reset, port=source,
                                synchronized_signal=terminal)
                        }, map_contract["clock_intent"], None)
                    resolved_reset_assumptions.append(assumption_text)
                    # A measured terminal with a dotted 'cellname.signal' shape
                    # names a submodule instance (scope) whose defining module
                    # hosts the auxiliary injection. A terminal with NO dot
                    # (e.g. after `flatten`, a bare top-level net like
                    # 'macro_rst_n') has no cell to resolve -- that is not a
                    # failure, it means the property belongs at TOP scope, and
                    # must be routed there rather than treated as "unresolved"
                    # and dropped (formerly: resolved_module silently ended up
                    # None for a legitimate top-level terminal, and the two
                    # generated properties were then discarded with no trace --
                    # see domain_formal.run_cdc's auxiliary_properties gate).
                    has_cell_scope = "." in replacements[0]
                    resolved_module = None
                    resolved_scope = "top_level"
                    if has_cell_scope:
                        scope = replacements[0].split(".", 1)[0]
                        scope_cell = (mod.get("cells") or {}).get(scope, {})
                        resolved_module = (
                            scope_cell.get("attributes") or {}).get("module")
                        # A dotted terminal whose cell/module lookup STILL
                        # fails to resolve a module is genuinely unresolved --
                        # unlike a bare top-level net, there is no safe
                        # top-scope fallback here (the terminal is scoped to a
                        # cell we could not identify), so it must be reported
                        # as skipped rather than silently attached anywhere.
                        resolved_scope = (
                            "submodule" if resolved_module else "unresolved")
                    reset_resolutions.append({
                        "id": reset_id,
                        "declared_source_signal": source,
                        "structurally_resolved_source_signal": internal_source,
                        "declared_synchronized_signal": signal,
                        "structurally_measured_terminal_signals": replacements,
                        "formal_module": resolved_module,
                        "formal_scope": resolved_scope,
                        "formal_local_endpoint": terminal,
                        "basis": (
                            "declared reset ID preserved and encoded in the "
                            "owning RTL module against the measured terminal"),
                    })
                formal_contract["reset_intent"] = resolved_resets
                formal_params["_resolved_reset_properties"] = \
                    resolved_reset_properties
                formal_params["_resolved_reset_module"] = resolved_module
                formal_params["_resolved_reset_scope"] = resolved_scope
                formal_params["_resolved_reset_assumptions"] = \
                    "\n".join(resolved_reset_assumptions)
                formal = domain_formal.run_cdc(
                    files, top, buses, params.get("bus_protocols"), formal_contract,
                    formal_params, _elaboration_signature, _OUTPUT_DIR,
                    symbols)
                formal["reset_signal_resolutions"] = reset_resolutions
            elif formal_scope == "source":
                source_props, source_skipped = cdc_formal.build_properties(
                    buses, params.get("bus_protocols"),
                    _clock_of_domain(domain_map))
                symbols = _formal_symbols(mod, flops)
                for prop in source_props:
                    try:
                        domain_formal._require_signal(
                            symbols, prop["signal"],
                            f"formal property {prop['name']}.signal")
                        domain_formal._require_signal(
                            symbols, prop["clock"],
                            f"formal property {prop['name']}.clock",
                            exact_width=1, direction="input")
                    except ValueError as exc:
                        source_skipped.append({
                            "id": prop["name"], "reason": str(exc)})
                formal = cdc_formal.run(
                    work_dir=_WORK_DIR, files=files, top=top, module=top,
                    buses=[], protocols={}, clock_of_domain={},
                    depth=int(params.get("formal_depth", 20) or 20),
                    elaborate_check=_elaboration_signature, config=formal_params,
                    output_dir=_OUTPUT_DIR, properties=source_props,
                    skipped_properties=source_skipped)
            else:
                raise ValueError(
                    "CDC formal_scope must be source, multiclock, or full")
        except Exception as exc:  # noqa: BLE001
            formal = {"attempted": False, "status": "not_assessable",
                      "note": str(exc), "properties": [], "tasks": {}}
    formal_failed = _formal_blocks_closure(
        formal_requested, formal.get("status"))
    measured_controls = sum(
        item["measured"] and item["kind"] == "control_synchronizer"
        for item in primary_crossings)
    measured_resets = sum(
        item["measured"] and item["kind"] == "reset_synchronizer"
        for item in primary_crossings)
    measured_buses = sum(
        item["measured"] and item["kind"] == "qualified_capture_bus"
        for item in primary_crossings)
    primary_error = None
    if missing_primary:
        primary_error = (
            f"authoritative domain map declares {len(declared_obligations)} "
            f"asynchronous primary-input crossing(s), but only "
            f"{measured_primary_count} were measured in the elaborated netlist; "
            f"missing: {', '.join(item['signal'] for item in missing_primary)}")

    undeclared_reset_sources = _undeclared_async_reset_sources(
        mod, flops, declared_obligations)
    canonical_results, canonical_checks, canonical_signoff = \
        _canonical_cdc_evidence(
            crossings, unwaived, missing_primary, unresolved_identity,
            formal_requested, formal, undeclared_reset_sources)
    structural_checks_pass = all(canonical_checks[key] for key in (
        "synchronizer_pass",
        "all_crossings_classified",
        "reset_resolution_preserved",
        "reconvergence_pass",
    ))

    # ALL gates must close. A design can have a synchronizer on every crossing
    # (unwaived_violations == 0) and still ship a broken multi-bit bus, which is
    # precisely the failure per-bit analysis alone reports as clean.
    verdict = "pass" if (not unwaived and not unprotected_buses
                         and not formal_failed and not missing_primary
                         and structural_checks_pass) else "fail"
    return _cde(
        objective=f"{kind} signoff of {top}",
        status="failed" if (missing_primary or formal_failed) else "completed",
        # (A) GATING -- THREE independent gates, all of which must close:
        #   unwaived_violations        -- is there a synchronizer on each crossing
        #   unprotected_multi_bit_buses-- is each multi-bit crossing COHERENT
        #   formal_coherency_failures  -- does a DECLARED scheme actually hold
        # They are independent on purpose: a design can score 0 on the first and
        # still be broken on the second, which is exactly the failure mode
        # per-bit-only analysis reports as clean. The remaining counts are
        # context and must never be used as gates.
        results={"crossings": {
                     "value": len(crossings) + measured_primary_count,
                     "unit": "count",
                     "class": "diagnostic",
                     "basis": "structural_internal_plus_primary_input_trace",
                     "note": ("POPULATION, not a residual. More crossings is not "
                              "worse; declaring this as the gate would peg it at "
                              "the design's crossing count forever.")},
                 "structural_internal_crossings": {
                     "value": len(crossings), "unit": "count",
                     "class": "diagnostic", "basis": "structural_netlist_analysis"},
                 "measured_async_primary_input_crossings": {
                     "value": measured_primary_count, "unit": "count",
                     "class": "diagnostic",
                     "basis": "elaborated_netlist_primary_input_trace"},
                 "measured_control_synchronizers": {
                     "value": measured_controls,
                     "unit": "count", "class": "diagnostic",
                     "basis": "elaborated_netlist_primary_input_trace"},
                 "measured_reset_synchronizers": {
                     "value": measured_resets,
                     "unit": "count", "class": "diagnostic",
                     "basis": "elaborated_netlist_primary_input_trace"},
                 "measured_qualified_capture_buses": {
                     "value": measured_buses,
                     "unit": "count", "class": "diagnostic",
                     "basis": "elaborated_netlist_primary_input_trace"},
                 "declared_async_primary_input_crossings": {
                     "value": len(declared_obligations), "unit": "count",
                     "class": "diagnostic",
                     "basis": map_contract.get("schema") or "not_declared"},
                 "declared_control_synchronizers": {
                     "value": declared_census.get(
                         "control_two_flop_synchronizers", 0),
                     "unit": "count", "class": "diagnostic",
                     "basis": map_contract.get("schema") or "not_declared"},
                 "declared_reset_synchronizers": {
                     "value": declared_census.get("reset_synchronizers", 0),
                     "unit": "count", "class": "diagnostic",
                     "basis": map_contract.get("schema") or "not_declared"},
                 "declared_qualified_capture_buses": {
                     "value": declared_census.get("qualified_capture_buses", 0),
                     "unit": "count", "class": "diagnostic",
                     "basis": map_contract.get("schema") or "not_declared"},
                 "missing_declared_primary_input_crossings": {
                     "value": len(missing_primary), "unit": "count",
                     "class": "gating",
                     "basis": map_contract.get("schema") or "not_declared",
                     "closes_at": "== 0",
                     "note": ("Every asynchronous primary-input obligation in "
                              "the authoritative map must be found in the "
                              "elaborated netlist. A declared non-zero census "
                              "with zero measured work fails closed.")},
                 "unsynchronized": {
                     "value": len(unsync), "unit": "count",
                     "class": "diagnostic", "basis": "structural_netlist_analysis",
                     "note": "pre-waiver count; the gate is the unwaived subset"},
                 "unwaived_violations": {
                     "value": len(unwaived), "unit": "count",
                     "class": "gating", "basis": "structural_netlist_analysis",
                     "closes_at": "== 0",
                     "note": ("Crossings with no recognized synchronizer and no "
                              "waiver. A null means NOT ASSESSED and must never "
                              "read as zero -- see the not_assessable path above, "
                              "which fires when the domain_map does not resolve "
                              "against the netlist (0 crossings would be false).")},
                 "unprotected_multi_bit_buses": {
                     "value": len(unprotected_buses), "unit": "count",
                     "class": "gating", "basis": "structural_netlist_analysis",
                     "closes_at": "== 0",
                     "note": ("Multi-bit crossings with no DECLARED coherency "
                              "scheme. INDEPENDENT of unwaived_violations: a bus "
                              "whose every bit carries a 2-flop synchronizer "
                              "scores 0 there and is still broken here, because "
                              "per-bit synchronization of a multi-bit value is "
                              "the defect rather than the fix. Undeclared reads "
                              "as unprotected -- protection nobody stated is not "
                              "protection.")},
                 "multi_bit_crossings": {
                     "value": len(multi_bit_buses), "unit": "count",
                     "class": "diagnostic", "basis": "structural_netlist_analysis",
                     "note": ("POPULATION of multi-bit buses crossing a domain "
                              "boundary, protected or not. Context for the gate "
                              "above, never a gate itself.")},
                 "crossings_without_net_identity": {
                     "value": unresolved_identity, "unit": "count",
                     "class": "diagnostic", "basis": "structural_netlist_analysis",
                     "note": ("Crossings whose bit could not be tied to a named "
                              "net. Bus width is derived from bit identity, so a "
                              "non-zero value here means some widths are an "
                              "upper bound from the crossing count rather than a "
                              "measurement. Those groups are treated as "
                              "multi-bit when the count exceeds one, because an "
                              "unknown width must never read as one.")},
                 "formal_coherency_failures": {
                     "value": (len(formal.get("failing_properties") or [])
                               if formal.get("status") in ("pass", "fail")
                               else None),
                     "unit": "count",
                     "class": "gating", "basis": "formal_task_matrix",
                     "closes_at": "== 0",
                     "note": ("Counterexamples to a DECLARED source-domain "
                              "coherency obligation. NULL means the proof did "
                              "not run or did not reach a definite result, and "
                              "null is NOT zero: an unproved obligation is an "
                              "assumption carried into signoff, not evidence. "
                              "Bounded: valid only to the recorded depth.")},
                 "sequential_cells_extracted": {
                     "value": len(flops), "unit": "count",
                     "class": "diagnostic", "basis": "structural_netlist_analysis",
                     "note": ("Population the screen actually saw. Load-bearing: "
                              "a collapsing cell count means the screen is looking "
                              "at less design, not that the design got cleaner.")},
                 **canonical_results},
        signoff={**canonical_signoff,
                 "crossings": crossings,
                 "declared_primary_input_crossings": declared_obligations,
                 "measured_primary_input_crossings": primary_crossings,
                 "missing_primary_input_crossings": missing_primary,
                 "declared_crossing_census": declared_census,
                 # Hierarchical instances `flatten` could not inline and this
                 # run accepted, each with the basis that let it through. An
                 # acceptance recorded nowhere is indistinguishable from a
                 # design that had no residual hierarchy at all.
                 "accepted_residual_hierarchy": _ACCEPTED_HIERARCHY or None,
                 "rejected_waivers": invalid_waivers or None,
                 "accepted_waivers": [w.get("crossing") or w.get("bus")
                                      or w.get("signal") for w in valid_waivers],
                 "synchronizer_inventory": sorted(synchronized),
                 "unsynchronized_crossings": unsync,
                 "unwaived_violations": unwaived,
                 "buses": buses,
                 "unprotected_multi_bit_buses": unprotected_buses,
                 "formal": formal,
                 "domain_map": domain_map, "verdict": verdict,
                 "domain_map_schema": map_contract.get("schema") or "flat",
                 # (B) DIAGNOSTIC -- the repair surface: which crossings, between
                 # which domains, and which already carry a synchronizer.
                 "diagnostics": {
                     "class": "diagnostic", "basis": "structural_netlist_analysis",
                     "unwaived_crossings": unwaived,
                     "unsynchronized_crossings": unsync,
                     "synchronizer_inventory": sorted(synchronized),
                     "unprotected_multi_bit_buses": unprotected_buses,
                     "multi_bit_buses": multi_bit_buses,
                     "sequential_cells": len(flops),
                     "population_note": ("crossings/sequential_cells are the "
                                         "denominator; they are diagnostic because "
                                         "a CHANGED denominator (re-elaboration, "
                                         "hierarchy change) can make a shrinking "
                                         "violation count look like progress while "
                                         "screening strictly less design.")},
                 # (C) DESCRIPTIVE -- configuration, expected to hold steady.
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "kind": kind, "top": top,
                     "domain_count": len(set(domain_map.values())),
                     "rtl_file_count": len(files),
                     "method": "structural_2flop_synchronizer_heuristic"},
                 # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), len(unwaived),
                     "unwaived_violations")},
        inputs_ref={"rtl_files": files,
                    "domain_map": map_contract.get("source")},
        assumptions=["structural primary-input and flop-to-flop tracing; not a full "
                 "commercial CDC signoff; immediate destination-fanin "
                 "reconvergence is checked but transitive reconvergence is not",
                     "authoritative map declarations define the required census; "
                     "each obligation is reconciled against elaborated netlist "
                     "reachability before it contributes to measured work",
                     "multi-bit coherency schemes (gray/handshake/qualifier/fifo) "
                     "are CALLER-DECLARED via bus_protocols and are NOT verified "
                     "structurally; an undeclared multi-bit crossing is reported "
                     "unprotected rather than assumed safe",
                     "formal scope and task results are recorded per obligation; "
                     "bounded, inductive, cover, and fairness-backed live evidence "
                     "remain distinct; digital formal does NOT prove analog "
                     "metastability settling or recovery/removal timing"],
        validation={
            "verdict": verdict,
            "stage_closure_eligible": True,
            "checks": canonical_checks,
            "checks_evidence": {
                "synchronizer_pass": "results.synchronizer_verification_failures",
                "all_crossings_classified": "results.unclassified_crossings",
                "reset_resolution_preserved": "results.reset_resolution_failures",
                "reconvergence_pass": "results.reconvergence_violations",
            },
        },
        error=primary_error,
        provenance={"yosys": _yosys_version(), "log": "yosys_cdc.log"},
        pdk_binding=_ACTIVE_MODEL_EVIDENCE or "none",
    )


def _execute_rdc_formal(params, map_contract, files, top, mod, flops):
    requested = (str(params.get("formal", "")).lower() in
                 ("1", "true", "yes"))
    formal = {"attempted": False, "status": "not_attempted",
              "note": "multi-reset formal proof not requested"}
    if requested:
        scope = str(params.get("formal_scope", "multireset")).lower()
        try:
            if scope not in ("multireset", "full"):
                raise ValueError("RDC formal_scope must be multireset or full")
            if map_contract.get("schema") != "clock-reset-domain-map/v2":
                raise ValueError(
                    "multi-reset formal requires clock-reset-domain-map/v2")
            formal = domain_formal.run_rdc(
                files, top, map_contract, params, _elaboration_signature,
                _OUTPUT_DIR, _formal_symbols(mod, flops))
        except Exception as exc:  # noqa: BLE001
            formal = {"attempted": False, "status": "not_assessable",
                      "note": str(exc), "properties": [], "tasks": {}}
    return formal, _formal_blocks_closure(requested, formal.get("status"))


def _net_bits(mod, name):
    record = (mod.get("netnames") or {}).get(name)
    if record is None:
        record = (mod.get("ports") or {}).get(name)
    return tuple((record or {}).get("bits") or ())


def _reset_chain_depth(mod, flops, signal, destination_domain):
    target_bits = set(_net_bits(mod, signal))
    lanes = _flop_lanes(flops)
    producers = {lane["q"]: lane for lane in lanes if isinstance(lane["q"], int)}
    current = next((producers[bit] for bit in target_bits if bit in producers), None)
    depth = 0
    visited = set()
    cells = set()
    stages = []
    while current and current["stage"] not in visited and \
            current.get("domain") == destination_domain:
        visited.add(current["stage"])
        cells.add(current["name"])
        stages.append(current)
        depth += 1
        previous = None
        for candidate in lanes:
            if candidate["stage"] in visited or \
                    candidate.get("domain") != destination_domain:
                continue
            if current.get("d") == candidate.get("q"):
                previous = candidate
                break
        current = previous
    return depth, cells, stages


def _reset_intent_problems(mod, flops, contract):
    problems = []
    ports = mod.get("ports") or {}
    fanout = _combinational_fanout(mod)
    for reset in (contract.get("reset_intent") or {}).values():
        reset_id = reset.get("id")
        source = reset.get("port") or reset.get("source_port") or reset.get("name")
        destinations = reset.get("destination_domains") or []
        if source not in ports or ports[source].get("direction") != "input":
            problems.append(f"reset {reset_id} source '{source}' is not a top-level input")
            continue
        if len(ports[source].get("bits") or []) != 1:
            problems.append(f"reset {reset_id} source '{source}' must be one bit")
        if len(destinations) != 1:
            problems.append(f"reset {reset_id} must name exactly one destination domain")
            continue
        destination = destinations[0]
        clock = ((contract.get("clock_intent") or {}).get(destination) or {}).get(
            "clock_port")
        if clock not in ports or ports[clock].get("direction") != "input":
            problems.append(
                f"reset {reset_id} destination clock '{clock}' is not a top-level input")
        synchronized = reset.get("synchronized_signal")
        synchronized_bits = _net_bits(mod, synchronized)
        if not synchronized_bits:
            problems.append(
                f"reset {reset_id} synchronized signal '{synchronized}' is absent")
            continue
        if len(synchronized_bits) != 1:
            problems.append(
                f"reset {reset_id} synchronized signal '{synchronized}' must be one bit")
        depth, chain, chain_lanes = _reset_chain_depth(
            mod, flops, synchronized, destination)
        required = reset.get("synchronizer_stages", 0)
        if depth < required:
            problems.append(
                f"reset {reset_id} measured chain depth {depth} is below declared {required}")
        source_reached = _reachable_bits(_net_bits(mod, source), fanout)
        chain_flops = [flop for flop in flops if flop["name"] in chain]
        if reset.get("assertion") == "asynchronous" and (
                not chain_flops or any(
                    not any(bit in source_reached for bit in flop.get("rst", ()))
                    for flop in chain_flops)):
            problems.append(
                f"reset {reset_id} source does not asynchronously assert every declared chain stage")
        expected_polarity = "0" if reset.get("polarity") == "active_low" else "1"
        expected_asserted = expected_polarity
        expected_deasserted = "1" if expected_asserted == "0" else "0"
        for flop in chain_flops:
            key = (flop.get("rst_port") or "") + "_POLARITY"
            value = str((flop.get("parameters") or {}).get(key, ""))
            if value and value[-1:] != expected_polarity:
                problems.append(
                    f"reset {reset_id} polarity disagrees with chain cell {flop['name']}")
            value_key = (flop.get("rst_port") or "") + "_VALUE"
            reset_value = str((flop.get("parameters") or {}).get(value_key, ""))
            if reset_value and any(bit not in (expected_asserted, "x", "X")
                                   for bit in reset_value):
                problems.append(
                    f"reset {reset_id} asserted value disagrees with chain cell {flop['name']}")
        if chain_lanes:
            head = chain_lanes[-1]
            if str(head.get("d")) != expected_deasserted:
                problems.append(
                    f"reset {reset_id} first stage does not shift the deasserted value")
    return problems


def _analyze_rdc(params):
    """Reset-domain-crossing signoff -- a genuine reset analysis, not a relabeled
    CDC. An async-reset flop whose reset net was ASSERTED in one domain but reaches
    a flop clocked in a different domain WITHOUT being resynchronized to that
    destination clock is a reset-domain crossing (risk: reset-removal race /
    metastable release). A reset is considered synchronized when its net is driven
    by a flip-flop CLOCKED in the destination domain (a reset synchronizer)."""
    kind = "RDC"
    # Reset domains may be supplied explicitly; otherwise fall back to the clock
    # domain_map (a common single-map setup). One of them is required.
    reset_domain_map = params.get("reset_domain_map") or params.get("domain_map")
    if not reset_domain_map:
        return _cde(objective="RDC signoff", status="failed",
                    error="reset_domain_map (or domain_map) is required for RDC signoff",
                    validation={"verdict": "fail"})
    top, rest = _elaborate_mod(params, kind)
    if top is None:
        return rest
    mod, files, flops, cell_count = rest
    map_contract = params.get("_reset_domain_map_contract") or \
        params.get("_domain_map_contract") or {}
    reset_obligations = [
        item for item in (map_contract.get("obligations") or [])
        if item.get("kind") == "reset_synchronizer"
    ]
    if not flops:
        reason = (f"RDC screen not assessable: Yosys elaboration of top '{top}' "
                  f"extracted 0 sequential cells (saw {cell_count} cells). No "
                  f"reset-domain crossings can be analyzed. This is NOT a pass.")
        return _not_assessable_cde(kind, top, files, reason, cell_count)

    bit_domain = _bit_domain_index(mod, reset_domain_map)
    for f in flops:
        f["clk_domain"] = next((bit_domain[b] for b in f["clk"] if b in bit_domain), None)
        f["rst_domain"] = next((bit_domain[b] for b in f["rst"] if b in bit_domain), None)

    unresolved_async = [f["name"] for f in flops if f["has_async_reset"] and
                        not f.get("clk_domain")]
    if unresolved_async:
        reason = ("RDC screen not assessable: partial reset/clock domain coverage "
                  f"for asynchronous-reset cells {sorted(unresolved_async)}")
        return _not_assessable_cde(kind, top, files, reason, cell_count)

    intent_problems = _reset_intent_problems(mod, flops, map_contract)
    if intent_problems:
        reason = "RDC intent reconciliation failed: " + "; ".join(intent_problems)
        return _not_assessable_cde(kind, top, files, reason, cell_count)
    formal, formal_failed = _execute_rdc_formal(
        params, map_contract, files, top, mod, flops)

    async_flops = [f for f in flops if f["has_async_reset"]]
    if not async_flops:
        declared_async = [
            reset for reset in (map_contract.get("reset_intent") or {}).values()
            if reset.get("assertion") == "asynchronous"
        ]
        if declared_async:
            reason = (
                f"RDC structural screen found 0 asynchronous-reset flops, but "
                f"v2 declares {len(declared_async)} asynchronous reset "
                "synchronizer obligation(s); declared work was not measured")
            return _not_assessable_cde(kind, top, files, reason, cell_count)
        # No async resets at all -> there is genuinely nothing to cross. This is a
        # real, assessable result (unlike zero-flop), so it may pass.
        return _cde(
            objective=f"RDC signoff of {top}",
            status="failed" if formal_failed else "completed",
            results={"async_reset_flops": {"value": 0, "unit": "count"},
                     "reset_crossings": {"value": 0, "unit": "count"},
                     "declared_reset_synchronizers": {
                         "value": len(reset_obligations), "unit": "count"},
                     "sequential_cells_extracted": {"value": len(flops), "unit": "count"}},
            signoff={"reset_crossings": [], "synchronizer_inventory": [],
                     "declared_primary_input_reset_obligations": reset_obligations,
                     "unwaived_violations": [], "reset_domain_map": reset_domain_map,
                     "domain_map_schema": map_contract.get("schema") or "flat",
                     "formal": formal,
                     "verdict": "fail" if formal_failed else "pass"},
            inputs_ref={"rtl_files": files,
                        "domain_map": map_contract.get("source")},
            assumptions=["no async-reset flops present; sync-reset only design"],
            validation={"verdict": "fail" if formal_failed else "pass",
                        "note": "no async resets -> no reset-domain crossings"},
            provenance={"yosys": _yosys_version(), "log": "yosys_cdc.log"},
        )

    # A reset net is "synchronized to a clock domain D" when it is produced by a
    # flop clocked in D (reset synchronizer output).
    qbit_clk_domain = {}
    for f in flops:
        for b in f["q"]:
            if f.get("clk_domain"):
                qbit_clk_domain[b] = f["clk_domain"]
    for f in async_flops:
        if not f.get("rst_domain"):
            f["rst_domain"] = next((qbit_clk_domain.get(bit) for bit in f["rst"]
                                    if qbit_clk_domain.get(bit)), None)
    unresolved_reset_domains = [f["name"] for f in async_flops
                                if not f.get("rst_domain")]
    if unresolved_reset_domains:
        reason = ("RDC screen not assessable: unresolved reset ownership for "
                  f"asynchronous-reset cells {sorted(unresolved_reset_domains)}")
        return _not_assessable_cde(kind, top, files, reason, cell_count)

    declared_chain_cells = set()
    allowed_reset_bits = {}
    for reset in (map_contract.get("reset_intent") or {}).values():
        destination = (reset.get("destination_domains") or [None])[0]
        _, cells, chain_lanes = _reset_chain_depth(
            mod, flops, reset.get("synchronized_signal"),
            destination)
        lane_counts = {}
        for lane in chain_lanes:
            lane_counts[lane["name"]] = lane_counts.get(lane["name"], 0) + 1
        flop_widths = {flop["name"]: max(len(flop["d"]), len(flop["q"]))
                       for flop in flops}
        declared_chain_cells.update(
            cell for cell in cells if lane_counts.get(cell) == flop_widths.get(cell))
        allowed_reset_bits.setdefault(destination, set()).update(
            _net_bits(mod, reset.get("synchronized_signal")))

    reset_crossings = []
    synchronized = []
    for f in async_flops:
        rdom = f.get("rst_domain")
        cdom = f.get("clk_domain")
        if f["name"] in declared_chain_cells:
            synchronized.append({"flop": f["name"], "reset_domain": rdom,
                                 "clock_domain": cdom,
                                 "reset_port": f["rst_port"],
                                 "declared_chain": True})
            continue
        allowed = allowed_reset_bits.get(cdom)
        if allowed is not None and not set(f["rst"]).issubset(allowed):
            reset_crossings.append({
                "flop": f["name"], "reset_domain": rdom,
                "clock_domain": cdom, "reset_port": f["rst_port"],
                "reason": "functional state uses raw or intermediate reset, not declared synchronized output"})
            continue
        if not rdom or not cdom or rdom == cdom:
            continue  # reset originates in the same domain it lands in -> no crossing
        # Is the reset net driven by a flop clocked in the destination domain?
        sync_to_dest = any(qbit_clk_domain.get(b) == cdom for b in f["rst"])
        rec = {"flop": f["name"], "reset_domain": rdom, "clock_domain": cdom,
               "reset_port": f["rst_port"]}
        if sync_to_dest:
            synchronized.append(rec)
        else:
            reset_crossings.append(rec)

    valid_waivers, invalid_waivers = _split_waivers(params.get("waivers", []))
    waivers = {w.get("crossing") for w in valid_waivers}
    unwaived = [c for c in reset_crossings
                if f"{c['reset_domain']}->{c['clock_domain']}@{c['flop']}" not in waivers]

    if not any(f.get("clk_domain") or f.get("rst_domain") for f in async_flops):
        reason = (f"RDC screen not assessable: none of the {len(async_flops)} "
                  f"async-reset cells matched a net in the supplied "
                  f"reset_domain_map ({sorted(reset_domain_map)}); 0 crossings is "
                  f"not a real result. This is NOT a pass.")
        return _not_assessable_cde(kind, top, files, reason, cell_count)

    verdict = "pass" if not unwaived and not formal_failed else "fail"
    return _cde(
        objective=f"RDC signoff of {top}",
        status="failed" if formal_failed else "completed",
        results={"async_reset_flops": {"value": len(async_flops), "unit": "count"},
                 "reset_crossings": {"value": len(reset_crossings), "unit": "count"},
                 "synchronized_resets": {"value": len(synchronized), "unit": "count"},
                 "declared_reset_synchronizers": {
                     "value": len(reset_obligations), "unit": "count"},
                 "unwaived_violations": {"value": len(unwaived), "unit": "count"},
                 "formal_reset_failures": {
                     "value": (len(formal.get("failing_properties") or [])
                               if formal.get("status") in ("pass", "fail") else None),
                     "unit": "count", "class": "gating",
                     "basis": "formal_task_matrix", "closes_at": "== 0"},
                 "sequential_cells_extracted": {"value": len(flops), "unit": "count"}},
        signoff={"reset_crossings": reset_crossings,
                 "declared_primary_input_reset_obligations": reset_obligations,
                 "rejected_waivers": invalid_waivers or None,
                 "accepted_waivers": [w.get("crossing") for w in valid_waivers],
                 "synchronizer_inventory": synchronized,
                 "unwaived_violations": unwaived,
                 "reset_domain_map": reset_domain_map,
                 "domain_map_schema": map_contract.get("schema") or "flat",
                 "formal": formal,
                 "verdict": verdict},
        inputs_ref={"rtl_files": files,
                    "domain_map": map_contract.get("source")},
        assumptions=["reset synchronizer = reset net driven by a flop clocked in "
                     "the destination domain; not a full commercial RDC signoff"],
        validation={"verdict": verdict},
        provenance={"yosys": _yosys_version(), "log": "yosys_cdc.log"},
    )


def _flatten_domain_map(obj):
    """Flatten a rich domain-map document into the {net: domain} dict the
    analyzers consume. A `microwatt-domain-map/v1`-style object carries
    `clocks: [{name, domain}]` and `resets: [{name, domain, aliases:[...]}]`;
    every clock/reset net name (and reset alias) maps to its domain. An object
    that already looks flat ({str: str}, no clocks/resets) is returned as-is."""
    if not isinstance(obj, dict):
        return {}
    if "clocks" not in obj and "resets" not in obj:
        if not obj or not all(isinstance(k, str) and isinstance(v, str)
                              and k and v for k, v in obj.items()):
            return {}
        return dict(obj)
    flat = {}
    for c in obj.get("clocks", []) or []:
        if not isinstance(c, dict):
            continue
        if c.get("name") and c.get("domain"):
            flat[c["name"]] = c["domain"]
    for r in obj.get("resets", []) or []:
        if not isinstance(r, dict):
            continue
        dom = r.get("domain")
        if r.get("name") and dom:
            flat[r["name"]] = dom
        for a in r.get("aliases", []) or []:
            if dom and isinstance(a, str):
                flat[a] = dom
    return flat


def _map_error(message):
    return "invalid clock/reset domain map: " + message


def _adapt_producer_v1(obj):
    """Translate the campaign producer's v1 dialect to the canonical v1 form."""
    clocks = obj.get("clock_domains") or []
    if not clocks or all("name" in clock for clock in clocks):
        return obj
    resets_by_port = {
        reset.get("source_port"): reset for reset in obj.get("resets", [])
        if isinstance(reset, dict) and reset.get("source_port")}
    has_external = any(
        item.get("classification") in (
            "asynchronous-requiring-a-synchronizer", "qualified-capture")
        or (item.get("classification") == "reset"
            and resets_by_port.get(item.get("port"), {}).get("external_type")
            == "asynchronous")
        for item in obj.get("inputs", []) if isinstance(item, dict))
    canonical_clocks = [{
        "name": clock.get("id"), "kind": "synchronous",
        "clock_port": clock.get("clock"), "edge": clock.get("edge"),
        "period_ns": clock.get("period_ns"),
    } for clock in clocks]
    if has_external:
        canonical_clocks.append({"name": "async_external", "kind": "asynchronous"})
    captures = {item.get("bus"): item for item in obj.get(
        "qualified_captures", []) if isinstance(item, dict)}
    canonical_inputs = []
    for item in obj.get("inputs", []):
        if not isinstance(item, dict):
            canonical_inputs.append(item)
            continue
        classification = item.get("classification")
        name = item.get("port")
        asynchronous = classification in (
            "asynchronous-requiring-a-synchronizer", "qualified-capture")
        if classification == "reset":
            asynchronous = resets_by_port.get(name, {}).get(
                "external_type") == "asynchronous"
        mapped_class = {
            "asynchronous-requiring-a-synchronizer": "asynchronous_control",
            "qualified-capture": "qualified_capture_bus",
        }.get(classification, classification)
        protocol = {
            "asynchronous_control": "two_flop",
            "qualified_capture_bus": "qualifier",
            "reset": "async_assert_sync_deassert",
        }.get(mapped_class, "synchronous")
        canonical_inputs.append({
            "name": name, "width": item.get("width"),
            "classification": mapped_class,
            "async_by_construction": asynchronous,
            "source_domain": item.get("source_domain") or "async_external",
            "destination_domain": item.get("destination_domain"),
            "required_protocol": protocol,
        })
    canonical_captures = []
    for name, capture in captures.items():
        source_item = next((item for item in obj.get("inputs", [])
                            if item.get("port") == name), {})
        qualifier = str(source_item.get("qualifier") or
                        capture.get("qualifier") or "").split()[0]
        if "." in qualifier:
            sync_id = qualifier.split(".", 1)[0]
            sync = next((item for item in obj.get("synchronizers", [])
                         if item.get("id") == sync_id), {})
            qualifier = sync.get("source") or qualifier
        canonical_captures.append({
            "bus": name, "width": capture.get("width"),
            "qualifier": qualifier,
            "capture_stages": capture.get("register_stages"),
            "qualifier_synchronizer_stages": next((
                sync.get("stages") for sync in obj.get("synchronizers", [])
                if sync.get("source") == qualifier), None),
            "per_bit_synchronizers": capture.get("per_bit_synchronizers"),
            "host_stability_contract": source_item.get(
                "host_stability_contract"),
        })
    canonical_resets = [{
        "name": reset.get("source_port"),
        "destination_domains": [reset.get("destination_domain")],
        "id": reset.get("id"), "port": reset.get("source_port"),
        "polarity": reset.get("polarity"),
        "assertion": reset.get("external_type"),
        "deassertion": reset.get("internal_type"),
        "synchronized_signal": reset.get("id"),
        "synchronizer_stages": next((
            sync.get("stages") for sync in obj.get("synchronizers", [])
            if sync.get("id") == reset.get("id")), 0),
        "minimum_assert_cycles": reset.get("minimum_assert_cycles", 1),
        "deassertion_latency_cycles": reset.get("deassertion_latency_cycles") or
            next((sync.get("stages") for sync in obj.get("synchronizers", [])
                if sync.get("id") == reset.get("id")), 1),
        "dependencies": reset.get("dependencies", []),
    } for reset in obj.get("resets", [])]
    expected = obj.get("expected_census") or {}
    controls = expected.get("control_2ff_synchronizers", 0)
    reset_count = expected.get("reset_synchronizers", 0)
    adapted = dict(obj)
    adapted.update({
        "clock_domains": canonical_clocks,
        "inputs": canonical_inputs,
        "qualified_capture_buses": canonical_captures,
        "resets": canonical_resets,
        "expected_census": {
            "synchronizer_bearing_crossings": controls + reset_count,
            "control_two_flop_synchronizers": controls,
            "reset_synchronizers": reset_count,
            "qualified_capture_buses": expected.get("qualified_capture_buses", 0),
            "unsynchronized_crossings": expected.get("unsynchronized_crossings", 0),
        },
    })
    return adapted


def _clock_reset_domain_map_v1(obj, source):
    """Validate and normalize the authoritative clock-reset-domain-map/v1.

    The structural analyzer still needs a flat net-to-domain map, while the
    primary-input census needs the richer intent. Keep both; projecting to the
    flat map alone is the lossy operation that caused cdc.3 to report zero.
    """
    obj = _adapt_producer_v1(obj)
    required = ("clock_domains", "inputs", "resets",
                "qualified_capture_buses", "expected_census")
    missing = [key for key in required if key not in obj]
    if missing:
        return None, _map_error("missing required field(s): " + ", ".join(missing))
    for key in ("clock_domains", "inputs", "resets", "qualified_capture_buses"):
        if not isinstance(obj.get(key), list):
            return None, _map_error(f"'{key}' must be a list")
    if not isinstance(obj.get("expected_census"), dict):
        return None, _map_error("'expected_census' must be an object")

    flat = {}
    domains = set()
    for index, clock in enumerate(obj["clock_domains"]):
        if not isinstance(clock, dict):
            return None, _map_error(f"clock_domains[{index}] must be an object")
        name = clock.get("name")
        kind = clock.get("kind")
        if not isinstance(name, str) or not name:
            return None, _map_error(f"clock_domains[{index}].name is required")
        if not isinstance(kind, str) or not kind:
            return None, _map_error(f"clock_domains[{index}].kind is required")
        domains.add(name)
        clock_port = clock.get("clock_port")
        if kind == "synchronous":
            if not isinstance(clock_port, str) or not clock_port:
                return None, _map_error(
                    f"synchronous clock domain '{name}' requires clock_port")
            flat[clock_port] = name
            if clock.get("edge", "rising") != "rising":
                return None, _map_error(
                    f"clock domain '{name}' uses unsupported non-rising edge")

    bus_records = {}
    for index, bus in enumerate(obj["qualified_capture_buses"]):
        if not isinstance(bus, dict):
            return None, _map_error(
                f"qualified_capture_buses[{index}] must be an object")
        bus_name = bus.get("bus")
        if not isinstance(bus_name, str) or not bus_name:
            return None, _map_error(
                f"qualified_capture_buses[{index}].bus is required")
        signal = bus_name.split("[", 1)[0]
        if signal in bus_records:
            return None, _map_error(
                f"duplicate qualified capture bus for '{signal}'")
        bus_records[signal] = bus

    obligations = []
    seen_inputs = set()
    for index, item in enumerate(obj["inputs"]):
        if not isinstance(item, dict):
            return None, _map_error(f"inputs[{index}] must be an object")
        name = item.get("name")
        classification = item.get("classification")
        source_domain = item.get("source_domain")
        destination_domain = item.get("destination_domain")
        width = item.get("width")
        if not isinstance(name, str) or not name:
            return None, _map_error(f"inputs[{index}].name is required")
        if name in seen_inputs:
            return None, _map_error(f"duplicate input '{name}'")
        seen_inputs.add(name)
        if not isinstance(width, int) or isinstance(width, bool) or width < 1:
            return None, _map_error(f"input '{name}' has invalid width")
        if not isinstance(classification, str) or not classification:
            return None, _map_error(
                f"input '{name}' requires classification")
        async_input = item.get("async_by_construction")
        if not isinstance(async_input, bool):
            return None, _map_error(
                f"input '{name}' requires boolean async_by_construction")
        if not async_input:
            continue
        if not isinstance(source_domain, str) or not source_domain:
            return None, _map_error(
                f"asynchronous input '{name}' requires source_domain")
        if source_domain not in domains:
            return None, _map_error(
                f"asynchronous input '{name}' references unknown "
                f"source_domain '{source_domain}'")
        if destination_domain not in domains:
            return None, _map_error(
                f"asynchronous input '{name}' references unknown "
                f"destination_domain '{destination_domain}'")
        protocol = item.get("required_protocol")
        if not isinstance(protocol, str) or not protocol.strip():
            return None, _map_error(
                f"asynchronous input '{name}' requires required_protocol")

        if classification == "asynchronous_control":
            if width != 1:
                return None, _map_error(
                    f"asynchronous control '{name}' must be one bit")
            kind = "control_synchronizer"
            detail = {}
        elif classification == "reset":
            if width != 1:
                return None, _map_error(f"reset input '{name}' must be one bit")
            kind = "reset_synchronizer"
            detail = {}
        elif classification == "qualified_capture_bus":
            record = bus_records.get(name)
            if record is None:
                return None, _map_error(
                    f"qualified capture input '{name}' has no matching "
                    "qualified_capture_buses entry")
            if record.get("width") != width:
                return None, _map_error(
                    f"qualified capture bus '{name}' width disagrees with inputs")
            qualifier = record.get("qualifier")
            if not isinstance(qualifier, str) or qualifier not in seen_inputs | {
                    x.get("name") for x in obj["inputs"] if isinstance(x, dict)}:
                return None, _map_error(
                    f"qualified capture bus '{name}' has invalid qualifier")
            kind = "qualified_capture_bus"
            detail = {
                "qualifier": qualifier,
                "capture_stages": record.get("capture_stages"),
                "qualifier_synchronizer_stages":
                    record.get("qualifier_synchronizer_stages"),
                "per_bit_synchronizers": record.get("per_bit_synchronizers"),
                "host_stability_contract": record.get("host_stability_contract"),
            }
        else:
            return None, _map_error(
                f"unsupported asynchronous input classification "
                f"'{classification}' for '{name}'")

        obligation = {
            "signal": name, "width": width, "kind": kind,
            "classification": classification,
            "from_domain": source_domain,
            "to_domain": destination_domain,
            "required_protocol": protocol,
        }
        obligation.update(detail)
        obligations.append(obligation)

    reset_names = {
        item["signal"] for item in obligations
        if item["kind"] == "reset_synchronizer"
    }
    declared_resets = set()
    for index, reset in enumerate(obj["resets"]):
        if not isinstance(reset, dict):
            return None, _map_error(f"resets[{index}] must be an object")
        name = reset.get("name")
        destinations = reset.get("destination_domains")
        if not isinstance(name, str) or not name:
            return None, _map_error(f"resets[{index}].name is required")
        if not isinstance(destinations, list) or not destinations:
            return None, _map_error(
                f"reset '{name}' requires destination_domains")
        if any(domain not in domains for domain in destinations):
            return None, _map_error(
                f"reset '{name}' references an unknown destination domain")
        if reset.get("deassertion") not in (None, "synchronous"):
            return None, _map_error(
                f"reset '{name}' uses unsupported asynchronous deassertion")
        declared_resets.add(name)
    if reset_names != declared_resets:
        return None, _map_error(
            "reset inputs and resets[] declarations do not match")
    qualified_names = {
        item["signal"] for item in obligations
        if item["kind"] == "qualified_capture_bus"
    }
    if qualified_names != set(bus_records):
        return None, _map_error(
            "qualified capture inputs and qualified_capture_buses[] "
            "declarations do not match")

    controls = sum(o["kind"] == "control_synchronizer" for o in obligations)
    resets = sum(o["kind"] == "reset_synchronizer" for o in obligations)
    buses = sum(o["kind"] == "qualified_capture_bus" for o in obligations)
    census = {
        "synchronizer_bearing_crossings": controls + resets,
        "control_two_flop_synchronizers": controls,
        "reset_synchronizers": resets,
        "qualified_capture_buses": buses,
        "declared_async_primary_input_crossings": len(obligations),
    }
    expected = obj["expected_census"]
    for key in ("synchronizer_bearing_crossings",
                "control_two_flop_synchronizers",
                "reset_synchronizers", "qualified_capture_buses",
                "unsynchronized_crossings"):
        if not isinstance(expected.get(key), int) or isinstance(
                expected.get(key), bool):
            return None, _map_error(
                f"expected_census.{key} must be an integer")
    for key in ("synchronizer_bearing_crossings",
                "control_two_flop_synchronizers",
                "reset_synchronizers", "qualified_capture_buses"):
        if expected[key] != census[key]:
            return None, _map_error(
                f"expected_census.{key}={expected[key]} but declarations imply "
                f"{census[key]}")
    census["expected_unsynchronized_crossings"] = \
        expected["unsynchronized_crossings"]

    bus_protocols = {}
    for obligation in obligations:
        if obligation["kind"] == "qualified_capture_bus":
            bus_protocols[obligation["signal"]] = {
                "scheme": "qualifier",
                "qualifier": obligation["qualifier"],
            }
    reset_flat = dict(flat)
    for obligation in obligations:
        if obligation["kind"] == "reset_synchronizer":
            reset_flat[obligation["signal"]] = obligation["from_domain"]
    return {
        "flat": flat,
        "reset_flat": reset_flat,
        "schema": "clock-reset-domain-map/v1",
        "source": source,
        "obligations": obligations,
        "census": census,
        "bus_protocols": bus_protocols,
        "clock_intent": {clock["name"]: clock for clock in obj["clock_domains"]},
        "reset_intent": {reset["name"]: reset for reset in obj["resets"]},
        "formal_crossings": obj.get("formal_crossings") or [],
    }, None


def _clock_reset_domain_map_v2(obj, source):
    """Validate v2 timing/reset intent, then reuse canonical census checks."""
    clocks = obj.get("clock_domains")
    if not isinstance(clocks, list) or not clocks:
        return None, _map_error("v2 requires a non-empty clock_domains list")
    names = set()
    period_by_name = {}
    canonical_clocks = []
    for index, clock in enumerate(clocks):
        if not isinstance(clock, dict):
            return None, _map_error(f"clock_domains[{index}] must be an object")
        name = clock.get("id") or clock.get("name")
        port = clock.get("clock_port") or clock.get("clock")
        relation = clock.get("relation", "primary")
        edge = clock.get("edge")
        period = clock.get("period_ns")
        if not isinstance(name, str) or not name or name in names:
            return None, _map_error(f"clock_domains[{index}] has invalid/duplicate id")
        if relation not in ("primary", "related", "generated", "asynchronous"):
            return None, _map_error(f"clock domain '{name}' has invalid relation")
        if not isinstance(port, str) or not port or edge != "rising":
            return None, _map_error(f"clock domain '{name}' requires port and edge")
        if not isinstance(period, (int, float)) or isinstance(period, bool) or period <= 0:
            return None, _map_error(f"clock domain '{name}' requires period_ns > 0")
        phase = clock.get("phase_ns")
        if phase is not None:
            if (not isinstance(phase, (int, float)) or isinstance(phase, bool)
                    or phase < 0 or phase >= period):
                return None, _map_error(
                    f"clock domain '{name}' requires 0 <= phase_ns < period_ns")
        if relation in ("related", "generated"):
            ratio = clock.get("ratio")
            if (clock.get("parent") not in names or not isinstance(ratio, dict)
                    or not isinstance(ratio.get("numerator"), int)
                    or not isinstance(ratio.get("denominator"), int)
                    or ratio["numerator"] < 1 or ratio["denominator"] < 1):
                return None, _map_error(
                    f"clock domain '{name}' requires an earlier parent and positive ratio")
            expected_period = (period_by_name[clock["parent"]]
                               * ratio["denominator"] / ratio["numerator"])
            if abs(float(period) - float(expected_period)) > 1.0e-9:
                return None, _map_error(
                    f"clock domain '{name}' period disagrees with parent/ratio")
        elif clock.get("parent") is not None or clock.get("ratio") is not None:
            return None, _map_error(
                f"clock domain '{name}' may declare parent/ratio only when "
                "relation is related or generated")
        if not isinstance(clock.get("must_toggle", True), bool):
            return None, _map_error(f"clock domain '{name}'.must_toggle must be boolean")
        if clock.get("must_toggle", True) is False:
            idle = clock.get("max_idle_ticks")
            if not isinstance(idle, int) or isinstance(idle, bool) or idle < 1:
                return None, _map_error(
                    f"clock domain '{name}' with must_toggle=false requires "
                    "max_idle_ticks >= 1")
        names.add(name)
        period_by_name[name] = float(period)
        canonical_clocks.append(dict(clock, name=name, kind="synchronous",
                                     clock_port=port))
    canonical_resets = []
    reset_ids = set()
    for index, reset in enumerate(obj.get("resets") or []):
        if not isinstance(reset, dict):
            return None, _map_error(f"resets[{index}] must be an object")
        reset_id = reset.get("id") or reset.get("name")
        port = reset.get("port") or reset.get("source_port")
        destinations = reset.get("destination_domains")
        if (not isinstance(reset_id, str) or not reset_id or reset_id in reset_ids
                or not isinstance(port, str) or not port):
            return None, _map_error(f"resets[{index}] has invalid/duplicate id or port")
        if reset.get("polarity") not in ("active_low", "active_high"):
            return None, _map_error(f"reset '{reset_id}' requires polarity")
        if reset.get("assertion") not in ("asynchronous", "synchronous"):
            return None, _map_error(f"reset '{reset_id}' requires assertion style")
        if reset.get("deassertion") != "synchronous":
            return None, _map_error(
                f"reset '{reset_id}' requires synchronous deassertion; "
                "asynchronous release is not a supported formal contract")
        if (not isinstance(destinations, list) or not destinations
                or any(domain not in names for domain in destinations)):
            return None, _map_error(f"reset '{reset_id}' has invalid destination_domains")
        for field in ("synchronizer_stages", "minimum_assert_cycles",
                      "deassertion_latency_cycles"):
            value = reset.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                return None, _map_error(f"reset '{reset_id}' requires {field} >= 1")
        dependencies = reset.get("dependencies", [])
        if not isinstance(dependencies, list):
            return None, _map_error(f"reset '{reset_id}'.dependencies must be a list")
        reset_ids.add(reset_id)
        canonical_resets.append(dict(reset, name=port))
    if any(dependency not in reset_ids for reset in canonical_resets
           for dependency in reset.get("dependencies", [])):
        return None, _map_error("reset dependency references an unknown reset id")
    dependencies = {
        reset["id"]: list(reset.get("dependencies", []))
        for reset in canonical_resets
    }
    visiting = set()
    visited = set()

    def _visit_reset(reset_id):
        if reset_id in visiting:
            return False
        if reset_id in visited:
            return True
        visiting.add(reset_id)
        for dependency in dependencies[reset_id]:
            if not _visit_reset(dependency):
                return False
        visiting.remove(reset_id)
        visited.add(reset_id)
        return True

    if any(not _visit_reset(reset_id) for reset_id in dependencies):
        return None, _map_error("reset dependencies must be acyclic")

    synchronous_resets = obj.get("synchronous_reset_intent", [])
    if not isinstance(synchronous_resets, list):
        return None, _map_error("'synchronous_reset_intent' must be a list")
    synchronous_ids = set()
    canonical_synchronous_resets = []
    for index, reset in enumerate(synchronous_resets):
        if not isinstance(reset, dict):
            return None, _map_error(
                f"synchronous_reset_intent[{index}] must be an object")
        reset_id = reset.get("id")
        port = reset.get("port")
        destinations = reset.get("destination_domains")
        if (not isinstance(reset_id, str) or not reset_id
                or reset_id in synchronous_ids or reset_id in reset_ids
                or not isinstance(port, str) or not port):
            return None, _map_error(
                f"synchronous_reset_intent[{index}] has invalid/duplicate id or port")
        if reset.get("polarity") not in ("active_low", "active_high"):
            return None, _map_error(
                f"synchronous reset '{reset_id}' requires polarity")
        if (reset.get("assertion") != "synchronous"
                or reset.get("deassertion") != "synchronous"):
            return None, _map_error(
                f"synchronous reset '{reset_id}' requires synchronous "
                "assertion and deassertion")
        if (not isinstance(destinations, list) or not destinations
                or any(domain not in names for domain in destinations)):
            return None, _map_error(
                f"synchronous reset '{reset_id}' has invalid destination_domains")
        if reset.get("synchronizer_stages") != 0:
            return None, _map_error(
                f"synchronous reset '{reset_id}' requires synchronizer_stages=0")
        synchronized_signal = reset.get("synchronized_signal")
        if not isinstance(synchronized_signal, str) or not synchronized_signal:
            return None, _map_error(
                f"synchronous reset '{reset_id}' requires synchronized_signal")
        synchronous_ids.add(reset_id)
        canonical_synchronous_resets.append(dict(reset))

    inputs = obj.get("inputs")
    if not isinstance(inputs, list):
        return None, _map_error("'inputs' must be a list")
    synchronous_input_ports = {
        item.get("name") for item in inputs
        if isinstance(item, dict)
        and item.get("classification") == "synchronous_reset"
    }
    declared_synchronous_ports = {
        reset["port"] for reset in canonical_synchronous_resets
    }
    if synchronous_input_ports != declared_synchronous_ports:
        return None, _map_error(
            "synchronous reset inputs and synchronous_reset_intent[] "
            "declarations do not match")

    formal_crossings = obj.get("formal_crossings", [])
    if not isinstance(formal_crossings, list):
        return None, _map_error("'formal_crossings' must be a list")
    crossing_ids = set()
    supported_protocols = {
        "level", "pulse", "toggle", "gray", "handshake", "qualifier",
        "mcp", "fifo", "async_fifo", "reconvergence",
    }
    for index, crossing in enumerate(formal_crossings):
        if not isinstance(crossing, dict):
            return None, _map_error(
                f"formal_crossings[{index}] must be an object")
        crossing_id = crossing.get("id")
        protocol = crossing.get("protocol")
        source_domain = crossing.get("source_domain")
        destination_domain = crossing.get("destination_domain")
        source_signal = crossing.get("source_signal")
        if (not isinstance(crossing_id, str) or not crossing_id
                or crossing_id in crossing_ids):
            return None, _map_error(
                f"formal_crossings[{index}] has invalid/duplicate id")
        if protocol not in supported_protocols:
            return None, _map_error(
                f"formal crossing '{crossing_id}' has unsupported protocol")
        if source_domain not in names or destination_domain not in names:
            return None, _map_error(
                f"formal crossing '{crossing_id}' references an unknown clock domain")
        if not isinstance(source_signal, str) or not source_signal:
            return None, _map_error(
                f"formal crossing '{crossing_id}' requires source_signal")
        if "primary_input" in crossing and not isinstance(
                crossing["primary_input"], bool):
            return None, _map_error(
                f"formal crossing '{crossing_id}'.primary_input must be boolean")
        latency = crossing.get("max_latency_cycles")
        if latency is not None and (
                not isinstance(latency, int) or isinstance(latency, bool)
                or latency < 1):
            return None, _map_error(
                f"formal crossing '{crossing_id}' requires "
                "max_latency_cycles >= 1")
        if protocol in ("level", "pulse", "toggle", "reconvergence"):
            if not isinstance(crossing.get("destination_signal"), str):
                return None, _map_error(
                    f"formal crossing '{crossing_id}' requires destination_signal")
        if protocol in ("handshake", "qualifier", "mcp"):
            qualifier = crossing.get("request") or crossing.get("qualifier")
            if not isinstance(qualifier, str) or not qualifier:
                return None, _map_error(
                    f"formal crossing '{crossing_id}' requires request or qualifier")
            liveness = (
                crossing.get("eventual_response"),
                crossing.get("fairness_signal"),
                crossing.get("fairness_justification"),
            )
            if any(value is not None for value in liveness) and not all(
                    isinstance(value, str) and value for value in liveness):
                return None, _map_error(
                    f"formal crossing '{crossing_id}' liveness requires "
                    "eventual_response, fairness_signal, and fairness_justification")
        if protocol in ("fifo", "async_fifo"):
            for field in ("write_pointer", "read_pointer", "write_enable",
                          "full", "read_enable", "empty"):
                if not isinstance(crossing.get(field), str) or not crossing[field]:
                    return None, _map_error(
                        f"formal crossing '{crossing_id}' requires {field}")
        crossing_ids.add(crossing_id)
    external_domains = sorted({
        item.get("source_domain") for item in obj.get("inputs", [])
        if isinstance(item, dict) and item.get("async_by_construction") is True
        and item.get("source_domain") not in names
    } - {None})
    canonical = dict(obj, clock_domains=canonical_clocks + [
        {"name": domain, "kind": "asynchronous"}
        for domain in external_domains],
                     resets=canonical_resets)
    canonical["$schema"] = "clock-reset-domain-map/v1"
    normalized, error = _clock_reset_domain_map_v1(canonical, source)
    if error:
        return None, error
    normalized["schema"] = "clock-reset-domain-map/v2"
    normalized["clock_intent"] = {clock["name"]: clock for clock in canonical_clocks}
    normalized["reset_intent"] = {reset.get("id"): reset
                                  for reset in canonical_resets}
    normalized["synchronous_reset_intent"] = {
        reset["id"]: reset for reset in canonical_synchronous_resets
    }
    normalized["formal_crossings"] = formal_crossings
    return normalized, None


def _normalize_domain_map_input(dm):
    """Return (normalized_contract, error) for inline or path domain maps."""
    if dm is None:
        return None, "domain_map is required for CDC/RDC signoff"
    source = "inline"
    if isinstance(dm, str):
        source = dm
        candidates = (dm, os.path.join("/input", os.path.basename(dm)))
        loaded = None
        read_error = None
        for cand in candidates:
            try:
                if os.path.isfile(cand):
                    with open(cand, encoding="utf-8") as f:
                        loaded = json.load(f)
                    source = cand
                    break
            except (OSError, ValueError) as exc:
                read_error = str(exc)
                break
        if loaded is None:
            detail = f": {read_error}" if read_error else ""
            return None, _map_error(
                f"domain_map path '{dm}' could not be read{detail}")
        dm = loaded
    if not isinstance(dm, dict):
        return None, _map_error("domain_map must be an object or JSON file path")

    schema = dm.get("$schema")
    if schema is not None:
        if schema == "clock-reset-domain-map/v1":
            return _clock_reset_domain_map_v1(dm, source)
        if schema == "clock-reset-domain-map/v2":
            return _clock_reset_domain_map_v2(dm, source)
        return None, _map_error(f"unsupported schema '{schema}'")

    flat = _flatten_domain_map(dm)
    if not flat:
        return None, _map_error(
            "map did not contain a supported flat or clocks/resets mapping")
    return {
        "flat": flat, "reset_flat": flat,
        "schema": "legacy-flat-domain-map",
        "source": source, "obligations": [], "census": {},
        "bus_protocols": {}, "clock_intent": {}, "reset_intent": {},
        "formal_crossings": [],
    }, None


def _resolve_domain_map(dm):
    """Accept a domain map as an inline dict (flat or schema), or a PATH to a
    JSON file, and return the flat {net: domain} dict. Returns None when it
    cannot be resolved (so the caller's fail-closed guard fires). A path is
    tried as given and, as a fallback, under /input by basename (container
    mount)."""
    normalized, _error = _normalize_domain_map_input(dm)
    return normalized["flat"] if normalized else None


def _domain_map_failure(scenario, error):
    kind = "RDC" if scenario == "rdc_signoff" else "CDC"
    return _cde(
        objective=f"{kind} signoff",
        status="failed",
        error=error,
        validation={"verdict": "fail", "note": error},
        assumptions=["fail-closed: malformed or unsupported domain maps are "
                     "not projected, guessed, or treated as zero crossings"],
    )


def dispatch(params):
    s = params.get("scenario") or "cdc_signoff"
    if s not in ("cdc_signoff", "rdc_signoff", "synchronizer_verify", "reconvergence"):
        return _cde(objective="cdc/rdc signoff", status="failed",
                    error=f"unknown scenario '{s}'", validation={"verdict": "fail"})
    params = dict(params)
    normalized, map_error = _normalize_domain_map_input(params.get("domain_map"))
    if map_error:
        return _domain_map_failure(s, map_error)
    params["domain_map"] = normalized["flat"]
    params["_domain_map_contract"] = normalized
    if normalized["bus_protocols"]:
        protocols = dict(normalized["bus_protocols"])
        protocols.update(params.get("bus_protocols") or {})
        params["bus_protocols"] = protocols

    if params.get("reset_domain_map") is not None:
        if normalized.get("schema") != "legacy-flat-domain-map":
            return _domain_map_failure(
                s, "a separate reset_domain_map cannot override schema-backed intent")
        reset_normalized, reset_error = _normalize_domain_map_input(
            params.get("reset_domain_map"))
        if reset_error:
            return _domain_map_failure(s, reset_error)
        params["reset_domain_map"] = reset_normalized["reset_flat"]
        params["_reset_domain_map_contract"] = reset_normalized
    elif s == "rdc_signoff":
        params["reset_domain_map"] = normalized["reset_flat"]
    if not shutil.which("yosys"):
        return _cde(objective="cdc/rdc signoff", status="failed",
                    error="yosys not found on PATH", validation={"verdict": "fail"})
    if s == "rdc_signoff":
        return _analyze_rdc(params)
    # cdc_signoff, synchronizer_verify, reconvergence all analyze clock-domain
    # crossings; the latter two refine the reporting (see _post_scenario).
    res = _analyze(params, "CDC")
    return _post_scenario(res, s)


def _post_scenario(res, scenario):
    """Refine a CDC result for the synchronizer_verify / reconvergence scenarios.
    Never upgrades a verdict; only ADDS scenario-specific evidence and can DOWNGRADE
    a pass to fail when the stricter scenario check finds an issue. Leaves a
    fail/not_assessable result untouched."""
    if not isinstance(res, dict) or scenario == "cdc_signoff":
        return res
    signoff = res.get("signoff_evidence") if isinstance(res.get("signoff_evidence"), dict) else {}
    if not signoff or signoff.get("verdict") == "not_assessable":
        return res
    # KEY ABSENT and MEASURED ZERO ARE DIFFERENT ANSWERS.
    # This read `signoff.get("crossings", []) or []`, so an evidence block with
    # no `crossings` key produced an empty list, every stricter check below found
    # nothing, and the inherited `pass` stood. MEASURED: evidence lacking the key
    # yielded `crossings_checked: 0` and verdict `pass` -- byte-identical to a
    # genuine single-clock-domain design that really has zero crossings.
    #
    # These scenarios exist ONLY to apply a stricter check than cdc_signoff. A
    # stricter check that silently verified nothing is worse than not running it,
    # because the envelope then carries evidence of a check that never happened.
    if "crossings" not in signoff:
        signoff["scenario_check_skipped"] = {
            "scenario": scenario,
            "reason": ("no `crossings` key in the signoff evidence, so the "
                       "stricter %s check had nothing to examine. This is NOT "
                       "the same as a design with zero crossings: that case "
                       "carries an explicit empty list." % scenario),
        }
        if res.get("validation", {}).get("verdict") == "pass":
            res["validation"] = {
                "verdict": "not_assessable",
                "note": ("%s could not run: the crossing inventory was absent "
                         "from the evidence" % scenario)}
            signoff["verdict"] = "not_assessable"
        return res
    crossings = signoff.get("crossings") or []
    synchronized = set(signoff.get("synchronizer_inventory", []) or [])

    if scenario == "synchronizer_verify":
        # Every crossing MUST land on a recognized synchronizer; enumerate the
        # ones that do not (single-flop / unsynchronized) as explicit failures.
        missing = [c for c in crossings
               if (c.get("to_stage") or c.get("to")) not in synchronized]
        signoff["synchronizer_verification"] = {
            "crossings_checked": len(crossings),
            "with_synchronizer": len(crossings) - len(missing),
            "missing_synchronizer": missing,
        }
        metric = res.setdefault("results", {}).setdefault(
            "synchronizer_verification_failures", {
                "unit": "count", "class": "gating",
                "basis": "structural_netlist_analysis", "closes_at": "== 0"})
        metric["value"] = len(missing)
        validation = res.setdefault("validation", {})
        validation.setdefault("checks", {})["synchronizer_pass"] = not missing
        if missing and res.get("validation", {}).get("verdict") == "pass":
            validation["verdict"] = "fail"
            validation["note"] = \
                f"{len(missing)} crossing(s) lack a 2-flop synchronizer"
            signoff["verdict"] = "fail"
        res["objective"] = res.get("objective", "").replace("CDC signoff", "synchronizer verification")

    elif scenario == "reconvergence":
        # Reconvergence = two or more crossings from the same source domain that
        # fan into the SAME destination flop -- separately-synchronized bits can
        # skew and glitch. Flag every destination flop with >1 incoming crossing.
        by_dest = {}
        missing_destination = []
        for c in crossings:
            destination = c.get("to") or c.get("to_stage")
            if destination is None:
                missing_destination.append(c)
                continue
            by_dest.setdefault(destination, []).append(c)
        if missing_destination:
            signoff["scenario_check_skipped"] = {
                "scenario": scenario,
                "reason": ("%d crossing(s) have no destination identity; "
                           "reconvergence is not assessable"
                           % len(missing_destination)),
                "crossings": missing_destination,
            }
            res.setdefault("results", {}).setdefault(
                "reconvergence_violations", {})["value"] = None
            validation = res.setdefault("validation", {})
            validation.get("checks", {}).pop("reconvergence_pass", None)
            validation["verdict"] = "not_assessable"
            validation["note"] = signoff["scenario_check_skipped"]["reason"]
            signoff["verdict"] = "not_assessable"
            return res
        reconv = {d: cs for d, cs in by_dest.items() if len(cs) > 1}
        signoff["reconvergence"] = {
            "destinations_with_multiple_crossings": len(reconv),
            "reconvergent": [{"dest": d, "sources": cs} for d, cs in reconv.items()],
        }
        metric = res.setdefault("results", {}).setdefault(
            "reconvergence_violations", {
                "unit": "count", "class": "gating",
                "basis": "destination_fanin_analysis", "closes_at": "== 0"})
        metric["value"] = len(reconv)
        validation = res.setdefault("validation", {})
        validation.setdefault("checks", {})["reconvergence_pass"] = not reconv
        if reconv and res.get("validation", {}).get("verdict") == "pass":
            validation["verdict"] = "fail"
            validation["note"] = \
                f"{len(reconv)} reconvergent destination(s) detected"
            signoff["verdict"] = "fail"
        res["objective"] = res.get("objective", "").replace("CDC signoff", "reconvergence analysis")

    return res


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
