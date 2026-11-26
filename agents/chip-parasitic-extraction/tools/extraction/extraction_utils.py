#!/usr/bin/env python3
"""extraction_utils.py -- real OpenROAD OpenRCX parasitic extraction.

Reads node LEF/Liberty + a routed DEF + OpenRCX RC rules, runs define_process_corner
+ extract_parasitics, and writes SPEF. RC rules/corners come from the PDK binding.
Node-aware. Results conform to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "extraction"
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


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def _cde(objective, status, results=None, signoff=None, pdk_binding=None,
         assumptions=None, validation=None, provenance=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "OpenROAD OpenRCX", "version": "openroad"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": {},
        "signoff_evidence": signoff or {}, "margin": {"method": "rc_extraction"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _check_lef_collisions(lef_paths):
    """Detect FATAL LEF MACRO double-definitions across the given LEF files.

    OpenROAD's read_lef does not de-duplicate cell MACRO definitions: if the same
    cell MACRO name is defined by more than one LEF, the collision can drop
    masters downstream (e.g. 'clkinv_1 not found'). This most often happens when a
    merged/complete LEF (which already contains the standard cells) is passed
    together with a separate tech + cell LEF. Duplicate SITE (and VIARULE)
    definitions are NOT fatal -- OpenROAD keeps the first identical definition and
    only logs ODB-0394 -- and many PDK tech+cell LEF pairs legitimately define the
    same SITEs in both files, so they are ignored here. Return a human-readable
    error naming the colliding MACROs, or None if the LEF set is clean."""
    import re as _re
    lefs = [str(p) for p in lef_paths if p]
    seen = {}          # object name -> first realpath that defined it
    collide = {}       # object name -> set of realpaths
    obj_re = _re.compile(r"^\s*(MACRO|SITE)\s+(\S+)", _re.MULTILINE)
    reals = []
    for p in lefs:
        rp = os.path.realpath(p)
        if rp in reals:
            return "duplicate LEF passed more than once: " + p
        reals.append(rp)
        try:
            with open(p, "r", errors="ignore") as _f:
                txt = _f.read()
        except Exception:
            continue
        for kind, name in obj_re.findall(txt):
            # Only a duplicate MACRO is fatal: OpenROAD can drop a colliding cell
            # master downstream ('clkinv_1 not found'). A duplicate SITE (or
            # VIARULE) is benign -- OpenROAD keeps the first identical definition
            # and merely logs ODB-0394. Many PDK tech+cell LEF pairs (e.g. sky130A
            # unithd/unithddbl) legitimately define the SITEs in BOTH files, so
            # treating a SITE overlap as fatal is a false positive that blocks
            # every physical stage. Screen MACRO collisions only.
            if kind != "MACRO":
                continue
            if name in seen and seen[name] != rp:
                collide.setdefault(name, {seen[name]})
                collide[name].add(rp)
            else:
                seen[name] = rp
    if collide:
        names = sorted(collide)
        shown = ", ".join(names[:5]) + ("" if len(names) <= 5 else " (+%d more)" % (len(names) - 5))
        return ("LEF double-define: object(s) " + shown + " are defined in more than "
                "one of the supplied LEFs; pass the merged LEF ONCE as tech_lef with "
                "NO separate cell_lef so cell masters are not dropped")
    return None


def _rc_model_corner_count(rc_rules):
    """How many extraction corners the OpenRCX model file actually declares.

    The RC rules file is the AUTHORITY on extraction-corner count -- asking
    OpenRCX for more corners than it models does not produce a stricter run, it
    ABORTS (measured: sky130hd rcx_patterns.rules has one `DensityModel 0` and
    `-corner_cnt 3` dies with "free(): invalid pointer" / SIGABRT).

    Returns None when the count cannot be determined, so the caller can fall
    back conservatively and SAY SO rather than guessing a number.
    """
    try:
        txt = open(rc_rules, encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    # `DensityRate <n> ...` states the model count directly when present.
    m = re.search(r"^\s*DensityRate\s+(\d+)", txt, re.M)
    if m:
        try:
            n = int(m.group(1))
            if n >= 1:
                return n
        except ValueError:
            pass
    # Otherwise count the DensityModel blocks themselves.
    n = len(re.findall(r"^\s*DensityModel\s+\d+", txt, re.M))
    return n or None


def _normal_path(path):
    return os.path.normpath(str(path)).replace("\\", "/")


def _resolve_bound_file(bound_path, explicit_path=None):
    """Resolve a binding-relative path without changing the binding."""
    candidates = [str(bound_path)]
    if explicit_path:
        explicit = str(explicit_path)
        if (_normal_path(explicit).endswith("/" + _normal_path(bound_path))
                or os.path.basename(explicit) == os.path.basename(str(bound_path))):
            candidates.append(explicit)
    if not os.path.isabs(str(bound_path)):
        candidates.append(os.path.join("/workspace", str(bound_path)))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return str(bound_path)


def _verify_bound_reference(binding, resolved_path, bound_path):
    """Verify a bound file against the binding's immutable reference record."""
    references = binding.get("references") or {}
    bound_norm = _normal_path(bound_path)
    matches = []
    for name, reference in references.items():
        if not isinstance(reference, dict) or not reference.get("path"):
            continue
        ref_norm = _normal_path(reference["path"])
        if ref_norm == bound_norm or bound_norm.endswith("/" + ref_norm):
            matches.append((name, reference))
    if not matches:
        raise ValueError(
            f"no hash-pinned binding reference found for RC rule path: {bound_path}")

    measured = _hash_input_file(resolved_path)
    if not measured:
        raise ValueError(f"could not hash bound RC rule file: {resolved_path}")
    accepted = []
    for name, reference in matches:
        if reference.get("sha256") != measured["sha256"]:
            continue
        expected_bytes = reference.get("bytes")
        if expected_bytes is not None and int(expected_bytes) != measured["bytes"]:
            continue
        accepted.append(name)
    if not accepted:
        expected = sorted({
            str(reference.get("sha256")) for _, reference in matches
            if reference.get("sha256")
        })
        raise ValueError(
            "bound RC rule hash mismatch for %s: measured %s, expected %s"
            % (bound_path, measured["sha256"], ", ".join(expected) or "missing"))
    return {
        "path": str(bound_path),
        "resolved_path": str(resolved_path),
        "sha256": measured["sha256"],
        "bytes": measured["bytes"],
        "reference_keys": sorted(accepted),
    }


