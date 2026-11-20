#!/usr/bin/env python3
"""testbench_generation_utils.py -- verification-environment scaffolding for the
chip-testbench-generation tool.

Generates a cocotb / UVM-style environment (driver, monitor, scoreboard, agent per
interface) traced to the vplan, and runs a Verilator lint/smoke check on the DUT.
Node-agnostic. Results conform to the Common Design Envelope.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import mutation
import simulator_select

TOOL = "testbench-generation"
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
        if smoke["status"] == "skipped":
            verdict = "not_assessable"; status = "failed"
        elif missing:
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
        _safe_write(os.path.join(_OUTPUT_DIR, name), line + "\n")
    except Exception as _e:
        print("[" + str(TOOL) + "] run-command capture skipped: " + str(_e), flush=True)


def _safe_write(path, content):
    """Write text after creating its parent directory.

    This protects nested CHIP_OUTPUT_DIR values and generated subpaths. The host
    bind-mount source must still be created before the container starts.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)



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
    _safe_write(path, _render_report_md(results))
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
    _safe_write(path, _render_summary_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def save_final_results(results):
    results = _finalize_envelope(results)
    path = os.path.join(_OUTPUT_DIR, "common_design_envelope.json")
    _safe_write(path, json.dumps(results, indent=2, default=str))
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


def _tool_version(command):
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "unknown"
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
        return _cp.normalize_stage(TOOL) or "testbench"
    except Exception:
        return "testbench"


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
        base.setdefault("basis", "agent_read_of_smoke_log" if base else "not_provided")
        base["class"] = "model_authored"
        return base
    return metric_classes.label_interpretation(interp, basis="agent_read_of_smoke_log")


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
         validation=None, inputs_ref=None, error=None, qor=None):
    env = {
        "tool": TOOL, "stage": _canonical_stage(),
        "status": status, "objective": objective,
        "tools_used": [
            {"name": "cocotb-scaffold", "version": "1.0.0"},
            {"name": "Verilator", "version": _tool_version(["verilator", "--version"])},
            {"name": "cocotb", "version": _tool_version(
                ["python3", "-c", "import cocotb; print(cocotb.__version__)"]
            )},
        ],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "shared_artifact",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "scaffold"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic scaffold + verilator smoke"},
    }
    if error:
        env["error"] = error
    return env


def _introspect_dut(params):
    """Read the DUT's ACTUAL ports out of the RTL with Verilator.

    The generator previously took the caller's word for the interface: a
    testbench naming `dat_valid` when the DUT declares `data_valid`, or driving a
    signal the DUT declares as an OUTPUT, generated cleanly and failed only much
    later at simulation time -- and a scaffold that never runs fails silently
    forever. Verilator elaborates the RTL and emits a JSON AST; the port
    directions come from that, not from the request.

    Returns {available: bool, ports: [...], reason: ...}. When Verilator is
    unavailable or the RTL does not elaborate, this reports `available: False`
    and the cross-check below is skipped rather than being reported as clean."""
    out = {"available": False, "ports": [], "reason": None, "top": params.get("dut_top")}
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "dut_introspect.v")
        open(p, "w").write(params["rtl"])
        files.append(p)
    files += [f for f in (params.get("rtl_files") or []) if os.path.exists(f)]
    if not files:
        out["reason"] = "no RTL supplied, so the DUT interface could not be read"
        return out
    if not shutil.which("verilator"):
        out["reason"] = "verilator unavailable; DUT ports could not be introspected"
        return out
    top = params.get("dut_top")
    objdir = os.path.join(_WORK_DIR, "introspect_obj")
    cmd = ["verilator", "--json-only", "--Mdir", objdir]
    if top:
        cmd += ["--top-module", str(top)]
    for k, v in (params.get("defines") or {}).items():
        cmd.append(f"-D{k}={v}" if v not in (None, "") else f"-D{k}")
    for d in (params.get("include_dirs") or []):
        cmd.append(f"-I{d}")
    cmd += files
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR,
                              timeout=180)
    except Exception as exc:
        out["reason"] = f"verilator introspection failed to run: {exc}"
        return out
    if proc.returncode != 0:
        out["reason"] = ("RTL did not elaborate, so its ports could not be read: "
                         + (proc.stderr or proc.stdout)[-400:])
        return out
    trees = sorted(glob.glob(os.path.join(objdir, "*.tree.json")))
    if not trees:
        out["reason"] = "verilator produced no JSON AST"
        return out
    try:
        ast = json.load(open(trees[0]))
    except Exception as exc:
        out["reason"] = f"verilator AST unreadable: {exc}"
        return out
    ports, seen = [], set()

    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "VAR":
                d = str(node.get("direction") or "").upper()
                # GPARAM/LPARAM are parameters, not ports; only INPUT/OUTPUT/
                # INOUT are interface signals.
                if d in ("INPUT", "OUTPUT", "INOUT"):
                    nm = node.get("origName") or node.get("name")
                    if nm and nm not in seen:
                        seen.add(nm)
                        ports.append({"name": nm, "direction": d.lower(),
                                      "var_type": node.get("varType"),
                                      "dtype": node.get("dtypeName")})
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for x in node:
                _walk(x)

    _walk(ast)
    out["available"] = True
    out["ports"] = ports
    out["inputs"] = [p["name"] for p in ports if p["direction"] == "input"]
    out["outputs"] = [p["name"] for p in ports if p["direction"] == "output"]
    out["note"] = ("port names and directions are read from the elaborated RTL; "
                   "bit WIDTHS are not extracted and are therefore not checked")
    return out


def _check_interfaces_against_dut(ifaces, dut):
    """Compare the requested interface signals with the DUT's real ports."""
    res = {"checked": False, "unknown_signals": [], "driving_outputs": [],
           "unused_dut_inputs": [], "reason": None}
    if not dut.get("available"):
        res["reason"] = dut.get("reason") or "DUT ports unavailable"
        return res
    real = {p["name"]: p["direction"] for p in dut["ports"]}
    requested = []
    for i in ifaces:
        for s in (i.get("signals") or []):
            nm = s.get("name") if isinstance(s, dict) else s
            if nm:
                requested.append((i.get("name"), nm,
                                  (s.get("role") if isinstance(s, dict) else None)))
    for iface, sig, role in requested:
        if sig not in real:
            res["unknown_signals"].append(
                {"interface": iface, "signal": sig,
                 "reason": "no such port on the DUT"})
        elif str(role or "").lower() in ("drive", "driver", "input") and \
                real[sig] == "output":
            res["driving_outputs"].append(
                {"interface": iface, "signal": sig,
                 "reason": "the testbench would drive a DUT OUTPUT"})
    named = {s for _, s, _ in requested}
    res["unused_dut_inputs"] = [n for n, d in real.items()
                                if d == "input" and n not in named]
    res["checked"] = True
    res["requested_signal_count"] = len(requested)
    res["dut_port_count"] = len(real)
    return res


