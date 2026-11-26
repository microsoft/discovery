#!/usr/bin/env python3
"""lvs_utils.py -- real Netgen Layout-vs-Schematic comparison (+ Magic extraction).

LVS is a mandatory tapeout gate: the layout-extracted netlist must match the
source/schematic netlist device-for-device and net-for-net. Two scenarios:

  * lvs_compare    -- run `netgen -batch lvs "<layout> <cell>" "<schem> <cell>"
                      <setup> <report>` on two netlists and parse the verdict;
                      or, with engine=klayout (caller > binding tool_policy >
                      binding capabilities.lvs.engine), run the PDK's KLayout
                      .lylvs deck on a GDS + a schematic (gate-level Verilog is
                      converted to SPICE with CDL pin order) and parse the lvsdb.
  * extract_layout -- run Magic `ext2spice` on a .mag/.gds layout to produce the
                      layout SPICE netlist for a subsequent compare.

Node-aware: the device-matching setup file comes from the PDK binding (lvs_rules).
Results conform to the Common Design Envelope.
"""
import collections
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "lvs"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


def _is_ident(s):
    """True if *s* is a safe cell identifier -- blocks script injection via
    user-supplied cell names interpolated into Magic Tcl / Netgen scripts."""
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
                or low.endswith("_report.json") or low.endswith(".csv")
                or low.endswith(".out")):
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
          "- `reports/` \u2014 Netgen comparison report (`*.out`), `REPORT.md`",
          "- `logs/` \u2014 verbatim Netgen/Magic log and the exact run command", ""]
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


def _netgen_bin():
    """Resolve the netgen executable across distros: Debian ships it as
    `netgen-lvs`; source/other builds use `netgen`."""
    for cand in ("netgen", "netgen-lvs"):
        p = shutil.which(cand)
        if p:
            return p
    for p in ("/usr/lib/netgen/bin/netgen", "/usr/bin/netgen-lvs"):
        if os.path.exists(p):
            return p
    return None


def _version(bin_name, args):
    try:
        out = subprocess.run([bin_name] + args, capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return txt.splitlines()[0] if txt else bin_name
    except Exception:
        return bin_name


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None, engine="Netgen", engine_version=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": engine, "version": engine_version or "netgen"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "netlist_comparison"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _resolve_lvs_policy(params, binding):
    """Resolve the LVS engine + Magic-extract settings from the PDK tool_policy,
    tracking the source of each decision. Precedence: caller param > tool_policy >
    pdk_binding.capabilities.lvs.engine > tool default (netgen, the sky130
    reference LVS engine).

    Returns {engine, engine_source, pdk_recommended, override, magic_settings}."""
    if not isinstance(binding, dict):
        binding = {}
    policy = ((binding.get("tool_policy") or {}).get("lvs") or {})
    pol_engine = policy.get("engine")
    pol_magic = (policy.get("settings") or {}).get("magic") or {}
    # The binding's capability block is where nangate45 declares its engine
    # (capabilities.lvs.engine = klayout). Ignoring it silently defaulted every
    # nangate45 run to netgen + Magic extraction, which has no Magic tech there.
    cap_engine = (((binding.get("capabilities") or {}).get("lvs") or {})
                  .get("engine"))
    pdk_engine = pol_engine or cap_engine
    caller_engine = str(params.get("engine") or "").lower().strip() or None
    if caller_engine:
        engine = caller_engine
        source = ("caller_override" if pdk_engine and caller_engine != str(pdk_engine).lower()
                  else "caller")
    elif pol_engine:
        engine, source = str(pol_engine).lower(), "pdk_policy"
    elif cap_engine:
        engine, source = str(cap_engine).lower(), "pdk_capability"
    else:
        engine, source = "netgen", "tool_default"
    pol_engine = pdk_engine
    # Magic extract settings: caller magicrc wins, else policy, else binding.
    magicrc = (params.get("magicrc") or pol_magic.get("magicrc")
               or binding.get("magicrc"))
    return {"engine": engine, "engine_source": source,
            "pdk_recommended": pol_engine, "override": source == "caller_override",
            "magic_settings": {"magicrc": magicrc}}


# --- extraction cross-check against the PDK CDL ------------------------------
# An extracted netlist that is STRUCTURALLY VALID but WRONG passes every check
# this tool used to make: `_extract_layout` reported "layout netlist extracted"
# with no device count at all, so an empty extraction (the measured symptom of a
# missing PDK_ROOT, where Magic loads no technology and `gds read` imports
# nothing) reported success.
#
# The PDK's own CDL is the ground truth here -- it ships alongside the GDS and
# describes the same cells, so a disagreement is a real discrepancy rather than
# two engines differing by convention. MEASURED over the whole sky130_fd_sc_hd
# library: 437 cells extracted with Magic, 435 match the CDL exactly. The 2 that
# differ are characterized below and are library facts, not tool defects.
#
# FOUR CONVENTIONS HAD TO BE MEASURED, and getting any of them wrong silently
# corrupts the comparison:
#
#   1. FINGER EXPANSION. The CDL carries `m=` (260 of 437 cells use m>1);
#      clkbuf_16 is 4 device lines but 40 fingers. Magic extracts the fingers
#      individually, so the CDL must be finger-expanded or every wide cell looks
#      like a mismatch.
#   2. ALL DEVICE TYPES, not just MOSFETs. Counting only `M` lines reports 0
#      devices for conb_1, whose CDL body is two `r` resistors -- and then calls
#      a correct extraction a failure.
#   3. HIERARCHY. Magic emits a MULTI-SUBCKT file for a hierarchical cell
#      (macro_sparecell defines nand2_2/inv_2/nor2_2/conb_1 and then instantiates
#      them). Summing device lines across the file counts the sub-definitions AND
#      the instances: 29 devices for a cell that has 42. Both sides are parsed
#      per-subckt and flattened to primitives.
#   4. MODEL PREFIX. Magic writes `sky130_fd_pr__nfet_01v8`; the CDL writes
#      `nfet_01v8`.
#
# The comparison is PER MODEL, not on the total. A swap that keeps the count
# identical (nfet -> pfet) is a real defect and is caught; a check on totals
# alone would pass it.
_SPICE_DEVICE_PREFIXES = frozenset("MRCDQXJ")

#: Cells whose CDL body is knowingly incomplete are NOT special-cased here. On
#: sky130 the two library-level differences are diode_2 (the CDL states
#: "Tap diode is not represented here", so the layout has a device the CDL does
#: not) and probec_p_8 (identical device COUNT, but the CDL names 3 metal shorts
#: `short` where Magic extracts `res_generic_m5`). Both are reported as
#: mismatches with their per-model delta and routed to waiver adjudication,
#: because auto-classifying "same count, different model" as benign would also
#: bless a genuine nfet->pfet swap.


def _join_spice_continuations(text):
    """SPICE `+` lines continue the PREVIOUS line. Parsing without joining
    splits one device across records and loses its `m=` multiplier."""
    out = []
    for raw in text.splitlines():
        s = raw.rstrip()
        if s.startswith("+"):
            if out:
                out[-1] += " " + s[1:].strip()
        else:
            out.append(s)
    return out


def _norm_device_model(model, vendor_prefixes=("sky130_fd_pr__",)):
    for p in vendor_prefixes:
        if model and model.startswith(p):
            return model[len(p):]
    return model or ""


def _parse_spice_netlist(path, cdl_style, cell_prefix=""):
    """Parse a SPICE file into {subckt: {"prim": Counter, "inst": Counter}}.

    SUBCKT-AWARE by construction; see the hierarchy note above.

    `cdl_style` selects where the model name sits on a device line. The CDL puts
    it after the terminals and before the parameters, so the model is the last
    BARE token on the joined line. Magic writes the model immediately after the
    terminals and then only `k=v` parameters, so the model is the last bare token
    BEFORE the first `=`.
    """
    cells, cur = {}, None
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    for s in _join_spice_continuations(text):
        t = s.strip()
        if not t or t.startswith("*"):
            continue
        u = t.upper()
        if u.startswith(".SUBCKT"):
            parts = t.split()
            cur = parts[1] if len(parts) > 1 else None
            if cur:
                cells.setdefault(cur, {"prim": collections.Counter(),
                                       "inst": collections.Counter()})
            continue
        if u.startswith(".ENDS"):
            cur = None
            continue
        if cur is None or t[:1].upper() not in _SPICE_DEVICE_PREFIXES:
            continue
        toks = t.split()
        if cdl_style:
            model = next((x for x in reversed(toks) if "=" not in x and x != "/"), None)
        else:
            model = None
            for x in toks[1:]:
                if "=" in x:
                    break
                model = x
        m = re.search(r"\bm=([0-9.]+)", t)
        try:
            mult = int(float(m.group(1))) if m else 1
        except (TypeError, ValueError):
            mult = 1
        # A subcircuit INSTANCE is recursed into; a primitive is counted.
        if model and cell_prefix and model.startswith(cell_prefix):
            cells[cur]["inst"][model] += mult
        else:
            cells[cur]["prim"][_norm_device_model(model)] += mult
    return cells


def _flatten_devices(cells, name, depth=0, _max_depth=32):
    """Flatten one subckt to primitive device counts, recursing into instances."""
    if depth > _max_depth or name not in cells:
        return collections.Counter()
    c = collections.Counter(cells[name]["prim"])
    for sub, n in cells[name]["inst"].items():
        for k, v in _flatten_devices(cells, sub, depth + 1, _max_depth).items():
            c[k] += v * n
    return c


def _cdl_cross_check(extracted_spice, cell, cdl_path, cell_prefix=""):
    """Compare an extracted netlist against the PDK CDL for the same cell.

    Returns None when the cross-check could not be performed, so a missing CDL
    reads as NOT ASSESSABLE rather than as agreement -- the whole point is that
    an unverified extraction previously reported success.
    """
    if not cdl_path or not os.path.exists(str(cdl_path)):
        return None
    if not extracted_spice or not os.path.exists(str(extracted_spice)):
        return None
    cdl_cells = _parse_spice_netlist(cdl_path, True, cell_prefix)
    ext_cells = _parse_spice_netlist(extracted_spice, False, cell_prefix)
    if cell not in cdl_cells:
        return {"status": "not_assessable", "cell": cell,
                "reason": ("cell %r is not in the PDK CDL, so there is no "
                           "ground truth to compare the extraction against"
                           % cell),
                "cdl_devices": None, "extracted_devices": None, "delta": {}}
    if cell not in ext_cells:
        return {"status": "not_assessable", "cell": cell,
                "reason": ("cell %r is not defined in the extracted netlist"
                           % cell),
                "cdl_devices": None, "extracted_devices": None, "delta": {}}
    cd = _flatten_devices(cdl_cells, cell)
    ex = _flatten_devices(ext_cells, cell)
    delta = {k: {"cdl": cd.get(k, 0), "extracted": ex.get(k, 0)}
             for k in sorted(set(cd) | set(ex)) if cd.get(k, 0) != ex.get(k, 0)}
    return {"status": "match" if not delta else "mismatch",
            "cell": cell,
            "cdl_devices": sum(cd.values()),
            "extracted_devices": sum(ex.values()),
            "cdl_by_model": dict(cd), "extracted_by_model": dict(ex),
            "delta": delta,
            "note": ("CDL finger-expanded (m=) and hierarchy flattened on both "
                     "sides; compared PER MODEL, so a swap that preserves the "
                     "device count is still caught")}


def _extract_layout(params):
    """Magic ext2spice: extract a SPICE netlist from a .mag/.gds layout."""
    if not shutil.which("magic"):
        # not_assessable, not fail: no extraction ran, so there is nothing to
        # call wrong. `fail` here would read as a defective layout.
        return _cde(objective="LVS extract", status="failed", engine="Magic",
                    error="Magic is not provisioned in this tool image, so no "
                          "netlist was extracted. This is a tool-provisioning "
                          "gap, NOT a layout defect.",
                    validation={"verdict": "not_assessable",
                                "reason": "magic absent from tool image",
                                "remediation": "provision Magic"})
    binding = params.get("pdk_binding") or {}
    layout = params.get("layout")
    cell = params.get("cell") or params.get("top")
    if cell is not None and not _is_ident(cell):
        return _cde(objective="LVS extract", status="failed", engine="Magic",
                    error=f"invalid 'cell'/'top' identifier: {cell!r}", validation={"verdict": "fail"})
    pol = _resolve_lvs_policy(params, binding)
    magicrc = pol["magic_settings"].get("magicrc")
    _cap_engine = str((((binding.get("capabilities") or {}).get("lvs") or {}).get("engine")
                       if isinstance(binding, dict) else "") or "").lower()
    _klayout_hint = ("" if _cap_engine != "klayout" else
                     " This PDK binds capabilities.lvs.engine=klayout: run scenario "
                     "lvs_compare with engine=klayout, `layout` (GDS) and "
                     "`schematic_netlist` -- the KLayout deck extracts the layout "
                     "itself, no Magic extraction is needed.")
    if (_cap_engine == "klayout" and not magicrc and not params.get("magic_tech")
            and not params.get("magicrc")):
        return _cde(objective="LVS extract", status="failed", engine="Magic",
                    pdk_binding=binding or "none",
                    error="this PDK has no Magic technology (no magicrc/magic_tech in "
                          "the binding or params), so Magic cannot extract its "
                          "layout; an extraction attempt would only yield an empty "
                          "netlist." + _klayout_hint,
                    validation={"verdict": "not_assessable",
                                "reason": "no Magic tech for this PDK",
                                "remediation": "use lvs_compare engine=klayout"})
    if not layout or not os.path.exists(str(layout)):
        return _cde(objective="LVS extract", status="failed", engine="Magic",
                    pdk_binding=binding or "none",
                    error=f"layout not found: {layout}", validation={"verdict": "fail"})
    out_spice = os.path.join(_OUTPUT_DIR, f"{cell or 'layout'}.ext.spice")
    is_gds = str(layout).lower().endswith((".gds", ".gds2", ".oas"))
    load = (f"gds read {layout}\nload {cell}\n" if is_gds else f"load {layout}\n")
    tcl = os.path.join(_WORK_DIR, "extract.tcl")
    with open(tcl, "w") as f:
        f.write(f"""{load}extract all
ext2spice lvs
ext2spice -o {out_spice}
quit -noprompt
""")
    cmd = ["magic", "-dnull", "-noconsole"]
    if magicrc and os.path.exists(str(magicrc)):
        cmd += ["-rcfile", str(magicrc)]
    cmd += [tcl]
    t0 = time.time()
    _save_run_command(cmd)
    # PDK_ROOT is what lets the vendor magicrc find its techfile. Without it
    # Magic loads no technology, so there is no `cifinput` section, `gds read`
    # imports nothing and ext2spice emits an EMPTY netlist -- which downstream
    # LVS would compare against the schematic and could call a match.
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR,
                          env=_magic_env(techfile=params.get("magic_tech"),
                                         rcfile=magicrc, params=params))
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "magic_extract.log"), "w").write(out)
    if not os.path.exists(out_spice):
        return _cde(objective=f"extract layout netlist for {cell}", status="failed",
                    engine="Magic", pdk_binding=binding or "none",
                    error="magic ext2spice produced no netlist; see magic_extract.log:\n"
                          + out[-1500:] + _klayout_hint, validation={"verdict": "fail"},
                    provenance={"magic": _version("magic", ["--version"]), "log": "magic_extract.log"})
    # CROSS-CHECK AGAINST THE PDK's OWN CDL. Until now this scenario reported
    # "layout netlist extracted" with no device count whatsoever, so an EMPTY
    # netlist -- the measured symptom of a missing PDK_ROOT -- was reported as a
    # clean pass and handed to LVS.
    _cdl = (params.get("cdl") or (binding.get("cdl") if isinstance(binding, dict) else None))
    _xc = _cdl_cross_check(out_spice, cell, _cdl,
                           cell_prefix=str(params.get("cell_prefix") or ""))
    _ext_cells = _parse_spice_netlist(out_spice, False,
                                      str(params.get("cell_prefix") or ""))
    _ext_total = sum(_flatten_devices(_ext_cells, cell).values()) if cell in _ext_cells else None
    if _xc and _xc["status"] == "mismatch":
        return _cde(
            objective=f"extract layout SPICE netlist for {cell}", status="failed",
            engine="Magic", pdk_binding=binding or "none",
            error=("EXTRACTION DISAGREES WITH THE PDK CDL for %s: the CDL "
                   "describes %d device(s) and the extraction produced %d. "
                   "Per-model delta: %s. The CDL ships with the same PDK as the "
                   "layout, so this is a real discrepancy -- either the "
                   "extraction is wrong or the layout does not implement the "
                   "cell the CDL describes. A netlist that disagrees with the "
                   "reference cannot be used as the layout side of LVS."
                   % (_xc["cell"], _xc["cdl_devices"], _xc["extracted_devices"],
                      _xc["delta"])),
            validation={"verdict": "fail"},
            qor={"cdl_devices": _xc["cdl_devices"],
                 "extracted_devices": _xc["extracted_devices"]},
            signoff={"cdl_cross_check": _xc},
            inputs_ref={"layout": layout, "cdl": _cdl},
            provenance={"magic": _version("magic", ["--version"]),
                        "log": "magic_extract.log"})
    if _xc is None:
        _xc_note = ("extraction NOT cross-checked against a reference netlist "
                    "(no `cdl` supplied in params or pdk_binding), so the "
                    "device content of this netlist is unverified")
    elif _xc["status"] == "not_assessable":
        _xc_note = "extraction NOT cross-checked: " + _xc["reason"]
    else:
        _xc_note = ("extraction agrees with the PDK CDL: %d device(s), matched "
                    "per model" % _xc["cdl_devices"])
    return _cde(
        objective=f"extract layout SPICE netlist for {cell}", status="completed",
        engine="Magic", pdk_binding=binding or "none",
        results={"layout_netlist": {"value": os.path.basename(out_spice), "unit": "-"},
                 "extracted_devices": {"value": _ext_total, "unit": "count"}},
        qor={"extracted_devices": _ext_total,
             "cdl_devices": (_xc or {}).get("cdl_devices"),
             "cdl_cross_check": (_xc or {}).get("status", "not_performed")},
        signoff={"layout_netlist": os.path.basename(out_spice), "report": "magic_extract.log",
                 "cdl_cross_check": _xc,
                 "cdl_cross_check_note": _xc_note,
                 "engine_selection": {"engine": "magic",
                                      "source": pol["engine_source"],
                                      "pdk_recommended": pol["pdk_recommended"]},
                 "pdk_policy_override": pol["override"]},
        inputs_ref={"layout": layout, "cdl": _cdl},
        assumptions=["ext2spice in LVS mode; feed the netlist to lvs_compare"],
        validation={"verdict": "pass",
                    "note": "layout netlist extracted; " + _xc_note},
        provenance={"magic": _version("magic", ["--version"]),
                    "runtime_s": round(elapsed, 3), "log": "magic_extract.log"},
    )


