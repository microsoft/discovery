#!/usr/bin/env python3
"""dft_utils.py -- real Yosys-driven Design-for-Test structural analysis.

Elaborates RTL/netlist with Yosys, enumerates flip-flops (scan candidates),
classifies scannable vs. hazardous elements (latches, async-set/reset, gated
clocks that block a clean scan chain), and plans scan chains (count + max length)
for the requested chain budget. Node-aware (scan cell from the binding). This is
the Yosys back-end of the DFT flow. Results conform to the Common Design Envelope.
"""
import json
import heapq
import math
import os
import re
import shutil
import subprocess
import time

TOOL = "dft"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


def _is_ident(s):
    """True if *s* is a safe HDL/Tcl identifier -- blocks script injection via
    user-supplied module/cell/net names interpolated into Yosys scripts."""
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
        if (low.endswith((".log", ".tcl", ".ys", ".sh", ".do"))
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
          "- `logs/` \u2014 verbatim Yosys log and the exact run command", ""]
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


def _yosys_version():
    try:
        out = subprocess.run(["yosys", "-V"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return txt.splitlines()[0] if txt else "yosys"
    except Exception:
        return "yosys"


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "Yosys DFT analysis", "version": _yosys_version()}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "shared_artifact",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "scan_analysis"},
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
    if params.get("netlist"):
        files.append(params["netlist"])
    files += [f for f in params.get("rtl_files", []) if os.path.exists(str(f))]
    return files


def _resolve_liberty(params):
    """Resolve Liberty path(s) for gate-level cell models from params or the PDK
    binding. A mapped (gate-level) netlist instantiates standard-cell masters
    (e.g. sky130_fd_sc_hd__dfxtp_1) that are NOT defined in the netlist; Yosys
    `hierarchy -check` fails on them unless the cell models are loaded. Reading
    the node Liberty as `-lib` (blackbox) supplies those interfaces. Returns a
    de-duplicated list of existing Liberty files (may be empty for pure RTL)."""
    binding = params.get("pdk_binding") or {}
    lib = params.get("liberty")
    if not lib and isinstance(binding, dict):
        lib = binding.get("liberty")
        if not lib:
            refs = binding.get("references") or {}
            for k in ("liberty_tt", "liberty", "liberty_ss", "liberty_ff"):
                r = refs.get(k)
                if isinstance(r, dict):
                    lib = r.get("container_path") or r.get("path")
                elif isinstance(r, str):
                    lib = r
                if lib:
                    break
    if not lib:
        return []
    libs = lib if isinstance(lib, list) else [lib]
    out, seen = [], set()
    for p in libs:
        p = str(p)
        if p and p not in seen and os.path.exists(p):
            seen.add(p)
            out.append(p)
    return out


def _looks_gate_level(files):
    """Heuristic: a mapped/gate-level netlist references standard-cell masters by
    name. Detect by scanning for a common stdcell library prefix so we know to
    load Liberty cell models before elaboration."""
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as _fh:
                head = _fh.read(200000)
            if re.search(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9]+_sc_[A-Za-z0-9]+__", head):
                return True
        except Exception:
            continue
    return False


def _classify_scan_cells(cells):
    scannable = 0
    hazards = {"latch": 0, "async_set_reset": 0, "gated_or_other": 0}
    for cell in cells.values():
        cell_type = str(cell.get("type", ""))
        if not cell_type.startswith("$"):
            lower = cell_type.lower()
            if re.search(r"(?:^|__)[a-z]*dl[a-z]*tp", lower) or "latch" in lower:
                hazards["latch"] += 1
            elif re.search(r"(?:^|__)[a-z]*df[a-z]*[rs][a-z]*tp", lower) \
                    or re.search(r"__s?edf|__dffs|__sdf[bf]", lower):
                hazards["async_set_reset"] += 1
            elif re.search(r"(?:^|__)[a-z]*df[a-z]*tp", lower) \
                    or "__dff" in lower:
                scannable += 1
            continue
        upper = cell_type.upper()
        # Yosys proc retains vector registers as one cell; scan chains shift
        # storage bits, not vector-cell instances.
        width = max(1, len(cell.get("connections", {}).get("Q", [])))
        if upper.startswith(("$DLATCH", "$_DLATCH")):
            hazards["latch"] += width
        elif upper.startswith(("$ADFF", "$ALDFF", "$DFFSR", "$SDFFCE",
                               "$_DFFSR", "$_SDFF", "$_ADFF")):
            hazards["async_set_reset"] += width
        elif upper.startswith(("$DFF", "$DFFE", "$SDFF", "$_DFF")):
            scannable += width
        elif upper.startswith("$DLATCHSR"):
            hazards["gated_or_other"] += width
    total = scannable + sum(hazards.values())
    coverage = round(100.0 * scannable / total, 2) if total else 0.0
    return {
        "scannable_ff": scannable, "hazards": hazards,
        "total_sequential": total, "coverage_estimate_pct": coverage,
        "clean": scannable > 0 and not any(hazards.values()),
    }


def _coverage_target(params):
    value = params.get("coverage_target", params.get("coverage_goal_pct", 95.0))
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 95.0
    return value if 0.0 <= value <= 100.0 else 95.0


def _atpg_verdict(coverage, target, sampled, aborted):
    if coverage < target:
        return "pass_with_caveats" if coverage > 0 else "fail"
    if sampled or aborted:
        return "pass_with_caveats"
    return "pass"


def _select_faults(faults, params):
    """Select the exhaustive fault set or one deterministic campaign shard."""
    if "fault_shard_count" not in params and "fault_shard_index" not in params:
        try:
            legacy_limit = int(params.get("max_faults", 0))
        except (TypeError, ValueError):
            raise ValueError("max_faults must be an integer")
        if legacy_limit > 0 and len(faults) > legacy_limit:
            step = len(faults) / float(legacy_limit)
            indexes = sorted(set(int(index * step)
                                 for index in range(legacy_limit)))
            selected = [faults[index] for index in indexes]
            return selected, {
                "mode": "diagnostic_sample", "population": len(faults),
                "selected": len(selected), "shard_index": None,
                "shard_count": None,
            }
    try:
        shard_count = int(params.get("fault_shard_count", 1))
        shard_index = int(params.get("fault_shard_index", 0))
    except (TypeError, ValueError):
        raise ValueError("fault_shard_count and fault_shard_index must be integers")
    if shard_count < 1:
        raise ValueError("fault_shard_count must be >= 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("fault_shard_index must be in [0, fault_shard_count)")
    selected = list(faults)[shard_index::shard_count]
    return selected, {
        "mode": "exhaustive" if shard_count == 1 else "deterministic_shard",
        "population": len(faults), "selected": len(selected),
        "shard_index": None if shard_count == 1 else shard_index,
        "shard_count": None if shard_count == 1 else shard_count,
    }


def _compact_patterns(patterns):
    """Deterministic greedy set cover over already graded fault patterns."""
    remaining = set().union(*(set(item.get("detects", [])) for item in patterns))
    candidates = list(enumerate(patterns))
    compacted = []
    while remaining:
        ranked = sorted(
            candidates,
            key=lambda item: (-len(set(item[1].get("detects", [])) & remaining),
                              item[0]))
        index, best = ranked[0]
        newly_detected = set(best.get("detects", [])) & remaining
        if not newly_detected:
            break
        compacted.append(best)
        remaining -= newly_detected
        candidates = [item for item in candidates if item[0] != index]
    return compacted


def _plan_scan_domains(cells, chain_count, max_chain_length):
    """Keep clock/reset/power domains separate and balance within each domain."""
    try:
        chain_count = int(chain_count)
        max_chain_length = int(max_chain_length)
    except (TypeError, ValueError):
        raise ValueError("chain_count and max_chain_length must be integers")
    if chain_count < 1 or max_chain_length < 1:
        raise ValueError("chain_count and max_chain_length must be >= 1")
    groups = {}
    for cell in cells:
        key = (cell.get("clock"), cell.get("reset"), cell.get("power"))
        groups.setdefault(key, []).append(str(cell["name"]))
    allocations = {
        key: max(1, math.ceil(len(names) / max_chain_length))
        for key, names in groups.items()}
    minimum_chains = sum(allocations.values())
    if minimum_chains > chain_count:
        raise ValueError(
            "max_chain_length requires at least %d domain-local chains" %
            minimum_chains)
    remaining = chain_count - minimum_chains
    while remaining:
        key = max(
            allocations,
            key=lambda item: (len(groups[item]) / allocations[item], str(item)))
        if allocations[key] >= len(groups[key]):
            break
        allocations[key] += 1
        remaining -= 1
    plan = []
    for (clock, reset, power), names in sorted(groups.items(), key=str):
        sorted_names = sorted(names)
        chains = [[] for _ in range(allocations[(clock, reset, power)])]
        for index, name in enumerate(sorted_names):
            chains[index % len(chains)].append(name)
        for chain in chains:
            plan.append({
                "domain": {"clock": clock, "reset": reset, "power": power},
                "cells": chain,
            })
    return plan


def _liberty_blocks(text, keyword):
    blocks = {}
    pattern = re.compile(r"\b" + re.escape(keyword) +
                         r"\s*\(\s*[\"']?([^\"')\s]+)[\"']?\s*\)\s*\{")
    for match in pattern.finditer(text):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        if depth == 0:
            blocks[match.group(1)] = text[match.end():index - 1]
    return blocks


def _validate_scan_cell_contract(liberties, from_cell, to_cell, scan_data_pin,
                                 scan_enable_pin, q_pin):
    cells = {}
    for liberty in liberties:
        with open(liberty, encoding="utf-8", errors="replace") as stream:
            cells.update(_liberty_blocks(stream.read(), "cell"))
    if from_cell not in cells:
        raise ValueError("functional flop cell is absent from Liberty: " + from_cell)
    if to_cell not in cells:
        raise ValueError("scan cell is absent from Liberty: " + to_cell)

    def pins(cell):
        return {
            name: (re.search(r"\bdirection\s*:\s*[\"']?(input|output|inout)[\"']?\s*;", body)
                   .group(1) if re.search(
                       r"\bdirection\s*:\s*[\"']?(input|output|inout)[\"']?\s*;", body)
                   else None)
            for name, body in _liberty_blocks(cells[cell], "pin").items()
        }

    functional = pins(from_cell)
    scan = pins(to_cell)
    required = {"CLK": "input", "D": "input", q_pin: "output"}
    for pin, direction in required.items():
        if functional.get(pin) != direction or scan.get(pin) != direction:
            raise ValueError("functional pin contract mismatch for %s" % pin)
    for pin in (scan_data_pin, scan_enable_pin):
        if scan.get(pin) != "input":
            raise ValueError("scan cell pin %s must be an input" % pin)
    return {
        "compatible": True, "from_cell": from_cell, "to_cell": to_cell,
        "functional_pins": ["CLK", "D", q_pin],
        "scan_pins": [scan_data_pin, scan_enable_pin],
    }


def _scan_analysis(params):
    if not shutil.which("yosys"):
        return _cde(objective="DFT scan analysis", status="failed",
                    error="yosys not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    top = params.get("top")
    files = _stage_rtl(params)
    if not top or not files:
        return _cde(objective="DFT scan analysis", status="failed", pdk_binding=binding or "none",
                    error="missing 'top' or RTL/netlist", validation={"verdict": "fail"})
    if not _is_ident(top):
        return _cde(objective="DFT scan analysis", status="failed", pdk_binding=binding or "none",
                    error=f"invalid 'top' identifier: {top!r}", validation={"verdict": "fail"})
    js = os.path.join(_WORK_DIR, "netlist.json")
    # Load node Liberty as blackbox cell models so a gate-level netlist's
    # standard-cell instances (e.g. sky130_fd_sc_hd__dfxtp_1) resolve during
    # `hierarchy -check`. For pure RTL no Liberty is needed and none is required.
    libs = _resolve_liberty(params)
    gate_level = _looks_gate_level(files)
    lib_reads = "\n".join(f"read_liberty -lib {l}" for l in libs)
    reads = "\n".join(f"read_verilog {f}" for f in files)
    script = f"""{lib_reads}
{reads}
hierarchy -check -top {top}
proc
flatten
write_json {js}
stat
"""
    sp = os.path.join(_WORK_DIR, "dft.ys")
    open(sp, "w").write(script)
    cmd = ["yosys", "-q", "-s", sp]
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "dft.log"), "w").write(out)
    if proc.returncode != 0 or not os.path.exists(js):
        # A gate-level netlist that references unresolved standard-cell masters is
        # a missing-cell-models INPUT error (supply the PDK Liberty), not a
        # scan-hazard finding. Classify it distinctly so it is not mis-triaged.
        _unresolved = re.search(
            r"Module `\\?([^']+?)'[^\n]*is not part of the design", out)
        if _unresolved:
            _cell = _unresolved.group(1)
            _hint = (f"gate-level netlist references standard-cell master "
                     f"'{_cell}' with no loaded model. Supply the node Liberty so "
                     f"the tool can `read_liberty -lib` the cell interfaces before "
                     f"elaboration (params.liberty or pdk_binding.references."
                     f"liberty_tt.container_path).")
            if libs:
                _hint += (" Liberty WAS provided but did not define this master; "
                          "check that the netlist's library matches the binding "
                          "corner/library.")
            else:
                _hint += " No Liberty was resolved from params or the PDK binding."
            return _cde(
                objective=f"DFT scan analysis of {top}", status="failed",
                pdk_binding=binding or "none",
                results={"unresolved_cell_master": _cell,
                         "gate_level_detected": gate_level,
                         "liberty_loaded": libs},
                signoff={"dft_ready": False, "tool_input_error": True,
                         "missing_cell_models": True,
                         "unresolved_cell_master": _cell,
                         "liberty_loaded": libs, "remediation": _hint},
                inputs_ref={"files": files, "liberty": libs},
                assumptions=["missing standard-cell models is an input/mount error, "
                             "not a scan-hazard finding"],
                error=("Yosys elaboration failed: unresolved standard-cell master '"
                       + _cell + "'. " + _hint + "\n\nlog tail:\n" + out[-1200:]),
                validation={"verdict": "fail",
                            "note": "missing cell models for gate-level netlist "
                                    "(load PDK Liberty)"},
                provenance={"yosys": _yosys_version(), "log": "dft.log"})
        return _cde(objective=f"DFT scan analysis of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="Yosys elaboration failed; see dft.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"yosys": _yosys_version(), "log": "dft.log"})
    netlist = json.load(open(js))
    mod = netlist["modules"].get(top) or next(iter(netlist["modules"].values()))
    cells = mod.get("cells", {})
    classification = _classify_scan_cells(cells)
    scannable = classification["scannable_ff"]
    hazards = classification["hazards"]
    total_ff = classification["total_sequential"]
    # Scan-chain planning for the requested chain budget.
    try:
        n_chains = max(1, int(params.get("scan_chains", 1)))
    except (TypeError, ValueError):
        n_chains = 1
    import math
    max_len = math.ceil(scannable / n_chains) if scannable else 0
    # Coverage-ready if there are no latches (uncontrollable) and there is at
    # least one scannable element. Async set/reset flops are scannable with a
    # test-mode override but flagged.
    clean = classification["clean"]
    verdict = "pass" if clean else ("pass_with_caveats" if scannable > 0 else "fail")
    scan_coverage_est = classification["coverage_estimate_pct"]
    return _cde(
        objective=f"DFT scan analysis of {top}",
        status="completed", pdk_binding=binding or "none",
        # KEY NAMES ARE A CONTRACT WITH THE PROGRESS REGISTRY, NOT A LOCAL
        # CHOICE. `cde_progress.py`'s `dft` recipe binds `scannability` from
        # `results.total_sequential`/`sequential_elements` against
        # `results.eligible_scan_flops`/`eligible_flops`, and `hazards` from
        # `results.latches`/`async_set_reset_hazards`/`other_hazards` plus
        # `validation.all_hazards_zero`. This tool emitted `flip_flops`,
        # `scannable_ff` and `signoff_evidence.scan_hazards` -- a third dialect
        # matching none of them -- so both families evaluated `not_assessable`,
        # `gate_closed` was forced False, and an honest 32/32-scannable,
        # zero-hazard pass was rejected as `gate_not_closed` until the caller
        # hand-aliased the same numbers under the registry's names.
        # The original names are kept so existing consumers do not break.
        results={"flip_flops": {"value": total_ff, "unit": "count"},
                 "scannable_ff": {"value": scannable, "unit": "count"},
                 "total_sequential": {"value": total_ff, "unit": "count"},
                 "eligible_scan_flops": {"value": scannable, "unit": "count"},
                 "latches": {"value": hazards["latch"], "unit": "count"},
                 "async_set_reset_hazards": {
                     "value": hazards["async_set_reset"], "unit": "count"},
                 "other_hazards": {
                     "value": hazards["gated_or_other"], "unit": "count"},
                 "scan_coverage_estimate": {"value": scan_coverage_est, "unit": "percent"}},
        qor={"flip_flops": total_ff, "scannable_ff": scannable,
             "total_sequential": total_ff, "eligible_scan_flops": scannable,
             "scan_chains": n_chains, "max_chain_length": max_len,
             "scan_coverage_estimate_pct": scan_coverage_est},
        signoff={"scannable_ff": scannable, "scan_hazards": hazards,
                 "hazards": hazards,
                 "scan_chains": n_chains, "max_chain_length": max_len,
                 "scan_cell": (binding.get("scan_cell") or params.get("scan_cell")),
                 "gate_level_netlist": gate_level, "liberty_loaded": libs,
                 "dft_ready": clean, "report": "dft.log"},
        inputs_ref={"files": files, "liberty": libs},
        assumptions=["structural scan analysis: posedge D-FFs are scannable; "
                     "latches block scan; async set/reset flops need a test-mode "
                     "override; ATPG fault coverage is a separate (Fault) step; "
                     "gate-level netlists load PDK Liberty (read_liberty -lib) so "
                     "standard-cell masters resolve during elaboration"],
        validation={"verdict": verdict,
                    # Covers ALL hazard categories, unlike the `results.latches`
                    # alias the count component binds first.
                    "all_hazards_zero": not any(hazards.values()),
                    "note": "no scan hazards; scannable design" if clean
                    else (f"{hazards['latch']} latch(es) block scan"
                          if hazards["latch"] else "no scannable flip-flops found")},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "dft.log"},
    )


