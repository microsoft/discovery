#!/usr/bin/env python3
"""uarch_ppa_utils.py -- analytic microarchitecture / PPA exploration.

No external engine: this is deterministic analytic estimation. Two scenarios:
  * explore -- sweep architectural knobs (e.g. pipeline depth, issue width,
    cache size) over a caller-supplied grid and estimate PPA per point using a
    transparent analytic model plus node scaling factors from the PDK binding
    (fanout-of-4 delay, cell density, energy/op). Returns the Pareto-optimal
    points.
  * estimate -- estimate PPA (frequency, area, power) for a single architectural
    configuration.

Node-aware: FO4 delay, cell density, and energy/op come from the PDK binding.
Results conform to the Common Design Envelope.
"""
import itertools
import json
import os
import time

TOOL = "uarch-ppa"
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
        with open(os.path.join(_OUTPUT_DIR, name), "a", encoding="utf-8") as f:
            f.write(str(cmd) + "\n")
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
                       ("Evidence", "signoff_evidence")):
        d = r.get(key)
        if isinstance(d, dict) and d:
            rows = _report_kv_rows(d)
            if rows:
                L += ["", "## " + title, "", "| Metric | Value |", "| --- | --- |"] + rows
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
        if low.endswith((".log", ".txt")) or low == "run_command.txt":
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
    pb = r.get("pdk_binding")
    if pb and pb != "none":
        L += ["## Provenance", "",
              "- PDK binding: " + (str(pb) if not isinstance(pb, dict)
                                   else str(pb.get("pdk", pb))), ""]
    L += ["## Where to find more", "",
          "- `common_design_envelope.json` \u2014 full machine-readable envelope (this dir)",
          "- `reports/` \u2014 the full sweep table / Pareto set", ""]
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


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "uarch-ppa", "version": "1.0.0"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "analytic_ppa"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


#: EVERY tunable coefficient in the analytic model, in one place.
#:
#: These numbers were invented. They are plausible first-order shapes -- ILP grows
#: sub-linearly with issue width, logic area grows super-linearly, a bigger cache
#: reduces stall -- but NONE of them was fitted against silicon or against a real
#: synthesis run on this node. Previously they were scattered as bare literals
#: inside the arithmetic (`width ** 0.6`, `cache_kb * 6.0`, `area_um2 * 2.0e-4`),
#: which made an UNCALIBRATED GUESS indistinguishable from a measured constant:
#: the tool emitted `area_um2` and `power_mw` to four decimal places, and nothing
#: in the envelope said the exponent behind them was chosen by hand.
#:
#: Consolidating them here does two things. A caller can now REPLACE any of them
#: with a value fitted to their own node, and the envelope can state exactly which
#: ones are still defaults -- so an absolute prediction is never presented with
#: the same authority as a measurement.
_MODEL_COEFFICIENTS = {
    "ilp_exponent": {
        "default": 0.6, "unit": "exponent",
        "meaning": "effective ILP = issue_width ** e (sub-linear returns)"},
    "hazard_cpi_per_stage": {
        "default": 0.03, "unit": "CPI per stage",
        "meaning": "added CPI per pipeline stage beyond the first"},
    "miss_stall_base": {
        "default": 0.30, "unit": "fraction",
        "meaning": "stall fraction at the reference cache size"},
    "miss_stall_ref_kb": {
        "default": 8.0, "unit": "KB",
        "meaning": "cache size at which miss_stall_base applies"},
    "miss_stall_exponent": {
        "default": 0.5, "unit": "exponent",
        "meaning": "stall = base * (ref_kb / cache_kb) ** e"},
    "area_width_exponent": {
        "default": 1.3, "unit": "exponent",
        "meaning": "core logic gates scale as width ** e"},
    "pipeline_flops_kge": {
        "default": 0.8, "unit": "kGE per stage per width",
        "meaning": "flop area added per pipeline stage per issue slot"},
    "cache_kge_per_kb": {
        "default": 6.0, "unit": "kGE per KB",
        "meaning": "SRAM-equivalent gate cost per KB of cache"},
    "power_width_exponent": {
        "default": 0.4, "unit": "exponent",
        "meaning": "dynamic power multiplier width ** e (wider datapath toggles more)"},
    "leakage_mw_per_um2": {
        "default": 2.0e-4, "unit": "mW per um2",
        "meaning": "leakage power per unit area"},
    "clk_overhead_ps": {
        "default": 40.0, "unit": "ps",
        "meaning": "flop setup + clock skew overhead added to every cycle"},
    "min_fo4_per_stage": {
        "default": 8.0, "unit": "FO4",
        "meaning": "floor on logic depth per stage; deeper pipelines cannot go below it"},
}