# =============================================================================
# KLayout LVS engine (scenario lvs_compare, engine=klayout)
# =============================================================================
# nangate45 binds capabilities.lvs.engine = klayout with the vendored deck
# lvs_freepdk45.lylvs. The deck EXTRACTS the layout itself (no Magic tech exists
# for this node), so the inputs are the layout GDS and a SPICE/CDL schematic.
# The schematic side needs care, all of it measured on this node (see the
# binding's lvs_findings):
#   * reference_netlist MUST be the post-P&R netlist (OpenROAD write_verilog).
#   * cell pin ORDER must come from the PDK CDL, never from cells.v:
#     cells.v declares DFF_X1(CK,D,Q,QN) while the CDL declares
#     (D CK Q QN VDD VSS) -- reusing the Verilog order mis-wires D and CK.
#   * physical-only masters (FILLCELL_*, TAPCELL_*) carry no logic and are
#     excluded from the schematic; KLayout's `align` flattens layout-only cells.
_VERILOG_EXTS_ALL = (".v", ".vg", ".gv", ".vlog", ".verilog", ".sv")
_PHYSICAL_ONLY_PATTERNS = ("FILLCELL_*", "TAPCELL_*")
_WELL_NET_NAMES = frozenset(("PWELL", "NWELL", "BULK"))
_DECK_PATCHES = ("nangate_pwell_connect_explicit",)


class _VError(Exception):
    pass


def _cdl_library(cdl_path):
    """Parse a CDL/SPICE library into {name: {pins, lines, children}}.

    `pins` is the .SUBCKT DECLARATION order -- the only order an X card may use.
    `lines` keeps the raw text (continuations included) so the block can be
    copied verbatim into the schematic."""
    lib = collections.OrderedDict()
    try:
        text = open(cdl_path, encoding="utf-8", errors="replace").read()
    except (OSError, TypeError):
        return lib
    logical = []
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln.startswith("+") and logical:
            logical[-1][0] += " " + ln[1:].strip()
            logical[-1][1].append(ln)
        else:
            logical.append([ln.rstrip(), [ln.rstrip()]])
    cur = None
    for joined, raws in logical:
        t = joined.strip()
        u = t.upper()
        if u.startswith(".SUBCKT"):
            parts = t.split()
            if len(parts) < 2:
                cur = None
                continue
            pins = []
            for p in parts[2:]:
                if "=" in p or p.upper() in ("PARAMS:", "PARAM:"):
                    break
                pins.append(p)
            cur = {"name": parts[1], "pins": pins, "lines": list(raws),
                   "children": set()}
            lib[parts[1]] = cur
            continue
        if cur is None:
            continue
        cur["lines"].extend(raws)
        if u.startswith(".ENDS"):
            cur = None
            continue
        if t[:1].upper() == "X":
            toks = [x for x in t.split() if "=" not in x and x != "/"]
            if len(toks) >= 2:
                cur["children"].add(toks[-1])
    return lib


def _lib_lookup(lib, name):
    if name in lib:
        return lib[name]
    up = str(name).upper()
    for k, v in lib.items():
        if k.upper() == up:
            return v
    return None


_VNUM_RE = re.compile(r"(?:\d+\s*)?'\s*[sS]?[bBoOdDhH]\s*[0-9a-fA-FxXzZ_?]+|\d+")
_VID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_V_DIR_KW = frozenset(("input", "output", "inout"))
_V_NET_KW = frozenset(("wire", "tri", "wand", "wor", "triand", "trior", "tri0",
                       "tri1", "supply0", "supply1", "reg", "logic", "uwire"))
_V_SKIP_KW = frozenset(("parameter", "localparam", "defparam", "genvar",
                        "integer", "real", "time", "specparam", "timeunit",
                        "timeprecision"))
_V_BEHAV_KW = frozenset(("always", "initial", "function", "task", "generate",
                         "always_comb", "always_ff", "always_latch"))


