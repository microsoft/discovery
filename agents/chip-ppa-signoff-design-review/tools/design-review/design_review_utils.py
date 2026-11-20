#!/usr/bin/env python3
"""design_review_utils.py -- independent signoff / design-review adjudication for
the chip-ppa-signoff-design-review tool.

Consumes Common Design Envelopes only (never re-runs a flow stage). It judges
signoff readiness: required-gate coverage, un-waived violations, waiver validity
(owner + justification + rule-deck version), and PPA vs budget. It NEVER launders
an un-waived violation or an unjustified waiver into a `pass`. Node-agnostic.
Results conform to the Common Design Envelope.
"""
import json
import os

TOOL = "design-review"
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

_WAIVER_REQUIRED_FIELDS = ("owner", "justification", "rule_deck_version")


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


# ---------------------------------------------------------------- CDE helper
def _cde(objective, status, results=None, signoff=None, qor=None, assumptions=None,
         validation=None, inputs_ref=None, provenance=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "design-review", "version": "1.2.0"}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {},
        "margin": {"method": "evidence_sufficiency"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {"engine": "envelope review (no flow re-run)"},
    }
    if error:
        env["error"] = error
    return env


# ---------------------------------------------------------------- loaders
def _load_envelopes(params):
    """Load reviewed envelopes. Each must carry an 'id' referencing its source CDE.

    Records HOW each envelope arrived. An envelope read from disk can be hashed
    and re-read; one handed in inline as a dict cannot be distinguished from one
    the caller composed, so the two are never conflated."""
    envs = []
    for e in params.get("envelopes", []):
        if isinstance(e, str) and os.path.exists(e):
            d = json.load(open(e))
            d.setdefault("id", os.path.basename(e))
            d["_source_path"] = e
            d["_sha256"] = _hash_input_file(e)
            envs.append(d)
        elif isinstance(e, str):
            # A PATH THAT DOES NOT EXIST. Previously this fell through to the
            # "unresolvable entry" error only by luck of ordering; make it an
            # explicit, named failure -- a review cannot judge evidence it could
            # not open.
            raise ValueError(f"cited envelope file does not exist: {e}")
        elif isinstance(e, dict):
            if not e.get("id"):
                raise ValueError("each envelope needs an 'id' referencing its source CDE")
            d = dict(e)
            d["_source_path"] = None
            d["_sha256"] = None
            envs.append(d)
        else:
            raise ValueError(f"unresolvable envelope entry: {e!r}")
    return envs


#: Envelope fields whose values name an artifact FILE the producing stage wrote.
#: A review that never opens these is checking that a claim is internally
#: coherent, not that it is true.
_ARTIFACT_FIELDS = ("report", "log", "drc_report", "ir_report", "em_report",
                    "lvs_report", "antenna_report", "spef", "gds", "routed_def",
                    "floorplan_def", "netlist", "guide_file")