#: Node constants. Same problem, same treatment: a default here is a GUESS about
#: the node, and a guess about the node silently rescales every absolute number.
_NODE_DEFAULTS = {
    "fo4_ps": {"default": 80.0, "unit": "ps",
               "meaning": "FO4 inverter delay (typical of a 130 nm node)"},
    "cell_density_kge_um2": {"default": 0.05, "unit": "kGE per um2",
                             "meaning": "achievable placed cell density"},
    "energy_per_op_fj": {"default": 500.0, "unit": "fJ per op",
                         "meaning": "switching energy per operation"},
}


def _resolve_coefficients(params, binding):
    """Resolve every model coefficient with caller > binding > tool default.

    Returns (values, provenance, uncalibrated) where `uncalibrated` lists every
    coefficient still sitting on a hand-chosen default. That list is what makes
    the difference between "the model was calibrated for this node" and "the
    model shipped with numbers somebody guessed", which the emitted PPA figures
    cannot otherwise convey."""
    supplied = params.get("model_coefficients") or {}
    bind_coeffs = (binding.get("uarch_model_coefficients") or {}) \
        if isinstance(binding, dict) else {}
    values, prov, uncal = {}, {}, []
    for name, spec in _MODEL_COEFFICIENTS.items():
        if name in supplied and supplied[name] is not None:
            values[name] = float(supplied[name])
            prov[name] = "caller"
        elif name in bind_coeffs and bind_coeffs[name] is not None:
            values[name] = float(bind_coeffs[name])
            prov[name] = "pdk_binding.uarch_model_coefficients"
        else:
            values[name] = float(spec["default"])
            prov[name] = "tool_default_uncalibrated"
            uncal.append(name)
    return values, prov, uncal


def _node_scaling(binding, params=None):
    """Node scaling constants from the PDK binding.

    Returns (fo4_ps, density, energy_fj, provenance, defaulted) so the caller can
    see which node constants were actually supplied. A defaulted node constant
    rescales EVERY absolute figure this tool emits."""
    params = params or {}
    binding = binding if isinstance(binding, dict) else {}
    out, prov, defaulted = {}, {}, []
    aliases = {"cell_density_kge_um2": ("cell_density_kge_um2", "density")}
    for name, spec in _NODE_DEFAULTS.items():
        keys = aliases.get(name, (name,))
        val = None
        for k in keys:
            if params.get(k) is not None:
                val, prov[name] = float(params[k]), "caller"
                break
            if binding.get(k) is not None:
                val, prov[name] = float(binding[k]), "pdk_binding"
                break
        if val is None:
            val, prov[name] = float(spec["default"]), "tool_default_uncalibrated"
            defaulted.append(name)
        out[name] = val
    return (out["fo4_ps"], out["cell_density_kge_um2"], out["energy_per_op_fj"],
            prov, defaulted)


