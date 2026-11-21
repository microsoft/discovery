#!/usr/bin/env python3
"""antenna_erc_utils.py -- real antenna / ERC signoff, two engines.

Node-aware antenna signoff. The engine is selected from the PDK binding
(`antenna_rules.engine`), because the antenna ruleset is NOT the same shape
across PDKs:

  * KLayout deck (engine=klayout): runs a KLayout antenna/ERC deck on a
    GDS/OASIS/DEF layout (`klayout -b -r <deck> ...`) and parses the KLayout
    report database (.lyrdb) for per-check violation counts.
  * Magic antennacheck (engine=magic): sky130 (and PDKs that ship no KLayout
    antenna deck) carry their antenna ruleset as `antenna <layer> ...`
    directives inside the Magic techfile; this reads the layout (DEF via
    tech+cell LEF, or GDS/mag), extracts, runs Magic's built-in `antennacheck`,
    and counts the violations Magic files as feedback.

Both paths fail closed on a missing engine/deck/techfile/layout and never
fabricate a clean result. Antenna ratios / rule sources come from the PDK
binding. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

TOOL = "antenna-erc"
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
                or low.endswith("_report.json") or low.endswith(".lyrdb")
                or low.endswith(".csv")):
            return "reports"
        if (low.endswith((".log", ".tcl", ".ys", ".sh", ".do", ".drc", ".lydrc", ".rb"))
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
          "- `reports/` \u2014 antenna/ERC report DB (`*.lyrdb`), `REPORT.md`",
          "- `logs/` \u2014 verbatim KLayout log and the exact run command", ""]
    return "\n".join(L)


def _write_summary_md(results):
    return  # option b: SUMMARY.md removed (tool emits REPORT.md; agent emits EXECUTIVE_SUMMARY.md)
    path = os.path.join(_OUTPUT_DIR, "SUMMARY.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render_summary_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def _write_signoff_results(results):
    """Materialize the blessed-attempt output contract's results/ artifact.

    A pure signoff check (no netlist/GDS/DEF of its own to hand off) never
    writes a leftover file for `_organize_output()` to route into results/,
    so results/ was created (via quick_setup) but left with zero non-empty
    files -- a packaging defect distinct from whether the check itself ran
    (DX-170: the antennacheck run genuinely happened; only the results/
    artifact was never packaged). Write a small, real summary of this run's
    own already-computed signoff evidence -- no new measurement, just the
    genuine result repackaged into the directory the contract requires.
    """
    path = os.path.join(_OUTPUT_DIR, "antenna_signoff.json")
    payload = {
        "$schema": "chip-antenna-erc-signoff/1",
        "tool": results.get("tool", TOOL),
        "status": results.get("status"),
        "verdict": (results.get("validation") or {}).get("verdict"),
        "results": results.get("results"),
        "signoff_evidence": results.get("signoff_evidence"),
        "provenance": results.get("provenance"),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        print("[" + str(TOOL) + "] wrote " + path, flush=True)
    except Exception as _e:
        print("[" + str(TOOL) + "] signoff-results generation skipped: " + str(_e), flush=True)


def save_final_results(results):
    results = _finalize_envelope(results)
    path = os.path.join(_OUTPUT_DIR, "common_design_envelope.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    for fn, lbl in ((_write_report_md, "report"), (_write_summary_md, "summary"),
                    (_write_signoff_results, "signoff-results")):
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


def _klayout_version():
    try:
        out = subprocess.run(["klayout", "-v"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return txt.splitlines()[0] if txt else "klayout"
    except Exception:
        return "klayout"


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "KLayout antenna/ERC", "version": _klayout_version()}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "rule_deck_check"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _parse_lyrdb(path):
    per_check = {}
    total = 0
    try:
        tree = ET.parse(path)
        for item in tree.getroot().iter("item"):
            cat = (item.findtext("category") or "unknown").strip().strip("'\"") or "unknown"
            per_check[cat] = per_check.get(cat, 0) + 1
            total += 1
    except Exception as e:
        return None, {"parse_error": str(e)}
    return total, per_check


#: Ruby globals a deck may legitimately read that are never `-rd` variables.
_RUBY_BUILTIN_GLOBALS = frozenset((
    "stdout", "stderr", "stdin", "PROGRAM_NAME", "LOAD_PATH", "LOADED_FEATURES",
    "DEBUG", "VERBOSE", "FILENAME", "SAFE", "0", "1", "2", "3", "4", "5", "6",
    "7", "8", "9"))
#: A `$var` used in one of these shapes has a fallback, so leaving it unset is
#: not fatal (`$thr ||= 4`, `if $topcell`, `$x.nil?`, `defined?($x)` ...).
_OPTIONAL_USE = (r"\$%s\s*(?:\|\||&&|\?|\.nil\?|\.to_s\.empty\?)",
                 r"(?:if|unless|\|\||&&|defined\?\()\s*\(?\s*\$%s\b")
#: KLayout DRC decks in the wild read the layout / report / top cell under
#: different names: sky130/OpenLane use `input`/`report`/`topcell`, the ORFS
#: FreePDK45 deck reads `source($in_gds)` / `report(..., $report_file)`. Passing
#: only one convention silently hands the other deck `nil` ("No layout loaded").
_LAYOUT_VARS = ("input", "in_gds")
_REPORT_VARS = ("report", "report_file")
_TOP_VARS = ("topcell", "top_cell")
#: Run-time switch names a deck may expose to restrict itself to antenna rules.
_ANTENNA_ONLY_SWITCHES = ("antenna_only", "antenna_only_mode", "only_antenna",
                          "run_antenna_only")


def _deck_text(deck):
    """Ruby/DSL body of a KLayout deck (.lydrc XML is unwrapped), '' if unreadable."""
    import html as _html
    try:
        with open(str(deck), encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    m = re.search(r"<text>(.*)</text>", text, re.S)
    if m:
        text = _html.unescape(m.group(1))
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


def _deck_variables(text):
    """{name: required?} for every `$name` the deck reads (builtins excluded)."""
    found = {}
    for name in re.findall(r"\$([A-Za-z_]\w*)", text):
        if name in _RUBY_BUILTIN_GLOBALS or name in found:
            continue
        optional = any(re.search(pat % re.escape(name), text) for pat in _OPTIONAL_USE)
        assigned = re.search(r"\$%s\s*(?:\|\|)?=[^=~]" % re.escape(name), text)
        found[name] = not (optional or assigned)
    return found


def _deck_reads_lefdef(text):
    return bool(re.search(r"lefdef|LEFDEF|\.def\b|read_def", text))


def _klayout_rd_vars(layout, report_db, top, threads=None, deck_vars=None):
    """Ordered -rd map: every known convention, caller deck_vars win per key."""
    rd = {}
    for name in _LAYOUT_VARS:
        rd[name] = str(layout)
    for name in _REPORT_VARS:
        rd[name] = str(report_db)
    if top:
        for name in _TOP_VARS:
            rd[name] = str(top)
    if threads is not None:
        rd["thr"] = str(int(threads))
    for key, value in (deck_vars or {}).items():
        rd[str(key)] = str(value)
    return rd


def _klayout_preflight(deck, layout, rd):
    """Fail-closed deck/input compatibility check. Returns (error, deck_vars_info)."""
    text = _deck_text(deck)
    info = {"deck_variables": _deck_variables(text) if text else None}
    if not text:
        return None, info
    missing = sorted(name for name, required in info["deck_variables"].items()
                     if required and not rd.get(name))
    info["deck_variables_missing"] = missing
    if missing:
        return ("KLayout deck %s reads run-time variable(s) %s that no value was "
                "supplied for; KLayout would see nil and fail (e.g. 'No layout "
                "loaded'). Supply them via deck_vars, e.g. {\"deck_vars\": {%s}}."
                % (os.path.basename(str(deck)),
                   ", ".join("$" + n for n in missing),
                   ", ".join('"%s": "..."' % n for n in missing))), info
    if str(layout).lower().endswith(".def") and not _deck_reads_lefdef(text):
        return ("KLayout deck %s loads its input with source()/GDS semantics and "
                "has no LEF/DEF reader setup, but the layout is a DEF (%s): this "
                "deck needs a GDS/OASIS layout; stream out first (chip-gds-assembly) "
                "and pass the .gds/.oas as `layout`."
                % (os.path.basename(str(deck)), os.path.basename(str(layout)))), info
    return None, info


def _antenna_check(params):
    if not shutil.which("klayout"):
        return _cde(objective="antenna/ERC", status="failed",
                    error="klayout not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    layout = params.get("layout") or params.get("gds") or params.get("def_file")
    deck = (params.get("deck") or params.get("antenna_rules")
            or binding.get("antenna_rules") or binding.get("erc_rules"))
    top = params.get("top")
    for n, v in (("layout", layout), ("deck", deck)):
        if not v:
            return _cde(objective="antenna/ERC", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}' (deck comes from the PDK "
                              "binding antenna_rules/erc_rules)", validation={"verdict": "fail"})
    for p in (layout, deck):
        if not os.path.exists(str(p)):
            return _cde(objective="antenna/ERC", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    report_db = os.path.join(_OUTPUT_DIR, "antenna_erc.lyrdb")
    deck_text = _deck_text(deck)
    deck_vars = dict(params.get("deck_vars") or {})
    # Antenna-only switch: if the deck exposes one as a run-time variable, turn it
    # on so only the antenna group runs. (The ORFS FreePDK45 deck has none -- its
    # FEOL/BEOL/ANTENNA groups are hard-coded Ruby locals -- so it runs the whole
    # DRC deck and the non-antenna categories are classified out below.)
    antenna_switch = next((n for n in _deck_variables(deck_text)
                           if n.lower() in _ANTENNA_ONLY_SWITCHES), None)
    if antenna_switch and antenna_switch not in deck_vars:
        deck_vars[antenna_switch] = "true"
    rd = _klayout_rd_vars(layout, report_db, top, None, deck_vars)
    preflight_error, deck_info = _klayout_preflight(deck, layout, rd)
    if preflight_error:
        return _cde(objective=f"antenna/ERC of {top or os.path.basename(str(layout))}",
                    status="failed", pdk_binding=binding or "none",
                    error=preflight_error, validation={"verdict": "fail"},
                    signoff={"deck": os.path.basename(str(deck)),
                             "deck_variables": deck_info})
    cmd = ["klayout", "-b", "-r", str(deck)]
    for k, v in rd.items():
        cmd += ["-rd", f"{k}={v}"]
    log = os.path.join(_OUTPUT_DIR, "antenna_erc.log")
    if os.path.exists(report_db):
        os.remove(report_db)  # a stale DB must never be read as this run's result
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(log, "w").write(out)
    if proc.returncode != 0 and not os.path.exists(report_db):
        return _cde(objective=f"antenna/ERC of {top or os.path.basename(str(layout))}",
                    status="failed", pdk_binding=binding or "none",
                    error="KLayout antenna/ERC failed; see antenna_erc.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"klayout": _klayout_version(), "log": "antenna_erc.log"})
    total, per_check = _parse_lyrdb(report_db) if os.path.exists(report_db) else (None, {})
    if total is None:
        # No/unparseable report DB: the result is unmeasured. A count scraped
        # from the log (or a default 0) would be a fabricated clean.
        return _cde(objective=f"antenna/ERC of {top or os.path.basename(str(layout))}",
                    status="failed", pdk_binding=binding or "none",
                    error=("KLayout exited %d without a parseable report database "
                           "(%s); antenna/ERC result unmeasured; see antenna_erc.log"
                           % (proc.returncode, per_check.get("parse_error")
                              or "antenna_erc.lyrdb missing")),
                    validation={"verdict": "fail"},
                    signoff={"deck_variables": deck_info},
                    provenance={"klayout": _klayout_version(), "log": "antenna_erc.log"})
    # Category classification. For an antenna check whose deck carries antenna
    # rules, only *ANTENNA* categories are antenna violations; anything else the
    # deck emitted (e.g. FreePDK45's WELL.4 from the full DRC deck) is reported
    # as non_antenna_categories -- informational, owned by chip-drc.
    antenna_only = params.get("antenna_only")
    if antenna_only is None:
        antenna_only = (params.get("scenario") == "antenna_check"
                        and bool(re.search(r"antenna", deck_text, re.I)))
    else:
        antenna_only = str(antenna_only).strip().lower() in ("1", "true", "yes", "on")
    non_antenna = {}
    if antenna_only:
        non_antenna = {c: n for c, n in per_check.items() if "ANTENNA" not in c.upper()}
        per_check = {c: n for c, n in per_check.items() if "ANTENNA" in c.upper()}
        total = sum(per_check.values())
    waivers = params.get("waivers") or []
    waived_checks = {}
    bad = []
    for w in waivers:
        if not (w.get("rule") and w.get("owner") and w.get("justification")):
            bad.append(w)
            continue
        waived_checks[w["rule"]] = w
    if bad:
        return _cde(objective="antenna/ERC", status="failed", pdk_binding=binding or "none",
                    error="every waiver requires rule + owner + justification",
                    signoff={"invalid_waivers": bad}, validation={"verdict": "fail"})
    unwaived = (sum(c for chk, c in per_check.items() if chk not in waived_checks)
                if per_check else total)
    clean = unwaived == 0
    verdict = "pass" if clean else "fail"
    classification = {
        "antenna_only": bool(antenna_only),
        "rule": ("only categories containing 'ANTENNA' count as antenna violations"
                 if antenna_only else "every deck category counts"),
        "antenna_only_switch": antenna_switch,
        "non_antenna_categories": non_antenna,
        "non_antenna_items": sum(non_antenna.values())}
    assumptions = ["signoff requires zero un-waived antenna/ERC violations; "
                   "antenna ratios / ERC rules from the binding"]
    if non_antenna:
        assumptions.append(
            "deck %s also ran non-antenna DRC rules (%d item(s) in %s); they are "
            "reported as non_antenna_categories for information only and do not "
            "count as antenna violations -- DRC signoff is chip-drc's job"
            % (os.path.basename(str(deck)), sum(non_antenna.values()),
               ", ".join(sorted(non_antenna))))
    return _cde(
        objective=f"antenna / ERC check of {top or os.path.basename(str(layout))}",
        status="completed", pdk_binding=binding or "none",
        results={"antenna_erc_violations": {"value": total, "unit": "count"},
                 "unwaived_violations": {"value": unwaived, "unit": "count"},
                 "non_antenna_categories": non_antenna},
        qor={"antenna_erc_violations": total, "unwaived_violations": unwaived,
             "non_antenna_items": sum(non_antenna.values())},
        signoff={"per_check": per_check, "report_db": "antenna_erc.lyrdb",
                 "waived_checks": sorted(waived_checks.keys()),
                 "clean": clean, "deck": os.path.basename(str(deck)),
                 "report": "antenna_erc.log",
                 "category_classification": classification,
                 "non_antenna_categories": non_antenna,
                 "rd_variables": sorted(rd), "deck_variables": deck_info},
        inputs_ref={"layout": layout, "deck": deck},
        assumptions=assumptions,
        validation={"verdict": verdict,
                    "note": "antenna/ERC clean" if clean
                    else f"{unwaived} un-waived antenna/ERC violation(s)"},
        provenance={"klayout": _klayout_version(), "runtime_s": round(elapsed, 3),
                    "log": "antenna_erc.log", "deck": os.path.basename(str(deck))},
    )


def _as_path(v):
    """Extract a filesystem path from a binding value that may be a bare string
    or an object like {"path": ...} / {"rule_source": {"path": ...}}."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        if isinstance(v.get("path"), str):
            return v["path"]
        rs = v.get("rule_source")
        if isinstance(rs, dict) and isinstance(rs.get("path"), str):
            return rs["path"]
    return None