def _verify_evidence(envs, evidence_root=None, require_artifacts=False):
    """Open and hash the artifacts each envelope cites.

    The review previously checked only that an envelope's own fields were
    self-consistent -- it never opened the report a gate cited, so an envelope
    claiming `drc_report: drc.rpt` with no such file on disk reviewed exactly the
    same as one backed by a real report. This resolves each cited artifact,
    records its sha256, and reports the ones that are missing.

    `evidence_root` is where relative artifact paths are resolved. Without it,
    relative paths are UNRESOLVABLE, and that is reported as such rather than
    silently treated as verified."""
    out = {"envelopes": [], "artifacts": [], "missing_artifacts": [],
           "unresolvable_artifacts": [], "inline_envelopes": [],
           "hashed_envelopes": 0}
    for e in envs:
        eid = e.get("id")
        if e.get("_source_path"):
            out["hashed_envelopes"] += 1
            out["envelopes"].append({"id": eid, "path": e["_source_path"],
                                     "sha256": e.get("_sha256")})
        else:
            out["inline_envelopes"].append(eid)
        base = evidence_root
        if base is None and e.get("_source_path"):
            base = os.path.dirname(e["_source_path"])
        seen = set()
        for section in ("signoff_evidence", "provenance"):
            for k, v in (e.get(section) or {}).items():
                if k not in _ARTIFACT_FIELDS or not isinstance(v, str) or not v:
                    continue
                if (eid, k, v) in seen:
                    continue
                seen.add((eid, k, v))
                path = v if os.path.isabs(v) else (os.path.join(base, v) if base else None)
                if path is None:
                    out["unresolvable_artifacts"].append(
                        {"envelope": eid, "field": k, "cited": v,
                         "reason": "relative path and no evidence_root supplied"})
                elif os.path.exists(path):
                    out["artifacts"].append(
                        {"envelope": eid, "field": k, "cited": v, "path": path,
                         "sha256": _hash_input_file(path),
                         "bytes": os.path.getsize(path)})
                else:
                    out["missing_artifacts"].append(
                        {"envelope": eid, "field": k, "cited": v,
                         "resolved_to": path,
                         "reason": "cited artifact does not exist"})
    out["artifacts_verified"] = len(out["artifacts"])
    # The review is only artifact-backed when it actually opened something and
    # nothing it cited was missing.
    out["evidence_verified"] = bool(out["artifacts"]) and not out["missing_artifacts"]
    out["require_artifacts"] = bool(require_artifacts)
    return out


def _env_verdict(e):
    return e.get("verdict") or (e.get("validation") or {}).get("verdict")


#: Gates whose entire purpose is to count violations. For these, a count that
#: cannot be read is a hole in the review, not a zero.
_VIOLATION_BEARING_GATES = ("drc", "lvs", "antenna", "antenna_erc", "erc",
                            "sta", "cdc", "rdc", "cdc_rdc")

#: Result keys the producing agents actually emit. `unwaived_violations` is the
#: canonical one (chip-drc, chip-antenna-erc, chip-cdc-rdc-signoff); the rest are
#: their gate-specific totals. VERIFIED by reading each producer, not assumed.
_VIOLATION_KEYS = ("unwaived_violations", "drc_violations",
                   "antenna_erc_violations", "drv_violations",
                   "property_mismatches", "violations")


def _metric_value(container, key):
    """Read a CDE metric, which is {"value": N, "unit": ...} -- not a bare int."""
    if not isinstance(container, dict) or key not in container:
        return None
    v = container[key]
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return None


def _env_violations(e):
    """Un-waived violation count for an envelope, or None if it cannot be read.

    THIS PREVIOUSLY READ NOTHING THAT ANY PRODUCER EMITS. It looked only at a
    top-level `violations` key and at `signoff_evidence["violations"]` as a bare
    int -- while chip-drc, chip-lvs, chip-antenna-erc, chip-sta and
    chip-cdc-rdc-signoff all publish their counts in `results` as CDE METRIC
    DICTS (`results.unwaived_violations.value`, `results.drc_violations.value`,
    ...). MEASURED: a real chip-drc envelope carrying 7 un-waived violations
    returned 0 here, and a review of it came back `pass`.

    The consequence was that this agent's INDEPENDENT violation check did
    nothing at all: it always saw zero and fell back to trusting each envelope's
    own self-reported verdict -- the precise behaviour an independent reviewer
    exists to avoid.

    Returns None (NOT 0) when no count is present, so "measured zero" and "never
    read" stay distinguishable. Reporting an unreadable count as clean is the
    same false-absence bug in a new place.
    """
    for container in (e.get("results"), e.get("qor_metrics"),
                      e.get("signoff_evidence"), e):
        for key in _VIOLATION_KEYS:
            v = _metric_value(container, key)
            if v is not None:
                return v
    return None


