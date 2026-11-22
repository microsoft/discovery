#!/usr/bin/env python3
"""soc_integration_utils.py -- hierarchical SoC assembly and budget partitioning.

Partitions the top-level PPA budget to blocks (by weight or explicit values),
verifies the partition sums within the top budget, defines interconnect topology,
and checks interface consistency across blocks. Node-aware. Results conform to the
Common Design Envelope.
"""
import json
import os

TOOL = "soc-integration"
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


def _cde(objective, status, results=None, signoff=None, qor=None, pdk_binding=None,
         assumptions=None, validation=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "soc-integration", "version": "1.0.0"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "budget_partition"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic budget partition"},
    }
    if error:
        env["error"] = error
    return env


_INITIATOR = {"master", "initiator", "manager", "source", "out", "output", "tx"}
_TARGET = {"slave", "target", "subordinate", "sink", "in", "input", "rx"}


def _norm_role(v):
    """Map a role/direction spelling onto 'initiator' / 'target' / None."""
    s = str(v or "").strip().lower()
    if s in _INITIATOR:
        return "initiator"
    if s in _TARGET:
        return "target"
    return None


def _iface_endpoints(blocks):
    """Return [{block, name, width, role, clock_domain, protocol, raw}] for every
    interface on every block.

    Accepts both the legacy shorthand (`interfaces: ["axi"]`, a bare name) and the
    full form (`{name, width, direction|role, clock_domain, protocol}`). The
    shorthand carries NO width, role or domain, which is exactly why a name-only
    check cannot judge consistency -- such an endpoint is recorded with None
    fields and reported as under-specified rather than silently treated as
    matching."""
    eps = []
    for b in blocks:
        for i in (b.get("interfaces") or []):
            if isinstance(i, dict):
                eps.append({
                    "block": b.get("name"), "name": i.get("name"),
                    "width": i.get("width"),
                    "role": _norm_role(i.get("role", i.get("direction"))),
                    "clock_domain": i.get("clock_domain", i.get("domain")),
                    "protocol": i.get("protocol"),
                    "role_declared": i.get("role", i.get("direction")) is not None,
                })
            else:
                eps.append({"block": b.get("name"), "name": i, "width": None,
                            "role": None, "clock_domain": None, "protocol": None,
                            "role_declared": False})
    return eps


def _check_interfaces(blocks):
    """Check interface consistency across blocks by COMPARING THE SIGNALS, not by
    counting how many times a name appears.

    Two blocks can both list "axi" and still be unconnectable: different data
    widths, both driving as initiators, or sitting in different clock domains. A
    count of occurrences cannot see any of that -- it reports 'consistent' for a
    32-bit master talking to a 64-bit master. Each finding names the interface,
    the blocks, and the field that disagrees."""
    eps = _iface_endpoints(blocks)
    by_name = {}
    for e in eps:
        by_name.setdefault(e["name"], []).append(e)
    findings = []
    gaps = []
    per_iface = []
    for name, group in sorted(by_name.items(), key=lambda kv: str(kv[0])):
        blks = sorted({e["block"] for e in group})
        widths = sorted({e["width"] for e in group if e["width"] is not None})
        domains = sorted({str(e["clock_domain"]) for e in group
                          if e["clock_domain"] is not None})
        protos = sorted({str(e["protocol"]) for e in group
                         if e["protocol"] is not None})
        roles = [e["role"] for e in group if e["role"]]
        inits = roles.count("initiator")
        targs = roles.count("target")
        under = [e["block"] for e in group
                 if e["width"] is None or not e["role_declared"]]
        rec = {"interface": name, "blocks": blks, "endpoints": len(group),
               "widths": widths, "clock_domains": domains, "protocols": protos,
               "initiators": inits, "targets": targs,
               "under_specified_on": under, "issues": [], "gaps": []}
        if len(group) < 2:
            rec["issues"].append("dangling: only one endpoint; it connects to "
                                 "nothing inside this hierarchy")
        if len(widths) > 1:
            rec["issues"].append(f"width mismatch across blocks: {widths}")
        if len(domains) > 1:
            rec["issues"].append(
                f"clock-domain mismatch across blocks: {domains}; this crossing "
                f"needs a CDC scheme and is out of scope for integration")
        if len(protos) > 1:
            rec["issues"].append(f"protocol mismatch across blocks: {protos}")
        if len(group) >= 2 and inits and not targs:
            rec["issues"].append(f"{inits} initiators and no target: nothing "
                                 f"terminates this interface")
        if len(group) >= 2 and targs and not inits:
            rec["issues"].append(f"{targs} targets and no initiator: nothing "
                                 f"drives this interface")
        if under:
            # A GAP, not a contradiction. Nothing here disagrees -- there is not
            # enough information to tell whether it agrees. Keeping the two apart
            # matters: a gap must block a clean pass without being reported as a
            # violation that was found.
            rec["gaps"].append(
                "under-specified on " + ", ".join(sorted(under))
                + ": no width and/or role declared, so consistency CANNOT be "
                  "established (this is not the same as being consistent)")
        rec["consistent"] = not rec["issues"]
        rec["fully_specified"] = not rec["gaps"]
        per_iface.append(rec)
        for msg in rec["issues"]:
            findings.append({"interface": name, "blocks": blks, "detail": msg})
        for msg in rec["gaps"]:
            gaps.append({"interface": name, "blocks": blks, "detail": msg})
    fully_specified = [r for r in per_iface if r["fully_specified"]]
    return {
        "interfaces": per_iface,
        "findings": findings,
        "gaps": gaps,
        "interface_count": len(per_iface),
        "endpoint_count": len(eps),
        "inconsistent_count": sum(1 for r in per_iface if not r["consistent"]),
        "under_specified_count": len(per_iface) - len(fully_specified),
        # An interface set is only "checked" when every interface carried enough
        # information to be compared. Otherwise the clean ones are clean and the
        # rest are simply unknown.
        "fully_checked": bool(per_iface) and len(fully_specified) == len(per_iface),
    }


