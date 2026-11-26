#!/usr/bin/env python3
"""rtl_lint_utils.py -- real RTL lint / style checking via Verible.

Three scenarios:
    * lint_gate -- run both lint and canonical-format verification against one
        immutable source snapshot. This is the complete stage gate.
  * lint   -- run `verible-verilog-lint` over Verilog/SystemVerilog sources
    (optional `--rules`, `--waiver_files`); parse the per-line violations and
    report a count + per-rule breakdown. Zero violations => pass.
  * format -- run `verible-verilog-format` in check mode (`--verify`) to report
    whether the sources are already canonically formatted.

Node-agnostic: RTL lint is independent of the PDK/node. Results conform to the
Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "rtl-lint"
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


def _enforce_complete_gate_progress(results):
    """A complete lint gate without both progress families is not evidence."""
    signoff = results.get("signoff_evidence")
    if not isinstance(signoff, dict) or signoff.get("gate_scope") != "complete":
        return
    progress = results.get("progress")
    families = progress.get("families") if isinstance(progress, dict) else None
    missing = [name for name in ("lint_violations", "format")
               if not isinstance(families, dict)
               or not isinstance(families.get(name), dict)
               or not isinstance(families[name].get("residual"), (int, float))]
    if not missing:
        return
    error = ("complete lint gate is missing assessable progress family/families: "
             + ", ".join(missing))
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

    _enforce_complete_gate_progress(results)

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
                       ("Review evidence", "signoff_evidence")):
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
        if (low.endswith((".log", ".sh", ".txt"))
                or low == "run_command.txt"):
            return "logs"
        return "results"

    moves = {}
    for entry in list(os.listdir(root)):
        full = os.path.join(root, entry)
        if not os.path.isfile(full):
            continue
        dest = _classify(entry)
        if dest is None:
            continue
        target = os.path.join(root, dest, entry)
        if os.path.exists(target):
            raise FileExistsError("refusing to overwrite artifact: " + target)
        os.replace(full, target)
        moves[entry] = dest + "/" + entry
        moves[full] = target
    return moves


def _relocate_output_refs(value, moves):
    if isinstance(value, str):
        return moves.get(value, value)
    if isinstance(value, dict):
        return {key: _relocate_output_refs(item, moves) for key, item in value.items()}
    if isinstance(value, list):
        return [_relocate_output_refs(item, moves) for item in value]
    return value


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
    if plines:
        L += ["## Provenance", ""] + plines + [""]
    L += ["## Where to find more", "",
          "- `common_design_envelope.json` \u2014 full machine-readable envelope (this dir)",
          "- `logs/` \u2014 verbatim Verible output and the exact run command", ""]
    return "\n".join(L)


def _write_summary_md(results):
    return  # option b: SUMMARY.md removed (tool emits REPORT.md; agent emits EXECUTIVE_SUMMARY.md)
    path = os.path.join(_OUTPUT_DIR, "SUMMARY.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render_summary_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def save_final_results(results):
    results = _relocate_output_refs(results, _organize_output())
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


def _bin(name):
    for c in (name, "/usr/local/bin/" + name, "/usr/bin/" + name):
        if shutil.which(c) or os.path.exists(c):
            return shutil.which(c) or c
    return None


def _verible_version():
    b = _bin("verible-verilog-lint")
    if not b:
        return "verible"
    try:
        out = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return "verible " + txt.splitlines()[0] if txt else "verible"
    except Exception:
        return "verible"


def _canonical_stage():
    """The registry stage key this tool's envelopes belong to.

    Measured on the live corpus: envelopes that stamp no `stage` resolve to no
    registry entry, report NO METRIC, and a missing metric is indistinguishable
    downstream from a closed gate. The tool names its own gate rather than
    leaving it to the caller. Resolved through the registry so the constant
    lives in ONE place.
    """
    try:
        import cde_progress as _cp
        return _cp.normalize_stage(TOOL) or "lint"
    except Exception:
        return "lint"


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
        base.setdefault("basis", "agent_read_of_lint_report" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_lint_report")


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


def _cde(objective, status, results=None, signoff=None, assumptions=None,
         validation=None, provenance=None, inputs_ref=None, qor=None,
         error=None, engine="verible-verilog-lint"):
    validation = validation or {"verdict": "review"}
    provenance = dict(provenance or {})
    env = {
        "tool": TOOL, "stage": _canonical_stage(),
        "status": status, "objective": objective,
        # ROOT VERDICT, ALWAYS. `finalize_cde.py` reads the gate verdict from
        # the CDE ROOT and refuses (by design) to invent one, so a tool that
        # recorded it only under `validation.verdict` failed closure on every
        # single attempt and cost a hand-repair cycle each time. This is a
        # same-document copy of an already-measured field -- it adds no
        # information and can never disagree with `validation.verdict`.
        "verdict": validation.get("verdict"),
        "tools_used": [{"name": engine, "version": _verible_version()}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "static_lint"},
        "validation": validation,
        "provenance": provenance,
    }
    if error:
        env["error"] = error
    _enforce_task_identity_handoff(env)
    return env


_HOST_OWNED_TASK_IDENTITY_FIELDS = (
    "run_id",
    "task_uuid",
    "task_dx_id",
    "task_identity_sha256",
)


def _enforce_task_identity_handoff(results):
    """Name the host as the owner of task/run identity, and refuse to claim it.

    The OTHER half of the closure-stamp defect: a raw CDE that carries no task
    reference at all looks identical to one whose reference was dropped, so
    every attempt re-diagnosed "why did finalize refuse to stamp this". The tool
    cannot resolve a canonical owner -- only the host knows which task claimed
    the attempt, and a fabricated `run_id` is evidence laundering, not a fix. So
    it states the handoff explicitly instead of leaving an absence to interpret,
    and fails closed if any caller tries to inject identity through it.
    """
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
        "raw RTL-lint tool output contains host-owned task/run identity "
        "field(s): " + ", ".join(claimed)
        + "; leave them absent and finalize the attempt on the host with "
          "catalog/finalize_cde.py")
    provenance["task_identity_state"] = "rejected_untrusted_tool_stamp"
    results["status"] = "failed"
    results["error"] = error
    results["verdict"] = "fail"
    validation = results.get("validation")
    if not isinstance(validation, dict):
        validation = {}
        results["validation"] = validation
    validation["verdict"] = "fail"
    validation["stage_closure_eligible"] = False
    validation["note"] = error



def _sources(params):
    srcs = _as_list(params.get("sources") or params.get("files"))
    src = params.get("source") or params.get("file")
    if src:
        srcs = [src] + srcs
    for source in srcs:
        if not source or not os.path.isfile(str(source)):
            raise FileNotFoundError("lint source not found: " + str(source))
    return [str(s) for s in srcs]


# --- DX-142: verible diagnostic-line parsing (was: silent under-count) -----
# Verible diagnostic shapes confirmed against the pinned release
# (v0.0-4141-g09a245fe, see Containerfile) by actually running the binary --
# NOT guessed:
#   <file>:<line>:<col>: <message> [<rule-name>]              single-column
#   <file>:<line>:<col_start>-<col_end>: <message> [<rule>]   COLUMN RANGE --
#       this shape was silently dropped by the old single-integer-column
#       regex, e.g. ".../crc16_ccitt.v:44:19-25: ... [explicit-function-lifetime]"
#   <file>:<line>:<col(-col)>: syntax error at token "..."    NO trailing
#       "[rule]" bracket -- also silently dropped by the old regex, which
#       required one.
# A leading glog-style tool-fatal line such as
#   "E0924 21:45:19.803065 3681056 verilog-linter.cc:111] Can't read '...'"
# never matches this shape (checked against the hint regex below) because
# there is no "<digits>[-<digits>]:" immediately followed by whitespace
# right after the would-be file portion.
#
# `verible-verilog-lint` was probed for a structured/JSON emission mode
# (--print_diagnostics=json, per publicly documented Verible builds) and it
# does NOT exist on the pinned v0.0-4141-g09a245fe release (--helpfull has no
# json/xml/machine-readable flag at all -- confirmed by running --helpfull
# against the actual pinned binary). Structured output is therefore not an
# option for this tool version; the regex is hardened instead, with a
# reconciliation guard so a shape this hardening still misses fails loudly.
_VIOLATION_LINE_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+)(?:-(?P<col_end>\d+))?:\s+"
    r"(?P<message>.*?)(?:\s+\[(?P<rule>[^\]]+)\])?\s*$")
# Loose, independently-derived detector of "this line looks like a verible
# diagnostic", used ONLY to reconcile against the strict parser above. If a
# line trips this hint but the strict parser cannot turn it into a counted
# violation, that is an unrecognised diagnostic shape and the caller must
# fail loudly rather than silently under-report (this exact bug already
# produced one false clean-pass gate closure -- see
# tickets/lint/mytop4-hiersoc-crc16_ccitt-lint-verible-column-range-undercount.md).
_DIAG_LINE_HINT_RE = re.compile(r"^.+?:\d+:\d+(?:-\d+)?:\s")


def _parse_verible_lint_output(out):
    """Parse verible-verilog-lint's log text into (count, rules_hit).

    Counts EVERY diagnostic line -- rule violations (single-column or
    column-range) AND syntax errors (no rule bracket) -- because both
    represent a real lint-stage failure that must not be silently dropped.
    Reconciles the strict parse against a loose diagnostic-line detector and
    raises RuntimeError if any hinted line could not be accounted for,
    instead of returning a smaller count.
    """
    rules_hit = {}
    count = 0
    hinted = 0
    unaccounted = []
    for line in out.splitlines():
        if not _DIAG_LINE_HINT_RE.match(line):
            continue
        hinted += 1
        m = _VIOLATION_LINE_RE.match(line)
        if not m:
            unaccounted.append(line)
            continue
        count += 1
        rule = m.group("rule") or "syntax-error-or-unclassified"
        rules_hit[rule] = rules_hit.get(rule, 0) + 1
    if unaccounted or count != hinted:
        raise RuntimeError(
            "rtl-lint: verible-verilog-lint emitted " + str(hinted)
            + " diagnostic-shaped line(s) but only " + str(count)
            + " could be parsed into a violation; refusing to silently "
              "under-report. Unparsed line(s) (up to 5): "
            + repr(unaccounted[:5]))
    return count, rules_hit


def _failed_lint_run(srcs, elapsed, out, error, note):
    return _cde(
        objective="RTL lint of " + str(len(srcs)) + " source(s)",
        status="failed", error=error,
        inputs_ref={"sources": srcs},
        provenance={"verible": _verible_version(),
                    "runtime_s": round(elapsed, 3),
                    "log": "logs/verible_lint.log"},
        validation={"verdict": "fail", "note": note})


def _lint(params):
    b = _bin("verible-verilog-lint")
    if not b:
        return _cde(objective="RTL lint", status="failed",
                    error="verible-verilog-lint not found on PATH",
                    validation={"verdict": "fail"})
    srcs = _sources(params)
    if not srcs:
        return _cde(objective="RTL lint", status="failed",
                    error="no source found: provide `source`/`sources` (.v/.sv)",
                    validation={"verdict": "fail"})
    cmd = [b]
    rules = params.get("rules")
    if rules:
        cmd.append("--rules=" + (",".join(rules) if isinstance(rules, list) else str(rules)))
    ruleset = params.get("ruleset")
    if ruleset:
        cmd.append("--ruleset=" + str(ruleset))
    rules_config = params.get("rules_config")
    if rules_config:
        cmd.append("--rules_config=" + str(rules_config))
    if str(params.get("rules_config_search", "")).lower() in ("1", "true", "yes"):
        cmd.append("--rules_config_search")
    waivers = params.get("waiver_files")
    if waivers:
        wl = waivers if isinstance(waivers, list) else [waivers]
        cmd.append("--waiver_files=" + ",".join(str(w) for w in wl))
    # Automatic fixing: autofix mode (no|patch|inplace|generate-waiver) + output file.
    autofix = params.get("autofix")
    if autofix:
        cmd.append("--autofix=" + str(autofix))
        autofix_out = params.get("autofix_output_file")
        if autofix_out:
            cmd.append("--autofix_output_file=" + str(autofix_out))
    cmd += srcs
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "verible_lint.log"), "w").write(out)
    # verible-verilog-lint exits 0 (clean) or 1 (violations found) for a
    # completed lint pass; anything else (e.g. 2 == "Can't read <file>") means
    # the tool never actually finished linting. Reporting lint_violations=0 in
    # that case would be a false clean pass, so treat it as a tool failure.
    if proc.returncode not in (0, 1):
        return _failed_lint_run(
            srcs, elapsed, out,
            "verible-verilog-lint exited " + str(proc.returncode)
            + " (tool-fatal, not a completed lint verdict): "
            + out.strip()[-2000:],
            "tool did not complete a lint pass; see error")
    try:
        count, rules_hit = _parse_verible_lint_output(out)
    except RuntimeError as exc:
        return _failed_lint_run(
            srcs, elapsed, out, str(exc),
            "unparseable verible diagnostic output -- see error")
    expected_returncode = 0 if count == 0 else 1
    if proc.returncode != expected_returncode:
        return _failed_lint_run(
            srcs, elapsed, out,
            "verible-verilog-lint exit/diagnostic mismatch: exit="
            + str(proc.returncode) + ", parsed_diagnostics=" + str(count)
            + "; refusing a potentially false clean result",
            "verible exit status disagrees with parsed diagnostics")
    subcheck_verdict = "pass" if count == 0 else "fail"
    verdict = "not_assessable" if count == 0 else "fail"
    return _cde(
        objective="RTL lint of " + str(len(srcs)) + " source(s)", status="completed",
        # (A) GATING -- the deterministic parse of verible's own output. This is
        # the ONLY class a consumer may close on. `rules` below is a breakdown of
        # this same count, NOT an independent gate.
        results={"lint_violations": {
            "value": count, "unit": "count",
            "class": "gating", "basis": "parsed_verible_lint_output",
            "closes_at": "== 0",
            "note": ("Counted from verible's own diagnostic lines. A null here "
                     "means NOT ASSESSED and must never read as zero. Waived "
                     "rules are excluded by verible via --waiver_files, so this "
                     "count is already post-waiver.")}},
        qor={"lint_violations": count, "clean": count == 0,
             "rules": rules_hit},
        signoff={
            "gate_scope": "diagnostic_subcheck",
            "native_exit_codes": {"verible_lint": proc.returncode},
            "stage_closure_eligible": False,
            "lint_violations": count, "clean": count == 0,
            # (B) DIAGNOSTIC -- measured, non-gating. This is the repair surface:
            # which rules fired and how often is what tells you WHERE to look.
            "diagnostics": {
                "class": "diagnostic",
                "basis": "parsed_verible_lint_output",
                "rules_hit": rules_hit,
                "distinct_rules": len(rules_hit),
                "note": ("Per-rule breakdown of the gating count. Sums to "
                         "lint_violations; it is not a second gate.")},
            # (C) DESCRIPTIVE -- run configuration, expected to hold steady across
            # attempts. Kept separate so the stall machinery does not read a
            # constant as a converged metric.
            "descriptive": {
                "class": "descriptive", "basis": "run_configuration",
                "engine": "verible-verilog-lint",
                "source_count": len(srcs),
                "rules_config": rules_config or "none",
                "autofix": autofix or "off",
                "elapsed_s": round(elapsed, 3)},
            "rules": rules_hit, "files": [os.path.basename(s) for s in srcs],
            "rules_config": rules_config or "none",
            "autofix": autofix or "off",
            "report": "logs/verible_lint.log",
            # (D) MODEL-AUTHORED -- advisory only, never closes or moves a gate.
            "interpretation": _labelled_interpretation(
                params.get("interpretation")),
            "interpretation_crosscheck": _crosscheck_interpretation(
                params.get("interpretation"), count, "lint_violations")},
        inputs_ref={"sources": srcs},
        assumptions=["Verible default rule set unless --rules/--ruleset given; "
                     "waivers applied via --waiver_files"],
        validation={"verdict": verdict,
                "subcheck_verdict": subcheck_verdict,
                "stage_closure_eligible": False,
                    "note": ("lint clean" if count == 0
                     else str(count) + " lint violation(s)")
                    + "; run lint_gate for stage closure"},
        provenance={"verible": _verible_version(), "runtime_s": round(elapsed, 3),
                "log": "logs/verible_lint.log"},
    )


def _formatted_proposal_name(source, used_names=None):
    """Return a flat proposal name that keeps a valid HDL extension."""
    used_names = used_names if used_names is not None else set()
    base = os.path.basename(source)
    stem, suffix = os.path.splitext(base)
    candidate = stem + ".formatted" + suffix if suffix else base + ".formatted"
    if candidate in used_names:
        source_hash = (_hash_input_file(source) or {}).get("sha256", "unknown")[:12]
        base = stem + "." + source_hash
        candidate = base + ".formatted" + suffix
        index = 2
        while candidate in used_names:
            candidate = base + "." + str(index) + ".formatted" + suffix
            index += 1
    used_names.add(candidate)
    return candidate


def _format(params):
    b = _bin("verible-verilog-format")
    if not b:
        return _cde(objective="RTL format check", status="failed",
                    engine="verible-verilog-format",
                    error="verible-verilog-format not found on PATH",
                    validation={"verdict": "fail"})
    srcs = _sources(params)
    if not srcs:
        return _cde(objective="RTL format check", status="failed",
                    engine="verible-verilog-format",
                    error="no source found: provide `source`/`sources` (.v/.sv)",
                    validation={"verdict": "fail"})
    unformatted = []
    logs = []
    native_exits = {}
    # Formatter style knobs (Verible: --column_limit / --indentation_spaces). When
    # `write_formatted` is set, emit the canonically formatted file to /output
    # instead of only verifying.
    style = []
    col = params.get("column_limit")
    if col is not None:
        style.append("--column_limit=" + str(int(col)))
    ind = params.get("indentation_spaces")
    if ind is not None:
        style.append("--indentation_spaces=" + str(int(ind)))
    write_formatted = str(params.get("write_formatted", "")).lower() in ("1", "true", "yes")
    formatted_files = []
    format_proposals = []
    proposal_errors = []
    used_names = set()
    t0 = time.time()
    for s in srcs:
        cmd = [b] + style + ["--verify", s]
        _save_run_command(cmd, "run_command_format.txt")
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
        native_exits[s] = proc.returncode
        logs.append("$ " + " ".join(cmd) + "\n" + proc.stdout + proc.stderr)
        if proc.returncode != 0:
            unformatted.append(os.path.basename(s))
        if write_formatted and proc.returncode != 0:
            fcmd = [b] + style + [s]
            _save_run_command(fcmd, "run_command_format_proposal.txt")
            fproc = subprocess.run(fcmd, capture_output=True, text=True, cwd=_WORK_DIR)
            if fproc.returncode == 0:
                proposal_name = _formatted_proposal_name(s, used_names)
                fp = os.path.join(_OUTPUT_DIR, proposal_name)
                with open(fp, "w", encoding="utf-8") as proposal_file:
                    proposal_file.write(fproc.stdout)
                verify_cmd = [b] + style + ["--verify", fp]
                _save_run_command(verify_cmd, "run_command_format_proposal_verify.txt")
                verify_proc = subprocess.run(
                    verify_cmd, capture_output=True, text=True, cwd=_WORK_DIR)
                verified = verify_proc.returncode == 0
                logs.append("$ " + " ".join(verify_cmd) + "\n"
                            + verify_proc.stdout + verify_proc.stderr)
                proposal = {
                    "source": s,
                    "proposal": "results/" + proposal_name,
                    "source_hash": _hash_input_file(s),
                    "proposal_hash": _hash_input_file(fp),
                    "verified_canonical": verified,
                }
                format_proposals.append(proposal)
                if verified:
                    formatted_files.append("results/" + proposal_name)
                else:
                    proposal_errors.append(
                        proposal_name + " did not pass formatter re-verification")
            else:
                proposal_errors.append(
                    os.path.basename(s) + " formatter exited "
                    + str(fproc.returncode) + " while creating a proposal")
    elapsed = time.time() - t0
    open(os.path.join(_OUTPUT_DIR, "verible_format.log"), "w").write("\n\n".join(logs))
    count = len(unformatted)
    subcheck_verdict = "pass" if count == 0 else "fail"
    verdict = "not_assessable" if count == 0 else "fail"
    return _cde(
        objective="RTL format check of " + str(len(srcs)) + " source(s)",
        status="completed", engine="verible-verilog-format",
        results={"unformatted_files": {"value": count, "unit": "count"}},
        qor={"unformatted_files": count, "all_formatted": count == 0},
        signoff={"gate_scope": "diagnostic_subcheck",
                 "native_exit_codes": {"verible_format": native_exits},
             "stage_closure_eligible": False,
             "unformatted_files": unformatted, "all_formatted": count == 0,
                 "column_limit": col, "indentation_spaces": ind,
                 "formatted_files": formatted_files,
                 "format_proposals": format_proposals,
                 "proposal_errors": proposal_errors,
                 "report": "logs/verible_format.log"},
        inputs_ref={"sources": srcs},
        assumptions=["--verify check mode: nonzero exit means the file is not "
                     "canonically formatted"],
        validation={"verdict": verdict,
                "subcheck_verdict": subcheck_verdict,
                "stage_closure_eligible": False,
                    "note": ("all sources canonically formatted" if count == 0
                     else str(count) + " source(s) need formatting")
                    + "; run lint_gate for stage closure"},
        provenance={"verible": _verible_version(), "runtime_s": round(elapsed, 3),
                "log": "logs/verible_format.log"},
    )


def _metric_value(envelope, key):
    value = (envelope.get("results") or {}).get(key)
    if isinstance(value, dict):
        value = value.get("value")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _write_subrun_cde(name, envelope):
    path = os.path.join(_OUTPUT_DIR, name)
    with open(path, "w", encoding="utf-8") as subrun_file:
        json.dump(envelope, subrun_file, indent=2, default=str)
    return "results/" + name


_NEVER_STYLE_RULES = ("syntax-error-or-unclassified",)


def _flag_false(value):
    return str(value).strip().lower() in ("0", "false", "no", "not_gating")


def _declared_style_rules(params):
    """Return (rules, error). Style classification is caller-DECLARED only."""
    raw = params.get("style_rules")
    classes = params.get("rule_classes")
    if raw is None and isinstance(classes, dict):
        raw = classes.get("style")
    if raw is None:
        return [], None
    raw = _as_list(raw)
    rules = sorted({str(r).strip().lstrip("+-") for r in raw if str(r).strip()})
    bad = [r for r in rules if r in _NEVER_STYLE_RULES]
    if bad:
        return [], ("style_rules may not classify parse/syntax diagnostics as "
                    "style: " + ", ".join(bad))
    return rules, None


def _lint_gate(params):
    """Run the complete lint stage gate over one immutable source snapshot.

    Optional declared contract (defaults preserve the original behaviour):
      format_gating=false  -- formatting is measured with --verify only, recorded
                              as class `not_gating`, and no proposal is written.
      style_rules / rule_classes.style -- caller-declared style rule names; their
                              findings are reported separately as `not_gating`
                              and the gate closes on the remaining (semantic +
                              parse) findings. Nothing is waived or defaulted.
    """
    srcs = _sources(params)
    if not srcs:
        return _cde(
            objective="RTL lint and canonical-format gate", status="failed",
            error="no source found: provide `source`/`sources` (.v/.sv)",
            validation={"verdict": "fail"})

    format_gating = not _flag_false(params.get("format_gating", True))
    style_rules, style_error = _declared_style_rules(params)
    if style_error:
        return _cde(
            objective="RTL lint and canonical-format gate", status="failed",
            error=style_error, inputs_ref={"sources": srcs},
            validation={"verdict": "fail"})

    before = {source: _hash_input_file(source) for source in srcs}
    lint_result = _lint(params)
    format_params = dict(params)
    format_params["write_formatted"] = format_gating
    format_result = _format(format_params)
    lint_subrun = _write_subrun_cde("lint_subrun_cde.json", lint_result)
    format_subrun = _write_subrun_cde("format_subrun_cde.json", format_result)
    after = {source: _hash_input_file(source) for source in srcs}

    if before != after:
        return _cde(
            objective="RTL lint and canonical-format gate", status="failed",
            error="source bytes changed while lint_gate was running",
            inputs_ref={"sources": srcs},
            signoff={"source_hashes_before": before, "source_hashes_after": after,
                     "lint_subrun": lint_subrun, "format_subrun": format_subrun},
            validation={"verdict": "fail",
                        "note": "lint_gate never permits in-place source mutation"})

    lint_count = _metric_value(lint_result, "lint_violations")
    format_count = _metric_value(format_result, "unformatted_files")
    subrun_errors = []
    if lint_result.get("status") != "completed" or lint_count is None:
        subrun_errors.append("lint subrun was not assessable")
    if format_result.get("status") != "completed" or format_count is None:
        subrun_errors.append("format subrun was not assessable")
    if subrun_errors:
        return _cde(
            objective="RTL lint and canonical-format gate", status="failed",
            error="; ".join(subrun_errors), inputs_ref={"sources": srcs},
            signoff={"source_hashes": before, "lint_subrun": lint_subrun,
                     "format_subrun": format_subrun,
                     "lint_error": lint_result.get("error"),
                     "format_error": format_result.get("error")},
            validation={"verdict": "fail",
                        "note": "both required gate families must be assessable"})

    lint_signoff = lint_result.get("signoff_evidence") or {}
    format_signoff = format_result.get("signoff_evidence") or {}
    rules_hit = lint_signoff.get("rules", {}) or {}
    style_hit = {r: n for r, n in rules_hit.items() if r in style_rules}
    gating_hit = {r: n for r, n in rules_hit.items() if r not in style_rules}
    style_count = sum(style_hit.values())
    gating_count = lint_count - style_count
    lint_clean = gating_count == 0
    format_clean = format_count == 0
    format_ok = format_clean or not format_gating
    verdict = "pass" if lint_clean and format_ok else "fail"
    required = ["lint_violations"] + (["format"] if format_gating else [])

    results = {
        "lint_violations": {
            "value": gating_count, "unit": "count", "class": "gating",
            "basis": "parsed_verible_lint_output", "closes_at": "== 0"},
        "unformatted_files": (
            {"value": format_count, "unit": "count", "class": "gating",
             "basis": "verible-verilog-format --verify", "closes_at": "== 0"}
            if format_gating else
            {"value": format_count, "unit": "count", "class": "not_gating",
             "basis": "verible-verilog-format --verify",
             "note": "formatting declared not_gating by caller; measured only, "
                     "never recorded as pass or waived"}),
    }
    if style_rules:
        results["style_violations"] = {
            "value": style_count, "unit": "count", "class": "not_gating",
            "basis": "parsed_verible_lint_output",
            "note": "findings from caller-declared style rules; reported "
                    "separately, not part of lint_violations"}
    classification = {
        "format_gating": format_gating,
        "format_class": "gating" if format_gating else "not_gating",
        "style_rules_declared": style_rules,
        "style_findings_by_rule": style_hit,
        "gating_findings_by_rule": gating_hit,
        "proposals_written": format_gating,
    }
    return _cde(
        objective="RTL lint and canonical-format gate of "
                  + str(len(srcs)) + " source(s)",
        status="completed",
        results=results,
        qor={"lint_violations": gating_count, "lint_clean": lint_clean,
             "unformatted_files": format_count, "all_formatted": format_clean,
             "style_violations": style_count,
             "rules": rules_hit},
        signoff={
            "gate_scope": "complete",
            "required_families": required,
            "not_gating_families": ([] if format_gating else ["format"])
                                   + (["style_violations"] if style_rules else []),
            "rule_classification": classification,
            "source_hashes": before,
            "source_hashes_before": before,
            "source_hashes_after": after,
            "sources_unchanged": before == after,
            "rules_hit": rules_hit,
            "unformatted_files": format_signoff.get("unformatted_files", []),
            "format_proposals": format_signoff.get("format_proposals", []),
            "proposal_errors": format_signoff.get("proposal_errors", []),
            "lint_subrun": lint_subrun,
            "format_subrun": format_subrun,
            "native_exit_codes": {
                **lint_signoff.get("native_exit_codes", {}),
                **format_signoff.get("native_exit_codes", {}),
            },
        },
        inputs_ref={"sources": srcs},
        assumptions=[
            "required gate families are closed at residual zero; families the "
            "caller declares not_gating are measured and reported, never "
            "recorded as pass or waived",
            "style rules are only those the caller declared; parse/syntax "
            "diagnostics can never be classified as style",
            "formatter proposals (format_gating=true only) are re-verified and "
            "never replace input files in place",
        ],
        validation={
            "verdict": verdict,
            "stage_closure_eligible": True,
            "note": "lint_violations=" + str(gating_count)
                    + ", style_violations=" + str(style_count)
                    + ", unformatted_files=" + str(format_count)
                    + (" (gating)" if format_gating else " (not_gating)")},
        provenance={"verible": _verible_version(),
                "logs": ["logs/verible_lint.log", "logs/verible_format.log"]},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("lint_gate", "gate", "signoff"):
        return _lint_gate(params)
    if s in ("lint", "style", "rtl_lint"):
        return _lint(params)
    if s in ("format", "format_check", "fmt"):
        return _format(params)
    return _cde(objective="RTL lint", status="failed",
                error="unknown scenario '%s'; supported: lint_gate, lint, format" % s,
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
