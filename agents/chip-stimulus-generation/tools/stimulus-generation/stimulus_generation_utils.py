#!/usr/bin/env python3
"""stimulus_generation_utils.py -- directed and constrained-random stimulus
generation for the chip-stimulus-generation tool.

Seeded pseudo-random sampling over ranges and weighted value-sets, with simple
relational blocks honoured by BOUNDED REJECTION SAMPLING. There is no SMT/CSP
solver here (no pyvsc, no z3): higher-order or tightly-coupled constraints are
not solved, they are sampled-and-checked, and a sample that does not conform is
dropped rather than emitted.

Every emitted transaction is re-checked against the full constraint set --
field domains AND relational blocks -- immediately before emission, so the tool
never emits stimulus that violates the constraints it was given.

Node-agnostic; shares the vplan. Results conform to the CDE.
"""
import json
import os
import random

TOOL = "stimulus-generation"
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
    if results.get("signoff_evidence", {}).get("file") == "stimulus.json":
        results["signoff_evidence"]["file"] = "results/stimulus.json"
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


def _cde(objective, status, results=None, signoff=None, assumptions=None,
         validation=None, inputs_ref=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": TOOL, "version": "1.2.0"}],
        "pdk_binding": "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "shared_artifact",
        "results": results or {}, "qor_metrics": {},
        "signoff_evidence": signoff or {}, "margin": {"method": "seeded_crv"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "deterministic seeded CRV"},
    }
    if error:
        env["error"] = error
    return env


def _normalize_constraint_spec(spec, context):
    if isinstance(spec, dict):
        return dict(spec)
    if isinstance(spec, list):
        return {"values": list(spec)}
    raise ValueError(f"{context} must be an object or a list shorthand")


def _normalize_constraints(constraints):
    if not isinstance(constraints, dict):
        raise ValueError("constraints must be an object")
    return {
        field: _normalize_constraint_spec(spec, f"constraint '{field}'")
        for field, spec in constraints.items()
    }


def _normalize_blocks(blocks):
    if blocks is None:
        return []
    if not isinstance(blocks, list):
        raise ValueError("constraint_blocks must be an array")
    normalized = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ValueError(f"constraint_blocks[{index}] must be an object")
        item = dict(block)
        for side in ("if", "then"):
            conditions = item.get(side, {})
            if not isinstance(conditions, dict):
                raise ValueError(f"constraint_blocks[{index}].{side} must be an object")
            item[side] = {
                field: _normalize_constraint_spec(
                    spec, f"constraint_blocks[{index}].{side}.{field}"
                ) if isinstance(spec, (dict, list)) else spec
                for field, spec in conditions.items()
            }
        # A BLOCK THAT CONSTRAINS NOTHING IS A TYPO, NOT A CONSTRAINT.
        # `item.get(side, {})` defaults to an empty dict, and `all(...)` over an
        # empty dict is True -- so a block written as {"iff": ..., "than": ...}
        # (or simply {}) silently constrained nothing and never complained. The
        # caller believes a restriction is in force and it is not, which is the
        # empty-reads-as-satisfied failure one level below the parameter surface.
        if not item.get("if") and not item.get("then"):
            raise ValueError(
                f"constraint_blocks[{index}] constrains nothing: it has neither a "
                "non-empty 'if' nor a non-empty 'then'. Check for a misspelled key "
                "-- a block that matches nothing is silently ignored, so it is "
                "rejected here rather than accepted as a no-op")
        normalized.append(item)
    return normalized


def _check_constraints(constraints):
    for field, spec in constraints.items():
        if "min" in spec and "max" in spec and spec["min"] > spec["max"]:
            return f"field '{field}': min ({spec['min']}) > max ({spec['max']})"
        if "values" in spec:
            w = spec.get("weights")
            if w and len(w) != len(spec["values"]):
                return f"field '{field}': weights length != values length"
        # A FIELD WITH NO DECLARED DOMAIN CANNOT BE SAMPLED.
        # `_sample` falls through to `txn[field] = None` for such a field, so the
        # emitted stimulus carried a literal null for a signal the caller thought
        # they had specified -- and the run still reported pass.
        if "values" not in spec and "min" not in spec and "max" not in spec:
            return (f"field '{field}': no domain declared (needs `values`, or "
                    "`min`+`max`); an undeclared field samples as null")
    return None