def _policy_overrides(envs):
    """Find envelopes whose stage overrode a PDK tool_policy recommendation.

    A stage records `signoff_evidence.pdk_policy_override = true` (and an
    `engine_selection` with the recommended-vs-used engines) when a caller chose
    a tool/engine/settings that differ from the PDK's recommendation. The review
    must surface these as caveats -- a clean run that silently ignored the PDK's
    recommended toolset is not an unqualified pass."""
    overrides = []
    for e in envs:
        sig = e.get("signoff_evidence") or {}
        if sig.get("pdk_policy_override"):
            sel = sig.get("engine_selection") or {}
            overrides.append({
                "envelope": e.get("id"),
                "gate": e.get("gate"),
                "used": sel.get("engines"),
                "pdk_recommended": sel.get("pdk_recommended"),
                "source": sel.get("source")})
    return overrides


def _split_waivers(waivers):
    valid, invalid = [], []
    for w in waivers or []:
        if not isinstance(w, dict):
            invalid.append({"waiver": w, "missing": list(_WAIVER_REQUIRED_FIELDS)})
            continue
        missing = [f for f in _WAIVER_REQUIRED_FIELDS if not w.get(f)]
        if missing:
            invalid.append({"waiver": w.get("id", w), "missing": missing})
        else:
            valid.append(w)
    return valid, invalid


def _waived_count(valid_waivers, env):
    gate = env.get("gate")
    return sum(1 for w in valid_waivers
               if w.get("gate") == gate or w.get("envelope") == env.get("id"))


def _check_budget(envs, budget):
    """budget: {metric: {max: x} | {min: y}}. Returns {metric: {...}}."""
    ppa = {}
    if not budget:
        return ppa
    # collect the latest available value per metric across envelopes
    values = {}
    for e in envs:
        for src in ("qor_metrics", "metrics", "qor"):
            for k, v in (e.get(src) or {}).items():
                if isinstance(v, dict) and "value" in v:
                    v = v["value"]
                if isinstance(v, (int, float)):
                    values[k] = v
    for metric, spec in budget.items():
        val = values.get(metric)
        if val is None:
            # A metric the caller BUDGETED but no envelope measured. This is not
            # a neutral gap: the design was not shown to meet a limit the caller
            # declared. `meets: None` was previously excluded from the violation
            # list, so declaring a budget nobody measured was indistinguishable
            # from meeting it.
            ppa[metric] = {"value": None, "budget": spec, "meets": None,
                           "note": "BUDGETED BUT NEVER MEASURED: no envelope "
                                   "reports this metric, so the design was not "
                                   "shown to meet it"}
            continue
        meets = True
        if "max" in spec and val > spec["max"]:
            meets = False
        if "min" in spec and val < spec["min"]:
            meets = False
        ppa[metric] = {"value": val, "budget": spec, "meets": meets}
    return ppa


#: The gates this catalog itself documents as MANDATORY for tapeout. Sourced from
#: the agent descriptions -- chip-drc: "DRC is a mandatory tapeout gate: zero
#: un-waived violations to sign off"; chip-lvs: "LVS is a mandatory tapeout
#: gate" -- and from the openroad skill, which gates GDS assembly on DRC, LVS
#: AND antenna together. Not invented here; only quoted.
#:
#: This is a FLOOR, never a complete list. A design's real gate set depends on
#: the design (CDC, low-power, DFT, formal, ...), which this tool cannot know
#: because it only sees the envelopes it was handed.
_MANDATORY_TAPEOUT_GATES = ("drc", "lvs", "antenna")


def _decide(unwaived_violations, missing_gates, failed_envs, invalid_waivers,
            ppa_violations, policy_overrides=None, ppa_unmeasured=None,
            evidence_gaps=None):
    if unwaived_violations > 0 or missing_gates or failed_envs or ppa_violations:
        return "fail"
    # A budget declared and never measured, or a cited artifact that is not on
    # disk, blocks a clean pass. Neither is a violation that was FOUND -- they
    # are checks that were not completed -- so they cap the verdict rather than
    # asserting a failure.
    if ppa_unmeasured or evidence_gaps:
        return "pass_with_caveats"
    if invalid_waivers or policy_overrides:
        return "pass_with_caveats"
    return "pass"