def _emit_agent(iface, style, opts=None):
    opts = opts or {}
    name = iface["name"]
    sigs = iface.get("signals", [])
    comp = os.path.join(_OUTPUT_DIR, f"{name}_agent.py")
    # Generation options honored in the emitted scaffold.
    clock_period = opts.get("clock_period", 10)
    clock_unit = opts.get("clock_unit", "ns")
    reset_polarity = str(opts.get("reset_polarity", "active_high")).lower()
    _rst_active = "0" if reset_polarity == "active_low" else "1"
    # Which components to emit (default: full agent). Order preserved.
    want = [c.lower() for c in opts.get("components", ["driver", "monitor", "scoreboard"])]
    _valid = ["driver", "monitor", "scoreboard"]
    want = [c for c in want if c in _valid] or _valid
    seq_count = int(opts.get("sequence_count", 1))
    items_per_seq = int(opts.get("items_per_sequence", 100))

    parts = [f'"""{style} agent for interface {name} (generated)."""',
             f'# clock: {clock_period} {clock_unit}; reset: {reset_polarity}',
             f'CLOCK_PERIOD = {clock_period}',
             f'CLOCK_UNIT = "{clock_unit}"',
             f'RESET_ACTIVE_LEVEL = {_rst_active}', '']
    cap = name.capitalize()
    if "driver" in want:
        parts += [f'class {cap}Driver:',
                  '    def __init__(self, dut): self.dut = dut',
                  f'    async def drive(self, txn): pass  # drive {sigs}', '']
    if "monitor" in want:
        parts += [f'class {cap}Monitor:',
                  '    def __init__(self, dut): self.dut = dut',
                  f'    async def sample(self): pass  # sample {sigs}', '']
    if "scoreboard" in want:
        # A scoreboard is only a CHECKER if something tells it what to expect.
        # The previous emission was `self.expected = []` plus
        # `check(actual) -> actual in self.expected`, which returns False for
        # every input: the generated environment could not pass. The tempting
        # "fix" -- returning True -- is far worse, because it converts an
        # obviously-unfinished environment into one that appears to verify and
        # silently blesses every DUT output.
        #
        # So: the scoreboard REFUSES to render a verdict until a reference model
        # is installed. An unfinished environment must be loud, not permissive.
        parts += [f'class {cap}Scoreboard:',
                  '    """Compares DUT output against a reference model.',
                  '',
                  '    NOT SELF-CHECKING UNTIL `reference_model` IS SET. Until',
                  '    then check() raises: an unfinished checker must fail',
                  '    loudly rather than return a verdict it cannot justify.',
                  '    Returning True here would make an empty testbench look',
                  '    like a passing one.',
                  '    """',
                  '',
                  '    def __init__(self, reference_model=None):',
                  '        # reference_model: callable(stimulus) -> expected output',
                  '        self.reference_model = reference_model',
                  '        self.expected = []',
                  '        self.matches = 0',
                  '        self.mismatches = []',
                  '',
                  '    @property',
                  '    def self_checking(self):',
                  '        return self.reference_model is not None',
                  '',
                  '    def expect(self, stimulus):',
                  '        """Record the expected response for a driven stimulus."""',
                  '        if self.reference_model is None:',
                  '            raise NotImplementedError(',
                  f'                "{cap}Scoreboard has no reference_model: it '
                  'cannot know what to expect. "',
                  '                "Install one before running, or this '
                  'environment checks nothing.")',
                  '        exp = self.reference_model(stimulus)',
                  '        self.expected.append(exp)',
                  '        return exp',
                  '',
                  '    def check(self, actual):',
                  '        if self.reference_model is None:',
                  '            raise NotImplementedError(',
                  f'                "{cap}Scoreboard has no reference_model, so '
                  'this result is UNCHECKED. "',
                  '                "Refusing to report a pass or a fail.")',
                  '        if not self.expected:',
                  '            raise AssertionError(',
                  '                "check() called with nothing expected: '
                  'expect() must be called for each driven transaction.")',
                  '        exp = self.expected.pop(0)',
                  '        if actual == exp:',
                  '            self.matches += 1',
                  '            return True',
                  '        self.mismatches.append({"expected": exp, "actual": actual})',
                  '        return False',
                  '',
                  '    def report(self):',
                  '        """Final status. Zero comparisons is NOT a pass."""',
                  '        if not self.self_checking:',
                  '            return {"status": "not_checking",',
                  '                    "reason": "no reference model installed"}',
                  '        if self.mismatches:',
                  '            return {"status": "fail", "matches": self.matches,',
                  '                    "mismatches": self.mismatches}',
                  '        # Unconsumed expectations are DROPPED TRANSACTIONS.',
                  '        # Checked before the no-comparison case because it is',
                  '        # the more specific diagnosis of the same symptom.',
                  '        if self.expected:',
                  '            return {"status": "fail",',
                  '                    "reason": "%d expected response(s) never '
                  'arrived" % len(self.expected)}',
                  '        if self.matches == 0:',
                  '            return {"status": "no_comparisons",',
                  '                    "reason": "the scoreboard never compared '
                  'anything; an unrun check is not a pass"}',
                  '        return {"status": "pass", "matches": self.matches}',
                  '']
    # For a UVM-style env, emit a sequence stub honoring the requested counts.
    if style in ("uvm", "pyuvm"):
        parts += [f'class {cap}Sequence:',
                  f'    SEQUENCE_COUNT = {seq_count}',
                  f'    ITEMS_PER_SEQUENCE = {items_per_seq}',
                  '    async def body(self): pass', '']
    _safe_write(comp, "\n".join(parts) + "\n")
    return {"interface": name, "components": want,
            "file": f"{name}_agent.py", "vplan_item": iface.get("vplan_item")}


def _smoke(params):
    files = []
    if params.get("rtl"):
        p = os.path.join(_WORK_DIR, "dut.v")
        open(p, "w").write(params["rtl"])
        files.append(p)
    files += [f for f in params.get("rtl_files", []) if os.path.exists(f)]
    if not files or not shutil.which("verilator"):
        return {"status": "skipped", "reason": "no RTL or verilator unavailable"}
    # Lint rigor + resolution controls. -Wall promotes style/lint warnings (off by
    # default to preserve prior lenient behavior); -Wno-<rule> waives specific
    # ones; -D/-I let lint resolve parameterized / multi-file RTL.
    # Warnings remain in smoke.log but do not become fatal merely because the
    # generated/lowered RTL emits many instances of one warning class. Syntax,
    # elaboration, and unsupported constructs still return non-zero.
    lint_args = ["-Wno-fatal"]
    if str(params.get("lint_all_warnings", "")).lower() in ("1", "true", "yes"):
        lint_args.append("-Wall")
    for rule in (params.get("lint_suppress_rules") or []):
        lint_args.append(f"-Wno-{rule}")
    for k, v in (params.get("defines") or {}).items():
        lint_args.append(f"-D{k}={v}" if v not in (None, "") else f"-D{k}")
    for d in (params.get("include_dirs") or []):
        lint_args.append(f"-I{d}")
    cmd = (["verilator", "--lint-only", "--top-module", params.get("dut_top", "top")]
           + lint_args + files)
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    _safe_write(os.path.join(_OUTPUT_DIR, "smoke.log"), proc.stdout + "\n" + proc.stderr)
    return {"status": "pass" if proc.returncode == 0 else "fail",
            "lint_flags": lint_args, "log": "smoke.log"}