# --------------------------------------------------------------------------
# Constraint conformance
#
# THREE INDEPENDENT PATHS used to emit stimulus that violated the caller's own
# constraints, each with verdict "pass":
#   1. the bounded rejection loop appended the last STILL-REJECTED transaction
#      when it ran out of tries;
#   2. a soft constraint overwrote a field AFTER sampling, with no re-check
#      against that field's declared range (a field declared 0..9 emitted 9999);
#   3. a field with no declared domain sampled as literal null.
# Rather than patch each path, every transaction now passes ONE exit gate before
# it can be emitted. A generator that emits stimulus violating the stated
# constraints is worse than one that emits none: the DUT is exercised with
# illegal input, and either it misbehaves (a phantom bug that costs a debug
# session) or it tolerates it (false confidence, and coverage credited to bins
# legal stimulus never reached).
# --------------------------------------------------------------------------

def _value_in_domain(value, spec):
    """True when `value` satisfies the field's declared domain."""
    if not isinstance(spec, dict):
        return value == spec
    if "values" in spec:
        return value in spec["values"]
    lo, hi = spec.get("min"), spec.get("max")
    if lo is None and hi is None:
        return True
    try:
        return (lo is None or value >= lo) and (hi is None or value <= hi)
    except TypeError:
        # A None (unsampled) value against a numeric bound. Not comparable, and
        # certainly not conformant.
        return False


def _txn_violations(txn, constraints, blocks):
    """Every way a sampled transaction fails the caller's constraint set.

    THE SINGLE EXIT GATE. Checked immediately before emission, after soft
    constraints and every other post-processing step, so nothing that mutates a
    transaction can bypass it.
    """
    out = []
    for field, spec in constraints.items():
        if field not in txn:
            out.append({"kind": "missing_field", "field": field})
        elif not _value_in_domain(txn[field], spec):
            out.append({"kind": "field_domain", "field": field,
                        "value": txn[field], "declared": spec})
    if blocks and not _block_ok(txn, blocks):
        out.append({"kind": "relational_block"})
    return out


def _domain_descriptor(spec):
    """Simple domain descriptor, or None when the shape is not analyzable."""
    if not isinstance(spec, dict):
        return ("set", [spec])
    if "values" in spec:
        return ("set", list(spec["values"]))
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None or hi is not None:
        return ("range", (lo, hi))
    return None


def _provably_disjoint(a, b):
    """True ONLY when two domains provably cannot overlap.

    Deliberately conservative: anything it cannot decide returns False. A false
    positive here would reject a satisfiable constraint set, which is worse than
    letting the runtime gate catch it.
    """
    if a is None or b is None:
        return False
    ka, va = a
    kb, vb = b
    try:
        if ka == "set" and kb == "set":
            return not (set(map(repr, va)) & set(map(repr, vb)))
        if ka == "set" and kb == "range":
            lo, hi = vb
            return not any((lo is None or x >= lo) and (hi is None or x <= hi)
                           for x in va)
        if ka == "range" and kb == "set":
            return _provably_disjoint(b, a)
        if ka == "range" and kb == "range":
            alo, ahi = va
            blo, bhi = vb
            if ahi is not None and blo is not None and ahi < blo:
                return True
            if bhi is not None and alo is not None and bhi < alo:
                return True
            return False
    except TypeError:
        return False
    return False