def _require_blocks(params, objective):
    blocks = params.get("blocks") or []
    if not blocks:
        return None, _cde(objective=objective, status="failed",
                          error="need 'blocks'", validation={"verdict": "fail"})
    unnamed = [i for i, b in enumerate(blocks) if not b.get("name")]
    if unnamed:
        return None, _cde(objective=objective, status="failed",
                          error=f"blocks at index {unnamed} have no 'name'",
                          validation={"verdict": "fail"})
    return blocks, None


def _assemble(params):
    """Assemble blocks into a hierarchy and stitch interfaces.

    Checks the things that make an assembly ill-formed regardless of budget:
    duplicate instance names, self-referential or unknown children, and
    interfaces that cannot actually be wired."""
    blocks, err = _require_blocks(params, "assemble SoC hierarchy")
    if err:
        return err
    names = [b["name"] for b in blocks]
    dupes = sorted({n for n in names if names.count(n) > 1})
    known = set(names)
    unknown_children = []
    for b in blocks:
        for c in (b.get("contains") or []):
            if c not in known:
                unknown_children.append({"block": b["name"], "child": c})
    self_ref = sorted({b["name"] for b in blocks
                       if b["name"] in (b.get("contains") or [])})
    ic = _check_interfaces(blocks)
    children = {c for b in blocks for c in (b.get("contains") or [])}
    roots = [n for n in names if n not in children]
    hard = bool(dupes or unknown_children or self_ref) or ic["inconsistent_count"] > 0
    if hard:
        verdict = "fail"
    elif not ic["fully_checked"]:
        # Nothing contradicted, but the interfaces were not fully described, so the
        # stitch was not actually verified. Do not report that as assembled.
        verdict = "review"
    else:
        verdict = "pass"
    return _cde(
        objective=f"assemble {len(blocks)} block(s) into an SoC hierarchy",
        status="completed" if verdict != "fail" else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"blocks": {"value": len(blocks), "unit": "count"},
                 "interfaces": {"value": ic["interface_count"], "unit": "count"},
                 "hierarchy_roots": {"value": len(roots), "unit": "count"}},
        qor={"block_count": len(blocks), "interface_count": ic["interface_count"],
             "inconsistent_interfaces": ic["inconsistent_count"],
             "under_specified_interfaces": ic["under_specified_count"]},
        signoff={"roots": roots, "duplicate_block_names": dupes,
                 "unknown_children": unknown_children,
                 "self_referential_blocks": self_ref,
                 "interface_check": ic,
                 "interfaces_fully_checked": ic["fully_checked"]},
        inputs_ref={"blocks": names},
        assumptions=["hierarchy is taken from the declared 'contains' lists; a block "
                     "named by no other block is a root"],
        validation={"verdict": verdict,
                    "note": ("; ".join(
                        ([f"duplicate block names: {dupes}"] if dupes else [])
                        + ([f"unknown children: {unknown_children}"] if unknown_children else [])
                        + ([f"self-referential: {self_ref}"] if self_ref else [])
                        + [f["interface"] + ": " + f["detail"]
                           for f in ic["findings"] + ic["gaps"]])
                        or "hierarchy well-formed and every interface consistent")},
    )