def _atpg(params):
    """Combinational stuck-at ATPG via yosys SAT test generation.

    For each primary output we SAT-solve for an input pattern that drives it to 1
    (a test for the output stuck-at-0 fault) and to 0 (stuck-at-1). A satisfiable
    result yields a real test vector and marks the fault DETECTABLE; UNSAT marks
    it REDUNDANT/untestable (the output is stuck -- a genuine design finding).
    This is real SAT-based test generation for the primary-output fault set;
    full internal-net fault grading is the documented extension.

    Node-agnostic (works on RTL); the design is flattened + mapped to a gate
    netlist first so the SAT instance is combinational."""
    if not shutil.which("yosys"):
        return _cde(objective="ATPG", status="failed",
                    error="yosys not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    top = params.get("top")
    files = _stage_rtl(params)
    if not top or not files:
        return _cde(objective="ATPG", status="failed", pdk_binding=binding or "none",
                    error="missing 'top' or RTL/netlist", validation={"verdict": "fail"})
    if not _is_ident(top):
        return _cde(objective="ATPG", status="failed", pdk_binding=binding or "none",
                    error=f"invalid 'top' identifier: {top!r}", validation={"verdict": "fail"})
    js = os.path.join(_WORK_DIR, "atpg_netlist.json")
    reads = "\n".join(f"read_verilog {f}" for f in files)
    # Flatten + synth to a gate netlist so the SAT model is purely combinational.
    prep = os.path.join(_WORK_DIR, "atpg_prep.ys")
    open(prep, "w").write(
        f"{reads}\nhierarchy -check -top {top}\nproc\nflatten\n"
        f"synth -top {top}\nwrite_json {js}\n")
    p0 = subprocess.run(["yosys", "-q", "-s", prep], capture_output=True,
                        text=True, cwd=_WORK_DIR)
    if p0.returncode != 0 or not os.path.exists(js):
        return _cde(objective=f"ATPG of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="yosys elaboration failed:\n" + (p0.stdout + p0.stderr)[-1500:],
                    validation={"verdict": "fail"})
    net = json.load(open(js))
    mod = net["modules"].get(top) or next(iter(net["modules"].values()))
    outs, ins = [], []
    for name, port in (mod.get("ports") or {}).items():
        (outs if port.get("direction") == "output" else ins).append(name)
    if not outs:
        return _cde(objective=f"ATPG of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="design has no primary outputs to target",
                    validation={"verdict": "fail"})
    show = " ".join(f"-show {i}" for i in ins)
    faults = []           # {output, stuck_at, detectable, pattern}
    detectable = 0
    log_all = p0.stdout
    for o in outs:
        for target, stuck in ((1, "sa0"), (0, "sa1")):
            sc = os.path.join(_WORK_DIR, "atpg_sat.ys")
            open(sc, "w").write(
                f"read_json {js}\nhierarchy -top {top}\n"
                f"sat -set {o} {target} {show}\n")
            ps = subprocess.run(["yosys", "-s", sc], capture_output=True,
                                text=True, cwd=_WORK_DIR)
            out = ps.stdout + ps.stderr
            log_all += out
            # yosys sat: "SAT solving finished - model found:" => detectable;
            # "no model found" / "unsatisfiable" => redundant.
            is_sat = ("model found" in out.lower()
                      and "no model found" not in out.lower())
            pattern = {}
            if is_sat:
                # model table rows:  \<name>   <Dec>   <Hex>   <Bin>
                for m in re.finditer(r"^\s*\\(\S+)\s+(-?\d+)\s+", out, re.M):
                    pattern[m.group(1)] = m.group(2)
            detect = is_sat
            if detect:
                detectable += 1
            faults.append({"output": o, "stuck_at": stuck,
                           "detectable": bool(detect),
                           "pattern": pattern or None})
    open(os.path.join(_OUTPUT_DIR, "atpg.log"), "w").write(log_all)
    total = len(faults)
    redundant = [f for f in faults if not f["detectable"]]
    coverage = round(100.0 * detectable / total, 2) if total else 0.0
    # Redundant output faults mean an output is stuck -- a real design issue.
    verdict = "pass" if not redundant else "pass_with_caveats"
    return _cde(
        objective=f"combinational stuck-at ATPG of {top}", status="completed",
        pdk_binding=binding or "none",
        results={"output_faults": {"value": total, "unit": "count"},
                 "detectable_faults": {"value": detectable, "unit": "count"},
                 "fault_coverage": {"value": coverage, "unit": "percent"}},
        qor={"output_faults": total, "detectable_faults": detectable,
             "redundant_faults": len(redundant), "fault_coverage_pct": coverage},
        signoff={"fault_coverage_pct": coverage, "detectable": detectable,
                 "redundant_output_faults": [{"output": f["output"],
                                              "stuck_at": f["stuck_at"]}
                                             for f in redundant],
                 "test_patterns": [f for f in faults if f["detectable"]][:64],
                 "report": "atpg.log"},
        inputs_ref={"files": files},
        assumptions=["SAT-based combinational test generation for the primary-"
                     "output stuck-at fault set; a redundant (UNSAT) fault means "
                     "the output is stuck; full internal-net fault grading and "
                     "sequential ATPG are the documented extension"],
        validation={"verdict": verdict,
                    "note": (f"{coverage}% output-fault coverage; all testable"
                             if not redundant else
                             f"{len(redundant)} redundant output fault(s) -- stuck output")},
        provenance={"yosys": _yosys_version(), "log": "atpg.log"},
    )


def _retarget_scan_output(module, port_name, tail_bit):
    old_bits = list(module["ports"].get(port_name, {}).get("bits", []))
    module["ports"][port_name] = {"direction": "output", "bits": [tail_bit]}

    preferred = {
        "hide_name": 0,
        "bits": [tail_bit],
        "attributes": {},
    }
    rewritten = {port_name: preferred}
    for name, netname in module["netnames"].items():
        if name == port_name:
            continue
        # Once the public port is moved to the scan tail, aliases that named
        # only its abandoned functional driver must not survive emission.
        if old_bits != [tail_bit] and netname.get("bits", []) == old_bits \
                and name not in module["ports"]:
            continue
        rewritten[name] = netname
    module["netnames"] = rewritten


def _resolve_functional_models(params):
    binding = params.get("pdk_binding") or {}
    models = params.get("functional_models")
    defines = params.get("functional_model_defines")
    if models is None and isinstance(binding, dict):
        contract = binding.get("functional_cell_models") or {}
        yosys_model = contract.get("yosys_model") or {}
        path = (yosys_model.get("container_path") or
                yosys_model.get("path"))
        models = [path] if path else None
        if defines is None:
            defines = yosys_model.get("defines")
    paths = []
    for value in _as_list(models):
        if isinstance(value, dict):
            value = value.get("container_path") or value.get("path")
        if value and os.path.isfile(str(value)):
            paths.append(str(value))
    safe_defines = []
    for define in _as_list(defines):
        text = str(define)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_+./:-]*)?",
                            text):
            raise ValueError("unsafe functional model define: %r" % define)
        safe_defines.append(text)
    return paths, safe_defines


def _generate_liberty_sim_models(params):
    liberties = _resolve_liberty(params)
    if not liberties:
        return None
    output = os.path.join(_WORK_DIR, "liberty_sim_models.v")
    script = os.path.join(_WORK_DIR, "liberty_sim_models.ys")
    reads = "\n".join(
        "read_liberty -ignore_miss_func -ignore_miss_data_latch %s" % path
        for path in liberties)
    open(script, "w").write(reads + "\nwrite_verilog -noattr %s\n" % output)
    process = subprocess.run(
        ["yosys", "-q", "-s", script], capture_output=True, text=True,
        cwd=_WORK_DIR)
    log = process.stdout + "\n" + process.stderr
    open(os.path.join(_OUTPUT_DIR, "liberty_sim_models.log"), "w").write(log)
    if process.returncode or not os.path.isfile(output) or not os.path.getsize(output):
        return None
    return output


def _scan_mappings(params, binding):
    """Resolve flop -> scan-flop substitutions. NODE CONSTANTS COME FROM THE BINDING.

    THIS FUNCTION USED TO CARRY sky130 LITERALS AS A FALLBACK, and that was the
    single most dangerous silent default in the flow:

        from_cell       -> "sky130_fd_sc_hd__dfxtp_1"
        to_cell         -> "sky130_fd_sc_hd__sdfxtp_1"
        scan_data_pin   -> "SCD"
        scan_enable_pin -> "SCE"

    On sky130 those values are correct, so an unbound campaign still "worked"
    while taking node constants from tool code instead of from the hashed
    binding -- the defect was invisible precisely because the baseline node
    masked it. On ANY OTHER NODE the same code emits a WRONG SCAN NETLIST WITH
    NO ERROR: on nangate45 the scan flop is `SDFF_X1` with pins `SI`/`SE`, so
    every substitution silently targets cells that do not exist, and the result
    is a netlist that looks scan-inserted and is not.

    A wrong answer delivered confidently is worse than a refusal, so there is now
    NO fallback. An unbound campaign fails closed and names what it needs. The
    pin DEFAULTS on the per-item path below are likewise gone: an entry that
    declares `from_cell`/`to_cell` but omits its pins was silently acquiring
    sky130's `SCD`/`SCE`.
    """
    raw = params.get("scan_cell_mappings")
    if raw is None and isinstance(binding, dict):
        raw = binding.get("scan_cell_mappings")
    if raw is None:
        # Permit an explicit caller-supplied pair, but require it to be COMPLETE.
        # Partial specification is how a sky130 pin name used to sneak in beside
        # a correctly-specified cell name.
        explicit = {
            "from_cell": params.get("scan_from_cell"),
            "to_cell": params.get("scan_to_cell")
            or (binding.get("scan_cell") if isinstance(binding, dict) else None),
            "scan_data_pin": params.get("scan_data_pin"),
            "scan_enable_pin": params.get("scan_enable_pin"),
            "q_pin": params.get("ff_q_pin"),
        }
        supplied = {k: v for k, v in explicit.items() if v}
        if not supplied:
            raise ValueError(
                "scan_cell_mappings is unresolved: no mapping was supplied by the "
                "caller and the PDK binding carries no `scan_cell_mappings` (nor a "
                "`scan_cell`). Scan-cell masters and scan pin names are NODE "
                "constants and must come from the hashed binding -- this tool no "
                "longer falls back to sky130 literals, because on another node "
                "that silently produces a wrong scan netlist with no error. "
                "Bind `scan_cell_mappings` (from_cell, to_cell, scan_data_pin, "
                "scan_enable_pin, q_pin) and re-run.")
        incomplete = sorted(k for k, v in explicit.items() if not v)
        if incomplete:
            raise ValueError(
                "scan mapping is incomplete: missing %s. Every field is a node "
                "constant; partially specifying one lets the unspecified fields "
                "silently inherit another node's values." % ", ".join(incomplete))
        raw = [explicit]
    mappings = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            raise ValueError("scan_cell_mappings entries must be objects")
        mapping = {
            "from_cell": item.get("from_cell"),
            "to_cell": item.get("to_cell"),
            "scan_data_pin": item.get("scan_data_pin"),
            "scan_enable_pin": item.get("scan_enable_pin"),
            "q_pin": item.get("q_pin"),
        }
        absent = sorted(k for k, v in mapping.items() if v is None)
        if absent:
            raise ValueError(
                "scan mapping for %r is missing %s -- scan pin names differ per "
                "node (sky130 uses SCD/SCE, nangate45 uses SI/SE) and are never "
                "defaulted" % (mapping.get("from_cell") or "<unnamed>",
                               ", ".join(absent)))
        if not all(_is_ident(value) for value in mapping.values()):
            raise ValueError("scan mapping contains an invalid identifier")
        mappings.append(mapping)
    from_cells = [item["from_cell"] for item in mappings]
    if len(from_cells) != len(set(from_cells)):
        raise ValueError("scan_cell_mappings contains duplicate from_cell values")
    return mappings


def _dfflibmap_inventory(liberty):
    process = subprocess.run(
        ["yosys", "-Q", "-T", "-p",
         "dfflibmap -info -liberty %s" % liberty],
        capture_output=True, text=True, cwd=_WORK_DIR)
    output = process.stdout + "\n" + process.stderr
    path = os.path.join(_OUTPUT_DIR, "dfflibmap_info.log")
    open(path, "w").write(output)
    if process.returncode:
        raise RuntimeError("dfflibmap -info failed: " + output[-1200:])
    return {"report": "dfflibmap_info.log", "bytes": len(output),
            "mapping_lines": len(re.findall(r"^\s*cell\s+", output, re.M))}


def _strip_scan_interface(module, scan_ports):
    for name in scan_ports:
        module.get("ports", {}).pop(name, None)
        module.get("netnames", {}).pop(name, None)


def _equivalence_work(output):
    simple = len(re.findall(r"Executing EQUIV_SIMPLE pass", output))
    status = len(re.findall(r"Executing EQUIV_STATUS pass", output))
    return {
        "equiv_simple_executions": simple,
        "equiv_status_executions": status,
        "positive_proof_check_work_count": simple + status,
    }