def _spef_content_digest(path):
    """SHA-256 of a SPEF's CONTENT, ignoring its `*DATE` header line.

    Two SPEFs produced from the same RC model differ only in that timestamp. A
    plain file hash therefore reports them as different files and hides that
    they carry one measurement; excluding the line is what makes "these three
    corners share one RC model" a fact the envelope can state instead of
    something a reader has to diff for.
    """
    try:
        import hashlib
        digest = hashlib.sha256()
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lstrip().startswith("*DATE"):
                    continue
                digest.update(line.encode("utf-8", "replace"))
        return digest.hexdigest()
    except Exception:
        return None


def _bound_corner_plan(binding, explicit_rc_rules=None):
    """Resolve every all-corners binding entry and verify its pinned bytes."""
    corners = [str(c) for c in (binding.get("corners") or []) if c]
    rules_by_corner = binding.get("rc_rules_by_corner")
    if not corners:
        raise ValueError("all_corners mode requires binding.corners")
    if not isinstance(rules_by_corner, dict):
        raise ValueError("all_corners mode requires binding.rc_rules_by_corner")

    plan = []
    for corner in corners:
        bound_path = rules_by_corner.get(corner)
        if not bound_path:
            raise ValueError(
                f"binding.rc_rules_by_corner is missing declared corner '{corner}'")
        resolved = _resolve_bound_file(bound_path, explicit_rc_rules)
        if not os.path.isfile(resolved):
            raise ValueError(
                f"bound RC rule file for corner '{corner}' not found: {bound_path}")
        verified = _verify_bound_reference(binding, resolved, bound_path)
        plan.append({
            "corner": corner,
            "rc_rules": resolved,
            "bound_rc_rules": str(bound_path),
            "verification": verified,
        })
    return plan