def _vtokenize(text):
    """Tokenize structural Verilog. Escaped identifiers (`\\u_rx.sc `) become
    ("eid", "u_rx.sc"); comments and (* attributes *) are dropped."""
    text = re.sub(r"(?m)^[ \t]*`.*$", "", text)
    toks, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if text.startswith("(*", i) and not text.startswith("(*)", i):
            j = text.find("*)", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "\\":
            j = i + 1
            while j < n and not text[j].isspace():
                j += 1
            toks.append(("eid", text[i + 1:j]))
            i = j
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            toks.append(("str", text[i + 1:j]))
            i = j + 1
            continue
        if c.isdigit() or c == "'":
            m = _VNUM_RE.match(text, i)
            if m:
                toks.append(("num", re.sub(r"\s+", "", m.group(0))))
                i = m.end()
                continue
        m = _VID_RE.match(text, i)
        if m:
            toks.append(("id", m.group(0)))
            i = m.end()
            continue
        toks.append(("sym", c))
        i += 1
    return toks


def _vconst_bits(s):
    """Verilog literal -> list of bit chars, MSB first ('0','1','x','z')."""
    m = re.match(r"^(\d+)?'[sS]?([bBoOdDhH])([0-9a-fA-FxXzZ_?]+)$", s)
    if not m:
        return list(format(int(s), "032b"))
    width = int(m.group(1)) if m.group(1) else None
    base, digits = m.group(2).lower(), m.group(3).replace("_", "").lower()
    digits = digits.replace("?", "z")
    if base == "d":
        bits = (format(int(digits), "b") if digits.isdigit()
                else digits[-1] * (width or 32))
    else:
        per = {"b": 1, "o": 3, "h": 4}[base]
        bits = ""
        for d in digits:
            bits += (d * per if d in "xz" else format(int(d, 16), "0%db" % per))
    if width is None:
        width = max(32, len(bits))
    if len(bits) < width:
        pad = bits[0] if bits and bits[0] in "xz" else "0"
        bits = pad * (width - len(bits)) + bits
    return list(bits[-width:])


class _VParser:
    """Recursive-descent parser for STRUCTURAL (gate-level) Verilog only.

    Behavioural constructs, operators and parameterised ranges raise _VError:
    a netlist this parser cannot read exactly must fail closed, never be
    approximated into a schematic that LVS would then 'compare'."""

    def __init__(self, toks):
        self.t, self.p = toks, 0

    def peek(self, off=0):
        q = self.p + off
        return self.t[q] if q < len(self.t) else ("eof", "")

    def take(self):
        tok = self.peek()
        self.p += 1
        return tok

    def expect(self, sym):
        tok = self.take()
        if tok != ("sym", sym):
            raise _VError("expected %r, got %r" % (sym, tok[1]))
        return tok

    def is_sym(self, sym, off=0):
        return self.peek(off) == ("sym", sym)

    def name(self):
        k, v = self.take()
        if k not in ("id", "eid"):
            raise _VError("expected identifier, got %r" % v)
        return v

    def skip_balanced(self):
        opener = self.take()[1]
        closer = {"(": ")", "[": "]", "{": "}"}[opener]
        depth = 1
        while depth and self.peek()[0] != "eof":
            k, v = self.take()
            if k == "sym" and v == opener:
                depth += 1
            elif k == "sym" and v == closer:
                depth -= 1

    def skip_statement(self):
        while self.peek()[0] != "eof" and not self.is_sym(";"):
            if self.is_sym("(") or self.is_sym("[") or self.is_sym("{"):
                self.skip_balanced()
            else:
                self.take()
        self.take()

    def int_tok(self):
        k, v = self.take()
        if k != "num" or "'" in v:
            raise _VError("non-literal range/select %r (parameterised ranges "
                          "are not supported in a gate-level netlist)" % v)
        return int(v)

    def range_(self):
        self.expect("[")
        msb = self.int_tok()
        self.expect(":")
        lsb = self.int_tok()
        self.expect("]")
        return (msb, lsb)

    def expr(self):
        k, v = self.peek()
        if k == "sym" and v == "{":
            self.take()
            if self.peek()[0] == "num" and self.is_sym("{", 1):
                n = self.int_tok()
                inner = self.expr()
                self.expect("}")
                return ("repl", n, inner)
            items = [self.expr()]
            while self.is_sym(","):
                self.take()
                items.append(self.expr())
            self.expect("}")
            return ("concat", items)
        if k == "num":
            self.take()
            return ("const", _vconst_bits(v))
        if k in ("id", "eid"):
            self.take()
            sel = None
            if self.is_sym("["):
                self.take()
                a = self.int_tok()
                if self.is_sym(":"):
                    self.take()
                    b = self.int_tok()
                    sel = ("range", a, b)
                else:
                    sel = ("bit", a)
                self.expect("]")
            return ("ref", v, sel)
        raise _VError("unsupported expression token %r (only nets, bit/part "
                      "selects, concatenations and literals are structural)" % v)

    def module(self):
        mod = {"name": self.name(), "ports": [], "dirs": {}, "ranges": {},
               "instances": [], "assigns": [], "supply": {}}
        if self.is_sym("#"):
            self.take()
            self.skip_balanced()
        if self.is_sym("("):
            self.take()
            cur_dir, cur_rng = None, None
            while not self.is_sym(")"):
                k, v = self.peek()
                if k == "id" and v in _V_DIR_KW:
                    self.take()
                    cur_dir, cur_rng = v, None
                    continue
                if k == "id" and (v in _V_NET_KW or v == "signed"):
                    self.take()
                    continue
                if self.is_sym("["):
                    cur_rng = self.range_()
                    continue
                if self.is_sym(","):
                    self.take()
                    continue
                if self.is_sym("."):
                    raise _VError("named port expressions in a module header "
                                  "are not supported")
                nm = self.name()
                mod["ports"].append(nm)
                if cur_dir:
                    mod["dirs"][nm] = cur_dir
                    if cur_rng:
                        mod["ranges"][nm] = cur_rng
            self.take()
        self.expect(";")
        while True:
            k, v = self.peek()
            if k == "eof":
                raise _VError("module %s: missing endmodule" % mod["name"])
            if k == "id" and v == "endmodule":
                self.take()
                return mod
            if k == "id" and (v in _V_DIR_KW or v in _V_NET_KW):
                self.decl(mod)
            elif k == "id" and v == "assign":
                self.take()
                if self.is_sym("#"):
                    self.take()
                    if self.is_sym("("):
                        self.skip_balanced()
                    else:
                        self.take()
                while True:
                    lhs = self.expr()
                    self.expect("=")
                    mod["assigns"].append((lhs, self.expr()))
                    if self.is_sym(","):
                        self.take()
                        continue
                    self.expect(";")
                    break
            elif k == "id" and v in _V_SKIP_KW:
                self.skip_statement()
            elif k == "id" and v == "specify":
                while self.peek()[0] != "eof" and self.peek() != ("id", "endspecify"):
                    self.take()
                self.take()
            elif k == "id" and v in _V_BEHAV_KW:
                raise _VError("module %s contains behavioural construct %r; "
                              "LVS needs a structural gate-level netlist"
                              % (mod["name"], v))
            elif k in ("id", "eid"):
                self.instances(mod)
            else:
                raise _VError("module %s: unexpected token %r" % (mod["name"], v))

    def decl(self, mod):
        kind = self.take()[1]
        is_dir = kind in _V_DIR_KW
        rng = None
        while True:
            k, v = self.peek()
            if k == "id" and (v in _V_NET_KW or v in ("signed", "scalared", "vectored")):
                self.take()
                if v in ("supply0", "supply1"):
                    kind = v
                continue
            if self.is_sym("("):           # drive strength
                self.skip_balanced()
                continue
            break
        if self.is_sym("["):
            rng = self.range_()
        while True:
            nm = self.name()
            if self.is_sym("["):           # unpacked array -> not structural
                raise _VError("array declaration %r is not supported" % nm)
            if is_dir:
                mod["dirs"][nm] = kind
            if rng:
                mod["ranges"][nm] = rng
            if kind in ("supply0", "supply1"):
                mod["supply"][nm] = kind[-1]
            if self.is_sym("="):
                self.take()
                mod["assigns"].append((("ref", nm, None), self.expr()))
            if self.is_sym(","):
                self.take()
                continue
            self.expect(";")
            return

    def instances(self, mod):
        master = self.name()
        if self.is_sym("#"):
            self.take()
            self.skip_balanced()
        while True:
            inst = {"master": master, "name": self.name(), "named": None,
                    "positional": None}
            if self.is_sym("["):
                raise _VError("instance array %s[...] is not supported" % inst["name"])
            self.expect("(")
            if self.is_sym("."):
                named = collections.OrderedDict()
                while True:
                    self.expect(".")
                    if self.is_sym("*"):
                        raise _VError("wildcard .* connection is not supported")
                    pin = self.name()
                    self.expect("(")
                    named[pin] = None if self.is_sym(")") else self.expr()
                    self.expect(")")
                    if self.is_sym(","):
                        self.take()
                        continue
                    break
                inst["named"] = named
            elif not self.is_sym(")"):
                pos = []
                while True:
                    pos.append(None if (self.is_sym(",") or self.is_sym(")"))
                               else self.expr())
                    if self.is_sym(","):
                        self.take()
                        continue
                    break
                inst["positional"] = pos
            else:
                inst["named"] = collections.OrderedDict()
            self.expect(")")
            mod["instances"].append(inst)
            if self.is_sym(","):
                self.take()
                continue
            self.expect(";")
            return


def _vparse_modules(text):
    """Return OrderedDict{name: module} for every module in *text*."""
    psr = _VParser(_vtokenize(text))
    mods = collections.OrderedDict()
    while psr.peek()[0] != "eof":
        k, v = psr.take()
        if k == "id" and v in ("module", "macromodule"):
            mod = psr.module()
            mods[mod["name"]] = mod
    return mods


def _vspan(a, b):
    return range(a, b - 1, -1) if a >= b else range(a, b + 1)


def _vbits(mod, ast):
    """Flatten an expression AST to bit keys, MSB first:
    ("n", name, index-or-None) for a net bit, ("c", "0"/"1"/"x"/"z") for a
    literal bit."""
    if ast is None:
        return []
    kind = ast[0]
    if kind == "ref":
        name, sel = ast[1], ast[2]
        if sel is None:
            rng = mod["ranges"].get(name)
            if rng is None:
                return [("n", name, None)]
            return [("n", name, i) for i in _vspan(rng[0], rng[1])]
        if sel[0] == "bit":
            return [("n", name, sel[1])]
        return [("n", name, i) for i in _vspan(sel[1], sel[2])]
    if kind == "const":
        return [("c", b) for b in ast[1]]
    if kind == "concat":
        out = []
        for a in ast[1]:
            out += _vbits(mod, a)
        return out
    if kind == "repl":
        return _vbits(mod, ast[2]) * ast[1]
    raise _VError("unknown expression kind %r" % (kind,))



def _spice_namer():
    """Map net keys to unique SPICE-safe names. KLayout's SPICE reader is
    CASE-INSENSITIVE, so uniqueness is enforced on the upper-cased name:
    two Verilog nets differing only in case must not be silently shorted."""
    names, used = {}, set()

    def _name(key):
        if key in names:
            return names[key]
        base = key if isinstance(key, str) else (
            key[1] if key[2] is None else "%s[%d]" % (key[1], key[2]))
        s = re.sub(r"[^A-Za-z0-9_\[\]\.\$<>]", "_", str(base)) or "n"
        if s[0].isdigit():
            s = "n_" + s
        cand, k = s, 1
        while cand.upper() in used:
            cand = "%s__%d" % (s, k)
            k += 1
        used.add(cand.upper())
        names[key] = cand
        return cand
    return _name


def _spice_wrap(head, tokens, per_line=12):
    out, line = [], head
    for i, tok in enumerate(tokens):
        if i and i % per_line == 0:
            out.append(line)
            line = "+"
        line += " " + tok
    out.append(line)
    return out


def _verilog_to_spice(verilog_path, cdl_path, top=None, out_path=None,
                      power_net="VDD", ground_net="VSS",
                      physical_only=_PHYSICAL_ONLY_PATTERNS):
    """Convert a gate-level Verilog netlist into a SPICE schematic for KLayout LVS.

    Pin ORDER comes from the PDK CDL (.SUBCKT declaration), never from the
    Verilog cell models; the used CDL subckts are copied verbatim ahead of the
    design subckt(s) so KLayout compares hierarchically. Physical-only masters
    are excluded and counted. `assign` aliases are merged with a union-find
    whose representative prefers a top-level port name, so aliased ports become
    repeated names in the .SUBCKT header (KLayout's reader joins same-named
    pins onto one net).

    Returns a report dict; report["ok"] is False whenever ANY instance or
    connection could not be expressed exactly (fail closed -- an approximate
    schematic would make the comparison meaningless)."""
    import fnmatch
    rep = {"ok": False, "errors": [], "top": None, "modules": [],
           "instances_total": 0, "instances_emitted": 0,
           "excluded_physical": {}, "excluded_physical_no_cdl": {},
           "masters": {}, "unresolved_masters": {}, "pin_errors": [],
           "constant_connections": [], "implicit_power_connections": 0,
           "unconnected_pins": 0, "aliased_port_groups": [],
           "cdl_subckts_included": 0, "pin_order_source": "CDL",
           "spice": out_path}
    errs = rep["errors"]

    def _err(msg):
        if len(errs) < 50:
            errs.append(msg)

    try:
        text = open(verilog_path, encoding="utf-8", errors="replace").read()
    except (OSError, TypeError) as e:
        _err("cannot read Verilog netlist %s: %s" % (verilog_path, e))
        return rep
    try:
        mods = _vparse_modules(text)
    except _VError as e:
        _err("Verilog parse error: %s" % e)
        return rep
    if not mods:
        _err("no module found in %s" % verilog_path)
        return rep
    lib = _cdl_library(cdl_path)
    if not lib:
        _err("PDK CDL %s is unreadable or declares no .SUBCKT" % cdl_path)
        return rep
    if top:
        if top not in mods:
            _err("top module %r not found in the Verilog netlist (modules: %s)"
                 % (top, ", ".join(list(mods)[:10])))
            return rep
    else:
        used = {i["master"] for m in mods.values() for i in m["instances"]}
        roots = [m for m in mods if m not in used]
        if len(roots) != 1:
            _err("cannot infer the top module (candidates: %s); pass `top`"
                 % ", ".join(roots[:10]))
            return rep
        top = roots[0]
    rep["top"] = top

    order, state = [], {}

    def _visit(name, depth=0):
        if state.get(name) == 2:
            return
        if state.get(name) == 1 or depth > 64:
            raise _VError("recursive module instantiation at %s" % name)
        state[name] = 1
        for inst in mods[name]["instances"]:
            if inst["master"] in mods:
                _visit(inst["master"], depth + 1)
        state[name] = 2
        order.append(name)
    try:
        _visit(top)
    except _VError as e:
        _err(str(e))
        return rep
    rep["modules"] = list(order)

    supply_keys = {("n", power_net, None), ("n", ground_net, None)}
    extra_pins = {}          # module -> [power/ground nets appended to header]
    used_cells = collections.OrderedDict()
    blocks = []
    masters = collections.Counter()
    excl = collections.Counter()
    excl_nocdl = collections.Counter()
    unresolved = collections.Counter()

    for mname in order:
        mod = mods[mname]
        parent = {}

        def find(k):
            root = k
            while parent.get(root, root) != root:
                root = parent[root]
            while parent.get(k, k) != root:
                parent[k], k = root, parent[k]
            return root

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        port_bits = []
        for pn in mod["ports"]:
            port_bits += _vbits(mod, ("ref", pn, None))
        port_rank = {}
        for i, k in enumerate(port_bits):
            port_rank.setdefault(k, i)
        for nm, val in mod["supply"].items():
            union(("n", ground_net if val == "0" else power_net, None), ("n", nm, None))
        for lhs, rhs in mod["assigns"]:
            try:
                lb, rb = _vbits(mod, lhs), _vbits(mod, rhs)
            except _VError as e:
                _err("%s: assign: %s" % (mname, e))
                continue
            if len(lb) != len(rb):
                _err("%s: assign width mismatch (%d vs %d bits)" % (mname, len(lb), len(rb)))
                continue
            for a, b in zip(lb, rb):
                if a[0] == "c" or b[0] == "c":
                    rep["constant_connections"].append("%s: assign %s = 1'b%s" % (
                        mname, a[1] if a[0] == "n" else b[1], (b if b[0] == "c" else a)[1]))
                    continue
                union(a, b)
        groups = collections.defaultdict(list)
        for k in list(parent) + port_bits:
            groups[find(k)].append(k)
        best = {}
        for root, members in groups.items():
            members = list(dict.fromkeys(members))
            best[root] = min(members, key=lambda k: (k not in port_rank,
                                                     port_rank.get(k, 0), str(k)))
            ports_in = [k for k in members if k in port_rank]
            if mname == top and len(ports_in) > 1:
                rep["aliased_port_groups"].append(sorted(
                    (k[1] if k[2] is None else "%s[%d]" % (k[1], k[2])) for k in ports_in))
        namer = _spice_namer()
        inst_namer = _spice_namer()
        nc = [0]

        def net_name(k):
            return namer(best.get(find(k), find(k)))

        def nc_name(inst, pin):
            nc[0] += 1
            rep["unconnected_pins"] += 1
            return namer("__nc_%s_%s" % (inst, pin))

        implicit_used = []
        lines = []
        for inst in mod["instances"]:
            rep["instances_total"] += 1
            master, iname = inst["master"], inst["name"]
            if any(fnmatch.fnmatchcase(master, p) for p in physical_only):
                excl[master] += 1
                continue
            sub = mods.get(master)
            cell = None if sub else _lib_lookup(lib, master)
            if sub is None and cell is None:
                bits = []
                try:
                    for ast in (inst["named"] or {}).values():
                        bits += _vbits(mod, ast)
                    for ast in inst["positional"] or []:
                        bits += _vbits(mod, ast)
                except _VError:
                    bits = [("n", "?", None)]
                signal = [b for b in bits if b[0] == "c" or find(b) not in
                          {find(s) for s in supply_keys}]
                if not signal:
                    excl_nocdl[master] += 1
                else:
                    unresolved[master] += 1
                continue
            if sub is not None:
                pins = []
                for pn in sub["ports"]:
                    pins.append((pn, len(_vbits(sub, ("ref", pn, None)))))
            else:
                pins = [(p, 1) for p in cell["pins"]]
            conns = collections.OrderedDict()
            if inst["positional"] is not None:
                if cell is not None:
                    # Library cells are ordered by cells.v in Verilog but by
                    # the CDL in SPICE; a positional map would silently mis-wire.
                    rep["pin_errors"].append("%s (%s): positional connections to a "
                                             "library cell cannot be mapped to CDL "
                                             "pin order" % (iname, master))
                    continue
                if len(inst["positional"]) > len(pins):
                    rep["pin_errors"].append("%s (%s): %d positional connections "
                                             "for %d ports" % (iname, master,
                                                               len(inst["positional"]), len(pins)))
                    continue
                for (pn, _w), ast in zip(pins, inst["positional"]):
                    conns[pn] = ast
            else:
                pin_lookup = {p.upper(): p for p, _w in pins}
                bad = [p for p in inst["named"] if p.upper() not in pin_lookup]
                if bad:
                    rep["pin_errors"].append("%s (%s): pin(s) %s not declared by the %s"
                                             % (iname, master, ", ".join(bad),
                                                "module" if sub else "CDL subckt"))
                    continue
                for p, ast in inst["named"].items():
                    conns[pin_lookup[p.upper()]] = ast
            nets, ok = [], True
            for pn, width in pins:
                ast = conns.get(pn)
                try:
                    bits = _vbits(mod, ast) if ast is not None else []
                except _VError as e:
                    rep["pin_errors"].append("%s.%s: %s" % (iname, pn, e))
                    ok = False
                    break
                if not bits:
                    if width == 1 and pn in (power_net, ground_net):
                        rep["implicit_power_connections"] += 1
                        implicit_used.append(pn)
                        nets.append(net_name(("n", pn, None)))
                    else:
                        nets += [nc_name(iname, pn) for _ in range(width)]
                    continue
                if len(bits) != width:
                    rep["pin_errors"].append("%s.%s: %d-bit connection to a %d-bit pin"
                                             % (iname, pn, len(bits), width))
                    ok = False
                    break
                for b in bits:
                    if b[0] == "c":
                        rep["constant_connections"].append(
                            "%s.%s = 1'b%s (no tie cell; the layout cannot "
                            "realise a literal)" % (iname, pn, b[1]))
                        ok = False
                        break
                    nets.append(net_name(b))
                if not ok:
                    break
            if not ok:
                continue
            if sub is not None:
                for ep in extra_pins.get(master, []):
                    implicit_used.append(ep)
                    nets.append(net_name(("n", ep, None)))
                lines += _spice_wrap("X" + inst_namer(iname), nets + [master])
            else:
                masters[cell["name"]] += 1
                used_cells[cell["name"]] = cell
                lines += _spice_wrap("X" + inst_namer(iname), nets + [cell["name"]])
            rep["instances_emitted"] += 1
        header = [net_name(k) for k in port_bits]
        extras = []
        for ep in dict.fromkeys(implicit_used):
            key = ("n", ep, None)
            if not any(find(k) == find(key) for k in port_bits):
                extras.append(ep)
                header.append(net_name(key))
        extra_pins[mname] = extras
        blk = ["* module %s: %d port bit(s)%s" % (
            mname, len(port_bits),
            ("; implicit supply pin(s) appended: " + " ".join(extras)) if extras else "")]
        blk += _spice_wrap(".SUBCKT " + mname, header)
        blk += lines
        blk.append(".ENDS " + mname)
        blocks.append(blk)

    # Transitive closure over CDL children (a library cell may instantiate others).
    queue = list(used_cells)
    while queue:
        cname = queue.pop()
        for child in sorted(_lib_lookup(lib, cname)["children"]):
            c = _lib_lookup(lib, child)
            if c is None:
                unresolved[child] += 1
            elif c["name"] not in used_cells:
                used_cells[c["name"]] = c
                queue.append(c["name"])
    rep.update({"masters": dict(masters), "excluded_physical": dict(excl),
                "excluded_physical_no_cdl": dict(excl_nocdl),
                "unresolved_masters": dict(unresolved),
                "cdl_subckts_included": len(used_cells)})
    if unresolved:
        _err("master(s) with no CDL subckt and signal connections: %s"
             % ", ".join("%s x%d" % kv for kv in sorted(unresolved.items())))
    if rep["pin_errors"]:
        _err("%d instance(s) have pin errors (first: %s)"
             % (len(rep["pin_errors"]), rep["pin_errors"][0]))
    if rep["constant_connections"]:
        _err("%d literal connection(s) (first: %s)" % (
            len(rep["constant_connections"]), rep["constant_connections"][0]))
    rep["pin_errors"] = rep["pin_errors"][:50]
    rep["constant_connections"] = rep["constant_connections"][:50]
    out = ["* SPICE schematic generated by chip-lvs from %s" % os.path.basename(str(verilog_path)),
           "* pin order: PDK CDL %s (NOT the Verilog cell models)" % os.path.basename(str(cdl_path)),
           "* physical-only masters excluded: %s" % (
               ", ".join("%s x%d" % kv for kv in sorted({**excl, **excl_nocdl}.items())) or "none"),
           ""]
    lib_order = [n for n in lib if n in used_cells]
    for n in lib_order:
        out += lib[n]["lines"]
        out.append("")
    for blk in blocks:
        out += blk
        out.append("")
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(out) + "\n")
        except OSError as e:
            _err("cannot write schematic %s: %s" % (out_path, e))
    rep["ok"] = not errs
    return rep