def _prove_scan_functional_equivalence(pre_scan_json, post_scan_json, top,
                                       mappings, scan_ports, depth=8):
    import copy
    gold = copy.deepcopy(pre_scan_json)
    gate = copy.deepcopy(post_scan_json)
    gold_top = gold["modules"][top]
    gate_top = gate["modules"][top]
    _strip_scan_interface(gold_top, scan_ports)
    _strip_scan_interface(gate_top, scan_ports)
    reverse = {item["to_cell"]: item for item in mappings}
    for cell in gate_top.get("cells", {}).values():
        mapping = reverse.get(cell.get("type"))
        if not mapping:
            continue
        cell["type"] = mapping["from_cell"]
        cell.get("connections", {}).pop(mapping["scan_data_pin"], None)
        cell.get("connections", {}).pop(mapping["scan_enable_pin"], None)
        cell.get("port_directions", {}).pop(mapping["scan_data_pin"], None)
        cell.get("port_directions", {}).pop(mapping["scan_enable_pin"], None)
    gold_path = os.path.join(_WORK_DIR, "scan_equiv_gold.json")
    gate_path = os.path.join(_WORK_DIR, "scan_equiv_gate.json")
    json.dump(gold, open(gold_path, "w"))
    json.dump({"modules": {top: gate_top}}, open(gate_path, "w"))
    script = os.path.join(_WORK_DIR, "scan_equiv.ys")
    open(script, "w").write(
        f"read_json {gold_path}\nrename {top} gold\n"
        f"read_json {gate_path}\nrename {top} gate\n"
        "equiv_make gold gate equiv\nprep -top equiv\n"
        f"equiv_simple -seq {int(depth)}\nequiv_status -assert\n")
    process = subprocess.run(["yosys", "-s", script], capture_output=True,
                             text=True, cwd=_WORK_DIR)
    output = process.stdout + "\n" + process.stderr
    report = os.path.join(_OUTPUT_DIR, "scan_equivalence.log")
    open(report, "w").write(output)
    work = _equivalence_work(output)
    report_bytes = os.path.getsize(report) if os.path.isfile(report) else 0
    proven = (process.returncode == 0
              and "Equivalence successfully proven" in output
              and report_bytes > 0
              and work["equiv_simple_executions"] > 0
              and work["equiv_status_executions"] > 0)
    return {"verdict": "pass" if proven else "fail", "proven": proven,
            "depth": int(depth), "report": "scan_equivalence.log",
            "report_bytes": report_bytes,
            **work,
            "method": "scan-cell functional projection plus Yosys equiv_simple"}