def _estimate_point(cfg, fo4_ps, density, energy_fj, k=None):
    """Transparent first-order analytic PPA model.

    - depth (pipeline stages): more stages => higher freq (fewer FO4/stage) but
      more flop area/power and a CPI penalty from hazards.
    - width (issue width): higher IPC (sub-linear) but super-linear area/power.
    - cache_kb: bigger cache lowers miss rate (better effective IPC) but adds area/power.
    """
    depth = float(cfg.get("depth", cfg.get("pipeline_depth", 5)))
    width = float(cfg.get("width", cfg.get("issue_width", 1)))
    cache_kb = float(cfg.get("cache_kb", 8))
    logic_fo4 = float(cfg.get("logic_fo4_per_stage", 200.0))
    base_gates_k = float(cfg.get("base_gates_k", 50.0))  # kGE core logic
    if k is None:
        k = {n: s["default"] for n, s in _MODEL_COEFFICIENTS.items()}

    fo4_per_stage = max(logic_fo4 / depth, k["min_fo4_per_stage"])
    cycle_ps = fo4_per_stage * fo4_ps + k["clk_overhead_ps"]
    freq_mhz = 1.0e6 / cycle_ps

    # effective IPC: width gives sub-linear ILP; hazards grow with depth;
    # cache reduces stall fraction.
    ilp = width ** k["ilp_exponent"]
    hazard_cpi = 1.0 + k["hazard_cpi_per_stage"] * (depth - 1)
    miss_stall = k["miss_stall_base"] * (
        k["miss_stall_ref_kb"] / max(cache_kb, 1.0)) ** k["miss_stall_exponent"]
    ipc = ilp / (hazard_cpi * (1.0 + miss_stall))
    mips = ipc * freq_mhz

    gates_k = (base_gates_k * width ** k["area_width_exponent"]
               + k["pipeline_flops_kge"] * depth * width
               + cache_kb * k["cache_kge_per_kb"])
    area_um2 = gates_k * 1000.0 / (density * 1000.0)  # kGE / (kGE per um2)

    # dynamic power ~ energy/op * ops/s (ops/s = ipc*freq), + leakage ~ area
    dyn_mw = energy_fj * 1e-15 * (ipc * freq_mhz * 1e6) * 1e3
    dyn_mw *= width ** k["power_width_exponent"]
    leak_mw = area_um2 * k["leakage_mw_per_um2"]
    power_mw = dyn_mw + leak_mw

    return {
        "config": {"depth": depth, "width": width, "cache_kb": cache_kb},
        "freq_mhz": round(freq_mhz, 2),
        "ipc": round(ipc, 4),
        "mips": round(mips, 2),
        "area_um2": round(area_um2, 1),
        "power_mw": round(power_mw, 4),
    }


def _pareto(points):
    """Maximize mips, minimize area_um2, minimize power_mw."""
    def dominates(a, b):
        return (a["mips"] >= b["mips"] and a["area_um2"] <= b["area_um2"]
                and a["power_mw"] <= b["power_mw"]
                and (a["mips"] > b["mips"] or a["area_um2"] < b["area_um2"]
                     or a["power_mw"] < b["power_mw"]))
    front = []
    for p in points:
        if not any(dominates(q, p) for q in points if q is not p):
            front.append(p)
    return front


