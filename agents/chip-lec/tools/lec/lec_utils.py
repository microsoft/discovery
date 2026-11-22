#!/usr/bin/env python3
"""lec_utils.py -- logical equivalence checking via eqy (Equivalence checking
with Yosys) for the chip-lec tool.

Scenarios: rtl_vs_netlist, hierarchical_rtl_vs_netlist, netlist_vs_netlist,
post_dft_mission, post_eco.
The post-DFT scenario constrains functional mode and normalizes both sides
symmetrically before proof. eqy auto-partitions the two designs, maps key points,
and proves each partition with a bounded SAT strategy, falling back to an
sby-backed UNBOUNDED k-induction strategy (`engine smtbmc`, eqy's own default)
for hard sequential points such as arithmetic partitions. Node-aware:
cell functional models come from the PDK binding when the revised side is a
mapped netlist. A non-equivalence is a hard failure. Results conform to the
Common Design Envelope.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

import rtl_frontend

TOOL = "lec"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


def _is_ident(s):
    """True if *s* is a safe HDL/Tcl identifier -- blocks script injection via
    user-supplied module names interpolated into Yosys scripts."""
    return bool(s) and bool(re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", str(s)))


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
        raw_prov = results.get("provenance")
        prov: dict[str, object]
        if isinstance(raw_prov, dict):
            prov = dict(raw_prov)
        else:
            prov = {} if raw_prov in (None, "") else {"note": str(raw_prov)}
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
        if "input_hashes" not in prov:
            prov["input_hashes"] = _hashes
        chain = prov.get("hash_chain")
        if isinstance(chain, dict) and chain.get("prev_hash"):
            chain.setdefault("hash_algo", "sha256")
            chain.setdefault(
                "canonicalization",
                "self_hash computed over the envelope with "
                "provenance.hash_chain.self_hash removed, recursively key-sorted, "
                "JSON compact serialization, UTF-8 SHA-256.")
            chain.pop("self_hash", None)
            encoded = json.dumps(
                results, sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
            chain["self_hash"] = __import__("hashlib").sha256(encoded).hexdigest()
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


def _yosys_version():
    try:
        return subprocess.run(["yosys", "-V"], capture_output=True, text=True,
                              timeout=30).stdout.strip().split("\n")[0]
    except Exception:
        return "unknown"


def _eqy_version():
    try:
        proc = subprocess.run(["eqy", "--version"], capture_output=True, text=True,
                              timeout=30)
        return (proc.stdout or proc.stderr).strip().split("\n")[0]
    except Exception:
        return "unknown"


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
        base.setdefault("basis", "agent_read_of_eqy_log" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_eqy_log")


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
         pdk_binding=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None):
    # `qor` was previously missing from this signature while the main return
    # path passed `qor={...}` -- so ANY run that got far enough to report a
    # result died with `TypeError: _cde() got an unexpected keyword argument
    # 'qor'`. It stayed invisible because every real attempt failed earlier (on
    # the Liberty read or the uninstallable proof engine) and took one of the
    # early `return _cde(..., error=...)` paths, which pass only valid kwargs.
    # Net effect: this tool could never emit a passing envelope, and
    # `qor_metrics` was hardcoded to {} even when metrics had been parsed.
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [
            {"name": "eqy", "version": _eqy_version()},
            {"name": "Yosys", "version": _yosys_version()},
        ],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "formal_equivalence"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _stage(text_or_path, name):
    if os.path.exists(str(text_or_path)):
        return text_or_path
    p = os.path.join(_WORK_DIR, name)
    open(p, "w").write(text_or_path)
    return p


def _resolve_model(params):
    binding = params.get("pdk_binding")
    binding = binding if isinstance(binding, dict) else {}
    bound = binding.get("functional_cell_models")
    bound = bound if isinstance(bound, dict) else {}
    references = binding.get("references")
    references = references if isinstance(references, dict) else {}
    spec = (params.get("cell_models") or params.get("functional_verilog")
            or bound.get("yosys_model") or bound.get("model")
            or references.get("cell_models"))
    if isinstance(spec, str):
        spec = {"path": spec}
    if not isinstance(spec, dict) or not spec.get("path"):
        return None, None, None

    raw_path = str(spec["path"])
    candidates = [raw_path]
    if not os.path.isabs(raw_path):
        candidates.extend([
            os.path.join("/input", raw_path),
            os.path.join("/workspace", raw_path),
            os.path.join("/pdk", raw_path.removeprefix("pdk/")),
        ])
    path = next((p for p in candidates if os.path.isfile(p)), None)
    expected = (
        params.get("cell_models_sha256")
        or spec.get("sha256")
    )
    return path, expected, spec


def _resolve_liberty(params):
    """Resolve one functional Liberty view without guessing among corners."""
    binding = params.get("pdk_binding")
    binding = binding if isinstance(binding, dict) else {}
    references = binding.get("references")
    references = references if isinstance(references, dict) else {}
    raw = params.get("liberty") or binding.get("liberty")
    corner = params.get("normalization_corner")
    if raw is None:
        if corner:
            raw = references.get("liberty_" + str(corner))
            if raw is None:
                return None, None, (
                    "normalization_corner is not present in binding references: "
                    + str(corner))
        elif references.get("liberty"):
            raw = references.get("liberty")
        else:
            candidates = {
                key.removeprefix("liberty_"): value
                for key, value in references.items()
                if key.startswith("liberty_")
            }
            if candidates:
                raw = candidates
    if isinstance(raw, dict) and "path" not in raw:
        if corner:
            raw = raw.get(str(corner))
        elif len(raw) == 1:
            raw = next(iter(raw.values()))
        else:
            return None, None, (
                "normalization_corner is required when the binding exposes "
                "multiple Liberty corners")
    spec = {"path": raw} if isinstance(raw, str) else raw
    if not isinstance(spec, dict) or not spec.get("path"):
        return None, None, "missing functional Liberty view"
    raw_path = str(spec["path"])
    candidates = [raw_path]
    if not os.path.isabs(raw_path):
        candidates.extend([
            os.path.join("/input", raw_path),
            os.path.join("/workspace", raw_path),
            os.path.join("/pdk", raw_path.removeprefix("pdk/")),
        ])
    path = next((candidate for candidate in candidates
                 if os.path.isfile(candidate)), None)
    if path is None:
        return None, spec.get("sha256"), "functional Liberty file not found"
    expected = params.get("liberty_sha256") or spec.get("sha256")
    actual = _hash_input_file(path)
    if expected and (not actual or
                     actual["sha256"].lower() != str(expected).lower()):
        return None, expected, "functional Liberty SHA-256 verification failed"
    return path, expected, None


def _liberty_declared(params):
    """True when SOMETHING in this call declares a functional Liberty view.

    Separates "no Liberty was asked for" from "a Liberty was asked for and could
    not be used". `_resolve_liberty` returns an error string for both, and the
    second must fail the run instead of silently reading the gate netlist with
    no cell function at all.
    """
    binding = params.get("pdk_binding")
    binding = binding if isinstance(binding, dict) else {}
    references = binding.get("references")
    references = references if isinstance(references, dict) else {}
    corner = params.get("normalization_corner")
    return bool(
        params.get("liberty")
        or binding.get("liberty")
        or references.get("liberty")
        or (corner and references.get("liberty_" + str(corner)))
        or any(key.startswith("liberty_") for key in references))


def _run_yosys(script):
    sp = os.path.join(_OUTPUT_DIR, "lec.ys")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command(["yosys", "-s", sp])
    proc = subprocess.run(["yosys", "-s", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    open(os.path.join(_OUTPUT_DIR, "yosys_lec.log"), "w").write(proc.stdout + "\n" + proc.stderr)
    return proc, elapsed


def _run_yosys_named(script, stem):
    """Run a named Yosys preparation step with durable script/log evidence."""
    yosys = shutil.which("yosys") or "yosys"
    script_path = os.path.join(_OUTPUT_DIR, stem + ".ys")
    log_path = os.path.join(_OUTPUT_DIR, stem + ".log")
    open(script_path, "w").write(script)
    t0 = time.time()
    _save_run_command([yosys, "-s", script_path], stem + "_run_command.txt")
    proc = subprocess.run([yosys, "-s", script_path], capture_output=True,
                          text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    open(log_path, "w").write((proc.stdout or "") + "\n" +
                               (proc.stderr or ""))
    return proc, elapsed


def _yosys_arg(value):
    text = str(value)
    if any(char in text for char in ("\0", "\n", "\r")):
        raise ValueError("unsafe path in Yosys script")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yosys_define_args(model_spec):
    defines = model_spec.get("defines", []) if isinstance(model_spec, dict) else []
    if not isinstance(defines, (list, tuple)) or not all(
            re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_+./:-]*)?",
                str(item))
            for item in defines):
        raise ValueError("functional model defines contain an unsafe token")
    return " ".join("-D " + str(item) for item in defines)


def _interface_signature(document, top):
    module = (document.get("modules") or {}).get(top)
    if not isinstance(module, dict):
        raise ValueError("Yosys interface JSON is missing top module %r" % top)
    signature = {}
    for name, port in sorted((module.get("ports") or {}).items()):
        if not _is_ident(name):
            raise ValueError("unsupported non-identifier top port %r" % name)
        signature[name] = {
            "direction": port.get("direction"),
            "width": len(port.get("bits") or []),
            "offset": int(port.get("offset") or 0),
            "upto": bool(port.get("upto")),
            "signed": bool(port.get("signed")),
        }
    if not signature:
        raise ValueError("top module has no ports")
    return signature


def _probe_interface(source, top, stem):
    json_path = os.path.join(_OUTPUT_DIR, stem + "_interface.json")
    script = (
        "read_verilog -sv %s\n"
        "hierarchy -top %s\n"
        "write_json %s\n"
        % (_yosys_arg(source), top, _yosys_arg(json_path)))
    proc, elapsed = _run_yosys_named(script, stem + "_interface")
    if proc.returncode != 0 or not os.path.isfile(json_path):
        raise ValueError("%s interface elaboration failed" % stem)
    return _interface_signature(json.load(open(json_path)), top), elapsed


def _port_decl(name, port):
    width = port["width"]
    vector = ""
    if width > 1:
        low = port["offset"]
        high = low + width - 1
        bounds = (low, high) if port["upto"] else (high, low)
        vector = "[%d:%d] " % bounds
    signed = "signed " if port["signed"] else ""
    return "    %s wire %s%s;" % (
        port["direction"], signed, vector + name)


def _mode_literal(width, value):
    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, int) or value < 0 or value >= (1 << width):
        raise ValueError("functional-mode value %r does not fit %d bit(s)"
                         % (value, width))
    return "%d'd%d" % (width, value)


def _mission_wrapper(top, interface, constraints):
    if not isinstance(constraints, dict) or not constraints:
        raise ValueError("functional_mode must be a non-empty signal-to-value map")
    unknown = sorted(set(constraints) - set(interface))
    if unknown:
        raise ValueError("functional_mode names unknown port(s): " +
                         ", ".join(unknown))
    for name in constraints:
        if interface[name]["direction"] != "input":
            raise ValueError("functional_mode may constrain input ports only: " +
                             name)
    core = top + "__mission_core"
    declarations = [_port_decl(name, port)
                    for name, port in interface.items()]
    connections = []
    for name, port in interface.items():
        value = (_mode_literal(port["width"], constraints[name])
                 if name in constraints else name)
        connections.append("        .%s(%s)" % (name, value))
    return (
        "module %s (\n%s\n);\n"
        "%s\n\n"
        "    %s mission_core (\n%s\n    );\n"
        "endmodule\n"
        % (top, ",\n".join("    " + name for name in interface),
           "\n".join(declarations), core, ",\n".join(connections)))


def _normalized_design_summary(path, top):
    document = json.load(open(path))
    module = (document.get("modules") or {}).get(top)
    if not isinstance(module, dict):
        raise ValueError("normalized JSON is missing top module %r" % top)
    cells = module.get("cells") or {}
    residual = sorted({cell.get("type") for cell in cells.values()
                       if isinstance(cell.get("type"), str)
                       and not cell["type"].startswith("$")})
    state_types = {}
    for cell in cells.values():
        cell_type = str(cell.get("type") or "")
        if "DFF" in cell_type.upper() or "LATCH" in cell_type.upper():
            state_types[cell_type] = state_types.get(cell_type, 0) + 1
    return {
        "interface": _interface_signature(document, top),
        "cell_count": len(cells),
        "state_count": sum(state_types.values()),
        "state_types": state_types,
        "unresolved_non_internal_cells": residual,
    }


def _normalize_post_dft_side(source, top, wrapper, liberty, model, model_spec,
                             stem):
    results_dir = os.path.join(_OUTPUT_DIR, "results")
    os.makedirs(results_dir, exist_ok=True)
    comb = os.path.join(results_dir, stem + "_comb_liberty_mapped.v")
    mapped = os.path.join(results_dir, stem + "_liberty_mapped.v")
    normalized = os.path.join(results_dir, stem + "_normalized.v")
    normalized_json = os.path.join(results_dir, stem + "_normalized.json")
    define_args = _yosys_define_args(model_spec)
    core = top + "__mission_core"
    script = f"""read_liberty -ignore_miss_func {_yosys_arg(liberty)}
read_verilog -sv {_yosys_arg(source)}
rename {top} {core}
read_verilog -sv {_yosys_arg(wrapper)}
prep -top {top} -flatten
proc
memory
flatten
techmap -autoproc
opt -full
hierarchy -check -top {top} -purge_lib
check -assert
abc -liberty {_yosys_arg(liberty)}
clean -purge
select {top}
write_verilog -noattr -noexpr -selected {_yosys_arg(comb)}
select -clear

design -reset
read_verilog +/simcells.v
read_verilog -sv {define_args} {_yosys_arg(model)}
read_verilog -sv {_yosys_arg(comb)}
hierarchy -check -top {top}
flatten
proc
memory
techmap -autoproc
opt -full
hierarchy -check -top {top} -purge_lib
check -assert
dfflibmap -liberty {_yosys_arg(liberty)}
abc -liberty {_yosys_arg(liberty)}
clean -purge
select {top}
write_verilog -noattr -noexpr -selected {_yosys_arg(mapped)}
select -clear