def _confidence(envs, missing_gates, invalid_waivers, gate_list_supplied=True,
                evidence=None, unreadable_counts=None, ppa_unmeasured=None):
    """Confidence in the REVIEW, judged on what it was able to establish.

    Previously this was a function of submission FORM only (were gates listed,
    were waivers well-formed), so a review that opened nothing, could not read a
    single violation count, and never measured a budgeted metric still reported
    `high`. Confidence now degrades with every check the review could not
    actually complete."""
    if missing_gates:
        return "low"
    if not gate_list_supplied:
        return "low"
    if not envs:
        return "low"
    ev = evidence or {}
    # Citing an artifact that is not on disk is a broken citation: the review
    # cannot be confident in evidence it could not open.
    if ev.get("missing_artifacts"):
        return "low"
    if unreadable_counts:
        return "low"
    demoted = False
    if invalid_waivers:
        demoted = True
    if ppa_unmeasured:
        demoted = True
    # Nothing was opened: every envelope came in inline and no artifact was
    # resolved. The review checked coherence, not truth.
    if not ev.get("artifacts") and not ev.get("hashed_envelopes"):
        return "low"
    if ev.get("unresolvable_artifacts") or ev.get("inline_envelopes"):
        demoted = True
    if ev.get("require_artifacts") and not ev.get("artifacts"):
        return "low"
    return "medium" if demoted else "high"