def _explore(params):
    binding = params.get("pdk_binding") or {}
    grid = params.get("grid") or params.get("sweep")
    if not grid or not isinstance(grid, dict):
        return _cde(objective="uarch PPA exploration", status="failed",
                    pdk_binding=binding or "none",
                    error="no `grid` provided (e.g. {depth:[3,5,8], width:[1,2], cache_kb:[8,16]})",
                    validation={"verdict": "fail"})
    fo4_ps, density, energy_fj, node_prov, node_defaulted = _node_scaling(
        binding, params)
    k, coeff_prov, uncalibrated = _resolve_coefficients(params, binding)
    base = params.get("base_config") or {}
    keys = list(grid.keys())
    vals = [grid[k_] if isinstance(grid[k_], list) else [grid[k_]] for k_ in keys]
    points = []
    for combo in itertools.product(*vals):
        cfg = dict(base)
        cfg.update(dict(zip(keys, combo)))
        points.append(_estimate_point(cfg, fo4_ps, density, energy_fj, k))
    if not points:
        return _cde(objective="uarch PPA exploration", status="failed",
                    pdk_binding=binding or "none",
                    error="empty grid produced no design points",
                    validation={"verdict": "fail"})
    front = _pareto(points)
    sweep_path = os.path.join(_OUTPUT_DIR, "sweep.json")
    with open(sweep_path, "w") as f:
        json.dump({"points": points, "pareto": front,
                   "model_coefficients": k,
                   "coefficient_provenance": coeff_prov}, f, indent=2)
    best_perf = max(points, key=lambda p: p["mips"])
    # CALIBRATION HONESTY. The RANKING this model produces is defensible: the
    # coefficient shapes are monotonic, so "deeper pipeline clocks faster and
    # costs area" holds regardless of the exact exponent. The ABSOLUTE numbers
    # are not: freq_mhz / area_um2 / power_mw are only as good as coefficients
    # nobody fitted. Reporting both with the same authority is what made an
    # invented exponent readable as an engineering estimate.
    calibrated = not uncalibrated and not node_defaulted
    verdict = "pass" if calibrated else "review"
    note = ("%d point(s) evaluated, %d Pareto-optimal" % (len(points), len(front)))
    if not calibrated:
        note += ("; RANKING is usable but the ABSOLUTE figures are NOT calibrated: "
                 "%d model coefficient(s) and %d node constant(s) are still "
                 "hand-chosen tool defaults (%s). Do not compare these numbers "
                 "against a PPA budget."
                 % (len(uncalibrated), len(node_defaulted),
                    ", ".join((uncalibrated + node_defaulted)[:5])))
    return _cde(
        objective="explore %d architectural configuration(s)" % len(points),
        status="completed", pdk_binding=binding or "none",
        results={"points": {"value": len(points), "unit": "count"},
                 "pareto_points": {"value": len(front), "unit": "count"},
                 "best_mips": {"value": best_perf["mips"], "unit": "MIPS",
                               "class": "diagnostic",
                               "basis": ("calibrated_analytic_model" if calibrated
                                         else "UNCALIBRATED_analytic_model"),
                               "note": ("relative ranking only unless every "
                                        "coefficient is calibrated")}},
        qor={"points": len(points), "pareto_points": len(front),
             "best_config": best_perf["config"], "best_mips": best_perf["mips"],
             "model_calibrated": calibrated,
             "uncalibrated_coefficients": len(uncalibrated) + len(node_defaulted)},
        signoff={"pareto": front, "best_perf": best_perf, "sweep": "sweep.json",
                 "model_coefficients": k,
                 "coefficient_provenance": coeff_prov,
                 "node_constant_provenance": node_prov,
                 "uncalibrated_coefficients": uncalibrated or None,
                 "defaulted_node_constants": node_defaulted or None,
                 "model_calibrated": calibrated,
                 "absolute_predictions_valid": calibrated,
                 "ranking_valid": True,
                 "calibration_note": (
                     "every coefficient is caller- or binding-supplied; absolute "
                     "figures may be compared to a budget" if calibrated else
                     "RELATIVE RANKING ONLY. The Pareto ordering is defensible "
                     "because the coefficient shapes are monotonic, but the "
                     "absolute freq/area/power figures rest on hand-chosen "
                     "exponents and node constants that were never fitted to "
                     "silicon or to a synthesis run. Supply model_coefficients "
                     "and node constants to obtain absolute predictions.")},
        inputs_ref={"grid": grid, "node_scaling":
                    {"fo4_ps": fo4_ps, "density": density, "energy_fj": energy_fj}},
        assumptions=["transparent first-order analytic PPA model; node constants "
                     "(FO4 delay, cell density, energy/op) from the PDK binding; "
                     "estimates are for early exploration, not signoff",
                     "model coefficients are EXPLICIT and overridable; any left "
                     "on a tool default is reported as uncalibrated and the "
                     "absolute figures are declared ranking-only"],
        validation={"verdict": verdict, "note": note},
        provenance={"sweep": "sweep.json",
                    "coefficient_provenance": coeff_prov,
                    "node_constant_provenance": node_prov},
    )