def _generate(params):
    ifaces = params.get("interfaces", [])
    if not ifaces:
        return _cde(objective="generate environment", status="failed",
                    error="no interfaces supplied", validation={"verdict": "fail"})
    style = params.get("style", "cocotb")
    # Generation options honored by the emitted scaffold (all optional).
    opts = {
        "clock_period": params.get("clock_period", 10),
        "clock_unit": params.get("clock_unit", "ns"),
        "reset_polarity": params.get("reset_polarity", "active_high"),
        "components": params.get("components", ["driver", "monitor", "scoreboard"]),
        "sequence_count": params.get("sequence_count", 1),
        "items_per_sequence": params.get("items_per_sequence", 100),
    }
    comps = [_emit_agent(i, style, opts) for i in ifaces]
    missing = [c["interface"] for c in comps if not c["vplan_item"]]
    # Read the DUT's real ports and check the requested interface against them.
    dut = _introspect_dut(params)
    iface_check = _check_interfaces_against_dut(ifaces, dut)
    # A generated scoreboard is not a checker until a reference model exists.
    # The generator cannot supply one -- it does not know the intended function --
    # so it reports whether the caller declared one and refuses to call the
    # environment self-checking otherwise.
    has_scoreboard = any("scoreboard" in c["components"] for c in comps)
    reference_model = params.get("reference_model")
    self_checking = bool(has_scoreboard and reference_model)
    smoke = _smoke(params)
    verdict = "pass"
    status = "completed"
    if missing:
        verdict = "fail"; status = "failed"
    elif smoke["status"] == "fail":
        verdict = "fail"; status = "failed"
    elif iface_check["unknown_signals"] or iface_check["driving_outputs"]:
        # The testbench references signals the DUT does not have, or drives a
        # DUT output. Either is a guaranteed simulation-time failure.
        verdict = "fail"; status = "failed"
    elif not self_checking:
        # It compiles and traces to the vplan, but nothing decides pass/fail.
        # This is the honest state of a scaffold: usable, not yet verifying.
        verdict = "review"
    elif not iface_check["checked"]:
        verdict = "review"
    return _cde(
        objective=f"generate {style} environment for {params.get('dut_top')}",
        status=status,
        # (A) GATING -- a scaffold is only usable if it COMPILES and every
        # component traces to a vplan item. `agents` is the population and is
        # deliberately NOT gating: it is higher-is-better, so declaring it would
        # make generating more components read as further from closure.
        results={"agents": {
                     "value": len(comps), "unit": "count",
                     "class": "diagnostic", "basis": "deterministic_scaffold",
                     "note": ("POPULATION and higher-is-better; never a residual.")},
                 "smoke_failures": {
                     "value": 0 if smoke.get("status") != "fail" else 1,
                     "unit": "count",
                     "class": "gating", "basis": "verilator_smoke_compile",
                     "closes_at": "== 0",
                     "note": ("A scaffold that does not compile is not an "
                              "environment. This is a COMPILE floor, NOT evidence "
                              "that the testbench checks anything -- a wiring-only "
                              "scaffold with no reference model can smoke clean "
                              "and still verify nothing.")},
                 "missing_vplan_linkage": {
                     "value": len(missing), "unit": "count",
                     "class": "gating", "basis": "deterministic_scaffold",
                     "closes_at": "== 0",
                     "note": ("An unlinked component cannot be traced to a "
                              "verification goal, so it cannot count toward one.")},
                 "interface_mismatches": {
                     "value": (len(iface_check["unknown_signals"])
                               + len(iface_check["driving_outputs"])),
                     "unit": "count",
                     "class": "gating", "basis": "verilator_dut_introspection",
                     "closes_at": "== 0",
                     "note": ("Signals the DUT does not declare, or DUT OUTPUTS "
                              "the testbench would drive. Read from the "
                              "elaborated RTL, not from the request.")},
                 "self_checking": {
                     "value": self_checking, "unit": "bool",
                     "class": "gating", "basis": "deterministic_scaffold",
                     "closes_at": "== True",
                     "note": ("A scoreboard with no reference model cannot "
                              "decide pass/fail; the generated check() RAISES "
                              "rather than returning a verdict it cannot "
                              "justify.")}},
        signoff={"generated": comps, "smoke_test": smoke,
                 "generation_options": opts,
                 "missing_vplan_linkage": missing,
                 "dut_introspection": dut,
                 "interface_check": iface_check,
                 "self_checking": self_checking,
                 "reference_model_supplied": bool(reference_model),
                 # (B) DIAGNOSTIC -- the repair surface: WHICH components are
                 # unlinked and what the smoke run actually reported.
                 "diagnostics": {
                     "class": "diagnostic", "basis": "deterministic_scaffold",
                     "unlinked_components": missing,
                     "component_count": len(comps),
                     "smoke_status": smoke.get("status"),
                     "smoke_detail": smoke,
                     "population_note": ("component_count is the denominator. "
                                         "Diagnostic, not descriptive: dropping a "
                                         "component shrinks it and clears its "
                                         "linkage defect without the environment "
                                         "covering any more.")},
                 # (C) DESCRIPTIVE -- configuration, expected to hold steady.
                 "descriptive": {
                     "class": "descriptive", "basis": "run_configuration",
                     "dut_top": params.get("dut_top"), "style": style,
                     "generation_options": opts,
                     "engine": "deterministic scaffold + verilator smoke"},
                 # (D) MODEL-AUTHORED -- advisory only, never closes a gate.
                 "interpretation": _labelled_interpretation(
                     params.get("interpretation")),
                 "interpretation_crosscheck": _crosscheck_interpretation(
                     params.get("interpretation"), len(missing),
                     "missing_vplan_linkage")},
        inputs_ref={"dut_top": params.get("dut_top")},
        assumptions=["scaffold provides component skeletons; fill in protocol logic",
                     "DUT port names and DIRECTIONS are read from the elaborated "
                     "RTL via Verilator; bit widths are NOT extracted, so a "
                     "width mismatch is not detected here",
                     "the environment is self-checking only when a reference "
                     "model is supplied; without one the scoreboard raises "
                     "instead of returning a verdict"],
        validation={"verdict": verdict,
                    "note": (
                        f"unlinked components: {missing}" if missing
                        else ("smoke compile failed" if smoke.get("status") == "fail"
                        else (f"interface does not match the DUT: "
                              f"{iface_check['unknown_signals']}"
                              f"{iface_check['driving_outputs']}"
                              if (iface_check["unknown_signals"]
                                  or iface_check["driving_outputs"])
                        else ("scaffold compiles and traces to the vplan, but NO "
                              "REFERENCE MODEL was supplied: the scoreboard "
                              "cannot decide pass/fail, so this environment "
                              "verifies nothing yet" if not self_checking
                        else ("DUT ports could not be introspected ("
                              + str(iface_check.get("reason"))
                              + "), so the interface was not verified against "
                                "the RTL" if not iface_check["checked"]
                        else "environment generated, interface matches the DUT, "
                             "and a reference model is installed")))))},
    )