# ---------------------------------------------------------------- scenarios
def _review(params, focus="signoff"):
    try:
        envs = _load_envelopes(params)
    except ValueError as _e:
        # Unloadable evidence is a REVIEW FAILURE reported as an envelope, not a
        # traceback: the caller needs a verdict object either way.
        return _cde(objective="signoff review", status="failed",
                    error=str(_e),
                    validation={"verdict": "fail",
                                "reason": "evidence could not be loaded",
                                "confidence": "low"})
    if not envs:
        return _cde(objective="signoff review", status="failed",
                    error="no envelopes supplied to review",
                    validation={"verdict": "fail", "reason": "no evidence"})

    required_gates = params.get("required_gates", [])
    waivers = params.get("waivers", [])
    budget = params.get("budget", {})
    valid_waivers, invalid_waivers = _split_waivers(waivers)

    covered = {}
    unwaived_violations = 0
    violation_detail = []
    failed_envs = []
    unreadable_counts = []
    for e in envs:
        gate = e.get("gate")
        if gate:
            covered[gate] = e["id"]
        st = e.get("status", "completed")
        verdict = _env_verdict(e)
        raw_v = _env_violations(e)
        if raw_v is None:
            # A violation-counting gate whose count cannot be read leaves this
            # review with NOTHING to check independently -- it would fall back
            # to the envelope's own verdict, which is not review.
            if gate and str(gate).lower() in _VIOLATION_BEARING_GATES:
                unreadable_counts.append({
                    "envelope": e["id"], "gate": gate,
                    "detail": ("no violation count found in results/qor/"
                               "signoff_evidence; this gate's whole output is a "
                               "count, so an unreadable one is a hole in the "
                               "review, not a zero")})
        else:
            open_v = max(0, raw_v - _waived_count(valid_waivers, e))
            if open_v:
                unwaived_violations += open_v
                violation_detail.append({"envelope": e["id"], "gate": gate,
                                         "open_violations": open_v})
        if st == "failed" or verdict == "fail":
            failed_envs.append(e["id"])

    # Gate names are matched case- and separator-insensitively on BOTH paths.
    # The documented example passes `required_gates: ["DRC","LVS","STA"]` while
    # envelopes may label the same gate `drc`; a literal comparison reported a
    # fully covered design as missing every gate -- a FALSE FAIL, which is how a
    # reviewer learns to ignore this check. `antenna_erc` and `antenna` are the
    # same gate under two agent names.
    _GATE_ALIASES = {"antenna": {"antenna", "antenna_erc", "erc"},
                     "antenna_erc": {"antenna", "antenna_erc", "erc"},
                     "erc": {"antenna", "antenna_erc", "erc"}}

    def _norm(g):
        return str(g).strip().lower().replace("-", "_").replace(" ", "_")

    covered_norm = {_norm(g) for g in covered}

    def _is_covered(gate):
        n = _norm(gate)
        return bool(_GATE_ALIASES.get(n, {n}) & covered_norm)

    missing_gates = [g for g in required_gates if not _is_covered(g)]
    # AN EMPTY REQUIRED LIST IS NOT A SATISFIED ONE.
    # `required_gates` defaulted to [], so the comprehension above iterated zero
    # times, `missing_gates` came out empty, and the review reported "all
    # required gates covered". MEASURED: a signoff review holding ONE synthesis
    # envelope -- no DRC, no LVS, no antenna, no STA -- returned verdict `pass`
    # with confidence `high`. This agent's entire purpose is to refuse exactly
    # that, and it was the easiest possible way to obtain a green signoff.
    #
    # When no list is supplied the tool falls back to the floor this catalog
    # documents as mandatory, and reports that COMPLETENESS IS UNKNOWN: it
    # cannot know which further gates this particular design needed.
    gate_list_supplied = bool(required_gates)
    floor_missing = []
    if not gate_list_supplied and focus == "signoff":
        floor_missing = [g for g in _MANDATORY_TAPEOUT_GATES
                         if not _is_covered(g)]
        missing_gates = list(floor_missing)

    ppa = _check_budget(envs, budget)
    ppa_violations = [m for m, d in ppa.items() if d.get("meets") is False]
    # Budgeted but never measured. Tracked separately from a violation because
    # it is a check that did not happen, not a limit that was breached -- but it
    # must still block a clean pass.
    ppa_unmeasured = [m for m, d in ppa.items() if d.get("meets") is None]
    policy_overrides = _policy_overrides(envs)

    # Open and hash what the envelopes cite, rather than trusting that it exists.
    evidence = _verify_evidence(envs, params.get("evidence_root"),
                                bool(params.get("require_artifacts")))
    evidence_gaps = list(evidence["missing_artifacts"])
    if evidence["require_artifacts"] and not evidence["artifacts"]:
        evidence_gaps.append({"reason": "require_artifacts was set but no cited "
                                        "artifact could be opened"})

    verdict = _decide(unwaived_violations, missing_gates, failed_envs,
                      invalid_waivers, ppa_violations, policy_overrides,
                      ppa_unmeasured, evidence_gaps)
    # Even with the mandatory floor met, an unsupplied gate list means the
    # completeness question was never answered. That is not a pass.
    if not gate_list_supplied and verdict in ("pass", "pass_with_caveats"):
        verdict = "not_assessable"
    # A gate whose count could not be read was NOT independently checked.
    if unreadable_counts and verdict in ("pass", "pass_with_caveats"):
        verdict = "not_assessable"
    confidence = _confidence(envs, missing_gates, invalid_waivers,
                             gate_list_supplied, evidence, unreadable_counts,
                             ppa_unmeasured)
    if unreadable_counts:
        confidence = "low"

    notes = []
    if evidence["missing_artifacts"]:
        notes.append(
            "CITED ARTIFACT(S) NOT ON DISK: %s. The review opened what each "
            "envelope pointed at; these could not be opened, so the claims "
            "resting on them are unverified."
            % ([a["cited"] for a in evidence["missing_artifacts"]][:6],))
    if ppa_unmeasured:
        notes.append(
            "BUDGETED BUT NEVER MEASURED: %s. A budget was declared for these "
            "metrics and no envelope reports them, so the design was not shown "
            "to meet them." % (ppa_unmeasured,))
    if evidence["inline_envelopes"] and not evidence["hashed_envelopes"]:
        notes.append(
            "every envelope was supplied INLINE, so none could be hashed or "
            "re-read from its source; this review checked internal coherence, "
            "not that the evidence exists")
    if invalid_waivers:
        notes.append("invalid waiver(s) present: missing owner/justification/"
                     "rule-deck version -- not laundered into a pass")
    if unwaived_violations:
        notes.append("un-waived violation(s) present -> fail")
    if unreadable_counts:
        notes.append(
            "violation count UNREADABLE for %d violation-counting gate(s): %s. "
            "Their counts were not independently verified, so this review would "
            "be relying on each envelope's own verdict."
            % (len(unreadable_counts),
               [u["gate"] for u in unreadable_counts]))
    if missing_gates:
        notes.append(f"required gate(s) without evidence: {missing_gates}")
    if not gate_list_supplied:
        notes.append(
            "NO `required_gates` SUPPLIED: gate coverage was checked only "
            "against the mandatory tapeout floor %s that this catalog documents "
            "(DRC, LVS and antenna gate GDS assembly). Whether this design "
            "needed further gates -- CDC, low-power, DFT, formal, STA corners -- "
            "was NOT assessed, because the reviewer was never told. Supply "
            "`required_gates` to obtain a pass."
            % (list(_MANDATORY_TAPEOUT_GATES),))
    if policy_overrides:
        notes.append("PDK tool_policy override(s): a stage used a tool/engine set "
                     "differing from the PDK recommendation -> pass_with_caveats")

    return _cde(
        objective=f"{focus} review of {len(envs)} envelope(s)",
        status="completed",
        results={
            "verdict": {"value": verdict, "unit": "enum"},
            "covered_gates": {"value": len(covered), "unit": "count"},
            "missing_gates": {"value": len(missing_gates), "unit": "count"},
            "gate_list_supplied": {
                "value": gate_list_supplied, "unit": "bool",
                "class": "gating", "basis": "caller_declaration",
                "closes_at": "== True",
                "note": ("Whether the reviewer was told WHICH gates this design "
                         "required. Without it, coverage is checked only against "
                         "the documented mandatory floor and completeness is "
                         "unknown -- an empty required list is not a satisfied "
                         "one.")},
            "unwaived_violations": {"value": unwaived_violations, "unit": "count"},
            "unreadable_violation_counts": {
                "value": len(unreadable_counts), "unit": "count",
                "class": "gating", "basis": "envelope_parse",
                "closes_at": "== 0",
                "note": ("Violation-counting gates whose count this reviewer "
                         "could not read. Reported rather than treated as zero: "
                         "an unreadable count is not a clean one, and falling "
                         "back to the envelope's self-reported verdict is not "
                         "independent review.")},
            "invalid_waivers": {"value": len(invalid_waivers), "unit": "count"},
            "pdk_policy_overrides": {"value": len(policy_overrides), "unit": "count"},
        },
        qor=ppa,
        signoff={
            "covered_gates": covered,
            "missing_gates": missing_gates,
            "gate_list_supplied": gate_list_supplied,
            "mandatory_floor_applied": (list(_MANDATORY_TAPEOUT_GATES)
                                        if not gate_list_supplied else None),
            "unwaived_violations": violation_detail,
            "unreadable_violation_counts": unreadable_counts or None,
            "invalid_waivers": invalid_waivers,
            "valid_waivers": [w.get("id", w.get("gate")) for w in valid_waivers],
            "failed_envelopes": failed_envs,
            "ppa_vs_budget": ppa,
            "ppa_budgeted_but_unmeasured": ppa_unmeasured or None,
            "evidence_audit": evidence,
            "evidence_verified": evidence["evidence_verified"],
            "artifacts_opened": evidence["artifacts_verified"],
            "missing_artifacts": evidence["missing_artifacts"] or None,
            "pdk_policy_overrides": policy_overrides,
            "notes": notes or ["all required gates covered; no open violations"],
        },
        inputs_ref={"reviewed": [e["id"] for e in envs]},
        assumptions=["consumes envelopes only; no flow stage re-run",
                     "cited artifacts are opened and hashed where they can be "
                     "resolved; an envelope supplied inline cannot be re-read "
                     "from source and is reported as such"],
        validation={"verdict": verdict, "confidence": confidence,
                    "independent_review": True},
    )