def _estimate(params):
    binding = params.get("pdk_binding") or {}
    cfg = params.get("config")
    if not cfg or not isinstance(cfg, dict):
        return _cde(objective="uarch PPA estimate", status="failed",
                    pdk_binding=binding or "none",
                    error="no `config` provided (e.g. {depth:5, width:2, cache_kb:16})",
                    validation={"verdict": "fail"})
    fo4_ps, density, energy_fj, node_prov, node_defaulted = _node_scaling(
        binding, params)
    k, coeff_prov, uncalibrated = _resolve_coefficients(params, binding)
    pt = _estimate_point(cfg, fo4_ps, density, energy_fj, k)
    # A SINGLE POINT HAS NO RANKING TO FALL BACK ON. The sweep at least yields a
    # defensible ordering; here the ONLY output is four absolute numbers. If the
    # coefficients behind them were never fitted, those numbers are a hypothesis
    # with four decimal places, and reporting `pass` invites them to be compared
    # against a budget.
    calibrated = not uncalibrated and not node_defaulted
    verdict = "pass" if calibrated else "not_assessable"
    note = ("analytic PPA estimate produced from calibrated coefficients"
            if calibrated else
            "estimate produced, but %d model coefficient(s) and %d node "
            "constant(s) are hand-chosen tool defaults (%s). These absolute "
            "figures are NOT a prediction for this node and must not be "
            "compared against a PPA budget."
            % (len(uncalibrated), len(node_defaulted),
               ", ".join((uncalibrated + node_defaulted)[:5])))
    _basis = "calibrated_analytic_model" if calibrated else "UNCALIBRATED_analytic_model"
    return _cde(
        objective="estimate PPA for one architectural configuration",
        status="completed", pdk_binding=binding or "none",
        results={"freq_mhz": {"value": pt["freq_mhz"], "unit": "MHz",
                              "basis": _basis},
                 "mips": {"value": pt["mips"], "unit": "MIPS", "basis": _basis},
                 "area_um2": {"value": pt["area_um2"], "unit": "um2",
                              "basis": _basis},
                 "power_mw": {"value": pt["power_mw"], "unit": "mW",
                              "basis": _basis}},
        qor={"freq_mhz": pt["freq_mhz"], "ipc": pt["ipc"], "mips": pt["mips"],
             "area_um2": pt["area_um2"], "power_mw": pt["power_mw"],
             "model_calibrated": calibrated,
             "uncalibrated_coefficients": len(uncalibrated) + len(node_defaulted)},
        signoff={"estimate": pt,
                 "model_coefficients": k,
                 "coefficient_provenance": coeff_prov,
                 "node_constant_provenance": node_prov,
                 "uncalibrated_coefficients": uncalibrated or None,
                 "defaulted_node_constants": node_defaulted or None,
                 "model_calibrated": calibrated,
                 "absolute_predictions_valid": calibrated},
        inputs_ref={"config": cfg, "node_scaling":
                    {"fo4_ps": fo4_ps, "density": density, "energy_fj": energy_fj}},
        assumptions=["transparent first-order analytic PPA model; node constants "
                     "from the PDK binding; estimate is for early exploration, "
                     "not signoff",
                     "model coefficients are EXPLICIT and overridable; any left "
                     "on a tool default is reported as uncalibrated"],
        validation={"verdict": verdict, "note": note},
        provenance={"coefficient_provenance": coeff_prov,
                    "node_constant_provenance": node_prov},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("explore", "sweep", "dse"):
        return _explore(params)
    if s in ("estimate", "point", "ppa"):
        return _estimate(params)
    return _cde(objective="uarch PPA", status="failed",
                error="unknown scenario '%s'; supported: explore, estimate" % s,
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