def _check_blocks(constraints, blocks):
    """Static screen for blocks that contradict, or can never fire.

    Catches the common contradiction BEFORE burning the whole sampling budget,
    and with an explanation instead of a silent shortfall. Vacuous blocks are
    reported too: a block whose antecedent can never hold constrains nothing,
    the same way a property that cannot fail proves nothing.
    """
    contradictions, vacuous = [], []
    for index, blk in enumerate(blocks):
        for field, cond in (blk.get("then") or {}).items():
            dom = constraints.get(field)
            if dom is None:
                continue
            if _provably_disjoint(_domain_descriptor(dom),
                                  _domain_descriptor(cond)):
                contradictions.append({
                    "block": index, "field": field, "required": cond,
                    "declared_domain": dom,
                    "why": ("the block requires '%s' to take a value its own "
                            "declared domain cannot produce, so no sample can "
                            "ever satisfy this block" % field)})
        for field, cond in (blk.get("if") or {}).items():
            dom = constraints.get(field)
            if dom is None:
                continue
            if _provably_disjoint(_domain_descriptor(dom),
                                  _domain_descriptor(cond)):
                vacuous.append({
                    "block": index, "field": field, "antecedent": cond,
                    "declared_domain": dom,
                    "why": ("the antecedent can never hold, so this block never "
                            "fires and constrains nothing")})
    return contradictions, vacuous


def _check_supplied_values(constraints, dists, soft):
    """Values supplied OUTSIDE the field's declared domain are a caller error.

    A soft constraint used to overwrite a field after sampling with no re-check,
    so a field declared 0..9 could emit 9999 and pass. Caught statically here so
    the message names the contradiction rather than reporting a shortfall.
    """
    problems = []
    for field, dist in (dists or {}).items():
        spec = constraints.get(field)
        if spec is None:
            continue
        bad = [v for v in dist if not _value_in_domain(v, spec)]
        if bad:
            problems.append({"source": "value_distributions", "field": field,
                             "values": bad, "declared_domain": spec})
    for field, pref in (soft or {}).items():
        spec = constraints.get(field)
        if spec is None or not isinstance(pref, dict) or "value" not in pref:
            continue
        if not _value_in_domain(pref["value"], spec):
            problems.append({"source": "soft_constraints", "field": field,
                             "values": [pref["value"]], "declared_domain": spec})
    return problems


def _sample(constraints, rng, dists=None, randc_state=None, soft=None):
    dists = dists or {}
    soft = soft or {}
    txn = {}
    for field, spec in constraints.items():
        if field in dists:
            # weighted value distribution: {value: weight}
            vals = list(dists[field].keys())
            wts = [dists[field][v] for v in vals]
            txn[field] = rng.choices(vals, weights=wts)[0]
        elif randc_state is not None and field in randc_state:
            # cyclic (randc): draw without replacement until the pool empties,
            # then reshuffle — every value appears once per cycle.
            pool = randc_state[field]
            if not pool:
                base = spec.get("values") or list(
                    range(int(spec.get("min", 0)), int(spec.get("max", 0)) + 1))
                pool = list(base)
                rng.shuffle(pool)
            txn[field] = pool.pop()
            randc_state[field] = pool
        elif "values" in spec:
            txn[field] = rng.choices(spec["values"], weights=spec.get("weights"))[0]
        elif "min" in spec and "max" in spec:
            txn[field] = rng.randint(int(spec["min"]), int(spec["max"]))
        else:
            txn[field] = None
    # Soft constraints: with the given probability, nudge a field to a preferred
    # value (relaxable — does not hard-fail generation).
    for field, pref in soft.items():
        if field in txn and rng.random() < float(pref.get("probability", 0.9)):
            txn[field] = pref.get("value", txn[field])
    return txn


def _block_ok(txn, blocks):
    """Evaluate simple relational constraint blocks against a sample.
    Each block: {"if": {field: value|{min,max}}, "then": {field: value|{min,max}|{values:[...]}}}.
    Returns True if all blocks whose antecedent holds also satisfy the consequent."""
    def _match(val, cond):
        if isinstance(cond, dict):
            if "values" in cond:
                return val in cond["values"]
            lo, hi = cond.get("min"), cond.get("max")
            return (lo is None or val >= lo) and (hi is None or val <= hi)
        return val == cond
    for blk in blocks:
        ante = blk.get("if", {})
        if all(f in txn and _match(txn[f], c) for f, c in ante.items()):
            cons = blk.get("then", {})
            if not all(f in txn and _match(txn[f], c) for f, c in cons.items()):
                return False
    return True