def _scan_insert(params):
    """REAL scan insertion: swap combinational D-flops for their scan-equivalent
    master and STITCH scan chains, emitting a scan-inserted gate-level netlist
    (<top>.scan.v) — not a paper plan.

    Method (gate-level, node-aware): load the PDK Liberty (so the scan master's
    pins resolve) + the mapped netlist, flatten, and write_json. Then, in Python:
      1. find every non-scan flop of `scan_from_cell` (default sky130_fd_sc_hd__dfxtp_1);
      2. swap its master to `scan_to_cell` (default …__sdfxtp_1) — the functional
         CLK/D/Q pins are identical, so functional connectivity is untouched;
      3. balance them across `scan_chains` chains and STITCH: each flop's scan-data
         pin (SCD) ← previous flop's Q; the head flop's SCD ← a new `scan_in_<c>`
         input; the tail flop's Q → a new `scan_out_<c>` output; every flop's
         scan-enable pin (SCE) ← a single new `scan_enable` input;
      4. read the stitched JSON back through Yosys (+Liberty) and write_verilog the
         scan netlist. Stats are re-derived from the emitted netlist, not asserted.

    SRAM macros / latches / async-set-reset flops are NEVER chained (left as-is).
    Fails closed if the from-cell is absent (nothing to insert) or the netlist
    doesn't emit."""
    if not shutil.which("yosys"):
        return _cde(objective="DFT scan insertion", status="failed",
                    error="yosys not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    top = params.get("top")
    files = _stage_rtl(params)
    if not top or not files:
        return _cde(objective="DFT scan insertion", status="failed",
                    pdk_binding=binding or "none",
                    error="missing 'top' or netlist", validation={"verdict": "fail"})
    if not _is_ident(top):
        return _cde(objective="DFT scan insertion", status="failed",
                    pdk_binding=binding or "none",
                    error=f"invalid 'top' identifier: {top!r}",
                    validation={"verdict": "fail"})
    try:
        mappings = _scan_mappings(params, binding)
    except ValueError as exc:
        return _cde(objective="DFT scan insertion", status="failed",
                    pdk_binding=binding or "none", error=str(exc),
                    validation={"verdict": "fail"})
    primary_mapping = mappings[0]
    from_cell = primary_mapping["from_cell"]
    to_cell = primary_mapping["to_cell"]
    scd_pin = primary_mapping["scan_data_pin"]
    sce_pin = primary_mapping["scan_enable_pin"]
    q_pin = primary_mapping["q_pin"]
    # Top-level scan PORT names (distinct from the SCD/SCE standard-CELL pins
    # above). Default to the conventional scan_in / scan_enable / scan_out, but
    # the agent SHOULD pass the design's FROZEN contract port names (e.g.
    # scan_en) so the emitted scan netlist matches the contract EXACTLY -- a
    # tool-convention port name that differs from the frozen contract is a real
    # downstream defect (it surfaces as a boundary mismatch at synthesis/STA).
    # A single chain emits the bare port name (no _0 suffix); multiple chains
    # suffix each with its chain index.
    scan_in_port = params.get("scan_in_port", "scan_in")
    scan_out_port = params.get("scan_out_port", "scan_out")
    scan_en_port = params.get("scan_enable_port", "scan_enable")
    for _id in (scan_in_port, scan_out_port, scan_en_port):
        if not _is_ident(_id):
            return _cde(objective="DFT scan insertion", status="failed",
                        pdk_binding=binding or "none",
                        error=f"invalid identifier: {_id!r}",
                        validation={"verdict": "fail"})
    libs = _resolve_liberty(params)
    if not libs:
        return _cde(
            objective=f"DFT scan insertion of {top}", status="failed",
            pdk_binding=binding or "none",
            signoff={"missing_cell_models": True, "tool_input_error": True,
                     "remediation": "scan insertion needs the node Liberty so the "
                     "scan master's pins (SCD/SCE) resolve; supply params.liberty "
                     "or pdk_binding.references.liberty_tt.container_path."},
            error="no Liberty resolved; scan insertion requires PDK cell models "
                  "(read_liberty -lib) to emit a legal scan netlist.",
            validation={"verdict": "fail"})
    try:
        scan_contracts = [
            _validate_scan_cell_contract(
                libs, item["from_cell"], item["to_cell"],
                item["scan_data_pin"], item["scan_enable_pin"], item["q_pin"])
            for item in mappings]
        dff_inventory = _dfflibmap_inventory(libs[0])
    except (OSError, ValueError, RuntimeError) as exc:
        return _cde(
            objective=f"DFT scan insertion of {top}", status="failed",
            pdk_binding=binding or "none", error=str(exc),
            validation={"verdict": "fail",
                        "note": "scan-cell or Liberty mapping contract invalid"})
    # --- ADDITIVE, DEFAULT-OFF: hierarchical segment-chain support (DX-110) -----
    # When BOTH new params are ABSENT the two strings below are empty and every
    # generated Yosys script / code path is BYTE-IDENTICAL to the flat behavior,
    # so the already-taped-out flat macros remain exactly reproducible.
    #   macro_blackbox_files : dont_touch hard-macro stubs read as -lib (blackbox)
    #       so an SoC netlist that (correctly) still instantiates the INTENDED
    #       macros elaborates in BOTH the pre-scan elaboration AND the post-emit
    #       structural re-check (the macros resolve as intended blackboxes, not
    #       as unresolved cells / unintended blackboxes).
    #   scan_segment_terminus_net : the swappable-flop chain is one SEGMENT whose
    #       tail flop already drives this existing internal net (wired downstream
    #       to the next macro's scan_in). Do NOT retarget the public scan_out;
    #       leave it as already driven by the macro segment.
    macro_bb_files = [str(f) for f in _as_list(params.get("macro_blackbox_files"))
                      if os.path.exists(str(f))]
    macro_lib_reads = "".join(
        f"read_verilog -lib {f}\n" for f in macro_bb_files)
    segment_terminus = params.get("scan_segment_terminus_net")
    segment_mode = bool(segment_terminus)
    js = os.path.join(_WORK_DIR, "pre_scan.json")
    lib_reads = "\n".join(f"read_liberty -lib {l}" for l in libs)
    reads = "\n".join(f"read_verilog {f}" for f in files)
    pre = f"""{lib_reads}
{macro_lib_reads}{reads}
hierarchy -check -top {top}
flatten
write_json {js}
"""
    sp = os.path.join(_WORK_DIR, "pre_scan.ys")
    open(sp, "w").write(pre)
    t0 = time.time()
    _save_run_command(["yosys", "-q", "-s", sp])
    p1 = subprocess.run(["yosys", "-q", "-s", sp], capture_output=True,
                        text=True, cwd=_WORK_DIR)
    log = p1.stdout + "\n" + p1.stderr
    if p1.returncode != 0 or not os.path.exists(js):
        open(os.path.join(_OUTPUT_DIR, "scan_insert.log"), "w").write(log)
        return _cde(objective=f"DFT scan insertion of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="Yosys pre-scan elaboration failed; see scan_insert.log:\n"
                          + log[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"yosys": _yosys_version(), "log": "scan_insert.log"})

    net = json.load(open(js))
    modname = top if top in net["modules"] else next(iter(net["modules"]))
    mod = net["modules"][modname]
    cells = mod.get("cells", {})
    mod.setdefault("ports", {})
    mod.setdefault("netnames", {})

    # Highest bit id in use -> allocate fresh scan nets above it.
    max_bit = 1
    def _scan_bits(node):
        nonlocal max_bit
        if isinstance(node, list):
            for b in node:
                if isinstance(b, int) and b > max_bit:
                    max_bit = b
        elif isinstance(node, dict):
            for v in node.values():
                _scan_bits(v)
    for c in cells.values():
        _scan_bits(c.get("connections", {}))
    for pr in mod["ports"].values():
        _scan_bits(pr.get("bits", []))
    _next = [max_bit + 1]
    def _new_net():
        b = _next[0]
        _next[0] += 1
        return b

    # MUTUAL-EXCLUSION GUARD (methodology): scan insertion must happen EXACTLY
    # once. If the incoming netlist ALREADY contains scan cells (the scan_to_cell,
    # or any obvious scan-flop master), it was already scan-inserted — either by an
    # upstream synthesis-fused pass (logic-synthesis scan_insert:true) or a prior
    # DFT run. Inserting again would double-swap/re-stitch and corrupt the chains.
    # Fail closed with an actionable message rather than silently double-inserting.
    to_cells = {item["to_cell"] for item in mappings}
    _preexisting_scan = sorted(
        n for n, c in cells.items()
        if c.get("type") in to_cells
        or re.search(r"__s[a-z]*df[a-z]*tp", str(c.get("type", "")).lower()))
    if _preexisting_scan:
        open(os.path.join(_OUTPUT_DIR, "scan_insert.log"), "w").write(log)
        return _cde(
            objective=f"DFT scan insertion of {top}", status="failed",
            pdk_binding=binding or "none",
            results={"preexisting_scan_cells": len(_preexisting_scan),
                     "scan_to_cell": to_cell},
            signoff={"already_scan_inserted": True,
                     "preexisting_scan_cells": len(_preexisting_scan),
                     "scan_to_cell": to_cell,
                     "remediation": "the input netlist already contains scan cells "
                     "— scan insertion has already run (synthesis-fused "
                     "scan_insert:true, or a prior DFT insertion). Do NOT insert "
                     "twice: consume the existing scan netlist, or (if the DFT "
                     "stage owns insertion per the production methodology) disable "
                     "the synthesis-fused scan_insert and re-run synthesis to "
                     "produce a non-scan netlist for this stage."},
            error=(f"netlist already scan-inserted ({len(_preexisting_scan)} "
                   f"scan cells present); refusing to double-insert."),
            validation={"verdict": "fail",
                        "note": "already scan-inserted — mutual-exclusion guard"})

    mapping_by_from = {item["from_cell"]: item for item in mappings}
    mapping_by_cell = {
        name: mapping_by_from[cell.get("type")]
        for name, cell in cells.items() if cell.get("type") in mapping_by_from}
    scan_cells = sorted(mapping_by_cell)
    if not scan_cells:
        open(os.path.join(_OUTPUT_DIR, "scan_insert.log"), "w").write(log)
        return _cde(
            objective=f"DFT scan insertion of {top}", status="failed",
            pdk_binding=binding or "none",
            results={"scan_from_cells": sorted(mapping_by_from), "swapped": 0},
            signoff={"scan_mappings": mappings,
                     "note": "no cells of any approved from_cell found"},
            error="no approved functional flop masters in netlist; nothing to stitch.",
            validation={"verdict": "fail"})

    # SEGMENT terminus resolution (additive; no-op unless segment_mode). Find the
    # single-bit internal net named by scan_segment_terminus_net and the swappable
    # flop whose Q already drives it -- that flop is forced to the chain TAIL so
    # the emitted segment tail keeps driving the existing downstream wiring.
    terminus_bit = None
    terminus_tail_cell = None
    if segment_mode:
        _tgt = str(segment_terminus).strip().lstrip("\\")
        for _key, _nn in mod.get("netnames", {}).items():
            if str(_key).strip().lstrip("\\") == _tgt:
                _bits = _nn.get("bits", [])
                if len(_bits) == 1 and isinstance(_bits[0], int):
                    terminus_bit = _bits[0]
                break
        if terminus_bit is None:
            return _cde(
                objective=f"DFT scan insertion of {top}", status="failed",
                pdk_binding=binding or "none",
                error=f"scan_segment_terminus_net {segment_terminus!r} is not a "
                      f"single-bit net in module {modname}; cannot terminate segment.",
                validation={"verdict": "fail"})
        for _cn in scan_cells:
            _qb = cells[_cn].get("connections", {}).get(q_pin, [])
            if _qb and _qb[0] == terminus_bit:
                terminus_tail_cell = _cn
                break
        if terminus_tail_cell is None:
            return _cde(
                objective=f"DFT scan insertion of {top}", status="failed",
                pdk_binding=binding or "none",
                error=f"no swappable flop drives the segment terminus net "
                      f"{segment_terminus!r}; cannot terminate the segment.",
                validation={"verdict": "fail"})

    try:
        requested_chains = int(params.get("scan_chains", 0))
        max_chain_limit = int(params.get("max_chain_length", 800))
    except (TypeError, ValueError):
        return _cde(objective=f"DFT scan insertion of {top}", status="failed",
                    error="scan_chains and max_chain_length must be integers",
                    validation={"verdict": "fail"})
    power_domains = params.get("scan_power_domains") or {}
    descriptors = []
    for name in scan_cells:
        connection = cells[name].get("connections", {})
        reset_bits = []
        for pin in ("ARST", "SET", "CLR", "RESET_B", "RESET"):
            reset_bits.extend(connection.get(pin, []))
        descriptors.append({
            "name": name, "clock": tuple(connection.get("CLK", [])),
            "reset": tuple(reset_bits),
            "power": power_domains.get(name, "default"),
        })
    domain_count = len({(item["clock"], item["reset"], item["power"])
                        for item in descriptors})
    if requested_chains <= 0:
        requested_chains = max(
            domain_count, math.ceil(len(scan_cells) / max_chain_limit))
    try:
        chain_plan = _plan_scan_domains(
            descriptors, requested_chains, max_chain_limit)
    except ValueError as exc:
        return _cde(objective=f"DFT scan insertion of {top}", status="failed",
                    error=str(exc), validation={"verdict": "fail"})
    chains = [item["cells"] for item in chain_plan]
    n_chains = len(chains)
    if segment_mode and n_chains != 1:
        return _cde(
            objective=f"DFT scan insertion of {top}", status="failed",
            pdk_binding=binding or "none",
            error="segment insertion requires exactly one planned scan chain; "
                  f"the domain planner produced {n_chains}. Scan-exclude the "
                  "non-eligible (e.g. reset-synchronizer) flops so the segment "
                  "is single-domain.",
            validation={"verdict": "fail"})

    # Reuse frozen interface bits when the mapped design already exposes scan
    # ports.  Allocating replacement bits while leaving the original netnames
    # in place makes write_verilog alias two unrelated nets to the same port
    # name, which can create undriven chain heads and multiple-driven outputs.
    # New bits are needed only when insertion is introducing a missing port.
    _existing_en = mod["ports"].get(scan_en_port, {}).get("bits", [])
    sce_net = _existing_en[0] if _existing_en else _new_net()
    mod["ports"][scan_en_port] = {"direction": "input", "bits": [sce_net]}
    mod["netnames"][scan_en_port] = {"hide_name": 0, "bits": [sce_net],
                                     "attributes": {}}
    swapped = 0
    max_len = 0
    terminal_contracts = {}
    scan_port_names = [scan_en_port]
    for ci, chain in enumerate(chains):
        if not chain:
            continue
        # SEGMENT: force the terminus-driving flop to the chain TAIL so its Q (which
        # already drives the existing downstream net) becomes the segment output.
        if segment_mode and terminus_tail_cell in chain:
            chain = [c for c in chain if c != terminus_tail_cell] + [terminus_tail_cell]
        max_len = max(max_len, len(chain))
        _si = scan_in_port if n_chains == 1 else f"{scan_in_port}_{ci}"
        scan_port_names.append(_si)
        _existing_si = mod["ports"].get(_si, {}).get("bits", [])
        si_net = _existing_si[0] if _existing_si else _new_net()
        mod["ports"][_si] = {"direction": "input", "bits": [si_net]}
        mod["netnames"][_si] = {"hide_name": 0, "bits": [si_net],
                                "attributes": {}}
        prev_scan_src = si_net
        last_q = None
        for cname in chain:
            c = cells[cname]
            mapping = mapping_by_cell[cname]
            c["type"] = mapping["to_cell"]
            conn = c.setdefault("connections", {})
            conn[mapping["scan_data_pin"]] = [prev_scan_src]
            conn[mapping["scan_enable_pin"]] = [sce_net]
            pd = c.setdefault("port_directions", {})
            pd[mapping["scan_data_pin"]] = "input"
            pd[mapping["scan_enable_pin"]] = "input"
            qbits = conn.get(mapping["q_pin"])
            if not qbits:
                open(os.path.join(_OUTPUT_DIR, "scan_insert.log"), "w").write(log)
                return _cde(
                    objective=f"DFT scan insertion of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error=f"flop {cname!r} has no '{mapping['q_pin']}' connection; cannot "
                          f"stitch scan chain.", validation={"verdict": "fail"})
            prev_scan_src = qbits[0]
            last_q = qbits[0]
            swapped += 1
        # Tail Q -> scan-out observe port (contract name; suffixed only when >1 chain).
        if segment_mode:
            # The tail flop already drives the existing terminus net (wired
            # downstream to the next macro's scan_in). Do NOT retarget the public
            # scan_out -- it stays driven by the preserved macro segment. Assert
            # the stitch actually landed the terminus flop at the tail.
            if last_q != terminus_bit:
                return _cde(
                    objective=f"DFT scan insertion of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="segment tail Q does not equal the terminus net bit; "
                          "chain tail ordering failed.",
                    validation={"verdict": "fail"})
            # scan_out remains a compared functional output; strip it in the
            # scan-disabled equivalence projection exactly as the flat path does.
            scan_port_names.append(scan_out_port)
        else:
            _so = scan_out_port if n_chains == 1 else f"{scan_out_port}_{ci}"
            _retarget_scan_output(mod, _so, last_q)
            terminal_contracts[_so] = {
                "cell": chain[-1], **mapping_by_cell[chain[-1]]}
            scan_port_names.append(_so)

    js2 = os.path.join(_WORK_DIR, "post_scan.json")
    json.dump(net, open(js2, "w"))
    scan_v = os.path.join(_OUTPUT_DIR, f"{top}.scan.v")
    # The pre-scan JSON already carries every Liberty cell as a blackbox module
    # (write_json emitted them), so it is self-contained — do NOT read_liberty
    # again on emit or Yosys errors "Re-definition of module <scan cell>".
    post = f"""read_json {js2}
hierarchy -check -top {modname}
opt_clean
write_verilog -noattr {scan_v}
stat
"""
    sp2 = os.path.join(_WORK_DIR, "post_scan.ys")
    open(sp2, "w").write(post)
    _save_run_command(["yosys", "-q", "-s", sp2], name="run_command_emit.txt")
    p2 = subprocess.run(["yosys", "-q", "-s", sp2], capture_output=True,
                        text=True, cwd=_WORK_DIR)
    log += "\n\n=== emit ===\n" + p2.stdout + "\n" + p2.stderr
    open(os.path.join(_OUTPUT_DIR, "scan_insert.log"), "w").write(log)
    elapsed = time.time() - t0
    if p2.returncode != 0 or not os.path.exists(scan_v) \
            or os.path.getsize(scan_v) == 0:
        return _cde(objective=f"DFT scan insertion of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="scan netlist emission failed; see scan_insert.log:\n"
                          + log[-1500:], validation={"verdict": "fail"},
                    provenance={"yosys": _yosys_version(), "log": "scan_insert.log"})

    # Re-elaborate the actual emitted artifact and fail closed on precisely the
    # structural defects that downstream equivalence partitioning rejects:
    # conflicting drivers and used-but-undriven nets.
    structural = os.path.join(_WORK_DIR, "post_scan_check.ys")
    verified_json = os.path.join(_WORK_DIR, "verified_scan.json")
    structural_script = f"""{lib_reads}
{macro_lib_reads}read_verilog {scan_v}
hierarchy -check -top {modname}
check -assert
write_json {verified_json}
"""
    open(structural, "w").write(structural_script)
    p3 = subprocess.run(["yosys", "-s", structural], capture_output=True,
                        text=True, cwd=_WORK_DIR)
    structural_log = p3.stdout + "\n" + p3.stderr
    open(os.path.join(_OUTPUT_DIR, "structural_check.log"), "w").write(
        structural_log)
    if p3.returncode != 0 or not os.path.exists(verified_json):
        return _cde(
            objective=f"DFT scan insertion of {top}", status="failed",
            pdk_binding=binding or "none",
            error="emitted scan netlist failed Yosys check -assert; see "
                  "structural_check.log:\n" + structural_log[-1500:],
            validation={"verdict": "fail",
                        "note": "multiple-driver/undriven-net structural check "
                                "failed"},
            provenance={"yosys": _yosys_version(),
                        "log": "structural_check.log"})

    verified = json.load(open(verified_json))
    verified_mod = verified["modules"][modname]
    emitted = open(scan_v, "r", encoding="utf-8", errors="replace").read()
    scan_out_drivers = {}
    segment_evidence = {}
    if segment_mode:
        # SEGMENT scan_out PRESERVATION check: the public scan_out must remain a
        # single-bit output driven EXACTLY ONCE by the preserved downstream macro
        # segment (NOT hijacked onto a swapped scan-cell Q). The downstream
        # `assign scan_out = <macro segment out>` is INTENDED, not a stale alias.
        to_cells_set = {item["to_cell"] for item in mappings}
        port_bits = verified_mod.get("ports", {}).get(
            scan_out_port, {}).get("bits", [])
        drivers = []
        for cell_name, cell in verified_mod.get("cells", {}).items():
            directions = cell.get("port_directions", {})
            for pin, bits in cell.get("connections", {}).items():
                if directions.get(pin) == "output" and port_bits \
                        and port_bits[0] in bits:
                    drivers.append({"cell": cell_name, "type": cell.get("type"),
                                    "pin": pin})
        scan_out_drivers = {scan_out_port: drivers}
        seg_errors = []
        if len(port_bits) != 1:
            seg_errors.append(
                f"{scan_out_port}: expected one output bit, found {len(port_bits)}")
        if len(drivers) != 1:
            seg_errors.append(
                f"{scan_out_port}: expected exactly one driver, found {len(drivers)}")
        if any(d["type"] in to_cells_set for d in drivers):
            seg_errors.append(
                f"{scan_out_port}: hijacked onto a swapped scan-cell Q (segment "
                "scan_out must stay driven by the downstream macro)")
        segment_evidence = {
            "terminus_net": str(segment_terminus),
            "terminus_tail_cell": terminus_tail_cell,
            "scan_out_preserved_driver": drivers,
        }
        if seg_errors:
            return _cde(
                objective=f"DFT scan insertion of {top}", status="failed",
                pdk_binding=binding or "none",
                error="segment scan_out preservation check failed: "
                      + "; ".join(seg_errors),
                validation={"verdict": "fail"},
                signoff={"segment_evidence": segment_evidence,
                         "scan_out_drivers": scan_out_drivers},
                provenance={"yosys": _yosys_version(),
                            "log": "structural_check.log"})
    else:
        expected_scan_outs = (
            [scan_out_port] if n_chains == 1
            else [f"{scan_out_port}_{i}" for i in range(n_chains)])
        driver_errors = []
        for port_name in expected_scan_outs:
            port_bits = verified_mod.get("ports", {}).get(port_name, {}).get("bits", [])
            if len(port_bits) != 1:
                driver_errors.append(
                    f"{port_name}: expected one output bit, found {len(port_bits)}")
                continue
            bit = port_bits[0]
            drivers = []
            for cell_name, cell in verified_mod.get("cells", {}).items():
                directions = cell.get("port_directions", {})
                for pin, bits in cell.get("connections", {}).items():
                    if directions.get(pin) == "output" and bit in bits:
                        drivers.append({
                            "cell": cell_name,
                            "type": cell.get("type"),
                            "pin": pin,
                        })
            scan_out_drivers[port_name] = drivers
            if len(drivers) != 1:
                driver_errors.append(
                    f"{port_name}: expected one cell driver, found {len(drivers)}")
            expected = terminal_contracts[port_name]
            if len(drivers) == 1 and (drivers[0]["type"] != expected["to_cell"]
                or drivers[0]["pin"] != expected["q_pin"]):
                driver_errors.append(
                    f"{port_name}: driver is {drivers[0]['type']}."
                f"{drivers[0]['pin']}, expected {expected['to_cell']}."
                f"{expected['q_pin']}")

        stale_assigns = re.findall(
            r"(?m)^\s*assign\s+(" +
            "|".join(re.escape(name) for name in expected_scan_outs) +
            r")\s*=", emitted)
        iq_aliases = [
            name for name, netname in verified_mod.get("netnames", {}).items()
            if any(
                bit in netname.get("bits", [])
                for port_name in expected_scan_outs
                for bit in verified_mod["ports"][port_name]["bits"])
            and re.search(r"(^|[.$/])IQ(?:$|[.\[])", name, re.IGNORECASE)
        ]
        if driver_errors or stale_assigns or iq_aliases:
            details = driver_errors[:]
            if stale_assigns:
                details.append("stale continuous assignments drive: "
                               + ", ".join(sorted(set(stale_assigns))))
            if iq_aliases:
                details.append("internal IQ aliases remain: "
                               + ", ".join(sorted(iq_aliases)))
            return _cde(
                objective=f"DFT scan insertion of {top}", status="failed",
                pdk_binding=binding or "none",
                error="scan-out terminal-driver validation failed: "
                      + "; ".join(details),
                validation={"verdict": "fail",
                            "note": "scan_out must be driven exactly once by the "
                                    "terminal scan cell"},
                signoff={"scan_out_drivers": scan_out_drivers,
                         "stale_scan_out_assigns": stale_assigns,
                         "internal_iq_aliases": iq_aliases},
                provenance={"yosys": _yosys_version(),
                            "log": "structural_check.log"})

    # Re-derive the swapped-cell count from the EMITTED netlist (evidence, not
    # the in-memory count) so the report reflects what was actually written.
    emitted_by_type = {
        cell_type: len(re.findall(r"\b" + re.escape(cell_type) + r"\b", emitted))
        for cell_type in sorted(to_cells)}
    emitted_scan_cells = sum(emitted_by_type.values())
    equivalence = _prove_scan_functional_equivalence(
        json.load(open(js)), net, modname, mappings, scan_port_names,
        depth=params.get("equivalence_depth", 8))
    ok = emitted_scan_cells >= swapped and swapped > 0
    ok = ok and equivalence["proven"]
    return _cde(
        objective=f"DFT scan insertion of {top} "
                  f"({len(mappings)} approved mapping(s), {n_chains} chains)",
        status="completed", pdk_binding=binding or "none",
        results={"scan_netlist": {"value": os.path.basename(scan_v), "unit": "file"},
                 "flops_swapped": {"value": swapped, "unit": "count"},
                 "scan_chains": {"value": n_chains, "unit": "count"},
                 "max_chain_length": {"value": max_len, "unit": "count"}},
        qor={"flops_swapped": swapped, "scan_chains": n_chains,
             "max_chain_length": max_len,
             "scan_cells_in_emitted_netlist": emitted_scan_cells,
             "scan_cells_by_type": emitted_by_type},
        signoff={"scan_netlist": os.path.basename(scan_v),
                 "scan_from_cell": from_cell, "scan_to_cell": to_cell,
                 "scan_mappings": mappings,
                 "scan_cell_contracts": scan_contracts,
                 "dfflibmap_inventory": dff_inventory,
                 "chain_plan": chain_plan,
                 "segment_mode": segment_mode,
                 "segment_evidence": segment_evidence,
                 "macro_blackbox_files": macro_bb_files,
                 "scan_data_pin": scd_pin, "scan_enable_pin": sce_pin,
                 "flops_swapped": swapped, "scan_chains": n_chains,
                 "max_chain_length": max_len,
                 "scan_ports": [scan_en_port]
                 + ([scan_in_port] if n_chains == 1
                    else [f"{scan_in_port}_{i}" for i in range(n_chains)])
                 + ([scan_out_port] if n_chains == 1
                    else [f"{scan_out_port}_{i}" for i in range(n_chains)]),
                 "scan_cells_in_emitted_netlist": emitted_scan_cells,
                 "scan_cells_by_type": emitted_by_type,
                 "insertion_verified": ok,
                 "functional_equivalence": equivalence,
                 "structural_check": {
                     "verdict": "pass",
                     "method": "Yosys re-elaboration plus check -assert",
                     "multiple_drivers": 0,
                     "undriven_nets": 0,
                     "scan_out_drivers": scan_out_drivers,
                     "stale_scan_out_assigns": 0,
                     "internal_iq_aliases": 0,
                     "report": "structural_check.log"},
                 "report": "scan_insert.log"},
        inputs_ref={"files": files, "liberty": libs},
        assumptions=[
            "functional CLK/D/Q compatibility is validated against Liberty and "
            "the scan-disabled functional projection is proven sequentially "
            "equivalent with Yosys before closure",
            "SRAM macros, latches, and async-set/reset flops are NOT chained",
            "scan-cell master + SCD/SCE pin names default to sky130_fd_sc_hd; "
            "override via scan_to_cell/scan_data_pin/scan_enable_pin for another node",
            "top-level scan PORT names default to scan_in/scan_enable/scan_out "
            "(single chain drops the _N suffix); pass scan_in_port/scan_enable_port/"
            "scan_out_port to match the design's frozen contract port names exactly"],
        validation={
            "verdict": "pass" if ok else "fail",
            "note": (f"scan-inserted netlist emitted with {emitted_scan_cells} "
                     f"cells across {n_chains} domain-local chains; functional "
                     "equivalence proven"
                     if ok else "scan netlist cell count or functional equivalence "
                     "failed")},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3),
                    "log": "scan_insert.log"},
    )


def _is_flop_type(t):
    """True if a cell master is a (scan or plain) edge-triggered D flop — the
    sequential boundary we cut to build the combinational ATPG model."""
    tl = str(t).lower()
    if tl.startswith(("$dff", "$sdff", "$adff", "$_dff", "$_sdff")):
        return True
    # Liberty (scan) flop masters: match with OR without a `lib__` prefix so both
    # sky130_fd_sc_hd__sdfxtp_1 and a bare sdfxtp_1 are recognized. `*tp` = the
    # transparent/edge D-flop family (dfxtp, sdfxtp, dfrtp, sdfrtp, ...).
    return bool(re.search(r"s?df[a-z]*tp", tl) or "__dff" in tl or tl.startswith("dff"))