def _spice_schematic_prepare(sch_path, cdl_path, out_path):
    """Normalise a SPICE/CDL schematic and append the PDK CDL subckts it
    instantiates but does not define, so KLayout can compare hierarchically.
    Masters defined nowhere are returned as unresolved (fail closed upstream)."""
    rep = {"ok": False, "errors": [], "masters": {}, "unresolved_masters": {},
           "cdl_subckts_included": 0, "pin_order_source": "schematic", "spice": out_path}
    try:
        text = open(sch_path, encoding="utf-8", errors="replace").read()
    except (OSError, TypeError) as e:
        rep["errors"].append("cannot read schematic %s: %s" % (sch_path, e))
        return rep
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    own = _cdl_library(sch_path)
    lib = _cdl_library(cdl_path) if cdl_path else collections.OrderedDict()
    masters = collections.Counter()
    for cell in own.values():
        for ln in cell["lines"]:
            t = ln.strip()
            if t[:1].upper() == "X":
                toks = [x for x in t.split() if "=" not in x and x != "/"]
                if len(toks) >= 2 and toks[-1] not in own:
                    masters[toks[-1]] += 1
    need, unresolved = collections.OrderedDict(), collections.Counter()
    queue = list(masters)
    while queue:
        m = queue.pop()
        c = _lib_lookup(lib, m)
        if c is None:
            unresolved[m] += masters.get(m, 1)
            continue
        if c["name"] in need or c["name"] in own:
            continue
        need[c["name"]] = c
        queue += sorted(c["children"])
    out = ["* schematic normalised by chip-lvs; %d PDK CDL subckt(s) appended" % len(need), ""]
    for n in [n for n in lib if n in need]:
        out += lib[n]["lines"] + [""]
    out.append(text)
    try:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
    except OSError as e:
        rep["errors"].append("cannot write schematic %s: %s" % (out_path, e))
    rep.update({"masters": dict(masters), "unresolved_masters": dict(unresolved),
                "cdl_subckts_included": len(need)})
    if unresolved:
        rep["errors"].append("master(s) defined neither in the schematic nor in "
                             "the PDK CDL: %s" % ", ".join(sorted(unresolved)))
    rep["ok"] = not rep["errors"]
    return rep


def _lvs_cell_coverage(masters, cdl_lib, deck_text, binding):
    """Binding cell_coverage enforcement. Masters outside the deck's asserted
    connect_implicit set, outside the CDL, or matching the binding's `omitted`
    patterns make the comparison NOT ASSESSABLE (coverage), never a mismatch."""
    import fnmatch
    asserted = set(re.findall(r'connect_implicit\(\s*"([^"]+)"', deck_text or ""))
    cov = ((((binding or {}).get("capabilities") or {}).get("lvs") or {})
           .get("cell_coverage") or {})
    omitted = [str(o).split()[0] for o in (cov.get("omitted") or []) if str(o).strip()]
    names = sorted(masters)
    outside_cdl = [m for m in names if cdl_lib and _lib_lookup(cdl_lib, m) is None]
    outside_asserted = [m for m in names if asserted and m not in asserted]
    omitted_hits = [m for m in names
                    if any(fnmatch.fnmatchcase(m, p) for p in omitted)]
    return {"ok": not (outside_cdl or outside_asserted or omitted_hits),
            "masters_checked": len(names),
            "asserted_set_size": len(asserted),
            "asserted_set_source": ("deck connect_implicit list" if asserted
                                    else "none in deck; CDL membership only"),
            "outside_cdl": outside_cdl, "outside_deck_asserted_set": outside_asserted,
            "binding_omitted_hits": omitted_hits, "binding_omitted_patterns": omitted,
            "enforcement": cov.get("enforcement")}



_LVSDB_KEYS = {"layout": "J", "reference": "H", "xref": "Z", "circuit": "X",
               "net": "N", "name": "I", "pin": "P", "device": "D", "log": "L",
               "entry": "M", "description": "B", "top": "W"}
_LVSDB_STATUS = {"0": "mismatch", "mismatch": "mismatch", "1": "match",
                 "match": "match", "X": "nomatch", "nomatch": "nomatch",
                 "W": "warning", "warning": "warning", "S": "skipped",
                 "skipped": "skipped"}
_LVSDB_SEVERITY = {"I": "info", "info": "info", "W": "warning",
                   "warning": "warning", "E": "error", "error": "error"}
_LVSDB_TOKEN_RE = re.compile(
    r"\s+|,|#[^\n]*|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[()]|[^\s(),'\"]+")


class _SNode(object):
    __slots__ = ("key", "items")

    def __init__(self, key):
        self.key, self.items = key, []

    def k(self):
        return _LVSDB_KEYS.get(self.key, self.key)

    def atoms(self):
        return [x for x in self.items if isinstance(x, str)]

    def nodes(self, key=None):
        return [x for x in self.items if isinstance(x, _SNode)
                and (key is None or x.k() == key)]


def _sexpr_parse(text):
    """Parse KLayout's lvsdb/l2n s-expression dialect: `key(items...)`, where a
    `(` directly after a word opens a node keyed by that word and a bare `(`
    opens an anonymous node (`()` is an absent name/id)."""
    root = _SNode("")
    stack = [root]
    prev_word_end = -1
    for m in _LVSDB_TOKEN_RE.finditer(text):
        tok = m.group(0)
        if not tok or tok.isspace() or tok == "," or tok.startswith("#"):
            continue
        if tok == "(":
            cur = stack[-1]
            key = ""
            if (prev_word_end == m.start() and cur.items
                    and isinstance(cur.items[-1], str)):
                key = cur.items.pop()
            node = _SNode(key)
            cur.items.append(node)
            stack.append(node)
            prev_word_end = -1
            continue
        if tok == ")":
            if len(stack) > 1:
                stack.pop()
            prev_word_end = -1
            continue
        if tok[0] in "'\"":
            body = tok[1:-1]
            stack[-1].items.append(re.sub(r"\\(.)", r"\1", body))
            prev_word_end = -1
            continue
        stack[-1].items.append(tok)
        prev_word_end = m.end()
    return root


