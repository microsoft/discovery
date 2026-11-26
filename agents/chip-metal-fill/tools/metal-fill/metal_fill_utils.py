#!/usr/bin/env python3
"""metal_fill_utils.py -- real OpenROAD metal-fill / density.

Runs OpenROAD `density_fill` on a routed DEF with a node fill config to insert
metal fill and meet the PDK density windows, then writes a filled DEF and reports
per-layer density. The fill rules / density windows come from the PDK binding.
Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "metal-fill"
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
        import shlex
        line = (" ".join(shlex.quote(str(c)) for c in cmd)
                if isinstance(cmd, (list, tuple)) else str(cmd))
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
        if (low.endswith((".log", ".tcl", ".ys", ".sh", ".do", ".json5"))
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
          "- `results/` \u2014 filled DEF (next-stage input)",
          "- `logs/` \u2014 verbatim OpenROAD log and the exact run command", ""]
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


def _parse_pdn_continuity(out):
    """Parse the __PDN_IN__/__PDN_OUT__ pair into a continuity record.

    Returns None when either marker is missing, so an old log reads as NOT
    MEASURED rather than as a clean pass -- absence of the probe must never be
    reportable as "power nets are fine".

    Everything keys on RAILS (special power/ground nets that carry SWIRE
    geometry), not on the raw POWER/GROUND sigtype count. Measured: a design
    with no PDN at all still reports one GROUND-typed net, because the tie-low
    net `zero_` carries that sigtype. Keying on sigtype reported "1 power net
    preserved" for a design that cannot be powered.

    `destroyed` is deliberately narrow: rails ENTERED and fewer LEFT. A design
    that arrives with none cannot have them destroyed here, and is reported
    through `absent` instead, because a flow that builds its PDN after
    placement is legitimate and must not be failed.

    UNCONNECTED SUPPLY PINS are tracked separately, because an intact grid does
    NOT mean every cell reaches it. Measured on crc16_ccitt: the rails survived
    every stage 2 -> 2 while CTS's 8 new clock buffers and the tie cell sat with
    all 4 supply pins unattached (0 -> 32 -> 36). `check_power_grid` still
    passed, since it audits the grid, not each instance's attachment to it.
    OpenROAD's global connection RULES persist in the ODB, so any stage that
    inserts cells must re-run `global_connect`; none did.

    `unpowered_created` fires only when THIS stage increased the count, mirroring
    `destroyed`. A pre-existing count is disclosed, not failed -- the stage that
    introduced it is the one that should answer for it. On a design with no PDN
    every supply pin is unconnected by definition (measured: 1410 on crc16_ccitt
    pre-PDN), so the flag is suppressed entirely when no rails entered.
    """
    mi = re.search(r"__PDN_IN__\s+pg=(\d+)\s+rail=(\d+)(?:\s+unc=(\d+))?", out)
    mo = re.search(r"__PDN_OUT__\s+pg=(\d+)\s+rail=(\d+)(?:\s+unc=(\d+))?", out)
    if not mi or not mo:
        return None
    pg_in, rail_in = int(mi.group(1)), int(mi.group(2))
    pg_out, rail_out = int(mo.group(1)), int(mo.group(2))
    # A log predating the unc= probe reads as NOT MEASURED, never as zero.
    unc_in = int(mi.group(3)) if mi.group(3) is not None else None
    unc_out = int(mo.group(3)) if mo.group(3) is not None else None
    unc_measured = unc_in is not None and unc_out is not None
    return {
        "measured": True,
        "pg_nets_in": pg_in, "pg_nets_out": pg_out,
        "rails_in": rail_in, "rails_out": rail_out,
        "destroyed": rail_in > 0 and rail_out < rail_in,
        "absent": rail_in == 0,
        "preserved": rail_in > 0 and rail_out >= rail_in,
        "unconnected_measured": unc_measured,
        "unconnected_pg_pins_in": unc_in,
        "unconnected_pg_pins_out": unc_out,
        "unpowered_created": bool(
            unc_measured and rail_in > 0 and unc_out > unc_in),
        "unpowered_pre_existing": bool(
            unc_measured and rail_in > 0 and unc_in > 0),
        "note": ("a rail is a SPECIAL power/ground net carrying SWIRE "
                 "geometry; POWER/GROUND sigtype alone also matches tie-off "
                 "nets such as `zero_` and does not mean the design is "
                 "powerable"),
    }


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD density_fill", "version": "openroad"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "density_fill"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


# --- per-layer metal-density disposition (PDK-specific) --------------------
#
# SKY130A: the per-layer metal MINIMUM-density rules are RECOMMENDED / CMP
# guidance, NOT hard tapeout-gating DRC rules, so a minimum-density SHORTFALL is
# reclassified ADVISORY (surfaced, never a gate failure) on sky130A. Grounds:
#   * `mX.pd.1` (min oxide pattern density 0.70) is flagged RR ("recommended rule
#     at any IP level"), A ("documents a CL-algorithm behaviour that may not be
#     checked by DRC"), and AL ("Al back-end flows only") in the SkyWater DRC
#     manual -- the signoff Magic / KLayout sky130A decks do not fail on it.
#   * met5 has NO published minimum-density rule at all (the `m5.-` section defines
#     only width m5.1, spacing m5.2, via4 enclosure m5.3, and min AREA m5.4 = 4um^2).
#   * The HARD metal-density rules are the MAXIMUM ones (`mX.13` = 0.77 max PD) --
#     i.e. OVER-density is the real DRC violation; UNDER-density is not.
# A small standalone soft macro legitimately under-fills the upper metals (few
# met4/met5 shapes exist), and forcing legal fill to hit a min-density floor is
# physically infeasible without floating metal / shorts; upper-metal density
# closure is completed at chip integration with top-level fill. MAXIMUM-density
# overages and fill-induced shorts stay HARD failures on EVERY PDK.
#
# This reclassification is DELIBERATELY scoped to sky130A. Other PDKs may define a
# genuinely hard minimum-density rule, so their minimum-density shortfalls are
# left as HARD violations (unchanged).
def _resolve_pdk_name(binding, params):
    """Best-effort PDK identifier from params/binding (e.g. 'sky130A')."""
    for src in (params or {}, binding or {}):
        if isinstance(src, dict):
            for key in ("pdk", "pdk_name", "node", "process"):
                v = src.get(key)
                if v:
                    return str(v)
    return ""


def _is_sky130(pdk):
    return str(pdk or "").strip().lower().startswith("sky130")


def _min_density_disposition(pdk, binding=None):
    """How this node dispositions a minimum-density shortfall.

    Returns one of 'advisory' | 'hard' | 'not_applicable'.

    PREFER THE BINDING. The node's own `density_windows.terminal_policy
    .minimum_density.severity` is the authority, because that is where the PDK
    owner recorded the decision with its basis. The sky130 string test survives
    ONLY as the fallback for a binding that predates the terminal-policy block,
    so sky130 behaviour is bit-for-bit what it was.

    The third state matters: a node that publishes NO density rule at all (e.g.
    FreePDK45/nangate45) must not have a minimum-density *failure* reported
    against it. There is no published minimum, so there is nothing to be under.
    Reporting `hard` there would be a fabricated limit -- the mirror image of the
    bug where a real limit gets dropped, and just as wrong.
    """
    if isinstance(binding, dict):
        windows = binding.get("density_windows")
        if isinstance(windows, dict):
            policy = windows.get("terminal_policy")
            if isinstance(policy, dict):
                minimum = policy.get("minimum_density")
                if isinstance(minimum, dict):
                    severity = str(minimum.get("severity") or "").strip().lower()
                    if severity in ("advisory", "hard", "not_applicable"):
                        return severity
    return "advisory" if _is_sky130(pdk) else "hard"


def _classify_density(layers, pdk, binding=None):
    """Classify per-layer metal density against its min/max window.

    `layers`: {layer_name: {density, minimum, maximum, ...}} (the shape emitted in
    reports/density_integrity.json). Returns:
      {classified, hard_violations, advisories, max_density_violations,
       min_density_shortfalls, verdict, min_density_policy, pdk}

    Disposition:
      * density ABOVE the maximum window  -> HARD 'fail' on EVERY PDK (real CMP/DRC
        over-density error).
      * density BELOW the minimum window  -> 'advisory' on sky130A (recommended-rule
        reclassification, ALL metal layers), 'fail' on any other PDK.
      * within window (or no bound)        -> 'pass'.

    THE VERDICT FOLLOWS THE DISPOSITION, NOT THE COUNT.
    This function used to return `pass_with_caveats` whenever it had classified one
    or more shortfalls ADVISORY -- i.e. it converted its OWN "recommended rule, not
    gating" finding into a verdict string that `cde_progress.py` can never close a
    gate on (`CLOSING_VERDICTS = (pass,)`, by design). Measured: an attempt with all
    eight obligation families at residual 0.0 and no `not_assessable` family was
    refused blessing (`fresh_gate_not_closed`) purely on that string, and closing it
    took a whole remediation task that changed no measurement and redid no fill. A
    caveat the binding itself dispositions as non-gating is not unfinished work, so
    it is reported (`min_density_advisories`, `min_density_policy`) and the verdict
    stays `pass`. Anything HARD still fails.
    """
    min_disposition = _min_density_disposition(pdk, binding)
    sky = min_disposition == "advisory"
    classified = {}
    hard = 0
    advisories = 0
    max_viol = 0
    min_short = 0
    for name, rec in (layers or {}).items():
        if not isinstance(rec, dict):
            continue
        r = dict(rec)
        try:
            dv = float(r.get("density")) if r.get("density") is not None else None
        except (TypeError, ValueError):
            dv = None
        lo = r.get("minimum")
        hi = r.get("maximum")
        status = "pass"
        disposition = None
        if dv is not None and hi is not None and dv > float(hi):
            status, disposition = "fail", "max_density_over_window"
            hard += 1
            max_viol += 1
        elif dv is not None and lo is not None and dv < float(lo):
            min_short += 1
            if min_disposition == "advisory":
                status, disposition = "advisory", "min_density_recommended_sky130a"
                advisories += 1
            elif min_disposition == "not_applicable":
                # The node publishes no minimum-density rule, so a measured value
                # below a window we were handed cannot be a violation of anything.
                # Surface it without inventing a limit to have breached.
                status, disposition = "advisory", "min_density_not_published_by_pdk"
                advisories += 1
            else:
                status, disposition = "fail", "min_density_under_window"
                hard += 1
        r["status"] = status
        if disposition:
            r["disposition"] = disposition
        classified[name] = r
    verdict = "fail" if hard else "pass"
    verdict_basis = (
        "hard density-window violation(s) present"
        if hard else
        ("%d minimum-density shortfall(s) classified ADVISORY by this PDK's own "
         "policy (non-gating) -- reported, not unfinished work" % advisories
         if advisories else "every classified layer inside its density window"))
    policy = (
        "sky130A: metal minimum-density is a RECOMMENDED (CMP) rule "
        "(mX.pd.1 = RR/A/AL; met5 has no min-density rule) -> min shortfalls are "
        "ADVISORY, not gating; maximum-density overages + shorts remain hard"
        if min_disposition == "advisory" else
        ("this PDK publishes NO pattern-density rule, so a minimum-density "
         "shortfall is not assessable against a published limit -- reported, "
         "never failed; maximum-density overages + shorts remain hard"
         if min_disposition == "not_applicable" else
         "non-sky130A: minimum-density treated as a hard rule (PDK-specific; left "
         "unchanged)"))
    return {"classified": classified, "hard_violations": hard,
            "advisories": advisories, "max_density_violations": max_viol,
            "min_density_shortfalls": min_short, "verdict": verdict,
            "verdict_basis": verdict_basis,
            "min_density_disposition": min_disposition,
            "min_density_policy": policy, "pdk": pdk or "unknown"}


def _density_checks_block(res, shorts, verdict, extra_evidence=None):
    """`validation.checks` + `checks_evidence` for a density disposition.

    Every check names the artifact that MEASURED it. An assertion with no evidence
    pointer forces a reviewer to read tool source by hand to learn what it covered,
    and a reviewer who cannot cheaply tell "binding-declared non-gating advisory"
    apart from "real unfinished work" correctly refuses to bless either.
    """
    checks = {
        "maximum_density_violations_zero": res["max_density_violations"] == 0,
        "density_hard_violations_zero": res["hard_violations"] == 0,
        "fill_induced_shorts_zero": shorts == 0,
        "min_density_shortfalls_non_gating": bool(res["advisories"]) or
                                             res["min_density_shortfalls"] == 0,
    }
    evidence = {
        "maximum_density_violations_zero":
            "density_disposition.json `max_density_violations` (per-layer measured "
            "density vs the binding's own maximum window)",
        "density_hard_violations_zero":
            "density_disposition.json `hard_violations` -- MAXIMUM-density overages "
            "on every PDK, plus MINIMUM shortfalls on a PDK whose min-density rule "
            "is hard. This is a DENSITY-WINDOW check, NOT a rule-deck DRC run: "
            "BEOL rule-legality of the inserted fill is verified downstream (see "
            "signoff_evidence.beol_scope_obligation).",
        "fill_induced_shorts_zero":
            "caller-supplied `fill_short_overlaps` (measured fill-to-signal overlap "
            "count); absent means 0 was supplied, not that a short check ran here",
        "min_density_shortfalls_non_gating":
            "density_disposition.json `min_density_policy` + `advisories` -- the "
            "PDK binding's own disposition of minimum density as recommended/"
            "advisory rather than gating",
    }
    if extra_evidence:
        evidence.update(extra_evidence)
    return checks, evidence


def _density_check(params):
    """Classify a per-layer metal-density measurement (min/max windows).

    Accepts a caller-supplied `layer_density` (a {layer: {density, minimum,
    maximum}} dict, or a path to a density_integrity.json produced by the
    measurement pass) and dispositions it via `_classify_density`. This is the
    AUTHORITATIVE density gate: on sky130A a minimum-density shortfall is advisory
    (verdict pass_with_caveats), never a gate failure -- only a maximum-density
    overage or a fill-induced short fails.
    """
    binding = params.get("pdk_binding") or {}
    pdk = _resolve_pdk_name(binding, params)
    layers = params.get("layer_density")
    if layers is None:
        layers = params.get("layers")
    # A path to a density-measurement JSON (the density_integrity.json shape).
    if isinstance(layers, str):
        if not os.path.exists(layers):
            return _cde(objective="metal density check", status="failed",
                        pdk_binding=binding or "none",
                        error=f"layer_density file not found: {layers}",
                        validation={"verdict": "fail"})
        try:
            _j = json.load(open(layers))
            layers = _j.get("layers", _j)
        except Exception as e:
            return _cde(objective="metal density check", status="failed",
                        pdk_binding=binding or "none",
                        error=f"could not parse layer_density file: {e}",
                        validation={"verdict": "fail"})
    if not isinstance(layers, dict) or not layers:
        return _cde(objective="metal density check", status="failed",
                    pdk_binding=binding or "none",
                    error="missing per-layer density map: provide `layer_density` as "
                          "a {layer:{density,minimum,maximum}} dict or a path to a "
                          "density_integrity.json",
                    validation={"verdict": "fail"})
    # Fill-induced shorts are a hard failure regardless of density windows.
    try:
        shorts = int(params.get("fill_short_overlaps", 0) or 0)
    except (TypeError, ValueError):
        shorts = 0
    res = _classify_density(layers, pdk, binding)
    verdict = res["verdict"]
    if shorts > 0 and verdict != "fail":
        verdict = "fail"
    checks, checks_evidence = _density_checks_block(res, shorts, verdict)
    note = (f"{res['max_density_violations']} max-density violation(s), "
            f"{res['min_density_shortfalls']} min-density shortfall(s) "
            f"({res['advisories']} advisory on sky130A), {shorts} fill short(s); "
            f"verdict {verdict} because {res['verdict_basis']}; "
            + res["min_density_policy"])
    try:
        json.dump({"pdk": pdk, "shorts": shorts, **res},
                  open(os.path.join(_OUTPUT_DIR, "density_disposition.json"), "w"),
                  indent=2)
    except Exception as _e:
        print("[" + str(TOOL) + "] density_disposition write skipped: " + str(_e),
              flush=True)
    return _cde(
        objective=f"metal density check (pdk={pdk or 'unknown'})", status="completed",
        pdk_binding=binding or "none",
        results={"density_layers": {"value": res["classified"], "unit": "-"},
                 "max_density_violations": {"value": res["max_density_violations"],
                                            "unit": "count"},
                 "min_density_shortfalls": {"value": res["min_density_shortfalls"],
                                            "unit": "count"},
                 "min_density_advisories": {"value": res["advisories"],
                                            "unit": "count"},
                 "fill_short_overlaps": {"value": shorts, "unit": "count"},
                 "density_hard_violations": {"value": res["hard_violations"],
                                             "unit": "count"}},
        qor={"density_hard_violations": res["hard_violations"],
             "maximum_density_violations": res["max_density_violations"],
             "max_density_violations": res["max_density_violations"],
             "min_density_shortfalls": res["min_density_shortfalls"],
             "min_density_advisories": res["advisories"],
             "fill_induced_shorts": shorts,
             "fill_short_overlaps": shorts},
        signoff={"min_density_policy": res["min_density_policy"],
                 "density_disposition": "density_disposition.json",
                 "per_layer": res["classified"]},
        assumptions=[
            "sky130A metal MINIMUM-density is a recommended CMP rule (mX.pd.1 = "
            "RR/A/AL; met5 has no PDK min-density rule) -> min shortfalls are "
            "ADVISORY, not gating; upper-metal density closes at chip integration "
            "with top-level fill",
            "MAXIMUM-density overages and fill-induced shorts remain hard failures "
            "on every PDK",
            "the advisory reclassification is scoped to sky130A only; other PDKs "
            "keep min-density as a hard rule"],
        validation={"verdict": verdict, "note": note,
                    "checks": checks, "checks_evidence": checks_evidence},
        provenance={"method": "per-layer density-window disposition",
                    "min_density_policy_scope": "sky130A"},
    )


def _def_components(def_path):
    """The `COMPONENTS <n> ;` header count, or None when unreadable."""
    try:
        with open(str(def_path), encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = re.match(r"^\s*COMPONENTS\s+(\d+)\s*;", line)
                if m:
                    return int(m.group(1))
    except OSError:
        return None
    return None


def _def_fills_by_layer(def_path):
    """Per-layer shape counts in a DEF's FILLS section, plus the header total.

    This is the AUTHORITATIVE, tool-independent count of inserted fill, and the
    cross-check every KLayout-based density measurement has to reconcile against.
    """
    total, per_layer = None, {}
    try:
        in_fills = False
        with open(str(def_path), encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if total is None:
                    m = re.match(r"^\s*FILLS\s+(\d+)\s*;", line)
                    if m:
                        total, in_fills = int(m.group(1)), True
                        continue
                if not in_fills:
                    continue
                if line.strip().startswith("END FILLS"):
                    break
                m = re.match(r"\s*-\s+LAYER\s+(\S+)", line)
                if m:
                    per_layer[m.group(1)] = per_layer.get(m.group(1), 0) + 1
    except OSError:
        return None
    if total is None:
        return None
    return {"total": total, "per_layer": per_layer}


def _resolve_layermap(params, binding):
    """The KLayout LEF/DEF layer map, from the caller or the PDK binding."""
    klayout = binding.get("klayout")
    candidates = [params.get("layermap"), binding.get("layermap"),
                  binding.get("klayout_layermap"),
                  klayout.get("layermap") if isinstance(klayout, dict) else None]
    for value in candidates:
        if value:
            return value
    return None


#: GDS datatype for the synthesized FILL-purpose entries. 24 is chosen to avoid the
#: datatypes sky130A's shipped map already uses on metal layers (4/5/16/20/44/48).
_FILL_PURPOSE_DATATYPE = 24


def _write_fill_purpose_map(layermap_path, out_path):
    """Derive a KLayout layer map that can actually SEE DEF FILLS geometry.

    WHY THIS IS GENERATED RATHER THAN DOCUMENTED.
    KLayout's `LEFDEFReaderConfiguration.map_file` generates ONLY the layers present
    in the map file. The sky130A map the PDK ships declares no `FILL` purpose for any
    metal layer, so every DEF `FILLS` shape is dropped on read -- with a per-layer
    "No mapping for layer 'metX', purpose 'FILL' - layer is ignored" WARNING, never
    an error. Measured: met2-met5 density read as ~0 on a DEF that genuinely carried
    287/580/804/160 fill shapes. A silent zero from a measurement tool is
    indistinguishable from a real zero, and the previous fix was a hand-derived
    supplemental map copied between attempts -- which is a fix that only exists where
    someone remembered to copy it.

    The shipped map is NEVER modified in place: it is a `chip-pdk-binding`-owned
    artifact. This writes a measurement-only superset beside the attempt's own logs.
    Returns {"path", "layers_added", "base"} or None when the base map is unreadable.
    """
    try:
        with open(str(layermap_path), encoding="utf-8", errors="ignore") as fh:
            base = fh.read()
    except OSError:
        return None
    # `metX  LEFPIN,NET,SPNET,PIN,VIA  <gds_layer>  <datatype>` -- harvest the GDS
    # layer number each metal already maps to so the FILL entry lands on the same one.
    gds_layer = {}
    for line in base.splitlines():
        parts = line.split()
        if len(parts) >= 4 and re.match(r"^met(al)?\d+$", parts[0], re.I):
            try:
                gds_layer.setdefault(parts[0], int(parts[2]))
            except ValueError:
                continue
    if not gds_layer:
        return None
    if "FILL" in base:
        added = []
    else:
        added = sorted(gds_layer)
    lines = [base.rstrip("\n"), "",
             "# --- generated by chip-metal-fill: FILL-purpose entries the shipped",
             "#     map omits, without which KLayout silently drops DEF FILLS",
             "#     geometry (measurement only; the PDK map is not modified)."]
    for layer in added:
        lines.append("%-7s %-24s %-3d %d"
                     % (layer, "FILL", gds_layer[layer], _FILL_PURPOSE_DATATYPE))
    try:
        with open(str(out_path), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        return None
    return {"path": os.path.basename(str(out_path)), "layers_added": added,
            "base": str(layermap_path), "datatype": _FILL_PURPOSE_DATATYPE}


def _fill(params):
    if not shutil.which("openroad"):
        return _cde(objective="metal fill", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    top = params.get("top")
    def_file = params.get("def_file")
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    # PDK tool_policy: the fill stage may recommend the fill rules config.
    # Precedence: caller param > tool_policy.fill > binding.fill_config/fill_rules.
    _pol_fill = ((binding.get("tool_policy") or {}).get("fill") or {})
    _pol_fill_cfg = (_pol_fill.get("settings") or {}).get("fill_config")
    if params.get("fill_config"):
        fill_config, _fill_src = params.get("fill_config"), "caller"
    elif _pol_fill_cfg:
        fill_config, _fill_src = _pol_fill_cfg, "pdk_policy"
    elif binding.get("fill_config") or binding.get("fill_rules"):
        fill_config = binding.get("fill_config") or binding.get("fill_rules")
        _fill_src = "binding"
    else:
        fill_config, _fill_src = None, "unset"
    for n, v in (("top", top), ("def_file", def_file), ("tech_lef", tech_lef),
                 ("fill_config", fill_config)):
        if not v:
            return _cde(objective="metal fill", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}' (fill_config comes from the "
                              "PDK binding)", validation={"verdict": "fail"})
    for p in [def_file, tech_lef, fill_config] + cell_lefs:
        if not os.path.exists(str(p)):
            return _cde(objective="metal fill", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    out_def = os.path.join(_OUTPUT_DIR, "filled.def")
    lef_reads = "\n".join([f"read_lef {tech_lef}"] + [f"read_lef {c}" for c in cell_lefs])
    # --- POWER-NET CONTINUITY (see chip-placement for the full incident) -----
    #
    # This stage carries MORE risk than placement or CTS: density_fill writes
    # metal geometry onto the same layers the PDN occupies (the sky130 PDN was
    # measured spanning met1-met5), so fill that overlapped or replaced rail
    # geometry would be a genuine tool defect rather than a wiring one.
    #
    # Measured: metal-fill PRESERVES rails (2 in -> 2 out, and the emitted DEF
    # still carries SPECIALNETS=2 with VPWR). So this stage is a CARRIER too --
    # but it had no power-net inspection at all, so on crc16_ccitt it ran and
    # reported success on a design that had already lost its PDN four stages
    # earlier and could never be power-connected.
    #
    # A rail is a SPECIAL power/ground net carrying SWIRE geometry. Sigtype
    # alone is NOT sufficient: the tie-low net `zero_` carries GROUND sigtype,
    # so counting sigtype scored 1 on a design with no PDN whatsoever.
    _pdn_probe = (
        "set _b [ord::get_db_block]\n"
        "set _pg 0\n"
        "set _rail 0\n"
        "set _unc 0\n"
        "foreach _n [$_b getNets] {\n"
        "  set _t [$_n getSigType]\n"
        "  if {$_t != \"POWER\" && $_t != \"GROUND\"} { continue }\n"
        "  incr _pg\n"
        "  if {[$_n isSpecial] && [llength [$_n getSWires]] > 0} { incr _rail }\n"
        "}\n"
        "foreach _i [$_b getInsts] {\n"
        "  foreach _it [$_i getITerms] {\n"
        "    set _st [[$_it getMTerm] getSigType]\n"
        "    if {$_st != \"POWER\" && $_st != \"GROUND\"} { continue }\n"
        "    if {[$_it getNet] == \"NULL\"} { incr _unc }\n"
        "  }\n"
        "}\n")
    _pdn_in = _pdn_probe + "puts \"__PDN_IN__ pg=$_pg rail=$_rail unc=$_unc\"\n"
    _pdn_out = _pdn_probe + "puts \"__PDN_OUT__ pg=$_pg rail=$_rail unc=$_unc\"\n"
    script = f"""{lef_reads}
read_def {def_file}
{_pdn_in}density_fill -rules {fill_config}
{_pdn_out}write_def {out_def}
report_design_area
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "fill.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command(["openroad", "-exit", sp])
    proc = subprocess.run(["openroad", "-exit", sp], capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "fill.log"), "w").write(out)
    if proc.returncode != 0 or not os.path.exists(out_def):
        return _cde(objective=f"metal fill of {top}", status="failed", pdk_binding=binding or "none",
                    error="OpenROAD density_fill failed; see fill.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "fill.log"})
    _pdn = _parse_pdn_continuity(out)
    if _pdn and _pdn["destroyed"]:
        return _cde(
            objective=f"metal fill of {top}", status="failed",
            pdk_binding=binding or "none",
            error=("METAL FILL DESTROYED THE POWER GRID: %d supply rail(s) "
                   "entered this stage and only %d survived it. Fill writes "
                   "metal on the same layers the PDN occupies, so this is a "
                   "fill-rule conflict with the power grid, not a wiring "
                   "mistake -- the design can no longer be power-connected."
                   % (_pdn["rails_in"], _pdn["rails_out"])),
            validation={"verdict": "fail"},
            qor={"power_rails_in": _pdn["rails_in"],
                 "power_rails_out": _pdn["rails_out"]},
            provenance={"openroad": "openroad", "log": "fill.log"})
    _pdn_note = None
    if _pdn is None:
        _pdn_note = ("power-net continuity NOT measured (no __PDN_IN__/"
                     "__PDN_OUT__ markers in this log)")
    elif _pdn["absent"]:
        _pdn_note = (
            "this design carries NO supply rails on entry (%d POWER/GROUND-"
            "typed net(s) seen, but none of them special with geometry -- a "
            "tie-off net such as `zero_` carries that sigtype without "
            "distributing power). Metal fill does not create a PDN, so this "
            "is inherited from upstream and the filled result cannot be "
            "power-connected." % _pdn["pg_nets_in"])
    else:
        _pdn_note = ("%d supply rail(s) preserved through metal fill"
                     % _pdn["rails_out"])
    # Count inserted fill shapes. OpenROAD density_fill writes FLOATING fill
    # geometry into a `FILLS <n> ;` ... `END FILLS` DEF section -- the header count
    # is AUTHORITATIVE. The old heuristic counted the text `FILL`/`fill_` in the
    # DEF, which matches neither the `FILLS` section header (word boundary) nor the
    # per-shape `- LAYER ...` entries, so a real fill run reported 0 (observed live:
    # routing.11 inserted 3113 fills but the native CDE said fill_shapes=0). Read
    # the DEF header first; fall back to the OpenROAD FIN-0004 cumulative log total.
    fill_cells = None
    try:
        _def_txt = open(out_def).read()
        _hdr = re.search(r"^\s*FILLS\s+(\d+)\s*;", _def_txt, re.M)
        if _hdr:
            fill_cells = int(_hdr.group(1))
        else:
            # No FILLS section -> fills may be filler CELLS (named instances) instead.
            _named = len(re.findall(r"\bfill_\w+", _def_txt))
            fill_cells = _named if _named else 0
    except Exception as _e:
        print("[" + str(TOOL) + "] fill-shape count from DEF unavailable: "
              + str(_e), flush=True)
    if not fill_cells:
        # FIN-0004 prints a cumulative running total per layer; the LAST is the grand total.
        _fin = re.findall(r"FIN-0004[^\n]*?(\d+)\s*$", out, re.M)
        if _fin:
            fill_cells = int(_fin[-1])
    fill_cells = fill_cells or 0
    # Component preservation: fill must ADD instances, never drop a design cell.
    components_in = _def_components(def_file)
    components_out = _def_components(out_def)
    components_preserved = (
        None if components_in is None or components_out is None
        else components_out >= components_in)
    fills_by_layer = _def_fills_by_layer(out_def)
    # A KLayout map that can actually see the fill this stage just wrote. Emitted
    # unconditionally so no downstream density/QA measurement has to re-derive it
    # (or, worse, accept a silent zero from the shipped map).
    _layermap = _resolve_layermap(params, binding)
    fill_purpose_map = None
    if _layermap and os.path.exists(str(_layermap)):
        fill_purpose_map = _write_fill_purpose_map(
            _layermap, os.path.join(_OUTPUT_DIR, "layermap_with_fill_purpose.map"))
    # If the caller supplies a per-layer density measurement, disposition it here so
    # the fill stage's verdict already honors the PDK-specific min-density policy
    # (sky130A: min shortfall = advisory, not a fail). Absent a measurement, keep the
    # historical insert-only pass (density is then confirmed by the density_check
    # scenario / DRC).
    _dens = params.get("layer_density")
    if isinstance(_dens, str) and os.path.exists(_dens):
        try:
            _dj = json.load(open(_dens))
            _dens = _dj.get("layers", _dj)
        except Exception:
            _dens = None
    density_result = None
    verdict = "pass"
    note = "metal fill inserted; verify density via DRC"
    try:
        shorts = int(params.get("fill_short_overlaps", 0) or 0)
    except (TypeError, ValueError):
        shorts = 0
    if isinstance(_dens, dict) and _dens:
        pdk = _resolve_pdk_name(binding, params)
        density_result = _classify_density(_dens, pdk, binding)
        verdict = density_result["verdict"]
        if shorts > 0 and verdict != "fail":
            verdict = "fail"
        note = (f"metal fill inserted; {density_result['max_density_violations']} "
                f"max-density violation(s), {density_result['min_density_shortfalls']} "
                f"min-density shortfall(s) "
                f"({density_result['advisories']} advisory on sky130A), "
                f"{shorts} fill short(s); verdict {verdict} because "
                f"{density_result['verdict_basis']}; "
                + density_result["min_density_policy"])
        try:
            json.dump({"pdk": pdk, "shorts": shorts, **density_result},
                      open(os.path.join(_OUTPUT_DIR, "density_disposition.json"), "w"),
                      indent=2)
        except Exception as _e:
            print("[" + str(TOOL) + "] density_disposition write skipped: " + str(_e),
                  flush=True)
    _results = {"filled_def": {"value": "filled.def", "unit": "-"},
                "fill_shapes": {"value": fill_cells, "unit": "count"}}
    _qor = {"fill_shapes": fill_cells}
    _signoff = {"filled_def": "filled.def", "fill_config": os.path.basename(str(fill_config)),
                "fill_config_source": _fill_src, "report": "fill.log"}
    # --- BEOL SCOPE OBLIGATION (DX-173) --------------------------------------
    #
    # This stage inserts BEOL geometry (`density_fill` writes floating fill on
    # the same metal layers the design and its PDN occupy) but invokes NO
    # KLayout deck itself -- there is no `deck_vars` this attempt could ever
    # truthfully declare. That is not the same as "unscreened": the inserted
    # fill's rule-legality is verified by whichever downstream `drc`/`antenna`/
    # `erc` attempt consumes THIS attempt's `filled_def`/`filled_gds` output
    # with its own genuine `beol: true` KLayout deck scope. Recording that
    # obligation explicitly (rather than a vague "run DRC after fill" aside)
    # lets `catalog/validate_check_scope.py` trace the discharge chain instead
    # of either (a) stamping an undeserved deck_vars on this attempt, or
    # (b) silently dropping the requirement.
    _signoff["beol_scope_obligation"] = {
        "status": "discharged_downstream",
        "owner": "downstream drc/antenna/erc attempt consuming this attempt's "
                 "filled_def/filled_gds",
        "note": "metal-fill runs OpenROAD density_fill only and never invokes "
                "a KLayout deck; validate_check_scope.py confirms discharge "
                "per-attempt by finding a downstream drc/antenna/erc attempt "
                "in the same design version that consumes this attempt's "
                "output (directly, or via an intermediate streamout/pass-"
                "through stage) and itself genuinely declares beol=true. "
                "Absent that chain, this attempt stays NOT ASSESSABLE -- it "
                "is never retroactively marked scoped.",
    }
    _assumptions = ["fill inserted per the node fill config / density windows from "
                    "the binding; BEOL rule-legality of the inserted fill is "
                    "verified downstream by the drc/antenna/erc attempt that "
                    "consumes this attempt's filled_def/filled_gds (see "
                    "signoff_evidence.beol_scope_obligation) -- this stage "
                    "does not itself invoke a KLayout deck"]
    if density_result is not None:
        _results["min_density_advisories"] = {"value": density_result["advisories"],
                                              "unit": "count"}
        _results["density_hard_violations"] = {"value": density_result["hard_violations"],
                                               "unit": "count"}
        _qor["density_hard_violations"] = density_result["hard_violations"]
        _qor["min_density_advisories"] = density_result["advisories"]
        _signoff["min_density_policy"] = density_result["min_density_policy"]
        _signoff["per_layer_density"] = density_result["classified"]
        _signoff["density_disposition"] = "density_disposition.json"
        _assumptions.append(
            "sky130A metal MINIMUM-density is a recommended CMP rule (mX.pd.1 = "
            "RR/A/AL; met5 has no PDK min-density rule) -> min shortfalls are "
            "ADVISORY, not gating; maximum-density overages + shorts stay hard; "
            "advisory scope is sky130A only")
    _qor = dict(_qor or {})
    _qor.update({
        # Measured, not assumed: what this stage was handed and what it gave
        # back. Rails are the meaningful count.
        "power_rails_in": (_pdn or {}).get("rails_in"),
        "power_rails_out": (_pdn or {}).get("rails_out"),
        "power_rails_preserved": (_pdn or {}).get("preserved"),
        # An intact grid does not mean every cell reaches it.
        "unconnected_pg_pins_in": (_pdn or {}).get("unconnected_pg_pins_in"),
        "unconnected_pg_pins_out": (_pdn or {}).get("unconnected_pg_pins_out"),
    })
    _signoff = dict(_signoff or {})
    _signoff.update({"power_net_continuity": _pdn,
                     "power_net_continuity_note": _pdn_note})
    _results["components_preserved"] = {"value": components_preserved, "unit": "bool"}
    _results["components_in"] = {"value": components_in, "unit": "count"}
    _results["components_out"] = {"value": components_out, "unit": "count"}
    _qor.update({"components_in": components_in, "components_out": components_out,
                 "fill_shapes": fill_cells})
    if fills_by_layer:
        _signoff["fill_shapes_by_layer"] = fills_by_layer["per_layer"]
        _signoff["fill_shapes_def_header"] = fills_by_layer["total"]
    if fill_purpose_map:
        _signoff["klayout_fill_purpose_map"] = fill_purpose_map
        _assumptions.append(
            "a KLayout layer map with explicit FILL-purpose entries is emitted at "
            "`%s` (derived from %s, which is NOT modified). KLayout's map_file "
            "mechanism generates only the layers a map declares, so reading this "
            "attempt's DEF with the PDK's shipped map silently drops every FILLS "
            "shape with an ignorable warning; any density/QA measurement of this "
            "output must use the emitted map and reconcile against the DEF's own "
            "`FILLS %s ;` header." % (fill_purpose_map["path"],
                                      os.path.basename(fill_purpose_map["base"]),
                                      (fills_by_layer or {}).get("total", "n")))
    # Every assertion names what measured it. Without this a reviewer cannot tell a
    # binding-declared non-gating advisory from real unfinished work, and the safe
    # response to that ambiguity is to refuse blessing -- correctly, but on
    # documentation rather than on evidence.
    _checks = {
        "fill_inserted": fill_cells > 0,
        "components_preserved": components_preserved,
        "power_rails_preserved": (_pdn or {}).get("preserved"),
        "fill_shape_count_matches_def_header": (
            None if not fills_by_layer
            else sum(fills_by_layer["per_layer"].values()) == fills_by_layer["total"]),
    }
    _checks_evidence = {
        "fill_inserted": "filled.def `FILLS <n> ;` header (authoritative), with "
                         "OpenROAD FIN-0004 in fill.log as fallback",
        "components_preserved": "COMPONENTS header of the input DEF vs filled.def",
        "power_rails_preserved": "fill.log `__PDN_IN__`/`__PDN_OUT__` ODB probe "
                                 "counting special POWER/GROUND nets carrying SWIRE "
                                 "geometry",
        "fill_shape_count_matches_def_header":
            "per-layer `- LAYER ...` entries in the filled.def FILLS section summed "
            "against that section's own header count -- the independent cross-check "
            "that catches a reader silently dropping a purpose class",
    }
    if density_result is not None:
        _dchecks, _devidence = _density_checks_block(density_result, shorts, verdict)
        _checks.update(_dchecks)
        _checks_evidence.update(_devidence)
    return _cde(
        objective=f"metal fill / density of {top}", status="completed",
        pdk_binding=binding or "none",
        results=_results,
        qor=_qor,
        signoff=_signoff,
        inputs_ref={"def_file": def_file, "tech_lef": tech_lef, "fill_config": fill_config},
        assumptions=_assumptions,
        validation={"verdict": verdict, "note": note,
                    "checks": _checks, "checks_evidence": _checks_evidence},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3), "log": "fill.log"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("metal_fill", "fill", "density_fill"):
        return _fill(params)
    if s in ("density_check", "check_density", "verify_density"):
        return _density_check(params)
    return _cde(objective="metal fill", status="failed",
                error=f"unknown scenario '{s}'; supported: metal_fill, density_check",
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
