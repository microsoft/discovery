#!/usr/bin/env python3
"""drc_utils.py -- real KLayout batch Design-Rule-Check.

Runs a KLayout DRC rule deck (`klayout -b -r <deck> -rd input=<layout>
-rd in_gds=<layout> -rd report=<db> -rd report_file=<db> ...`) on a GDS/OASIS/DEF layout, parses the KLayout report database
(.lyrdb XML), and reports the violation count with a per-rule breakdown. DRC is a
mandatory tapeout gate: zero un-waived violations to sign off. Node-aware -- the
rule deck comes from the PDK binding. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

TOOL = "drc"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


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


def _is_ident(s):
    """True if *s* is a safe cell identifier -- blocks script injection via
    user-supplied top-cell names interpolated into Magic Tcl scripts."""
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
        if (low.endswith((".log", ".tcl", ".ys", ".sp", ".sh", ".do", ".drc", ".rb"))
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
          "- `reports/` \u2014 DRC report DB (`*.lyrdb`), `REPORT.md`",
          "- `logs/` \u2014 verbatim KLayout log and the exact run command", ""]
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


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None,
         qor=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "KLayout DRC", "version": _klayout_version()},
                       {"name": "Magic DRC", "version": _magic_version()}],
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


def _klayout_version():
    try:
        out = subprocess.run(["klayout", "-v"], capture_output=True, text=True, timeout=30)
        return (out.stdout + out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else "klayout"
    except Exception:
        return "klayout"


def _magic_bin():
    for c in ("magic", "/usr/bin/magic", "/usr/local/bin/magic"):
        if shutil.which(c) or os.path.exists(c):
            return shutil.which(c) or c
    return None


def _magic_version():
    b = _magic_bin()
    if not b:
        return "magic"
    try:
        out = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=30)
        txt = (out.stdout + out.stderr).strip()
        return "magic " + txt.splitlines()[0] if txt else "magic"
    except Exception:
        return "magic"


def _parse_lyrdb(path):
    """Parse a KLayout report database (.lyrdb XML): total items + per-category counts."""
    per_rule = {}
    total = 0
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        # items live under <items><item><category>rule</category>...</item></items>
        for item in root.iter("item"):
            cat = item.findtext("category") or "unknown"
            cat = cat.strip().strip("'").strip('"') or "unknown"
            per_rule[cat] = per_rule.get(cat, 0) + 1
            total += 1
    except Exception as e:
        return None, {"parse_error": str(e)}
    return total, per_rule


def _run_klayout_drc(params, layout, top, settings=None):
    """Run one KLayout batch DRC. Returns a per-engine dict:
    {engine, count, per_rule, report, ok, error, deck}.

    `settings` is the resolved effective KLayout setting map (caller params already
    merged over PDK tool_policy defaults by the orchestrator)."""
    settings = settings or {}
    binding = params.get("pdk_binding") or {}
    deck = (params.get("drc_deck") or params.get("drc_rules")
            or binding.get("drc_rules") or binding.get("drc_deck"))
    if not deck:
        return {"engine": "klayout", "ok": False, "count": None, "per_rule": {},
                "error": "missing KLayout drc_deck (PDK binding drc_rules)"}
    if not os.path.exists(str(deck)):
        return {"engine": "klayout", "ok": False, "count": None, "per_rule": {},
                "error": f"KLayout deck not found: {deck}"}
    report_db = os.path.join(_OUTPUT_DIR, "drc_klayout.lyrdb")
    # Pass EVERY known layout/report/top-cell variable convention (see
    # _LAYOUT_VARS); caller/policy deck_vars override per key. The deck text is
    # then scanned so a `$var` it needs that is still unset fails HERE, by name,
    # instead of as KLayout's opaque "No layout loaded".
    rd = _klayout_rd_vars(layout, report_db, top, settings.get("threads"),
                          settings.get("deck_vars"))
    preflight_error, deck_info = _klayout_preflight(deck, layout, rd)
    if preflight_error:
        return {"engine": "klayout", "ok": False, "count": None, "per_rule": {},
                "error": preflight_error, "deck": os.path.basename(str(deck)),
                "deck_variables": deck_info}
    cmd = ["klayout", "-b", "-r", str(deck)]
    for k, v in rd.items():
        cmd += ["-rd", f"{k}={v}"]
    log = os.path.join(_OUTPUT_DIR, "drc_klayout.log")
    if os.path.exists(report_db):
        os.remove(report_db)  # a stale DB must never be read as this run's result
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    out = proc.stdout + "\n" + proc.stderr
    open(log, "w").write(out)
    if proc.returncode != 0 and not os.path.exists(report_db):
        return {"engine": "klayout", "ok": False, "count": None, "per_rule": {},
                "error": "KLayout DRC failed; see drc_klayout.log:\n" + out[-1200:],
                "report": "drc_klayout.log", "deck": os.path.basename(str(deck))}
    if not os.path.exists(report_db):
        # No report database means the deck never wrote its findings (e.g. it
        # reads a report variable this run did not set). A zero parsed from the
        # log would be fabricated, so this is a failed run, not a clean one.
        return {"engine": "klayout", "ok": False, "count": None, "per_rule": {},
                "error": ("KLayout exited %d but wrote no report database %s; "
                          "the DRC result is unmeasured" % (proc.returncode,
                                                            os.path.basename(report_db))),
                "report": "drc_klayout.log", "deck": os.path.basename(str(deck)),
                "deck_variables": deck_info}
    total, per_rule = _parse_lyrdb(report_db)
    if total is None:
        return {"engine": "klayout", "ok": False, "count": None, "per_rule": {},
                "error": "KLayout report database unparseable: %s" % per_rule,
                "report": "drc_klayout.log", "deck": os.path.basename(str(deck))}
    return {"engine": "klayout", "ok": True, "count": total,
            "per_rule": per_rule if isinstance(per_rule, dict) else {},
            "report": "drc_klayout.log", "report_db": "drc_klayout.lyrdb",
            "deck": os.path.basename(str(deck)), "version": _klayout_version(),
            "deck_variables": deck_info,
            "rd_variables": sorted(rd)}


def _run_magic_drc(params, layout, top, settings=None):
    """Run one Magic batch DRC (rules live in the tech bound via the .magicrc /
    techfile). Returns the same per-engine dict shape as the KLayout runner.

    `settings` is the resolved effective Magic setting map."""
    settings = settings or {}
    b = _magic_bin()
    if not b:
        return {"engine": "magic", "ok": False, "count": None, "per_rule": {},
                "error": "magic not found on PATH"}
    magicrc = settings.get("magicrc")
    tech = settings.get("magic_tech")
    # A GDS is streamed in and the top cell loaded; DRC rules come from the tech.
    euclidean = "on" if settings.get("drc_euclidean", True) else "off"
    top_expr = f'set top "{top}"' if top else "set top {}"
    script = (
        f"drc euclidean {euclidean}\n"
        # Put the internal grid on the 0.005um lambda pitch BEFORE reading the GDS,
        # exactly as the canonical sky130A.magicrc does. Without this, `gds read` of a
        # sky130 signoff GDS (5nm features) under Magic's default 10nm lambda trips
        # "Input off lambda grid by 1/2; grid redefined", which yields a SPURIOUS
        # drc count with an EMPTY why-block (phantom violations that no rule fired).
        # The guard is idempotent: it is a no-op when a bound magicrc already scaled.
        "catch {set _sf [tech lambda]; if {[lindex $_sf 1] < 2} {scalegrid 1 2}}\n"
        "snap lambda\n"
        f'gds read "{layout}"\n'
        f"{top_expr}\n"
        'if {$top eq ""} { set top [lindex [cellname list top] 0] }\n'
        "load $top\n"
        # FLAT full-chip signoff DRC. Magic's HIERARCHICAL drc check reports
        # phantom violations at standard-cell abutment/overlap boundaries (paint
        # in one cell interacting with a neighbor's halo) that DO NOT exist in the
        # true as-fabricated layout: they show up in `drc list count total` but
        # carry NO rule text (empty `drc listall why`). Flattening to a single cell
        # first yields the ground-truth geometry, so the count and the why-list
        # agree and inter-cell false-positives vanish. This is also the canonical
        # signoff methodology (flat full-chip DRC). Fall back to hierarchical if
        # flatten fails so the engine still produces a count.
        'if {[catch {flatten -nolabels ${top}__drcflat; load ${top}__drcflat}]} '
        '{ load $top }\n'
        # Under -dnull there is no box after `load`, so a bare `drc check` aborts
        # with "Box tool must be present", checks NOTHING, and the count reads 0
        # on any layout (measured: a 50nm met1 sliver reported clean). Put the
        # box on the whole top cell so the check and `drc listall why` cover it.
        "select top cell\n"
        'puts "MAGIC_DRC_BOX [box values]"\n'
        "drc check\n"
        "drc catchup\n"
        'if {[catch {set c [drc list count total]} c]} {set c ""}\n'
        'if {$c eq ""} {set c 0}\n'
        'puts "MAGIC_DRC_COUNT $c"\n'
        'if {[catch {set why [drc listall why]} why]} {set why ""}\n'
        'puts "MAGIC_DRC_WHY_BEGIN"\n'
        'foreach {rule boxes} $why { puts "MAGIC_DRC_RULE [llength $boxes]\\t$rule" }\n'
        'puts "MAGIC_DRC_WHY_END"\n'
        "quit -noprompt\n")
    scr = os.path.join(_WORK_DIR, "magic_drc.tcl")
    with open(scr, "w") as f:
        f.write(script)
    cmd = [b, "-dnull", "-noconsole"]
    if magicrc and os.path.exists(str(magicrc)):
        cmd += ["-rcfile", str(magicrc)]
    elif tech and os.path.exists(str(tech)):
        cmd += ["-T", str(tech)]
    cmd += [scr]
    log = os.path.join(_OUTPUT_DIR, "drc_magic.log")
    _save_run_command(cmd)
    # Without PDK_ROOT the vendor magicrc resolves its techfile against the
    # ORIGINAL BUILD MACHINE's path, loads no technology, and Magic then reads
    # no geometry yet still exits 0 -- reporting MAGIC_DRC_COUNT 0 on a design
    # it never inspected. A false clean on a mandatory tapeout gate.
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR,
                          env=_magic_env(techfile=tech, rcfile=magicrc,
                                         params=params))
    out = proc.stdout + "\n" + proc.stderr
    open(log, "w").write(out)
    m = re.search(r"MAGIC_DRC_COUNT\s+(\d+)", out)
    if m is None:
        return {"engine": "magic", "ok": False, "count": None, "per_rule": {},
                "error": "Magic produced no DRC count; see drc_magic.log:\n" + out[-1200:],
                "report": "drc_magic.log"}
    count = int(m.group(1))
    # Same evidence run: Magic without a GDS-capable tech prints "Don't know how
    # to read GDS-II" / "Cell X couldn't be read" and then DRCs an EMPTY cell,
    # reporting MAGIC_DRC_COUNT 0. That zero is unmeasured, never clean.
    unread = re.search(r"Don't know how to read GDS|couldn't be read|"
                       r"Nothing in \"cifinput\" section", out)
    if unread:
        return {"engine": "magic", "ok": False, "count": None, "per_rule": {},
                "error": ("Magic did not load the layout (%r); its DRC count of %d "
                          "covers an empty cell. Bind a magicrc/magic_tech with a "
                          "cifinput section or run engine=klayout only; see "
                          "drc_magic.log" % (unread.group(0), count)),
                "report": "drc_magic.log"}
    box = re.search(r"MAGIC_DRC_BOX[ \t]*([^\n]*)", out)
    if "Box tool must be present" in out or not box or len(box.group(1).split()) != 4:
        return {"engine": "magic", "ok": False, "count": None, "per_rule": {},
                "error": ("Magic had no box over the top cell, so `drc check` "
                          "checked nothing; its DRC count of %d is unmeasured, "
                          "not clean; see drc_magic.log" % count),
                "report": "drc_magic.log"}
    per_rule = {}
    wm = re.search(r"MAGIC_DRC_WHY_BEGIN\n(.*?)MAGIC_DRC_WHY_END", out, re.S)
    if wm:
        for rm in re.finditer(r"^MAGIC_DRC_RULE (\d+)\t(.+)$", wm.group(1), re.M):
            rule = rm.group(2).strip()
            per_rule[rule] = per_rule.get(rule, 0) + int(rm.group(1))
    if count == 0 and per_rule:
        return {"engine": "magic", "ok": False, "count": None, "per_rule": per_rule,
                "error": ("Magic reported a DRC count of 0 but `drc listall why` "
                          "lists %d violation box(es); the engine result is "
                          "internally inconsistent and cannot be called clean; "
                          "see drc_magic.log" % sum(per_rule.values())),
                "report": "drc_magic.log"}
    return {"engine": "magic", "ok": True, "count": count, "per_rule": per_rule,
            "box": box.group(1).split(),
            "report": "drc_magic.log", "version": _magic_version()}


def _resolve_drc_config(params, binding):
    """Resolve the DRC engine set and per-engine settings by PDK-recommendation
    precedence, tracking the source of every decision.

    Precedence (highest first):
      1. explicit caller param           (source: caller / caller_override)
      2. binding.tool_policy.drc         (source: pdk_policy)
      3. tool built-in default           (source: tool_default)

    Returns (engines_list, settings_by_engine, decision_log) where decision_log
    records each choice + its source so a reviewer / the signoff agent can see
    when a caller overrode a PDK recommendation."""
    policy = ((binding.get("tool_policy") or {}).get("drc") or {})
    pol_engines = policy.get("engines")
    pol_settings = policy.get("settings") or {}
    log = {}

    # --- engine set ---------------------------------------------------------
    caller_engine = str(params.get("engine") or "").lower().strip() or None
    magic_ok = _magic_bin() is not None
    magic_bound = bool(params.get("magicrc") or params.get("magic_rcfile")
                       or params.get("magic_tech")
                       or (pol_settings.get("magic") or {}).get("magicrc")
                       or (pol_settings.get("magic") or {}).get("magic_tech")
                       or binding.get("magicrc") or binding.get("magic_tech"))
    if caller_engine:
        engines = ["klayout", "magic"] if caller_engine == "both" else [caller_engine]
        if pol_engines and sorted(engines) != sorted(pol_engines):
            log["engine_source"] = "caller_override"
            log["policy_recommended_engines"] = pol_engines
        else:
            log["engine_source"] = "caller"
    elif pol_engines:
        engines = list(pol_engines)
        log["engine_source"] = "pdk_policy"
    else:
        engines = ["klayout", "magic"] if (magic_ok and magic_bound) else ["klayout"]
        log["engine_source"] = "tool_default"
    log["engines"] = engines

    # --- per-engine settings (caller param wins per key, else policy) --------
    def _pick(caller_val, pol_val):
        return (caller_val, "caller") if caller_val is not None else (
            (pol_val, "pdk_policy") if pol_val is not None else (None, "unset"))

    settings = {"klayout": {}, "magic": {}}
    src = {"klayout": {}, "magic": {}}

    kpol = pol_settings.get("klayout") or {}
    thr, thr_src = _pick(params.get("threads"), kpol.get("threads"))
    if thr is not None:
        settings["klayout"]["threads"] = thr
    src["klayout"]["threads"] = thr_src
    # deck_vars merge: policy defaults, caller overrides per key.
    dv = dict(kpol.get("deck_vars") or {})
    dv.update(params.get("deck_vars") or {})
    if dv:
        settings["klayout"]["deck_vars"] = dv
    src["klayout"]["deck_vars"] = ("merged" if (kpol.get("deck_vars") and params.get("deck_vars"))
                                   else "caller" if params.get("deck_vars")
                                   else "pdk_policy" if kpol.get("deck_vars") else "unset")

    mpol = pol_settings.get("magic") or {}
    mrc, mrc_src = _pick(params.get("magicrc") or params.get("magic_rcfile"),
                         mpol.get("magicrc") or binding.get("magicrc"))
    settings["magic"]["magicrc"] = mrc
    src["magic"]["magicrc"] = mrc_src
    mt, mt_src = _pick(params.get("magic_tech"),
                       mpol.get("magic_tech") or binding.get("magic_tech"))
    settings["magic"]["magic_tech"] = mt
    src["magic"]["magic_tech"] = mt_src
    eucl, eucl_src = _pick(params.get("drc_euclidean"), mpol.get("drc_euclidean"))
    settings["magic"]["drc_euclidean"] = True if eucl is None else eucl
    src["magic"]["drc_euclidean"] = eucl_src

    log["settings_source"] = src
    log["mode"] = policy.get("mode", "all_must_pass")
    return engines, settings, log


def _drc_check(params):
    binding = params.get("pdk_binding") or {}
    layout = params.get("layout") or params.get("gds") or params.get("def_file")
    top = params.get("top")
    if top is not None and not _is_ident(top):
        return _cde(objective="DRC", status="failed", pdk_binding=binding or "none",
                    error=f"invalid 'top' identifier: {top!r}", validation={"verdict": "fail"})
    # Incompatible inputs: Magic takes a single technology source. A caller that
    # supplies BOTH a magicrc (which binds its own tech) and a magic_tech is
    # contradictory -- fail closed rather than silently ignoring one.
    if (params.get("magicrc") or params.get("magic_rcfile")) and params.get("magic_tech"):
        return _cde(objective="DRC", status="failed", pdk_binding=binding or "none",
                    error="provide only one Magic technology source: magicrc OR "
                          "magic_tech, not both", validation={"verdict": "fail"})
    # PDK-recommendation-aware selection: the recommended engine SET and per-engine
    # SETTINGS come from binding.tool_policy.drc; explicit caller params override,
    # tool defaults are the last resort. Every decision's source is recorded.
    engines, eff_settings, policy_log = _resolve_drc_config(params, binding)
    for e in engines:
        if e not in ("klayout", "magic"):
            return _cde(objective="DRC", status="failed", pdk_binding=binding or "none",
                        error=f"unknown engine '{e}'; use klayout, magic, or both",
                        validation={"verdict": "fail"})
    if not layout:
        return _cde(objective="DRC", status="failed", pdk_binding=binding or "none",
                    error="missing required field 'layout'", validation={"verdict": "fail"})
    if not os.path.exists(str(layout)):
        return _cde(objective="DRC", status="failed", pdk_binding=binding or "none",
                    error=f"layout not found: {layout}", validation={"verdict": "fail"})

    runs = []
    for e in engines:
        if e == "klayout":
            if not shutil.which("klayout"):
                return _cde(objective="DRC", status="failed", pdk_binding=binding or "none",
                            error="klayout not found on PATH", validation={"verdict": "fail"})
            runs.append(_run_klayout_drc(params, layout, top, eff_settings["klayout"]))
        else:
            runs.append(_run_magic_drc(params, layout, top, eff_settings["magic"]))

    # A failed engine invocation (tool error) fails the whole check -- we must not
    # sign off DRC with an engine that did not actually run.
    failed = [r for r in runs if not r.get("ok")]
    if failed:
        return _cde(
            objective=f"DRC of {top or os.path.basename(str(layout))}",
            status="failed", pdk_binding=binding or "none",
            error="; ".join(f"{r['engine']}: {r.get('error')}" for r in failed),
            signoff={"engines": [r["engine"] for r in runs]},
            validation={"verdict": "fail"},
            provenance={"klayout": _klayout_version(), "magic": _magic_version()})

    # Merge per-engine results. Per-rule keys are namespaced by engine so a rule
    # of the same name in both decks is not silently collapsed.
    per_rule = {}
    per_engine = {}
    total = 0
    for r in runs:
        per_engine[r["engine"]] = {"violations": r["count"],
                                   "per_rule": r["per_rule"],
                                   "report": r.get("report")}
        if r.get("rd_variables"):
            per_engine[r["engine"]]["rd_variables"] = r["rd_variables"]
            per_engine[r["engine"]]["deck_variables"] = r.get("deck_variables")
        total += int(r["count"] or 0)
        for rule, c in (r["per_rule"] or {}).items():
            per_rule[f"{r['engine']}:{rule}"] = c

    # Waiver adjudication: a waiver must name the rule + owner + justification.
    # Waivers may target an engine-namespaced rule (`magic:<rule>`) or a bare rule
    # name (applies to that rule in either engine).
    waivers = params.get("waivers") or []
    waived_rules = {}
    bad_waivers = []
    for w in waivers:
        if not (w.get("rule") and w.get("owner") and w.get("justification")):
            bad_waivers.append(w)
            continue
        waived_rules[w["rule"]] = w
    if bad_waivers:
        return _cde(objective="DRC", status="failed", pdk_binding=binding or "none",
                    error="every waiver requires rule + owner + justification",
                    signoff={"invalid_waivers": bad_waivers},
                    validation={"verdict": "fail"})

    def _is_waived(namespaced_rule):
        if namespaced_rule in waived_rules:
            return True
        bare = namespaced_rule.split(":", 1)[-1]
        return bare in waived_rules

    if per_rule:
        unwaived = sum(c for rule, c in per_rule.items() if not _is_waived(rule))
    else:
        unwaived = total
    waived_count = total - unwaived
    clean = unwaived == 0
    verdict = "pass" if clean else "fail"
    engine_label = "+".join(r["engine"] for r in runs)
    prov = {"runtime_engines": engine_label, "report": [r.get("report") for r in runs],
            "engine_source": policy_log.get("engine_source"),
            "settings_source": policy_log.get("settings_source"),
            "policy_mode": policy_log.get("mode")}
    if policy_log.get("engine_source") == "caller_override":
        prov["policy_override"] = {
            "note": "caller engine set overrides the PDK tool_policy recommendation",
            "policy_recommended_engines": policy_log.get("policy_recommended_engines"),
            "engines_used": policy_log.get("engines")}
    if any(r["engine"] == "klayout" for r in runs):
        prov["klayout"] = _klayout_version()
    if any(r["engine"] == "magic" for r in runs):
        prov["magic"] = _magic_version()
    # A caller override of a PDK recommendation is not a failure, but it must be
    # surfaced as a caveat so the signoff/design-review agent can judge it.
    _override = policy_log.get("engine_source") == "caller_override"
    if clean and _override:
        verdict = "pass_with_caveats"
    return _cde(
        objective=f"design-rule check ({engine_label}) of "
                  f"{top or os.path.basename(str(layout))}",
        status="completed",
        pdk_binding=binding or "none",
        results={"drc_violations": {"value": total, "unit": "count"},
                 "unwaived_violations": {"value": unwaived, "unit": "count"}},
        qor={"drc_violations": total, "unwaived_violations": unwaived,
             "waived_violations": waived_count, "engines": engine_label,
             "per_engine": {e: v["violations"] for e, v in per_engine.items()}},
        signoff={"engines": engine_label, "per_engine": per_engine,
                 "per_rule": per_rule,
                 "waived_rules": sorted(waived_rules.keys()),
                 "clean": clean,
                 "engine_selection": {
                     "source": policy_log.get("engine_source"),
                     "engines": policy_log.get("engines"),
                     "pdk_recommended": policy_log.get("policy_recommended_engines"),
                     "mode": policy_log.get("mode")},
                 "pdk_policy_override": _override,
                 "complementary_rule_note":
                 "sky130 signoff requires BOTH Magic and KLayout DRC clean; their "
                 "decks catch complementary rules" if len(runs) > 1 else
                 "single-engine DRC; sky130 signoff also needs the complementary engine"},
        inputs_ref={"layout": layout,
                    "klayout_deck": per_engine.get("klayout", {}).get("report"
                    ) and (params.get("drc_deck") or (binding or {}).get("drc_rules"))},
        assumptions=["signoff requires zero un-waived violations across every engine "
                     "run; sky130 clean DRC needs both Magic and KLayout",
                     "engine set + settings resolved from the PDK tool_policy unless "
                     "the caller explicitly overrode them"],
        validation={"verdict": verdict,
                    "note": (
                        (f"DRC clean ({engine_label})"
                         + ("; caller overrode the PDK-recommended engine set"
                            if _override else "; no un-waived violations"))
                        if clean else
                        f"{unwaived} un-waived DRC violation(s) across {engine_label}")},
        provenance=prov,
    )


def dispatch(params):
    s = params.get("scenario")
    if s == "drc_check":
        return _drc_check(params)
    return _cde(objective="DRC", status="failed",
                error=f"unknown scenario '{s}'; supported: drc_check",
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