def _tb_non_vacuity(params):
    """Prove the testbench CAN FAIL by breaking the design on purpose.

    A passing testbench is evidence only if it would have failed on a broken
    design. Nothing else in this catalog asks that question: the coverage
    agents measure how much of the RTL was exercised, never whether the
    checker would notice a wrong answer. A scoreboard whose compare is
    commented out reports 100% pass and full coverage forever.

    Protocol:
      1. POSITIVE CONTROL -- run the testbench on the UNMODIFIED RTL. It must
         pass. If it does not, nothing downstream is interpretable (a mutant
         "failing" would prove nothing when the original fails too), so the run
         is not_assessable rather than a result.
      2. For each mutant: run the same testbench, unmodified, on the mutated
         RTL. A FAILING run means the testbench detected the defect (KILLED).
      3. Score = killed / assessable.

    THE STALE-BUILD TRAP (measured, and it silently zeroed the score).
    cocotb's Makefile builds sim_build/sim.vvp from $(VERILOG_SOURCES) and make
    compares MTIMES. Reusing one work tree means that after the control run
    sim.vvp is NEWER than every mutant file, so make declares it up to date and
    RE-RUNS THE ORIGINAL BINARY. Measured on the real bsum16 testbench:

        shared work tree : mutant -> COMPILED=0  MISMATCH=0     PASS=8  "survived"
        pristine tree    : mutant -> COMPILED=1  MISMATCH=1473  FAIL=1  KILLED

    The same mutant, opposite verdicts. Every run therefore gets a PRISTINE
    work tree, and -- because a fresh tree is a precaution, not a proof -- each
    run is additionally required to show evidence that a COMPILER ACTUALLY RAN.
    A run with no compile evidence is recorded as `not_assessable`, NEVER as
    `survived`: reporting a stale binary as a surviving mutant would accuse a
    healthy testbench of being vacuous.

    EQUIVALENT MUTANTS. A surviving mutant is not proof of a testbench defect --
    it may be semantically equivalent to the original (mutating unreachable
    logic). Survivors are reported for triage. The claim that IS defensible is
    the converse: a testbench that kills NOTHING is not checking anything.
    """
    rtl = params.get("rtl_file")
    tb_dir = params.get("tb_dir")
    if not rtl or not os.path.isfile(str(rtl)):
        return _cde(objective="testbench non-vacuity", status="failed",
                    error=f"rtl_file not found: {rtl}",
                    validation={"verdict": "fail"})
    if not tb_dir or not os.path.isdir(str(tb_dir)):
        return _cde(objective="testbench non-vacuity", status="failed",
                    error=f"tb_dir not found: {tb_dir}",
                    validation={"verdict": "fail"})
    limit = int(params.get("mutants", 6))
    # A simulator that cannot PARSE the DUT fails every mutant identically, which
    # is indistinguishable from killing them unless the control run is inspected.
    # Probe before assuming, and keep the choice in the record.
    sim_command = params.get("sim_command")
    sim_choice = None
    if not sim_command:
        sim_choice = simulator_select.select(
            [rtl], top=params.get("dut_top") or params.get("top"))
        sim_command = "make SIM=%s" % sim_choice["selected"]
    rtl_arg = params.get("rtl_arg", "RTL={rtl}")
    timeout = int(params.get("sim_timeout_s", 900))

    src = open(rtl, encoding="utf-8", errors="replace").read()
    muts = mutation.generate(src, limit=limit,
                             seed=int(params.get("mutation_seed", 0)))
    if not muts:
        return _cde(objective="testbench non-vacuity", status="failed",
                    error=("no mutation sites found in %s -- the testbench "
                           "cannot be proven non-vacuous against RTL that "
                           "offers nothing to break." % os.path.basename(rtl)),
                    validation={"verdict": "fail"})

    root = os.path.join(_WORK_DIR, "nonvacuity")
    shutil.rmtree(root, ignore_errors=True)
    rtl_dir = os.path.join(root, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    base = os.path.basename(rtl)
    shutil.copy(rtl, os.path.join(rtl_dir, base))
    for m in muts:
        with open(os.path.join(rtl_dir, "mutant_%d.v" % m["index"]), "w",
                  encoding="utf-8") as fh:
            fh.write(m["source"])

    def _one(rtl_name, tag):
        """Run the testbench once, in its own pristine copy of tb_dir."""
        work = os.path.join(root, "work_%s" % tag)
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(tb_dir, work)
        cmd = sim_command + " " + rtl_arg.format(
            rtl=os.path.join(rtl_dir, rtl_name))
        try:
            proc = subprocess.run(cmd, shell=True, cwd=work, timeout=timeout,
                                  capture_output=True, text=True)
            rc, out = proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            return {"tag": tag, "rc": None, "timed_out": True,
                    "compiled": False, "log_tail": "timed out"}
        _safe_write(os.path.join(_OUTPUT_DIR, "nonvacuity_%s.log" % tag), out)
        # Evidence that a COMPILER RAN on THIS invocation. Without it the run
        # may have replayed a previously built binary and proves nothing.
        compiled = bool(re.search(r"iverilog|verilator|Compiling|sim_build/sim",
                                  out))
        return {"tag": tag, "rc": rc, "timed_out": False, "compiled": compiled,
                "log_tail": out[-400:]}

    control = _one(base, "control")
    if control["rc"] != 0:
        return _cde(
            objective="testbench non-vacuity", status="failed",
            error=("POSITIVE CONTROL FAILED: the testbench does not pass on "
                   "the UNMODIFIED RTL (rc=%s). Mutation scoring is "
                   "meaningless until it does -- a mutant that 'fails' proves "
                   "nothing when the original fails too. Fix the testbench or "
                   "the run configuration first." % control["rc"]),
            validation={"verdict": "not_assessable"},
            signoff={"positive_control": control})
    if not control["compiled"]:
        return _cde(
            objective="testbench non-vacuity", status="failed",
            error=("POSITIVE CONTROL produced no compiler evidence, so the "
                   "simulation may have replayed a stale binary. Every "
                   "mutant verdict would be untrustworthy. Check that "
                   "`sim_command` really builds (%s)." % sim_command),
            validation={"verdict": "not_assessable"},
            signoff={"positive_control": control})

    killed, survived, unassessable = [], [], []
    for m in muts:
        r = _one("mutant_%d.v" % m["index"], "mutant_%d" % m["index"])
        rec = {"index": m["index"], "mutation": m["description"],
               "line": m["line"], "kind": m["kind"],
               "rc": r["rc"], "compiled": r["compiled"],
               "timed_out": r["timed_out"]}
        if r["timed_out"] or not r["compiled"]:
            rec["reason"] = ("no compiler evidence -- possible stale build"
                             if not r["timed_out"] else "simulation timed out")
            unassessable.append(rec)
        elif r["rc"] != 0:
            killed.append(rec)
        else:
            survived.append(rec)

    assessable = len(killed) + len(survived)
    score = round(100.0 * len(killed) / assessable, 2) if assessable else None
    vacuous = assessable > 0 and not killed

    if vacuous:
        verdict, note = "fail", (
            "TESTBENCH IS VACUOUS: %d assessable mutant(s) were injected into "
            "%s and the testbench passed on EVERY ONE. It reports success "
            "regardless of whether the design is correct, so its previous "
            "passes are not evidence." % (assessable, base))
    elif assessable == 0:
        verdict, note = "not_assessable", (
            "no mutant produced a trustworthy result (%d unassessable); "
            "non-vacuity was NOT demonstrated." % len(unassessable))
    else:
        verdict = "pass"
        note = ("testbench is non-vacuous: it detected %d of %d assessable "
                "injected defects (%.2f%%)." % (len(killed), assessable, score))
        if survived:
            note += (" %d mutant(s) survived -- each is either a genuine "
                     "detection gap or a semantically equivalent mutant, and "
                     "needs triage; survival alone does not prove a defect."
                     % len(survived))

    return _cde(
        objective="testbench non-vacuity (mutation-based)",
        status="completed",
        results={"mutation_score_pct": {"value": score, "unit": "percent"},
                 "mutants_killed": {"value": len(killed), "unit": "count"},
                 "mutants_survived": {"value": len(survived), "unit": "count"},
                 "testbench_vacuous": {
                     "value": vacuous if assessable else None, "unit": "bool",
                     "class": "gating", "basis": "executed_mutation_controls",
                     "closes_at": "== false"},
                 "mutants_unassessable": {
                     "value": len(unassessable), "unit": "count",
                     "class": "gating", "basis": "executed_mutation_controls",
                     "closes_at": "== 0"}},
        qor={"mutation_score_pct": score, "mutants_killed": len(killed),
             "mutants_survived": len(survived),
             "mutants_unassessable": len(unassessable),
             "testbench_vacuous": vacuous},
        signoff={"positive_control": control, "killed": killed,
                 "survived": survived, "unassessable": unassessable,
                 "note": note,
                 "simulator_selection": sim_choice,
                 "equivalent_mutant_caveat": (
                     "a surviving mutant may be semantically equivalent to the "
                     "original; survival is a triage item, not a proven gap")},
        inputs_ref={"rtl_file": rtl, "tb_dir": tb_dir},
        validation={"verdict": verdict, "note": note})


ATTEMPT_ROOT_STAGE = "simulation"


def _read_evidence_json(path, name):
    if not path or not os.path.isfile(str(path)):
        raise ValueError("%s not found: %s" % (name, path))
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ValueError("%s is not valid JSON: %s" % (name, exc))
    if not isinstance(data, dict):
        raise ValueError("%s must contain a JSON object" % name)
    return data


def _metric_value(block, key):
    value = block.get(key) if isinstance(block, dict) else None
    if isinstance(value, dict):
        value = value.get("value")
    return value


def _metric_count(block, key, name):
    value = _metric_value(block, key)
    if isinstance(value, bool):
        raise ValueError("%s.%s is boolean, not a count" % (name, key))
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s.%s is missing or not an integer" % (name, key))
    if value < 0:
        raise ValueError("%s.%s must be non-negative" % (name, key))
    return value


def _junit_summary(path, name):
    if not path or not os.path.isfile(str(path)):
        raise ValueError("%s not found: %s" % (name, path))
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("%s is not valid JUnit XML: %s" % (name, exc))
    cases = root.findall(".//testcase")
    if not cases:
        raise ValueError("%s records zero executed testcases" % name)
    return {
        "tests": len(cases),
        "failures": sum(1 for case in cases if case.find("failure") is not None),
        "errors": sum(1 for case in cases if case.find("error") is not None),
        "skipped": sum(1 for case in cases if case.find("skipped") is not None),
        "testcases": sorted(str(case.get("name") or "") for case in cases),
    }


def _regression_summary(path):
    if not path:
        return None
    if not os.path.isfile(str(path)):
        raise ValueError("regression_log not found: %s" % path)
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    matches = re.findall(
        r"RANDOM_REGRESSION_SUMMARY\s+frames=(\d+)\s+"
        r"(?:bytes|comparisons)=(\d+)\s+mismatches=(\d+)", text)
    if not matches:
        raise ValueError(
            "regression_log has no RANDOM_REGRESSION_SUMMARY marker")
    frames, comparisons, mismatches = (int(value) for value in matches[-1])
    return {"frames": frames, "comparisons": comparisons,
            "mismatches": mismatches}


def _evidence_ref(params, key, path):
    refs = params.get("evidence_refs")
    ref = refs.get(key) if isinstance(refs, dict) else None
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("evidence_refs.%s is required" % key)
    ref = ref.strip().replace("\\", "/")
    if ref.startswith("/") or ".." in ref.split("/"):
        raise ValueError(
            "evidence_refs.%s must be a workspace-relative path" % key)
    identity = _hash_input_file(path)
    if not identity:
        raise ValueError("could not hash %s: %s" % (key, path))
    return {"path": ref, "sha256": identity["sha256"],
            "bytes": identity["bytes"]}


def _result_metric(value, unit, basis, closes_at, metric_class="gating"):
    return {"value": value, "unit": unit, "class": metric_class,
            "basis": basis, "closes_at": closes_at}


def _attempt_root_failure(message):
    env = _cde(
        objective="finalize authoritative testbench-generation attempt",
        status="failed",
        results={
            "failures": _result_metric(1, "count", "finalizer", "== 0"),
            "failing_tests": _result_metric(
                1, "count", "finalizer", "== 0"),
            "elaboration_errors": _result_metric(
                1, "count", "finalizer", "== 0"),
            "analyze_errors": _result_metric(
                1, "count", "finalizer", "== 0"),
            "sim_passed": _result_metric(
                False, "bool", "finalizer", "== True"),
            "tests": _result_metric(
                0, "count", "finalizer", ">= 1", "diagnostic"),
        },
        validation={"verdict": "fail", "note": message},
        error=message)
    env["stage"] = ATTEMPT_ROOT_STAGE
    env["verdict"] = "fail"
    return env


def _finalize_attempt(params):
    """Compose the authoritative attempt-root CDE from native evidence.

    Native generation and mutation CDEs describe sub-operations and therefore
    carry ``stage=testbench``. The campaign role is different: its canonical
    attempt directory is ``simulation`` and its progress model is ``funcverif``.
    This boundary opens the evidence itself and derives that role's measured
    fields; callers never hand-author or assert the aggregate counts.
    """
    try:
        generation_path = params.get("generation_cde")
        junit_path = params.get("junit_xml")
        rerun_path = params.get("junit_rerun_xml")
        nonvacuity_path = params.get("nonvacuity_cde")
        regression_path = params.get("regression_log")

        generation = _read_evidence_json(generation_path, "generation_cde")
        nonvacuity = _read_evidence_json(
            nonvacuity_path, "nonvacuity_cde")
        junit = _junit_summary(junit_path, "junit_xml")
        rerun = _junit_summary(rerun_path, "junit_rerun_xml")
        regression = _regression_summary(regression_path)

        if generation.get("status") != "completed" or \
                (generation.get("validation") or {}).get("verdict") != "pass":
            raise ValueError("generation_cde is not a completed pass")
        generation_results = generation.get("results") or {}
        smoke_failures = _metric_count(
            generation_results, "smoke_failures", "generation_cde.results")
        missing_vplan = _metric_count(
            generation_results, "missing_vplan_linkage",
            "generation_cde.results")
        interface_mismatches = _metric_count(
            generation_results, "interface_mismatches",
            "generation_cde.results")
        if _metric_value(generation_results, "self_checking") is not True:
            raise ValueError("generation_cde does not prove a self-checking environment")
        if smoke_failures or missing_vplan or interface_mismatches:
            raise ValueError(
                "generation gate is open (smoke=%d, vplan=%d, interface=%d)"
                % (smoke_failures, missing_vplan, interface_mismatches))

        if nonvacuity.get("status") != "completed" or \
                (nonvacuity.get("validation") or {}).get("verdict") != "pass":
            raise ValueError("nonvacuity_cde is not a completed pass")
        nonvacuity_results = nonvacuity.get("results") or {}
        nonvacuity_qor = nonvacuity.get("qor_metrics") or {}
        mutants_killed = _metric_count(
            nonvacuity_results, "mutants_killed", "nonvacuity_cde.results")
        mutants_survived = _metric_count(
            nonvacuity_results, "mutants_survived", "nonvacuity_cde.results")
        mutants_unassessable = _metric_count(
            nonvacuity_qor, "mutants_unassessable",
            "nonvacuity_cde.qor_metrics")
        if mutants_killed < 1 or mutants_unassessable:
            raise ValueError(
                "non-vacuity is not proven (killed=%d, unassessable=%d)"
                % (mutants_killed, mutants_unassessable))

        if junit["testcases"] != rerun["testcases"]:
            raise ValueError("clean rerun did not execute the identical testcase set")
        test_failures = (junit["failures"] + junit["errors"]
                         + junit["skipped"])
        rerun_failures = (rerun["failures"] + rerun["errors"]
                          + rerun["skipped"])
        if test_failures or rerun_failures:
            raise ValueError(
                "runtime suite is not clean (initial=%d, rerun=%d)"
                % (test_failures, rerun_failures))
        if regression and regression["mismatches"]:
            raise ValueError(
                "random regression reports %d mismatch(es)"
                % regression["mismatches"])

        evidence = {
            "generation_cde": _evidence_ref(
                params, "generation_cde", generation_path),
            "junit_xml": _evidence_ref(params, "junit_xml", junit_path),
            "junit_rerun_xml": _evidence_ref(
                params, "junit_rerun_xml", rerun_path),
            "nonvacuity_cde": _evidence_ref(
                params, "nonvacuity_cde", nonvacuity_path),
        }
        if regression_path:
            evidence["regression_log"] = _evidence_ref(
                params, "regression_log", regression_path)
        input_paths = {
            key: record["path"] for key, record in evidence.items()
        }

        basis = "tool-opened JUnit XML and native CDE evidence"
        results = {
            "failures": _result_metric(
                test_failures, "count", basis, "== 0"),
            "failing_tests": _result_metric(
                test_failures, "count", basis, "== 0"),
            "elaboration_errors": _result_metric(
                smoke_failures, "count", basis, "== 0"),
            "analyze_errors": _result_metric(
                smoke_failures, "count", basis, "== 0"),
            "sim_passed": _result_metric(
                True, "bool", basis, "== True"),
            "tests": _result_metric(
                junit["tests"], "count", basis, ">= 1", "diagnostic"),
            "tests_run": _result_metric(
                junit["tests"], "count", basis, ">= 1", "diagnostic"),
            "directed_tests_completed": _result_metric(
                junit["tests"], "count", basis, ">= 1", "diagnostic"),
            "rerun_failures": _result_metric(
                rerun_failures, "count", basis, "== 0"),
            "missing_vplan_linkage": _result_metric(
                missing_vplan, "count", basis, "== 0"),
            "interface_mismatches": _result_metric(
                interface_mismatches, "count", basis, "== 0"),
            "environment_self_checking": _result_metric(
                True, "bool", basis, "== True"),
            "mutants_killed": _result_metric(
                mutants_killed, "count", basis, ">= 1"),
            "mutants_survived": _result_metric(
                mutants_survived, "count", basis, ">= 0", "diagnostic"),
            "mutants_unassessable": _result_metric(
                mutants_unassessable, "count", basis, "== 0"),
        }
        if regression:
            results.update({
                "mismatches": _result_metric(
                    regression["mismatches"], "count", basis, "== 0"),
                "scoreboard_mismatches": _result_metric(
                    regression["mismatches"], "count", basis, "== 0"),
                "random_regression_frames": _result_metric(
                    regression["frames"], "frames", basis, ">= 1",
                    "diagnostic"),
                "executed_comparisons": _result_metric(
                    regression["comparisons"], "comparisons", basis, ">= 1",
                    "diagnostic"),
            })
        else:
            results["executed_comparisons"] = _result_metric(
                junit["tests"], "tests", basis, ">= 1", "diagnostic")

        env = _cde(
            objective=(params.get("objective") or
                       "finalize authoritative testbench-generation attempt"),
            status="completed",
            results=results,
            signoff={
                "evidence_files": evidence,
                "runtime_tests": junit,
                "clean_rerun": rerun,
                "random_regression": regression,
                "nonvacuity": {
                    "mutants_killed": mutants_killed,
                    "mutants_survived": mutants_survived,
                    "mutants_unassessable": mutants_unassessable,
                },
            },
            inputs_ref=input_paths,
            validation={
                "verdict": "pass",
                "note": (
                    "%d/%d runtime tests passed before and after mutation; "
                    "%d mutant(s) killed; canonical simulation evidence bound"
                    % (junit["tests"], rerun["tests"], mutants_killed)),
            })
        env["stage"] = ATTEMPT_ROOT_STAGE
        env["verdict"] = "pass"
        env["vplan"] = params.get("vplan") or generation.get("vplan")
        env["provenance"]["evidence_hashes"] = evidence

        import cde_progress as _cde_progress
        progress = _cde_progress.compute_progress(env, ATTEMPT_ROOT_STAGE)
        required_families = {"test_failures", "elab_errors"}
        if not required_families.issubset(set(progress.get("families") or {})):
            raise ValueError(
                "canonical funcverif families did not bind: %s"
                % sorted((progress.get("families") or {}).keys()))
        if progress.get("stage_key") != "funcverif" or \
                progress.get("stage_key_source") == "tool_fallback" or \
                progress.get("alignment") != "ok" or \
                not progress.get("gate_closed"):
            raise ValueError("canonical simulation progress did not close")
        env["progress"] = progress
        return env
    except Exception as exc:
        return _attempt_root_failure(str(exc))


def dispatch(params):
    s = params.get("scenario")
    if s in ("generate_env", "add_component"):
        return _generate(params)
    if s == "smoke_test":
        smoke = _smoke(params)
        verdict = {"pass": "pass", "fail": "fail"}.get(
            smoke.get("status"), "not_assessable")
        return _cde(objective="smoke test",
                    status="completed" if verdict == "pass" else "failed",
                    signoff={"smoke_test": smoke},
                    validation={"verdict": verdict})
    if s in ("tb_non_vacuity", "mutation_check", "negative_control"):
        return _tb_non_vacuity(params)
    if s == "finalize_attempt":
        return _finalize_attempt(params)
    return _cde(objective="testbench generation", status="failed",
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


# Legacy compatibility helpers retained during DX-237 image/source union.
def _looks_workspace_absolute(value):
    """True when *value* is NOT a workspace-relative (repo-relative) path.

    `evidence_refs` values are committed into the CDE for humans/tools to
    re-open the cited evidence from the repo root. A container-mount path
    (`/inputs/...`, `/output/...`) resolves to nothing outside this run's
    container and silently breaks every future reader -- reject it instead.
    """
    if not isinstance(value, str) or not value:
        return True
    if value.startswith("/") or value.startswith("\\"):
        return True
    if len(value) > 1 and value[1] == ":":  # e.g. "C:\..."
        return True
    return False

def _metric(value, unit, klass, closes_at,
            basis="tool-opened JUnit XML and native CDE evidence"):
    return {"value": value, "unit": unit, "class": klass, "basis": basis,
            "closes_at": closes_at}

def _mval(results_dict, key, default=None):
    v = (results_dict or {}).get(key)
    if isinstance(v, dict):
        return v.get("value", default)
    return default if v is None else v

def _parse_junit(path):
    if not path or not os.path.isfile(path):
        raise ValueError("junit evidence file not found: %s" % path)
    import xml.etree.ElementTree as ET
    digest = _hash_input_file(path)
    root = ET.parse(path).getroot()
    testcases = list(root.iter("testcase"))
    names = sorted(
        (tc.get("classname") or "") + "::" + (tc.get("name") or "")
        for tc in testcases)
    failures = sum(1 for tc in testcases if tc.find("failure") is not None)
    errors = sum(1 for tc in testcases if tc.find("error") is not None)
    skipped = sum(1 for tc in testcases if tc.find("skipped") is not None)
    return {"tests": len(testcases), "failures": failures, "errors": errors,
            "skipped": skipped, "names": names}, digest

def _read_json_and_hash(path):
    if not path or not os.path.isfile(path):
        raise ValueError("evidence file not found: %s" % path)
    digest = _hash_input_file(path)
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc, digest

def _finalize_attempt_legacy(params):
    """Author the attempt-root `stage: simulation` CDE from OPENED evidence.

    This is the ONLY supported attempt-root CDE writer for this tool: it never
    trusts a native sub-CDE's self-reported verdict at face value -- it opens
    and hashes the generation CDE, both JUnit XML runs, the non-vacuity CDE,
    and the regression log, and derives every gating number itself.
    """
    def _fail(error, extra_provenance=None):
        env = {
            "tool": TOOL, "stage": "simulation", "status": "failed",
            "objective": params.get("objective")
                or ("Finalize the attempt-root testbench-generation "
                    "simulation CDE from independently opened native evidence"),
            "tools_used": [{"name": "testbench-generation-finalizer",
                            "version": "1.0.0"}],
            "pdk_binding": "none", "assumptions": [],
            "inputs_ref": dict(params.get("evidence_refs") or {}),
            "vplan": params.get("vplan") or "shared_artifact",
            "results": {}, "qor_metrics": {}, "signoff_evidence": {},
            "margin": {}, "error": error,
            "validation": {"verdict": "fail", "note": error},
            "verdict": "fail",
            "provenance": {"engine": "finalize_attempt aggregator"},
        }
        if extra_provenance:
            env["provenance"].update(extra_provenance)
        return _finalize_envelope(env)

    evidence_refs = params.get("evidence_refs")
    if not isinstance(evidence_refs, dict) or not evidence_refs:
        return _fail("finalize_attempt requires a non-empty 'evidence_refs' "
                     "map of workspace-relative paths for every opened "
                     "evidence file")

    bad_refs = sorted(k for k, v in evidence_refs.items()
                       if _looks_workspace_absolute(v))
    if bad_refs:
        return _fail(
            "evidence_refs must be workspace-relative (repo-relative) paths, "
            "never container-mount-absolute paths -- offending key(s): %s"
            % ", ".join(bad_refs))

    required = ("generation_cde", "junit_xml", "junit_rerun_xml",
                "nonvacuity_cde")
    missing = [k for k in required if not params.get(k)]
    if missing:
        return _fail("finalize_attempt missing required evidence path(s): %s"
                     % ", ".join(missing))

    evidence_hashes = {}
    try:
        generation_cde, gen_hash = _read_json_and_hash(params["generation_cde"])
        evidence_hashes["generation_cde"] = gen_hash
        nonvacuity_cde, nv_hash = _read_json_and_hash(params["nonvacuity_cde"])
        evidence_hashes["nonvacuity_cde"] = nv_hash
        junit, junit_hash = _parse_junit(params["junit_xml"])
        evidence_hashes["junit_xml"] = junit_hash
        junit_rerun, junit_rerun_hash = _parse_junit(params["junit_rerun_xml"])
        evidence_hashes["junit_rerun_xml"] = junit_rerun_hash
    except Exception as exc:
        return _fail(str(exc), extra_provenance={"evidence_hashes": evidence_hashes})

    regression_log_text = None
    if params.get("regression_log") and os.path.isfile(params["regression_log"]):
        evidence_hashes["regression_log"] = _hash_input_file(params["regression_log"])
        try:
            with open(params["regression_log"], "r", encoding="utf-8",
                      errors="replace") as fh:
                regression_log_text = fh.read()
        except Exception:
            regression_log_text = None

    if junit["tests"] == 0 or junit_rerun["tests"] == 0:
        return _fail(
            "runtime evidence carries zero executed testcases -- a "
            "self-checking suite must actually EXECUTE at least one real "
            "test before and after mutation, not merely compile",
            extra_provenance={"evidence_hashes": evidence_hashes})

    testcase_set_mismatch = junit["names"] != junit_rerun["names"]

    gen_results = generation_cde.get("results") or {}
    smoke_failures = _mval(gen_results, "smoke_failures", 0) or 0
    missing_vplan_linkage = _mval(gen_results, "missing_vplan_linkage", None)
    interface_mismatches = _mval(gen_results, "interface_mismatches", 0) or 0
    self_checking = bool(_mval(gen_results, "self_checking", False))
    gen_verdict = ((generation_cde.get("validation") or {}).get("verdict")
                  or generation_cde.get("verdict"))

    nv_results = nonvacuity_cde.get("results") or {}
    nv_qor = nonvacuity_cde.get("qor_metrics") or {}
    mutants_killed = int(_mval(nv_results, "mutants_killed", 0) or 0)
    mutants_survived = int(_mval(nv_results, "mutants_survived", 0) or 0)
    mutants_unassessable = int(nv_qor.get("mutants_unassessable", 0) or 0)
    testbench_vacuous = bool(nv_qor.get("testbench_vacuous", False))
    nv_verdict = ((nonvacuity_cde.get("validation") or {}).get("verdict")
                 or nonvacuity_cde.get("verdict"))

    total_failures = junit["failures"]
    total_errors = junit["errors"]
    total_skipped = junit["skipped"]
    combined_failures = junit["failures"] + junit_rerun["failures"]
    combined_errors = junit["errors"] + junit_rerun["errors"]
    combined_skipped = junit["skipped"] + junit_rerun["skipped"]
    mismatches = total_failures
    elaboration_errors = int(smoke_failures)
    analyze_errors = int(interface_mismatches)

    reasons = []
    if combined_failures or combined_errors:
        reasons.append(
            "%d runtime testcase failure(s) / %d error(s) across the "
            "pre- and post-mutation identical suites"
            % (combined_failures, combined_errors))
    if combined_skipped:
        reasons.append("%d runtime testcase(s) skipped" % combined_skipped)
    if testcase_set_mismatch:
        reasons.append(
            "the pre- and post-mutation runtime testcase sets are not "
            "identical (%s vs %s)" % (junit["names"], junit_rerun["names"]))
    if elaboration_errors:
        reasons.append(
            "%d generation-stage smoke/compile failure(s)" % elaboration_errors)
    if analyze_errors:
        reasons.append(
            "%d generation-stage interface mismatch(es)" % analyze_errors)
    if not self_checking:
        reasons.append(
            "generation-stage environment is not self-checking (no "
            "reference model wired)")
    if gen_verdict != "pass":
        reasons.append(
            "generation-stage native CDE verdict is %r, not 'pass'"
            % gen_verdict)
    if mutants_killed < 1:
        reasons.append("non-vacuity killed zero assessable mutants")
    if mutants_unassessable:
        reasons.append("%d unassessable mutant run(s)" % mutants_unassessable)
    if testbench_vacuous:
        reasons.append("non-vacuity CDE reports the testbench is VACUOUS")
    if nv_verdict != "pass":
        reasons.append(
            "non-vacuity native CDE verdict is %r, not 'pass'" % nv_verdict)

    status = "failed" if reasons else "completed"
    verdict = "fail" if reasons else "pass"
    note = "; ".join(reasons) if reasons else (
        "identical runtime testcase set (%d tests) passed before and after "
        "mutation with zero fail/error/skip; non-vacuity killed %d/%d "
        "assessable mutant(s) with zero unassessable runs"
        % (junit["tests"], mutants_killed, mutants_killed + mutants_survived))

    results = {
        "failures": _metric(total_failures, "count", "gating", "== 0"),
        "failing_tests": _metric(total_failures, "count", "gating", "== 0"),
        "errors": _metric(total_errors, "count", "gating", "== 0"),
        "skipped": _metric(total_skipped, "count", "gating", "== 0"),
        "elaboration_errors": _metric(elaboration_errors, "count", "gating", "== 0"),
        "analyze_errors": _metric(analyze_errors, "count", "gating", "== 0"),
        "sim_passed": _metric(not reasons, "bool", "gating", "== True"),
        "tests": _metric(junit["tests"], "count", "diagnostic", ">= 1"),
        "tests_run": _metric(junit["tests"], "count", "diagnostic", ">= 1"),
        "directed_tests_completed": _metric(junit["tests"], "count",
                                            "diagnostic", ">= 1"),
        "rerun_failures": _metric(junit_rerun["failures"], "count", "gating",
                                  "== 0"),
        "interface_mismatches": _metric(analyze_errors, "count", "gating", "== 0"),
        "environment_self_checking": _metric(self_checking, "bool", "gating",
                                             "== True"),
        "mutants_killed": _metric(mutants_killed, "count", "gating", ">= 1"),
        "mutants_survived": _metric(mutants_survived, "count", "diagnostic",
                                    ">= 0"),
        "mutants_unassessable": _metric(mutants_unassessable, "count",
                                        "gating", "== 0"),
        "mismatches": _metric(mismatches, "count", "gating", "== 0"),
        "scoreboard_mismatches": _metric(mismatches, "count", "gating", "== 0"),
    }
    if missing_vplan_linkage is None:
        # No blessed campaign vplan existed -- an honest not-assessable, never
        # a fabricated 0. See _finalize_attempt callers' assumptions.
        results["missing_vplan_linkage"] = {
            "value": None, "unit": "count", "class": "not_assessable",
            "basis": "no blessed campaign vplan existed at generation time",
            "note": ("vplan linkage could not be genuinely measured -- this "
                     "is a named residual (owner: vplan authoring), not a "
                     "fabricated zero"),
        }
    else:
        results["missing_vplan_linkage"] = _metric(
            int(missing_vplan_linkage), "count", "gating", "== 0")

    if regression_log_text:
        m = re.search(
            r"RANDOM_REGRESSION_SUMMARY\s+frames=(\d+)\s+bytes=(\d+)\s+"
            r"mismatches=(\d+)", regression_log_text)
        if m:
            frames, byte_count, log_mismatches = (int(x) for x in m.groups())
            results["random_regression_frames"] = _metric(
                frames, "frames", "diagnostic", ">= 1")
            results["executed_comparisons"] = _metric(
                byte_count, "comparisons", "diagnostic", ">= 1")
            if log_mismatches and "random_regression_mismatches" not in reasons:
                reasons.append(
                    "regression log reports %d mismatch(es)" % log_mismatches)
                status, verdict = "failed", "fail"

    results["stage"] = "simulation"
    env = {
        "tool": TOOL, "stage": "simulation", "status": status,
        "objective": params.get("objective")
            or ("Finalize the attempt-root testbench-generation simulation "
                "CDE from independently opened native evidence"),
        "tools_used": [{"name": "testbench-generation-finalizer",
                        "version": "1.0.0"}],
        "pdk_binding": "none",
        "assumptions": params.get("attempt_intent") and [params["attempt_intent"]] or [],
        "inputs_ref": dict(evidence_refs),
        "vplan": params.get("vplan") or "shared_artifact",
        "results": results, "qor_metrics": {}, "signoff_evidence": {},
        "margin": {},
        "validation": {"verdict": verdict, "note": note},
        "verdict": verdict,
        "provenance": {"engine": "finalize_attempt aggregator",
                       "evidence_hashes": evidence_hashes},
    }
    if reasons:
        env["error"] = note
    return _finalize_envelope(env)