def _lvsdb_names(section):
    """{circuit: {net_id: net_name}} from a J (layout) or H (reference) node."""
    out = {}
    for c in section.nodes("X"):
        a = c.atoms()
        if not a:
            continue
        nets = {}
        for n in c.nodes("N"):
            na = n.atoms()
            nm = n.nodes("I")
            if na and nm and nm[0].atoms():
                nets[na[0]] = nm[0].atoms()[0]
        out[a[0]] = nets
    return out


def _lvsdb_pair(node):
    """Split an xref entry into ([name_a, name_b], status). An absent side is
    `()` and comes back as None."""
    names, status = [], None
    rest = list(node.items)
    while rest and len(names) < 2:
        it = rest[0]
        if isinstance(it, str):
            names.append(it)
        elif it.key == "" and not it.items:
            names.append(None)
        else:
            break
        rest.pop(0)
    for it in rest:
        if isinstance(it, str) and it in _LVSDB_STATUS:
            status = _LVSDB_STATUS[it]
            break
        if isinstance(it, _SNode):
            break
    while len(names) < 2:
        names.append(None)
    return names, status


def _lvsdb_messages(node):
    out = []
    for b in node.nodes("B"):
        out += [("info", t) for t in b.atoms()]
    for lg in node.nodes("L"):
        for e in lg.nodes("M"):
            sev = next((_LVSDB_SEVERITY[a] for a in e.atoms() if a in _LVSDB_SEVERITY), "info")
            for b in e.nodes("B"):
                out += [(sev, t) for t in b.atoms()]
    return out


def _parse_lvsdb(path):
    """Parse a KLayout .lvsdb into compare counts. Returns None if unreadable.

    Counts are of xref entries whose status is `mismatch` or `nomatch`; a
    `skipped` circuit was NOT compared and is reported as such, never as a
    match."""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except (OSError, TypeError):
        return None
    root = _sexpr_parse(text)
    lay_names, ref_names, xref, top = {}, {}, None, None
    for n in root.nodes():
        if n.k() == "J":
            lay_names = _lvsdb_names(n)
            w = n.nodes("W")
            if w and w[0].atoms():
                top = w[0].atoms()[0]
        elif n.k() == "H":
            ref_names = _lvsdb_names(n)
        elif n.k() == "Z":
            xref = n
    if xref is None:
        return {"xref_present": False}
    bad = ("mismatch", "nomatch")
    res = {"xref_present": True, "top_circuit": top, "circuits": 0,
           "circuits_matched": 0, "circuits_mismatched": [], "circuits_skipped": [],
           "mismatched_nets": 0, "mismatched_devices": 0, "mismatched_pins": 0,
           "mismatched_subcircuits": 0, "warnings": 0,
           "unmatched_layout_nets": collections.Counter(),
           "unmatched_reference_nets": collections.Counter(),
           "messages": collections.Counter(), "per_circuit": []}
    for msg in _lvsdb_messages(xref):
        res["messages"]["%s: %s" % msg] += 1
    for c in xref.nodes("X"):
        (la, ra), status = _lvsdb_pair(c)
        res["circuits"] += 1
        pc = {"layout": la, "reference": ra, "status": status, "nets": 0,
              "devices": 0, "pins": 0, "subcircuits": 0, "well_signature": False,
              "messages": []}
        for sev, msg in _lvsdb_messages(c):
            res["messages"]["%s: %s" % (sev, msg)] += 1
            if len(pc["messages"]) < 10:
                pc["messages"].append(msg)
            if re.search(r"\b(PWELL|NWELL|BULK)\b", msg):
                pc["well_signature"] = True
        for z in c.nodes("Z"):
            for e in z.items:
                if not isinstance(e, _SNode) or e.k() not in ("N", "D", "P", "X"):
                    continue
                (ia, ib), st = _lvsdb_pair(e)
                if st == "warning":
                    res["warnings"] += 1
                if st not in bad:
                    continue
                kind = {"N": "nets", "D": "devices", "P": "pins", "X": "subcircuits"}[e.k()]
                pc[kind] += 1
                if e.k() == "N":
                    ln = lay_names.get(la, {}).get(ia) if ia else None
                    rn = ref_names.get(ra, {}).get(ib) if ib else None
                    if ln:
                        res["unmatched_layout_nets"][ln] += 1
                    if rn:
                        res["unmatched_reference_nets"][rn] += 1
                    if (ln or "").upper() in _WELL_NET_NAMES or (rn or "").upper() in _WELL_NET_NAMES:
                        pc["well_signature"] = True
        for kind, key in (("nets", "mismatched_nets"), ("devices", "mismatched_devices"),
                          ("pins", "mismatched_pins"), ("subcircuits", "mismatched_subcircuits")):
            res[key] += pc[kind]
        if status is None:
            status = "mismatch" if (pc["nets"] or pc["devices"] or pc["pins"]
                                    or pc["subcircuits"]) else "match"
            pc["status"] = status + " (derived)"
        if status == "skipped":
            res["circuits_skipped"].append(la or ra)
        elif status in bad or la is None or ra is None:
            res["circuits_mismatched"].append(la or ra)
        else:
            res["circuits_matched"] += 1
        if status != "match" or pc["nets"] or pc["devices"] or pc["pins"]:
            # independent = a defect of its own that is not a well-net symptom;
            # a circuit whose only defects are mismatched SUBCIRCUITS inherits
            # its status from its children and is not counted twice.
            pc["independent_defect"] = bool(
                (pc["nets"] or pc["devices"] or pc["pins"] or la is None or ra is None)
                and not pc["well_signature"])
            if len(res["per_circuit"]) < 200:
                res["per_circuit"].append(pc)
    res["unmatched_layout_nets"] = dict(res["unmatched_layout_nets"].most_common(50))
    res["unmatched_reference_nets"] = dict(res["unmatched_reference_nets"].most_common(50))
    res["messages"] = dict(res["messages"].most_common(50))
    return res


_KLAYOUT_LOG_MSG_RE = re.compile(
    r"(?i)(not matching any net|making a better match|must be connected further up|"
    r"must-connect|netlists? (?:don't|do not) match|netlists match)")


def _klayout_log_messages(text):
    c = collections.Counter()
    for ln in (text or "").splitlines():
        if _KLAYOUT_LOG_MSG_RE.search(ln):
            c[re.sub(r"\s+", " ", ln.strip())[:300]] += 1
    return dict(c.most_common(50))


def _deck_rd_vars(deck_text):
    """Resolve the deck's -rd variable names FROM THE DECK TEXT. Each role is
    bound only to a `$var` the deck actually reads; the lvsdb role is bound only
    when the deck feeds it to report_lvs (this deck's `$report` goes to the DRC
    `report()` call, and passing it would SUPPRESS the lvsdb)."""
    used = set(re.findall(r"\$([A-Za-z_]\w*)", deck_text or "")) - {"stdout", "stderr"}

    def _pick(cands):
        return next((c for c in cands if c in used), None)
    lvsdb_m = re.search(r"report_lvs\(\s*\$([A-Za-z_]\w*)", deck_text or "")
    return {"used": sorted(used),
            "layout": _pick(("input", "in_gds", "layout", "gds", "gds_file", "source")),
            "schematic": _pick(("schematic", "in_netlist", "netlist", "reference",
                                "cir_file", "spice", "cdl")),
            "target_netlist": _pick(("target_netlist", "extracted_netlist",
                                     "out_netlist", "target")),
            "lvsdb": lvsdb_m.group(1) if lvsdb_m else None,
            "top": _pick(("top", "top_cell", "topcell", "cell"))}


def _patch_deck_nangate_pwell(deck_text, top):
    """Opt-in remedy documented in the nangate45 binding (lvs_findings.correct_fix):
    add PWELL to the Nangate branch's connect_explicit list (matching the OpenRAM
    branch, which already names it) and discharge the must-connect at the design
    top cell. Returns (patched_text, unified_diff) or (None, reason).

    Anchors must match EXACTLY ONCE; a deck that drifted from the reviewed
    version is refused rather than patched by guesswork."""
    import difflib
    src = deck_text.replace("\r\n", "\n")
    lines = src.split("\n")
    target = 'connect_explicit(pat, [ "BULK", "VSS" ])'
    hits = [i for i, ln in enumerate(lines) if ln.strip() == target]
    if len(hits) != 1:
        return None, ("anchor %r found %d time(s) (expected exactly 1); the deck "
                      "differs from the reviewed version" % (target, len(hits)))
    i = hits[0]
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    end = next((k for k in range(i + 1, min(i + 6, len(lines)))
                if lines[k].strip() == "end"), None)
    if end is None:
        return None, "could not find the `end` of the Nangate connect_explicit loop"
    new = list(lines)
    new[i] = indent + 'connect_explicit(pat, [ "BULK", "PWELL", "VSS" ])'
    new[end + 1:end + 1] = [
        "# --- chip-lvs deck_patch nangate_pwell_connect_explicit (opt-in) ---",
        "# Tapless library: PWELL cannot join VSS geometrically, so declare it",
        "# (as the OpenRAM branch above already does) and discharge the",
        "# must-connect obligation at the design top cell.",
        'connect_explicit("%s", [ "NWELL", "VDD" ])' % top,
        'connect_explicit("%s", [ "BULK", "PWELL", "VSS" ])' % top,
    ]
    diff = "".join(difflib.unified_diff(
        [x + "\n" for x in lines], [x + "\n" for x in new],
        "lvs_deck.orig", "lvs_deck.patched", n=1))
    return "\n".join(new), diff



def _klayout_bin():
    return shutil.which("klayout")


def _klayout_version_str():
    kl = _klayout_bin()
    return _version(kl, ["-v"]) if kl else "unavailable"


def _sha256_file(path):
    h = _hash_input_file(path)
    return h["sha256"] if h else None


def _klayout_preflight(klayout, layout, want_top, run_dir):
    """Read the layout with KLayout's own reader: top-cell count/name and the
    number of text labels on the top cell (ports LVS can match by name)."""
    out_json = os.path.join(run_dir, "preflight.json")
    script = os.path.join(run_dir, "preflight.py")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write("""import json, pya
ly = pya.Layout()
ly.read(%s)
tops = [c.name for c in ly.top_cells()]
want = %s
tc = ly.cell(want) if want else (ly.top_cells()[0] if len(tops) == 1 else None)
labels = 0
if tc is not None:
    for li in ly.layer_indexes():
        for _s in tc.shapes(li).each(pya.Shapes.STexts):
            labels += 1
open(%s, "w").write(json.dumps({"top_cells": tops[:20], "top_cell_count": len(tops),
    "dbu": ly.dbu, "top_found": tc is not None, "top_labels": labels,
    "layers": len(list(ly.layer_indexes()))}))
""" % (json.dumps(str(layout)), json.dumps(want_top), json.dumps(out_json)))
    cmd = [klayout, "-b", "-r", script]
    _save_run_command(cmd)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=run_dir, timeout=1800)
        log = proc.stdout + "\n" + proc.stderr
    except subprocess.TimeoutExpired:
        return None, "KLayout layout preflight timed out"
    with open(os.path.join(_OUTPUT_DIR, "klayout_preflight.log"), "w", encoding="utf-8") as f:
        f.write(log)
    try:
        return json.load(open(out_json, encoding="utf-8")), None
    except (OSError, ValueError):
        return None, "KLayout could not read the layout; see klayout_preflight.log:\n" + log[-1200:]