def _interconnect(params):
    """Derive the on-chip interconnect topology from the declared interfaces.

    Topology is CLASSIFIED FROM ENDPOINT COUNTS, not asserted: one initiator and
    one target is point-to-point, one initiator with many targets is a shared bus,
    and many initiators with many targets needs a crossbar/NoC."""
    blocks, err = _require_blocks(params, "define interconnect")
    if err:
        return err
    ic = _check_interfaces(blocks)
    topo = []
    for r in ic["interfaces"]:
        i, t = r["initiators"], r["targets"]
        if not r["blocks"] or r["endpoints"] < 2:
            kind = "unconnected"
        elif not (i or t):
            kind = "undetermined"     # no roles declared: cannot classify
        elif i <= 1 and t <= 1:
            kind = "point_to_point"
        elif i <= 1:
            kind = "shared_bus"
        else:
            kind = "crossbar_or_noc"
        topo.append({"interface": r["interface"], "topology": kind,
                     "initiators": i, "targets": t, "blocks": r["blocks"],
                     "consistent": r["consistent"]})
    undetermined = [t["interface"] for t in topo if t["topology"] == "undetermined"]
    if ic["inconsistent_count"]:
        verdict = "fail"
    elif undetermined or not ic["fully_checked"]:
        verdict = "review"
    else:
        verdict = "pass"
    return _cde(
        objective="define the on-chip interconnect topology",
        status="completed" if verdict != "fail" else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"interfaces": {"value": ic["interface_count"], "unit": "count"},
                 "crossbar_or_noc": {
                     "value": sum(1 for t in topo if t["topology"] == "crossbar_or_noc"),
                     "unit": "count"}},
        qor={"interface_count": ic["interface_count"],
             "inconsistent_interfaces": ic["inconsistent_count"],
             "undetermined_topologies": len(undetermined)},
        signoff={"topology": topo, "interface_check": ic,
                 "undetermined_topologies": undetermined},
        inputs_ref={"blocks": [b["name"] for b in blocks]},
        assumptions=["topology classified from declared initiator/target roles; an "
                     "interface with no declared roles is 'undetermined', never "
                     "assumed point-to-point"],
        validation={"verdict": verdict,
                    "note": ("; ".join(f["interface"] + ": " + f["detail"]
                                       for f in ic["findings"] + ic["gaps"])
                             or (f"roles not declared for {undetermined}; topology "
                                 f"cannot be classified" if undetermined
                                 else "topology derived for every interface"))},
    )


def _boundary_abstract(params):
    """Produce per-block boundary timing constraints from the top-level budget.

    The clock period comes from the top-level frequency and the I/O budget is a
    stated FRACTION of that period. NEITHER IS INVENTED: if the top-level
    frequency is absent, the constraint is not emitted and the run reports the
    hole, because a fabricated period would be handed to each block agent and
    closed against, making every downstream stage report success against a number
    nobody chose."""
    blocks, err = _require_blocks(params, "boundary abstraction")
    if err:
        return err
    top = params.get("top_budget") or {}
    holes = []
    top_freq = top.get("freq_mhz")
    if top_freq is None:
        holes.append("top_budget.freq_mhz absent: no clock period can be derived")
    io_frac = params.get("io_budget_fraction")
    if io_frac is None:
        holes.append("io_budget_fraction not supplied: the share of the period "
                     "allotted to input+output delay is a design decision, not a "
                     "default")
    per_block = []
    for b in blocks:
        fr = b.get("freq_mhz", top_freq)
        period_ns = (1000.0 / fr) if fr else None
        if period_ns is not None and io_frac is not None:
            budget = period_ns * float(io_frac)
            in_ns = round(budget / 2.0, 4)
            out_ns = round(budget / 2.0, 4)
        else:
            in_ns = out_ns = None
        per_block.append({
            "block": b["name"], "freq_mhz": fr,
            "clock_period_ns": round(period_ns, 4) if period_ns else None,
            "input_delay_ns": in_ns, "output_delay_ns": out_ns,
            "interfaces": [e["name"] for e in _iface_endpoints([b])],
            "constraint_emitted": in_ns is not None,
        })
    emitted = [p for p in per_block if p["constraint_emitted"]]
    ic = _check_interfaces(blocks)
    if ic["inconsistent_count"]:
        verdict = "fail"
    elif holes or len(emitted) != len(per_block):
        verdict = "review"
    else:
        verdict = "pass"
    return _cde(
        objective=f"boundary constraints for {len(blocks)} block(s)",
        status="completed" if verdict != "fail" else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"blocks": {"value": len(per_block), "unit": "count"},
                 "constraints_emitted": {"value": len(emitted), "unit": "count"}},
        qor={"block_count": len(per_block), "constraints_emitted": len(emitted),
             "io_budget_fraction": io_frac},
        signoff={"per_block_constraints": per_block, "intent_holes": holes,
                 "interface_check": ic},
        inputs_ref={"blocks": [b["name"] for b in blocks]},
        assumptions=["clock period derived from the top-level (or per-block) "
                     "frequency; the I/O budget is split evenly between input and "
                     "output delay; no period or I/O budget is defaulted"],
        validation={"verdict": verdict,
                    "note": ("; ".join(f["interface"] + ": " + f["detail"]
                                       for f in ic["findings"] + ic["gaps"])
                             or ("; ".join(holes)
                                 or "boundary constraints derived for every block"))},
    )