def _adjudicate_waivers(params):
    envs = _load_envelopes(params)
    waivers = params.get("waivers")
    if waivers is None:
        return _cde(objective="waiver adjudication", status="failed",
                    error="adjudicate_waivers requires a 'waivers' list",
                    validation={"verdict": "fail"})
    valid_waivers, invalid_waivers = _split_waivers(waivers)

    open_violations = 0
    unreadable = []
    detail = []
    for e in envs:
        raw_v = _env_violations(e)
        if raw_v is None:
            unreadable.append(e["id"])
            continue
        open_v = max(0, raw_v - _waived_count(valid_waivers, e))
        if open_v:
            open_violations += open_v
            detail.append({"envelope": e["id"], "gate": e.get("gate"),
                           "open_violations": open_v})

    # An unjustified waiver can never clear a real violation.
    if open_violations > 0:
        verdict = "fail"
    elif unreadable:
        verdict = "not_assessable"
    elif invalid_waivers:
        verdict = "pass_with_caveats"
    else:
        verdict = "pass"

    return _cde(
        objective="waiver adjudication",
        status="completed",
        results={
            "verdict": {"value": verdict, "unit": "enum"},
            "valid_waivers": {"value": len(valid_waivers), "unit": "count"},
            "invalid_waivers": {"value": len(invalid_waivers), "unit": "count"},
            "open_violations": {"value": open_violations, "unit": "count"},
        },
        signoff={"valid_waivers": [w.get("id", w.get("gate")) for w in valid_waivers],
                 "invalid_waivers": invalid_waivers,
                 "open_violations": detail,
                 "unreadable_violation_counts": unreadable,
                 "policy": "waiver requires owner + justification + rule-deck "
                           "version; unjustified waivers never clear a violation"},
        inputs_ref={"reviewed": [e["id"] for e in envs]},
        validation={"verdict": verdict,
                    "confidence": "low" if unreadable else ("high" if not invalid_waivers else "medium")},
    )