def _generate(params, coverage_directed=False):
    # Fail closed on a missing design/constraint binding: never fabricate stimulus
    # for an unspecified DUT or an empty constraint model (adversarial red-team gate).
    dut_top = params.get("dut_top")
    if not dut_top:
        return _cde(objective="generate stimulus", status="failed",
                    error="missing required 'dut_top': no DUT is bound, so there is "
                          "nothing to generate stimulus for; refusing to fabricate output",
                    validation={"verdict": "fail"})
    constraints = params.get("constraints", {})
    if not isinstance(constraints, dict) or not constraints:
        return _cde(objective="generate stimulus", status="failed",
                    error="missing required 'constraints': a non-empty constraint "
                          "model is required for constrained-random generation",
                    validation={"verdict": "fail"})
    try:
        constraints = _normalize_constraints(constraints)
        blocks = _normalize_blocks(params.get("constraint_blocks"))
    except ValueError as exc:
        return _cde(objective="generate stimulus", status="failed",
                    error="malformed constraints: " + str(exc),
                    validation={"verdict": "fail"})
    err = _check_constraints(constraints)
    if err:
        return _cde(objective="generate stimulus", status="failed",
                    error="unsolvable constraints: " + err, validation={"verdict": "fail"})

    # --- STATIC CONTRADICTION SCREEN (fail fast, with an explanation) --------
    _contradictions, _vacuous = _check_blocks(constraints, blocks)
    _bad_values = _check_supplied_values(constraints, params.get("value_distributions"),
                                         params.get("soft_constraints"))
    if _contradictions or _bad_values:
        return _cde(
            objective="generate stimulus", status="failed",
            error=("the supplied constraint set is self-contradictory, so no "
                   "conforming stimulus exists; nothing was emitted"),
            results={"tests": {
                "value": 0, "unit": "count", "class": "diagnostic",
                "basis": "static_contradiction_screen",
                "note": ("Zero because the constraints cannot be satisfied -- not "
                         "because generation succeeded and produced nothing.")}},
            signoff={"contradictions": _contradictions or None,
                     "values_outside_declared_domain": _bad_values or None,
                     "vacuous_blocks": _vacuous or None},
            validation={"verdict": "fail",
                        "note": ("caught statically, before sampling: a run that "
                                 "sampled anyway would have reported a shortfall "
                                 "without saying why")})

    seeds = params.get("seeds") or [random.randint(1, 2**31)]
    count = int(params.get("count", 100))
    # Advanced (pure-python-honored) constrained-random controls.
    dists = params.get("value_distributions") or {}
    soft = params.get("soft_constraints") or {}
    randc_fields = params.get("randc_fields") or []
    max_tries = int(params.get("max_rejection_tries", 50))
    tests = []
    block_rejections = 0
    dropped = []
    # Declared here rather than relying on the for-loop binding leaking out:
    # the directed-generation block below uses it, and a future empty-seed path
    # would otherwise raise NameError instead of generating nothing.
    randc_state = {f: [] for f in randc_fields} if randc_fields else None
    for seed in seeds:
        rng = random.Random(seed)
        randc_state = {f: [] for f in randc_fields} if randc_fields else None
        for _ in range(count):
            txn = _sample(constraints, rng, dists, randc_state, soft)
            # Honor relational blocks by bounded rejection sampling.
            tries = 0
            while blocks and not _block_ok(txn, blocks) and tries < max_tries:
                txn = _sample(constraints, rng, dists, randc_state, soft)
                tries += 1
                block_rejections += 1
            # *** THE EXIT GATE ***
            # This `append` used to sit here unconditionally, so an exhausted
            # rejection loop emitted its last STILL-REJECTED transaction. Every
            # transaction is now re-checked against the FULL constraint set --
            # field domains as well as relational blocks -- and a violating one
            # is DROPPED, never emitted. The shortfall is reported and gates.
            violations = _txn_violations(txn, constraints, blocks)
            if violations:
                if len(dropped) < 20:
                    dropped.append({"seed": seed, "stimulus": txn,
                                    "violations": violations, "tries": tries})
                continue
            tests.append({"seed": seed, "stimulus": txn})
    requested = len(seeds) * count
    holes = params.get("holes", [])
    hole_map = []
    if coverage_directed and holes:
        # DIRECTED GENERATION, not a label. This block previously emitted a
        # STRING -- "targeted_by: directed bias on <field list>" -- next to a
        # stimulus set that was sampled identically whether or not a hole was
        # supplied. The coverage hole was therefore no more likely to be hit
        # after "targeting" it than before, while the envelope reported it as
        # addressed.
        #
        # Each hole names a field and the value (or range) that was never hit.
        # For each one, transactions are emitted that CONTAIN that value, and
        # every such transaction is re-checked against the full constraint set
        # exactly like a random sample -- a directed test that violates the
        # constraints is dropped, not smuggled in.
        for h in holes:
            spec = h if isinstance(h, dict) else {"field": h}
            field = spec.get("field") or spec.get("name")
            if not field:
                hole_map.append({"hole": h, "targeted": False,
                                 "reason": "hole names no field, so no directed "
                                           "stimulus can be aimed at it"})
                continue
            if field not in constraints:
                hole_map.append({"hole": h, "field": field, "targeted": False,
                                 "reason": f"'{field}' is not a constrained "
                                           f"field, so its domain is unknown"})
                continue
            wanted = spec.get("values")
            if wanted is None and "value" in spec:
                wanted = [spec["value"]]
            if wanted is None:
                lo, hi = spec.get("min"), spec.get("max")
                if lo is not None and hi is not None:
                    try:
                        wanted = sorted({int(lo), int(hi),
                                         int((int(lo) + int(hi)) // 2)})
                    except (TypeError, ValueError):
                        wanted = None
            if not wanted:
                hole_map.append({"hole": h, "field": field, "targeted": False,
                                 "reason": "hole declares no value, values or "
                                           "min/max, so there is nothing to aim at"})
                continue
            rng = random.Random(seeds[0])
            per_value = max(1, int(spec.get("count", 4)))
            emitted, rejected = 0, 0
            for val in wanted:
                for _ in range(per_value):
                    txn = _sample(constraints, rng, dists, randc_state, soft)
                    txn[field] = val          # force the uncovered value
                    tries = 0
                    while blocks and not _block_ok(txn, blocks) and tries < max_tries:
                        txn = _sample(constraints, rng, dists, randc_state, soft)
                        txn[field] = val
                        tries += 1
                    if _txn_violations(txn, constraints, blocks):
                        rejected += 1
                        continue
                    tests.append({"seed": seeds[0], "stimulus": txn,
                                  "directed_at": {"field": field, "value": val}})
                    emitted += 1
            hole_map.append({
                "hole": h, "field": field, "values_targeted": list(wanted),
                "targeted": emitted > 0,
                "directed_transactions": emitted,
                "rejected_by_constraints": rejected,
                "reason": (None if emitted else
                           "every directed transaction violated the constraint "
                           "set, so this hole cannot be reached under these "
                           "constraints"),
            })
    shortfall = requested - len([t for t in tests if "directed_at" not in t])
    open(os.path.join(_OUTPUT_DIR, "stimulus.json"), "w").write(json.dumps(tests, indent=2))
    # EVIDENCE, NOT A LITERAL. `constraints_solvable` was hardcoded True and
    # could never be False. It is now witness-based, and it carries the same
    # asymmetry a bounded search always has: emitting N conforming transactions
    # PROVES the set is satisfiable (each one is a witness), but failing to find
    # one within the try budget does NOT prove it unsatisfiable -- a narrow but
    # legal constraint exhausts the same way. So the failing case is reported as
    # UNKNOWN, never as "proven unsatisfiable".
    if tests and not shortfall:
        _solvable, _solvable_note = True, (
            "demonstrated: every one of the %d requested transactions satisfies "
            "the full constraint set, and each is a witness" % requested)
    elif tests:
        _solvable, _solvable_note = None, (
            "partially demonstrated: %d of %d transactions conform. The %d "
            "shortfall was not found within %d rejection tries each, which does "
            "NOT prove the constraints unsatisfiable -- a narrow but legal "
            "constraint exhausts the budget the same way."
            % (len(tests), requested, shortfall, max_tries))
    else:
        _solvable, _solvable_note = None, (
            "NOT demonstrated: no conforming transaction was found in %d tries "
            "per sample. Unknown, not disproven." % max_tries)

    if shortfall:
        _verdict = "fail"
        _vnote = ("%d of %d requested transactions could not be generated within "
                  "the constraints and were DROPPED, not emitted. Emitting them "
                  "would have exercised the DUT with illegal input."
                  % (shortfall, requested))
    else:
        _verdict = "pass"
        _vnote = ("all %d requested transactions conform to the full constraint "
                  "set" % requested)

    return _cde(
        objective="generate " + ("coverage-directed" if coverage_directed else "constrained-random")
        + f" stimulus for {params.get('dut_top')}",
        status="completed" if not shortfall else "failed",
        results={
            "tests": {
                "value": len(tests), "unit": "count", "class": "diagnostic",
                "basis": "conformance_checked_emission",
                "note": ("Transactions EMITTED. Every one has been re-checked "
                         "against the field domains and relational blocks; a "
                         "violating sample is dropped rather than emitted.")},
            "stimulus_shortfall": {
                "value": shortfall, "unit": "count",
                "class": "gating", "closes_at": "== 0",
                "basis": "conformance_checked_emission",
                "note": ("Requested minus emitted. Non-zero means the constraint "
                         "set could not be satisfied within the try budget. "
                         "GATING because a test plan that silently generated "
                         "fewer transactions than it asked for has not run the "
                         "stimulus anyone believes it ran.")}},
        signoff={"seed_ledger": seeds,
                 "constraints_solvable": _solvable,
                 "constraints_solvable_note": _solvable_note,
                 "requested": requested, "emitted": len(tests),
                 "dropped_sample_examples": dropped or None,
                 "vacuous_blocks": _vacuous or None,
                 "targeted_holes": hole_map, "file": "stimulus.json",
                 "distributions_applied": sorted(dists.keys()),
                 "randc_fields": randc_fields,
                 "soft_constraints": sorted(soft.keys()),
                 "constraint_blocks": len(blocks),
                 "max_rejection_tries": max_tries,
                 "block_rejections": block_rejections},
        inputs_ref={"dut_top": params.get("dut_top"), "constraints": constraints},
        assumptions=["directed value-set / range / distribution / randc / soft "
                     "constraints and simple relational blocks (rejection-sampled); "
                     "higher-order constraints require an external SMT solver",
                     "every emitted transaction is re-checked against the full "
                     "constraint set immediately before emission; a violating "
                     "sample is dropped and counted, never emitted",
                     "satisfiability is witness-based: conforming samples prove "
                     "the set satisfiable, but exhausting the try budget does not "
                     "prove it unsatisfiable"],
        validation={"verdict": _verdict, "note": _vnote},
    )


def _directed(params):
    tests = params.get("tests", [])
    if not tests:
        return _cde(objective="directed tests", status="failed",
                    error="no directed 'tests' supplied", validation={"verdict": "fail"})
    open(os.path.join(_OUTPUT_DIR, "stimulus.json"), "w").write(json.dumps(tests, indent=2))
    unmapped = [i for i, t in enumerate(tests) if not t.get("vplan_item")]
    return _cde(objective="directed test generation", status="completed",
                results={"tests": {"value": len(tests), "unit": "count"}},
                signoff={"file": "stimulus.json", "unmapped_tests": unmapped},
                validation={"verdict": "pass" if not unmapped else "pass_with_caveats"})


def dispatch(params):
    s = params.get("scenario")
    if s == "constrained_random":
        return _generate(params, coverage_directed=False)
    if s == "coverage_directed":
        return _generate(params, coverage_directed=True)
    if s == "directed":
        return _directed(params)
    return _cde(objective="stimulus generation", status="failed",
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