def _build_comb_model(net, modname, ff_d="D", ff_q="Q"):
    """Cut every flop to turn the (scan) gate netlist into a COMBINATIONAL model
    for scan ATPG: each flop's Q net becomes a pseudo-primary-INPUT (scan makes it
    controllable) and its D net a pseudo-primary-OUTPUT (scan makes it observable).
    The flop cell is removed. Mutates net in place (pass a deep copy)."""
    mod = net["modules"][modname]
    cells = mod.get("cells", {})
    mod.setdefault("ports", {})
    flops = sorted(n for n, c in cells.items() if _is_flop_type(c.get("type", "")))
    ppi = ppo = 0
    for i, fname in enumerate(flops):
        conn = cells[fname].get("connections", {})
        q = conn.get(ff_q)
        d = conn.get(ff_d)
        if q:
            mod["ports"][f"ppi_{i}"] = {"direction": "input", "bits": list(q)}
            ppi += 1
        if d:
            mod["ports"][f"ppo_{i}"] = {"direction": "output", "bits": list(d)}
            ppo += 1
        del cells[fname]
    return len(flops), ppi, ppo


def _cell_output_bits(mod):
    """Every driven net bit that is a CELL OUTPUT — the stuck-at fault checkpoints
    (collapsed to gate outputs). Uses port_directions (present because the PDK
    Liberty was loaded as -lib)."""
    bits, seen = [], set()
    for c in mod.get("cells", {}).values():
        pd = c.get("port_directions", {})
        conn = c.get("connections", {})
        for pin, direction in pd.items():
            if direction == "output":
                for b in conn.get(pin, []):
                    if isinstance(b, int) and b not in seen:
                        seen.add(b)
                        bits.append(b)
    return bits


#: `$flatten\<instance>.<generated-name>` — Yosys keeps the PRE-flatten instance
#: in the name of every cell it creates while inlining, which is the only place
#: the physical owner of a decomposition node survives.
_FLATTEN_OWNER = re.compile(r"^\$flatten\\?(?P<instance>[^.]+)\.")


def _checkpoint_owners(mod):
    """bit -> {owner_instance, owner_cell_type, driver_cell} for fault sites.

    WHY A CHECKPOINT NEEDS AN OWNER. `read_liberty` without `-lib` imports each
    standard cell's boolean FUNCTION as a network of generic `$_AND_`/`$_OR_`/
    `$_NOT_` primitives, so `flatten; techmap` DECOMPOSES every physical cell
    before fault checkpoints are enumerated. The resulting `net_bit` IDs are
    internal sub-expression nodes: measured on one design, only 16 of 655
    checkpoints resolved to a net that also exists in the physical netlist.
    Anyone later asked to grade that fault list by simulation on the real
    netlist has nothing to force for the other 97.6%.

    Worse, Yosys's bit numbering for purely-internal nets is NOT reproducible
    across separate elaborations of the identical script, so the mapping cannot
    be recovered after the fact -- it has to be captured HERE, at generation
    time, or not at all.

    `owner_instance` is None when the name carries no owner rather than being
    guessed: an unresolved owner is a stated unknown, not a silent default.
    """
    owners = {}
    for name, cell in (mod.get("cells") or {}).items():
        match = _FLATTEN_OWNER.match(str(name))
        if match:
            owner = match.group("instance").lstrip("\\")
        elif str(name).startswith("$"):
            owner = None           # generated, with no pre-flatten owner encoded
        else:
            owner = str(name).lstrip("\\")
        pd = cell.get("port_directions", {})
        conn = cell.get("connections", {})
        for pin, direction in pd.items():
            if direction != "output":
                continue
            for bit in conn.get(pin, []):
                if isinstance(bit, int) and bit not in owners:
                    owners[bit] = {
                        "owner_instance": owner,
                        "owner_cell_type": cell.get("type"),
                        "driver_cell": name,
                    }
    return owners


def _inject_saf(net, modname, bit, value):
    """Return a DEEP-COPIED netlist with a stuck-at-`value` fault forced on `bit`:
    every READER of that bit (cell input-port connections + module output ports) is
    rewired to the constant "0"/"1". The driver is left dangling (miter/opt prunes
    it). This is the faulty machine for the good-vs-faulty miter."""
    import copy
    g = copy.deepcopy(net)
    mod = g["modules"][modname]
    const = str(int(value))

    def _sub(bits):
        return [const if b == bit else b for b in bits]
    for c in mod.get("cells", {}).values():
        pd = c.get("port_directions", {})
        conn = c.get("connections", {})
        for pin, bl in list(conn.items()):
            if pd.get(pin) == "input" or (not pd and pin.upper() != "Y"):
                conn[pin] = _sub(bl)
    for pr in mod.get("ports", {}).values():
        if pr.get("direction") == "output":
            pr["bits"] = _sub(pr.get("bits", []))
    return g


def _fault_id(bit, value):
    return "net_%s_sa%d" % (bit, value)


def _write_json_artifact(name, value):
    path = os.path.join(_OUTPUT_DIR, name)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return {"path": name, **_hash_input_file(path)}


def _parse_sat_pattern(output):
    pattern = {}
    for match in re.finditer(
            r"^\s*\\?(in_[A-Za-z_][A-Za-z0-9_$.[\]]*)\s+(-?\d+)\s+",
            output, re.M):
        pattern[match.group(1)] = match.group(2)
    return pattern


def _pattern_constraints(pattern):
    commands = []
    for name, value in sorted((pattern or {}).items()):
        if not re.fullmatch(r"in_[A-Za-z_][A-Za-z0-9_$.[\]]*", name):
            raise ValueError("unsafe ATPG pattern signal: %r" % name)
        if not re.fullmatch(r"-?\d+", str(value)):
            raise ValueError("unsafe ATPG pattern value: %r" % value)
        commands.append("-set \\%s %s" % (name, value))
    return " ".join(commands)


def _write_fault_miter(comb, modname, gold_js, bit, value, suffix):
    gate = _inject_saf(comb, modname, bit, value)
    gate = {"modules": {modname: gate["modules"][modname]}}
    gate_js = os.path.join(_WORK_DIR, "atpg_gate_%s.json" % suffix)
    json.dump(gate, open(gate_js, "w"))
    return gate_js


# ---------------------------------------------------------------------------
# PATTERN GRADING
# ---------------------------------------------------------------------------
# DETECTION AND GRADING ARE DIFFERENT PROBLEMS. Detection asks "does an input
# assignment exist that makes this fault visible?" -- an open search, and SAT is
# the right tool. GRADING asks "does THIS already-known, fully-specified pattern
# make this fault visible?" -- zero free variables, a deterministic Boolean
# evaluation. Solving it with a full miter SAT call is architecturally wrong,
# and the cost showed it: measured at ~3.97 SAT calls/s against a ~1.9M-call
# grading obligation, i.e. ~133 hours, so the tool simply SKIPPED grading above
# `max_pattern_grade_faults` (default 64) and every design of nontrivial size
# was capped at `pass_with_caveats` with an honest but permanently open
# `grading` residual.
#
# The simulator below computes the identical answer by two-valued propagation:
# evaluate the good machine once per pattern, then for each fault propagate ONLY
# the affected cone in topological order. It is used automatically above the SAT
# ceiling and is CROSS-VALIDATED against the native SAT loop on a deterministic
# sample in the same run -- a substitute method is never trusted unverified, and
# any mismatch leaves the grading obligation OPEN rather than closing it.

class _UngradableModel(Exception):
    """The model cannot be two-valued simulated, so grading must fail closed."""


_CONST0, _CONST1 = -1, -2

_GATE_FUNCS = {
    "$_BUF_":    (("A",),               lambda v: v[0]),
    "$_NOT_":    (("A",),               lambda v: v[0] ^ 1),
    "$_AND_":    (("A", "B"),           lambda v: v[0] & v[1]),
    "$_NAND_":   (("A", "B"),           lambda v: (v[0] & v[1]) ^ 1),
    "$_OR_":     (("A", "B"),           lambda v: v[0] | v[1]),
    "$_NOR_":    (("A", "B"),           lambda v: (v[0] | v[1]) ^ 1),
    "$_XOR_":    (("A", "B"),           lambda v: v[0] ^ v[1]),
    "$_XNOR_":   (("A", "B"),           lambda v: v[0] ^ v[1] ^ 1),
    "$_ANDNOT_": (("A", "B"),           lambda v: v[0] & (v[1] ^ 1)),
    "$_ORNOT_":  (("A", "B"),           lambda v: v[0] | (v[1] ^ 1)),
    "$_MUX_":    (("A", "B", "S"),      lambda v: v[1] if v[2] else v[0]),
    "$_NMUX_":   (("A", "B", "S"),      lambda v: (v[1] if v[2] else v[0]) ^ 1),
    "$_AOI3_":   (("A", "B", "C"),      lambda v: ((v[0] & v[1]) | v[2]) ^ 1),
    "$_OAI3_":   (("A", "B", "C"),      lambda v: ((v[0] | v[1]) & v[2]) ^ 1),
    "$_AOI4_":   (("A", "B", "C", "D"),
                  lambda v: ((v[0] & v[1]) | (v[2] & v[3])) ^ 1),
    "$_OAI4_":   (("A", "B", "C", "D"),
                  lambda v: ((v[0] | v[1]) & (v[2] | v[3])) ^ 1),
}


def _norm_bit(bit):
    if isinstance(bit, int):
        return bit
    text = str(bit)
    if text == "0":
        return _CONST0
    if text == "1":
        return _CONST1
    raise _UngradableModel(
        "net carries the non-binary state %r; a two-valued simulation would "
        "have to invent a value for it" % text)


def _build_eval_plan(mod):
    """Compile the combinational model into a topologically ordered eval plan."""
    cells, driver, consumers = [], {}, {}
    for name, cell in (mod.get("cells") or {}).items():
        spec = _GATE_FUNCS.get(cell.get("type"))
        if spec is None:
            raise _UngradableModel(
                "cell %s has type %r, which this simulator does not evaluate"
                % (name, cell.get("type")))
        ports, func = spec
        conn = cell.get("connections") or {}
        inputs = []
        for port in ports:
            bits = conn.get(port)
            if not bits:
                raise _UngradableModel(
                    "cell %s (%s) has no %s connection" % (name, cell["type"], port))
            inputs.append(_norm_bit(bits[0]))
        out = conn.get("Y")
        if not out:
            raise _UngradableModel("cell %s (%s) has no Y output" % (name, cell["type"]))
        out_bit = _norm_bit(out[0])
        if out_bit < 0:
            raise _UngradableModel("cell %s drives a constant" % name)
        if out_bit in driver:
            raise _UngradableModel("net bit %d has more than one driver" % out_bit)
        index = len(cells)
        driver[out_bit] = index
        cells.append((name, cell["type"], tuple(inputs), out_bit, func))
        for bit in inputs:
            consumers.setdefault(bit, []).append(index)

    indegree = [sum(1 for bit in cell[2] if bit in driver) for cell in cells]
    order, ready = [], [i for i, d in enumerate(indegree) if d == 0]
    while ready:
        index = ready.pop()
        order.append(index)
        for consumer in consumers.get(cells[index][3], ()):
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                ready.append(consumer)
    if len(order) != len(cells):
        raise _UngradableModel(
            "combinational loop: %d cell(s) never became evaluable"
            % (len(cells) - len(order)))
    rank = [0] * len(cells)
    for position, index in enumerate(order):
        rank[index] = position

    ports = mod.get("ports") or {}
    input_ports, input_bits, observable = {}, set(), []
    for name, port in ports.items():
        bits = [_norm_bit(b) for b in port.get("bits", [])]
        if port.get("direction") in ("input", "inout"):
            input_ports[name.lstrip("\\")] = bits
            input_bits.update(b for b in bits if b >= 0)
        if port.get("direction") in ("output", "inout"):
            observable.extend(b for b in bits if b >= 0)
    undriven = {bit for cell in cells for bit in cell[2]
                if bit >= 0 and bit not in driver}
    unreachable = undriven - input_bits
    if unreachable:
        raise _UngradableModel(
            "%d net bit(s) are neither driven nor reachable from an input port, "
            "so no pattern can control them" % len(unreachable))
    return {
        "cells": cells, "order": order, "rank": rank, "consumers": consumers,
        "input_ports": input_ports, "primary_input_bits": sorted(undriven),
        "observable": sorted(set(observable)),
    }


_PATTERN_BIT = re.compile(r"^(?P<port>.+)\[(?P<index>\d+)\]$")


def _pattern_values(plan, pattern):
    """Seed the model from a SAT pattern. FAIL CLOSED on an unspecified input:
    defaulting one would grade a pattern the solver never actually produced."""
    values = {_CONST0: 0, _CONST1: 1}
    for raw, value in (pattern or {}).items():
        name = raw[3:] if str(raw).startswith("in_") else str(raw)
        bits = plan["input_ports"].get(name)
        if bits is None:
            match = _PATTERN_BIT.match(name)
            base = plan["input_ports"].get(match.group("port")) if match else None
            if base is None:
                raise _UngradableModel(
                    "pattern names %r, which is not an input of this model" % raw)
            index = int(match.group("index"))
            if index >= len(base):
                raise _UngradableModel("pattern names out-of-range bit %r" % raw)
            bits = [base[index]]
        number = int(value)
        for offset, bit in enumerate(bits):
            if bit >= 0:
                values[bit] = (number >> offset) & 1
    missing = [bit for bit in plan["primary_input_bits"] if bit not in values]
    if missing:
        raise _UngradableModel(
            "pattern leaves %d primary input bit(s) unspecified" % len(missing))
    return values


def _simulate_good(plan, values):
    cells = plan["cells"]
    for index in plan["order"]:
        _, _, inputs, out, func = cells[index]
        values[out] = func([values[bit] for bit in inputs])
    return values


def _fault_visible(plan, good, bit, value):
    """True when stuck-at-`value` on `bit` changes an observable under `good`.

    Event-driven over the affected cone only, in topological rank order, so each
    cell is evaluated at most once. Matches `_inject_saf` exactly: the fault
    forces what every READER sees, and the dangling driver is not re-applied.
    """
    if good.get(bit) == value:
        return False                       # pattern does not excite the fault
    cells, rank, consumers = plan["cells"], plan["rank"], plan["consumers"]
    delta = {bit: value}
    heap, queued = [], set()
    for index in consumers.get(bit, ()):
        if index not in queued:
            queued.add(index)
            heapq.heappush(heap, (rank[index], index))
    while heap:
        _, index = heapq.heappop(heap)
        queued.discard(index)
        _, _, inputs, out, func = cells[index]
        if out == bit:
            continue                       # the faulted net is held at `value`
        new = func([delta[b] if b in delta else good[b] for b in inputs])
        if new != (delta[out] if out in delta else good[out]):
            delta[out] = new
            for consumer in consumers.get(out, ()):
                if consumer not in queued:
                    queued.add(consumer)
                    heapq.heappush(heap, (rank[consumer], consumer))
    return any(bit_ in delta and delta[bit_] != good[bit_]
               for bit_ in plan["observable"])


def _sat_grade(comb, modname, gold_js, constraints, bit, value, suffix,
               sat_timeout):
    """Native SAT grading of ONE (pattern, fault) pair. Returns True/False, or
    None when the solver gave neither verdict (never silently 'not detected')."""
    gate_js = _write_fault_miter(comb, modname, gold_js, bit, value, suffix)
    script = os.path.join(_WORK_DIR, "atpg_grade.ys")
    open(script, "w").write(
        f"read_json {gold_js}\nrename {modname} gold\n"
        f"read_json {gate_js}\nrename {modname} gate\n"
        "miter -equiv -flatten gold gate miter\n"
        f"sat {constraints} -set trigger 1 -set-def trigger "
        f"-timeout {sat_timeout} miter\n")
    try:
        proc = subprocess.run(["yosys", "-s", script], capture_output=True,
                              text=True, cwd=_WORK_DIR, timeout=sat_timeout + 15)
    except subprocess.TimeoutExpired:
        return None
    output = (proc.stdout + proc.stderr).lower()
    if "model found" in output and "no model found" not in output:
        return True
    if "no model found" in output or not proc.returncode:
        return False
    return None