def _antenna_engine(params):
    """Which antenna engine to use: 'magic', 'klayout', or None (let the deck
    presence decide). Explicit param wins; else read antenna_rules.engine from
    the binding. sky130's antenna ruleset is Magic-only, so a binding that names
    engine=magic (or points antenna_rules at a Magic techfile) routes to Magic."""
    eng = (params.get("engine") or "").strip().lower()
    if eng in ("magic", "klayout"):
        return eng
    binding = params.get("pdk_binding") or {}
    ar = params.get("antenna_rules") or binding.get("antenna_rules")
    if isinstance(ar, dict):
        be = str(ar.get("engine", "")).strip().lower()
        if be in ("magic", "klayout"):
            return be
        src = _as_path(ar)
        if src and src.lower().endswith((".tech", ".magicrc")):
            return "magic"
    return None


def _magic_version():
    try:
        out = subprocess.run(["magic", "--version"], capture_output=True,
                             text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return "magic " + (txt.splitlines()[0] if txt else "")
    except Exception:
        return "magic"


def _antenna_check_magic(params):
    """sky130-style antenna signoff via Magic `antennacheck`.

    open_pdks ships NO KLayout antenna deck for sky130; the antenna ruleset is
    the `antenna <layer> ...` directives in the Magic techfile (bound as
    antenna_rules.rule_source), evaluated by Magic's built-in `antennacheck`
    after extraction. This reads the routed layout (DEF via tech+cell LEF, or a
    GDS/mag), extracts, runs `antennacheck`, and counts the violations Magic
    files as feedback. Fails closed if Magic or the techfile/layout is absent --
    never fabricates a clean result.
    """
    if not shutil.which("magic"):
        return _cde(objective="antenna (Magic antennacheck)", status="failed",
                    error="magic not found on PATH (sky130 antenna check is "
                          "Magic-based, not KLayout)", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    ar = params.get("antenna_rules") or binding.get("antenna_rules") or {}
    layout = params.get("layout") or params.get("def_file") or params.get("gds")
    top = params.get("top")
    # Techfile carrying the antenna directives (the bound rule source).
    techfile = (_as_path(params.get("techfile")) or _as_path(ar)
                or _as_path(binding.get("magic_tech"))
                or _as_path((binding.get("rule_decks") or {}).get("magic_tech")))
    # Prefer a real .magicrc sibling of the techfile (sets scale + layer map for
    # DEF/LEF reads); fall back to loading the techfile directly with -T.
    rcfile = _as_path(params.get("magicrc"))
    if not rcfile and techfile and techfile.lower().endswith(".tech"):
        _cand = os.path.join(os.path.dirname(techfile),
                             os.path.splitext(os.path.basename(techfile))[0] + ".magicrc")
        if os.path.isfile(_cand):
            rcfile = _cand
    for n, v in (("layout", layout), ("techfile/antenna_rules", techfile)):
        if not v:
            return _cde(objective="antenna (Magic antennacheck)", status="failed",
                        pdk_binding=binding or "none",
                        error=f"missing required field '{n}' (antenna_rules must bind "
                              "the sky130 Magic techfile carrying the antenna directives)",
                        validation={"verdict": "fail"})
    for p in (layout, techfile):
        if not os.path.exists(str(p)):
            return _cde(objective="antenna (Magic antennacheck)", status="failed",
                        pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})

    low = str(layout).lower()
    tech_lef = (_as_path(params.get("tech_lef")) or _as_path(binding.get("tech_lef")))
    cell_lefs = params.get("cell_lef") or params.get("lef") \
        or binding.get("stdcell_lef") or binding.get("cell_lef")
    if not isinstance(cell_lefs, (list, tuple)):
        cell_lefs = [cell_lefs] if cell_lefs else []
    cell_lefs = [_as_path(x) for x in cell_lefs if _as_path(x)]
    topcell = top or os.path.splitext(os.path.basename(str(layout)))[0]

    tcl = os.path.join(_WORK_DIR, "run_magic_antenna.tcl")
    lines = ["crashbackups stop", "drc off", "snap internal"]
    if low.endswith(".def"):
        if not tech_lef:
            return _cde(objective="antenna (Magic antennacheck)", status="failed",
                        pdk_binding=binding or "none",
                        error="a DEF layout needs tech_lef (and cell LEF) to read; "
                              "bind tech_lef/stdcell_lef", validation={"verdict": "fail"})
        lines.append(f"lef read {tech_lef}")
        for cl in cell_lefs:
            lines.append(f"lef read {cl}")
        lines.append(f"def read {layout}")
        lines.append(f"load {topcell} -dereference")
    elif low.endswith((".gds", ".gdsii", ".gds2", ".oas", ".oasis")):
        lines.append(f"gds read {layout}")
        lines.append(f"load {topcell} -dereference")
    else:  # .mag or a magic cell name
        lines.append(f"load {os.path.splitext(str(layout))[0]} -dereference")
    lines += ["select top cell", "expand", "extract do local", "extract no all",
              "extract all",
              # *** CLEAR FEEDBACK BEFORE THE CHECK -- THE COUNT IS CUMULATIVE. ***
              # Magic's feedback list is a SESSION-WIDE accumulator, not an
              # antennacheck output. `extract all` files its own entries into it
              # ("device missing 1 terminal; connecting remainder to node VGND"),
              # which are EXTRACTION artifacts of decap/fill cells and say nothing
              # about antenna ratios. Without this clear, those extraction warnings
              # are reported as antenna violations.
              # MEASURED on a real filled bsum16 GDS:
              #   after `extract all`   feedback count = 10   <- all extraction
              #   after `feedback clear`               = 0
              #   after `antennacheck`                 = 0    <- ZERO real violations
              # i.e. the stage reported 10 antenna violations on a design that has
              # none. This over-reports, so it fails SAFE -- but a fabricated
              # violation is still a wrong number, and chasing it would have meant
              # inserting diodes to fix a defect that does not exist.
              "feedback clear",
              "antennacheck",
              # Now the count is antennacheck's alone: it files one feedback entry
              # per violation, and nothing else has contributed to the list.
              "puts \"ANTENNA_FEEDBACK_COUNT: [feedback count]\"",
              "quit -noprompt"]
    with open(tcl, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    cmd = ["magic", "-dnull", "-noconsole"]
    if rcfile and os.path.isfile(rcfile):
        cmd += ["-rcfile", rcfile]
    else:
        cmd += ["-T", str(techfile)]
    cmd += [tcl]
    log = os.path.join(_OUTPUT_DIR, "antenna_magic.log")
    # PDK_ROOT must be set or the vendor magicrc falls back to the ORIGINAL BUILD
    # MACHINE's techfile path, loads no technology, reads no geometry and reports
    # a FALSE CLEAN while exiting 0 (measured).
    env = _magic_env(techfile=techfile, rcfile=rcfile, params=params,
                     extra={"MAGTYPE": "mag"})
    t0 = time.time()
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR,
                          env=env, stdin=subprocess.DEVNULL)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    with open(log, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n===== magic stdout/stderr =====\n" + out)

    # Parse the deterministic feedback count; fall back to counting the
    # per-violation antenna lines magic prints.
    # *** FAIL CLOSED WHEN MAGIC NEVER ACTUALLY READ THE LAYOUT. ***
    # MEASURED FALSE CLEAN: sky130A.magicrc carries a BUILD-MACHINE ABSOLUTE
    # PATH to the techfile ("/root/work/open-pdks/.../sky130A.tech"). When that
    # path is absent Magic prints "Could not find file ... in any of these
    # directories", loads NO technology, and therefore has no `cifinput` section
    # -- so `gds read` silently imports nothing, `extract` runs on an EMPTY cell,
    # `antennacheck` finds nothing, and `feedback count` returns 0. MAGIC EXITS
    # 0 THROUGHOUT, so the old returncode-only guard never fired and the tool
    # reported "0 violations / verdict pass / residual 0.0 / alignment ok" on a
    # run THAT INSPECTED NOTHING.
    #
    # A zero from a check that never looked is the single worst value this tool
    # can emit: it is indistinguishable from a genuinely clean antenna result
    # and it closes a mandatory tapeout gate. So the count is only trusted once
    # the run is POSITIVELY shown to have loaded a technology and read cells --
    # absence of an error message is NOT evidence that the layout was read.
    _fatal_markers = [
        ("could not find file", "Magic could not find its technology file "
                                "(the PDK .magicrc may carry a build-machine "
                                "absolute path that does not exist here)"),
        ('nothing in "cifinput" section', "the loaded techfile has no cifinput "
                                          "section, so Magic cannot read GDS"),
        ("couldn't be read", "the layout cell could not be read"),
        ("nothing here to extract", "extraction found no geometry"),
        ("no technology has been read", "no technology was loaded"),
    ]
    _low = out.lower()
    _fatal = [why for marker, why in _fatal_markers if marker in _low]
    # Positive evidence the run had a technology AND ingested the layout.
    _tech_ok = bool(re.search(r"technology\s+\S+", out, re.I)) and not _fatal
    _read_ok = bool(re.search(r"^\s*Reading\s+\"", out, re.M)) or \
        bool(re.search(r"Library name:", out))
    if _fatal or not _read_ok:
        _why = "; ".join(_fatal) if _fatal else (
            "Magic produced no evidence of reading any cell from the layout")
        return _cde(
            objective=f"antenna check of {topcell}", status="failed",
            pdk_binding=binding or "none",
            error=("antenna check DID NOT INSPECT THE LAYOUT -- refusing to "
                   "report a count. " + _why + ". A zero from a check that "
                   "never read the design is not a clean result; it is an "
                   "unrun check. Bind a working Magic technology (a .magicrc "
                   "whose techfile path resolves in this environment, or a "
                   "techfile carrying a cifinput section) and re-run.\n"
                   "see antenna_magic.log:\n" + out[-1200:]),
            signoff={"engine": "magic", "check": "antennacheck",
                     "layout_read": False, "technology_loaded": bool(_tech_ok),
                     "assessed": False},
            validation={"verdict": "not_assessable",
                        "note": "layout never read; count withheld"},
            provenance={"magic": _magic_version(), "log": "antenna_magic.log"})

    total = None
    m = re.search(r"ANTENNA_FEEDBACK_COUNT:\s*(\d+)", out)
    if m:
        total = int(m.group(1))
    if total is None:
        hits = re.findall(r"[Aa]ntenna (?:violation|error)", out)
        total = len(hits) if hits else None
    if total is None:
        # No parseable result AND a nonzero exit => genuinely could not run:
        # fail closed rather than laundering an unknown into a clean pass.
        if proc.returncode != 0:
            return _cde(objective=f"antenna check of {topcell}", status="failed",
                        pdk_binding=binding or "none",
                        error="magic antennacheck produced no parseable result; see "
                              "antenna_magic.log:\n" + out[-1500:],
                        validation={"verdict": "fail"},
                        provenance={"magic": _magic_version(), "log": "antenna_magic.log"})
        total = 0  # magic ran clean, printed no violations

    waivers = params.get("waivers") or []
    bad = [w for w in waivers
           if not (w.get("rule") and w.get("owner") and w.get("justification"))]
    if bad:
        return _cde(objective="antenna (Magic antennacheck)", status="failed",
                    pdk_binding=binding or "none",
                    error="every waiver requires rule + owner + justification",
                    signoff={"invalid_waivers": bad}, validation={"verdict": "fail"})
    waived = len([w for w in waivers if w.get("rule")])
    unwaived = max(0, total - waived)
    clean = unwaived == 0
    verdict = "pass" if clean else "fail"
    return _cde(
        objective=f"antenna check (Magic antennacheck) of {topcell}",
        status="completed", pdk_binding=binding or "none",
        results={"antenna_erc_violations": {"value": total, "unit": "count"},
                 "unwaived_violations": {"value": unwaived, "unit": "count"}},
        qor={"antenna_erc_violations": total, "unwaived_violations": unwaived},
        signoff={"engine": "magic", "check": "antennacheck",
                 "techfile": os.path.basename(str(techfile)),
                 "waived": waived, "clean": clean, "report": "antenna_magic.log"},
        inputs_ref={"layout": layout, "techfile": techfile,
                    **({"tech_lef": tech_lef} if tech_lef else {}),
                    **({"cell_lef": cell_lefs} if cell_lefs else {})},
        assumptions=["signoff requires zero un-waived antenna violations; sky130 "
                     "antenna ruleset = Magic techfile directives via antennacheck "
                     "(no KLayout antenna deck exists for this PDK)"],
        validation={"verdict": verdict,
                    "note": "antenna clean (Magic antennacheck)" if clean
                    else f"{unwaived} un-waived antenna violation(s)"},
        provenance={"magic": _magic_version(), "runtime_s": round(elapsed, 3),
                    "log": "antenna_magic.log",
                    "techfile": os.path.basename(str(techfile))},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("antenna_check", "erc_check", "antenna_erc"):
        # Engine selection: sky130 (and any PDK whose antenna ruleset ships as
        # Magic techfile directives) has NO KLayout antenna deck -- route it to
        # Magic `antennacheck`. A PDK that ships a real KLayout antenna/ERC deck
        # stays on the KLayout path. The engine comes from the binding
        # (antenna_rules.engine) or an explicit `engine` param.
        if _antenna_engine(params) == "magic":
            return _antenna_check_magic(params)
        return _antenna_check(params)
    return _cde(objective="antenna/ERC", status="failed",
                error=f"unknown scenario '{s}'; supported: antenna_check, erc_check",
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