def _check_evidence(params):
    envs = _load_envelopes(params)
    required_fields = params.get("required_fields") or ["status", "validation"]
    required_gates = params.get("required_gates", [])
    per_env = []
    all_ok = True
    covered = {}
    for e in envs:
        missing = [f for f in required_fields if f not in e]
        if e.get("gate"):
            covered[e["gate"]] = e["id"]
        ok = not missing
        all_ok = all_ok and ok
        per_env.append({"id": e["id"], "missing_fields": missing, "ok": ok})
    missing_gates = [g for g in required_gates if g not in covered]
    verdict = "pass" if (all_ok and not missing_gates) else "fail"
    return _cde(
        objective="evidence-sufficiency check",
        status="completed",
        results={"verdict": {"value": verdict, "unit": "enum"},
                 "envelopes": {"value": len(envs), "unit": "count"},
                 "missing_gates": {"value": len(missing_gates), "unit": "count"}},
        signoff={"per_envelope": per_env, "missing_gates": missing_gates,
                 "required_fields": required_fields},
        inputs_ref={"reviewed": [e["id"] for e in envs]},
        validation={"verdict": verdict,
                    "confidence": "high" if verdict == "pass" else "low"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s == "review_signoff":
        return _review(params, focus="signoff")
    if s == "adjudicate_waivers":
        return _adjudicate_waivers(params)
    if s == "check_evidence":
        return _check_evidence(params)
    return _cde(objective="design review", status="failed",
                error=f"unknown scenario '{s}'; supported: review_signoff, "
                      "adjudicate_waivers, check_evidence",
                validation={"verdict": "fail", "reason": "unknown scenario"})


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