def _grade_by_simulation(comb, modname, gold_js, graded_patterns, faults,
                         sat_timeout, crossvalidation_patterns=2,
                         crossvalidation_faults=24):
    """Grade every (pattern, fault) pair by simulation, then PROVE the method.

    Returns `(record, aborted)`. `record["complete"]` is True only when every
    pair was graded AND the cross-validation sample matched the native SAT loop
    exactly -- a disagreement leaves the obligation open instead of closing it
    on the strength of the faster method.
    """
    mod = comb["modules"][modname]
    started = time.time()
    plan = _build_eval_plan(mod)
    calls = 0
    good_by_pattern = {}
    for index, item in enumerate(graded_patterns):
        pattern = item.get("pattern") or {}
        if not pattern:
            raise _UngradableModel("pattern %d is empty" % index)
        good = _simulate_good(plan, _pattern_values(plan, pattern))
        good_by_pattern[index] = good
        detected = set(item.get("detects", []))
        for bit, value in faults:
            name = _fault_id(bit, value)
            if name in detected:
                continue
            calls += 1
            if _fault_visible(plan, good, bit, value):
                detected.add(name)
        item["detects"] = sorted(detected)

    trials, mismatches = [], []
    for index in sorted(good_by_pattern)[:crossvalidation_patterns]:
        item = graded_patterns[index]
        constraints = _pattern_constraints(item.get("pattern") or {})
        for bit, value in faults[:crossvalidation_faults]:
            reference = _sat_grade(comb, modname, gold_js, constraints, bit,
                                   value, "xval_%d_%s" % (index, _fault_id(bit, value)),
                                   sat_timeout)
            if reference is None:
                continue               # inconclusive solver run proves nothing
            observed = _fault_visible(plan, good_by_pattern[index], bit, value)
            trials.append({"pattern": index, "fault": _fault_id(bit, value),
                           "sat": reference, "simulation": observed})
            if reference != observed:
                mismatches.append(trials[-1])
    crossvalidation = {
        "trials": len(trials), "mismatches": len(mismatches),
        "exact_match": bool(trials) and not mismatches,
        "disagreements": mismatches[:16],
        "basis": ("every trial re-graded through the native SAT loop on the "
                  "same miter the detection sweep used"),
    }
    record = {
        "method": "two_valued_boolean_propagation",
        "complete": crossvalidation["exact_match"],
        "calls": calls,
        "elapsed_s": round(time.time() - started, 3),
        "crossvalidation": crossvalidation,
        "note": ("Grading has zero free variables, so it is a deterministic "
                 "Boolean evaluation rather than a search. Cross-validated "
                 "against the native SAT loop in this same run: an unverified "
                 "substitute method never closes the obligation."),
    }
    if not trials:
        record["complete"] = False
        record["note"] += (" NO cross-validation trial reached a definite SAT "
                           "verdict, so the method is unproven on this design "
                           "and the grading obligation stays OPEN.")
    aborted = ([] if record["complete"] else
               [{"reason": "simulation grading not cross-validated",
                 "mismatches": len(mismatches)}])
    return record, aborted


def _blackbox_sequential_masters(lib_reads, reads, top):
    """Port-only blackbox stubs for every SEQUENTIAL master the design uses.

    Discovered rather than hard-coded: a probe elaboration (no flatten) reports
    the modules actually instantiated, `_is_flop_type` selects the sequential
    ones, and their stubs are generated from their own declared ports. A probe
    that cannot run returns no stubs and says why -- the ATPG run still proceeds
    on the un-protected recipe, with the reason recorded, rather than failing on
    an optimization.
    """
    probe_js = os.path.join(_WORK_DIR, "atpg_probe.json")
    script = os.path.join(_WORK_DIR, "atpg_probe.ys")
    open(script, "w").write(
        f"{lib_reads}\n{reads}\nhierarchy -check -top {top}\n"
        f"write_json {probe_js}\n")
    try:
        proc = subprocess.run(["yosys", "-q", "-s", script], capture_output=True,
                              text=True, cwd=_WORK_DIR, timeout=900)
    except (OSError, subprocess.SubprocessError) as error:
        return {}, "sequential-master probe did not run: %s" % error
    if proc.returncode != 0 or not os.path.exists(probe_js):
        return {}, ("sequential-master probe elaboration failed; flop cut points "
                    "may land on decomposed internal nodes")
    try:
        probe = json.load(open(probe_js))
    except (OSError, ValueError) as error:
        return {}, "sequential-master probe JSON unreadable: %s" % error

    modules = probe.get("modules") or {}
    instantiated = {
        cell.get("type") for module in modules.values()
        for cell in (module.get("cells") or {}).values()
    }
    stubs, named = [], []
    for name in sorted(t for t in instantiated if t and _is_flop_type(t)):
        module = modules.get(name)
        if not module or not _is_ident(name):
            continue
        ports = []
        for port_name, port in sorted((module.get("ports") or {}).items()):
            direction = port.get("direction")
            width = len(port.get("bits") or [])
            if direction not in ("input", "output", "inout") or not width \
                    or not _is_ident(port_name):
                ports = []
                break
            span = "" if width == 1 else "[%d:0] " % (width - 1)
            ports.append("  %s %s%s" % (direction, span, port_name))
        if not ports:
            continue
        named.append(name)
        stubs.append("(* blackbox *)\nmodule %s (\n%s\n);\nendmodule\n"
                     % (name, ",\n".join(ports)))
    if not stubs:
        return {}, ("no sequential master was blackboxed (none instantiated, or "
                    "none had a usable port declaration)")
    stub_file = os.path.join(_WORK_DIR, "atpg_seq_blackbox.v")
    open(stub_file, "w").write("\n".join(stubs))
    return ({"modules": named, "stub_file": stub_file},
            "blackboxed %d sequential master(s) before flatten: %s"
            % (len(named), ", ".join(named)))