def _extract(params):
    if not shutil.which("openroad"):
        return _cde(objective="extraction", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    top, def_file = params.get("top"), params.get("def_file")
    binding = params.get("pdk_binding") or {}
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    libs = _as_list(params.get("liberty") or binding.get("liberty"))
    rc_rules = params.get("rc_rules") or binding.get("rc_tech") or binding.get("rc_rules")
    corner = params.get("corner") or (binding.get("corners") or ["typical"])[0]
    for n, v in (("top", top), ("def_file", def_file), ("tech_lef", tech_lef), ("rc_rules", rc_rules)):
        if not v:
            return _cde(objective="extraction", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}' (check pdk_binding)",
                        validation={"verdict": "fail"})
    for p in [def_file, tech_lef, rc_rules] + cell_lefs + libs:
        if not os.path.exists(str(p)):
            return _cde(objective="extraction", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    _lef_err = _check_lef_collisions([tech_lef] + cell_lefs)
    if _lef_err:
        return _cde(objective="extraction", status="failed", pdk_binding=binding or "none",
                    error=_lef_err, validation={"verdict": "fail"})
    out_spef = os.path.join(_OUTPUT_DIR, f"{top}.spef")
    lef_reads = "\n".join([f"read_lef {tech_lef}"] + [f"read_lef {c}" for c in cell_lefs])
    lib_reads = "\n".join(f"read_liberty {l}" for l in libs)
    # OpenRCX accuracy / modeling levers.
    #   coupling_threshold : min coupling cap (fF) kept as coupled vs lumped.
    #   context_depth      : # of neighbor tracks considered for coupling.
    #   cc_model           : coupling-capacitance model order.
    _ext_opts = ""
    _ct = params.get("coupling_threshold")
    if _ct is not None:
        _ext_opts += f" -coupling_threshold {_ct}"
    _cd = params.get("context_depth")
    if _cd is not None:
        _ext_opts += f" -context_depth {int(_cd)}"
    _ccm = params.get("cc_model")
    if _ccm is not None:
        _ext_opts += f" -cc_model {int(_ccm)}"
    _declared_corners = [str(c) for c in (binding.get("corners") or []) if c]
    _all_corners = (
        ((binding.get("tool_policy") or {}).get("extraction") or {}).get("mode")
        == "all_corners")
    try:
        if _all_corners:
            extraction_plan = _bound_corner_plan(binding, rc_rules)
        else:
            extraction_plan = [{
                "corner": str(corner),
                "rc_rules": str(rc_rules),
                "bound_rc_rules": str(rc_rules),
                "verification": _hash_input_file(rc_rules),
            }]
    except ValueError as e:
        return _cde(
            objective=f"extraction of {top}", status="failed",
            pdk_binding=binding or "none", error=str(e),
            validation={"verdict": "fail", "note": str(e)})

    multi_bound = len(extraction_plan) > 1
    invocation_records = []
    corner_spefs = []
    nets_by_corner = {}
    aggregate_logs = []
    t0 = time.time()
    for item in extraction_plan:
        item_corner = item["corner"]
        item_rules = item["rc_rules"]
        item_spef = (
            os.path.join(_OUTPUT_DIR, f"{top}.{item_corner}.spef")
            if multi_bound else out_spef)
        script = f"""{lib_reads}
{lef_reads}
read_def {def_file}
define_process_corner -ext_model_index 0 X
extract_parasitics -ext_model_file {item_rules}{_ext_opts}
write_spef {item_spef}
exit
"""
        script_name = (
            f"rcx.{item_corner}.tcl" if multi_bound else "rcx.tcl")
        log_name = (
            f"rcx.{item_corner}.log" if multi_bound else "rcx.log")
        command_name = (
            f"run_command.{item_corner}.txt" if multi_bound
            else "run_command.txt")
        script_path = os.path.join(_OUTPUT_DIR, script_name)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
        command = ["openroad", "-exit", script_path]
        _save_run_command(command, command_name)
        proc = subprocess.run(
            command, capture_output=True, text=True, cwd=_WORK_DIR)
        output = proc.stdout + "\n" + proc.stderr
        with open(os.path.join(_OUTPUT_DIR, log_name), "w", encoding="utf-8") as f:
            f.write(output)
        aggregate_logs.append(f"===== {item_corner} =====\n{output}")
        if proc.returncode != 0 or not os.path.exists(item_spef) \
                or os.path.getsize(item_spef) == 0:
            return _cde(
                objective=f"extraction of {top}", status="failed",
                pdk_binding=binding or "none",
                error=(
                    f"OpenRCX failed for bound corner {item_corner}; "
                    f"see {log_name}:\n{output[-1500:]}"
                ),
                validation={"verdict": "fail"},
                provenance={"openroad": "openroad", "log": log_name})
        spef_text = open(item_spef, encoding="utf-8", errors="replace").read()
        item_nets = len(re.findall(r"^\*D_NET", spef_text, re.M))
        nets_by_corner[item_corner] = item_nets
        corner_spefs.append(os.path.basename(item_spef))
        invocation_records.append({
            "corner": item_corner,
            "spef": os.path.basename(item_spef),
            "script": script_name,
            "log": log_name,
            "rc_rules": item["bound_rc_rules"],
            "rc_rules_verification": item["verification"],
            "returncode": proc.returncode,
        })
    elapsed = time.time() - t0
    if multi_bound:
        with open(os.path.join(_OUTPUT_DIR, "rcx.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(aggregate_logs))

    corners_extracted = len(corner_spefs)
    _corners_required = (
        len(_declared_corners) if _all_corners else len(extraction_plan))
    unextracted_corners = max(0, _corners_required - corners_extracted)
    _complete = (unextracted_corners == 0)
    _scope_note = (
        "corner coverage complete: %d of %d binding corner(s) extracted"
        % (corners_extracted, _corners_required)
        if _complete else
        "PARTIAL EXTRACTION: %d of %d binding corner(s) extracted; %d missing. "
        "A partial SPEF set CANNOT support multi-corner STA or power signoff."
        % (corners_extracted, _corners_required, unextracted_corners))

    # --- RC-MODEL CLAMP DISCLOSURE, DERIVED FROM THE RUN --------------------
    # `corner_cnt_clamped_to_rc_model` and `rc_model_corners` used to be the
    # hard-coded literals `False` and `None`. That denies exactly the
    # limitation the fields exist to surface: sky130A ships ONE OpenRCX rule
    # file, so three declared PVT corners collapse onto one RC model and the
    # three SPEFs come out byte-identical apart from their `*DATE` header.
    # Downstream STA then reads three SPEFs and concludes multi-corner STA
    # covered RC spread -- it did not; only the Liberty PVT view varied.
    # Derived from the plan's OWN verified digests, so it cannot drift from
    # what was actually loaded.
    _models_to_corners = {}
    for item in extraction_plan:
        verification = item.get("verification") or {}
        key = verification.get("sha256") or str(item["rc_rules"])
        _models_to_corners.setdefault(key, []).append(item["corner"])
    _rc_model_corners = len(_models_to_corners)
    _clamped = _rc_model_corners < len(extraction_plan)
    _shared_model_groups = {
        digest: sorted(names)
        for digest, names in _models_to_corners.items() if len(names) > 1
    }
    # A stage that emits N per-corner artifacts must hash them and, when they
    # are identical, say why -- otherwise the reader has to diff them to learn
    # that N files carry one measurement. The `*DATE` line is excluded because
    # a timestamp difference is not an RC difference.
    _spef_groups = {}
    for item in invocation_records:
        digest = _spef_content_digest(
            os.path.join(_OUTPUT_DIR, item["spef"]))
        item["spef_content_sha256"] = digest
        if digest:
            _spef_groups.setdefault(digest, []).append(item["corner"])
    _identical_spef_groups = {
        digest: sorted(names)
        for digest, names in _spef_groups.items() if len(names) > 1
    }
    _rc_boundary = None
    _next_stage_hint = None
    if _clamped:
        _rc_boundary = (
            "%d declared corner(s) resolve to %d distinct OpenRCX RC model "
            "file(s); corners sharing a model load the SAME bytes. No RC "
            "scaling, interpolation or relabeling is invented -- this is the "
            "PDK's capability boundary, reported rather than papered over."
            % (len(extraction_plan), _rc_model_corners))
        _next_stage_hint = (
            "STA/power: RC parasitics are COMMON-MODE across %s. Only the "
            "Liberty PVT view varies across these corners, so a multi-corner "
            "timing claim built on these SPEFs does NOT cover RC spread and "
            "must carry that caveat."
            % ", ".join(sorted(
                name for names in _shared_model_groups.values()
                for name in names)))
    _rc_resolution_note = (
        "all_corners mode resolves every binding corner through "
        "binding.rc_rules_by_corner and hash-verifies the bound rule bytes"
        if _all_corners else
        "single-corner mode uses the explicitly supplied rc_rules file and "
        "hash-verifies it; binding.rc_rules_by_corner is not consulted")
    _assumptions = [
        _rc_resolution_note,
        "each binding corner is a separate real OpenRCX invocation; SPEFs are "
        "neither copied nor relabeled and no RC scaling is invented",
        _scope_note,
    ]
    if _rc_boundary:
        _assumptions.append(_rc_boundary)
    if _identical_spef_groups:
        _assumptions.append(
            "per-corner SPEF contents are IDENTICAL (excluding the *DATE "
            "header) for %s -- the expected consequence of those corners "
            "sharing one RC model file, not a copy step"
            % "; ".join(", ".join(names)
                        for names in _identical_spef_groups.values()))

    return _cde(
        objective=(
            f"RC extraction of {top} ({', '.join(i['corner'] for i in extraction_plan)})"),
        status="completed",
        pdk_binding=binding or "none",
        results={"unextracted_corners": {"value": unextracted_corners,
                                         "unit": "corners"},
                 "corners_extracted": {"value": corners_extracted,
                                       "unit": "count"},
                 "nets_extracted": {
                     "value": max(nets_by_corner.values()) if nets_by_corner else 0,
                     "unit": "count"},
                 "nets_extracted_by_corner": nets_by_corner},
        signoff={"spef": corner_spefs[0] if len(corner_spefs) == 1 else None,
                 "corner": extraction_plan[0]["corner"] if len(extraction_plan) == 1 else None,
                 "rc_rules": extraction_plan[0]["bound_rc_rules"]
                 if len(extraction_plan) == 1 else None,
                 "report": "rcx.log",
                 "corner_cnt": len(extraction_plan),
                 "corner_cnt_source": (
                     "binding.rc_rules_by_corner" if _all_corners else "single"),
                 "corner_cnt_clamped_to_rc_model": _clamped,
                 "rc_model_corners": _rc_model_corners,
                 "rc_models_by_corner": {
                     digest: sorted(names)
                     for digest, names in _models_to_corners.items()},
                 "corners_sharing_one_rc_model": _shared_model_groups or None,
                 "identical_spef_content_groups": _identical_spef_groups or None,
                 "corners_declared_liberty": _declared_corners or None,
                 "corners_extracted": corners_extracted,
                 "corner_spefs": corner_spefs or None,
                 "corner_invocations": invocation_records,
                 "corner_coverage_complete": _complete,
                 "corner_scope": _scope_note,
                 "rc_corner_capability_boundary": _rc_boundary,
                 "next_stage_hint": _next_stage_hint,
                 "ext_options": _ext_opts.strip() or "default"},
        inputs_ref={"def_file": def_file,
                    "rc_rules_by_corner": {
                        i["corner"]: i["rc_rules"] for i in extraction_plan},
                    "tech_lef": tech_lef,
                    "cell_lef": cell_lefs, "liberty": libs},
        assumptions=_assumptions,
        validation={"verdict": "pass" if _complete else "fail",
                    "note": _scope_note},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "rcx.log",
                    "bookshelves_consulted": "unreachable: bookshelf.ask action rejected"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s == "extract":
        return _extract(params)
    return _cde(objective="extraction", status="failed",
                error=f"unknown scenario '{s}'; supported: extract",
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