def _lvs_compare_klayout(params, binding, pol):
    """KLayout LVS: `klayout -b -r <deck> -rd <var>=...` with the variable names
    read from the deck, then the outcome parsed from the .lvsdb + log."""
    t0 = time.time()
    if not isinstance(binding, dict):
        binding = {}
    sel = {"engine": "klayout", "source": pol["engine_source"],
           "pdk_recommended": pol["pdk_recommended"]}
    eng = {"engine": "KLayout", "engine_version": _klayout_version_str(),
           "pdk_binding": binding or "none"}

    def _fail(error, verdict="fail", signoff=None, **kw):
        so = {"engine_selection": sel, "pdk_policy_override": pol["override"]}
        so.update(signoff or {})
        v = {"verdict": verdict, "note": error.split("\n")[0][:400]}
        v.update(kw.pop("validation_extra", {}))
        return _cde(objective="LVS (KLayout)", status="failed", error=error,
                    validation=v, signoff=so, **eng, **kw)

    klayout = _klayout_bin()
    if not klayout:
        return _fail("KLayout is the required LVS engine (source: %s) but is not on "
                     "PATH in this tool image. No comparison was performed -- this "
                     "is a tool-provisioning gap, NOT a layout/schematic mismatch."
                     % pol["engine_source"], verdict="not_assessable",
                     validation_extra={"reason": "klayout absent from tool image",
                                       "remediation": "provision KLayout"})
    cap = (((binding.get("capabilities") or {}).get("lvs")) or {})
    layout = params.get("layout") or params.get("layout_gds") or params.get("gds")
    sch = params.get("schematic_netlist") or params.get("source_netlist")
    deck = (params.get("setup") or params.get("lvs_rules") or params.get("lvs_deck")
            or binding.get("lvs_rules"))
    cdl = params.get("cdl") or binding.get("cdl")
    top = params.get("top") or params.get("schematic_cell") or params.get("layout_cell")
    deck_patch = params.get("deck_patch")
    power_net = str(params.get("power_net") or binding.get("power_net") or "VDD")
    ground_net = str(params.get("ground_net") or binding.get("ground_net") or "VSS")
    if not layout and params.get("layout_netlist"):
        return _fail("engine=klayout extracts the layout itself from geometry; a "
                     "pre-extracted `layout_netlist` cannot be used. Supply "
                     "`layout` (GDS/OASIS of the routed design).")
    missing = [k for k, v in (("layout", layout), ("schematic_netlist", sch),
                              ("setup (pdk_binding.lvs_rules)", deck)) if not v]
    if missing:
        return _fail("missing required field(s) for engine=klayout: %s"
                     % ", ".join(missing))
    for p in (layout, sch, deck) + ((cdl,) if cdl else ()):
        if not os.path.exists(str(p)):
            return _fail("input not found: %s" % p)
    if top is not None and not _is_ident(top):
        return _fail("invalid 'top' identifier: %r" % (top,))
    if deck_patch and deck_patch not in _DECK_PATCHES:
        return _fail("unknown deck_patch %r; supported: %s"
                     % (deck_patch, ", ".join(_DECK_PATCHES)))
    if deck_patch and not top:
        return _fail("deck_patch %r needs `top` (the patch names the design top "
                     "cell)" % deck_patch)

    run_dir = os.path.join(_WORK_DIR, "klayout_lvs")
    os.makedirs(run_dir, exist_ok=True)
    deck_text = open(deck, encoding="utf-8", errors="replace").read()
    rd = _deck_rd_vars(deck_text)
    if not rd["layout"] or not rd["schematic"]:
        return _fail("the LVS deck %s does not read a recognised layout/schematic "
                     "-rd variable (deck reads: %s); cannot drive it in batch mode"
                     % (os.path.basename(str(deck)), ", ".join(rd["used"]) or "none"),
                     verdict="not_assessable")
    deck_sha = _sha256_file(deck)
    deck_ext = os.path.splitext(str(deck))[1] or ".lylvs"
    run_deck = os.path.join(run_dir, "lvs_deck" + deck_ext)
    patch_rec = None
    if deck_patch:
        patched, diff = _patch_deck_nangate_pwell(deck_text, top)
        if patched is None:
            return _fail("deck_patch %s refused: %s" % (deck_patch, diff),
                         verdict="not_assessable")
        with open(run_deck, "w", encoding="utf-8", newline="\n") as f:
            f.write(patched)
        with open(os.path.join(_OUTPUT_DIR, "lvs_deck_patch.diff"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(diff)
        patch_rec = {"name": deck_patch, "original_sha256": deck_sha,
                     "patched_sha256": _sha256_file(run_deck),
                     "patched_copy": run_deck, "diff": "lvs_deck_patch.diff",
                     "vendored_deck_modified": False}
    else:
        shutil.copyfile(deck, run_deck)

    # Schematic: Verilog -> CDL-ordered SPICE, or a SPICE/CDL schematic completed
    # with the PDK CDL subckts it instantiates.
    sch_out = os.path.join(_OUTPUT_DIR, "%s.schematic.cir" % (top or "design"))
    is_verilog = os.path.splitext(str(sch))[1].lower() in _VERILOG_EXTS_ALL
    phys = list(_PHYSICAL_ONLY_PATTERNS)
    pc = binding.get("physical_cells") or {}
    for key in ("filler_cells", "decap_cells"):
        phys += [str(x) for x in (pc.get(key) or [])]
    for key in ("tapcell_master", "endcap_master"):
        if pc.get(key):
            phys.append(str(pc[key]))
    phys += [str(x) for x in _as_list(params.get("exclude_cells"))]
    phys = list(dict.fromkeys(phys))
    if is_verilog:
        if not cdl:
            return _fail("schematic_netlist is gate-level Verilog but no PDK CDL "
                         "(`cdl` / pdk_binding.cdl) was supplied. Cell pin ORDER must "
                         "come from the CDL -- the Verilog cell models order pins "
                         "differently -- so the schematic cannot be built.",
                         signoff={"vacuity_guard": "verilog_source_without_cdl",
                                  "assessed": False})
        conv = _verilog_to_spice(sch, cdl, top=top, out_path=sch_out,
                                 power_net=power_net, ground_net=ground_net,
                                 physical_only=phys)
        top = top or conv.get("top")
    else:
        conv = _spice_schematic_prepare(sch, cdl, sch_out)
    conv_ev = {k: v for k, v in conv.items() if k != "errors"}
    cdl_lib = _cdl_library(cdl) if cdl else collections.OrderedDict()
    coverage = _lvs_cell_coverage(conv.get("masters") or {}, cdl_lib, deck_text, binding)
    unresolved = conv.get("unresolved_masters") or {}
    if unresolved or not coverage["ok"]:
        names = sorted(set(unresolved) | set(coverage["outside_cdl"])
                       | set(coverage["outside_deck_asserted_set"])
                       | set(coverage["binding_omitted_hits"]))
        return _fail(
            "CELL COVERAGE GAP (not a design mismatch): the schematic uses "
            "master(s) outside the set this deck/PDK can compare: %s. %s The "
            "comparison was NOT run." % (", ".join(names[:30]),
                                         coverage.get("enforcement") or ""),
            verdict="not_assessable",
            signoff={"coverage_gate": coverage, "schematic_conversion": conv_ev,
                     "assessed": False},
            validation_extra={"reason": "cell_coverage"},
            inputs_ref={"layout": layout, "schematic_netlist": sch, "cdl": cdl, "deck": deck})
    if not conv.get("ok"):
        return _fail("schematic could not be converted exactly, so no comparison "
                     "was run: " + "; ".join(conv.get("errors") or ["unknown error"]),
                     signoff={"schematic_conversion": conv_ev, "assessed": False},
                     inputs_ref={"layout": layout, "schematic_netlist": sch, "cdl": cdl})

    # Stage the layout INSIDE the run dir: the deck writes its relative
    # `lvs_report.lvsdb` next to the SOURCE layout, and /input may be read-only.
    lay_link = os.path.join(run_dir, os.path.basename(str(layout)))
    if os.path.lexists(lay_link):
        os.remove(lay_link)
    try:
        os.symlink(os.path.abspath(str(layout)), lay_link)
    except (OSError, NotImplementedError):
        shutil.copyfile(layout, lay_link)
    pre, perr = _klayout_preflight(klayout, lay_link, top, run_dir)
    if perr:
        return _fail(perr, verdict="not_assessable",
                     inputs_ref={"layout": layout})
    if pre.get("top_cell_count") != 1:
        return _fail("layout has %s top cells (%s); the deck selects the top cell "
                     "implicitly and aborts on 'multiple top cells'. Stream out a "
                     "single-top-cell GDS (binding consumer_obligations."
                     "single_top_cell)." % (pre.get("top_cell_count"),
                                            ", ".join(pre.get("top_cells") or [])),
                     verdict="not_assessable", signoff={"layout_preflight": pre},
                     inputs_ref={"layout": layout})
    if top and not pre.get("top_found"):
        return _fail("layout top cell is %r, not the requested top %r"
                     % ((pre.get("top_cells") or [None])[0], top),
                     signoff={"layout_preflight": pre}, inputs_ref={"layout": layout})
    top = top or (pre.get("top_cells") or [None])[0]

    extracted = os.path.join(_OUTPUT_DIR, "%s_extracted.cir" % top)
    rd_values = {rd["layout"]: lay_link, rd["schematic"]: sch_out}
    if rd["target_netlist"]:
        rd_values[rd["target_netlist"]] = extracted
    lvsdb_out = os.path.join(run_dir, "lvs_report.lvsdb")
    if rd["lvsdb"]:
        rd_values[rd["lvsdb"]] = lvsdb_out
    if rd["top"]:
        rd_values[rd["top"]] = top
    for k, v in (params.get("deck_vars") or {}).items():
        if re.match(r"^[A-Za-z_]\w*$", str(k)):
            rd_values[str(k)] = str(v)
    cmd = [klayout, "-b", "-r", run_deck]
    for k, v in rd_values.items():
        cmd += ["-rd", "%s=%s" % (k, v)]
    _save_run_command(cmd)
    for stale in (lvsdb_out,):
        if os.path.exists(stale):
            os.remove(stale)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=run_dir,
                              timeout=int(params.get("timeout_s") or 6 * 3600))
        log, rc = proc.stdout + "\n" + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        log, rc = "TIMEOUT after %ss\n%s" % (e.timeout, e.stdout or ""), None
    with open(os.path.join(_OUTPUT_DIR, "klayout_lvs.log"), "w", encoding="utf-8",
              errors="replace") as f:
        f.write(log)
    elapsed = time.time() - t0
    lvsdb = lvsdb_out if os.path.exists(lvsdb_out) else None
    if lvsdb is None:
        for cand in (os.path.join(run_dir, "lvs_report.lvsdb"),
                     os.path.join(os.path.dirname(os.path.abspath(str(layout))), "lvs_report.lvsdb")):
            if os.path.exists(cand):
                lvsdb = cand
                break
    if lvsdb:
        shutil.copyfile(lvsdb, os.path.join(_OUTPUT_DIR, "lvs_report.lvsdb"))
    parsed = _parse_lvsdb(lvsdb) if lvsdb else None
    log_msgs = _klayout_log_messages(log)
    deck_says_match = "Netlists match" in log and "don't match" not in log
    deck_says_mismatch = bool(re.search(r"Netlists don'?t match|do not match", log))

    inputs_ref = {"layout": layout, "schematic_netlist": sch, "cdl": cdl,
                  "deck": deck, "schematic_spice": sch_out}
    prov = {"klayout": eng["engine_version"], "runtime_s": round(elapsed, 3),
            "log": "klayout_lvs.log", "deck_sha256": deck_sha,
            "run_deck_sha256": _sha256_file(run_deck), "exit_code": rc}
    so = {"engine_selection": sel, "pdk_policy_override": pol["override"],
          "deck": os.path.basename(str(deck)), "deck_rd_vars": rd,
          "rd_values": rd_values, "report": "lvs_report.lvsdb" if lvsdb else None,
          "log": "klayout_lvs.log", "layout_preflight": pre,
          "schematic_conversion": conv_ev, "coverage_gate": coverage,
          "deck_patch": patch_rec, "log_messages": log_msgs,
          "lvsdb_summary": parsed}
    if not parsed or not parsed.get("xref_present"):
        return _fail("KLayout LVS produced no usable cross-reference (lvsdb %s, exit "
                     "code %s); no verdict can be read. See klayout_lvs.log:\n%s"
                     % ("missing" if not lvsdb else "without xref", rc, log[-1500:]),
                     verdict="not_assessable", signoff=so, inputs_ref=inputs_ref,
                     provenance=prov)

    defects = (parsed["mismatched_nets"] + parsed["mismatched_devices"]
               + parsed["mismatched_pins"] + parsed["mismatched_subcircuits"]
               + len(parsed["circuits_mismatched"]) + len(parsed["circuits_skipped"]))
    match = (defects == 0 and not deck_says_mismatch and (rc in (0, None) or deck_says_match)
             and rc is not None)
    blob = log + "\n" + "\n".join(parsed["messages"])
    well_sig = bool(re.search(r"\bPWELL\b", blob)) or any(
        n.upper() in _WELL_NET_NAMES for n in parsed["unmatched_layout_nets"])
    independent = [p for p in parsed["per_circuit"] if p.get("independent_defect")]

    caveats = []
    if cap.get("state") and cap.get("state") != "available":
        caveats.append("binding capabilities.lvs.state=%s: %s"
                       % (cap.get("state"), cap.get("reason") or ""))
    for bug in cap.get("known_deck_bugs") or []:
        caveats.append("known deck bug: " + str(bug))
    if patch_rec:
        caveats.append("deck_patch %s applied to a WORK-DIR COPY of the vendored deck "
                       "(original sha256 %s -> patched sha256 %s); the vendored deck was "
                       "not modified. The patch declares PWELL==VSS for a tapless "
                       "library; it must be reviewed before this result is signoff "
                       "evidence." % (deck_patch, deck_sha, patch_rec["patched_sha256"]))
    if not pre.get("top_labels"):
        caveats.append("the layout top cell carries 0 text labels, so top-level ports "
                       "were matched by topology only, not by name")
    if conv.get("aliased_port_groups"):
        caveats.append("%d group(s) of top-level ports are aliased by `assign` and share "
                       "one net in the schematic" % len(conv["aliased_port_groups"]))
    if conv.get("implicit_power_connections"):
        caveats.append("%d instance supply pin(s) had no explicit connection and were "
                       "tied to %s/%s by name" % (conv["implicit_power_connections"],
                                                  power_net, ground_net))
    if rd["top"] is None:
        caveats.append("the deck selects the layout top cell implicitly; preflight "
                       "verified a single top cell %r" % top)

    results = {"lvs_match": {"value": match, "unit": "bool"},
               "mismatched_nets": {"value": parsed["mismatched_nets"], "unit": "count"},
               "mismatched_devices": {"value": parsed["mismatched_devices"], "unit": "count"},
               "mismatched_pins": {"value": parsed["mismatched_pins"], "unit": "count"},
               "mismatched_subcircuits": {"value": parsed["mismatched_subcircuits"], "unit": "count"},
               "circuits_compared": {"value": parsed["circuits"], "unit": "count"},
               "circuits_mismatched": {"value": len(parsed["circuits_mismatched"]), "unit": "count"},
               "circuits_skipped": {"value": len(parsed["circuits_skipped"]), "unit": "count"},
               "schematic_instances": {"value": conv.get("instances_emitted"), "unit": "count"},
               "excluded_physical_instances": {"value": sum((conv.get("excluded_physical") or {}).values())
                                               + sum((conv.get("excluded_physical_no_cdl") or {}).values()),
                                               "unit": "count"},
               "pwell_gap_detected": {"value": well_sig, "unit": "bool"},
               "layout_top_labels": {"value": pre.get("top_labels"), "unit": "count"}}
    qor = {"lvs_clean": match, "mismatched_nets": parsed["mismatched_nets"],
           "mismatched_devices": parsed["mismatched_devices"]}
    assumptions = ["schematic pin order from the PDK CDL; physical-only masters "
                   "excluded: %s" % ", ".join(phys),
                   "KLayout hierarchical compare (deck `deep` + `align`)"]
    common = dict(results=results, qor=qor, signoff=dict(so, caveats=caveats),
                  inputs_ref=inputs_ref, provenance=prov, assumptions=assumptions, **eng)
    obj = "KLayout layout-vs-schematic of %s" % top
    if match:
        verdict = "pass_with_caveats" if caveats else "pass"
        return _cde(objective=obj, status="completed",
                    validation={"verdict": verdict,
                                "note": "netlists match (KLayout LVS)"
                                + ("; caveats: " + " | ".join(caveats) if caveats else "")},
                    **common)
    if well_sig and not patch_rec and not independent:
        attribution = ((binding.get("capabilities") or {}).get("drc") or {}).get(
            "lvs_findings", {}).get("remaining_mismatch") or (
            "tapless library: PWELL has no geometric path to VSS")
        caveats.append("residual attributed to the documented tapless-library PWELL "
                       "gap: " + str(attribution)[:400])
        return _cde(objective=obj, status="failed",
                    error=("LVS NOT ASSESSABLE: the comparison ran and every mismatched "
                           "circuit carries the PWELL/well-net signature of the "
                           "documented tapless-library gap (deck connect_explicit omits "
                           "PWELL in the Nangate branch). This is attributed, not a "
                           "design pass and not a proven design defect. Re-run with "
                           "deck_patch=\"nangate_pwell_connect_explicit\" after review "
                           "to obtain an assessable comparison."),
                    validation={"verdict": "not_assessable",
                                "reason": "tapless_pwell_gap",
                                "attribution": "binding lvs_findings (PWELL vs VSS)",
                                "remediation": "deck_patch=nangate_pwell_connect_explicit (opt-in, reviewed)"},
                    **common)
    if well_sig:
        caveats.append("PWELL/well-net signature present%s; other mismatches are "
                       "NOT explained by it" % (" despite deck_patch" if patch_rec else ""))
    return _cde(objective=obj, status="completed",
                error=("netlists do not match: %d net, %d device, %d pin, %d subcircuit "
                       "mismatch(es); %d circuit(s) mismatched, %d skipped"
                       % (parsed["mismatched_nets"], parsed["mismatched_devices"],
                          parsed["mismatched_pins"], parsed["mismatched_subcircuits"],
                          len(parsed["circuits_mismatched"]), len(parsed["circuits_skipped"]))),
                validation={"verdict": "fail", "note": "netlists do not match (KLayout LVS)"},
                **common)


def _lvs_compare(params):
    # ENGINE IS RESOLVED FIRST, BEFORE ANY BINARY PROBE. The previous order
    # probed for netgen up front, so a nangate45 run -- which binds engine
    # `klayout` and never wanted netgen at all -- reported "netgen not found",
    # naming the wrong missing dependency and pointing remediation at the wrong
    # tool. Ask which engine is required, THEN whether it is present.
    binding = params.get("pdk_binding") or {}
    pol = _resolve_lvs_policy(params, binding)
    # KLayout is implemented as a real engine (deck-driven extraction + compare);
    # see _lvs_compare_klayout. Resolution: caller > tool_policy > capability.
    if str(pol["engine"]).lower() == "klayout":
        return _lvs_compare_klayout(params, binding, pol)
    # Any other engine cannot be honored here -- fail closed rather than silently
    # running Netgen under a different engine label.
    #
    # The VERDICT here is `not_assessable`, NOT `fail`: no comparison ran, and
    # `fail` on an LVS gate claims the layout does not match the schematic.
    if pol["engine"] not in ("netgen", "netgen-lvs"):
        return _cde(
            objective="LVS", status="failed", pdk_binding=binding or "none",
            error=f"LVS engine '{pol['engine']}' (source: {pol['engine_source']}) "
                  "is not implemented by this tool (engines: netgen, klayout). "
                  "No netlist comparison was performed, so this is NOT a layout/"
                  "schematic mismatch -- it is a tool-provisioning gap. Provision "
                  f"the '{pol['engine']}' engine to assess this gate.",
            validation={"verdict": "not_assessable",
                        "reason": "required LVS engine absent from tool image",
                        "requested_engine": pol["engine"],
                        "available_engines": ["netgen", "klayout"],
                        "remediation": "provision the requested engine"})
    # Netgen IS the required engine here -- only now is its absence meaningful.
    netgen = _netgen_bin()
    if not netgen:
        return _cde(objective="LVS", status="failed", pdk_binding=binding or "none",
                    error="Netgen is the required LVS engine for this binding but "
                          "is not provisioned in this tool image. No netlist "
                          "comparison was performed, so this is NOT a layout/"
                          "schematic mismatch -- it is a tool-provisioning gap.",
                    validation={"verdict": "not_assessable",
                                "reason": "netgen absent from tool image",
                                "requested_engine": pol["engine"],
                                "remediation": "provision Netgen"})
    lay = params.get("layout_netlist")
    lay_cell = params.get("layout_cell") or params.get("top")
    sch = params.get("schematic_netlist") or params.get("source_netlist")
    sch_cell = params.get("schematic_cell") or params.get("top")
    for _cn, _cv in (("layout_cell/top", lay_cell), ("schematic_cell/top", sch_cell)):
        if _cv is not None and not _is_ident(_cv):
            return _cde(objective="LVS", status="failed", pdk_binding=binding or "none",
                        error=f"invalid '{_cn}' identifier: {_cv!r}", validation={"verdict": "fail"})
    setup = params.get("setup") or binding.get("lvs_rules") or "nosetup"
    for n, v in (("layout_netlist", lay), ("schematic_netlist", sch)):
        if not v:
            return _cde(objective="LVS", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}'", validation={"verdict": "fail"})
    for p in (lay, sch):
        if not os.path.exists(str(p)):
            return _cde(objective="LVS", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    if setup != "nosetup" and not os.path.exists(str(setup)):
        return _cde(objective="LVS", status="failed", pdk_binding=binding or "none",
                    error=f"setup file not found: {setup}", validation={"verdict": "fail"})
    # Netgen's SPICE reader is intolerant of CR line endings (a stray CR becomes
    # part of a token) and auto-detects format from the file extension (an
    # unfamiliar suffix like `.spice`/`.src` is misread as a Magic `.ext`). We
    # normalize both netlists to LF in workdir copies so a Windows-authored or
    # oddly-named netlist does not spuriously fail the compare. The output
    # extension MUST preserve the source netlist's format family -- a structural
    # Verilog schematic (`.v`/`.vlog`/`.verilog`, the source/schematic side of an
    # RTL-vs-layout LVS) forced to `.spi` is silently misread by Netgen as SPICE
    # and corrupts the compare; only non-Verilog (SPICE-family) inputs are
    # normalized to `.spi`.
    _VERILOG_EXTS = (".v", ".vlog", ".verilog")

    def _normalize(src, tag):
        src_ext = os.path.splitext(str(src))[1].lower()
        stem = os.path.splitext(os.path.basename(str(src)))[0]
        # Netgen picks the reader from the FIRST extension-like token, so a stem
        # such as `inv.ext` would be misread as a Magic `.ext`. Strip inner dots.
        stem = re.sub(r"[^A-Za-z0-9_]", "_", stem)
        out_ext = ".v" if src_ext in _VERILOG_EXTS else ".spi"
        dst = os.path.join(_WORK_DIR, f"{tag}_{stem}{out_ext}")
        try:
            with open(src, "rb") as fi:
                data = fi.read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            with open(dst, "wb") as fo:
                fo.write(data)
            return dst
        except Exception:
            return src
    lay = _normalize(lay, "lay")
    sch = _normalize(sch, "sch")
    report = os.path.join(_OUTPUT_DIR, "lvs_comp.out")

    # *** A GATE-LEVEL VERILOG SOURCE IS NOT SELF-CONTAINED. ***
    # A structural Verilog netlist INSTANTIATES standard cells but DEFINES none.
    # Netgen then builds every cell as an EMPTY subcircuit and reports, per cell:
    #     Cell sky130_fd_sc_hd__nand2_1 disconnected node: A
    #     Equate pins: cell ... has no elements.
    # The compare still runs and still prints a verdict, so the run LOOKS like a
    # real LVS -- it is vacuous. MEASURED on a real bsum16 layout, same inputs:
    #   without cell models: every cell "has no elements", 0 subcircuits compared,
    #                        devices 258 vs 261, nets 270 vs 267  -> meaningless
    #   with cell models:    27 subcircuits MATCH UNIQUELY, 0 fail,
    #                        devices 258 vs 258 (exact)           -> real compare
    # So the models are not an optimization; without them the gate is decorative.
    # Netgen's command-line form takes ONE file per side, so the extra models are
    # read into the SAME circuit index via a `readnet ... $index` Tcl script --
    # that is netgen's documented way to compose a multi-file netlist.
    models = _as_list(params.get("cell_models") or params.get("source_models")
                      or binding.get("cell_spice") or binding.get("cell_models"))
    models = [m for m in models if m]
    src_is_verilog = os.path.splitext(str(sch))[1].lower() in _VERILOG_EXTS
    for m in models:
        if not os.path.exists(str(m)):
            return _cde(objective="LVS", status="failed", pdk_binding=binding or "none",
                        error=f"cell model netlist not found: {m}",
                        validation={"verdict": "fail"})
    if src_is_verilog and not models:
        # FAIL CLOSED. A vacuous compare must never be reported as an LVS result,
        # in either direction: it cannot prove a match and its mismatches are
        # artifacts, so chasing them wastes a debug cycle on a phantom.
        return _cde(
            objective="LVS", status="failed", pdk_binding=binding or "none",
            error=("source netlist is structural Verilog but no cell models were "
                   "supplied, so every standard cell would be read as an EMPTY "
                   "subcircuit ('has no elements') and the comparison would be "
                   "vacuous. Supply `cell_models` (e.g. the PDK's "
                   "sky130_fd_sc_hd.spice) or pdk_binding.cell_spice."),
            validation={"verdict": "fail"},
            signoff={"vacuity_guard": "verilog_source_without_cell_models",
                     "assessed": False})

    # Always select each reader explicitly. Netgen's second-file auto detection
    # can reject valid SPICE; numeric circuit handles avoid another implicit read.
    def _tq(p):
        value = str(p).replace("\\", "/")
        return '"' + value.replace("$", "\\$").replace("[", "\\[").replace('"', '\\"') + '"'
    fmt = "verilog" if src_is_verilog else "spice"
    layout_fmt = "verilog" if os.path.splitext(lay)[1].lower() in _VERILOG_EXTS else "spice"
    tcl_lines = [
        "set lay [readnet %s %s]" % (layout_fmt, _tq(lay)),
        "set src [readnet %s %s]" % (fmt, _tq(sch)),
        'if {$lay < 0 || $src < 0} {error "explicit netlist reader failed"}',
    ]
    for m in models:
        tcl_lines.append("readnet spice %s $src" % _tq(m))
    tcl_lines.append('lvs [list $lay %s] [list $src %s] %s %s'
                     % (_tq(lay_cell or ""), _tq(sch_cell or ""), _tq(setup), _tq(report)))
    lvs_tcl = os.path.join(_WORK_DIR, "lvs_compare.tcl")
    with open(lvs_tcl, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(tcl_lines) + "\n")
    cmd = [netgen, "-batch", "source", lvs_tcl]
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "netgen.log"), "w", encoding="utf-8",
         errors="replace").write(out)
    # Netgen's report is NOT guaranteed UTF-8: it echoes net/cell names verbatim
    # from the layout, and an extracted netlist can carry stray high bytes. A
    # bare open().read() raises UnicodeDecodeError and the tool reports a decode
    # crash INSTEAD OF THE LVS VERDICT -- turning a completed comparison into a
    # failed stage. Decode permissively; the verdict lines are ASCII.
    if os.path.exists(report):
        with open(report, "r", encoding="utf-8", errors="replace") as _rf:
            report_text = _rf.read()
    else:
        report_text = out
    blob = out + "\n" + report_text
    # Netgen returns 0 even on mismatch: the verdict lives in the report text.
    match = bool(re.search(r"[Cc]ircuits?\s+match\s+uniquely", blob))
    uncmatched = bool(re.search(r"match\s+uniquely\s+with\s+incorrect", blob, re.I))
    mismatch = bool(re.search(r"do not match|Netlists? (?:do not|don't) match|"
                              r"Circuits do not match", blob)) or uncmatched
    prop_mismatch = _property_mismatch_count(blob)
    # *** DERIVE THE MISMATCH DELTA, NOT JUST THE RAW POPULATIONS. ***
    # STAGE_RESIDUALS['lvs'].direct in catalog/tools/cde_progress.py binds on
    # `mismatched_devices`/`mismatched_nets` (a residual-shaped DEFECT COUNT),
    # not on the raw per-side populations -- a residual model cannot subtract
    # two counts it never sees combined, so publishing ONLY
    # device_count_layout/source left a real mismatch (e.g. 244 vs 245
    # devices) representable ONLY as the difference between two fields the
    # model has no rule to subtract, and the gate could self-report residual
    # 0 / all_families_closed while lvs_match was false (DX-168).
    _counts = _parse_lvs_device_net_counts(blob)
    device_count_layout = _counts["device_count_layout"]
    device_count_source = _counts["device_count_source"]
    net_count_layout = _counts["net_count_layout"]
    net_count_source = _counts["net_count_source"]
    mismatched_devices = _counts["mismatched_devices"]
    mismatched_nets = _counts["mismatched_nets"]
    if match and not mismatch and not prop_mismatch and proc.returncode == 0:
        verdict = "pass"
        status = "completed"
        note = "circuits match uniquely (LVS clean)"
    elif mismatch or not match or prop_mismatch or proc.returncode != 0:
        verdict = "fail"
        status = "completed"
        note = ("device properties do not match" if prop_mismatch
                else "netgen execution failed" if proc.returncode != 0
                else "netlists do not match")
    else:
        verdict = "review"
        status = "completed"
        note = "LVS result inconclusive; inspect the report"
    if not os.path.exists(report) and proc.returncode != 0:
        return _cde(objective="LVS", status="failed", pdk_binding=binding or "none",
                    error="netgen failed; see netgen.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"netgen": _version(netgen, ["-batch", "quit"]), "log": "netgen.log"})
    clean = bool(match and not mismatch and not prop_mismatch and proc.returncode == 0)
    _results = {"lvs_match": {"value": clean, "unit": "bool"},
                "unique_match": {"value": clean,
                                 "unit": "bool"},
                "property_mismatches": {"value": prop_mismatch, "unit": "count"}}
    if device_count_layout is not None:
        _results["device_count_layout"] = {"value": device_count_layout, "unit": "count"}
        _results["device_count_source"] = {"value": device_count_source, "unit": "count"}
        _results["mismatched_devices"] = {"value": mismatched_devices, "unit": "count"}
    if net_count_layout is not None:
        _results["net_count_layout"] = {"value": net_count_layout, "unit": "count"}
        _results["net_count_source"] = {"value": net_count_source, "unit": "count"}
        _results["mismatched_nets"] = {"value": mismatched_nets, "unit": "count"}
    return _cde(
        objective=f"layout-vs-schematic of {lay_cell or os.path.basename(str(lay))}",
        status=status, pdk_binding=binding or "none",
        results=_results,
        qor={"lvs_clean": clean},
        signoff={"match": clean, "report": "lvs_comp.out",
                 "setup": os.path.basename(str(setup)) if setup != "nosetup" else "nosetup",
                 "property_mismatches": prop_mismatch,
                 "mismatched_devices": mismatched_devices,
                 "mismatched_nets": mismatched_nets,
                 "device_count_layout": device_count_layout,
                 "device_count_source": device_count_source,
                 "net_count_layout": net_count_layout,
                 "net_count_source": net_count_source,
                 "log": "netgen.log",
                 "engine_selection": {"engine": pol["engine"],
                                      "source": pol["engine_source"],
                                      "pdk_recommended": pol["pdk_recommended"]},
                 "pdk_policy_override": pol["override"]},
        inputs_ref={"layout_netlist": lay, "schematic_netlist": sch},
        assumptions=["device/param matching per the setup file from the binding; "
                     "signoff requires a unique match"],
        validation={"verdict": verdict, "note": note},
        provenance={"netgen": _version(netgen, ["-batch", "quit"]),
                    "runtime_s": round(elapsed, 3), "log": "netgen.log"},
    )


def _property_mismatch_count(blob):
    details = {
        line.strip() for line in blob.splitlines()
        if re.search(r"\bcircuit1\s*:.*\bcircuit2\s*:.*\bdelta\s*=", line, re.I)
        or re.search(r"Property.*mismatch|Device classes.*differ", line, re.I)
    }
    if details:
        return len(details)
    # Netgen 1.5 can report a unique topology match AND property errors.
    return int(bool(re.search(
        r"\bproperty\s+errors?\s+(?:were\s+found|found)\b|"
        r"\bthere\s+(?:were|are)\s+property\s+errors?\b",
        blob, re.I)))


def _parse_lvs_device_net_counts(blob):
    """Parse netgen's per-side device/net population counts and derive the
    mismatch DELTA from them.

    Netgen's text reports "Circuit 1 contains N devices, Circuit 2 contains M
    devices." once per subcircuit, plus once more for the top-level circuit as
    a whole; the LAST occurrence in the combined stdout+report text is always
    the top-level total (verified: it immediately precedes the final "Result:"
    line in every observed run). Returns a dict with `device_count_layout`,
    `device_count_source`, `mismatched_devices`, and the net-side equivalents,
    each `None` when the pattern was not found (never fabricated as 0).
    """
    dev_pairs = re.findall(
        r"Circuit 1 contains (\d+) devices?,\s*Circuit 2 contains (\d+) devices?",
        blob)
    net_pairs = re.findall(
        r"Circuit 1 contains (\d+) nets,\s*Circuit 2 contains (\d+) nets", blob)
    device_count_layout = int(dev_pairs[-1][0]) if dev_pairs else None
    device_count_source = int(dev_pairs[-1][1]) if dev_pairs else None
    net_count_layout = int(net_pairs[-1][0]) if net_pairs else None
    net_count_source = int(net_pairs[-1][1]) if net_pairs else None
    return {
        "device_count_layout": device_count_layout,
        "device_count_source": device_count_source,
        "mismatched_devices": (abs(device_count_layout - device_count_source)
                               if device_count_layout is not None
                               and device_count_source is not None else None),
        "net_count_layout": net_count_layout,
        "net_count_source": net_count_source,
        "mismatched_nets": (abs(net_count_layout - net_count_source)
                           if net_count_layout is not None
                           and net_count_source is not None else None),
    }


def _cross_check_extraction(params):
    """Cross-check an ALREADY-EXTRACTED netlist against the PDK CDL.

    Separate from `extract_layout` so a netlist produced by any engine -- or on
    a previous run -- can be audited without re-extracting.
    """
    binding = params.get("pdk_binding") or {}
    netlist = params.get("netlist") or params.get("layout_netlist")
    cell = params.get("cell") or params.get("top")
    cdl = params.get("cdl") or (binding.get("cdl") if isinstance(binding, dict) else None)
    prefix = str(params.get("cell_prefix") or "")
    missing = [k for k, v in (("netlist", netlist), ("cell", cell), ("cdl", cdl)) if not v]
    if missing:
        return _cde(objective="extraction cross-check", status="failed", engine="Magic",
                    pdk_binding=binding or "none",
                    error=("missing required field(s): %s. The reference netlist "
                           "is what makes this check meaningful, so it is never "
                           "defaulted." % ", ".join(missing)),
                    validation={"verdict": "fail"})
    xc = _cdl_cross_check(netlist, cell, cdl, cell_prefix=prefix)
    if xc is None:
        return _cde(objective=f"extraction cross-check for {cell}", status="failed",
                    engine="Magic", pdk_binding=binding or "none",
                    inputs_ref={"netlist": netlist, "cdl": cdl},
                    error=("could not read the extracted netlist or the CDL "
                           "(netlist=%r cdl=%r)" % (netlist, cdl)),
                    validation={"verdict": "fail"})
    if xc["status"] == "not_assessable":
        return _cde(
            objective=f"extraction cross-check for {cell}", status="completed",
            engine="Magic", pdk_binding=binding or "none",
            results={"cdl_cross_check": {"value": "not_assessable", "unit": "-"}},
            qor={"cdl_cross_check": "not_assessable"},
            signoff={"cdl_cross_check": xc},
            inputs_ref={"netlist": netlist, "cdl": cdl},
            # NOT a pass: an un-run check must never read as agreement.
            validation={"verdict": "review", "note": xc["reason"]},
            provenance={"reference": "PDK CDL"})
    ok = xc["status"] == "match"
    return _cde(
        objective=f"extraction cross-check for {cell}",
        status="completed" if ok else "failed",
        engine="Magic", pdk_binding=binding or "none",
        results={"cdl_devices": {"value": xc["cdl_devices"], "unit": "count"},
                 "extracted_devices": {"value": xc["extracted_devices"], "unit": "count"}},
        qor={"cdl_devices": xc["cdl_devices"],
             "extracted_devices": xc["extracted_devices"],
             "cdl_cross_check": xc["status"]},
        signoff={"cdl_cross_check": xc},
        inputs_ref={"netlist": netlist, "cdl": cdl},
        assumptions=["CDL finger-expanded (m=); hierarchy flattened on both "
                     "sides; compared per model"],
        error=None if ok else (
            "EXTRACTION DISAGREES WITH THE PDK CDL for %s: CDL %d device(s) vs "
            "extracted %d. Per-model delta: %s"
            % (cell, xc["cdl_devices"], xc["extracted_devices"], xc["delta"])),
        validation={"verdict": "pass" if ok else "fail",
                    "note": ("extraction agrees with the PDK CDL per model"
                             if ok else
                             "extraction disagrees with the PDK CDL")},
        provenance={"reference": "PDK CDL"})


def dispatch(params):
    s = params.get("scenario")
    if s == "lvs_compare":
        return _lvs_compare(params)
    if s == "extract_layout":
        return _extract_layout(params)
    if s in ("cross_check_extraction", "extraction_cross_check", "cdl_cross_check"):
        return _cross_check_extraction(params)
    return _cde(objective="LVS", status="failed",
                error=f"unknown scenario '{s}'; supported: lvs_compare, "
                      f"extract_layout, cross_check_extraction",
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


# --- magic PDK_ROOT env (BEGIN) -- vendored by catalog/migrate_magic_env.py
# sky130A.magicrc (and the open_pdks family generally) resolves its techfile via
# $PDK_ROOT and falls back to the ORIGINAL BUILD MACHINE's absolute path when
# that variable is unset. A tool that does not set PDK_ROOT therefore runs Magic
# with NO TECHNOLOGY LOADED -- and Magic does not fail: it reads no geometry,
# extracts an empty cell, reports zero violations and EXITS 0. That is a silent
# false clean on a mandatory tapeout gate, which is the worst value these tools
# can emit. Setting PDK_ROOT is what makes the vendor magicrc work unmodified.
def _magic_pdk_root(techfile=None, rcfile=None, params=None):
    """Derive a PDK_ROOT that makes the vendor magicrc resolve, or None.

    Precedence: explicit caller param > already-set environment > derived from
    the techfile/rcfile path. Never guesses: a derived root is returned only
    when the expected <root>/<variant>/libs.tech/magic directory really exists,
    so a wrong layout yields None (and the caller fails closed) rather than a
    plausible-but-wrong path.
    """
    if params:
        explicit = params.get("pdk_root") or (
            (params.get("pdk_binding") or {}).get("pdk_root")
            if isinstance(params.get("pdk_binding"), dict) else None)
        if explicit and os.path.isdir(str(explicit)):
            return str(explicit)
    env_root = os.environ.get("PDK_ROOT")
    if env_root and os.path.isdir(env_root):
        return env_root
    for path in (techfile, rcfile):
        if not path:
            continue
        p = os.path.abspath(str(path))
        # <root>/<variant>/libs.tech/magic/<file>  ->  climb four levels.
        magic_dir = os.path.dirname(p)
        libs_tech = os.path.dirname(magic_dir)
        variant = os.path.dirname(libs_tech)
        root = os.path.dirname(variant)
        if (os.path.basename(magic_dir) == "magic"
                and os.path.basename(libs_tech) == "libs.tech"
                and os.path.isdir(os.path.join(variant, "libs.tech", "magic"))
                and os.path.isdir(root)):
            return root
    return None


def _magic_env(techfile=None, rcfile=None, params=None, extra=None):
    """Environment for a Magic subprocess, with PDK_ROOT resolved."""
    env = dict(os.environ)
    env.setdefault("MAGTYPE", "mag")
    root = _magic_pdk_root(techfile, rcfile, params)
    if root:
        env["PDK_ROOT"] = root
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
# --- magic PDK_ROOT env (END) ---