def _fault_atpg(params):
    """REAL scan-aware combinational stuck-at ATPG with per-fault formal pattern
    generation. Cuts flops to a combinational model (scan controllability/
    observability), enumerates stuck-at faults on gate-output checkpoints, and for
    each fault builds a good-vs-faulty MITER and SAT-solves it: a counterexample is
    a TEST PATTERN that provably propagates the fault to an observable point (formal
    detection proof); UNSAT ⇒ the fault is redundant/undetectable. Reports stuck-at
    fault coverage + the pattern set.

    scope=block (default): fresh ATPG on the block's own scan netlist.
    scope=top: HIERARCHICAL — sub-macros are blackboxes so only top-GLUE logic is
    faulted here; block fault coverage is AGGREGATED from the sub-block DFT results
    (params.block_fault_coverages=[{design,fault_coverage_pct,faults}]); boundary-
    scan (JTAG/1149.1) + MBIST targets are recorded as top-only test structures."""
    if not shutil.which("yosys"):
        return _cde(objective="fault ATPG", status="failed",
                    error="yosys not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    top = params.get("top")
    files = _stage_rtl(params)
    scope = str(params.get("scope", "block")).strip().lower()
    if not top or not files:
        return _cde(objective="fault ATPG", status="failed", pdk_binding=binding or "none",
                    error="missing 'top' or netlist", validation={"verdict": "fail"})
    if not _is_ident(top):
        return _cde(objective="fault ATPG", status="failed", pdk_binding=binding or "none",
                    error=f"invalid 'top' identifier: {top!r}", validation={"verdict": "fail"})
    libs = _resolve_liberty(params)
    # ATPG needs FUNCTIONAL cells (SAT must know each gate's logic), so read the
    # Liberty in FULL (no -lib) to import cell functions, then flatten + techmap so
    # the mapped std cells become $-primitives the SAT solver can import. (A
    # blackbox -lib read leaves cells functionless and SAT fails to import them.)
    lib_reads = "\n".join(
        f"read_liberty -ignore_miss_func -ignore_miss_data_latch {l}"
        for l in libs)
    reads = "\n".join(f"read_verilog {f}" for f in files)
    js = os.path.join(_WORK_DIR, "atpg_net.json")
    t0 = time.time()
    # PROTECT THE FLOP BOUNDARY BEFORE FLATTENING. The full Liberty read that
    # makes SAT possible also imports each SCAN FLOP's internal D/SCD/SCE mux as
    # ordinary boolean logic, so `flatten` decomposes the flop too and the
    # pseudo-PI/pseudo-PO cut lands on a synthetic node with no wire in the real
    # netlist. Measured: that contaminated one design's untestable count with
    # redundancies inside the flop's OWN mux (331 -> 70 once the flop was
    # blackboxed) and moved every cut point off its named D/Q net. So sequential
    # masters are replaced by port-only blackbox stubs first; `_build_comb_model`
    # then cuts exactly the real D/Q nets. Combinational cells still decompose
    # (that is what SAT needs) -- see `_checkpoint_owners` for how those
    # checkpoints keep their physical owner.
    seq_blackboxes, seq_note = _blackbox_sequential_masters(
        lib_reads, reads, top)
    stub_read = (f"read_verilog {seq_blackboxes['stub_file']}\n"
                 if seq_blackboxes.get("stub_file") else "")
    delete_seq = "".join(
        f"delete {name}\n" for name in seq_blackboxes.get("modules", []))
    open(os.path.join(_WORK_DIR, "atpg_pre.ys"), "w").write(
        f"{lib_reads}\n{reads}\n{delete_seq}{stub_read}"
        f"hierarchy -check -top {top}\n"
        f"flatten\ntechmap\nopt -purge\nwrite_json {js}\n")
    p1 = subprocess.run(["yosys", "-q", "-s", os.path.join(_WORK_DIR, "atpg_pre.ys")],
                        capture_output=True, text=True, cwd=_WORK_DIR)
    if p1.returncode != 0 or not os.path.exists(js):
        open(os.path.join(_OUTPUT_DIR, "atpg.log"), "w").write(p1.stdout + p1.stderr)
        return _cde(objective=f"fault ATPG of {top}", status="failed", pdk_binding=binding or "none",
                    error="Yosys elaboration failed; see atpg.log:\n" + (p1.stderr or "")[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"yosys": _yosys_version(), "log": "atpg.log"})
    net = json.load(open(js))
    modname = top if top in net["modules"] else next(iter(net["modules"]))
    import copy as _copy
    comb = _copy.deepcopy(net)
    checkpoint_owners = _checkpoint_owners(net["modules"][modname])
    n_flops, n_ppi, n_ppo = _build_comb_model(comb, modname)
    mod = comb["modules"][modname]
    gold_js = os.path.join(_WORK_DIR, "atpg_gold.json")
    json.dump(comb, open(gold_js, "w"))
    fault_bits = _cell_output_bits(mod)
    all_faults = [(b, v) for b in sorted(fault_bits) for v in (0, 1)]
    total_faults = len(all_faults)
    try:
        faults, selection = _select_faults(all_faults, params)
    except ValueError as exc:
        return _cde(objective=f"fault ATPG of {top}", status="failed",
                    error=str(exc), validation={"verdict": "fail"})
    sampled = selection["mode"] == "diagnostic_sample"
    detectable = 0
    redundant = []      # SAT-PROVEN untestable (UNSAT miter) — creditable in test coverage
    aborted = []        # timeout / tool error / unparseable — NOT creditable (undetected)
    patterns = []
    try:
        sat_timeout = int(params.get("sat_timeout_s", 60))
    except (TypeError, ValueError):
        sat_timeout = 60
    for (bit, val) in faults:
        fault_name = _fault_id(bit, val)
        gate_js = _write_fault_miter(
            comb, modname, gold_js, bit, val, fault_name)
        sc = os.path.join(_WORK_DIR, "atpg_miter.ys")
        witness = os.path.join(_OUTPUT_DIR, "atpg_%s.vcd" % fault_name)
        open(sc, "w").write(
            f"read_json {gold_js}\nrename {modname} gold\n"
            f"read_json {gate_js}\nrename {modname} gate\n"
            f"miter -equiv -flatten gold gate miter\n"
            f"sat -enable_undef -set-def-inputs -max_undef "
            f"-prove trigger 0 -show-inputs -timeout {sat_timeout} "
            f"-dump_vcd {witness} miter\n")
        # NOTE: no -q — yosys -q suppresses the SAT result line we must parse.
        try:
            ps = subprocess.run(["yosys", "-s", sc], capture_output=True, text=True,
                                cwd=_WORK_DIR, timeout=sat_timeout + 15)
        except subprocess.TimeoutExpired:
            aborted.append({"net_bit": bit, "stuck_at": val, "reason": "sat_timeout"})
            continue
        out = ps.stdout + ps.stderr
        low = out.lower()
        # Three-way classification (production signoff distinction):
        #   detected  = SAT found a model  -> "SAT proof finished - model found: FAIL!"
        #   redundant = SAT proved UNSAT    -> "no model found" / "SUCCESS!" (provably untestable)
        #   aborted   = tool error / nonzero rc with neither verdict -> NOT credited
        is_detect = ("fail!" in low) or ("model found" in low and "no model found" not in low)
        is_redundant = (("success!" in low) or ("no model found" in low)) and not is_detect
        if is_detect:
            detectable += 1
            pat = _parse_sat_pattern(out)
            patterns.append({
                "fault": {"id": fault_name, "net_bit": bit, "stuck_at": val},
                "pattern": pat or None, "detects": [fault_name],
                "witness": (os.path.basename(witness)
                            if os.path.isfile(witness) else None)})
        elif is_redundant:
            redundant.append({"net_bit": bit, "stuck_at": val,
                              "reason": "ATPG-redundant (miter UNSAT — no pattern can "
                              "propagate this fault to an observable point)"})
        else:
            aborted.append({"net_bit": bit, "stuck_at": val,
                            "reason": "inconclusive (rc=%d; neither SAT model nor UNSAT "
                            "proof parsed)" % ps.returncode})
    # Merge identical cubes, then grade each unique cube against every selected
    # fault. Large populations must be split into deterministic shards; one shard
    # is never allowed to close signoff by itself.
    cubes = {}
    for item in patterns:
        key = tuple(sorted((item.get("pattern") or {}).items()))
        if key not in cubes:
            cubes[key] = dict(item, detects=[])
        cubes[key]["detects"].extend(item["detects"])
    graded_patterns = list(cubes.values())
    try:
        grade_limit = int(params.get("max_pattern_grade_faults", 64))
    except (TypeError, ValueError):
        grade_limit = 64
    method = str(params.get("pattern_grading_method", "auto")).strip().lower()
    if method not in ("auto", "sat", "simulation", "none"):
        method = "auto"
    if method == "auto":
        method = "sat" if len(faults) <= grade_limit else "simulation"
    grading_complete = False
    grading_aborted = []
    grading_record = {"method": method, "population_limit": grade_limit,
                      "faults": len(faults)}
    grading_warning = ""
    if method == "sat" and len(faults) > grade_limit:
        # NEVER let a default silently delete an obligation. The old behaviour
        # skipped grading here with nothing in the log to say why.
        grading_warning = (
            "GRADING SKIPPED: %d fault(s) exceed max_pattern_grade_faults=%d. "
            "The pattern SET was NOT certified minimal/complete; only per-fault "
            "DETECTION was proven. Raise max_pattern_grade_faults to attempt "
            "the O(patterns x faults) SAT loop (measured ~3.97 calls/s), or set "
            "pattern_grading_method=simulation for the cross-validated "
            "two-valued path.\n" % (len(faults), grade_limit))
        grading_record["skipped_reason"] = grading_warning.strip()
    elif method == "sat":
        grading_complete = True
        for pattern_index, item in enumerate(graded_patterns):
            pattern = item.get("pattern") or {}
            if not pattern:
                grading_aborted.append({"pattern": pattern_index,
                                        "reason": "empty SAT pattern"})
                continue
            constraints = _pattern_constraints(pattern)
            detected = set(item.get("detects", []))
            for bit, value in faults:
                name = _fault_id(bit, value)
                if name in detected:
                    continue
                graded = _sat_grade(
                    comb, modname, gold_js, constraints, bit, value,
                    "grade_%d_%s" % (pattern_index, name), sat_timeout)
                if graded is True:
                    detected.add(name)
                elif graded is None:
                    grading_aborted.append({"pattern": pattern_index,
                                            "fault": name,
                                            "reason": "grading_inconclusive"})
            item["detects"] = sorted(detected)
    elif method == "simulation":
        try:
            simulation_record, grading_aborted = _grade_by_simulation(
                comb, modname, gold_js, graded_patterns, faults, sat_timeout)
            grading_record.update(simulation_record)
            grading_complete = simulation_record["complete"]
        except _UngradableModel as error:
            grading_record["ungradable_reason"] = str(error)
            grading_aborted = [{"reason": "model not two-valued simulatable",
                                "detail": str(error)}]
            grading_warning = (
                "GRADING NOT RUN: the combinational model cannot be two-valued "
                "simulated (%s). The pattern SET was NOT certified.\n" % error)
    else:
        grading_record["skipped_reason"] = (
            "pattern_grading_method=none; grading was not attempted and the "
            "pattern set is NOT certified minimal/complete")
    if grading_aborted:
        grading_complete = False
    grading_record["complete"] = grading_complete
    compacted_patterns = _compact_patterns(graded_patterns)
    n_tested = len(faults)
    n_untestable = len(redundant)
    n_aborted = len(aborted)
    # Fault coverage: detected / ALL tested faults (untestable + aborted count against it).
    coverage = round(100.0 * detectable / n_tested, 2) if n_tested else 0.0
    # Test coverage (the SIGNOFF metric): detected / TESTABLE faults, crediting only
    # SAT-PROVEN-untestable (redundant) faults — aborted faults are NOT credited (they
    # are unproven and remain in the denominator).
    testable = n_tested - n_untestable
    test_coverage = round(100.0 * detectable / testable, 2) if testable else (
        100.0 if (n_tested and n_aborted == 0) else 0.0)
    elapsed = time.time() - t0
    block_covs = params.get("block_fault_coverages") or []
    agg = None
    if scope == "top" and block_covs:
        num = test_coverage * testable
        den = float(testable)
        for b in block_covs:
            try:
                cov = b.get("test_coverage_pct", b.get("fault_coverage_pct"))
                w = float(b.get("testable", b.get("faults", 1)))
                num += float(cov) * w
                den += w
            except (TypeError, ValueError):
                continue
        agg = round(num / den, 2) if den else test_coverage
    top_structs = {}
    if scope == "top":
        top_structs = {
            "boundary_scan": bool(params.get("boundary_scan")),
            "mbist": bool(params.get("mbist")),
            "pattern_retargeting": "block ATPG patterns retargeted through top scan "
            "access; only top-glue logic freshly ATPG'd here",
            "aggregated_chip_test_coverage_pct": agg,
            "sub_blocks_aggregated": len(block_covs)}
    goal = _coverage_target(params)
    # SIGNOFF metric = TEST coverage (crediting SAT-proven-untestable faults);
    # aborted faults are unproven, so a nonzero abort count blocks a clean PASS.
    driving = agg if (scope == "top" and agg is not None) else test_coverage
    incomplete_selection = selection["mode"] != "exhaustive"
    verdict = _atpg_verdict(
        driving, goal, sampled or incomplete_selection or not grading_complete,
        n_aborted + len(grading_aborted))
    fault_records = ([{"id": _fault_id(bit, value), "net_bit": bit,
                       "stuck_at": value,
                       **checkpoint_owners.get(bit, {
                           "owner_instance": None, "owner_cell_type": None,
                           "driver_cell": None})}
                      for bit, value in faults])
    fault_artifact = _write_json_artifact("atpg_faults.json", fault_records)
    pattern_artifact = _write_json_artifact("atpg_patterns.json", patterns)
    compacted_artifact = _write_json_artifact(
        "atpg_patterns_compacted.json", compacted_patterns)
    unresolved_owners = sum(
        1 for record in fault_records if not record.get("owner_instance"))
    open(os.path.join(_OUTPUT_DIR, "atpg.log"), "w").write(
        grading_warning +
        (seq_note + "\n" if seq_note else "") +
        f"scan ATPG: scope={scope} flops_cut={n_flops} faults_tested={n_tested}/"
        f"{total_faults} detected={detectable} untestable={n_untestable} "
        f"aborted={n_aborted} fault_cov={coverage}% test_cov={test_coverage}% "
        f"aggregated={agg}\n"
        f"pattern grading: method={grading_record.get('method')} "
        f"complete={grading_complete} calls={grading_record.get('calls')}\n"
        f"fault checkpoints without a resolved physical owner: "
        f"{unresolved_owners}/{len(fault_records)}\n")
    return _cde(
        objective=f"scan stuck-at ATPG of {top} (scope={scope})",
        status="completed", pdk_binding=binding or "none",
        results={"test_coverage": {"value": driving, "unit": "percent"},
                 "fault_coverage": {"value": coverage, "unit": "percent"},
                 "test_patterns": {"value": len(patterns), "unit": "count"},
                 "faults_tested": {"value": n_tested, "unit": "count"},
                 "untestable_faults": {"value": n_untestable, "unit": "count"},
                 "aborted_faults": {"value": n_aborted, "unit": "count"}},
        qor={"scope": scope, "top_glue_test_coverage_pct": test_coverage,
             "top_glue_fault_coverage_pct": coverage,
             "aggregated_chip_test_coverage_pct": agg,
             "faults_tested": n_tested, "faults_total_population": total_faults,
             "sampled": sampled, "detectable": detectable,
             "testable": testable, "untestable": n_untestable, "aborted": n_aborted,
             "flops_cut": n_flops, "pseudo_pi": n_ppi, "pseudo_po": n_ppo,
             "coverage_target_pct": goal},
        signoff={"test_coverage_pct": driving, "fault_coverage_pct": coverage,
                 "coverage_target_pct": goal, "coverage_metric": "test_coverage "
                 "(detected / testable; SAT-proven-untestable faults credited, "
                 "aborted faults NOT credited)",
                 "scope": scope, "faults_tested": n_tested, "testable_faults": testable,
                 "faults_total_population": total_faults, "sampled_fault_set": sampled,
                 "fault_selection": selection,
                 "pattern_grading": {
                     **grading_record,
                     "complete": grading_complete,
                     "population_limit": grade_limit,
                     "aborted": grading_aborted[:128],
                     "aborted_count": len(grading_aborted)},
                 "fault_checkpoint_granularity": {
                     "class": "descriptive",
                     "basis": "yosys_pre_flatten_instance_tag",
                     "sequential_masters_blackboxed": list(
                         seq_blackboxes.get("modules", [])),
                     "sequential_blackbox_note": seq_note,
                     "checkpoints_without_physical_owner": unresolved_owners,
                     "note": ("Checkpoints are enumerated on the DECOMPOSED "
                              "model (a full Liberty read is what lets SAT see "
                              "each cell's function), so a SAT fault count is "
                              "finer-grained than a physical gate-output count "
                              "and the two must never be equated. Each fault "
                              "carries owner_instance, the PRE-decomposition "
                              "cell it belongs to, because Yosys bit numbering "
                              "for internal nets is not reproducible across "
                              "elaborations and cannot be recovered later.")},
                 "detectable": detectable,
                 "untestable_faults": redundant[:128],
                 "untestable_fault_count": n_untestable,
                 "aborted_faults": aborted[:128], "aborted_fault_count": n_aborted,
                 "fault_model": "stuck-at (single); transition/at-speed (LOC/LOS) is "
                 "the documented delay-fault extension",
                 "test_patterns": patterns[:64],
                 "pattern_count": len(patterns),
                 "compacted_pattern_count": len(compacted_patterns),
                 "fault_artifact": fault_artifact,
                 "pattern_artifact": pattern_artifact,
                 "compacted_pattern_artifact": compacted_artifact,
                 "scan_model": "FULL-SCAN flop-cut "
                 "combinational (Q=pseudo-PI, D=pseudo-PO); per-fault good-vs-faulty "
                 "miter SAT — small-block estimator/redundancy identifier, not a "
                 "production compression ATPG engine",
                 "top_test_structures": top_structs or None, "report": "atpg.log"},
        inputs_ref={"files": files, "liberty": libs},
        assumptions=[
            "FULL-SCAN scan-aware combinational stuck-at ATPG: flops cut so scan makes "
            "flop state a pseudo-PI (controllable) + pseudo-PO (observable); faults are "
            "gate-output stuck-at checkpoints; each detected fault carries a SAT-proven "
            "test pattern (a miter counterexample = formal detection proof); each "
            "untestable fault carries a SAT UNSAT redundancy proof",
            "SIGNOFF metric is TEST coverage = detected / testable (SAT-proven-"
            "untestable faults credited out of the denominator; ABORTED faults are "
            "unproven and stay in the denominator, so aborts cap the verdict at "
            "pass_with_caveats)",
            ("pattern grading used %s. Detection is a SEARCH (SAT); grading a "
             "fully-specified pattern has no free variables and is a "
             "deterministic Boolean evaluation, so the simulation path computes "
             "the identical answer and is cross-validated against the native "
             "SAT loop in this same run -- it closes the obligation only on an "
             "exact match" % grading_record.get("method")),
            (seq_note or "sequential masters were not blackboxed before flatten"),
            "stuck-at is the fault-model floor; transition / at-speed (LOC/LOS) "
            "delay-fault ATPG is the documented extension for timing-critical designs",
            ("legacy max_faults created a diagnostic non-closing sample")
            if sampled else ("deterministic fault shard; aggregate every shard "
            "before signoff" if selection["mode"] == "deterministic_shard" else
            "full gate-output stuck-at fault set tested"),
            ("scope=top aggregates retargeted sub-block TEST coverage with top-glue "
             "coverage; boundary-scan + MBIST are separate top-only test structures")
            if scope == "top" else "scope=block: fresh ATPG on the block scan netlist"],
        validation={"verdict": verdict,
                    "note": f"{driving}% stuck-at TEST coverage vs {goal}% target "
                    f"({detectable} detected / {testable} testable; {n_untestable} "
                    f"proven-untestable, {n_aborted} aborted"
                    + (f"; sampled from {total_faults}" if sampled else "")
                    + (f"; chip-aggregated over {len(block_covs)} sub-blocks" if agg is not None else "")
                    + ")"},
        provenance={"yosys": _yosys_version(), "runtime_s": round(elapsed, 3), "log": "atpg.log"})


def _discover_scan_ports(ports, base_name, direction):
    """Return bare single-chain and indexed multi-chain ports for one boundary."""
    return {
        name: port["bits"][0]
        for name, port in ports.items()
        if (name == base_name or name.startswith(base_name + "_"))
        and port.get("direction") == direction
        and port.get("bits")
    }


def _resolve_scan_out_sources(cells, scan_outs, scan_enable_bit,
                              scan_cell_type=None, q_pin="Q"):
    """Resolve scan-output bits to their shift-mode sources.

    Accept only direct wiring or one active-high two-input AND with scan enable.
    Any other combinational path remains unresolved so integrity checking fails
    closed rather than assuming shift-mode transparency.
    """
    resolved = {}
    for name, out_bit in scan_outs.items():
        direct = {
            "scan_out": name,
            "output_bit": out_bit,
            "source_bit": out_bit,
            "path": "direct",
        }
        drivers = []
        for cell_name, cell in cells.items():
            conn = cell.get("connections", {})
            directions = cell.get("port_directions", {})
            for port_name, bits in conn.items():
                if directions.get(port_name) == "output" and out_bit in bits:
                    drivers.append((cell_name, cell))
                    break
        if not drivers:
            resolved[name] = direct
            continue
        if len(drivers) != 1 or scan_enable_bit is None:
            resolved[name] = {
                **direct, "source_bit": None, "path": "unsupported",
            }
            continue
        cell_name, cell = drivers[0]
        cell_type = str(cell.get("type", "")).lower()
        conn = cell.get("connections", {})
        directions = cell.get("port_directions", {})
        if scan_cell_type and cell.get("type") == scan_cell_type \
                and out_bit in conn.get(q_pin, []):
            resolved[name] = {
                **direct,
                "path": "direct_terminal_scan_cell",
                "terminal_cell": cell_name,
            }
            continue
        inputs = [
            bits[0] for port_name, bits in conn.items()
            if directions.get(port_name) == "input" and len(bits) == 1
        ]
        if cell_type in ("$and", "$_and_") and len(inputs) == 2 \
                and inputs.count(scan_enable_bit) == 1:
            source_bit = inputs[1] if inputs[0] == scan_enable_bit else inputs[0]
            resolved[name] = {
                **direct,
                "source_bit": source_bit,
                "path": "active_high_scan_enable_and",
                "guard_cell": cell_name,
            }
        else:
            resolved[name] = {
                **direct,
                "source_bit": None,
                "path": "unsupported",
                "guard_cell": cell_name,
                "guard_type": cell.get("type"),
            }
    return resolved


def _vcd_symbol(index):
    alphabet = "!\"#$%&'()*+,-./:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < 0:
        raise ValueError("VCD symbol index must be non-negative")
    symbol = ""
    while True:
        symbol = alphabet[index % len(alphabet)] + symbol
        index = index // len(alphabet) - 1
        if index < 0:
            return symbol


def _write_scan_stimulus_vcd(path, top, clock, scan_enable, scan_inputs,
                             pattern, cycles, reset=None, reset_active_low=True,
                             input_widths=None):
    input_widths = dict(input_widths or {})
    names = [clock, scan_enable] + list(scan_inputs)
    if reset:
        names.append(reset)
    names += sorted(set(input_widths) - set(names))
    codes = {name: _vcd_symbol(index) for index, name in enumerate(names)}
    lines = ["$date generated $end", "$version chip-dft $end",
             "$timescale 1ns $end", f"$scope module {top} $end"]
    lines += [f"$var wire {input_widths.get(name, 1)} {codes[name]} {name} $end"
              for name in names]
    lines += ["$upscope $end", "$enddefinitions $end", "#0",
              "0" + codes[clock], "1" + codes[scan_enable]]
    for name in names:
        if name in (clock, scan_enable) or name in scan_inputs:
            continue
        width = input_widths.get(name, 1)
        if name == reset:
            value = "1" if reset_active_low else "0"
        else:
            value = "0"
        lines.append((value + codes[name]) if width == 1 else
                     ("b" + value * width + " " + codes[name]))
    bits = list(pattern)
    for name in scan_inputs:
        lines.append((bits[0] if bits else "0") + codes[name])
    for cycle in range(cycles):
        base = cycle * 10
        if cycle:
            lines.append(f"#{base}")
            for chain_index, name in enumerate(scan_inputs):
                bit_index = cycle - chain_index
                value = bits[bit_index] if 0 <= bit_index < len(bits) else "0"
                lines.append(value + codes[name])
        lines += [f"#{base + 5}", "1" + codes[clock],
                  f"#{base + 10}", "0" + codes[clock]]
    open(path, "w").write("\n".join(lines) + "\n")
    return codes


def _vcd_values_at_edges(path, clock, signals):
    code_to_name = {}
    current = {}
    edge_values = []
    clock_code = None
    with open(path, encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.strip()
            match = re.match(r"\$var\s+\S+\s+\d+\s+(\S+)\s+(\S+)\s+\$end", line)
            if match:
                code, name = match.groups()
                code_to_name[code] = name
                if name == clock:
                    clock_code = code
                continue
            scalar = re.match(r"([01xXzZ])(\S+)$", line)
            vector = re.match(r"b([01xXzZ]+)\s+(\S+)$", line)
            if not scalar and not vector:
                continue
            value, code = (scalar.groups() if scalar else vector.groups())
            name = code_to_name.get(code)
            if name is None:
                continue
            old = current.get(name)
            current[name] = value.lower()
            if code == clock_code and old == "0" and value == "1":
                edge_values.append({signal: current.get(signal, "x")
                                    for signal in signals})
    return edge_values


def _scan_observed_bits(edges, chain_length, pattern_length, output_name):
    return "".join(
        edge.get(output_name, "x")
        for edge in edges[chain_length:chain_length + pattern_length])


def _run_scan_shift_simulation(top, scan_netlist, chain_lengths, scan_inputs,
                               scan_outputs, scan_enable, clock, params,
                               input_widths=None):
    models, defines = _resolve_functional_models(params)
    model_basis = "functional_verilog"
    liberty_model = _generate_liberty_sim_models(params)
    if liberty_model:
        models = [liberty_model]
        defines = []
        model_basis = "yosys_generated_from_liberty"
    if not models:
        return {"verdict": "not_assessable", "reason":
                "functional Verilog models or a Liberty model are required for "
                "emitted-netlist scan simulation"}
    pattern = "".join(ch for ch in str(params.get(
        "flush_pattern", "0011010010110100")) if ch in "01")
    if not pattern:
        pattern = "0011010010110100"
    cycles = max(chain_lengths) + len(pattern) + len(scan_inputs) + 1
    stimulus = os.path.join(_OUTPUT_DIR, "scan_stimulus.vcd")
    result = os.path.join(_OUTPUT_DIR, "scan_shift.vcd")
    _write_scan_stimulus_vcd(
        stimulus, top, clock, scan_enable, scan_inputs, pattern, cycles,
        reset=params.get("scan_reset_port"),
        reset_active_low=bool(params.get("scan_reset_active_low", True)),
        input_widths=input_widths)
    define_flags = " ".join("-D" + item for item in defines)
    model_reads = "\n".join(
        f"read_verilog -sv {define_flags} {path}" for path in models)
    script = os.path.join(_WORK_DIR, "scan_shift_sim.ys")
    open(script, "w").write(
        f"{model_reads}\nread_verilog {scan_netlist}\n"
        f"hierarchy -check -top {top}\nprep -top {top}\n"
        f"sim -r {stimulus} -scope {top} -sim -vcd {result} {top}\n")
    process = subprocess.run(["yosys", "-s", script], capture_output=True,
                             text=True, cwd=_WORK_DIR)
    output = process.stdout + "\n" + process.stderr
    open(os.path.join(_OUTPUT_DIR, "scan_shift_sim.log"), "w").write(output)
    if process.returncode or not os.path.isfile(result) or not os.path.getsize(result):
        return {"verdict": "fail", "reason": "Yosys scan simulation failed",
                "report": "scan_shift_sim.log", "model_basis": model_basis}
    edges = _vcd_values_at_edges(result, clock, scan_outputs)
    chains = []
    for index, (length, output_name) in enumerate(zip(chain_lengths, scan_outputs)):
        observed = _scan_observed_bits(
            edges, length, len(pattern), output_name)
        expected = "".join(
            pattern[position] if position >= index else "0"
            for position in range(len(pattern)))
        chains.append({"chain": index, "length": length,
                       "expected": expected, "observed": observed,
                       "match": observed == expected})
    passed = bool(chains) and all(item["match"] for item in chains)
    return {"verdict": "pass" if passed else "fail", "chains": chains,
            "pattern": pattern, "cycles": cycles,
            "stimulus": "scan_stimulus.vcd", "waveform": "scan_shift.vcd",
            "report": "scan_shift_sim.log", "models": models,
            "defines": defines, "model_basis": model_basis}


def _scan_chain_integrity(params):
    """Scan-chain integrity check: verify the scan SHIFT path — every chain shifts a
    known pattern head-to-tail. Catches the bug class the post-DFT LEC can't see
    (LEC holds scan_enable INACTIVE, so a broken SHIFT path is invisible). Traces
    the stitched chains structurally (scan_in_<c> → SCD/Q hops → scan_out_<c>)."""
    if not shutil.which("yosys"):
        return _cde(objective="scan chain integrity", status="failed",
                    error="yosys not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    top = params.get("top")
    files = _stage_rtl(params)
    if not top or not files:
        return _cde(objective="scan chain integrity", status="failed", pdk_binding=binding or "none",
                    error="missing 'top' or scan netlist", validation={"verdict": "fail"})
    scd = params.get("scan_data_pin", "SCD")
    q = params.get("ff_q_pin", "Q")
    libs = _resolve_liberty(params)
    lib_reads = "\n".join(f"read_liberty -lib {l}" for l in libs)
    reads = "\n".join(f"read_verilog {f}" for f in files)
    js = os.path.join(_WORK_DIR, "sci_net.json")
    open(os.path.join(_WORK_DIR, "sci.ys"), "w").write(
        f"{lib_reads}\n{reads}\nhierarchy -check -top {top}\nflatten\nwrite_json {js}\n")
    p = subprocess.run(["yosys", "-q", "-s", os.path.join(_WORK_DIR, "sci.ys")],
                       capture_output=True, text=True, cwd=_WORK_DIR)
    if p.returncode != 0 or not os.path.exists(js):
        open(os.path.join(_OUTPUT_DIR, "sci.log"), "w").write(p.stdout + p.stderr)
        return _cde(objective=f"scan chain integrity of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="Yosys elaboration failed; see sci.log:\n" + (p.stderr or "")[-1500:],
                    validation={"verdict": "fail"})
    net = json.load(open(js))
    mod = net["modules"].get(top) or next(iter(net["modules"].values()))
    cells = mod.get("cells", {})
    ports = mod.get("ports", {})
    scan_in_port = params.get("scan_in_port", "scan_in")
    scan_out_port = params.get("scan_out_port", "scan_out")
    scan_enable_port = params.get("scan_enable_port", "scan_enable")
    scan_ins = _discover_scan_ports(ports, scan_in_port, "input")
    scan_outs = _discover_scan_ports(ports, scan_out_port, "output")
    scan_enable = ports.get(scan_enable_port, {})
    scan_enable_bit = (
        scan_enable.get("bits", [None])[0]
        if scan_enable.get("direction") == "input" and scan_enable.get("bits")
        else None
    )
    scan_cell_type = (
        binding.get("scan_cell") if isinstance(binding, dict) else None
    ) or params.get("scan_cell")
    scan_out_paths = _resolve_scan_out_sources(
        cells, scan_outs, scan_enable_bit, scan_cell_type, q)
    resolved_scan_out_sources = {
        path["source_bit"] for path in scan_out_paths.values()
        if path.get("source_bit") is not None
    }
    scd_src = {}
    all_flops = set()
    for cn, c in cells.items():
        if not _is_flop_type(c.get("type", "")):
            continue
        all_flops.add(cn)
        conn = c.get("connections", {})
        if conn.get(scd):
            scd_src[cn] = conn[scd][0]
    chains, broken = [], []
    chain_members = []            # ordered flop list per chain (for flush sim + orphan check)
    seen_flops = {}               # flop -> chain index (shared-flop detection)
    shared = []
    for ci, (siname, sibit) in enumerate(sorted(scan_ins.items())):
        length, visited, cur_src, ok, guard = 0, set(), sibit, True, 0
        order = []
        while guard < len(cells) + 2:
            guard += 1
            nxt = next((cn for cn, s in scd_src.items()
                        if s == cur_src and cn not in visited), None)
            if nxt is None:
                break
            visited.add(nxt)
            order.append(nxt)
            length += 1
            if nxt in seen_flops:
                shared.append({"flop": nxt, "chains": [seen_flops[nxt], ci]})
            else:
                seen_flops[nxt] = ci
            cur_src = cells[nxt].get("connections", {}).get(q, [None])[0]
            if cur_src is None:
                ok = False
                break
        reaches_out = cur_src in resolved_scan_out_sources
        reached_path = next(
            (path for path in scan_out_paths.values()
             if path.get("source_bit") == cur_src),
            None)
        rec = {"chain": ci, "scan_in": siname, "length": length,
               "reaches_scan_out": reaches_out,
               "scan_out": reached_path.get("scan_out") if reached_path else None,
               "scan_out_path": reached_path.get("path") if reached_path else None}
        chains.append(rec)
        chain_members.append(order)
        if not (ok and length > 0 and reaches_out):
            broken.append(rec)
    total_len = sum(c["length"] for c in chains)
    # ORPHAN check: every scannable flop must sit on exactly one chain — a flop that
    # is neither on a chain nor structurally excluded is UNTESTABLE (ATPG can't
    # control/observe it), a real stitch bug the pure "chains intact" check misses.
    on_chain = set(seen_flops.keys())
    orphan_flops = sorted(all_flops - on_chain)

    # FLUSH / SHIFT-PATTERN SIMULATION (the production check; the structural trace is
    # the floor). Shift a known walking pattern in at scan_in with scan_enable
    # ACTIVE and confirm it emerges bit-exact at scan_out after exactly `length`
    # cycles of latency. Idealized single-clock shift model (Q_next=SCD under SE=1);
    # verifies observed vector + latency, catching length/latency mismatches and a
    # tail flop that does not actually reach scan_out.
    flush_pattern = str(params.get("flush_pattern", "0011010010110100"))
    flush_pattern = "".join(ch for ch in flush_pattern if ch in "01") or "0011010010110100"
    flush = []
    flush_fail = []
    for ci, order in enumerate(chain_members):
        L = len(order)
        if L == 0 or not chains[ci]["reaches_scan_out"]:
            rec = {"chain": ci, "simulated": False,
                   "reason": "no intact shift path to scan_out"}
            flush.append(rec)
            flush_fail.append(rec)
            continue
        # ideal shift register of depth L; feed pattern (LSB first), sample tail.
        reg = [None] * L
        observed = []
        # drive enough cycles to flush the whole pattern all the way through.
        drive = list(flush_pattern) + ["0"] * (L + 1)
        for cyc, inb in enumerate(drive):
            tail = reg[L - 1]
            for i in range(L - 1, 0, -1):
                reg[i] = reg[i - 1]
            reg[0] = inb
            if cyc >= L:                     # tail valid only after L-cycle latency
                observed.append("x" if tail is None else tail)
        expected = list(flush_pattern)
        obs_trim = observed[:len(expected)]
        match = obs_trim == expected
        rec = {"chain": ci, "simulated": True, "latency_cycles": L,
               "pattern": flush_pattern, "observed": "".join(obs_trim),
               "shift_match": match}
        flush.append(rec)
        if not match:
            flush_fail.append(rec)

    scan_clock = params.get("scan_clock_port", "clk")
    if not _is_ident(scan_clock) or scan_clock not in ports:
        netlist_sim = {"verdict": "not_assessable",
                       "reason": "scan_clock_port is absent or invalid"}
    elif not chains or broken:
        netlist_sim = {"verdict": "not_assessable",
                       "reason": "structural chain tracing did not produce intact chains"}
    else:
        netlist_sim = _run_scan_shift_simulation(
            top, files[0], [item["length"] for item in chains],
            [item["scan_in"] for item in chains],
            [item["scan_out"] for item in chains],
            scan_enable_port, scan_clock, params,
            input_widths={name: len(port.get("bits", []))
                          for name, port in ports.items()
                          if port.get("direction") == "input"})

    verdict = "pass" if (chains and not broken and not orphan_flops
                         and not shared and not flush_fail
                         and netlist_sim.get("verdict") == "pass") else "fail"
    fail_bits = []
    if not chains:
        fail_bits.append("no scan chains found")
    if broken:
        fail_bits.append(f"{len(broken)} broken/incomplete chain(s)")
    if orphan_flops:
        fail_bits.append(f"{len(orphan_flops)} orphan (off-chain) flop(s)")
    if shared:
        fail_bits.append(f"{len(shared)} flop(s) shared across chains")
    if flush_fail:
        fail_bits.append(f"{len(flush_fail)} chain(s) failed the flush/shift sim")
    if netlist_sim.get("verdict") != "pass":
        fail_bits.append("emitted-netlist scan simulation did not pass: "
                         + str(netlist_sim.get("reason") or
                               netlist_sim.get("verdict")))
    return _cde(
        objective=f"scan chain integrity of {top}", status="completed",
        pdk_binding=binding or "none",
        results={"scan_chains": {"value": len(chains), "unit": "count"},
                 "flops_on_chains": {"value": total_len, "unit": "count"},
                 "broken_chains": {"value": len(broken), "unit": "count"},
                 "orphan_flops": {"value": len(orphan_flops), "unit": "count"},
                 "shared_flops": {"value": len(shared), "unit": "count"},
                 "flush_sim_failures": {"value": len(flush_fail), "unit": "count"},
                 "netlist_shift_sim_failures": {
                     "value": 0 if netlist_sim.get("verdict") == "pass" else 1,
                     "unit": "count"}},
        qor={"scan_chains": len(chains), "flops_on_chains": total_len,
             "broken_chains": len(broken), "orphan_flops": len(orphan_flops),
             "shared_flops": len(shared), "total_scannable_flops": len(all_flops),
             "flush_sim_failures": len(flush_fail),
             "netlist_shift_simulation": netlist_sim.get("verdict")},
        signoff={"chains": chains, "broken_chains": broken,
                 "orphan_flops": orphan_flops[:64], "shared_flops": shared[:64],
                 "scan_out_paths": scan_out_paths,
                 "flush_sim": flush, "flush_pattern": flush_pattern,
                 "netlist_shift_simulation": netlist_sim,
                 "method": "emitted-netlist Yosys VCD co-simulation plus "
                 "flush/shift-pattern model (walking pattern in→out, "
                 "latency-checked) + structural shift-path trace (scan_in→SCD/Q hops→"
                 "scan_out, allowing only direct wiring or one active-high scan-enable "
                 "AND evaluated with scan enable asserted) + orphan/shared-flop audit",
                 "report": "sci.log"},
        inputs_ref={"files": files, "liberty": libs},
        assumptions=["scan-shift integrity requires Yosys simulation of the emitted "
                 "scan netlist with binding-owned functional cell models; the "
                 "idealized model remains a cross-check, not closure evidence",
                 "scan-shift integrity = flush/shift-pattern SIMULATION (a walking "
                     "pattern must emerge bit-exact at scan_out after exactly the "
                     "chain-length latency) backed by a structural shift-path trace; "
                     "every scannable flop must sit on exactly one chain (orphan flops "
                     "are untestable, shared flops are a stitch bug) — catches the bug "
                     "class the post-DFT LEC cannot see (it holds scan_enable inactive)",
                     "scan_out combinational traversal is fail-closed: only direct "
                     "terminal-Q wiring or one two-input active-high AND with the "
                     "declared scan-enable port is accepted in shift mode",
                     "idealized single-clock shift model (Q_next=SCD under scan_enable); "
                     "multi-clock-domain chains require lockup latches at domain "
                     "boundaries (verify separately) — the documented extension"],
        validation={"verdict": verdict,
                    "note": (f"{len(chains)} chains intact, {total_len} flops, "
                             f"flush sim passed on all chains"
                             if verdict == "pass" else "; ".join(fail_bits))},
        provenance={"yosys": _yosys_version(), "log": "sci.log"})



def dispatch(params):
    s = params.get("scenario")
    # scan insertion (writes a scan-inserted netlist) vs analysis (plan-only)
    if s in ("scan_insert", "scan_insertion", "insert_scan", "stitch_scan"):
        return _scan_insert(params)
    if s in ("scan_analysis", "dft_check"):
        return _scan_analysis(params)
    if s in ("fault_atpg", "atpg", "test_generation", "scan_atpg"):
        return _fault_atpg(params)
    if s in ("scan_chain_integrity", "chain_integrity", "shift_test"):
        return _scan_chain_integrity(params)
    if s in ("atpg_po", "atpg_primary_output"):
        return _atpg(params)
    return _cde(objective="DFT", status="failed",
                error=f"unknown scenario '{s}'; supported: scan_analysis, "
                      f"scan_insert, fault_atpg, scan_chain_integrity",
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