design -reset
read_liberty -ignore_miss_func {_yosys_arg(liberty)}
read_verilog -sv {_yosys_arg(mapped)}
prep -top {top} -flatten
proc
memory
flatten
techmap -autoproc
opt -full
hierarchy -check -top {top} -purge_lib
check -assert
stat
write_verilog -noattr {_yosys_arg(normalized)}
write_json {_yosys_arg(normalized_json)}
"""
    proc, elapsed = _run_yosys_named(script, "normalize_" + stem)
    if proc.returncode != 0 or not os.path.isfile(normalized) \
            or not os.path.isfile(normalized_json):
        raise ValueError("%s symmetric normalization failed" % stem)
    summary = _normalized_design_summary(normalized_json, top)
    if summary["unresolved_non_internal_cells"]:
        raise ValueError(
            "%s normalization left unresolved non-internal cells: %s"
            % (stem, summary["unresolved_non_internal_cells"]))
    return normalized, summary, elapsed


def _replace_json_bits(node, replacements):
    """Replace module-local JSON net bits while preserving constants."""
    if isinstance(node, list):
        return [_replace_json_bits(value, replacements) for value in node]
    if isinstance(node, dict):
        return {
            key: _replace_json_bits(value, replacements)
            for key, value in node.items()
        }
    if isinstance(node, int):
        return replacements.get(node, node)
    return node


def _share_blackbox_outputs_in_miter(
    prepared, miter, interfaces, module_name, allowed_modules,
    passive_inout_modules=None, passive_instances=None):
    """Give exact-named blackbox instances common deterministic semantics.

    ``equiv_make`` leaves each side's blackbox output as an independent symbolic
    source. This transformation verifies the pre-miter instance/type sets and
    interfaces, then replaces each exact pair with one shared symbolic output
    vector feeding both cones. Pairing is by exact instance name and port name.
    """
    allowed = set(allowed_modules)
    passive_inout = set(passive_inout_modules or [])
    passive_instance_set = set(passive_instances or [])
    if not allowed:
        raise ValueError("shared_blackbox_modules must be a non-empty list")
    if not passive_inout.issubset(allowed):
        raise ValueError("passive inout modules must be intentional blackboxes")

    modules = prepared.get("modules", {})
    gold = modules.get("gold")
    gate = modules.get("gate")
    if not isinstance(gold, dict) or not isinstance(gate, dict):
        raise ValueError("prepared design is missing gold/gate modules")

    def residual_cells(design):
        cells = design.get("cells", {})
        unexpected = sorted({
            cell.get("type") for cell in cells.values()
            if isinstance(cell.get("type"), str)
            and not cell["type"].startswith("$")
            and cell["type"] not in allowed
        })
        intentional = {
            name: cell["type"] for name, cell in cells.items()
            if cell.get("type") in allowed
        }
        return intentional, unexpected

    gold_cells, gold_unexpected = residual_cells(gold)
    gate_cells, gate_unexpected = residual_cells(gate)
    if gold_unexpected or gate_unexpected:
        raise ValueError(
            "unmodelled non-internal cells survived flattening: "
            f"gold={gold_unexpected}, gate={gate_unexpected}")
    if gold_cells != gate_cells:
        missing_gate = sorted(set(gold_cells) - set(gate_cells))
        missing_gold = sorted(set(gate_cells) - set(gold_cells))
        type_mismatch = sorted(
            name for name in set(gold_cells) & set(gate_cells)
            if gold_cells[name] != gate_cells[name])
        raise ValueError(
            "intentional blackbox instance set differs: "
            f"missing_gate={missing_gate}, missing_gold={missing_gold}, "
            f"type_mismatch={type_mismatch}")

    interface_modules = interfaces.get("modules", {})
    missing_interfaces = sorted(allowed - set(interface_modules))
    if missing_interfaces:
        raise ValueError(
            "reference-side blackbox interfaces are missing for: "
            + ", ".join(missing_interfaces))

    equiv = miter.get("modules", {}).get(module_name)
    if not isinstance(equiv, dict):
        raise ValueError(f"miter is missing module {module_name!r}")
    cells = equiv.get("cells", {})
    replacements = {}
    remove_cells = []
    shared_instances = []
    already_shared = []
    verified_input_bits = 0
    input_equivalence_obligations = 0
    pending_input_obligations = []
    shared_output_bits = 0
    used_passive_instances = set()
    integer_bits = []

    def collect_integer_bits(node):
        if isinstance(node, int):
            integer_bits.append(node)
        elif isinstance(node, list):
            for item in node:
                collect_integer_bits(item)
        elif isinstance(node, dict):
            for item in node.values():
                collect_integer_bits(item)

    collect_integer_bits(equiv)
    next_bit = max(integer_bits or [1]) + 1

    for instance, cell_type in sorted(gold_cells.items()):
        gold_name = instance + "_gold"
        gate_name = instance + "_gate"
        gold_cell = cells.get(gold_name)
        gate_cell = cells.get(gate_name)
        if gold_cell is None and gate_cell is None:
            shared_cell = cells.get(instance)
            if shared_cell and shared_cell.get("type") == cell_type:
                raise ValueError(
                    f"pre-shared blackbox instance is not auditable: {instance}")
            raise ValueError(
                f"cannot find exact miter cell pair for {instance!r}")
        if gold_cell is None or gate_cell is None:
            raise ValueError(
                f"incomplete miter cell pair for {instance!r}: "
                f"gold={gold_cell is not None}, gate={gate_cell is not None}")
        if gold_cell.get("type") != cell_type or gate_cell.get("type") != cell_type:
            raise ValueError(f"miter cell type changed for {instance!r}")
        if gold_cell.get("parameters", {}) != gate_cell.get("parameters", {}):
            raise ValueError(f"blackbox parameter mismatch at {instance}")

        ports = interface_modules[cell_type].get("ports", {})
        if not ports:
            raise ValueError(f"blackbox interface has no ports: {cell_type}")
        connected_output_bits = sum(
            len(gold_cell.get("connections", {}).get(port, []))
            for port, details in ports.items()
            if details.get("direction") == "output")
        if connected_output_bits == 0 \
                and cell_type not in passive_inout \
                and instance not in passive_instance_set:
            raise ValueError(
                "blackbox with no connected output requires passive declaration: "
                + instance)
        if connected_output_bits == 0:
            used_passive_instances.add(instance)
        gold_connections = gold_cell.get("connections", {})
        gate_connections = gate_cell.get("connections", {})
        unknown_ports = sorted(
            (set(gold_connections) | set(gate_connections)) - set(ports))
        if unknown_ports:
            raise ValueError(
                f"blackbox interface missing connected ports at {instance}: "
                + ", ".join(unknown_ports))
        gold_directions = gold_cell.get("port_directions", {})
        gate_directions = gate_cell.get("port_directions", {})
        if gold_directions and gate_directions \
                and gold_directions != gate_directions:
            raise ValueError(f"blackbox port-direction mismatch at {instance}")
        for port, details in sorted(ports.items()):
            direction = details.get("direction")
            gold_bits = gold_connections.get(port, [])
            gate_bits = gate_connections.get(port, [])
            if direction in ("input", "inout"):
                if len(gold_bits) != len(gate_bits):
                    raise ValueError(
                        f"blackbox input width mismatch at {instance}.{port}")
                if direction == "inout" and gold_bits != gate_bits:
                    raise ValueError(
                        f"blackbox input source mismatch at {instance}.{port}")
                if direction == "input" and gold_bits != gate_bits:
                    for index, (gold_bit, gate_bit) in enumerate(
                            zip(gold_bits, gate_bits)):
                        valid_bit = lambda bit: (
                            isinstance(bit, int) or bit in ("0", "1", "x", "z"))
                        if not valid_bit(gold_bit) or not valid_bit(gate_bit):
                            raise ValueError(
                                f"unsupported blackbox input bit at "
                                f"{instance}.{port}[{index}]")
                        if gold_bit == gate_bit:
                            continue
                        obligation_name = (
                            "$blackbox_input_equiv$%s$%s$%d"
                            % (instance, port, index))
                        pending_input_obligations.append((obligation_name, {
                            "hide_name": 1,
                            "type": "$equiv",
                            "parameters": {},
                            "attributes": {
                                "blackbox_input_obligation": "1",
                            },
                            "port_directions": {
                                "A": "input", "B": "input", "Y": "output",
                            },
                            "connections": {
                                "A": [gold_bit], "B": [gate_bit], "Y": [next_bit],
                            },
                        }))
                        next_bit += 1
                        input_equivalence_obligations += 1
                verified_input_bits += len(gold_bits)
            elif direction == "output":
                if len(gold_bits) != len(gate_bits):
                    raise ValueError(
                        f"blackbox output width mismatch at {instance}.{port}")
                for gold_bit, gate_bit in zip(gold_bits, gate_bits):
                    if not isinstance(gold_bit, int) or not isinstance(gate_bit, int):
                        if gold_bit != gate_bit:
                            raise ValueError(
                                f"non-net blackbox output mismatch at "
                                f"{instance}.{port}")
                        continue
                    prior = replacements.get(gate_bit)
                    if prior is not None and prior != gold_bit:
                        raise ValueError(
                            f"conflicting blackbox output map for bit {gate_bit}")
                    replacements[gate_bit] = gold_bit
                    shared_output_bits += 1
        remove_cells.extend([gold_name, gate_name])
        shared_instances.append(instance)

    rewritten = _replace_json_bits(equiv, replacements)
    if not isinstance(rewritten, dict):
        raise ValueError("rewritten equivalence miter is not a JSON object")
    rewritten_cells = rewritten.get("cells", {})
    if not isinstance(rewritten_cells, dict):
        raise ValueError("rewritten equivalence miter cells are not a JSON object")
    for name in remove_cells:
        rewritten_cells.pop(name, None)
    for name, obligation in pending_input_obligations:
        rewritten_cells[name] = obligation
    miter["modules"][module_name] = rewritten
    unused_passive_instances = sorted(passive_instance_set - used_passive_instances)
    if unused_passive_instances:
        raise ValueError(
            "passive blackbox instance declarations did not match a passive instance: "
            + ", ".join(unused_passive_instances))
    return {
        "method": (
            "exact instance/type/port pairing; one shared symbolic output "
            "vector drives corresponding gold and gate cones"),
        "allowed_modules": sorted(allowed),
        "passive_inout_modules": sorted(passive_inout),
        "passive_instances": sorted(passive_instance_set),
        "gold_instance_count": len(gold_cells),
        "gate_instance_count": len(gate_cells),
        "shared_pair_count": len(shared_instances),
        "already_shared_count": len(already_shared),
        "shared_output_bits": shared_output_bits,
        "verified_input_inout_bits": verified_input_bits,
        "input_equivalence_obligations": input_equivalence_obligations,
        "unexpected_gold_cells": gold_unexpected,
        "unexpected_gate_cells": gate_unexpected,
        "mapping_basis": "exact hierarchical instance name, cell type, and port name",
        "positional_mapping": False,
    }


def _run_shared_blackbox_flat(
        params, top, ref, rev, lib_read, read_ref, read_rev, init_norm, depth,
        cell_model_source, inputs_ref):
    allowed = params.get("shared_blackbox_modules")
    if not isinstance(allowed, (list, tuple)) or not all(
            _is_ident(module) for module in allowed):
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="shared_blackbox_modules must contain safe module identifiers",
            pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail"})
    passive_inout = params.get("passive_inout_blackbox_modules") or []
    if not isinstance(passive_inout, (list, tuple)) or not all(
            _is_ident(module) for module in passive_inout):
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="passive_inout_blackbox_modules must contain safe identifiers",
            pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail"})
    passive_instances = params.get("passive_blackbox_instances") or []
    if not isinstance(passive_instances, (list, tuple)) or not all(
            isinstance(instance, str) and instance for instance in passive_instances):
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="passive_blackbox_instances must contain non-empty instance names",
            pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail"})

    interface_json = os.path.join(_WORK_DIR, "blackbox_interfaces.json")
    prepared_json = os.path.join(_WORK_DIR, "prepared_sides.json")
    miter_json = os.path.join(_WORK_DIR, "shared_blackbox_miter.json")
    stage1_ys = (
        f"{read_ref}\n"
        "proc\n"
        f"write_json {interface_json}\n"
        f"prep -top {top}\n"
        f"{init_norm}"
        "flatten\n"
        "design -stash gold\n"
        f"{lib_read}{read_rev}\n"
        "proc\n"
        f"hierarchy -top {top}\n"
        "flatten\n"
        f"{init_norm}"
        "design -stash gate\n"
        f"design -copy-from gold -as gold {top}\n"
        f"design -copy-from gate -as gate {top}\n"
        f"write_json {prepared_json}\n"
        "equiv_make gold gate equiv\n"
        "hierarchy -top equiv\n"
        f"write_json {miter_json}\n"
    )
    stage1_path = os.path.join(_WORK_DIR, "shared_blackbox_prepare.ys")
    open(stage1_path, "w").write(stage1_ys)
    t0 = time.time()
    prepare = subprocess.run(
        ["yosys", "-ql", "shared_blackbox_prepare.log", stage1_path],
        capture_output=True, text=True, cwd=_WORK_DIR)
    prepare_log = (prepare.stdout or "") + "\n" + (prepare.stderr or "")
    prepare_log_path = os.path.join(_WORK_DIR, "shared_blackbox_prepare.log")
    if os.path.exists(prepare_log_path):
        prepare_log += "\n" + open(
            prepare_log_path, errors="replace").read()
    open(os.path.join(_OUTPUT_DIR, "shared_blackbox_prepare.log"), "w").write(
        prepare_log)
    open(os.path.join(_OUTPUT_DIR, "shared_blackbox_prepare.ys"), "w").write(
        stage1_ys)
    if prepare.returncode != 0:
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="shared-blackbox miter preparation failed; see "
                  "shared_blackbox_prepare.log",
            pdk_binding=params.get("pdk_binding", "none"),
            inputs_ref=inputs_ref, validation={"verdict": "fail"})

    try:
        interfaces = json.load(open(interface_json))
        prepared = json.load(open(prepared_json))
        miter = json.load(open(miter_json))
        sharing = _share_blackbox_outputs_in_miter(
            prepared, miter, interfaces, "equiv", list(allowed),
            passive_inout_modules=list(passive_inout),
            passive_instances=list(passive_instances))
        open(miter_json, "w").write(json.dumps(miter, indent=2) + "\n")
        open(os.path.join(
            _OUTPUT_DIR, "shared_blackbox_mapping.json"), "w").write(
                json.dumps(sharing, indent=2) + "\n")
    except Exception as exc:
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error=f"shared-blackbox validation failed: {exc}",
            pdk_binding=params.get("pdk_binding", "none"),
            inputs_ref=inputs_ref, validation={"verdict": "fail"})

    induct_command = (
        f"equiv_induct -seq {depth}\n"
        if params.get("run_equiv_induct", True) else "")
    proof_ys = (
        f"read_json {miter_json}\n"
        "hierarchy -top equiv\n"
        f"equiv_simple -seq {depth}\n"
        f"{induct_command}"
        "equiv_status -assert\n"
    )
    proof_path = os.path.join(_WORK_DIR, "shared_blackbox_proof.ys")
    open(proof_path, "w").write(proof_ys)
    _save_run_command(
        ["yosys", "-ql", "shared_blackbox_proof.log", proof_path],
        "shared_blackbox_run_command.txt")
    proof = subprocess.run(
        ["yosys", "-ql", "shared_blackbox_proof.log", proof_path],
        capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    proof_log = (proof.stdout or "") + "\n" + (proof.stderr or "")
    proof_log_path = os.path.join(_WORK_DIR, "shared_blackbox_proof.log")
    if os.path.exists(proof_log_path):
        proof_log += "\n" + open(proof_log_path, errors="replace").read()
    open(os.path.join(_OUTPUT_DIR, "shared_blackbox_proof.log"), "w").write(
        proof_log)
    open(os.path.join(_OUTPUT_DIR, "shared_blackbox_proof.ys"), "w").write(
        proof_ys)

    total_matches = re.findall(
        r"Found\s+(\d+)\s+\$equiv cells", proof_log, re.I)
    final_match = re.search(
        r"Of those cells\s+(\d+)\s+are proven and\s+(\d+)\s+are unproven",
        proof_log, re.I)
    total = int(total_matches[-1]) if total_matches else None
    proven = int(final_match.group(1)) if final_match else None
    unproven = int(final_match.group(2)) if final_match else None
    equivalent = (
        proof.returncode == 0
        and total is not None and total > 0
        and unproven == 0
        and bool(re.search(
            r"Equivalence successfully proven", proof_log, re.I))
    )
    verdict = "pass" if equivalent else "fail"
    return _cde(
        objective=f"logical equivalence of {top} (whole-design shared-blackbox proof)",
        status="completed",
        pdk_binding=params.get("pdk_binding", "none"),
        inputs_ref=inputs_ref,
        results={
            "compared_key_points": {"value": total, "unit": "count"},
            "proven_key_points": {"value": proven, "unit": "count"},
            "unproven_points": {
                "value": unproven, "unit": "count", "class": "gating"},
            "failing_points": {
                "value": 0 if equivalent else None, "unit": "count"},
            "mapping": {
                "unmapped_points": 0 if equivalent else None,
                "basis": sharing["mapping_basis"],
                "positional_mapping": False,
            },
        },
        qor={
            "unproven_points": unproven,
            "proven_key_points": proven,
            "total_key_points": total,
        },
        signoff={
            "verdict": verdict,
            "key_point_mapping": sharing["mapping_basis"],
            "engine": "yosys equiv_make + equiv_simple + equiv_induct",
            "cell_models": cell_model_source,
            "whole_design_confirmation": {
                "ran": True,
                "method": (
                    "whole design, no partitioning, no free partition inputs, "
                    "exact shared-blackbox instance semantics"),
                "proven_cells": proven,
                "unproven_cells": unproven,
                "returncode": proof.returncode,
                "equivalent": equivalent,
                "log": "shared_blackbox_proof.log",
            },
            "black_boxes": sharing,
        },
        validation={
            "verdict": verdict,
            "note": (
                "proved with zero unresolved/unproven points"
                if equivalent else
                "non-equivalence or incomplete proof is a hard failure"),
        },
        provenance={
            "yosys": _yosys_version(),
            "engine": "yosys-flat-shared-blackbox",
            "container_image": params.get("container_image")
                               or os.environ.get("CHIP_TOOL_IMAGE", "unrecorded"),
            "task_id": params.get("task_id"),
            "bookshelves_consulted": params.get(
                "bookshelves_consulted", "none_relevant"),
            "hash_chain": {
                "prev_hash": params.get("upstream_cde_self_hash"),
                "upstream": params.get("upstream_cde"),
            },
            "runtime_s": round(elapsed, 3),
            "log": "shared_blackbox_proof.log",
        },
    )


def _hierarchical_model_specs(params):
    specs = params.get("macro_models")
    if not isinstance(specs, (list, tuple)) or not specs:
        raise ValueError("macro_models must be a non-empty list of pinned model objects")
    paths = []
    evidence = []
    declared_modules = set()
    for spec in specs:
        if not isinstance(spec, dict) or not spec.get("path") or not spec.get("sha256"):
            raise ValueError("each macro_models entry requires path and sha256")
        raw = str(spec["path"])
        candidates = [raw]
        if not os.path.isabs(raw):
            candidates.extend([os.path.join("/input", raw),
                               os.path.join("/workspace", raw)])
        path = next((candidate for candidate in candidates
                     if os.path.isfile(candidate)), None)
        if path is None:
            raise ValueError("macro model file not found: " + raw)
        actual = _hash_input_file(path)
        if not actual or actual["sha256"].lower() != str(spec["sha256"]).lower():
            raise ValueError("macro model SHA-256 verification failed: " + raw)
        modules = spec.get("modules")
        if not isinstance(modules, (list, tuple)) or not modules \
                or not all(_is_ident(module) for module in modules):
            raise ValueError("each macro_models entry requires safe module names")
        overlap = declared_modules.intersection(modules)
        if overlap:
            raise ValueError("macro model modules declared more than once: "
                             + ", ".join(sorted(overlap)))
        declared_modules.update(modules)
        actual_modules = _functional_model_module_inventory(path)
        if set(modules) != actual_modules:
            raise ValueError(
                "macro model manifest differs from HDL definitions: "
                f"declared={sorted(modules)}, actual={sorted(actual_modules)}")
        paths.append(path)
        evidence.append({"path": path, "sha256": actual["sha256"],
                         "bytes": actual["bytes"],
                         "modules": list(modules)})
    return paths, evidence


def _functional_model_module_inventory(path):
    """Return functional model modules, preferring Yosys parsing in production."""
    yosys = shutil.which("yosys")
    if yosys:
        output = os.path.join(_WORK_DIR, "model_inventory_%s.json" % hashlib.sha256(
            str(path).encode("utf-8")).hexdigest()[:12])
        script = "read_verilog -sv %s\nproc\nwrite_json %s\n" % (
            _yosys_arg(path), _yosys_arg(output))
        proc, _ = _run_yosys_named(script, "model_inventory")
        if proc.returncode != 0 or not os.path.isfile(output):
            raise ValueError("could not parse macro model HDL: " + str(path))
        document = json.load(open(output))
        return set((document.get("modules") or {}).keys())
    text = open(path, encoding="utf-8", errors="replace").read()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return set(re.findall(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)", text))


def _proof_setup_fingerprint(params, macro_evidence, intentional_blackboxes,
                             passive_inout=None, passive_instances=None):
    def file_digest(value):
        info = _hash_input_file(value) if isinstance(value, str) else None
        return info["sha256"] if info else None

    binding = params.get("pdk_binding")
    binding = binding if isinstance(binding, dict) else None
    harness = _hash_input_file(__file__)
    frontend = _hash_input_file(getattr(rtl_frontend, "__file__", ""))
    macro_setup = sorted(
        ({"sha256": item["sha256"], "modules": sorted(item["modules"])}
         for item in macro_evidence),
        key=lambda item: (item["sha256"], item["modules"]),
    )
    setup = {
        "schema": "hierarchical-lec-setup/1",
        "top": params.get("top"),
        "reference_sha256": file_digest(params.get("reference")),
        "revised_sha256": file_digest(params.get("revised")),
        "functional_mutation_sha256": file_digest(
            params.get("functional_mutation_revised")),
        "blackbox_rewire_sha256": file_digest(
            params.get("blackbox_rewire_revised")),
        "liberty_sha256": file_digest(params.get("liberty")),
        "macro_models": macro_setup,
        "macro_model_modules": sorted(
            module for item in macro_evidence for module in item["modules"]),
        "intentional_blackbox_modules": sorted(intentional_blackboxes),
        "passive_inout_blackbox_modules": sorted(passive_inout or []),
        "passive_blackbox_instances": sorted(passive_instances or []),
        "pdk_binding_sha256": (
            hashlib.sha256(json.dumps(
                binding, sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")).hexdigest() if binding else None),
        "functional_cell_models": binding.get("functional_cell_models") if binding else None,
        "run_equiv_induct": bool(params.get("run_equiv_induct", True)),
        "container_image": params.get("container_image")
                           or os.environ.get("CHIP_TOOL_IMAGE", "unrecorded"),
        "harness_sha256": (harness or {}).get("sha256"),
        "rtl_frontend_sha256": (frontend or {}).get("sha256"),
        "source_language": params.get("language"),
        "vhdl_std": params.get("vhdl_std") or params.get("std"),
        "defines": params.get("defines"),
        "yosys_version": _yosys_version(),
        "eqy_version": _eqy_version(),
        "mapping": "exact_instance_type_port_no_positional",
        "proof": "whole_design_equiv_simple_induct",
        "equiv_induct_depth": int(params.get("equiv_induct_depth", 10)),
    }
    encoded = json.dumps(setup, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), setup


def _run_hierarchical_subproof(params, label, revised):
    global _OUTPUT_DIR, _WORK_DIR
    original_output, original_work = _OUTPUT_DIR, _WORK_DIR
    try:
        _OUTPUT_DIR = os.path.join(original_output, label)
        _WORK_DIR = os.path.join(original_work, label)
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        os.makedirs(_WORK_DIR, exist_ok=True)
        nested = dict(params)
        nested["scenario"] = "rtl_vs_netlist"
        nested["revised"] = revised
        return _equiv(nested)
    finally:
        _OUTPUT_DIR, _WORK_DIR = original_output, original_work


def _artifact_manifest(root):
    manifest = []
    if not os.path.isdir(root):
        return manifest
    for directory, _subdirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(directory, name)
            info = _hash_input_file(path)
            if info:
                manifest.append({
                    "path": os.path.relpath(path, root),
                    "sha256": info["sha256"],
                    "bytes": info["bytes"],
                })
    return sorted(manifest, key=lambda item: item["path"])


def _hierarchical_rtl_vs_netlist(params):
    top = params.get("top")
    if not _is_ident(top):
        return _cde(objective="hierarchical RTL-to-netlist equivalence",
                    status="failed", error="invalid top identifier",
                    validation={"verdict": "fail", "failure_phase": "input"})
    binding = params.get("pdk_binding")
    binding_incomplete = (
        not isinstance(binding, dict)
        or not binding.get("pdk")
        or not binding.get("stdcell_library")
    )
    if binding_incomplete:
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error=("hierarchical proof requires pdk_binding.pdk and "
                   "pdk_binding.stdcell_library"),
            validation={"verdict": "fail", "failure_phase": "model_resolution"})
    if params.get("cell_models") is not None \
            or params.get("functional_verilog") is not None:
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error=("hierarchical proof forbids direct cell-model overrides; "
                   "use the pinned binding"),
            validation={"verdict": "fail", "failure_phase": "model_resolution"})
    binding_params = {
        "pdk_binding": binding,
        "normalization_corner": params.get("normalization_corner"),
    }
    liberty, liberty_expected, liberty_error = _resolve_liberty(binding_params)
    if liberty_error or not liberty_expected:
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error=liberty_error or "binding Liberty SHA-256 is required",
            validation={"verdict": "fail", "failure_phase": "model_resolution"})
    params = dict(params)
    params["liberty"] = liberty
    params["liberty_sha256"] = liberty_expected
    if params.get("eqy_match") or params.get("eqy_match_directives"):
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error=("hierarchical_rtl_vs_netlist forbids heuristic EQY match "
                   "directives; use exact models and typed abstractions"),
            validation={"verdict": "fail", "failure_phase": "mapping_policy"})
    intentional = params.get("intentional_blackbox_modules")
    if not isinstance(intentional, (list, tuple)) or not intentional \
            or not all(_is_ident(item) for item in intentional):
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error="intentional_blackbox_modules must contain safe module identifiers",
            validation={"verdict": "fail", "failure_phase": "abstraction_policy"})
    passive_inout = params.get("passive_inout_blackbox_modules") or []
    if not isinstance(passive_inout, (list, tuple)) or not all(
            _is_ident(item) for item in passive_inout):
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error="passive_inout_blackbox_modules must contain safe identifiers",
            validation={"verdict": "fail", "failure_phase": "abstraction_policy"})
    passive_instances = params.get("passive_blackbox_instances") or []
    if not isinstance(passive_instances, (list, tuple)) or not all(
            isinstance(instance, str) and instance for instance in passive_instances):
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error="passive_blackbox_instances must contain non-empty instance names",
            validation={"verdict": "fail", "failure_phase": "abstraction_policy"})
    if not set(passive_inout).issubset(intentional):
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error="passive inout modules must also be intentional blackboxes",
            validation={"verdict": "fail", "failure_phase": "abstraction_policy"})
    for required in ("functional_mutation_revised", "blackbox_rewire_revised"):
        if not params.get(required):
            return _cde(
                objective=f"hierarchical RTL-to-netlist equivalence of {top}",
                status="failed", error="missing mandatory control: " + required,
                validation={"verdict": "fail", "failure_phase": "control_inputs"})
    try:
        macro_paths, macro_evidence = _hierarchical_model_specs(params)
    except ValueError as exc:
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed", error=str(exc),
            validation={"verdict": "fail", "failure_phase": "model_resolution"})
    modeled_modules = {
        module for item in macro_evidence for module in item["modules"]
    }
    overlap = modeled_modules.intersection(intentional)
    if overlap:
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error="modules cannot be both functionally modeled and blackboxed: "
                  + ", ".join(sorted(overlap)),
            validation={"verdict": "fail", "failure_phase": "abstraction_policy"})

    fingerprint, setup = _proof_setup_fingerprint(
        params, macro_evidence, intentional, passive_inout, passive_instances)
    revised_sha = setup["revised_sha256"]
    if not revised_sha or setup["functional_mutation_sha256"] == revised_sha:
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error="functional mutation control must differ from the revised design",
            validation={"verdict": "fail", "failure_phase": "control_inputs"})
    if setup["blackbox_rewire_sha256"] == revised_sha:
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error="blackbox rewire control must differ from the revised design",
            validation={"verdict": "fail", "failure_phase": "control_inputs"})
    if fingerprint in (params.get("prior_failed_setup_fingerprints") or []):
        return _cde(
            objective=f"hierarchical RTL-to-netlist equivalence of {top}",
            status="failed",
            error=("identical failed proof setup already attempted; route to "
                   "proof-harness remediation instead of retrying"),
            validation={"verdict": "fail", "failure_phase": "repeated_setup"},
            provenance={"proof_setup_fingerprint": fingerprint,
                        "proof_setup": setup})

    nested = dict(params)
    nested["shared_functional_models"] = macro_paths
    nested["shared_blackbox_modules"] = list(intentional)
    nested["passive_inout_blackbox_modules"] = list(passive_inout)
    nested["passive_blackbox_instances"] = list(passive_instances)
    nested["pdk_binding"] = {
        "pdk": binding["pdk"],
        "stdcell_library": binding["stdcell_library"],
        "binding_sha256": binding.get("binding_sha256"),
    }
    for key in ("macro_models", "intentional_blackbox_modules",
                "functional_mutation_revised", "blackbox_rewire_revised",
                "prior_failed_setup_fingerprints"):
        nested.pop(key, None)
    positive = _run_hierarchical_subproof(nested, "positive", params["revised"])
    mutation = _run_hierarchical_subproof(
        nested, "functional-mutation", params["functional_mutation_revised"])
    rewire = _run_hierarchical_subproof(
        nested, "blackbox-input-rewire", params["blackbox_rewire_revised"])
    child_artifacts = {
        "positive": _artifact_manifest(os.path.join(_OUTPUT_DIR, "positive")),
        "functional_mutation": _artifact_manifest(
            os.path.join(_OUTPUT_DIR, "functional-mutation")),
        "blackbox_input_rewire": _artifact_manifest(
            os.path.join(_OUTPUT_DIR, "blackbox-input-rewire")),
    }

    positive_pass = (positive.get("validation") or {}).get("verdict") == "pass"
    mutation_residual = (mutation.get("qor_metrics") or {}).get("unproven_points")
    mutation_confirmation = ((mutation.get("signoff_evidence") or {})
                             .get("whole_design_confirmation") or {})
    mutation_detected = (
        mutation.get("status") == "completed"
        and (mutation.get("validation") or {}).get("verdict") == "fail"
        and mutation_confirmation.get("ran") is True
        and mutation_confirmation.get("equivalent") is False
        and mutation_confirmation.get("returncode") == 1
        and isinstance(mutation_residual, int) and mutation_residual > 0)
    rewire_error = str(rewire.get("error") or "")
    rewire_confirmation = ((rewire.get("signoff_evidence") or {})
                          .get("whole_design_confirmation") or {})
    rewire_residual = (rewire.get("qor_metrics") or {}).get("unproven_points")
    rewire_blackboxes = (rewire.get("signoff_evidence") or {}).get("black_boxes") or {}
    rewire_detected = (
        (rewire.get("validation") or {}).get("verdict") == "fail"
        and ("blackbox input source mismatch" in rewire_error
             or (rewire.get("status") == "completed"
                 and rewire_confirmation.get("ran") is True
                 and rewire_confirmation.get("equivalent") is False
                 and rewire_confirmation.get("returncode") == 1
                 and isinstance(rewire_residual, int) and rewire_residual > 0
                 and rewire_blackboxes.get("input_equivalence_obligations", 0) > 0)))
    positive_qor = positive.get("qor_metrics") or {}
    positive_blackboxes = (positive.get("signoff_evidence") or {}).get("black_boxes")
    model_scope_assessed = (
        isinstance(positive_blackboxes, dict)
        and isinstance(positive_blackboxes.get("unexpected_gold_cells"), list)
        and isinstance(positive_blackboxes.get("unexpected_gate_cells"), list))
    unexpected = (positive_blackboxes or {}).get("unexpected_gate_cells") \
        if model_scope_assessed else None
    model_scope_clean = (
        model_scope_assessed
        and positive_blackboxes.get("unexpected_gold_cells") == []
        and positive_blackboxes.get("unexpected_gate_cells") == [])
    verdict = "pass" if (positive_pass and mutation_detected and rewire_detected
                          and model_scope_clean) else "fail"
    abstraction = {
        "functional_model": macro_evidence,
        "intentional_blackbox": sorted(intentional),
        "passive_inout_blackbox": sorted(passive_inout),
        "passive_blackbox_instance": sorted(passive_instances),
        "unexpected": unexpected,
        "assessed": model_scope_assessed,
    }
    control_failures = (int(not positive_pass) + int(not mutation_detected)
                        + int(not rewire_detected) + int(not model_scope_clean))
    return _cde(
        objective=f"hierarchical RTL-to-netlist equivalence of {top}",
        status="completed", pdk_binding=params.get("pdk_binding", "none"),
        inputs_ref={"reference": params.get("reference"),
                    "revised": params.get("revised"),
                    "functional_mutation_revised": params.get("functional_mutation_revised"),
                    "blackbox_rewire_revised": params.get("blackbox_rewire_revised"),
                    "macro_models": [item["path"] for item in macro_evidence]},
        results={
            "positive_proof": {"verdict": (positive.get("validation") or {}).get("verdict"),
                               "status": positive.get("status"),
                               "error": positive.get("error"),
                               "compared_key_points": positive_qor.get("total_key_points"),
                               "proven_key_points": positive_qor.get("proven_key_points"),
                               "unproven_points": positive_qor.get("unproven_points")},
            "functional_mutation_control": {
                "status": mutation.get("status"),
                "error": mutation.get("error"),
                "verdict": (mutation.get("validation") or {}).get("verdict"),
                "unproven_points": mutation_residual,
                "proof_confirmation": mutation_confirmation,
                "detected": mutation_detected},
            "blackbox_input_rewire_control": {
                "verdict": (rewire.get("validation") or {}).get("verdict"),
                "proof_confirmation": rewire_confirmation,
                "unproven_points": rewire_residual,
                "input_equivalence_obligations": rewire_blackboxes.get(
                    "input_equivalence_obligations"),
                "detected": rewire_detected, "error": rewire_error},
            "failing_points": {"value": control_failures, "unit": "controls"},
            "abstraction_policy": abstraction},
        qor={"unproven_points": positive_qor.get("unproven_points"),
               "total_key_points": positive_qor.get("total_key_points"),
               "total_partitions": positive_qor.get("total_key_points"),
             "unmapped_points": ((positive.get("results") or {})
                                 .get("mapping", {}).get("unmapped_points")),
             "unexpected_residual_cells": (
                 len(unexpected) if isinstance(unexpected, list) else None)},
        signoff={"verdict": verdict,
                 "mapping_basis": "exact hierarchical instance/type/port; no positional mapping",
                 "abstraction_policy": abstraction,
                 "blackbox_semantics": positive_blackboxes,
                 "proof_artifacts": child_artifacts},
        validation={"verdict": verdict, "positive_non_vacuous": positive_pass,
                    "functional_mutation_detected": mutation_detected,
                    "blackbox_input_rewire_detected": rewire_detected,
                    "no_positional_mapping": True},
        provenance={"proof_setup_fingerprint": fingerprint,
                    "proof_setup": setup,
                    "engine": "yosys-flat-shared-blackbox",
                    "task_id": params.get("task_id")})


def _post_dft_mission(params):
    top = params.get("top")
    if not _is_ident(top):
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error="invalid top identifier",
                    validation={"verdict": "fail", "failure_phase": "input"})
    if params.get("reference") in (None, "") or params.get("revised") in (None, ""):
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error="reference and revised inputs are required",
                    validation={"verdict": "fail", "failure_phase": "input"})
    try:
        reference = _stage(params.get("reference"), "post_dft_reference.v")
        revised = _stage(params.get("revised"), "post_dft_revised.v")
    except Exception as exc:
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error="could not stage proof inputs: %s" % exc,
                    validation={"verdict": "fail", "failure_phase": "input"})
    liberty, liberty_expected, liberty_error = _resolve_liberty(params)
    model, model_expected, model_spec = _resolve_model(params)
    if liberty_error:
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error=liberty_error,
                    validation={"verdict": "fail", "failure_phase": "model_resolution"})
    if not liberty_expected:
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error="expected functional Liberty SHA-256 is required",
                    validation={"verdict": "fail", "failure_phase": "model_resolution"})
    if model is None:
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error="functional Verilog cell model is required",
                    validation={"verdict": "fail", "failure_phase": "model_resolution"})
    if not model_expected:
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error="expected functional Verilog SHA-256 is required",
                    validation={"verdict": "fail", "failure_phase": "model_resolution"})
    model_actual = _hash_input_file(model)
    if model_expected and (not model_actual or
            model_actual["sha256"].lower() != str(model_expected).lower()):
        return _cde(objective="post-DFT mission equivalence", status="failed",
                    error="functional Verilog model SHA-256 verification failed",
                    validation={"verdict": "fail", "failure_phase": "model_resolution"})
    try:
        reference_interface, ref_probe_s = _probe_interface(
            reference, top, "reference")
        revised_interface, rev_probe_s = _probe_interface(
            revised, top, "revised")
        if reference_interface != revised_interface:
            raise ValueError("reference and revised top interfaces differ")
        wrapper_text = _mission_wrapper(
            top, reference_interface, params.get("functional_mode"))
    except Exception as exc:
        return _cde(
            objective=f"post-DFT mission equivalence of {top}", status="failed",
            error=str(exc), pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail", "failure_phase": "interface_mode"})

    try:
        results_dir = os.path.join(_OUTPUT_DIR, "results")
        os.makedirs(results_dir, exist_ok=True)
        wrapper = os.path.join(results_dir, "mission_wrapper.v")
        open(wrapper, "w").write(wrapper_text)
        ref_norm, ref_summary, ref_s = _normalize_post_dft_side(
            reference, top, wrapper, liberty, model, model_spec, "reference")
        rev_norm, rev_summary, rev_s = _normalize_post_dft_side(
            revised, top, wrapper, liberty, model, model_spec, "revised")
        if ref_summary["interface"] != rev_summary["interface"]:
            raise ValueError("normalized top interfaces differ")
        if ref_summary["state_count"] != rev_summary["state_count"]:
            raise ValueError(
                "normalized state counts differ: reference=%d revised=%d"
                % (ref_summary["state_count"], rev_summary["state_count"]))
        expected_states = params.get("expected_state_points")
        if expected_states is not None and \
                ref_summary["state_count"] != int(expected_states):
            raise ValueError(
                "normalized state count %d does not match expected %d"
                % (ref_summary["state_count"], int(expected_states)))
    except Exception as exc:
        return _cde(
            objective=f"post-DFT mission equivalence of {top}", status="failed",
            error=str(exc), pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail", "failure_phase": "normalization"})

    proof_params = dict(params)
    proof_params.update({
        "scenario": "netlist_vs_netlist",
        "reference": ref_norm,
        "revised": rev_norm,
        "inputs_pre_normalized": True,
    })
    result = _equiv(proof_params)
    if (result.get("validation") or {}).get("verdict") != "pass":
        result.setdefault("validation", {}).setdefault("failure_phase", "proof")
    result["objective"] = f"post-DFT mission equivalence of {top}"
    result.setdefault("inputs_ref", {}).update({
        "original_reference": reference,
        "original_revised": revised,
        "functional_liberty": liberty,
        "functional_verilog": model,
        "mission_wrapper": wrapper,
    })
    result.setdefault("results", {})["mission_normalization"] = {
        "functional_mode": dict(params.get("functional_mode") or {}),
        "reference": ref_summary,
        "revised": rev_summary,
        "interfaces_equal": True,
        "state_counts_equal": True,
    }
    result.setdefault("signoff_evidence", {})["operating_mode"] = {
        "name": "mission",
        "constraints": dict(params.get("functional_mode") or {}),
        "applied_symmetrically": True,
    }
    result.setdefault("provenance", {})["normalization"] = {
        "method": "symmetric Liberty/functional-Verilog lowering and techmap",
        "reference_seconds": round(ref_probe_s + ref_s, 3),
        "revised_seconds": round(rev_probe_s + rev_s, 3),
        "liberty_sha256": (_hash_input_file(liberty) or {}).get("sha256"),
        "liberty_expected_sha256": liberty_expected,
        "functional_verilog_sha256": (model_actual or {}).get("sha256"),
        "functional_verilog_expected_sha256": model_expected,
    }
    return result


_LEC_PARTITION_BASIS = "parsed_eqy_partition_summary"
_LEC_FLAT_BASIS = (
    "flat_whole_design_equiv_proof (equiv_make + equiv_simple + equiv_induct; "
    "supersedes the partitioned eqy tally recorded in signoff.diagnostics)")


def _lec_gating_basis(partition_equiv_pts, partition_total_pts,
                       partition_unproven, flat_confirm):
    """Decide, in exactly ONE place, which proof run backs the gating triple.

    (DX-154) Origin defect: a mixed-basis triple -- 15 equivalent / 19 total
    from the PARTITIONED eqy run paired with 0 unproven from a SEPARATE flat
    whole-design proof that superseded it (15+0 != 19). Numerator and
    denominator must always be read from the SAME proof, so this function
    returns the full (equiv, total, unproven) triple TOGETHER, never a partial
    override of just one field.

    Defaults to the partitioned tally. Moves to the flat proof ONLY when
    `flat_confirm` unambiguously records one that RAN, is EQUIVALENT, and
    parsed both a proven and an unproven cell count as integers -- an
    inconclusive, errored, unparsed, or non-equivalent flat run must leave the
    partitioned basis (and verdict) exactly as it was; this can only ever make
    the gate MORE conservative, never launder a real failure.
    """
    if (isinstance(flat_confirm, dict) and flat_confirm.get("ran")
            and flat_confirm.get("equivalent") is True
            and isinstance(flat_confirm.get("proven_cells"), int)
            and isinstance(flat_confirm.get("unproven_cells"), int)):
        proven = flat_confirm["proven_cells"]
        flat_unproven = flat_confirm["unproven_cells"]
        return proven, proven + flat_unproven, flat_unproven, _LEC_FLAT_BASIS
    return (partition_equiv_pts, partition_total_pts, partition_unproven,
            _LEC_PARTITION_BASIS)


# --- DX-162: reference input authenticity --------------------------------
# Origin defect: `lec-post-synth.5` accepted
# `campaigns/mytop4-hiersoc/environment-smoke/retry-3/functional/cdc/input/
# bsum16.v` -- a 951-byte environment-SMOKE-TEST fixture, not the design's
# registered `rtl.N` output -- as the golden reference, then compared the
# netlist synthesized FROM that stub against the stub itself. The proof was
# internally consistent and therefore green; it proved only that a wrong
# netlist matched a wrong reference. Nothing in the tool flagged that the
# reference lived outside the design's own stage tree.
#
# Two layers, both fail-closed:
#   1. CATEGORICAL: a reference (or revised) path resolving under a known
#      fixture/scratch tree (`environment-smoke/` and siblings) is refused
#      outright, for every scenario -- a fixture is never a signoff input,
#      regardless of what it contains.
#   2. IDENTITY: for scenarios where `reference` is asserted to be RTL
#      (`rtl_vs_netlist`, `hierarchical_rtl_vs_netlist`), when the `revised`
#      path names a recognizable `campaigns/<slug>/<design>/<design>.<N>/...`
#      stage tree, the design's own `versions.json` is consulted and the
#      reference file's content hash is required to match the CURRENTLY
#      REGISTERED `rtl` stage output for that exact design version. A
#      mismatch -- wrong file, stale file, or a file from outside the design's
#      tree entirely -- fails the gate loudly rather than silently comparing
#      whatever the caller happened to pass.
# When campaign context cannot be established (no recognizable stage path --
# e.g. a bare unit-test invocation with synthetic paths) the identity check is
# SKIPPED, not passed: it is not assessable outside a campaign, so it must
# never be reported as satisfied. The categorical fixture check still applies
# unconditionally in every case.
_FIXTURE_PATH_SEGMENTS = ("environment-smoke", "scratch", "fixtures", "fixture")

_CAMPAIGN_STAGE_PATH_RE = re.compile(
    r"(?P<root>.*campaigns/[^/]+)/(?P<design>[^/]+)/(?P<dv>[^/]+)/")


def _fixture_path_hit(path):
    """Return the offending path segment if `path` resolves under a known
    fixture/scratch tree, else None. Checked as whole path SEGMENTS (not a
    bare substring) so a design legitimately named e.g. `fixturebus` is not
    falsely flagged."""
    segments = str(path).replace("\\", "/").split("/")
    for seg in segments:
        if seg in _FIXTURE_PATH_SEGMENTS:
            return seg
    return None


def _parse_campaign_stage_path(path):
    """Parse a `.../campaigns/<slug>/<design>/<design_version>/...` path.
    Returns a dict with `campaign_root` (the path through `campaigns/<slug>`),
    `design`, and `design_version`, or None if `path` does not look like a
    registered campaign stage-tree path at all."""
    m = _CAMPAIGN_STAGE_PATH_RE.search(str(path).replace("\\", "/"))
    if not m:
        return None
    return {"campaign_root": m.group("root"), "design": m.group("design"),
            "design_version": m.group("dv")}


def _resolve_registered_rtl_file(campaign_root, design, design_version):
    """Resolve the currently-registered `rtl` stage output file for
    `design`/`design_version` from `campaign_root/versions.json`. Returns
    (path, None) on success or (None, reason) when it cannot be resolved --
    the caller must treat an unresolved lookup as NOT ASSESSABLE, never as a
    pass."""
    m = re.match(r"^(?P<repo>.*?)campaigns/[^/]+$", campaign_root)
    repo_root = m.group("repo") if m else ""
    versions_path = os.path.join(repo_root, campaign_root, "versions.json")
    if not os.path.isfile(versions_path):
        return None, f"versions.json not found at {versions_path!r}"
    try:
        versions = json.load(open(versions_path))
    except Exception as exc:
        return None, f"versions.json unreadable: {exc}"
    design_entry = (versions.get("designs") or {}).get(design)
    if not isinstance(design_entry, dict):
        return None, f"design {design!r} not present in {versions_path!r}"
    dv_entry = (design_entry.get("design_versions") or {}).get(design_version)
    if not isinstance(dv_entry, dict):
        return None, (f"design_version {design_version!r} not present for "
                       f"design {design!r} in {versions_path!r}")
    rtl_stage = (dv_entry.get("stages") or {}).get("rtl")
    if not isinstance(rtl_stage, dict) or rtl_stage.get("status") != "completed":
        return None, (f"no completed 'rtl' stage registered for "
                       f"{design_version!r} in {versions_path!r}")
    results_dir = rtl_stage.get("results")
    if not results_dir:
        return None, f"registered 'rtl' stage for {design_version!r} has no results dir"
    candidate = os.path.join(repo_root, results_dir, design + ".v")
    if os.path.isfile(candidate):
        return candidate, None
    abs_results = os.path.join(repo_root, results_dir)
    if os.path.isdir(abs_results):
        vs = sorted(f for f in os.listdir(abs_results) if f.endswith(".v"))
        if len(vs) == 1:
            return os.path.join(abs_results, vs[0]), None
    return None, f"no registered RTL output file found under {abs_results!r}"


def _check_reference_authenticity(params, top):
    """Return an error string when `reference` fails input authenticity, or
    None when the reference is accepted (either verified, or not assessable
    because no campaign context is present -- see module docstring above)."""
    for role, raw in (("reference", params.get("reference")),
                      ("revised", params.get("revised"))):
        if raw is None or not os.path.exists(str(raw)):
            continue
        hit = _fixture_path_hit(raw)
        if hit:
            return (f"{role} {str(raw)!r} resolves under a {hit!r} fixture/"
                     "scratch tree, not a design's own stage tree; a fixture "
                     "path is categorically refused as signoff input")
    scenario = params.get("scenario")
    if scenario not in ("rtl_vs_netlist", "hierarchical_rtl_vs_netlist"):
        return None
    ref_raw = params.get("reference")
    rev_raw = params.get("revised")
    if ref_raw is None or not os.path.exists(str(ref_raw)):
        return None  # inline-text reference; nothing on disk to authenticate
    if rev_raw is None:
        return None
    parsed = _parse_campaign_stage_path(rev_raw)
    if not parsed or parsed["design"] != top:
        return None  # no recognizable campaign context; not assessable
    registered, reason = _resolve_registered_rtl_file(
        parsed["campaign_root"], parsed["design"], parsed["design_version"])
    if registered is None:
        return None  # bookkeeping unresolved; not assessable, not a pass
    ref_hash = _hash_input_file(str(ref_raw))
    reg_hash = _hash_input_file(registered)
    if not ref_hash or not reg_hash or ref_hash["sha256"] != reg_hash["sha256"]:
        return (f"reference {str(ref_raw)!r} does not match the sha256 of the "
                f"design's currently registered rtl stage output "
                f"{registered!r} for design_version {parsed['design_version']!r} "
                f"(reference sha256={ref_hash and ref_hash['sha256']}, "
                f"registered sha256={reg_hash and reg_hash['sha256']})")
    return None


# --- DX-162: key-point / equivalence-point population plausibility -------
# Origin defect: `lec-post-synth.5` certified whole-design equivalence from a
# population of 2 equivalent (of 4 total) partitions on a 33-flop design.
# No count this small can constitute a whole-design proof: a partition-level
# or flat-cell-level population smaller than either side's OWN measured
# flop/latch count has not looked at every flop, by construction, no matter
# what the underlying proof engine reports for that population.
_SEQ_CELL_NAME_RE = re.compile(
    r"\$_?A?S?DFF|dff|dfx|dfr|dfs|dfb|dfc|dlx|dlr|dln|dlatch|\blatch\b", re.I)


def _count_sequential_cells(read_block, top, stem):
    """Read `read_block` and report the total instance count of cells whose
    type name matches a flop/latch naming convention (works uninstantiated,
    on generic Yosys internal cells, and on sky130_fd_sc_hd macro names).
    Returns (count_or_None, raw_stat_text). A None count means NOT MEASURED
    (elaboration failed), and must never be read as zero."""
    script = f"{read_block}\nhierarchy -top {top}\nproc\nstat\n"
    proc, _ = _run_yosys_named(script, stem)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        return None, text
    # `stat` (without `-top`) prints ONE "Local Count, excluding submodules"
    # section per module it touches: first the top module's own instance
    # tally, then a further section for every *cell type* used underneath it
    # (e.g. each sky130 std-cell's own internal primitive make-up). Summing
    # across the whole log double(triple/...)-counts every flop -- e.g. a
    # 33-dfxtp design showed up as 133 because each dfxtp's own 3-cell
    # internal section also matched the flop-name regex. Only the FIRST
    # "=== <top> ===" section (the design's own local instance count) is the
    # design's actual flop/latch population; stop at the next section header.
    header = re.compile(r"^===\s+" + re.escape(top) + r"\s+===\s*$")
    next_header = re.compile(r"^===\s+\S")
    total = 0
    in_top_section = False
    for line in text.splitlines():
        if header.match(line.strip()):
            in_top_section = True
            continue
        if in_top_section and next_header.match(line.strip()):
            break
        if not in_top_section:
            continue
        m = re.match(r"\s*(\d+)\s+(\S+)\s*$", line)
        if m and _SEQ_CELL_NAME_RE.search(m.group(2)):
            total += int(m.group(1))
    if not in_top_section:
        # stat never printed a section named after `top` (e.g. hierarchy
        # renamed/flattened it) -- not measured, never silently zero.
        return None, text
    return total, text


def _key_point_plausibility(population, ref_seq_count, rev_seq_count):
    """Gate a whole-design equivalence claim on key-point-count plausibility.
    Floor is the LARGER of the two designs' own measured flop/latch counts:
    a population below that floor cannot have examined every flop on the
    larger side, so it can never be a whole-design proof, regardless of what
    the underlying proof engine reported for that population."""
    if population is None or ref_seq_count is None or rev_seq_count is None:
        return {"checked": False, "plausible": True,
                "reason": "key-point population or a side's sequential-"
                          "element count could not be measured; plausibility "
                          "is NOT ASSESSED (never reported as satisfied)"}
    floor = max(ref_seq_count, rev_seq_count)
    if floor <= 0:
        return {"checked": False, "plausible": True,
                "reason": "neither side has measurable sequential elements; "
                          "plausibility floor is not meaningful"}
    plausible = population >= floor
    return {
        "checked": True,
        "plausible": plausible,
        "population": population,
        "reference_sequential_elements": ref_seq_count,
        "revised_sequential_elements": rev_seq_count,
        "floor": floor,
        "reason": (
            "population is plausible" if plausible else
            f"key-point/equivalence-point population ({population}) is "
            f"smaller than the larger side's own measured flop/latch count "
            f"({floor}); a whole-design equivalence claim cannot cover every "
            "flop with fewer key points than flops exist -- refusing to "
            "certify whole_design_confirmation.equivalent=true"
        ),
    }


_HIER_GUARD_MARK = "t:$paramod*"


def _hierarchy_flattened_guard(top):
    """Yosys assert: no user-module instance survives flattening in `top`.

    MEASURED on uart_apb (hierarchical RTL: uart_rx/uart_tx/2x uart_fifo):
    the whole-design proof stashed a gold that had only been `prep`-ed, never
    flattened, and `design -copy-from gold -as gold <top>` copies ONLY the top
    module -- so the submodule instances arrived in the miter as opaque cells:
        ERROR: No SAT model available for cell
               $auto$rename.cc:500:execute$705_gold (uart_rx).
    The run then kept EQY's partition failure as a "non-equivalent" verdict --
    a FALSE NEGATIVE on a design whose gate-level simulation passes. Every
    cell left after `flatten` must be a Yosys internal (`$...`) primitive; a
    derived parametric module (`$paramod...`) is a user module too. Any
    survivor is a setup error and fails the run closed, never a verdict.
    """
    return (f"select -assert-none {top}/t:* {top}/t:$* %d "
            f"{top}/{_HIER_GUARD_MARK} %u\n")


def _unflattened_cells(log_text):
    """Return the user-module cells a proof log shows surviving flattening.

    Empty list means the log carries no evidence of an unflattened hierarchy.
    """
    text = log_text or ""
    found = []
    for name, cell_type in re.findall(
            r"No SAT model available for cell\s+(\S+)\s+\(([^)\s]+)\)", text):
        found.append(f"{name} ({cell_type})")
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if ("Assertion failed: selection is not empty" not in line
                or _HIER_GUARD_MARK not in line):
            continue
        tripped = []
        for follow in lines[idx + 1: idx + 200]:
            if "Selection contains" in follow:
                continue
            m = re.search(r"(\S+/\S+)\s*$", follow)
            if not m:
                break
            tripped.append(m.group(1))
        found.extend(tripped or ["<guard tripped; see log>"])
    return sorted(set(found))


def _hierarchy_not_flattened_cde(top, params, cells, log_name, inputs_ref):
    """Fail closed: an unflattened side is a setup error, never a verdict."""
    return _cde(
        objective=f"logical equivalence of {top}", status="failed",
        error="hierarchy not flattened: " + ", ".join(cells),
        pdk_binding=params.get("pdk_binding", "none"),
        validation={"verdict": "fail",
                    "note": ("user-module instances survived flattening, so "
                             "no equivalence or non-equivalence verdict can "
                             "be drawn; see " + log_name)},
        provenance={"engine": "eqy", "log": log_name,
                    "unflattened_cells": list(cells)},
        inputs_ref=inputs_ref)


def _eqy_problem_text(top, read_ref, lib_read, shared_model_read, read_rev,
                      init_norm, gate_model_guard, match_block, depth):
    """Assemble the EQY problem file.

    Pure so the `[gate]` read order is directly testable. `shared_functional_
    models` was computed and then used by every OTHER code path except this one
    -- the proof that actually decides the gate -- so supplying the parameter
    changed nothing and failed with an unrelated "module not part of the design"
    error. Keeping the assembly in one pure function is what makes that class of
    omission visible to a test instead of only to a caller.
    """
    hier_guard = _hierarchy_flattened_guard(top)
    return f"""[options]