def _partition(params):
    blocks = params.get("blocks", [])
    top = params.get("top_budget", {})
    if not blocks or not top:
        return _cde(objective="partition budget", status="failed",
                    error="need 'blocks' and 'top_budget'", validation={"verdict": "fail"})
    _, err = _require_blocks(params, "partition budget")
    if err:
        return err
    wsum = sum(b.get("weight", 1) for b in blocks)
    if not wsum:
        return _cde(objective="partition budget", status="failed",
                    error="block weights sum to zero; cannot apportion the budget",
                    validation={"verdict": "fail"})
    per_block = []
    tot = {"power_mw": 0.0, "area_um2": 0.0}
    for b in blocks:
        frac = b.get("weight", 1) / wsum
        pw = b.get("power_mw", round(top.get("power_mw", 0) * frac, 3))
        ar = b.get("area_um2", round(top.get("area_um2", 0) * frac, 1))
        fr = b.get("freq_mhz", top.get("freq_mhz"))
        tot["power_mw"] += pw
        tot["area_um2"] += ar
        per_block.append({"name": b["name"], "freq_mhz": fr, "power_mw": pw,
                          "area_um2": ar, "interfaces": b.get("interfaces", [])})
    over = (tot["power_mw"] > top.get("power_mw", float("inf")) + 1e-6 or
            tot["area_um2"] > top.get("area_um2", float("inf")) + 1e-6)
    # Interface consistency compares the SIGNALS (width, role, clock domain,
    # protocol). The previous check counted how many blocks mentioned a name, so
    # a 32-bit master wired to a 64-bit master read as consistent.
    ic = _check_interfaces(blocks)
    dangling = [r["interface"] for r in ic["interfaces"] if r["endpoints"] < 2]
    if over or ic["inconsistent_count"]:
        verdict = "fail"
    elif not ic["fully_checked"] and ic["interface_count"]:
        # Budgets close, but the interfaces were never actually comparable.
        verdict = "review"
    else:
        verdict = "pass"
    return _cde(
        objective="partition top-level budget to blocks",
        status="completed" if verdict != "fail" else "failed",
        pdk_binding=params.get("pdk_binding", "none"),
        results={"blocks": {"value": len(per_block), "unit": "count"},
                 "rollup_power_mw": {"value": round(tot["power_mw"], 3), "unit": "mW"},
                 "rollup_area_um2": {"value": round(tot["area_um2"], 1), "unit": "um^2"}},
        qor={"top_budget": top, "rollup": tot,
             "inconsistent_interfaces": ic["inconsistent_count"],
             "under_specified_interfaces": ic["under_specified_count"]},
        signoff={"per_block_budgets": per_block,
                 "budget_within_top": not over,
                 "interface_check": ic,
                 "interfaces_fully_checked": ic["fully_checked"],
                 "dangling_interfaces": dangling},
        inputs_ref={"blocks": [b["name"] for b in blocks]},
        assumptions=["weight-proportional partition unless explicit per-block values "
                     "given; interface consistency compares width, role, clock "
                     "domain and protocol -- not name occurrence"],
        validation={"verdict": verdict,
                    "note": ("budget overflow: rollup exceeds top_budget" if over
                             else ("; ".join(f["interface"] + ": " + f["detail"]
                                             for f in ic["findings"] + ic["gaps"])
                                   or "budgets sum within top and every interface "
                                      "is consistent"))},
    )


def dispatch(params):
    s = params.get("scenario")
    # Each scenario has its own implementation. Routing them all to _partition
    # made four advertised capabilities indistinguishable: asking for an
    # interconnect topology or a boundary abstract returned a budget partition
    # and reported success.
    def _pad_connectivity(params):
        from pad_connectivity_preflight import check_pad_connectivity
        return check_pad_connectivity(params)

    handlers = {"assemble": _assemble, "partition_budget": _partition,
                "interconnect": _interconnect, "boundary_abstract": _boundary_abstract,
                "pad_connectivity": _pad_connectivity}
    fn = handlers.get(s)
    if fn:
        return fn(params)
    return _cde(objective="soc integration", status="failed",
                error=f"unknown scenario '{s}'; supported: "
                      + ", ".join(sorted(handlers)),
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