[gold]
{read_ref}
prep -top {top}
flatten
{hier_guard}memory
{init_norm}hierarchy -top {top} -purge_lib

[gate]
{lib_read}{shared_model_read}{read_rev}
prep -top {top}
{gate_model_guard}
{hier_guard}{init_norm}hierarchy -top {top} -purge_lib
{match_block}
[strategy sat]
use sat
depth {depth}

[strategy induct]
use sby
depth {depth}
engine smtbmc
"""


def _partition_boundary_evidence(failed_partitions):
    """Preserve EQY's own cut structure for every partition that failed.

    A partitioned counterexample is only readable together with the partition's
    CUT: EQY proves each partition with its boundary inputs LEFT FREE, so a
    failing partition that frees a SIBLING OUTPUT BIT (ABC shares XOR sub-terms
    across a CRC/parity tree) or the far end of a `assign <port> = <reg>;` alias
    can report "not equivalent" on a design that is genuinely equivalent.

    Both shapes were diagnosed by hand, twice, by copying `partition.log` and
    `partitions/*.json` out of a container that no longer exists. Those files
    live inside EQY's workdir and are discarded with it, so the analysis was not
    reproducible from the recorded attempt. This copies them into the attempt
    output and precomputes the free-boundary-input list per failing partition,
    so the next reader gets the discriminator instead of the forensics.

    Purely descriptive: it records structure, and never touches the verdict.
    """
    eqy_dir = os.path.join(_WORK_DIR, "lec")
    log_src = os.path.join(eqy_dir, "partition.log")
    evidence = {"partition_log": None, "free_boundary_inputs": {},
                "partition_outputs": {},
                "free_inputs_that_are_partition_outputs": {},
                "note": ("EQY cuts each partition with its boundary inputs "
                         "FREE. A free input that is also ANOTHER partition's "
                         "output (see free_inputs_that_are_partition_outputs) "
                         "is the fingerprint of both known artifacts: a shared "
                         "XOR sub-term across sibling output bits, and a "
                         "reversed `assign <port> = <reg>;` alias. Read these "
                         "before treating a partition failure as a functional "
                         "mismatch.")}
    try:
        if os.path.isfile(log_src):
            shutil.copyfile(log_src, os.path.join(_OUTPUT_DIR, "partition.log"))
            evidence["partition_log"] = "partition.log"
    except Exception as exc:
        evidence["partition_log_error"] = str(exc)
    part_dir = os.path.join(eqy_dir, "partitions")
    if not os.path.isdir(part_dir):
        return evidence

    def _signals(raw):
        # MEASURED shape: {"<signal>": [<bit>, ...]}. A list is accepted too so
        # a future EQY that flattens it does not silently record nothing.
        if isinstance(raw, dict):
            return sorted(str(key) for key in raw)
        if isinstance(raw, (list, tuple)):
            return sorted(str(item) for item in raw)
        return []

    def _spec_of(name):
        path = os.path.join(part_dir, str(name) + ".json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                document = json.load(handle)
        except Exception:
            return None
        inner = document.get("partition")
        return inner if isinstance(inner, dict) else document

    # Every partition's outputs, so a free input can be identified as some other
    # partition's output rather than a true primary input.
    all_outputs = {}
    for entry in sorted(os.listdir(part_dir)):
        if not entry.endswith(".json"):
            continue
        spec = _spec_of(entry[:-len(".json")])
        if spec:
            for signal in _signals(spec.get("outbits")):
                all_outputs.setdefault(signal, entry[:-len(".json")])

    for name in sorted(failed_partitions):
        spec = _spec_of(name)
        if not spec:
            continue
        inbits = _signals(spec.get("inbits"))
        outbits = _signals(spec.get("outbits"))
        evidence["free_boundary_inputs"][str(name)] = inbits
        evidence["partition_outputs"][str(name)] = outbits
        shared = {signal: all_outputs[signal] for signal in inbits
                  if signal in all_outputs and all_outputs[signal] != str(name)}
        if shared:
            evidence["free_inputs_that_are_partition_outputs"][str(name)] = shared
    return evidence


def _liberty_read_block(lib):
    """Yosys read block for the functional-Liberty gate-model path.

    Shared by the primary Liberty branch and the automatic fallback taken when a
    declared Verilog cell model turns out to be unreadable, so both paths emit
    byte-identical script text and cannot drift apart.
    """
    return f"read_liberty -ignore_miss_func {_yosys_arg(lib)}\n"


def _liberty_model_source(lib):
    return (os.path.basename(str(lib))
            + " (functional, -ignore_miss_func + "
              "post-flatten no-unmodelled-cell assert)")


def _probe_gate_model_read(read_block, stem="gate_model_probe"):
    """Read-test the gate-side cell-model block and report whether Yosys can use it.

    This is a MEASUREMENT, not a heuristic. `hierarchy -check` (no `-top`) is
    what surfaces the real failure mode: a Verilog cell library whose sequential
    cells are defined as Verilog UDPs (`primitive`/`endprimitive`) in a sibling
    file parses fine on its own, then errors with "Module
    'sky130_fd_sc_hd__udp_dff$P' referenced in module ... is not part of the
    design". Yosys's Verilog frontend implements no UDP construct at all, so the
    sibling file cannot be supplied either -- it fails to parse outright.

    Returns (ok, log_text). `ok` False means the gate netlist CANNOT be read
    through this model, and the caller must fall back to the Liberty-functional
    read rather than let EQY fail later with an error that reads like a missing
    model instead of an unusable one.
    """
    script = f"{read_block}\nhierarchy -check\n"
    proc, _ = _run_yosys_named(script, stem)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode == 0, text


def _equiv(params):
    top = params["top"]
    if not _is_ident(top):
        return _cde(objective="logical equivalence", status="failed",
                    error=f"invalid 'top' identifier: {top!r}", validation={"verdict": "fail"})
    _auth_error = _check_reference_authenticity(params, top)
    if _auth_error:
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="reference/revised input authenticity check failed (DX-162): "
                  + _auth_error,
            pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail",
                        "note": "a fixture path or an unregistered RTL "
                                "reference is refused as signoff input"},
            provenance={"engine": "eqy",
                        "authenticity_check": "reference_vs_registered_rtl"})
    ref = _stage(params["reference"], "gold.v")
    rev = _stage(params["revised"], "gate.v")
    pre_normalized = bool(params.get("inputs_pre_normalized"))
    # `pdk_binding.liberty` is a {"path", "sha256", ...} RECORD in this repo's
    # binding schema, not a bare string. The former test here was
    # `elif lib and os.path.exists(str(lib))`, and `str(dict)` is never a
    # filesystem path -- so a caller who supplied only the binding got a
    # SILENTLY SKIPPED Liberty branch, an empty `lib_read`, a gate side carrying
    # no cell function at all, and a late "module not part of the design" error
    # that reads like a missing model rather than a plumbing bug.
    # `_resolve_liberty` already handles the string/dict/per-corner shapes every
    # other entry point in this module uses, so route through it here too.
    lib, lib_expected_sha256, lib_error = (
        (None, None, None) if pre_normalized else _resolve_liberty(params))
    lib_declared = (not pre_normalized) and _liberty_declared(params)
    if lib_declared and lib_error:
        # Declared-but-unusable is a hard failure. Silently continuing without
        # cell function is what turned a plumbing defect into an unexplained
        # non-equivalence.
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="declared functional Liberty could not be used: " + lib_error,
            pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail",
                        "note": "a declared Liberty view that does not resolve "
                                "or does not hash-verify is refused, never "
                                "silently skipped"},
            provenance={"engine": "eqy",
                        "liberty_expected_sha256": lib_expected_sha256})
    # Functional Verilog models take precedence over Liberty. When the binding
    # declares a model, its digest is an execution contract and is verified
    # before EQY is allowed to read the gate design.
    cell_v, cell_v_expected_sha256, cell_v_spec = (
        (None, None, None) if pre_normalized else _resolve_model(params))
    lib_read = ""
    _cell_model_source = "none"
    cell_v_actual = _hash_input_file(cell_v) if cell_v else None
    inputs_ref = dict(params.get("inputs_ref") or {})
    inputs_ref.setdefault("reference", ref)
    inputs_ref.setdefault("revised", rev)
    if cell_v:
        inputs_ref.setdefault("functional_cell_models", cell_v)
    if cell_v and not cell_v_actual:
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="functional cell-model file could not be hashed",
            pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail"},
            provenance={"engine": "eqy"})
    if cell_v_expected_sha256 and (
            not cell_v_actual
            or cell_v_actual["sha256"].lower() != str(cell_v_expected_sha256).lower()):
        return _cde(
            objective=f"logical equivalence of {top}", status="failed",
            error="functional cell-model SHA-256 verification failed",
            pdk_binding=params.get("pdk_binding", "none"),
            validation={"verdict": "fail"},
            provenance={
                "engine": "eqy",
                "cell_models_expected_sha256": cell_v_expected_sha256,
                "cell_models_actual": cell_v_actual,
            })
    if cell_v:
        if cell_v_actual is None:
            return _cde(
                objective=f"logical equivalence of {top}", status="failed",
                error="functional cell-model file could not be hashed",
                pdk_binding=params.get("pdk_binding", "none"),
                validation={"verdict": "fail"},
                provenance={"engine": "eqy"})
        # simcells supplies behavioral definitions for Yosys internal primitives
        # that can be emitted by a Liberty-to-Verilog functional-model export.
        # Flattening below removes both simcells and standard-cell modules before
        # EQY combines the gold and gate designs.
        try:
            define_args = _yosys_define_args(cell_v_spec)
        except ValueError as exc:
            return _cde(
                objective=f"logical equivalence of {top}", status="failed",
                error=str(exc), pdk_binding=params.get("pdk_binding", "none"),
                validation={"verdict": "fail"})
        lib_read = (
            "read_verilog +/simcells.v\n"
            f"read_verilog -sv {define_args} {_yosys_arg(cell_v)}\n"
        )
        _cell_model_source = {
            "path": cell_v,
            "sha256": cell_v_actual["sha256"],
            "bytes": cell_v_actual["bytes"],
            "hash_verified": bool(cell_v_expected_sha256),
        }
    elif lib:
        # Read the Liberty FUNCTIONALLY (no `-lib`): Yosys derives each cell's
        # combinational `function:` and sequential `ff`/`latch` behavior so the
        # gate netlist is provable. `-lib` would create EMPTY blackbox modules
        # (zero cells, no function), leaving every key point unproven -- the
        # defect that made a whole-macro RTL-vs-netlist proof report ~all points
        # unproven. The gate side of an equivalence proof MUST carry cell function.
        #
        # `-ignore_miss_func` is REQUIRED, not a shortcut. Without it a single
        # library cell whose output has no Liberty `function` aborts the ENTIRE
        # read before partitioning ever starts:
        #     ERROR: Missing function on output GCLK of cell
        #            sky130_fd_sc_hd__dlclkp_1.
        # sky130_fd_sc_hd ships exactly such cells (clock gates / latches), and
        # they are typically NOT INSTANTIATED by synthesis -- so the whole proof
        # was being refused over cells the design does not even use. This was the
        # FIRST blocker hit on DX-60.
        #
        # The flag alone would be unsafe: if a cell that IS instantiated lacks a
        # function, it silently becomes an empty module and the miter could
        # "prove" equivalence against nothing. That is why the generated script
        # ASSERTS, after flattening, that no standard cell survives -- a cell
        # with no function cannot be flattened into logic, so it would still be
        # present and the assert fails the run closed. Verified on bsum16: all 21
        # instantiated cell types flatten away and the assert passes.
        lib_read = _liberty_read_block(lib)
        _cell_model_source = _liberty_model_source(lib)
    # Language-aware read for each side: Verilog via read_verilog (default), VHDL
    # via the GHDL frontend (plugin -i ghdl; ghdl -e <top>). The reference is
    # commonly RTL (may be VHDL); the revised side is usually a gate netlist.
    _read_ref = rtl_frontend.yosys_read_block([ref], top, params)
    _read_rev = rtl_frontend.yosys_read_block([rev], top, params)
    _shared_models = params.get("shared_functional_models")
    _shared_model_read = ""
    if _shared_models:
        values = (_shared_models if isinstance(_shared_models, (list, tuple))
                  else [_shared_models])
        missing = [str(value) for value in values
                   if not os.path.isfile(str(value))]
        if missing:
            return _cde(
                objective=f"logical equivalence of {top}", status="failed",
                error="shared functional model file not found: " + ", ".join(missing),
                pdk_binding=params.get("pdk_binding", "none"),
                validation={"verdict": "fail"})
        _shared_model_read = "".join(
            f"read_verilog -sv {_yosys_arg(value)}\n" for value in values)
        inputs_ref.setdefault("shared_functional_models", list(values))
    # --- GATE CELL-MODEL READ-TEST, WITH AN AUTOMATIC LIBERTY FALLBACK -------
    # A binding's `functional_cell_models.yosys_model` is NOT guaranteed to be
    # readable by the installed Yosys. MEASURED on sky130_fd_sc_hd: the model
    # parses, then `hierarchy` errors with "Module 'sky130_fd_sc_hd__udp_dff$P'
    # referenced in module 'sky130_fd_sc_hd__dfxtp_1' ... is not part of the
    # design", because the sequential cells are Verilog UDPs defined in a
    # sibling `models/primitives.v` that Yosys's frontend cannot parse AT ALL
    # (`primitive`/`endprimitive` is unimplemented -- a two-line standalone UDP
    # reproduces `syntax error, unexpected TOK_ID`). Supplying that sibling via
    # `shared_functional_models` therefore cannot help either.
    #
    # Before this check the failure surfaced only once EQY was already running,
    # phrased as a missing module, and every caller had to rediscover the same
    # manual workaround (strip the model keys from a binding copy and pass an
    # explicit Liberty string). The Liberty-functional read is the tool's OWN
    # documented fallback for exactly this case; it was simply unreachable
    # automatically. This probe MEASURES readability and takes it.
    #
    # It can only ever make the run MORE likely to produce an honest verdict:
    # a model that reads cleanly is used unchanged, and when no Liberty is
    # available to fall back to, the run fails closed with the probe log
    # attached instead of an opaque downstream error.
    _model_fallback = None
    if cell_v:
        _probe_ok, _probe_log = _probe_gate_model_read(
            lib_read + _shared_model_read)
        if not _probe_ok:
            if not lib:
                return _cde(
                    objective=f"logical equivalence of {top}", status="failed",
                    error=("the bound functional Verilog cell model cannot be "
                           "read by this Yosys (see gate_model_probe.log) and "
                           "no functional Liberty view is available to fall "
                           "back to:\n" + _probe_log[-1500:]),
                    pdk_binding=params.get("pdk_binding", "none"),
                    validation={"verdict": "fail",
                                "note": "unreadable gate cell model with no "
                                        "Liberty fallback"},
                    provenance={"engine": "eqy",
                                "gate_model_probe": "gate_model_probe.log"})
            _model_fallback = {
                "from": "functional_cell_models (Verilog)",
                "from_path": cell_v,
                "to": "functional Liberty (read_liberty -ignore_miss_func)",
                "to_path": lib,
                "reason": ("the bound Verilog cell model is not readable by "
                           "this Yosys build; `hierarchy -check` failed"),
                "probe_log": "gate_model_probe.log",
                "probe_tail": _probe_log[-600:],
            }
            lib_read = _liberty_read_block(lib)
            _cell_model_source = _liberty_model_source(lib)
            inputs_ref.pop("functional_cell_models", None)
            inputs_ref["liberty"] = lib
            inputs_ref["functional_cell_models_rejected"] = cell_v
    # equiv_induct_depth: proof depth used by eqy's SAT strategy for sequential
    # key points (default 10). Kept as a param for backward compatibility.
    _ind = params.get("equiv_induct_depth")
    depth = int(_ind) if _ind is not None else 10
    # key_point_mapping_file: an optional Yosys script of explicit `equiv_add`
    # mappings, still honored via an eqy match-side script hook for renamed points.
    _kpm = params.get("key_point_mapping_file")
    _kpm_note = "eqy auto-partition (name/interface based)"
    _match_lines = []
    if _kpm and os.path.exists(str(_kpm)):
        _match_lines.append(f"script {_kpm}")
        _kpm_note = f"eqy auto-partition + explicit mapping ({os.path.basename(str(_kpm))})"
    # Inline EQY [match] directives resolve auto-matcher AMBIGUITY without a
    # separate file or a per-design tool rebuild. EQY's key-point matcher can
    # report "conflicting matches for gold bit ..." when a hierarchical net and a
    # gate cell pin are both plausible mates (seen on the M3 dcache PLRU
    # `maybe_plrus.plru_upd`), which aborts partitioning. A dispatch can pass
    # `eqy_match` (a raw multi-line [match] block) or `eqy_match_directives`
    # (a list of `match`/`nomatch`/`gold-nomatch`/`gate-nomatch` lines) to pin or
    # exclude the ambiguous point. These are STRUCTURAL key-point directives, not
    # waivers: they only tell EQY which points correspond, they never assert
    # equivalence -- every mapped partition is still fully proven.
    _eqy_match = params.get("eqy_match")
    _eqy_match_directives = params.get("eqy_match_directives")
    if isinstance(_eqy_match, str) and _eqy_match.strip():
        _match_lines.extend(_eqy_match.strip().splitlines())
        _kpm_note += " + inline match directives"
    if isinstance(_eqy_match_directives, (list, tuple)) and _eqy_match_directives:
        _match_lines.extend(str(d) for d in _eqy_match_directives if str(d).strip())
        _kpm_note += " + inline match directives"
    _match_module = params.get("eqy_match_module", "*")
    _match_block = (f"\n[match {_match_module}]\n" + "\n".join(_match_lines) + "\n") if _match_lines else ""
    # Init-normalization applied SYMMETRICALLY to gold and gate before EQY reads
    # each side. A GHDL-elaborated VHDL gold (and some gate netlists) carry
    # NON-CONSTANT FF `init` attributes that EQY `read_gold`/`read_gate` cannot
    # evaluate ("Failed to get a constant init value for ..."), aborting before
    # partitioning. `async2sync` folds async-reset init into sync reset logic,
    # `setundef -init -zero` constant-izes any remaining undriven/x init bits, and
    # `setattr -unset init` STRIPS the residual init ATTRIBUTE (it removes the
    # attribute string only -- it does NOT delete the wire). Do NOT use
    # `delete a:init`: that selects and DELETES every wire carrying an init
    # attribute, corrupting the design and tripping a Yosys internal assert
    # (`!it.first.has_const()` in kernel/rtlil.cc) during read_gold. `opt -fast`
    # then canonicalizes. Stripping init symmetrically yields an init-independent
    # (induction-based) equivalence proof, which is what a post-synth LEC wants
    # (gate netlists generally carry no RTL init); applying it to only one side
    # would inject a false reset-state counterexample.
    _init_norm = (
        "async2sync\n"
        "setundef -init -zero\n"
        "setattr -unset init\n"
        # SPLIT PORT NETS BEFORE opt -- otherwise a port that is a pure ALIAS of a
        # register bit (`assign scan_out = sum_frame[15];`) collapses onto ONE net,
        # and Yosys aliases it in OPPOSITE DIRECTIONS on the two sides:
        #     gold:  \sum_frame[15] -> \scan_out
        #     gate:  \scan_out      -> \sum_frame[15]
        # EQY then registers scan_out and sum_frame[15] as TWO key points for what
        # is physically one net and builds a DEGENERATE partition in which the same
        # signal is simultaneously a partition input and that partition's output
        # ("partition pi bit 44: \\scan_out <-> \\scan_out" alongside
        #  "partition po bit 0: \\scan_out <-> \\scan_out"), plus a spurious
        # dependency cycle between the aliased partitions. SAT/BMC then reports
        # "partitions not equivalent" on unreachable partition-input states -- a
        # FALSE NON-EQUIVALENCE on a design that is genuinely equivalent.
        # MEASURED on bsum16 (DX-60): without this the scan_out partition FAILS;
        # with it the same partition is "Successfully proved". Applied symmetrically
        # so it can never itself introduce an asymmetry.
        "splitnets -ports\n"
        "opt -fast\n"
    )
    _equiv_lowering = (
        "proc\n"
        "memory\n"
    )
    # Generated normalized Verilog gives temporary cell-pin wires public names.
    # They are not architectural key points, and matching equal spellings across
    # independently normalized sides can create false internal correspondence.
    # Keep ports observable while making only those temporary internals private;
    # EQY's partition verdict remains untouched and every flat output point must
    # still prove with zero unproven $equiv cells.
    _flat_match_norm = "rename -hide w:* c:*\n"
    _gate_model_guard = (
        "flatten\n"
        "select -assert-none a:blackbox\n"
    )
    if params.get("shared_blackbox_modules"):
        return _run_shared_blackbox_flat(
            params, top, ref, rev, lib_read, _read_ref,
            _shared_model_read + _read_rev, _init_norm,
            depth, _cell_model_source, inputs_ref)
    # DX-162: measure each side's OWN flop/latch count independently of the
    # equivalence proof itself, so a key-point/equivalence-point population
    # far below either side's real flop count can be caught even when the
    # proof engine reports success for that (implausibly small) population.
    ref_seq_count, ref_seq_log = _count_sequential_cells(
        _read_ref, top, "keypoint_stat_reference")
    rev_seq_count, rev_seq_log = _count_sequential_cells(
        lib_read + _shared_model_read + _read_rev, top, "keypoint_stat_revised")
    # eqy problem file: [gold]/[gate] read+prep each side; per-partition proof
    # strategies tried in order -- a fast bounded SAT strategy first, then an
    # sby-backed UNBOUNDED k-induction strategy for hard sequential key points.
    # eqy auto-partitions and maps key points across the two designs.
    #
    # ENGINE CHOICE (do not "restore" `engine abc pdr` -- it is unusable here):
    # This fallback previously specified `engine abc pdr`. That was wrong twice
    # over, and it deterministically blocked DX-60 / DX-61 for 8 identical
    # attempts each:
    #   1. the `abc` binary is NOT INSTALLED in this image (only the sby ABC
    #      *driver* `sby_engine_abc.py` ships), so the engine could never run;
    #   2. that driver crashes before emitting any verdict --
    #      `KeyError: 'asserts'` at sby_engine_abc.py:173 -- so the failure
    #      surfaced as a tool crash rather than an honest "engine unavailable".
    # The result was the worst possible shape: no counterexample, no proof, and
    # no verdict -- an unprovable gate that looked like a design problem.
    #
    # `smtbmc` is eqy's OWN default for a `use sby` strategy, and it is fully
    # installed here (yosys-smtbmc + z3 + boolector + bitwuzla + yices). eqy
    # runs it as `mode prove`, i.e. BMC plus temporal induction -- a genuine
    # UNBOUNDED proof, which is what a bounded-depth SAT pass cannot give on an
    # arithmetic partition like `bsum16.sum`. Leaving the engine unset would
    # also work (same default); it is named explicitly so the proof engine is
    # visible in the emitted lec.eqy and in the evidence.
    eqy_text = _eqy_problem_text(
        top=top, read_ref=_read_ref, lib_read=lib_read,
        shared_model_read=_shared_model_read, read_rev=_read_rev,
        init_norm=_init_norm, gate_model_guard=_gate_model_guard,
        match_block=_match_block, depth=depth)
    ep = os.path.join(_WORK_DIR, "lec.eqy")
    open(ep, "w").write(eqy_text)
    # -f overwrites the eqy workdir (named after the .eqy file: ./lec/).
    cmd = ["eqy", "-f", ep]
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    # Fold eqy workdir logfile into the captured log for full provenance.
    eqy_logfile = os.path.join(_WORK_DIR, "lec", "logfile.txt")
    if os.path.exists(eqy_logfile):
        try:
            out += "\n\n===== eqy logfile.txt =====\n" + open(eqy_logfile).read()
        except Exception:
            pass
    open(os.path.join(_OUTPUT_DIR, "eqy_lec.log"), "w").write(out)
    open(os.path.join(_OUTPUT_DIR, "lec.eqy"), "w").write(eqy_text)
    _eqy_unflattened = _unflattened_cells(out)
    if _eqy_unflattened:
        return _hierarchy_not_flattened_cde(
            top, params, _eqy_unflattened, "eqy_lec.log", inputs_ref)
    # eqy prints per-partition results and a terminal summary; it exits 0 only
    # when every partition is proven equivalent. Parse the partition tally when
    # present, and classify a genuine tool ERROR distinctly from a real (valid)
    # non-equivalence finding.
    #
    # *** PARSE WHAT EQY ACTUALLY PRINTS. *** The original regex here looked for
    # "N of M partitions proven", a string EQY DOES NOT EMIT. Measured against
    # EQY 0.68 output it never matched, so `unproven_points` and
    # `partitions_created` were recorded as NULL on EVERY attempt -- verified
    # across 7 real lec-post-synth attempts, all of which stored
    # unproven=None / partitions_created=None / progress.residual=None.
    # That is why this stage looked like it had "no measurable residual" and was
    # declared a non-iterating binary gate: the residual was not absent, it was
    # NEVER CAPTURED. EQY prints these forms instead:
    #     "Warning: Failed to prove equivalence for 4/19 partitions:"
    #     "Successfully proved equivalence of partition <name>"
    #     "Failed to prove equivalence of partition <name>"
    # Same defect family as the chip-logic-synthesis stat parser and the chip-sta
    # DRV parser: a regex that silently matches nothing yields a FALSE ABSENCE,
    # which downstream reads as "not measurable" rather than "not measured".
    proved_partitions = set(re.findall(
        r"Successfully proved equivalence of partition\s+(\S+)", out, re.I))
    failed_partitions = set(re.findall(
        r"Failed to prove equivalence of partition\s+(\S+)", out, re.I))

    equiv_pts = total_pts = unproven = None
    # Authoritative tally line, when present: "Failed ... for <unproven>/<total>".
    m = re.search(r"Failed to prove equivalence for\s+(\d+)\s*/\s*(\d+)\s+partitions",
                  out, re.I)
    if m:
        unproven = int(m.group(1))
        total_pts = int(m.group(2))
        equiv_pts = total_pts - unproven
    # Legacy/alternate phrasing kept as a fallback so an older or newer EQY that
    # does emit it is still understood.
    if unproven is None:
        m2 = re.search(r"(\d+)\s+of\s+(\d+)\s+partitions?\s+proven", out, re.I)
        if m2:
            equiv_pts = int(m2.group(1))
            total_pts = int(m2.group(2))
            unproven = total_pts - equiv_pts
    # Last resort: derive from the per-partition lines themselves.
    if unproven is None and (proved_partitions or failed_partitions):
        equiv_pts = len(proved_partitions)
        unproven = len(failed_partitions)
        total_pts = equiv_pts + unproven

    partition_match = re.search(
        r"(?:created|re-generated)\s+(\d+)\s+partitions?", out, re.I)
    partitions_created = int(partition_match.group(1)) if partition_match else None
    if partitions_created is None and total_pts is not None:
        partitions_created = total_pts
    proven_equivalent = bool(re.search(
        r"Successfully proved designs equivalent|Equivalence successfully proven|"
        r"designs are equivalent", out, re.I))
    non_equivalent = bool(re.search(
        r"Failed to prove|NOT equivalent|found a difference|"
        r"designs are not equivalent|proving.*failed", out, re.I))

    # --- WHOLE-DESIGN CONFIRMATION OF A PARTITION FAILURE -------------------
    # EQY proves each partition with that partition's INPUTS LEFT FREE. A
    # counterexample may therefore sit on a partition-input state that is
    # UNREACHABLE in the assembled design -- i.e. EQY can report "partitions not
    # equivalent" for a design that is genuinely equivalent. That is not
    # hypothetical: MEASURED on bsum16 (DX-60), EQY failed `sum` and `sum_frame`
    # with a BMC counterexample on `sum[9]` at step 1, with all 21 instantiated
    # cell types fully modelled and no black boxes -- while a flat whole-design
    # proof of the SAME two files proved all 49 equivalence points and reported
    # "Equivalence successfully proven!" in ~9s.
    #
    # A flat `equiv_make`/`equiv_simple`/`equiv_induct` proof has NO free
    # partition inputs, so it is STRICTLY STRONGER evidence than a partitioned
    # one. Running it only on the failure path keeps the happy path fast.
    #
    # THIS CANNOT LAUNDER A REAL MISMATCH: it upgrades the verdict ONLY on an
    # explicit "Equivalence successfully proven!" with zero unproven cells. A
    # flat run that fails, errors, times out, or is unparseable leaves the
    # original failing verdict exactly as it was.
    flat_confirm = None
    partition_boundary = None
    flat_unflattened = []
    if non_equivalent and not proven_equivalent:
        partition_boundary = _partition_boundary_evidence(failed_partitions)
        flat_ys = (
            f"{_read_ref}\n"
            f"prep -top {top}\n"
            # `design -copy-from gold -as gold <top>` copies ONLY the top
            # module: gold must be flattened here, exactly as gate is, or
            # every submodule instance reaches equiv_make as an opaque cell.
            "flatten\n"
            f"{_hierarchy_flattened_guard(top)}"
            f"{_equiv_lowering}"
            f"{_init_norm}"
            f"{_flat_match_norm}"
            "design -stash gold\n"
            f"{lib_read}{_shared_model_read}{_read_rev}\n"
            f"hierarchy -top {top}\n"
            f"{_gate_model_guard}"
            f"{_hierarchy_flattened_guard(top)}"
            f"{_equiv_lowering}"
            f"{_init_norm}"
            f"{_flat_match_norm}"
            "design -stash gate\n"
            f"design -copy-from gold -as gold {top}\n"
            f"design -copy-from gate -as gate {top}\n"
            "equiv_make gold gate equiv\n"
            "hierarchy -top equiv\n"
            f"equiv_simple -seq {depth}\n"
            f"equiv_induct -seq {depth}\n"
            "equiv_status\n"
        )
        fp = os.path.join(_WORK_DIR, "flat_equiv.ys")
        open(fp, "w").write(flat_ys)
        try:
            fproc = subprocess.run(["yosys", "-ql", "flat_equiv.log", fp],
                                   capture_output=True, text=True, cwd=_WORK_DIR)
            flog = ""
            flp = os.path.join(_WORK_DIR, "flat_equiv.log")
            if os.path.exists(flp):
                flog = open(flp, errors="replace").read()
            flog = (fproc.stdout or "") + "\n" + (fproc.stderr or "") + "\n" + flog
            open(os.path.join(_OUTPUT_DIR, "flat_equiv.log"), "w").write(flog)
            open(os.path.join(_OUTPUT_DIR, "flat_equiv.ys"), "w").write(flat_ys)
            flat_unflattened = _unflattened_cells(flog)
            fm = re.search(r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven",
                           flog, re.I)
            fproven = int(fm.group(1)) if fm else None
            funproven = int(fm.group(2)) if fm else None
            fok = (fproc.returncode == 0
                   and bool(re.search(r"Equivalence successfully proven", flog, re.I))
                   and funproven == 0)
            flat_confirm = {
                "ran": True,
                "method": "yosys equiv_make + equiv_simple + equiv_induct "
                          "(whole design, no partitioning, no free partition inputs)",
                "proven_cells": fproven,
                "unproven_cells": funproven,
                "returncode": fproc.returncode,
                "equivalent": bool(fok),
                "log": "flat_equiv.log",
                "why": ("EQY partitions are proven with their inputs FREE, so a "
                        "partition counterexample can lie on a state unreachable "
                        "in the assembled design. This flat proof has no free "
                        "partition inputs and is therefore strictly stronger."),
            }
            if fok:
                # The design IS equivalent; the partition failure was an artifact.
                non_equivalent = False
                proven_equivalent = True
                unproven = 0
        except Exception as e:                       # never mask the original verdict
            flat_confirm = {"ran": False, "error": str(e),
                            "note": "flat confirmation could not run; the "
                                    "partitioned EQY verdict stands unchanged"}
        if flat_unflattened:
            # The flat proof could not adjudicate because a side was never
            # flattened; the EQY partition failure is then unconfirmed and
            # must not be reported as a non-equivalence verdict.
            return _hierarchy_not_flattened_cde(
                top, params, flat_unflattened, "flat_equiv.log", inputs_ref)

    # *** THE GATING BASIS IS DECIDED IN EXACTLY ONE PLACE (DX-154). ***
    # `equiv_pts`/`total_pts`/`unproven` above are the PARTITIONED EQY tally and
    # are left untouched -- they are recorded intact (failures included) in
    # signoff.diagnostics further down even when a flat proof supersedes them.
    # `_lec_gating_basis` decides, from `flat_confirm` alone, whether the
    # gating triple moves to the flat proof -- ALWAYS all three numbers
    # together, never a numerator from one run paired with a denominator from
    # another.
    gating_equiv_pts, gating_total_pts, gating_unproven, gating_basis = (
        _lec_gating_basis(equiv_pts, total_pts, unproven, flat_confirm))
    unproven = gating_unproven

    tool_error = bool(re.search(r"^ERROR:", out, re.M)) and not (
        proven_equivalent or non_equivalent)
    if tool_error and proc.returncode != 0 and not (proven_equivalent or non_equivalent):
        return _cde(objective=f"logical equivalence of {top}", status="failed",
                    error="eqy error; see eqy_lec.log:\n" + out[-1500:],
                    pdk_binding=params.get("pdk_binding", "none"),
                    validation={"verdict": "fail"},
                    provenance={"engine": "eqy", "log": "eqy_lec.log"})
    if (proc.returncode == 0 or proven_equivalent) and not non_equivalent:
        status, verdict = "completed", "pass"
        unproven = 0
    elif non_equivalent or (proc.returncode != 0):
        status, verdict = "completed", "fail"
    else:
        status, verdict = "completed", "review"

    # DX-162: key-point-count plausibility gate. A whole-design equivalence
    # claim whose population is implausibly small relative to either side's
    # own measured flop/latch count is refused, never certified -- even when
    # the proof engine (eqy or the flat whole-design proof) itself reported
    # success for that population. This can only ever make a pass MORE
    # conservative: it never turns a real failure into a pass.
    plausibility = _key_point_plausibility(
        gating_total_pts, ref_seq_count, rev_seq_count)
    if verdict == "pass" and plausibility["checked"] and not plausibility["plausible"]:
        verdict = "fail"
        if isinstance(flat_confirm, dict):
            flat_confirm = dict(flat_confirm)
            flat_confirm["equivalent"] = False
            flat_confirm["downgraded_by_key_point_plausibility"] = True
            flat_confirm["downgrade_reason"] = plausibility["reason"]
    return _cde(
        objective=f"logical equivalence of {top} (reference vs revised)",
        status=status,
        pdk_binding=params.get("pdk_binding", "none"),
        # --- METRIC CLASSES (catalog/tools/metric_classes.py) -----------------
        # LEC's gate is `unproven_points == 0`. CLOSURE STAYS BINARY: 15-of-19
        # partitions proven is NOT "79% equivalent", it is an INCOMPLETE PROOF.
        # The count is a PROGRESS signal, never a partial pass.
        #
        # *** THE POPULATION IS NOT DESCRIPTIVE HERE -- IT IS DIAGNOSTIC. ***
        # For every other adopted stage the population is stable context. For LEC
        # it is GAMEABLE: re-partitioning changes the denominator, so 4-of-19
        # unproven followed by 2-of-4 can look like progress while proving
        # strictly less. So `total_partitions` and the partition IDENTITY SET sit
        # in diagnostics, where a reviewer compares them, and NOT in descriptive,
        # which the stall machinery treats as expected-to-hold-steady.
        #
        # *** NUMERATOR AND DENOMINATOR ALWAYS SHARE ONE BASIS (DX-154). ***
        # `unproven_points`/`equivalent_points`/`total_partitions` are the GATING
        # triple and are ALWAYS read from `gating_basis` -- either the partitioned
        # EQY tally, or (when it superseded EQY) the flat whole-design proof.
        # They are never mixed across the two runs. The superseded EQY tally, if
        # any, is retained verbatim -- failures intact -- in signoff.diagnostics.
        results={"unproven_points": {
                     "value": unproven, "unit": "count",
                     "class": "gating",
                     "basis": gating_basis,
                     "closes_at": "== 0",
                     "note": ("null means NOT ASSESSED (eqy produced no readable "
                              "partition result), never zero. Closure is BINARY: "
                              "any unproven partition leaves the gate open -- "
                              "there is no partial equivalence."),
                 },
                 "equivalent_points": {"value": gating_equiv_pts, "unit": "count",
                                       "class": "gating", "basis": gating_basis},
                 "total_partitions": {"value": gating_total_pts, "unit": "count",
                                      "class": "gating", "basis": gating_basis,
                                      "note": ("despite the field name, this is "
                                               "the COMPARED-POINTS denominator "
                                               "for whichever proof is named in "
                                               "`basis` -- flat proofs count "
                                               "equivalence points, not "
                                               "partitions")},
                 "failing_points": {"value": 0 if verdict == "pass" else None,
                                    "unit": "count"},
                 "partitions_created": {"value": partitions_created, "unit": "count"},
                 "mapping": {
                     "io_complete": verdict == "pass",
                     "registers_complete": verdict == "pass",
                     "unmapped_points": 0 if verdict == "pass" else None,
                     "basis": "EQY partition/key-point proof terminal verdict",
                 },
                 # DX-162: key-point-count plausibility, gating. A tiny
                 # population (e.g. 2 equivalent partitions on a 33-flop
                 # design) is refused here regardless of what the proof
                 # engine reported for it -- see `_key_point_plausibility`.
                 "key_point_plausibility": {
                     "value": plausibility["plausible"] if plausibility["checked"] else None,
                     "unit": "bool",
                     "class": "gating",
                     "basis": "measured_flop_latch_count_vs_key_point_population",
                     "closes_at": "== true",
                     "note": plausibility["reason"],
                     "population": plausibility.get("population"),
                     "floor": plausibility.get("floor"),
                     "reference_sequential_elements": ref_seq_count,
                     "revised_sequential_elements": rev_seq_count,
                 }},
        qor={"unproven_points": unproven,
             "equivalent_points": gating_equiv_pts,
             "total_partitions": gating_total_pts,
             "gating_basis": gating_basis},
        signoff={"verdict": verdict,
                 "key_point_mapping": _kpm_note,
                 "engine": "eqy (sat + sby/smtbmc k-induction strategies)",
                 "cell_models": _cell_model_source,
                 # Present ONLY when the bound Verilog cell model was measured
                 # unreadable by this Yosys and the run fell back to the
                 # Liberty-functional read. A reviewer must be able to see, on
                 # the envelope itself, that the gate side was modelled from a
                 # DIFFERENT source than the binding's default named.
                 "cell_model_fallback": _model_fallback,
                 # Present ONLY when the partitioned proof reported a failure and
                 # a whole-design check was run to adjudicate it. A reviewer must
                 # be able to see that a pass came from the flat proof rather
                 # than from EQY, and on what basis.
                 "whole_design_confirmation": flat_confirm,
                 # DX-162: recorded alongside whole_design_confirmation so a
                 # reviewer can see, on the SAME envelope, both what the proof
                 # engine reported AND whether the population it reported over
                 # was even plausibly big enough to be a whole-design claim.
                 "key_point_plausibility": plausibility,
                 # (B) DIAGNOSTIC -- measured, non-gating: WHICH partitions are
                 # open, so a proof strategy can be aimed without re-running.
                 # ALWAYS the raw EQY partition tally, even when the flat proof
                 # above has superseded it as the gating basis -- the disclosure
                 # of a failed sub-proof must never be deleted or suppressed.
                 "diagnostics": {
                     "class": "diagnostic",
                     "basis": "parsed_eqy_partition_summary",
                     "superseded": gating_basis != _LEC_PARTITION_BASIS,
                     "equivalent_points": equiv_pts,
                     "total_partitions": total_pts,
                     "unproven_points": (
                         (total_pts - equiv_pts)
                         if (total_pts is not None and equiv_pts is not None)
                         else None),
                     "unproved_partitions": sorted(failed_partitions),
                     "proved_partitions": sorted(proved_partitions),
                     # EQY's OWN cut structure for every failing partition,
                     # captured from its workdir before that workdir is
                     # discarded. Without it a partition counterexample can
                     # only be read by re-running the whole proof.
                     "partition_boundary": partition_boundary,
                     "population": total_pts,
                     "population_note": (
                         "the denominator is NOT stable context for this stage: "
                         "re-partitioning changes it, so a residual drop is only "
                         "real progress when the partition set is unchanged"),
                     "note": (
                         "this is the PARTITIONED eqy tally, retained verbatim "
                         "for audit -- it is NOT the gating basis when "
                         "`superseded` is true (see signoff.whole_design_"
                         "confirmation and results.*.basis for what closed the "
                         "gate). A partition failure recorded here is real "
                         "eqy output and must never be edited to make the "
                         "numbers balance."
                     ) if gating_basis != _LEC_PARTITION_BASIS else (
                         "this IS the gating basis for this run"),
                 },
                 # (C) DESCRIPTIVE -- run configuration expected to hold steady.
                 # Deliberately does NOT include the partition count (see above).
                 "descriptive": {
                     "class": "descriptive",
                     "basis": "run_configuration",
                     "engine": "eqy",
                     "cell_models": _cell_model_source,
                     "elapsed_s": round(elapsed, 2),
                     "note": ("configuration/context, not a gate and not a "
                              "progress signal"),
                 },
                 # (D) MODEL-AUTHORED -- advisory only, cross-checked, never gating.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), unproven, "unproven_points"),
                 # *** THE ANTI-GOODHART RECORD. `unproven_points` ALONE IS
                 # GAMEABLE: merging or re-grouping partitions changes the
                 # DENOMINATOR, so 4-unproven-of-19 followed by 2-unproven-of-4
                 # can look like progress while proving strictly less. This repo
                 # has already been burned by exactly that shape (a DRC gate that
                 # "closed" by narrowing its rule scope). So record the population
                 # AND the partition IDENTITY SET every attempt: a comparison
                 # across attempts is only like-for-like when the partition set is
                 # unchanged, and a reviewer can see at a glance when it is not.
                 "partition_scope": {
                     "total": total_pts,
                     "proved": sorted(proved_partitions),
                     "unproved": sorted(failed_partitions),
                     "note": "compare attempts ONLY when the partition set is "
                             "identical; a changed set means the question "
                             "changed, not that the proof improved",
                 },
                 "log": "eqy_lec.log"},
        inputs_ref=inputs_ref,
        assumptions=["eqy auto-partitions and maps key points across the two designs; "
                     "provide a [match] script for renamed key points"],
        validation={"verdict": verdict,
                    "note": (
                        "key-point-count implausible: " + plausibility["reason"]
                        if (plausibility["checked"] and not plausibility["plausible"])
                        else "non-equivalence is a hard failure" if verdict == "fail" else (
                            "proved" if verdict == "pass" else "inconclusive; inspect eqy_lec.log"))},
        provenance={
            "yosys": _yosys_version(),
            "eqy": _eqy_version(),
            "engine": "eqy",
            "container_image": params.get("container_image")
                               or os.environ.get("CHIP_TOOL_IMAGE", "unrecorded"),
            "task_id": params.get("task_id"),
            "hash_chain": {
                "prev_hash": params.get("upstream_cde_self_hash"),
                "upstream": params.get("upstream_cde"),
            },
            "runtime_s": round(elapsed, 3),
            "log": "eqy_lec.log",
        },
    )


_SCENARIOS = {
    "rtl_vs_netlist": _equiv,
    "hierarchical_rtl_vs_netlist": _hierarchical_rtl_vs_netlist,
    "netlist_vs_netlist": _equiv,
    "post_dft_mission": _post_dft_mission,
    "post_eco": _equiv,
}


def dispatch(params):
    s = params.get("scenario")
    if s not in _SCENARIOS:
        return _cde(objective="equivalence checking", status="failed",
                    error=f"unknown scenario '{s}'; supported: " + ", ".join(_SCENARIOS),
                    validation={"verdict": "fail"})
    if not shutil.which("eqy"):
        return _cde(objective="equivalence checking", status="failed",
                    error="eqy not found on PATH", validation={"verdict": "fail"})
    for k in ("reference", "revised", "top"):
        if not params.get(k):
            return _cde(objective="equivalence checking", status="failed",
                        error=f"missing required field '{k}'", validation={"verdict": "fail"})
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
